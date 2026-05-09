from __future__ import annotations

from .common import *
from .git_safety import git
from .queue import read_manifest

def cleanup_artifacts(target: Path, *, dry_run: bool) -> list[str]:
    now = time.time()
    seven_days = 7 * 24 * 60 * 60
    thirty_days = 30 * 24 * 60 * 60
    queue_root = runtime_path(target, "target/automation_queue")
    worktree_root = runtime_path(target, "target/automation_worktrees")
    summaries: list[str] = []
    deleted_queue = 0
    deleted_worktrees = 0
    deleted_logs = 0

    for role in QUEUE_ROLES:
        role_root = queue_root / role
        if not role_root.exists():
            continue
        run_dirs = [path for path in role_root.iterdir() if path.is_dir()]
        manifests: list[tuple[Path, dict[str, Any], float]] = []
        for run_dir in run_dirs:
            manifest_path = run_dir / "manifest.json"
            if manifest_path.exists():
                try:
                    manifest = read_manifest(manifest_path)
                except (OSError, json.JSONDecodeError):
                    manifest = {}
            else:
                manifest = {}
            manifests.append((run_dir, manifest, run_dir.stat().st_mtime))
        successful = [
            item for item in manifests if item[1].get("status") == "applied"
        ]
        successful.sort(key=lambda item: item[2], reverse=True)
        keep_success = {item[0].name for item in successful[:5]}
        keep_run_ids: set[str] = set(keep_success)
        for run_dir, manifest, mtime in manifests:
            status = manifest.get("status")
            recent = now - mtime < seven_days
            keep = recent or status in {"queued", "deferred"} or run_dir.name in keep_success
            if keep:
                keep_run_ids.add(run_dir.name)
                continue
            if not dry_run:
                shutil.rmtree(run_dir)
            deleted_queue += 1

        wt_role_root = worktree_root / role
        if wt_role_root.exists():
            for worktree in wt_role_root.iterdir():
                if not worktree.is_dir():
                    continue
                recent = now - worktree.stat().st_mtime < seven_days
                if recent or worktree.name in keep_run_ids:
                    continue
                if not dry_run:
                    result = git(target, "worktree", "remove", "--force", str(worktree))
                    if result.returncode != 0 and worktree.exists():
                        shutil.rmtree(worktree)
                deleted_worktrees += 1

    log_root = runtime_path(target, "target/automation_logs")
    if log_root.exists():
        for log_path in log_root.glob("*.log"):
            if now - log_path.stat().st_mtime < thirty_days:
                continue
            if not dry_run:
                log_path.unlink(missing_ok=True)
            deleted_logs += 1

    if not dry_run:
        git(target, "worktree", "prune")
    if deleted_queue:
        summaries.append(f"deleted {deleted_queue} old applied/failed queue run dirs")
    if deleted_worktrees:
        summaries.append(f"deleted {deleted_worktrees} old role worktrees")
    if deleted_logs:
        summaries.append(f"deleted {deleted_logs} role logs older than 30 days")
    if not summaries:
        summaries.append("retention cleanup found no stale artifacts")
    return summaries
