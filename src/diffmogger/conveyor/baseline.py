from __future__ import annotations

from .state import *

def automation_status(target: Path) -> str:
    # Compatibility boundary: older targets still expose the operator status in
    # the task Markdown. Typed task status should replace this shim.
    task_text = read_text(dpath(target, "docs/CODEX_AUTOMATION_TASKS.md"))
    match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", task_text, re.MULTILINE)
    return match.group(1).strip().upper() if match else "UNKNOWN"

def verification_config_hash(target: Path) -> str:
    path = dpath(target, ".agentic/verification_commands.txt")
    if not path.exists() or not path.is_file() or path.is_symlink():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()

def current_head(target: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=target,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""

def baseline_record(target: Path) -> dict[str, Any]:
    return read_json(dpath(target, BASELINE_VERIFICATION_RELATIVE))

def baseline_record_is_current(target: Path, record: dict[str, Any]) -> bool:
    if not record:
        return False
    head_value = current_head(target)
    if not head_value:
        return True
    return (
        str(record.get("head") or "") == head_value
        and str(record.get("verification_config_hash") or "") == verification_config_hash(target)
    )

def baseline_preflight_needed(target: Path) -> bool:
    if not (dpath(target, ".agentic/verification_commands.txt")).exists():
        return False
    return not baseline_record_is_current(target, baseline_record(target))

def last_baseline_repair_source_role(state: dict[str, Any]) -> str:
    last_completed = str(state.get("last_completed_role") or "")
    if last_completed in {"planner", "builder", "hardener"}:
        return last_completed
    for entry in reversed(state.get("history") or []):
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        if role == "integrator":
            metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            accepted = metadata.get("accepted_by_role") if isinstance(metadata.get("accepted_by_role"), dict) else {}
            for accepted_role in ("hardener", "builder", "planner"):
                if int(accepted.get(accepted_role) or 0) > 0:
                    return accepted_role
            continue
        if role in {"planner", "builder", "hardener"} and int(entry.get("exit_code") or 0) == 0:
            return role
    return ""

def baseline_repair_route(target: Path, state: dict[str, Any]) -> tuple[str | None, str, bool] | None:
    record = baseline_record(target)
    if not baseline_record_is_current(target, record):
        return None
    status = str(record.get("status") or "unknown")
    root = str(record.get("root_cause") or "No baseline root cause recorded.")
    if status in {"passing", ""}:
        return None
    if status in {"failing_source", "missing_config", "repairable_local_service"}:
        source_role = last_baseline_repair_source_role(state)
        if source_role == "planner":
            if status == "repairable_local_service":
                return (
                    "builder",
                    f"baseline verification needs a repairable local service harness; create a verification_scope=baseline_repair patch: {root}",
                    False,
                )
            return (
                "hardener",
                    f"baseline verification is {status}; create a verification_scope=baseline_repair patch: {root}",
                    False,
                )
        if source_role == "builder" and status == "repairable_local_service":
            return (
                "hardener",
                f"baseline local-service repair needs hardening with verification_scope=baseline_repair: {root}",
                False,
            )
        return (
            "planner",
            f"baseline verification is {status}; plan a verification_scope=baseline_repair patch: {root}",
            False,
        )
    if status == "blocked_environment":
        return (
            None,
            f"baseline verification is blocked_environment after integrator preflight: {root}",
            False,
        )
    return None
