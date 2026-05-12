from __future__ import annotations

from .baseline import automation_status, baseline_preflight_needed, baseline_repair_route
from .locks import lock_is_active
from .progress import (
    no_progress_active,
    no_progress_info,
    planner_fast_follow_reason_after_deferral_change,
    post_builder_hardener_pending,
    post_builder_hardener_reason,
    role_after_integrator,
)
from .queue_state import (
    builder_triage_followup_info,
    duplicate_builder_deferral_info,
    queued_manifests,
    repeated_hardener_guardrail_deferral_info,
    target_has_multi_role,
    target_role_profile,
    unhandled_human_message_count,
)
from .state import *
from .tickets import candidate_done_hardener_catchup_reason, ticket_campaign_terminal, unverified_candidate_done_cluster_info

def choose_next(
    target: Path,
    state: dict[str, Any],
    no_progress_threshold: int = DEFAULT_NO_PROGRESS_THRESHOLD,
) -> tuple[str | None, str, bool]:
    status = automation_status(target)
    if status == "CRITICAL_STOP":
        return None, "automation status is CRITICAL_STOP", True
    if status not in ACTIVE_STATUSES:
        return None, f"automation status is {status}; waiting", False

    active, detail = lock_is_active(runtime_path(target, "target/codex_automation.lock"))
    if active:
        return None, f"main automation lock active: {detail}", False

    role_profile = target_role_profile(target)
    multi_role_available = target_has_multi_role(target)
    single_lane_profile = role_profile == "single_lane"

    ticket_state, ticket_reason = ticket_campaign_terminal(target)
    if ticket_state == "complete":
        return None, ticket_reason, True
    if ticket_state == "blocked":
        if baseline_preflight_needed(target):
            if single_lane_profile or not multi_role_available:
                return "single_lane", (
                    "ticket campaign is blocked, but baseline verification may be repairable; "
                    "running single-lane repair sprint"
                ), False
            return "integrator", (
                "ticket campaign is blocked, but baseline verification may be repairable; "
                "running clean-HEAD preflight"
            ), False
        blocked_baseline_route = baseline_repair_route(target, state)
        if blocked_baseline_route:
            if single_lane_profile or not multi_role_available:
                _role, route_reason, _stop = blocked_baseline_route
                return "single_lane", f"{route_reason}; running single-lane repair sprint", False
            return blocked_baseline_route
        return None, ticket_reason, True

    if single_lane_profile:
        return "single_lane", "single-lane automation profile selected; running continuous single-lane wrapper", False
    if not multi_role_available:
        return "single_lane", "multi-role files not found; running single-lane wrapper", False

    queue_depth = len(queued_manifests(target))
    if queue_depth:
        return "integrator", f"{queue_depth} queued role patch(es) need integration", False

    if baseline_preflight_needed(target):
        return "integrator", "baseline verification ledger is missing or stale; running clean-HEAD preflight", False

    baseline_route = baseline_repair_route(target, state)
    if baseline_route:
        return baseline_route

    duplicate_builder = duplicate_builder_deferral_info(target)
    if duplicate_builder:
        return (
            "integrator",
            (
                f"duplicate builder deferred patches need triage before more builder work: "
                f"{duplicate_builder['count']} patch(es), {duplicate_builder['signature']}, {duplicate_builder['files']}"
            ),
            False,
        )

    repeated_hardener_guardrail = repeated_hardener_guardrail_deferral_info(target)
    if repeated_hardener_guardrail:
        return (
            "planner",
            (
                "repeated hardener guardrail deferrals need repair planning before another normal hardener retry: "
                f"{repeated_hardener_guardrail['count']} patch(es) for "
                f"{repeated_hardener_guardrail['match_type']}={repeated_hardener_guardrail['match_value']}; "
                f"{repeated_hardener_guardrail['signature']}; root_cause={repeated_hardener_guardrail['root_cause']}; "
                "hardener must correct the deferral reason first, including "
                "`Test change rationale: <one concise reason this preserves or improves meaningful coverage>` "
                "when touching tests"
            ),
            False,
        )

    if no_progress_active(state, no_progress_threshold):
        info = no_progress_info(state)
        reason = str(info.get("reason") or "integrator made no patch progress")
        if not info.get("planner_requested_at"):
            return "planner", f"no-progress circuit breaker tripped: {reason}", False
        return None, f"no-progress circuit breaker active after planner handoff: {reason}", False

    if str(state.get("last_completed_role") or "") == "integrator":
        builder_followup = builder_triage_followup_info(target)
        if builder_followup:
            return (
                "planner",
                (
                    f"builder deferred patch triaged as {builder_followup['triage_status']}; "
                    f"planner should choose retry, supersede, or replace-from-current-HEAD for {builder_followup['run_id']}"
                ),
                False,
            )

    if unhandled_human_message_count(target):
        return "planner", "unhandled human message(s) need triage", False

    if post_builder_hardener_pending(state):
        return "hardener", post_builder_hardener_reason(target), False

    candidate_catchup = unverified_candidate_done_cluster_info(target)
    if candidate_catchup:
        return "hardener", candidate_done_hardener_catchup_reason(candidate_catchup), False

    fast_follow_reason = planner_fast_follow_reason_after_deferral_change(state)
    if fast_follow_reason:
        return "planner", fast_follow_reason, False

    last_role = str(state.get("last_completed_role") or "")
    if last_role == "integrator":
        role, reason = role_after_integrator(state)
        return role, reason, False
    if last_role == "builder":
        return "hardener", "builder lane completed without queued work; hardener gets the next look", False
    if last_role == "hardener":
        return "planner", "hardener completed; planner gets the next state-machine pass", False
    if last_role == "planner":
        return "builder", "planner completed; builder gets the next implementation pass", False
    return "builder", "builder lane is next runnable work", False

def conveyor_decision_queue(
    target: Path,
    state: dict[str, Any],
    next_role: str | None,
    next_reason: str,
    no_progress_threshold: int,
) -> list[dict[str, str]]:
    """Build a small display queue for observability; choose_next remains authoritative."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(role: str | None, state_name: str, reason: str) -> None:
        key = role or "idle"
        if key in seen:
            return
        seen.add(key)
        entries.append(
            {
                "role": key,
                "state": state_name,
                "reason": re.sub(r"\s+", " ", reason).strip()[:240],
            }
        )

    add(next_role, "next" if next_role else "idle", next_reason)
    if len(entries) >= DECISION_QUEUE_LIMIT:
        return entries

    status = automation_status(target)
    if status == "CRITICAL_STOP":
        add(None, "blocked", "automation status is CRITICAL_STOP")
        return entries[:DECISION_QUEUE_LIMIT]
    if status not in ACTIVE_STATUSES:
        add(None, "blocked", f"automation status is {status}; waiting")
        return entries[:DECISION_QUEUE_LIMIT]

    active, detail = lock_is_active(runtime_path(target, "target/codex_automation.lock"))
    if active:
        add(None, "blocked", f"main automation lock active: {detail}")
        return entries[:DECISION_QUEUE_LIMIT]

    role_profile = target_role_profile(target)
    multi_role_available = target_has_multi_role(target)
    single_lane_profile = role_profile == "single_lane"

    ticket_state, ticket_reason = ticket_campaign_terminal(target)
    if ticket_state == "complete":
        add(None, "blocked", ticket_reason)
        return entries[:DECISION_QUEUE_LIMIT]
    if ticket_state == "blocked":
        if baseline_preflight_needed(target):
            if single_lane_profile or not multi_role_available:
                add("single_lane", "ready", "ticket campaign is blocked, but baseline verification may be repairable")
            else:
                add("integrator", "ready", "ticket campaign is blocked, but baseline verification may be repairable")
        else:
            blocked_baseline_route = baseline_repair_route(target, state)
            if blocked_baseline_route:
                role, reason, _stop = blocked_baseline_route
                if single_lane_profile or (role is not None and not multi_role_available):
                    add("single_lane", "ready", reason)
                else:
                    add(role, "ready" if role else "blocked", reason)
            else:
                add(None, "blocked", ticket_reason)
        return entries[:DECISION_QUEUE_LIMIT]

    if single_lane_profile:
        add("single_lane", "ready", "single-lane automation profile selected; running continuous single-lane wrapper")
        return entries[:DECISION_QUEUE_LIMIT]
    if not multi_role_available:
        add("single_lane", "ready", "multi-role files not found; running single-lane wrapper")
        return entries[:DECISION_QUEUE_LIMIT]

    queue_depth = len(queued_manifests(target))
    if queue_depth:
        add("integrator", "ready", f"{queue_depth} queued role patch(es) need integration")

    duplicate_builder = duplicate_builder_deferral_info(target)
    if duplicate_builder:
        add(
            "integrator",
            "ready",
            (
                f"duplicate builder deferred patches need triage: {duplicate_builder['count']} patch(es), "
                f"{duplicate_builder['signature']}, {duplicate_builder['files']}"
            ),
        )

    repeated_hardener_guardrail = repeated_hardener_guardrail_deferral_info(target)
    if repeated_hardener_guardrail:
        add(
            "planner",
            "ready",
            (
                "repeated hardener guardrail deferrals need repair planning: "
                f"{repeated_hardener_guardrail['count']} patch(es) for "
                f"{repeated_hardener_guardrail['match_type']}={repeated_hardener_guardrail['match_value']}; "
                f"{repeated_hardener_guardrail['signature']}; root_cause={repeated_hardener_guardrail['root_cause']}"
            ),
        )

    no_progress_blocked = no_progress_active(state, no_progress_threshold)
    if no_progress_blocked:
        info = no_progress_info(state)
        reason = str(info.get("reason") or "integrator made no patch progress")
        if not info.get("planner_requested_at"):
            add("planner", "ready", f"no-progress circuit breaker tripped: {reason}")
        else:
            add(None, "blocked", f"no-progress circuit breaker active after planner handoff: {reason}")
    elif unhandled_human_message_count(target):
        add("planner", "ready", "unhandled human message(s) need triage")
    else:
        fast_follow_reason = planner_fast_follow_reason_after_deferral_change(state)
        if fast_follow_reason:
            add("planner", "ready", fast_follow_reason)

    if not no_progress_blocked and str(state.get("last_completed_role") or "") == "integrator":
        builder_followup = builder_triage_followup_info(target)
        if builder_followup:
            add(
                "planner",
                "ready",
                f"builder deferred patch triaged as {builder_followup['triage_status']}; choose retry, supersede, or replace-from-current-HEAD",
            )

    if post_builder_hardener_pending(state):
        add("hardener", "planned", post_builder_hardener_reason(target))
    else:
        candidate_catchup = unverified_candidate_done_cluster_info(target)
        if candidate_catchup:
            add("hardener", "planned", candidate_done_hardener_catchup_reason(candidate_catchup))

    last_role = str(state.get("last_completed_role") or "")
    if last_role == "integrator":
        role, reason = role_after_integrator(state)
        add(role, "planned", reason)
    elif last_role == "builder":
        add("hardener", "planned", "builder lane completed without queued work")
    elif last_role == "hardener":
        add("planner", "planned", "hardener completed; planner gets the next state-machine pass")
    elif last_role == "planner":
        add("builder", "planned", "planner completed; builder gets the next implementation pass")
    else:
        add("builder", "planned", "builder lane is the default momentum lane")

    add("hardener", "standby", "hardener verifies recently changed work when integration or builder output exists")
    add("builder", "standby", "builder can create the next implementation patch when planning is fresh")
    return entries[:DECISION_QUEUE_LIMIT]
