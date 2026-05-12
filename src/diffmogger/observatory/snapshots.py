from __future__ import annotations

import copy

from .common import *
from .git_state import baseline_verification_snapshot, git_snapshot, log_snapshot
from .queue_state import active_run, conveyor_health, decision_queue, progress_snapshot, queue_snapshot
from .scoring import action_plan_follow_through, recommendation_history_snapshot, scorecard_snapshot, worker_strategy_snapshot
from .self_review import first_review_snapshot, integration_safety_snapshot, self_review_snapshot, validation_snapshot
from diffmogger.runtime import ticket_run
from diffmogger.runtime.state_store import load_runner_state, runner_projection_path_for_target, state_snapshot


def observatory_safe_state(target: Path, canonical_state: dict[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(canonical_state)
    database = state.get("database") if isinstance(state.get("database"), dict) else {}
    database["path"] = target_rel(target, "target/orchestration.sqlite3")
    state["database"] = database
    projection = state.get("projection") if isinstance(state.get("projection"), dict) else {}
    projection["path"] = target_rel(target, "target/automation_conveyor_state.json")
    state["projection"] = projection
    projections = state.get("projections") if isinstance(state.get("projections"), dict) else {}
    projection_paths = {
        "conveyor": "target/automation_conveyor_state.json",
        "runner": "target/automation_runner.json",
    }
    for name, rel_path in projection_paths.items():
        item = projections.get(name) if isinstance(projections.get(name), dict) else {}
        if item:
            item["path"] = target_rel(target, rel_path)
            projections[name] = item
    if projections:
        state["projections"] = projections
    conveyor = state.get("conveyor_state") if isinstance(state.get("conveyor_state"), dict) else {}
    canonical = conveyor.get("canonical_state") if isinstance(conveyor.get("canonical_state"), dict) else {}
    if canonical:
        canonical["database_path"] = target_rel(target, "target/orchestration.sqlite3")
        conveyor["canonical_state"] = canonical
        state["conveyor_state"] = conveyor
    runner = state.get("runner_state") if isinstance(state.get("runner_state"), dict) else {}
    runner_canonical = runner.get("canonical_state") if isinstance(runner.get("canonical_state"), dict) else {}
    if runner_canonical:
        runner_canonical["database_path"] = target_rel(target, "target/orchestration.sqlite3")
        runner["canonical_state"] = runner_canonical
        state["runner_state"] = runner
    return state

STALE_TICKET_SOURCE_ISSUE = "ticket queue still needs to be populated or confirmed"

def is_stale_ticket_source_issue(value: Any) -> bool:
    return STALE_TICKET_SOURCE_ISSUE in str(value or "").lower()

def filtered_known_issues(target: Path, known_issue: str, known_issues: list[str]) -> tuple[str, list[str]]:
    if not (is_stale_ticket_source_issue(known_issue) or any(is_stale_ticket_source_issue(item) for item in known_issues)):
        return known_issue, known_issues
    ticket_state = ticket_run.ticket_source_state(target)
    if not bool(ticket_state.get("confirmed")):
        return known_issue, known_issues
    remaining = [item for item in known_issues if not is_stale_ticket_source_issue(item)]
    if is_stale_ticket_source_issue(known_issue):
        known_issue = remaining[0] if remaining else "No active issue summary."
    return known_issue, remaining

def parse_task_state(target: Path) -> dict[str, Any]:
    text = read_text(dpath(target, "docs/CODEX_AUTOMATION_TASKS.md"))
    status = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", text, re.MULTILINE)
    updated = re.search(r"^Last updated:\s*(.+)", text, re.MULTILINE)
    horizon = re.search(r"^-\s*Current horizon:\s*(.+)", text, re.MULTILINE)
    decision = re.search(r"^-\s*Advancement decision:\s*(.+)", text, re.MULTILINE)
    current_assessment = keyed_section_value(
        text,
        "Current Project State",
        ["Current assessment", "Current baseline", "Goal"],
    )
    known_issue = first_nonempty_section_line(text, "Known Issues") or "No active issue summary."
    known_issues = section_bullets(text, "Known Issues", limit=MAX_REVIEW_ITEMS)
    known_issue, known_issues = filtered_known_issues(target, known_issue, known_issues)
    worker_agents_allowed = task_bool_value(text, "Worker agents allowed", default=True)
    write_workers_allowed = task_bool_value(text, "Write-capable worker agents allowed", default=False)
    max_write_worker_count = task_int_value(text, "Max write worker count", default=0 if not write_workers_allowed else 1)
    validation = validation_snapshot(text)
    return {
        "status": status.group(1).strip() if status else "UNKNOWN",
        "last_updated": clean_text(updated.group(1), limit=120) if updated else "unknown",
        "horizon": clean_text(horizon.group(1), limit=160) if horizon else "unknown",
        "horizon_decision": clean_text(decision.group(1), limit=160) if decision else "unknown",
        "current_assessment": current_assessment or first_nonempty_section_line(text, "Current Project State") or "No current assessment recorded yet.",
        "best_next_milestone": first_nonempty_section_line(text, "Best Next Milestone") or "No milestone recorded yet.",
        "suggested_next_task": first_nonempty_section_line(text, "Suggested Next Sprint-Sized Task") or "No sprint task recorded yet.",
        "known_issue": known_issue,
        "known_issues": known_issues,
        "validation": validation,
        "integration_safety": integration_safety_snapshot(validation, target),
        "worker": {
            "agents_allowed": worker_agents_allowed,
            "write_workers_allowed": write_workers_allowed and worker_agents_allowed,
            "max_write_worker_count": max_write_worker_count if write_workers_allowed and worker_agents_allowed else 0,
        },
    }

def build_snapshot(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    generated_at = utc_now()
    canonical_state = state_snapshot(target)
    public_state = observatory_safe_state(target, canonical_state)
    conveyor = canonical_state.get("conveyor_state") if isinstance(canonical_state.get("conveyor_state"), dict) else {}
    runner = load_runner_state(runner_projection_path_for_target(target))
    queue = queue_snapshot(target)
    baseline_verification = baseline_verification_snapshot(target)
    task = parse_task_state(target)
    progress_text = read_text(dpath(target, "docs/MULTI_ROLE_PROGRESS.md"), limit=40_000)
    progress = progress_snapshot(progress_text)
    human_messages = canonical_state.get("human_messages") if isinstance(canonical_state.get("human_messages"), dict) else {}
    human_counts = human_messages.get("counts") if isinstance(human_messages.get("counts"), dict) else {}
    human = {
        "pending_requests": int(human_counts.get("pending_requests") or 0),
        "unhandled_inbox": int(human_counts.get("queued_notes") or 0) + int(human_counts.get("failed_notes") or 0),
        "outbound_records": int(human_counts.get("outbound_records") or 0),
    }
    conveyor_state = {
        "cycles": int(conveyor.get("cycles", 0) or 0),
        "updated_at": clean_text(conveyor.get("updated_at") or "never", limit=80),
        "last_decision": conveyor.get("last_decision") if isinstance(conveyor.get("last_decision"), dict) else {},
        "active_role_run": active_run(conveyor),
        "last_active_role_run": conveyor.get("last_active_role_run") if isinstance(conveyor.get("last_active_role_run"), dict) else {},
        "decision_queue": decision_queue(conveyor, queue),
        "health": conveyor_health(conveyor),
        "no_progress": conveyor.get("integrator_no_progress") if isinstance(conveyor.get("integrator_no_progress"), dict) else {},
        "history": list(conveyor.get("history") or [])[-MAX_HISTORY:] if isinstance(conveyor.get("history"), list) else [],
    }
    first_review = first_review_snapshot(target, task)
    scorecard = scorecard_snapshot(task, queue, conveyor_state, human, progress, first_review)
    follow_through = action_plan_follow_through(
        task,
        queue,
        conveyor_state,
        progress,
        scorecard.get("action_plan") if isinstance(scorecard.get("action_plan"), dict) else {},
    )
    recommendation_history = recommendation_history_snapshot(target, generated_at, follow_through, conveyor_state)
    worker_strategy = worker_strategy_snapshot(
        task,
        queue,
        conveyor_state,
        progress,
        scorecard.get("action_plan") if isinstance(scorecard.get("action_plan"), dict) else {},
        recommendation_history,
    )
    review = self_review_snapshot(
        task,
        queue,
        conveyor_state,
        human,
        progress,
        first_review,
        follow_through=follow_through,
        recommendation_history=recommendation_history,
        worker_strategy=worker_strategy,
    )
    review_items = review.get("items") if isinstance(review.get("items"), list) else []
    review_items.append(
        {
            "label": "Baseline verification",
            "body": (
                f"{baseline_verification.get('summary') or 'No baseline verification ledger recorded yet.'} "
                f"Next: {baseline_verification.get('next_action') or 'Run integrator baseline preflight.'}"
            ),
        },
    )
    review["items"] = review_items
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "target_name": target.name or "target",
        "task": task,
        "human": human,
        "git": git_snapshot(target),
        "queue": queue,
        "baseline_verification": baseline_verification,
        "runner": runner,
        "conveyor": conveyor_state,
        "state": public_state,
        "progress": progress,
        "scorecard": scorecard,
        "first_review": first_review,
        "follow_through": follow_through,
        "recommendation_history": recommendation_history,
        "worker_strategy": worker_strategy,
        "review": review,
        "empty_states": dict(EMPTY_STATES),
        "progress_recent": progress.get("recent_activity") or "No multi-role activity recorded yet.",
        "logs": log_snapshot(target),
    }
