#!/usr/bin/env python3
"""Integrate queued multi-role automation patches in a local target repo."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


QUEUE_ROLES = ("planner", "builder", "hardener")
ALL_ROLES = (*QUEUE_ROLES, "integrator")
DEFERRAL_REASONS = {
    "staleness",
    "conflict",
    "verification_failure",
    "verification_environment_failure",
    "guardrail_violation",
    "other",
}
RUNTIME_STATE_WHITELIST = {
    ".agentic/automation_prompt.md",
    ".agentic/verification_commands.txt",
    ".agentic/roles/planner.md",
    ".agentic/roles/builder.md",
    ".agentic/roles/hardener.md",
    ".agentic/roles/integrator.md",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "target/automation_signals.json",
}
RUNTIME_STATE_ALLOWED_PREFIXES = (".agentic/", "docs/")
RUNTIME_STATE_DENY_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "automation_queue",
    "automation_worktrees",
    "automation_logs",
    "automation_venvs",
}
RUNTIME_STATE_DENY_NAMES = {".DS_Store", "codex_automation.lock", "automation_conveyor.lock"}
RUNTIME_STATE_DENY_SUFFIXES = (
    ".7z",
    ".db",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".lock",
    ".log",
    ".pdf",
    ".png",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".tar",
    ".tgz",
    ".zip",
)
RUNTIME_STATE_MAX_BYTES = 1024 * 1024
RUNTIME_STATE_BLOCKING_STATUSES = {"blocked", "conflict", "error", "rejected"}
RUNTIME_STATE_VOLATILE_PATHS = {"target/automation_signals.json"}
PROGRESS_SECTIONS = [
    "Project State At Last Integration",
    "Cumulative Metrics",
    "Recent Activity Log",
    "Historical Summary",
    "Deferred-Patch Backlog",
    "Architectural Decisions",
    "Role Health",
]


@dataclass
class LockHandle:
    path: Path
    script_managed: bool


@dataclass
class VerificationResult:
    ok: bool
    checks_run: list[str]
    detail: str
    reason: str = ""


@dataclass
class VerificationRepair:
    attempted: bool
    detail: str
    final_command: str | None = None
    final_result: subprocess.CompletedProcess[str] | None = None


def load_environment_repair_module() -> Any | None:
    module_path = Path(__file__).with_name("repair_environment.py")
    if not module_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("diffmogger_repair_environment", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_id() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = False,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def git(target: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=target, check=check)


def require_git_repo(target: Path) -> None:
    result = git(target, "rev-parse", "--is-inside-work-tree")
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise SystemExit(f"Multi-role integration requires an initialized git repo: {target}")


def ensure_local_only(target: Path) -> None:
    remotes = git(target, "remote", "-v").stdout.strip()
    if remotes and os.environ.get("MULTI_ROLE_ALLOW_REMOTES") != "1":
        print(
            "Multi-role automation is local-only and refuses to run with configured git remotes.",
            file=sys.stderr,
        )
        print(remotes, file=sys.stderr)
        print(
            "Set MULTI_ROLE_ALLOW_REMOTES=1 only if you intentionally allow local automation in a repo with remotes.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def scan_push_hooks(target: Path) -> None:
    hooks_result = git(target, "rev-parse", "--git-path", "hooks")
    hooks_text = hooks_result.stdout.strip()
    hooks_dir = (target / hooks_text).resolve() if hooks_text else target / ".git" / "hooks"
    if not hooks_dir.exists():
        return
    offenders: list[Path] = []
    for hook in hooks_dir.iterdir():
        if hook.name.endswith(".sample"):
            continue
        if not hook.is_file() or not os.access(hook, os.X_OK):
            continue
        try:
            text = hook.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "git push" in text:
            offenders.append(hook)
    if offenders:
        print("Integrator refuses to run because executable git hooks contain `git push`:", file=sys.stderr)
        for hook in offenders:
            print(f"- {hook}", file=sys.stderr)
        raise SystemExit(2)


def update_info_exclude(target: Path, *, dry_run: bool) -> None:
    exclude = target / ".git" / "info" / "exclude"
    patterns = [
        "/target/codex_automation.lock",
        "/target/automation_venvs/",
        "/target/automation_queue/",
        "/target/automation_worktrees/",
        "/target/automation_logs/",
    ]
    if dry_run:
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = existing.splitlines()
    changed = False
    for pattern in patterns:
        if pattern not in lines:
            lines.append(pattern)
            changed = True
    if changed:
        exclude.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def acquire_lock(target: Path, run_id: str, *, dry_run: bool) -> LockHandle | None:
    if dry_run:
        return None
    lock_path = target / "target" / "codex_automation.lock"
    acquire = target / "scripts" / "acquire_codex_lock.sh"
    env = os.environ.copy()
    env.update(
        {
            "CODEX_LOCK_PATH": str(lock_path),
            "CODEX_RUN_ID": run_id,
            "CODEX_LOCK_OWNER_PID": str(os.getpid()),
        }
    )
    if acquire.exists():
        result = run(["bash", str(acquire), "multi-role integrator"], cwd=target, env=env)
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
            raise SystemExit(1)
        return LockHandle(path=lock_path, script_managed=True)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        print(f"Active Codex automation lock exists; refusing to acquire: {lock_path}", file=sys.stderr)
        raise SystemExit(1)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"pid={os.getpid()}\nrun_id={run_id}\ncreated_at={utc_now().isoformat(timespec='seconds')}\n")
    return LockHandle(path=lock_path, script_managed=False)


def release_lock(target: Path, run_id: str, lock: LockHandle | None) -> None:
    if lock is None:
        return
    release = target / "scripts" / "release_codex_lock.sh"
    env = os.environ.copy()
    env.update(
        {
            "CODEX_LOCK_PATH": str(lock.path),
            "CODEX_RUN_ID": run_id,
            "CODEX_LOCK_OWNER_PID": str(os.getpid()),
        }
    )
    if lock.script_managed and release.exists():
        result = run(["bash", str(release)], cwd=target, env=env)
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
        return
    try:
        lock.path.unlink()
    except FileNotFoundError:
        pass


def manifest_path_for(target: Path, role: str, run_id: str) -> Path:
    return target / "target" / "automation_queue" / role / run_id / "manifest.json"


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(path: Path, manifest: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file() or path.is_symlink():
        return None
    return sha256_bytes(path.read_bytes())


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


def runtime_state_path_safe(rel_text: str) -> tuple[bool, str]:
    rel = Path(rel_text)
    parts = rel.parts
    if any(part in {"", ".", ".."} for part in parts):
        return False, "runtime-state path may not contain empty, '.', or '..' segments"
    lowered_parts = {part.lower() for part in parts}
    if lowered_parts & {"secrets", ".ssh"}:
        return False, "runtime-state path may not reference secret-bearing paths"
    if any(part in RUNTIME_STATE_DENY_PARTS for part in parts):
        return False, "runtime-state path references denied runtime artifacts"
    name = rel.name
    if name == ".env" or name.startswith(".env."):
        return False, "runtime-state path may not reference environment files"
    if name in RUNTIME_STATE_DENY_NAMES or name.endswith(RUNTIME_STATE_DENY_SUFFIXES):
        return False, "runtime-state path references a denied file type"
    return True, ""


def runtime_state_path_is_ignored(target: Path, rel_text: str) -> bool:
    result = git(target, "check-ignore", "-q", "--", rel_text)
    return result.returncode == 0


def runtime_state_path_allowed(target: Path, rel_text: str) -> tuple[bool, str]:
    ok, detail = runtime_state_path_safe(rel_text)
    if not ok:
        return False, detail
    if rel_text in RUNTIME_STATE_WHITELIST:
        return True, ""
    if not rel_text.startswith(RUNTIME_STATE_ALLOWED_PREFIXES):
        return False, "runtime-state path is outside ignored automation state roots"
    if not runtime_state_path_is_ignored(target, rel_text):
        return False, "runtime-state path is not git-ignored in the target checkout"
    return True, ""


def normalize_runtime_state_path(target: Path, raw: Any) -> tuple[str | None, str]:
    if not isinstance(raw, str) or not raw.strip():
        return None, "runtime-state path is missing or not a string"
    if "\x00" in raw:
        return None, "runtime-state path contains a NUL byte"
    rel = Path(raw)
    if rel.is_absolute():
        return None, "runtime-state path must be relative"
    rel_text = rel.as_posix()
    allowed, detail = runtime_state_path_allowed(target, rel_text)
    if not allowed:
        return None, detail
    return rel_text, ""


def parent_has_symlink(target: Path, rel_path: str) -> bool:
    current = target
    for part in Path(rel_path).parts[:-1]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def runtime_state_status_from_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "none"
    statuses = {str(item.get("status") or "") for item in results}
    if statuses & RUNTIME_STATE_BLOCKING_STATUSES:
        return "deferred"
    if "would_apply" in statuses:
        return "would_apply"
    if "applied" in statuses:
        return "applied"
    if statuses == {"already_applied"}:
        return "already_applied"
    return "applied"


def set_runtime_state_results(manifest: dict[str, Any], results: list[dict[str, Any]]) -> None:
    manifest["runtime_state_results"] = results
    manifest["runtime_state_status"] = runtime_state_status_from_results(results)


def runtime_state_has_blocking_results(manifest: dict[str, Any]) -> bool:
    return str(manifest.get("runtime_state_status") or "") == "deferred"


def runtime_state_deferral_reason(manifest: dict[str, Any]) -> str:
    results = manifest.get("runtime_state_results") or []
    statuses = {str(item.get("status") or "") for item in results if isinstance(item, dict)}
    if "rejected" in statuses:
        return "guardrail_violation"
    if "conflict" in statuses:
        return "conflict"
    return "other"


def runtime_state_deferral_detail(manifest: dict[str, Any]) -> str:
    details: list[str] = []
    for item in manifest.get("runtime_state_results") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown")
        if status not in RUNTIME_STATE_BLOCKING_STATUSES:
            continue
        path = str(item.get("path") or "<unknown>")
        detail = str(item.get("detail") or status)
        details.append(f"{path}: {status}: {detail}")
    return "; ".join(details) or "runtime-state action was deferred"


def apply_runtime_state_actions(target: Path, manifest: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    actions_path = resolve_runtime_state_actions_path(target, manifest)
    if actions_path is None:
        set_runtime_state_results(manifest, [])
        return []
    try:
        actions_path.resolve(strict=False).relative_to(target.resolve())
    except ValueError:
        results = [
            {
                "action": "load_actions",
                "path": str(actions_path),
                "status": "rejected",
                "detail": "runtime_state_actions_path escapes target checkout",
            }
        ]
        set_runtime_state_results(manifest, results)
        return results
    if not actions_path.exists():
        results = [
            {
                "action": "load_actions",
                "path": str(actions_path),
                "status": "error",
                "detail": "runtime_state_actions_path does not exist",
            }
        ]
        set_runtime_state_results(manifest, results)
        return results
    try:
        payload = json.loads(actions_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        results = [
            {
                "action": "load_actions",
                "path": str(actions_path),
                "status": "error",
                "detail": f"could not load runtime-state actions: {exc}",
            }
        ]
        set_runtime_state_results(manifest, results)
        return results

    raw_actions = payload.get("actions") if isinstance(payload, dict) else None
    if not isinstance(raw_actions, list) or not raw_actions:
        set_runtime_state_results(manifest, [])
        return []

    target_resolved = target.resolve()
    planned_writes: list[tuple[int, Path, bytes]] = []
    results: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for index, action in enumerate(raw_actions):
        result: dict[str, Any] = {
            "action": "replace_file",
            "path": str(action.get("path") or "") if isinstance(action, dict) else "",
        }
        if not isinstance(action, dict):
            result.update({"status": "rejected", "detail": "runtime-state action must be an object"})
            results.append(result)
            continue
        if action.get("action") != "replace_file":
            result.update({"status": "rejected", "detail": "only replace_file runtime-state actions are supported"})
            results.append(result)
            continue

        rel_path, path_error = normalize_runtime_state_path(target, action.get("path"))
        if rel_path is None:
            result.update({"status": "rejected", "detail": path_error})
            results.append(result)
            continue
        result["path"] = rel_path
        if rel_path in seen_paths:
            result.update({"status": "rejected", "detail": "duplicate runtime-state action for path"})
            results.append(result)
            continue
        seen_paths.add(rel_path)

        content = action.get("content")
        if not isinstance(content, str):
            result.update({"status": "rejected", "detail": "runtime-state content must be UTF-8 text"})
            results.append(result)
            continue
        start_hash = action.get("start_hash")
        end_hash = action.get("end_hash")
        if start_hash is not None and not isinstance(start_hash, str):
            result.update({"status": "rejected", "detail": "start_hash must be a string or null"})
            results.append(result)
            continue
        if not isinstance(end_hash, str):
            result.update({"status": "rejected", "detail": "end_hash must be a string"})
            results.append(result)
            continue
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > RUNTIME_STATE_MAX_BYTES:
            result.update({"status": "rejected", "detail": "runtime-state content exceeds size limit"})
            results.append(result)
            continue
        actual_end_hash = sha256_bytes(content_bytes)
        if actual_end_hash != end_hash:
            result.update(
                {
                    "status": "rejected",
                    "detail": "content hash does not match end_hash",
                    "end_hash": end_hash,
                    "actual_end_hash": actual_end_hash,
                }
            )
            results.append(result)
            continue

        if parent_has_symlink(target, rel_path):
            result.update({"status": "rejected", "detail": "runtime-state parent path crosses a symlink"})
            results.append(result)
            continue
        destination = target / rel_path
        try:
            destination.resolve(strict=False).relative_to(target_resolved)
        except ValueError:
            result.update({"status": "rejected", "detail": "runtime-state destination escapes target checkout"})
            results.append(result)
            continue
        if destination.exists() and (destination.is_symlink() or not destination.is_file()):
            result.update({"status": "rejected", "detail": "runtime-state destination is not a regular file"})
            results.append(result)
            continue

        current_hash = file_sha256(destination)
        result.update({"start_hash": start_hash, "end_hash": end_hash, "current_hash": current_hash})
        if current_hash == end_hash:
            result.update({"status": "already_applied", "detail": "current file already matches desired content"})
            results.append(result)
            continue
        if rel_path in RUNTIME_STATE_VOLATILE_PATHS:
            result.update(
                {
                    "status": "skipped_volatile",
                    "detail": "volatile runtime state is merged separately; not replacing live file",
                }
            )
            results.append(result)
            continue
        if current_hash != start_hash:
            result.update({"status": "conflict", "detail": "current file hash differs from role-start hash"})
            results.append(result)
            continue

        result.update({"status": "would_apply", "detail": "runtime-state file will be replaced"})
        planned_writes.append((index, destination, content_bytes))
        results.append(result)

    if any(str(item.get("status") or "") in RUNTIME_STATE_BLOCKING_STATUSES for item in results):
        for index, item in enumerate(results):
            if item.get("status") == "would_apply":
                item["status"] = "blocked"
                item["detail"] = "not applied because another runtime-state action was deferred"
        set_runtime_state_results(manifest, results)
        return results

    if dry_run:
        set_runtime_state_results(manifest, results)
        return results

    for index, destination, content_bytes in planned_writes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_name(f".{destination.name}.runtime-state.{os.getpid()}.tmp")
        try:
            temp_path.write_bytes(content_bytes)
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)
        results[index]["status"] = "applied"
        results[index]["detail"] = "runtime-state file replaced"

    set_runtime_state_results(manifest, results)
    return results


def parse_created_at(manifest: dict[str, Any], fallback: float) -> float:
    raw = str(manifest.get("created_at") or "")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def load_queued_manifests(target: Path) -> list[tuple[Path, dict[str, Any]]]:
    queue_root = target / "target" / "automation_queue"
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
    queue_root = target / "target" / "automation_queue"
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


def dirty_status(target: Path) -> str:
    return git(target, "status", "--porcelain").stdout.strip()


def checkpoint_dirty_main(target: Path, run_id: str, *, dry_run: bool) -> tuple[str | None, list[str]]:
    status = dirty_status(target)
    if not status:
        return None, []
    dirty_files = [line[3:] if len(line) > 3 else line for line in status.splitlines()]
    if dry_run:
        return "DRY-RUN-CHECKPOINT", dirty_files

    git(target, "add", "-A", check=True)
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Diffmogger Integrator",
            "GIT_AUTHOR_EMAIL": "diffmogger-integrator@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Integrator",
            "GIT_COMMITTER_EMAIL": "diffmogger-integrator@example.invalid",
        }
    )
    message = f"chore(integrator): checkpoint dirty main before {run_id}"
    result = run(["git", "commit", "-m", message], cwd=target, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(1)
    checkpoint = git(target, "rev-parse", "HEAD", check=True).stdout.strip()
    return checkpoint, dirty_files


def head(target: Path) -> str:
    return git(target, "rev-parse", "HEAD", check=True).stdout.strip()


def path_exists_at_ref(target: Path, ref: str, rel_path: str) -> bool:
    result = git(target, "cat-file", "-e", f"{ref}:{rel_path}")
    return result.returncode == 0


def reset_to(target: Path, ref: str, manifests: list[dict[str, Any]], *, dry_run: bool) -> None:
    if dry_run:
        return
    git(target, "reset", "--hard", ref, check=True)
    for manifest in manifests:
        for rel in manifest.get("changed_files") or []:
            if not isinstance(rel, str) or not rel.strip():
                continue
            rel = rel.strip()
            if path_exists_at_ref(target, ref, rel):
                continue
            path = target / rel
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)


def apply_check(target: Path, patch: Path) -> subprocess.CompletedProcess[str]:
    return git(target, "apply", "--check", str(patch))


def apply_patch_file(target: Path, patch: Path, *, dry_run: bool) -> subprocess.CompletedProcess[str]:
    if dry_run:
        return subprocess.CompletedProcess(["git", "apply", str(patch)], 0, "", "")
    return git(target, "apply", str(patch))


def changed_since_base(target: Path, base_commit: str, current_head: str) -> set[str]:
    if not base_commit:
        return set()
    result = git(target, "diff", "--name-only", f"{base_commit}..{current_head}")
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def classify_apply_failure(target: Path, manifest: dict[str, Any], current_head: str, stderr: str) -> tuple[str, str]:
    base_commit = str(manifest.get("base_commit") or "")
    changed_files = {str(item) for item in manifest.get("changed_files") or []}
    if base_commit and base_commit != current_head and changed_files & changed_since_base(target, base_commit, current_head):
        return "staleness", f"Patch base {base_commit} no longer matches HEAD {current_head}; touched files changed since base. {stderr.strip()}"
    return "conflict", stderr.strip() or "git apply --check failed"


def mark_deferred(
    path: Path,
    manifest: dict[str, Any],
    *,
    reason: str,
    detail: str,
    head_before_integration: str,
    checkpoint_commit: str | None,
    checks_run: list[str] | None = None,
    dry_run: bool,
) -> None:
    if reason not in DEFERRAL_REASONS:
        reason = "other"
    update = {
        "status": "deferred",
        "deferral_reason": reason,
        "deferral_detail": detail,
        "head_before_integration": head_before_integration,
        "integrated_at": utc_now().isoformat(timespec="seconds"),
        "checkpoint_commit": checkpoint_commit,
    }
    if checks_run is not None:
        update["checks_run"] = checks_run
    manifest.update(update)
    write_manifest(path, manifest, dry_run=dry_run)


def mark_applied(
    path: Path,
    manifest: dict[str, Any],
    *,
    accepted_commit: str | None,
    head_before_integration: str,
    checkpoint_commit: str | None,
    checks_run: list[str],
    dry_run: bool,
) -> None:
    manifest.update(
        {
            "status": "applied",
            "deferral_reason": None,
            "deferral_detail": "",
            "head_before_integration": head_before_integration,
            "integrated_at": utc_now().isoformat(timespec="seconds"),
            "checkpoint_commit": checkpoint_commit,
            "accepted_commit": accepted_commit,
            "checks_run": checks_run,
        }
    )
    write_manifest(path, manifest, dry_run=dry_run)


def load_verification_commands(target: Path) -> list[str]:
    command_file = target / ".agentic" / "verification_commands.txt"
    if command_file.exists():
        lines = command_file.read_text(encoding="utf-8").splitlines()
    else:
        prompt = target / ".agentic" / "automation_prompt.md"
        if not prompt.exists():
            return []
        text = prompt.read_text(encoding="utf-8", errors="replace")
        marker = re_extract_fenced_block(text, "## Verification")
        lines = marker.splitlines() if marker else []
    commands: list[str] = []
    for raw in lines:
        line = raw.strip()
        line = line.removeprefix("- ").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("add project-specific"):
            continue
        commands.append(line)
    return commands


def re_extract_fenced_block(text: str, heading: str) -> str:
    start = text.find(heading)
    if start == -1:
        return ""
    section = text[start:]
    fence_start = section.find("```")
    if fence_start == -1:
        return ""
    fence_body_start = section.find("\n", fence_start)
    if fence_body_start == -1:
        return ""
    fence_end = section.find("```", fence_body_start + 1)
    if fence_end == -1:
        return ""
    return section[fence_body_start + 1 : fence_end].strip()


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout + "\n" + result.stderr).strip()


def command_uses_pytest(command: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = []
    if "pytest" in command:
        return True
    return any(token == "pytest" for token in tokens)


def missing_pytest_failure(command: str, output: str) -> bool:
    if not command_uses_pytest(command) and "pytest" not in output:
        return False
    lowered = output.lower()
    return any(
        marker in lowered
        for marker in [
            "no module named pytest",
            "no module named 'pytest'",
            "pytest: command not found",
            "pytest: not found",
        ]
    )


def quote_command(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def pytest_args_from_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    if not tokens:
        return []
    if Path(tokens[0]).name == "pytest":
        return tokens[1:]
    for index, token in enumerate(tokens[:-1]):
        if token == "-m" and tokens[index + 1] == "pytest":
            return tokens[index + 2 :]
    return []


def pytest_command_for_python(target: Path, python_path: Path, original_command: str) -> str:
    args = pytest_args_from_command(original_command)
    notifier_dir = target / "services" / "agentic-notifier"
    if not args and notifier_dir.exists() and "agentic-notifier" in python_path.as_posix():
        args = ["services/agentic-notifier"]
    return quote_command([str(python_path), "-m", "pytest", *args])


def python_can_import(python_path: Path, module: str) -> bool:
    result = run([str(python_path), "-c", f"import {module}"], cwd=python_path.parent)
    return result.returncode == 0


def existing_venv_pythons(target: Path) -> list[Path]:
    candidates: list[Path] = [
        target / "services" / "agentic-notifier" / ".venv" / "bin" / "python",
        target / ".venv" / "bin" / "python",
    ]
    services_dir = target / "services"
    if services_dir.exists():
        candidates.extend(sorted(services_dir.glob("*/.venv/bin/python")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(candidate)
    return unique


def git_ignores_path(target: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(target)
    except ValueError:
        return False
    result = git(target, "check-ignore", "-q", "--", rel.as_posix())
    return result.returncode == 0


def requirements_for_pytest_repair(target: Path) -> list[tuple[Path, Path]]:
    candidates: list[tuple[Path, Path]] = []
    notifier_requirements = target / "services" / "agentic-notifier" / "requirements.txt"
    if notifier_requirements.exists():
        candidates.append((notifier_requirements, notifier_requirements.parent / ".venv"))
    root_requirements = target / "requirements.txt"
    if root_requirements.exists():
        candidates.append((root_requirements, target / "target" / "automation_venvs" / "root"))
    services_dir = target / "services"
    if services_dir.exists():
        for requirements in sorted(services_dir.glob("*/requirements.txt")):
            item = (requirements, requirements.parent / ".venv")
            if item not in candidates:
                candidates.append(item)
    return candidates


def create_ignored_venv(target: Path) -> tuple[Path | None, str]:
    notes: list[str] = []
    for requirements, venv_dir in requirements_for_pytest_repair(target):
        if not git_ignores_path(target, venv_dir):
            notes.append(f"skipped {venv_dir.relative_to(target)} because it is not ignored by repo policy")
            continue
        python_path = venv_dir / "bin" / "python"
        if python_path.exists() and python_can_import(python_path, "pytest"):
            notes.append(f"using existing local ignored venv at {venv_dir.relative_to(target)}")
            return python_path, "; ".join(notes)
        if not python_path.exists():
            create = run([sys.executable, "-m", "venv", str(venv_dir)], cwd=target)
            if create.returncode != 0:
                notes.append(f"venv creation failed for {venv_dir.relative_to(target)}: {combined_output(create)}")
                continue
        install = run([str(python_path), "-m", "pip", "install", "-r", str(requirements)], cwd=target)
        if install.returncode != 0:
            notes.append(
                f"dependency install failed for {requirements.relative_to(target)}: {combined_output(install)}"
            )
            continue
        if python_can_import(python_path, "pytest"):
            notes.append(f"created local ignored venv from {requirements.relative_to(target)}")
            return python_path, "; ".join(notes)
        notes.append(f"installed {requirements.relative_to(target)} but pytest is still unavailable")
    return None, "; ".join(notes) if notes else "no requirements file with an ignored local venv location was found"


def attempt_verification_repair(
    target: Path,
    command: str,
    result: subprocess.CompletedProcess[str],
) -> VerificationRepair | None:
    output = combined_output(result)
    if not missing_pytest_failure(command, output):
        return None

    notes = ["detected missing pytest in the verification environment"]
    for python_path in existing_venv_pythons(target):
        if not python_path.exists() or not os.access(python_path, os.X_OK):
            continue
        if not python_can_import(python_path, "pytest"):
            notes.append(f"{python_path.relative_to(target)} exists but cannot import pytest")
            continue
        final_command = pytest_command_for_python(target, python_path, command)
        final_result = run(["/bin/bash", "-lc", final_command], cwd=target)
        notes.append(f"reran verification with existing local venv {python_path.relative_to(target)}")
        return VerificationRepair(
            attempted=True,
            detail="; ".join(notes),
            final_command=final_command,
            final_result=final_result,
        )

    python_path, create_detail = create_ignored_venv(target)
    notes.append(create_detail)
    if python_path is None:
        return VerificationRepair(attempted=True, detail="; ".join(note for note in notes if note))
    final_command = pytest_command_for_python(target, python_path, command)
    final_result = run(["/bin/bash", "-lc", final_command], cwd=target)
    notes.append(f"reran verification with local ignored venv {python_path.relative_to(target)}")
    return VerificationRepair(
        attempted=True,
        detail="; ".join(note for note in notes if note),
        final_command=final_command,
        final_result=final_result,
    )


def run_verification(target: Path) -> VerificationResult:
    commands = load_verification_commands(target)
    if not commands:
        return VerificationResult(
            ok=True,
            checks_run=["No verification commands configured; treated as pass."],
            detail="No verification commands configured.",
        )
    repair_module = load_environment_repair_module()
    if repair_module is not None:
        checks_run: list[str] = []
        details: list[str] = []
        for command in commands:
            outcome = repair_module.run_command_with_repair(target, command)
            checks_run.extend(str(item) for item in outcome.checks_run())
            details.append(outcome.detail())
            if not outcome.ok:
                return VerificationResult(
                    ok=False,
                    checks_run=checks_run,
                    detail="\n\n".join(details),
                    reason="verification_environment_failure" if outcome.environment_failure else "verification_failure",
                )
        return VerificationResult(ok=True, checks_run=checks_run, detail="\n\n".join(details))

    checks_run: list[str] = []
    details: list[str] = []
    for command in commands:
        result = run(["/bin/bash", "-lc", command], cwd=target)
        checks_run.append(command)
        output = combined_output(result)
        details.append(f"$ {command}\nexit={result.returncode}\n{output}".strip())
        if result.returncode != 0:
            repair = attempt_verification_repair(target, command, result)
            if repair is None:
                return VerificationResult(
                    ok=False,
                    checks_run=checks_run,
                    detail="\n\n".join(details),
                    reason="verification_failure",
                )
            checks_run.append(f"verification repair: {repair.detail}")
            details.append(f"verification repair: {repair.detail}")
            if repair.final_command is None or repair.final_result is None:
                return VerificationResult(
                    ok=False,
                    checks_run=checks_run,
                    detail="\n\n".join(details),
                    reason="verification_environment_failure",
                )
            checks_run.append(repair.final_command)
            final_output = combined_output(repair.final_result)
            details.append(
                f"$ {repair.final_command}\nexit={repair.final_result.returncode}\n{final_output}".strip()
            )
            if repair.final_result.returncode != 0:
                reason = (
                    "verification_environment_failure"
                    if missing_pytest_failure(repair.final_command, final_output)
                    else "verification_failure"
                )
                return VerificationResult(
                    ok=False,
                    checks_run=checks_run,
                    detail="\n\n".join(details),
                    reason=reason,
                )
    return VerificationResult(ok=True, checks_run=checks_run, detail="\n\n".join(details))


def staged_or_worktree_changes(target: Path) -> bool:
    return bool(git(target, "status", "--porcelain").stdout.strip())


def commit_current_patch(target: Path, manifest: dict[str, Any], run_id: str, *, dry_run: bool) -> str | None:
    if dry_run:
        return "DRY-RUN-COMMIT"
    if not staged_or_worktree_changes(target):
        return None
    git(target, "add", "-A", check=True)
    role = str(manifest.get("role") or "role")
    patch_run_id = str(manifest.get("run_id") or "unknown")
    summary = first_summary_line(str(manifest.get("summary") or ""))
    message = semantic_commit_message(manifest, target, patch_run_id)
    if summary:
        message += f"\n\n{summary}"
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Diffmogger Integrator",
            "GIT_AUTHOR_EMAIL": "diffmogger-integrator@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Integrator",
            "GIT_COMMITTER_EMAIL": "diffmogger-integrator@example.invalid",
        }
    )
    result = run(["git", "commit", "-m", message], cwd=target, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(1)
    return head(target)


def commit_automation_state(target: Path, run_id: str, *, dry_run: bool) -> str | None:
    if dry_run:
        return "DRY-RUN-STATE-COMMIT"
    paths = [
        "docs/CODEX_AUTOMATION_TASKS.md",
        "docs/MULTI_ROLE_PROGRESS.md",
    ]
    existing = [path for path in paths if (target / path).exists()]
    if not existing:
        return None
    result = git(target, "add", *existing)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return None
    diff = git(target, "diff", "--cached", "--quiet")
    if diff.returncode == 0:
        return None
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Diffmogger Integrator",
            "GIT_AUTHOR_EMAIL": "diffmogger-integrator@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Integrator",
            "GIT_COMMITTER_EMAIL": "diffmogger-integrator@example.invalid",
        }
    )
    result = run(["git", "commit", "-m", f"chore(integrator): update multi-role state {run_id}"], cwd=target, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(1)
    return head(target)


SEMANTIC_COMMIT_TYPES = {"feat", "fix", "docs", "test", "refactor", "chore", "build", "ci", "perf", "style"}
AUTOMATION_BOOKKEEPING_FILES = {
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "target/automation_signals.json",
}
CONVENTIONAL_SUBJECT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?:\s+(?P<action>.+)$")


def normalize_summary_line(raw: str) -> str:
    line = raw.strip()
    line = line.lstrip("#>*- \t").strip()
    line = line.strip("` ")
    return re.sub(r"\s+", " ", line)


def is_generic_commit_action(action: str) -> bool:
    lower = re.sub(r"\s+", " ", action.strip().lower().strip(".:;"))
    if not lower:
        return True
    if lower.startswith(("base_commit", "codex_exit_code", "patch:", "review /", "review `<")):
        return True
    if "raw codex output" in lower or " role run " in lower:
        return True
    if lower in {
        "changes",
        "document automation progress",
        "integrate builder work",
        "integrate hardener work",
        "integrate planner work",
        "integrate role work",
        "misc",
        "no summary",
        "update files",
        "update project",
        "work",
    }:
        return True
    return bool(re.fullmatch(r"(integrate|update|improve|change|modify) (builder|hardener|planner|role|automation)? ?work", lower))


def first_summary_line(text: str) -> str:
    skipped_prefixes = (
        "base_commit",
        "checks run:",
        "codex_exit_code",
        "commit scope:",
        "commit subject:",
        "commit type:",
        "patch:",
    )
    skipped_headings = {"checks", "checks run", "commit intent", "output", "summary"}
    for raw in text.splitlines():
        line = normalize_summary_line(raw)
        lower = line.lower()
        if not line or lower in skipped_headings:
            continue
        if lower.startswith(skipped_prefixes) or " role run " in lower:
            continue
        if is_generic_commit_action(line):
            continue
        return line[:200]
    return ""


def summary_field(text: str, field_name: str) -> str:
    prefix = f"{field_name.lower()}:"
    for raw in text.splitlines():
        line = normalize_summary_line(raw)
        if line.lower().startswith(prefix):
            return line[len(prefix) :].strip(" `")
    return ""


def normalize_commit_type(value: str) -> str:
    commit_type = re.sub(r"[^a-z]", "", value.strip().lower())
    return commit_type if commit_type in SEMANTIC_COMMIT_TYPES else ""


def slugify_scope(value: str) -> str:
    scope = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return scope[:48].strip("-")


def normalize_commit_scope(value: str) -> str:
    scope = slugify_scope(value)
    if not scope or scope in {"work", "changes", "files"}:
        return ""
    return scope


def trim_commit_action(action: str) -> str:
    action = normalize_summary_line(action).strip(".:;")
    conventional = CONVENTIONAL_SUBJECT_RE.match(action)
    if conventional:
        action = conventional.group("action").strip()
    if action[:1].isupper() and not action[:2].isupper():
        action = action[:1].lower() + action[1:]
    action = re.sub(r"\s+", " ", action).strip()
    if len(action) > 72:
        action = action[:72].rsplit(" ", 1)[0].strip()
    return "" if is_generic_commit_action(action) else action


def parse_commit_intent(summary: str, changed_files: list[str]) -> dict[str, str]:
    subject = summary_field(summary, "Commit subject") or summary_field(summary, "Commit message")
    if not subject:
        return {}

    intent: dict[str, str] = {}
    conventional = CONVENTIONAL_SUBJECT_RE.match(subject.strip())
    if conventional:
        intent["type"] = normalize_commit_type(conventional.group("type"))
        intent["scope"] = normalize_commit_scope(conventional.group("scope") or "")
        intent["action"] = trim_commit_action(conventional.group("action"))
    else:
        intent["type"] = normalize_commit_type(summary_field(summary, "Commit type"))
        intent["scope"] = normalize_commit_scope(summary_field(summary, "Commit scope"))
        intent["action"] = trim_commit_action(subject)

    if not intent.get("action"):
        return {}
    if intent.get("type") == "docs" and not docs_only(changed_files):
        intent.pop("type", None)
    if intent.get("scope") == "docs" and not docs_only(changed_files):
        intent.pop("scope", None)
    return {key: value for key, value in intent.items() if value}


def semantic_commit_message(manifest: dict[str, Any], target: Path, patch_run_id: str) -> str:
    role = str(manifest.get("role") or "role").strip().lower() or "role"
    changed_files = semantic_changed_files([str(path) for path in manifest.get("changed_files") or [] if isinstance(path, str)])
    intent = parse_commit_intent(str(manifest.get("summary") or ""), changed_files)
    commit_type = intent.get("type") or semantic_commit_type(changed_files)
    scope = intent.get("scope") or semantic_commit_scope(changed_files, role)
    action = intent.get("action") or semantic_commit_action(changed_files, role, semantic_patch_text(manifest, target), scope)
    return f"{commit_type}({scope}): {action}\n\nRole: {role}\nPatch-run: {patch_run_id}"


def semantic_changed_files(changed_files: list[str]) -> list[str]:
    meaningful = [path for path in changed_files if path not in AUTOMATION_BOOKKEEPING_FILES and not path.startswith("target/")]
    return meaningful or changed_files


def is_doc_path(path: str) -> bool:
    return path == "README.md" or path.startswith("docs/") or path.endswith(".md")


def docs_only(changed_files: list[str]) -> bool:
    return bool(changed_files) and all(is_doc_path(path) for path in changed_files)


def is_test_path(path: str) -> bool:
    name = Path(path).name
    return path.startswith(("tests/", "test/")) or ".test." in name or ".spec." in name


def is_source_path(path: str) -> bool:
    return path.startswith(("src/", "services/")) and not is_test_path(path)


def semantic_commit_type(changed_files: list[str]) -> str:
    if not changed_files:
        return "chore"
    if docs_only(changed_files):
        return "docs"
    if any(is_source_path(path) for path in changed_files):
        return "feat"
    if any("browser_smoke" in path for path in changed_files):
        return "test"
    if any(path.startswith("services/") for path in changed_files):
        return "feat"
    if any(path.startswith(("scripts/", "templates/")) for path in changed_files):
        return "feat"
    if any(is_test_path(path) for path in changed_files):
        return "test"
    return "chore"


def semantic_commit_scope(changed_files: list[str], role: str) -> str:
    joined = "\n".join(changed_files)
    for marker, scope in [
        ("run_observatory.py", "observatory"),
        ("run_conveyor_automation.py", "conveyor"),
        ("integrate_role_outputs.py", "integrator"),
        ("run_role_automation.sh", "role-runner"),
        ("check_integration_safety.py", "safety"),
        ("check_required_files.py", "scaffold"),
        ("validate_starter_kit.sh", "validation"),
        ("agentic-dashboard", "dashboard"),
        ("agentic-notifier", "notifier"),
    ]:
        if marker in joined:
            return scope

    for path in changed_files:
        if path.startswith("src/lib/"):
            stem = Path(path).stem
            return slugify_scope(re.sub(r"\.(test|spec)$", "", stem)) or "lib"
    if any(path.startswith("src/App.") for path in changed_files):
        return "app"
    if any(path.startswith("src/styles.") for path in changed_files):
        return "styles"
    if "browser_smoke" in joined:
        return "browser-smoke"

    if docs_only(changed_files):
        for marker, scope in [
            ("docs/DASHBOARD.md", "dashboard"),
            ("docs/FRESH_PROJECT_SETUP.md", "setup"),
            ("docs/LOCAL_FIRST_BASELINE.md", "local-first"),
            ("docs/DEVELOPMENT.md", "development"),
            ("docs/OPERATING_MODEL.md", "operating-model"),
        ]:
            if marker in changed_files:
                return scope
        return "docs"

    for path in changed_files:
        if path.startswith("scripts/"):
            return slugify_scope(Path(path).stem) or "scripts"
    return role or "automation"


def semantic_patch_text(manifest: dict[str, Any], target: Path) -> str:
    try:
        patch = resolve_patch_path(target, manifest)
        if patch.exists() and patch.is_file():
            return patch.read_text(encoding="utf-8", errors="replace")[:60_000]
    except OSError:
        pass
    return ""


def semantic_commit_action(changed_files: list[str], role: str, patch_text: str = "", scope: str | None = None) -> str:
    joined = "\n".join(changed_files)
    lower_patch = patch_text.lower()
    scope = scope or semantic_commit_scope(changed_files, role)
    if "closure checklist" in lower_patch:
        return "add review closure checklist"
    if "baseline comparison" in lower_patch and (
        "no saved baseline" in lower_patch or "saving comparison baselines" in lower_patch
    ):
        return "add baseline comparison guidance"
    if "chrome-launch-diagnostics" in lower_patch or (
        "chrome" in lower_patch and "diagnostics" in lower_patch and "browser_smoke" in joined
    ):
        return "report browser smoke launch diagnostics"
    if "check_required_files.py" in joined:
        return "enforce generated target contracts"
    if "check_integration_safety.py" in joined:
        return "enforce local integration safety"
    if "integrate_role_outputs.py" in joined and "run_role_automation.sh" in joined:
        return "propagate ignored runtime state"
    if "run_observatory.py" in joined:
        return "surface automation progress details"
    if "run_conveyor_automation.py" in joined:
        return "improve conveyor scheduling"
    if "agentic-dashboard" in joined:
        return "improve dashboard automation controls"
    if "validate_starter_kit.sh" in joined:
        return "strengthen starter kit validation"
    if docs_only(changed_files):
        if scope == "dashboard":
            return "document dashboard workflow"
        if scope == "setup":
            return "document project setup"
        if scope == "local-first":
            return "document local-first baseline"
        if scope == "development":
            return "document development workflow"
        return "update documentation"
    if "browser_smoke" in joined:
        return "harden browser smoke diagnostics"
    if any(is_test_path(path) for path in changed_files) and not any(is_source_path(path) for path in changed_files):
        return f"cover {scope} behavior"
    if any(is_source_path(path) for path in changed_files):
        if scope == "planning":
            return "update weekly planning workflow"
        return f"update {scope} workflow"
    if any(path.startswith(("scripts/", "templates/")) for path in changed_files):
        return f"improve {scope} automation"
    return f"update {scope} workflow"


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LOCAL_PATH_RE = re.compile(r"(?<![\w.])/(?:Users|private/tmp|tmp|var/folders)/[^\s`'\"<>)]*")


def scrub_local_references(text: str, target: Path) -> str:
    text = ANSI_RE.sub("", str(text))
    replacements = {
        str(target): "<target>",
        str(Path.home()): "<home>",
        "agentic-kit-" + "lab": "<workspace>",
    }
    for old, new in replacements.items():
        if old:
            text = text.replace(old, new)
    return LOCAL_PATH_RE.sub("<local-path>", text)


def progress_inline(text: str, target: Path, *, limit: int = 240) -> str:
    scrubbed = scrub_local_references(text, target)
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip()
    if not scrubbed:
        return "No detail."
    if len(scrubbed) > limit:
        return scrubbed[: limit - 3].rstrip() + "..."
    return scrubbed


def summarize_deferral_for_progress(item: dict[str, Any], target: Path) -> str:
    detail = str(item.get("deferral_detail") or "")
    if missing_pytest_failure("pytest", detail):
        return "missing pytest in the verification environment; raw detail stays in the manifest."
    if ("/User" + "s/") in detail or ("agentic-kit-" + "lab") in detail:
        return "local workspace path/reference in generated state; raw detail stays in the manifest."
    first_line = next((line.strip() for line in detail.splitlines() if line.strip()), detail)
    return progress_inline(first_line, target)


def compact_progress_section(text: str, target: Path, *, max_chars: int = 6000) -> str:
    scrubbed = scrub_local_references(text, target)
    lines: list[str] = []
    for line in scrubbed.splitlines():
        if len(line) > 320:
            line = line[:317].rstrip() + "..."
        lines.append(line)
    compacted = "\n".join(lines).strip()
    if len(compacted) <= max_chars:
        return compacted
    tail = compacted[-max_chars:].lstrip()
    first_newline = tail.find("\n")
    if first_newline != -1:
        tail = tail[first_newline + 1 :]
    return "- Older progress entries compacted to keep generated state skimmable.\n" + tail.strip()


def patch_is_empty(patch: Path) -> bool:
    return not patch.exists() or patch.stat().st_size == 0


def batch_apply(
    target: Path,
    queued: list[tuple[Path, dict[str, Any]]],
    *,
    head_before: str,
    checkpoint_commit: str | None,
    dry_run: bool,
) -> tuple[bool, list[tuple[Path, dict[str, Any]]], list[tuple[Path, dict[str, Any], str]]]:
    accepted: list[tuple[Path, dict[str, Any]]] = []
    deferred: list[tuple[Path, dict[str, Any], str]] = []
    for path, manifest in queued:
        patch = resolve_patch_path(target, manifest)
        manifest["head_before_integration"] = head_before
        if patch_is_empty(patch):
            accepted.append((path, manifest))
            continue
        check = apply_check(target, patch)
        if check.returncode != 0:
            reason, detail = classify_apply_failure(target, manifest, head_before, check.stderr)
            mark_deferred(
                path,
                manifest,
                reason=reason,
                detail=detail,
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            deferred.append((path, manifest, reason))
            continue
        apply_result = apply_patch_file(target, patch, dry_run=dry_run)
        if apply_result.returncode != 0:
            mark_deferred(
                path,
                manifest,
                reason="conflict",
                detail=apply_result.stderr.strip() or "git apply failed after check",
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            deferred.append((path, manifest, "conflict"))
            continue
        accepted.append((path, manifest))
    verification = run_verification(target)
    for _, manifest in accepted:
        manifest["checks_run"] = verification.checks_run
    return verification.ok, accepted, deferred


def replay_and_commit(
    target: Path,
    accepted: list[tuple[Path, dict[str, Any]]],
    *,
    head_before: str,
    checkpoint_commit: str | None,
    checks_run: list[str],
    dry_run: bool,
) -> list[tuple[Path, dict[str, Any], str | None]]:
    committed: list[tuple[Path, dict[str, Any], str | None]] = []
    reset_to(target, head_before, [manifest for _, manifest in accepted], dry_run=dry_run)
    for path, manifest in accepted:
        current_head = head(target) if not dry_run else head_before
        patch = resolve_patch_path(target, manifest)
        if not patch_is_empty(patch):
            result = apply_patch_file(target, patch, dry_run=dry_run)
            if result.returncode != 0:
                mark_deferred(
                    path,
                    manifest,
                    reason="conflict",
                    detail=result.stderr.strip() or "Patch failed while replaying accepted batch.",
                    head_before_integration=head_before,
                    checkpoint_commit=checkpoint_commit,
                    dry_run=dry_run,
                )
                continue
        apply_runtime_state_actions(target, manifest, dry_run=dry_run)
        if runtime_state_has_blocking_results(manifest):
            reset_to(target, current_head, [manifest], dry_run=dry_run)
            mark_deferred(
                path,
                manifest,
                reason=runtime_state_deferral_reason(manifest),
                detail=runtime_state_deferral_detail(manifest),
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=checks_run,
                dry_run=dry_run,
            )
            continue
        commit_hash = commit_current_patch(target, manifest, str(manifest.get("run_id") or ""), dry_run=dry_run)
        mark_applied(
            path,
            manifest,
            accepted_commit=commit_hash,
            head_before_integration=head_before,
            checkpoint_commit=checkpoint_commit,
            checks_run=checks_run,
            dry_run=dry_run,
        )
        committed.append((path, manifest, commit_hash))
    return committed


def integrate_individually(
    target: Path,
    queued: list[tuple[Path, dict[str, Any]]],
    *,
    head_before: str,
    checkpoint_commit: str | None,
    dry_run: bool,
) -> list[tuple[Path, dict[str, Any], str | None]]:
    committed: list[tuple[Path, dict[str, Any], str | None]] = []
    for path, manifest in queued:
        patch = resolve_patch_path(target, manifest)
        current_head = head(target) if not dry_run else head_before
        if patch_is_empty(patch):
            apply_runtime_state_actions(target, manifest, dry_run=dry_run)
            if runtime_state_has_blocking_results(manifest):
                mark_deferred(
                    path,
                    manifest,
                    reason=runtime_state_deferral_reason(manifest),
                    detail=runtime_state_deferral_detail(manifest),
                    head_before_integration=head_before,
                    checkpoint_commit=checkpoint_commit,
                    checks_run=["No patch changes to apply."],
                    dry_run=dry_run,
                )
                continue
            mark_applied(
                path,
                manifest,
                accepted_commit=None,
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=["No patch changes to apply."],
                dry_run=dry_run,
            )
            committed.append((path, manifest, None))
            continue
        check = apply_check(target, patch)
        if check.returncode != 0:
            reason, detail = classify_apply_failure(target, manifest, current_head, check.stderr)
            mark_deferred(
                path,
                manifest,
                reason=reason,
                detail=detail,
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            continue
        result = apply_patch_file(target, patch, dry_run=dry_run)
        if result.returncode != 0:
            mark_deferred(
                path,
                manifest,
                reason="conflict",
                detail=result.stderr.strip() or "git apply failed",
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            reset_to(target, current_head, [manifest], dry_run=dry_run)
            continue
        verification = run_verification(target)
        if not verification.ok:
            mark_deferred(
                path,
                manifest,
                reason=verification.reason or "verification_failure",
                detail=verification.detail,
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=verification.checks_run,
                dry_run=dry_run,
            )
            reset_to(target, current_head, [manifest], dry_run=dry_run)
            continue
        apply_runtime_state_actions(target, manifest, dry_run=dry_run)
        if runtime_state_has_blocking_results(manifest):
            reset_to(target, current_head, [manifest], dry_run=dry_run)
            mark_deferred(
                path,
                manifest,
                reason=runtime_state_deferral_reason(manifest),
                detail=runtime_state_deferral_detail(manifest),
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=verification.checks_run,
                dry_run=dry_run,
            )
            continue
        commit_hash = commit_current_patch(target, manifest, str(manifest.get("run_id") or ""), dry_run=dry_run)
        mark_applied(
            path,
            manifest,
            accepted_commit=commit_hash,
            head_before_integration=head_before,
            checkpoint_commit=checkpoint_commit,
            checks_run=verification.checks_run,
            dry_run=dry_run,
        )
        committed.append((path, manifest, commit_hash))
    return committed


def split_h2_sections(text: str) -> tuple[str, dict[str, str]]:
    lines = text.splitlines()
    header_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line.startswith("## "):
            current = line.removeprefix("## ").strip()
            sections[current] = []
        elif current is None:
            header_lines.append(line)
        else:
            sections[current].append(line)
    return "\n".join(header_lines).strip(), {key: "\n".join(value).strip() for key, value in sections.items()}


def deferred_manifests(target: Path) -> list[dict[str, Any]]:
    return [manifest for _, manifest in all_role_manifests(target) if manifest.get("status") == "deferred"]


def progress_counts(target: Path) -> tuple[dict[str, int], dict[str, int], int]:
    accepted = {role: 0 for role in QUEUE_ROLES}
    deferred = {role: 0 for role in QUEUE_ROLES}
    integrator_runs = 0
    for _, manifest in all_role_manifests(target):
        role = str(manifest.get("role") or "")
        if role == "integrator":
            integrator_runs += 1
        if role in accepted and manifest.get("status") == "applied":
            accepted[role] += 1
        if role in deferred and manifest.get("status") == "deferred":
            deferred[role] += 1
    return accepted, deferred, integrator_runs


def update_progress(
    target: Path,
    *,
    run_id: str,
    verification_status: str,
    committed: list[tuple[Path, dict[str, Any], str | None]],
    deferred_count: int,
    checkpoint_commit: str | None,
    cleanup_summary: list[str],
    dry_run: bool,
) -> None:
    progress = target / "docs" / "MULTI_ROLE_PROGRESS.md"
    if progress.exists():
        header, sections = split_h2_sections(progress.read_text(encoding="utf-8"))
    else:
        header = "# Multi-Role Progress\n\nDurable progress record for optional multi-role automation."
        sections = {}
    accepted_counts, deferred_counts, integrator_runs = progress_counts(target)
    deferred_items = deferred_manifests(target)
    accepted_lines = [
        f"- {progress_inline(str(manifest.get('role') or 'role'), target)} `{progress_inline(str(manifest.get('run_id') or 'unknown'), target, limit=80)}` -> {commit or 'no commit'}: {progress_inline(first_summary_line(str(manifest.get('summary') or '')) or 'No summary.', target)}"
        for _, manifest, commit in committed
    ] or ["- None."]
    backlog_lines = [
        f"- {progress_inline(str(item.get('role') or 'role'), target)} `{progress_inline(str(item.get('run_id') or 'unknown'), target, limit=80)}`: {progress_inline(str(item.get('deferral_reason') or 'other'), target, limit=80)}; {summarize_deferral_for_progress(item, target)}"
        for item in deferred_items
    ] or ["- None."]
    changed_files = sorted(
        {progress_inline(str(file), target, limit=160) for _, manifest, _ in committed for file in (manifest.get("changed_files") or [])}
    )
    recent_body = sections.get("Recent Activity Log", "").strip()
    if recent_body == "- No multi-role integrator runs yet.":
        recent_body = ""
    else:
        recent_body = compact_progress_section(recent_body, target)
    entry_lines = [
        f"### {utc_now().isoformat(timespec='seconds')} {run_id}",
        "",
        f"- verification: {progress_inline(verification_status, target)}",
        f"- accepted_patches: {len(committed)}",
        f"- deferred_patches: {deferred_count}",
        f"- checkpoint_commit: {checkpoint_commit or 'none'}",
        "- accepted:",
        *accepted_lines,
        "- files_changed:",
        *([f"  - {file}" for file in changed_files] or ["  - none"]),
    ]
    if cleanup_summary:
        entry_lines.extend(["- cleanup:", *[f"  - {line}" for line in cleanup_summary]])
    recent_body = (recent_body.rstrip() + "\n\n" + "\n".join(entry_lines)).strip()
    sections["Project State At Last Integration"] = "\n".join(
        [
            "- Current product horizon: see `docs/CODEX_AUTOMATION_TASKS.md`",
            f"- Latest evidence: integrator run `{run_id}` accepted {len(committed)} patches and deferred {deferred_count}.",
            f"- Last integrator run: {utc_now().isoformat(timespec='seconds')}",
            f"- Last verification status: {progress_inline(verification_status, target)}",
        ]
    )
    sections["Cumulative Metrics"] = "\n".join(
        [
            f"- Total integrator runs: {integrator_runs}",
            "- Accepted patches by role:",
            *[f"  - {role}: {accepted_counts[role]}" for role in QUEUE_ROLES],
            "- Deferred patches by role:",
            *[f"  - {role}: {deferred_counts[role]}" for role in QUEUE_ROLES],
            f"- Current deferred queue depth: {len(deferred_items)}",
            "- Mean time from role-run completion to integration: not computed",
            "- Human inbox messages handled: see `docs/HUMAN_RESPONSES_ARCHIVE.md`",
            "- Human requests created: see `docs/HUMAN_REQUESTS.md`",
            "- Human requests resolved: see `docs/HUMAN_RESPONSES_ARCHIVE.md`",
        ]
    )
    sections["Recent Activity Log"] = recent_body
    sections["Historical Summary"] = sections.get("Historical Summary") or "- No compacted multi-role history yet."
    sections["Deferred-Patch Backlog"] = "\n".join(backlog_lines)
    sections["Architectural Decisions"] = sections.get("Architectural Decisions") or "- None yet."
    sections["Role Health"] = "\n".join(
        [
            f"- {role}: accepted={accepted_counts.get(role, 0)} deferred={deferred_counts.get(role, 0)}"
            for role in QUEUE_ROLES
        ]
        + [f"- integrator: runs={integrator_runs}"]
    )
    body = header.rstrip() + "\n\n"
    for section in PROGRESS_SECTIONS:
        body += f"## {section}\n\n{sections.get(section, '').strip()}\n\n"
    body = scrub_local_references(body, target)
    if not dry_run:
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text(body.rstrip() + "\n", encoding="utf-8")


def update_task_file(
    target: Path,
    *,
    run_id: str,
    checkpoint_commit: str | None,
    dirty_files: list[str],
    committed: list[tuple[Path, dict[str, Any], str | None]],
    deferred_count: int,
    dry_run: bool,
) -> None:
    task = target / "docs" / "CODEX_AUTOMATION_TASKS.md"
    if not task.exists() or dry_run:
        return
    text = task.read_text(encoding="utf-8").rstrip()
    lines = [
        "",
        "",
        f"## Multi-Role Integration {run_id}",
        "",
        f"- checkpoint_commit: {checkpoint_commit or 'none'}",
        f"- dirty_files_checkpointed: {', '.join(dirty_files) if dirty_files else 'none'}",
        f"- accepted_patches: {len(committed)}",
        f"- deferred_patches: {deferred_count}",
        "- accepted_commits:",
        *[f"  - {manifest.get('role')} `{manifest.get('run_id')}` -> {commit or 'no commit'}" for _, manifest, commit in committed],
    ]
    task.write_text(text + "\n".join(lines).rstrip() + "\n", encoding="utf-8")


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
        "accepted_commit": head(target) if not dry_run else None,
    }
    write_manifest(path, manifest, dry_run=dry_run)


def cleanup_artifacts(target: Path, *, dry_run: bool) -> list[str]:
    now = time.time()
    seven_days = 7 * 24 * 60 * 60
    thirty_days = 30 * 24 * 60 * 60
    queue_root = target / "target" / "automation_queue"
    worktree_root = target / "target" / "automation_worktrees"
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

    log_root = target / "target" / "automation_logs"
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


def integrate(target: Path, run_id: str, *, dry_run: bool) -> int:
    require_git_repo(target)
    ensure_local_only(target)
    scan_push_hooks(target)
    update_info_exclude(target, dry_run=dry_run)
    lock = acquire_lock(target, run_id, dry_run=dry_run)
    checkpoint_commit: str | None = None
    dirty_files: list[str] = []
    head_before: str | None = None
    committed: list[tuple[Path, dict[str, Any], str | None]] = []
    deferred_count = 0
    verification_status = "not run"
    try:
        checkpoint_commit, dirty_files = checkpoint_dirty_main(target, run_id, dry_run=dry_run)
        head_before = head(target)
        queued = load_queued_manifests(target)
        if not queued:
            cleanup_summary = cleanup_artifacts(target, dry_run=dry_run)
            update_progress(
                target,
                run_id=run_id,
                verification_status="no queued patches",
                committed=[],
                deferred_count=0,
                checkpoint_commit=checkpoint_commit,
                cleanup_summary=cleanup_summary,
                dry_run=dry_run,
            )
            update_task_file(
                target,
                run_id=run_id,
                checkpoint_commit=checkpoint_commit,
                dirty_files=dirty_files,
                committed=[],
                deferred_count=0,
                dry_run=dry_run,
            )
            create_integrator_manifest(
                target,
                run_id=run_id,
                status="applied",
                head_before=head_before,
                checkpoint_commit=checkpoint_commit,
                summary="No queued patches.",
                dry_run=dry_run,
            )
            commit_automation_state(target, run_id, dry_run=dry_run)
            print("No queued multi-role patches.")
            return 0

        ok, accepted, deferred = batch_apply(
            target,
            queued,
            head_before=head_before,
            checkpoint_commit=checkpoint_commit,
            dry_run=dry_run,
        )
        deferred_count += len(deferred)
        if ok:
            checks = accepted[0][1].get("checks_run") if accepted else []
            committed = replay_and_commit(
                target,
                accepted,
                head_before=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=[str(item) for item in checks],
                dry_run=dry_run,
            )
            verification_status = "passed"
        else:
            verification_status = "batch failed; individual fallback used"
            reset_to(target, head_before, [manifest for _, manifest in queued], dry_run=dry_run)
            committed = integrate_individually(
                target,
                queued,
                head_before=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            deferred_count = sum(
                1
                for _, manifest in all_role_manifests(target)
                if manifest.get("status") == "deferred" and manifest.get("integrated_at")
            )
        cleanup_summary = cleanup_artifacts(target, dry_run=dry_run)
        update_progress(
            target,
            run_id=run_id,
            verification_status=verification_status,
            committed=committed,
            deferred_count=deferred_count,
            checkpoint_commit=checkpoint_commit,
            cleanup_summary=cleanup_summary,
            dry_run=dry_run,
        )
        update_task_file(
            target,
            run_id=run_id,
            checkpoint_commit=checkpoint_commit,
            dirty_files=dirty_files,
            committed=committed,
            deferred_count=deferred_count,
            dry_run=dry_run,
        )
        create_integrator_manifest(
            target,
            run_id=run_id,
            status="applied",
            head_before=head_before,
            checkpoint_commit=checkpoint_commit,
            summary=f"Accepted {len(committed)} patches; deferred {deferred_count}.",
            dry_run=dry_run,
        )
        commit_automation_state(target, run_id, dry_run=dry_run)
        print(f"INTEGRATION_COMPLETE run_id={run_id} accepted={len(committed)} deferred={deferred_count}")
        if dry_run:
            print("DRY RUN: no files were modified.")
        return 0
    finally:
        release_lock(target, run_id, lock)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--run-id", default=f"{now_id()}-integrator", help="Run id for lock and manifest records")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without mutating files")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    return integrate(target, args.run_id, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
