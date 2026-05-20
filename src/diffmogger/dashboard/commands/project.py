from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *
from diffmogger.runtime.state_store import load_ticket_run_state

from .brief import command_brief_load
from .run_control import (
    automation_prerequisites,
    automation_status_snapshot,
    baseline_blocker_rows,
    latest_run_log,
    prereq_rows,
    run_controls_snapshot,
    worker_controls_snapshot,
)


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _done_status(value: Any) -> bool:
    return str(value or "").strip().lower().replace("-", "_") in {"done", "complete", "completed"}


def _ticket_status_counts(tickets: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ticket in tickets:
        status = str(ticket.get("status") or "pending").strip().lower().replace("-", "_")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _ticket_run_with_items(target: Path, projected_ticket_run: dict[str, Any]) -> dict[str, Any]:
    ticket_run = dict(projected_ticket_run)
    if _records(ticket_run.get("tickets")):
        return ticket_run

    try:
        runtime_ticket_run = load_ticket_run_state(target, read_only=True) or {}
    except Exception:
        return ticket_run

    runtime_tickets = _records(runtime_ticket_run.get("tickets"))
    if not runtime_tickets:
        return ticket_run

    merged = {**runtime_ticket_run, **ticket_run}
    merged["tickets"] = runtime_tickets
    if not _record(merged.get("counts")):
        merged["counts"] = _ticket_status_counts(runtime_tickets)
    return merged


def _dag_summary(execution_dag: dict[str, Any]) -> dict[str, int]:
    raw_summary = _record(execution_dag.get("summary"))
    if raw_summary:
        return {
            "total": int(raw_summary.get("total", 0) or 0),
            "pending": int(raw_summary.get("pending", 0) or 0),
            "ready": int(raw_summary.get("ready", 0) or 0),
            "running": int(raw_summary.get("running", 0) or 0),
            "completed": int(raw_summary.get("completed", 0) or 0),
            "blocked": int(raw_summary.get("blocked", 0) or 0),
            "failed": int(raw_summary.get("failed", 0) or 0),
            "skipped": int(raw_summary.get("skipped", 0) or 0),
        }
    counts = {
        "total": 0,
        "pending": 0,
        "ready": 0,
        "running": 0,
        "completed": 0,
        "blocked": 0,
        "failed": 0,
        "skipped": 0,
    }
    for node in _records(execution_dag.get("nodes")):
        counts["total"] += 1
        status = str(node.get("status") or "pending").strip().lower().replace("-", "_")
        if status in counts and status != "total":
            counts[status] += 1
        elif status in {"done", "complete", "passed", "applied"}:
            counts["completed"] += 1
        elif status in {"queued", "planned", "selected"}:
            counts["ready"] += 1
        elif status in {"in_progress", "active"}:
            counts["running"] += 1
        else:
            counts["pending"] += 1
    return counts


def _repair_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repair_terms = ("repair", "setup", "harness", "mock", "fixture", "defer", "split", "reframe", "validation", "unblock")
    rows: list[dict[str, Any]] = []
    for action in actions:
        haystack = " ".join(str(action.get(key) or "") for key in ("kind", "action_type", "reason", "summary")).lower()
        if any(term in haystack for term in repair_terms):
            rows.append(action)
    return rows


def command_project_load_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    brief = command_brief_load(args)
    dashboard_app = load_dashboard_module()
    raw_snapshot = build_observatory_snapshot(target)
    state = _record(raw_snapshot.get("state"))
    task = _record(raw_snapshot.get("task"))
    human = _record(raw_snapshot.get("human"))
    queue = _record(raw_snapshot.get("queue"))
    conveyor = _record(raw_snapshot.get("conveyor"))
    git = _record(raw_snapshot.get("git"))
    execution_dag = _record(state.get("execution_dag"))
    ticket_run = _ticket_run_with_items(target, _record(state.get("ticket_run")))
    tickets = _records(ticket_run.get("tickets"))
    remaining_tickets = [ticket for ticket in tickets if not _done_status(ticket.get("status"))]
    next_actions = _records(state.get("next_actions"))
    active_validation_jobs = _records(state.get("active_validation_jobs"))
    validation_receipts = _records(state.get("validation_receipts"))
    strategy = _record(raw_snapshot.get("worker_strategy"))
    automation = automation_status_snapshot(target, dashboard_app)
    controls = run_controls_snapshot(target, dashboard_app, raw_snapshot)
    prerequisites = automation_prerequisites(target, dashboard_app)
    setup_repair_inputs = [
        row for row in prereq_rows(prerequisites)
        if row["required"] and not row["ok"]
    ]
    setup_repair_inputs.extend(baseline_blocker_rows(raw_snapshot))
    files = [
        describe_registered_file(target, record)
        for record in file_registry(dashboard_app).values()
    ]
    return {
        "target": target_metadata(target),
        "setup": {
            "project_name": str(brief.get("project_name") or target.name),
            "project_mode": brief.get("project_mode") or "unknown",
            "configured": bool(target_metadata(target)["automation_task_exists"]),
            "status": task.get("status") or "UNKNOWN",
            "horizon": task.get("horizon") or "unknown",
            "task": {
                "status": task.get("status") or "UNKNOWN",
                "horizon": task.get("horizon") or "unknown",
                "last_updated": task.get("last_updated"),
                "suggested_next_task": task.get("suggested_next_task"),
                "bootstrap_status": task.get("bootstrap_status"),
                "bootstrap_pending": task.get("bootstrap_pending"),
            },
            "intake": brief.get("intake") or {},
            "draft_intake": brief.get("draft_intake") or {},
            "dashboard_state": brief.get("dashboard_state") or {},
            "context_files": brief.get("context_files") or [],
            "detected": brief.get("detected") or {},
            "git": git,
            "files": files,
            "snapshot_generated_at": raw_snapshot.get("generated_at"),
        },
        "scheduler": {
            "selected_action": _record(state.get("selected_candidate") or state.get("selected_scheduler_candidate")),
            "next_actions": next_actions,
            "decision_queue": _records(conveyor.get("decision_queue")),
            "active_role_run": _record(conveyor.get("active_role_run") or state.get("active_role_run")),
            "why_not_parallel": _record(state.get("why_not_parallel")),
            "scheduler_parallel_dry_run": _record(state.get("scheduler_parallel_dry_run")),
            "blocked_candidates": _records(state.get("blocked_parallel_candidates")),
            "skipped_candidates": _records(state.get("skipped_scheduler_candidates") or state.get("skipped_candidates")),
        },
        "dag": {
            "summary": _dag_summary(execution_dag),
            "execution_dag": execution_dag,
            "proposed_execution_groups": _records(state.get("proposed_execution_groups")),
            "active_execution_groups": _records(state.get("active_execution_groups")),
            "recent_execution_groups": _records(state.get("recent_execution_groups")),
            "recently_completed_execution_groups": _records(state.get("recently_completed_execution_groups")),
            "active_read_only_workers": _records(state.get("active_read_only_workers")),
            "active_write_workers": _records(state.get("active_write_workers")),
            "completed_worker_reports": _records(state.get("completed_worker_reports")),
            "queued_worker_patches": _records(state.get("queued_worker_patches")),
            "write_worker_conflicts": _records(state.get("write_worker_conflicts")),
            "integration_backlog_from_parallel_workers": _records(state.get("integration_backlog_from_parallel_workers")),
            "worker_patch_integration_preflight": _record(state.get("worker_patch_integration_preflight")),
            "recent_outcomes": _records(state.get("recent_outcomes") or state.get("recent_events")),
            "queue": queue,
        },
        "tickets": {
            "counts": _record(ticket_run.get("counts")),
            "items": tickets,
            "remaining": remaining_tickets,
            "remaining_count": len(remaining_tickets),
            "source": ticket_run.get("source") or ticket_run.get("path") or "",
        },
        "human_input": {
            "pending_requests": int(human.get("pending_requests", 0) or 0),
            "unhandled_records": int(human.get("unhandled_inbox", 0) or 0),
            "unhandled_inbox": int(human.get("unhandled_inbox", 0) or 0),
            "outbound_records": int(human.get("outbound_records", 0) or 0),
            "summary": human.get("summary") or "",
        },
        "validation_repair": {
            "validation": _record(task.get("validation")),
            "integration_safety": _record(task.get("integration_safety")),
            "active_validation_jobs": active_validation_jobs,
            "validation_job_summary": _record(state.get("validation_job_summary")),
            "validation_receipts": validation_receipts,
            "repair_actions": _repair_actions(next_actions),
            "open_blockers": _records(state.get("open_blockers")),
            "setup_repair_inputs": setup_repair_inputs,
        },
        "controls": {
            **controls,
            "automation": automation,
            "worker_strategy": strategy,
            "worker_controls": worker_controls_snapshot(target, dashboard_app, strategy),
            "latest_worker_result": dashboard_app.latest_worker_result(target),
            "run_log": latest_run_log(target, dashboard_app),
        },
    }

def configured_recent_projects() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    env_value = os.environ.get("DIFFMOGGER_RECENT_PROJECTS", "")
    for raw in [item for item in env_value.split(os.pathsep) if item.strip()]:
        target = str(Path(raw).expanduser())
        if target in seen:
            continue
        seen.add(target)
        records.append({"target": target, "source": "environment", "label": Path(target).name})
    return records

def command_project_list_recent(_args: argparse.Namespace) -> dict[str, Any]:
    return {"projects": configured_recent_projects()}
