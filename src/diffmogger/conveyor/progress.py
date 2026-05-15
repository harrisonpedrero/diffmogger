from __future__ import annotations

from .active_role import update_timeout_streak, timeout_streak_count
from .baseline import current_head
from .queue_state import latest_applied_role_manifest_info, queue_snapshot, role_manifest_records, format_file_list
from .state import *
from diffmogger.runtime.paths import target_rel
from diffmogger.runtime.state_store import automation_control_state

def write_no_progress_progress_note(target: Path, info: dict[str, Any]) -> None:
    progress = dpath(target, "docs/MULTI_ROLE_PROGRESS.md")
    sqlite_rel = target_rel(target, "target/orchestration.sqlite3")
    queue_rel = target_rel(target, "target/automation_queue")
    reason = re.sub(r"\s+", " ", str(info.get("reason") or "integrator made no patch progress")).strip()
    reason = reason[:240] if len(reason) > 240 else reason
    stamp = utc_now()
    snapshot = queue_snapshot(target)
    control = automation_control_state(target)
    applied_by_role = snapshot.get("applied_by_role") if isinstance(snapshot.get("applied_by_role"), dict) else {}
    deferred_by_role = snapshot.get("deferred_by_role") if isinstance(snapshot.get("deferred_by_role"), dict) else {}
    deferred_depth = int(snapshot.get("deferred", 0) or 0)
    body = "\n".join(
        [
            "# Multi-Role Progress",
            "",
            f"Generated dashboard/export projection for optional multi-role automation. SQLite in `{sqlite_rel}` is the live state authority.",
            "Continuous conveyor mode prioritizes queued integration, baseline repair, typed human-message triage, fast-follow replanning after planner deferral changes, post-builder hardening, candidate verification, and builder momentum.",
            "",
            "## Project State At Last Integration",
            "",
            f"- Current product horizon: {control.get('horizon') or 'unknown'}",
            "- Latest evidence: no-progress circuit breaker tripped after an integrator cycle.",
            f"- Last integrator run: {stamp}",
            "- Last verification status: recorded in typed validation receipts",
            "",
            "## Cumulative Metrics",
            "",
            "- Total integrator runs: recorded in role manifests",
            "- Accepted patches by role:",
            *[f"  - {role}: {int(applied_by_role.get(role, 0) or 0)}" for role in QUEUE_ROLES],
            "- Deferred patches by role:",
            *[f"  - {role}: {int(deferred_by_role.get(role, 0) or 0)}" for role in QUEUE_ROLES],
            f"- Current deferred queue depth: {deferred_depth}",
            "",
            "## Recent Activity Log",
            "",
            f"### {stamp} conveyor-no-progress",
            "",
            f"- circuit_breaker: active after {info.get('streak', 0)} no-progress integrator cycle(s).",
            f"- reason: {reason}",
            "- next_lane: planner handoff or idle until the blocked condition changes.",
            "",
            "## Historical Summary",
            "",
            "- Historical progress is represented by role manifests and SQLite events.",
            "",
            "## Deferred-Patch Backlog",
            "",
            f"- See role manifests under `{queue_rel}/` for deferred patch details.",
            "",
            "## Architectural Decisions",
            "",
            "- None recorded in typed state.",
            "",
            "## Role Health",
            "",
            f"- conveyor: no-progress circuit breaker active; {reason}",
        ]
    )
    progress.parent.mkdir(parents=True, exist_ok=True)
    progress.write_text(body.rstrip() + "\n", encoding="utf-8")

def no_progress_info(state: dict[str, Any]) -> dict[str, Any]:
    info = state.get(NO_PROGRESS_STATE_KEY)
    return info if isinstance(info, dict) else {}

def no_progress_active(state: dict[str, Any], threshold: int) -> bool:
    info = no_progress_info(state)
    return bool(info.get("active")) and int(info.get("streak", 0)) >= threshold

def snapshot_deferred_role_signature(snapshot: dict[str, Any], role: str) -> str:
    raw = snapshot.get("deferred_signature_by_role")
    if isinstance(raw, dict):
        return str(raw.get(role) or "none")
    return "none"

def update_integrator_no_progress(
    state: dict[str, Any],
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    exit_code: int,
    threshold: int,
    finished_at: str,
) -> dict[str, Any]:
    accepted_delta = max(0, int(after.get("applied", 0)) - int(before.get("applied", 0)))
    deferred_delta = int(after.get("deferred", 0)) - int(before.get("deferred", 0))
    before_by_role = before.get("applied_by_role") if isinstance(before.get("applied_by_role"), dict) else {}
    after_by_role = after.get("applied_by_role") if isinstance(after.get("applied_by_role"), dict) else {}
    accepted_by_role = {
        role: max(0, int(after_by_role.get(role, 0)) - int(before_by_role.get(role, 0)))
        for role in QUEUE_ROLES
    }
    before_deferred_by_role = (
        before.get("deferred_by_role") if isinstance(before.get("deferred_by_role"), dict) else {}
    )
    after_deferred_by_role = (
        after.get("deferred_by_role") if isinstance(after.get("deferred_by_role"), dict) else {}
    )
    deferred_delta_by_role = {
        role: int(after_deferred_by_role.get(role, 0)) - int(before_deferred_by_role.get(role, 0))
        for role in QUEUE_ROLES
    }
    previous = no_progress_info(state)
    signature = str(after.get("deferred_signature") or "none")
    same_signature = bool(signature and signature != "none" and signature == previous.get("signature"))
    stuck_same_reason = same_signature and int(after.get("deferred", 0)) >= int(before.get("deferred", 0))
    builder_deferred_before = int(before_deferred_by_role.get("builder", 0))
    builder_deferred_after = int(after_deferred_by_role.get("builder", 0))
    builder_deferred_signature_before = snapshot_deferred_role_signature(before, "builder")
    builder_deferred_signature_after = snapshot_deferred_role_signature(after, "builder")
    same_builder_deferred_signature = bool(
        builder_deferred_signature_after
        and builder_deferred_signature_after != "none"
        and builder_deferred_signature_after == previous.get("builder_deferred_signature")
    )
    builder_deferred_unchanged = (
        builder_deferred_before > 0
        and builder_deferred_after > 0
        and deferred_delta_by_role.get("builder", 0) == 0
        and builder_deferred_signature_before != "none"
        and builder_deferred_signature_before == builder_deferred_signature_after
    )
    planner_only_acceptance = (
        accepted_delta > 0
        and accepted_by_role.get("planner", 0) == accepted_delta
        and all(int(accepted_by_role.get(role, 0)) == 0 for role in ("builder", "hardener"))
    )
    planner_acceptance_did_not_unstick_builder_deferral = (
        exit_code == 0 and planner_only_acceptance and builder_deferred_unchanged
    )
    same_no_progress_signature = same_signature or (
        planner_acceptance_did_not_unstick_builder_deferral and same_builder_deferred_signature
    )
    no_progress = exit_code == 0 and (
        (accepted_delta == 0 and (deferred_delta > 0 or stuck_same_reason))
        or planner_acceptance_did_not_unstick_builder_deferral
    )

    metadata = {
        "accepted_delta": accepted_delta,
        "deferred_delta": deferred_delta,
        "queued_before": int(before.get("queued", 0)),
        "queued_after": int(after.get("queued", 0)),
        "deferred_after": int(after.get("deferred", 0)),
        "deferred_signature": signature,
        "accepted_by_role": accepted_by_role,
        "deferred_by_role": {
            role: int(after_deferred_by_role.get(role, 0)) for role in QUEUE_ROLES
        },
        "deferred_delta_by_role": deferred_delta_by_role,
        "builder_deferred_before": builder_deferred_before,
        "builder_deferred_after": builder_deferred_after,
        "builder_deferred_signature_before": builder_deferred_signature_before,
        "builder_deferred_signature_after": builder_deferred_signature_after,
        "same_builder_deferred_signature": same_builder_deferred_signature,
        "builder_deferred_unchanged": builder_deferred_unchanged,
        "planner_only_acceptance": planner_only_acceptance,
        "planner_acceptance_did_not_unstick_builder_deferral": planner_acceptance_did_not_unstick_builder_deferral,
        "no_progress": no_progress,
    }

    if no_progress:
        streak = int(previous.get("streak", 0)) + 1 if same_no_progress_signature else 1
        active = streak >= threshold
        if planner_acceptance_did_not_unstick_builder_deferral:
            reason = (
                "integrator accepted planner-only patch, but builder deferred queue "
                f"stayed blocked for {builder_deferred_signature_after}"
            )
        else:
            reason = (
                f"integrator accepted 0 patches; deferred queue "
                f"{'grew' if deferred_delta > 0 else 'stayed blocked'} for {signature}"
            )
        state[NO_PROGRESS_STATE_KEY] = {
            "active": active,
            "streak": streak,
            "threshold": threshold,
            "signature": signature,
            "builder_deferred_signature": builder_deferred_signature_after,
            "reason": reason,
            "last_seen_at": finished_at,
            "last_snapshot": after,
            "planner_requested_at": previous.get("planner_requested_at") if same_no_progress_signature else None,
        }
        metadata["progress_success"] = False
        metadata["just_tripped"] = active and not bool(previous.get("active"))
        return metadata

    if exit_code == 0 and accepted_delta > 0:
        state[NO_PROGRESS_STATE_KEY] = {
            "active": False,
            "streak": 0,
            "reason": "integrator accepted patches",
            "cleared_at": finished_at,
        }
        metadata["progress_success"] = True
        metadata["just_tripped"] = False
        return metadata

    if exit_code == 0 and deferred_delta < 0:
        state[NO_PROGRESS_STATE_KEY] = {
            "active": False,
            "streak": 0,
            "reason": "integrator resolved deferred patches",
            "cleared_at": finished_at,
        }
        metadata["progress_success"] = True
        metadata["just_tripped"] = False
        return metadata

    metadata["progress_success"] = exit_code == 0
    metadata["just_tripped"] = False
    return metadata

def last_integrator_metadata(state: dict[str, Any]) -> dict[str, Any] | None:
    history = state.get("history")
    if not isinstance(history, list):
        return None
    for entry in reversed(history):
        if not isinstance(entry, dict) or entry.get("role") != "integrator":
            continue
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            return None
        return metadata
    return None

def last_integrator_accepted_by_role(state: dict[str, Any]) -> dict[str, int] | None:
    metadata = last_integrator_metadata(state)
    if not metadata:
        return None
    raw = metadata.get("accepted_by_role")
    if not isinstance(raw, dict):
        return None
    return {role: int(raw.get(role, 0) or 0) for role in ("planner", "builder", "hardener")}

def post_builder_hardener_pending(state: dict[str, Any]) -> bool:
    history = state.get("history")
    if not isinstance(history, list):
        return False
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        if role == "hardener":
            return False
        if role != "integrator":
            continue
        if int(entry.get("exit_code") or 0) != 0:
            continue
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        accepted = metadata.get("accepted_by_role") if isinstance(metadata.get("accepted_by_role"), dict) else {}
        if int(accepted.get("builder") or 0) > 0:
            return True
    return False

def post_builder_hardener_reason(target: Path) -> str:
    info = latest_applied_role_manifest_info(target, "builder")
    if not info:
        return "builder patch integrated; hardener gets one post-builder verification pass"
    files = [str(item) for item in info.get("files") or []]
    return (
        f"builder patch integrated; hardener gets one post-builder verification pass for "
        f"{info['run_id']} ({format_file_list(files)})"
    )

def planner_fast_follow_reason_after_deferral_change(state: dict[str, Any]) -> str | None:
    if str(state.get("last_completed_role") or "") != "integrator":
        return None
    metadata = last_integrator_metadata(state)
    if not metadata:
        return None
    deferred_delta = metadata.get("deferred_delta_by_role")
    if not isinstance(deferred_delta, dict):
        return None
    planner_delta = int(deferred_delta.get("planner", 0) or 0)
    if planner_delta > 0:
        return "planner patch deferred by latest integration; fast-follow replanning"
    if planner_delta < 0:
        return "planner deferred patch resolved by latest integration; fast-follow replanning"
    return None

def planner_fast_follow_after_deferral(state: dict[str, Any]) -> bool:
    return planner_fast_follow_reason_after_deferral_change(state) is not None

def role_after_integrator(state: dict[str, Any]) -> tuple[str, str]:
    if post_builder_hardener_pending(state):
        return "hardener", "builder patch integrated; hardener gets one post-builder verification pass"
    accepted_by_role = last_integrator_accepted_by_role(state)
    if not accepted_by_role:
        return "builder", "builder-first policy: last integration has no source-role metadata"
    if int(accepted_by_role.get("builder", 0)) > 0:
        return "hardener", "builder patch integrated; hardener gets one verification pass"
    accepted_total = sum(int(value) for value in accepted_by_role.values())
    if accepted_total > 0:
        return "builder", "builder-first policy: last integration did not accept builder patches"
    return "builder", "builder-first policy: last integration accepted no patches"

def apply_timeout_circuit_breaker(
    state: dict[str, Any],
    role: str | None,
    reason: str,
    stop: bool,
    *,
    threshold: int | None = None,
) -> tuple[str | None, str, bool]:
    if stop or role is None:
        return role, reason, stop
    limit = role_timeout_streak_limit() if threshold is None else threshold
    if limit <= 0:
        return role, reason, stop
    streak = timeout_streak_count(state, role)
    if streak < limit:
        return role, reason, stop
    if role == "planner":
        return (
            None,
            f"planner lane timed out {streak} consecutive time(s); waiting for manual or environment recovery",
            False,
        )
    return (
        "planner",
        (
            f"{role} lane timed out {streak} consecutive time(s); "
            f"planner should diagnose before relaunching {role}. Previous reason: {reason}"
        ),
        False,
    )

def record_cycle(
    state: dict[str, Any],
    *,
    role: str,
    reason: str,
    exit_code: int,
    started_at: str,
    finished_at: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    counts = state.setdefault("role_counts", {})
    if isinstance(counts, dict):
        counts[role] = int(counts.get(role, 0)) + 1
    successes = state.setdefault("last_success_by_role", {})
    progress_success = bool(metadata.get("progress_success", exit_code == 0))
    if isinstance(successes, dict) and exit_code == 0 and progress_success:
        successes[role] = finished_at
        update_timeout_streak(state, role, timed_out=False, finished_at=finished_at)
    elif exit_code == ROLE_TIMEOUT_EXIT_CODE:
        update_timeout_streak(state, role, timed_out=True, finished_at=finished_at)
    history = state.setdefault("history", [])
    entry = {
        "role": role,
        "reason": reason,
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
        "progress_success": progress_success,
    }
    if metadata:
        entry["metadata"] = metadata
    if isinstance(history, list):
        history.append(entry)
        del history[:-STATE_HISTORY_LIMIT]
    if role == "planner" and no_progress_active(state, int(no_progress_info(state).get("threshold", DEFAULT_NO_PROGRESS_THRESHOLD))):
        info = no_progress_info(state)
        info["planner_requested_at"] = finished_at
        state[NO_PROGRESS_STATE_KEY] = info
    state["cycles"] = int(state.get("cycles", 0)) + 1
    state["last_completed_role"] = role
    state["last_completed_at"] = finished_at
    state["last_exit_code"] = exit_code
    state["last_progress_success"] = progress_success
    return state
