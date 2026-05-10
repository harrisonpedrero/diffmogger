from __future__ import annotations

from .common import *
from .git_safety import head

def manifest_path_for(target: Path, role: str, run_id: str) -> Path:
    return runtime_path(target, "target/automation_queue") / role / run_id / "manifest.json"

def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def write_manifest(path: Path, manifest: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def resolve_patch_path(target: Path, manifest: dict[str, Any]) -> Path:
    patch = Path(str(manifest.get("patch_path") or ""))
    if patch.is_absolute():
        return patch
    return target / patch

def resolve_runtime_state_actions_path(target: Path, manifest: dict[str, Any]) -> Path | None:
    raw = str(manifest.get("runtime_state_actions_path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    return target / path

def parse_created_at(manifest: dict[str, Any], fallback: float) -> float:
    raw = str(manifest.get("created_at") or "")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback

def load_queued_manifests(target: Path) -> list[tuple[Path, dict[str, Any]]]:
    queue_root = runtime_path(target, "target/automation_queue")
    items: list[tuple[Path, dict[str, Any]]] = []
    for role in QUEUE_ROLES:
        role_root = queue_root / role
        if not role_root.exists():
            continue
        for path in role_root.glob("*/manifest.json"):
            try:
                manifest = read_manifest(path)
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("status") == "queued":
                items.append((path, manifest))
    items.sort(key=lambda item: (parse_created_at(item[1], item[0].stat().st_mtime), str(item[0])))
    return items

def all_role_manifests(target: Path) -> list[tuple[Path, dict[str, Any]]]:
    queue_root = runtime_path(target, "target/automation_queue")
    items: list[tuple[Path, dict[str, Any]]] = []
    for role in ALL_ROLES:
        role_root = queue_root / role
        if not role_root.exists():
            continue
        for path in role_root.glob("*/manifest.json"):
            try:
                items.append((path, read_manifest(path)))
            except (OSError, json.JSONDecodeError):
                continue
    return items

def manifest_list(manifests: list[dict[str, Any]] | dict[str, Any] | None) -> list[dict[str, Any]]:
    if manifests is None:
        return []
    if isinstance(manifests, dict):
        return [manifests]
    return [item for item in manifests if isinstance(item, dict)]

def create_integrator_manifest(
    target: Path,
    *,
    run_id: str,
    status: str,
    head_before: str | None,
    checkpoint_commit: str | None,
    summary: str,
    dry_run: bool,
) -> None:
    path = manifest_path_for(target, "integrator", run_id)
    manifest = {
        "role": "integrator",
        "run_id": run_id,
        "base_commit": head_before or "",
        "head_before_integration": head_before,
        "status": status,
        "deferral_reason": None if status == "applied" else "other",
        "deferral_detail": "" if status == "applied" else summary,
        "patch_path": "",
        "changed_files": [],
        "checks_run": [],
        "summary": summary,
        "created_at": utc_now().isoformat(timespec="seconds"),
        "integrated_at": utc_now().isoformat(timespec="seconds"),
        "checkpoint_commit": checkpoint_commit,
        "accepted_commit": head(target) if status == "applied" and not dry_run else None,
    }
    write_manifest(path, manifest, dry_run=dry_run)
