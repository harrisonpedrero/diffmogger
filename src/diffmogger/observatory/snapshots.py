from __future__ import annotations

import copy

from .common import *
from .git_state import baseline_verification_snapshot, git_snapshot, log_snapshot
from .queue_state import active_run, conveyor_health, decision_queue, progress_snapshot, queue_snapshot
from .scoring import action_plan_follow_through, recommendation_history_snapshot, scorecard_snapshot, worker_strategy_snapshot
from .self_review import first_review_snapshot, integration_safety_snapshot, self_review_snapshot, validation_snapshot
from diffmogger.runtime import ticket_run
from diffmogger.runtime.state_store import load_runner_state, runner_projection_path_for_target, state_snapshot


def redact_machine_paths(machine: dict[str, Any]) -> dict[str, Any]:
    work_item = machine.get("work_item") if isinstance(machine.get("work_item"), dict) else {}
    if work_item:
        work_item["repo_root"] = "."
        machine["work_item"] = work_item
    policy = machine.get("policy") if isinstance(machine.get("policy"), dict) else {}
    if policy:
        policy["target"] = "."
        machine["policy"] = policy
    capability = machine.get("capability_manifest") if isinstance(machine.get("capability_manifest"), dict) else {}
    repo = capability.get("repo") if isinstance(capability.get("repo"), dict) else {}
    if repo:
        repo["root"] = "."
        capability["repo"] = repo
        machine["capability_manifest"] = capability
    return machine


def target_path_aliases(target: Path) -> list[str]:
    aliases = {str(target), str(target.expanduser().resolve())}
    for value in list(aliases):
        if value.startswith("/private/var/"):
            aliases.add(value.replace("/private/var/", "/var/", 1))
        elif value.startswith("/var/"):
            aliases.add(value.replace("/var/", "/private/var/", 1))
    return sorted((item for item in aliases if item), key=len, reverse=True)


def scrub_target_path_values(value: Any, aliases: list[str]) -> Any:
    if isinstance(value, str):
        scrubbed = value
        for alias in aliases:
            scrubbed = scrubbed.replace(alias, "<target>")
        return scrubbed
    if isinstance(value, list):
        return [scrub_target_path_values(item, aliases) for item in value]
    if isinstance(value, dict):
        return {key: scrub_target_path_values(item, aliases) for key, item in value.items()}
    return value


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
        "machine": "target/orchestration.sqlite3",
        "capabilities": "target/orchestration.sqlite3",
        "automation_control": "target/orchestration.sqlite3",
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
    conveyor_machine = conveyor.get("state_machine") if isinstance(conveyor.get("state_machine"), dict) else {}
    if conveyor_machine:
        conveyor["state_machine"] = redact_machine_paths(conveyor_machine)
    if conveyor:
        state["conveyor_state"] = conveyor
    top_machine = state.get("conveyor_machine") if isinstance(state.get("conveyor_machine"), dict) else {}
    if top_machine:
        state["conveyor_machine"] = redact_machine_paths(top_machine)
    capability = state.get("capability_manifest") if isinstance(state.get("capability_manifest"), dict) else {}
    capability_repo = capability.get("repo") if isinstance(capability.get("repo"), dict) else {}
    if capability_repo:
        capability_repo["root"] = "."
        capability["repo"] = capability_repo
        state["capability_manifest"] = capability
    runner = state.get("runner_state") if isinstance(state.get("runner_state"), dict) else {}
    runner_canonical = runner.get("canonical_state") if isinstance(runner.get("canonical_state"), dict) else {}
    if runner_canonical:
        runner_canonical["database_path"] = target_rel(target, "target/orchestration.sqlite3")
        runner["canonical_state"] = runner_canonical
        state["runner_state"] = runner
    return scrub_target_path_values(state, target_path_aliases(target))

STALE_TICKET_SOURCE_MARKERS = (
    "ticket queue still needs to be populated or confirmed",
    "role-worktree ticket queue path mismatch",
    "role-worktree ticket helper visibility",
    "isolated role-worktree `ticket_run.py",
    "isolated role worktree `ticket_run.py",
    "canonical ticket helper read-only commands currently fail",
    "configured full-suite ticket helper commands",
    "sqlite3.operationalerror: unable to open database file",
    "worktrees cannot currently run canonical `ticket_run.py",
    "worktrees cannot currently run canonical ticket_run.py",
    "role worktree still cannot select or update",
    "role worktrees cannot currently mutate dashboard ticket state",
)
ROLE_WORKTREE_TICKET_SOURCE_MARKERS = (
    "role-worktree",
    "role worktree",
    "role worktrees",
    "isolated role-worktree",
    "isolated role worktree",
)
BOILERPLATE_GUIDANCE_MARKERS = (
    "continuous conveyor automation should use `scripts/run_conveyor_automation.sh`",
    "continuous conveyor automation should use `.diffmogger/scripts/run_conveyor_automation.sh`",
)
VERIFICATION_BOOTSTRAP_MARKER = "verification commands may need adjustment after bootstrap"

def is_stale_ticket_source_issue(value: Any) -> bool:
    lower = str(value or "").lower()
    return any(marker in lower for marker in STALE_TICKET_SOURCE_MARKERS)

def is_role_worktree_ticket_source_issue(value: Any) -> bool:
    lower = str(value or "").lower()
    return is_stale_ticket_source_issue(lower) and any(marker in lower for marker in ROLE_WORKTREE_TICKET_SOURCE_MARKERS)

def is_boilerplate_guidance_issue(value: Any) -> bool:
    lower = str(value or "").lower()
    return any(marker in lower for marker in BOILERPLATE_GUIDANCE_MARKERS)

def is_resolved_verification_bootstrap_issue(value: Any, validation: dict[str, Any] | None) -> bool:
    if VERIFICATION_BOOTSTRAP_MARKER not in str(value or "").lower():
        return False
    counts = validation.get("counts") if isinstance(validation, dict) and isinstance(validation.get("counts"), dict) else {}
    return int(counts.get("pass", 0) or 0) > 0 and int(counts.get("fail", 0) or 0) == 0

def is_filtered_known_issue(value: Any, validation: dict[str, Any] | None) -> bool:
    return is_boilerplate_guidance_issue(value) or is_resolved_verification_bootstrap_issue(value, validation)

def role_worktree_ticket_helper_current(target: Path) -> bool:
    worktree_root = target_path(target, "target/automation_worktrees")
    if not worktree_root.exists():
        return False
    helper_paths = [
        helper
        for helper in worktree_root.glob("*/*/.diffmogger/lib/diffmogger/runtime/ticket_run.py")
        if helper.is_file()
    ]
    if not helper_paths:
        return False
    try:
        latest = max(helper_paths, key=lambda path: path.stat().st_mtime)
        text = latest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "resolve_ticket_target" in text and "canonical_target_from_role_worktree" in text

def filtered_known_issues(
    target: Path,
    known_issue: str,
    known_issues: list[str],
    *,
    validation: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    all_issues = [known_issue, *known_issues]
    should_filter_stale_ticket = any(is_stale_ticket_source_issue(item) for item in all_issues)
    if should_filter_stale_ticket:
        ticket_state = ticket_run.ticket_source_state(target)
        if not bool(ticket_state.get("confirmed")):
            should_filter_stale_ticket = False
        elif any(is_role_worktree_ticket_source_issue(item) for item in all_issues) and not role_worktree_ticket_helper_current(target):
            should_filter_stale_ticket = False
    remaining = [
        item
        for item in known_issues
        if not is_filtered_known_issue(item, validation)
        and not (should_filter_stale_ticket and is_stale_ticket_source_issue(item))
    ]
    if is_filtered_known_issue(known_issue, validation) or (should_filter_stale_ticket and is_stale_ticket_source_issue(known_issue)):
        known_issue = remaining[0] if remaining else "No active issue summary."
    return known_issue, remaining

def validation_from_receipts(canonical_state: dict[str, Any]) -> dict[str, Any]:
    machine = canonical_state.get("conveyor_machine") if isinstance(canonical_state.get("conveyor_machine"), dict) else {}
    receipts = [item for item in list(machine.get("validation_receipts") or []) if isinstance(item, dict)]
    has_explicit_safety = any(str(item.get("kind") or "") == "integration_safety" for item in receipts)
    counts = {"pass": 0, "fail": 0, "warn": 0, "pending": 0, "info": 0}
    items: list[dict[str, str]] = []
    for receipt in receipts[:MAX_CHECK_ITEMS]:
        if str(receipt.get("kind") or "") == "integration_safety":
            continue
        command = clean_text(receipt.get("command") or receipt.get("kind") or "validation receipt", limit=360)
        if (
            has_explicit_safety
            and str(receipt.get("kind") or "") == "legacy_task_check"
            and any(marker in command.lower() for marker in ("integration_safety", "integration safety", "integration-safety", "scripts/check_integration_safety.py"))
        ):
            continue
        raw_status = str(receipt.get("status") or "info").lower()
        status = {
            "passed": "pass",
            "ok": "pass",
            "success": "pass",
            "failed": "fail",
            "blocked": "fail",
            "warning": "warn",
            "running": "pending",
        }.get(raw_status, raw_status)
        if status not in counts:
            status = "info"
        counts[status] += 1
        kind = clean_text(receipt.get("kind") or "validation", limit=80)
        items.append({"status": status, "text": f"{kind}: {command}"})
    if not items:
        return {"summary": "No validation results recorded yet.", "counts": counts, "items": []}
    if counts["fail"]:
        summary = f"{counts['pass']} pass, {counts['fail']} fail or environment note."
    elif counts["pass"]:
        summary = f"{counts['pass']} passing check(s) recorded."
    elif counts["pending"]:
        summary = "Validation is recorded as not run yet."
    else:
        summary = "Validation notes are recorded without pass/fail status."
    return {"summary": summary, "counts": counts, "items": items, "source": "validation_receipts"}


def task_state_from_canonical(target: Path, canonical_state: dict[str, Any]) -> dict[str, Any]:
    control = canonical_state.get("automation_control") if isinstance(canonical_state.get("automation_control"), dict) else {}
    validation = validation_from_receipts(canonical_state)
    known_issue = clean_text(control.get("known_issue") or "No active issue summary.", limit=240)
    known_issues = [
        clean_text(item, limit=260)
        for item in list(control.get("known_issues") or [])[:MAX_REVIEW_ITEMS]
        if str(item).strip()
    ]
    known_issue, known_issues = filtered_known_issues(target, known_issue, known_issues, validation=validation)
    worker = control.get("worker") if isinstance(control.get("worker"), dict) else {}
    worker_agents_allowed = bool(worker.get("agents_allowed", True))
    write_workers_allowed = bool(worker.get("write_workers_allowed", False)) and worker_agents_allowed
    max_write_worker_count = int(worker.get("max_write_worker_count", 0) or 0)
    return {
        "status": clean_text(control.get("status") or "UNKNOWN", limit=80),
        "last_updated": clean_text(control.get("last_updated") or control.get("updated_at") or "unknown", limit=120),
        "horizon": clean_text(control.get("horizon") or "unknown", limit=160),
        "horizon_decision": clean_text(control.get("horizon_decision") or "unknown", limit=160),
        "current_assessment": clean_text(
            control.get("current_assessment") or "No current assessment recorded yet.",
            limit=260,
        ),
        "best_next_milestone": clean_text(control.get("best_next_milestone") or "No milestone recorded yet.", limit=260),
        "suggested_next_task": clean_text(control.get("suggested_next_task") or "No sprint task recorded yet.", limit=260),
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
    task = task_state_from_canonical(target, canonical_state)
    progress = progress_snapshot(target)
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
