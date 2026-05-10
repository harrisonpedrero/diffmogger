from __future__ import annotations

from .common import *
from .git_safety import git
from .queue import resolve_runtime_state_actions_path

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
    manifest = load_manifest(target)
    if manifest.get("layout") == "sidecar_v1":
        if rel_text.startswith(".diffmogger/scripts/"):
            return False, "runtime-state path may not update Diffmogger helper scripts"
        owned = set(manifest_path_list(manifest, "owned_paths"))
        seed = set(manifest_path_list(manifest, "worktree_seed_paths"))
        human = set(manifest_path_list(manifest, "human_state_paths"))
        if rel_text in owned | seed | human and rel_text.startswith(".diffmogger/"):
            return True, ""
        return False, "runtime-state path is outside the sidecar manifest ownership set"
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
