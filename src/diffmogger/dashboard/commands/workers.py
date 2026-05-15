from __future__ import annotations

from contextlib import closing

from ..errors import *
from ..jsonio import *
from ..target import *

from .run_control import run_subprocess_streamed
from diffmogger.runtime.state_store import (
    StateEvent,
    active_resource_leases_conn,
    can_start_execution_group,
    can_start_worker,
    connect,
    current_conflicting_resource_leases_conn,
    database_path_for_target,
    ensure_automation_control_conn,
    launch_read_only_execution_group_conn,
    launch_write_execution_group_conn,
    plan_parallel_execution_groups_conn,
    release_resource_lease_conn,
    run_parallel_validation_conn,
    stable_json,
    state_snapshot,
    utc_now,
    validation_job_read_model_conn,
    validation_jobs_conn,
    worker_agents_conn,
    worker_contracts_conn,
    worker_patch_read_model_conn,
    append_event,
    worker_reports_read_model_conn,
)


def _budget_check_or_raise(target: Path, check_kind: str) -> dict[str, Any]:
    with closing(connect(database_path_for_target(target))) as conn:
        ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
        if check_kind == "read_only":
            check = can_start_worker(conn, "read_only", owner_role="dashboard")
        elif check_kind == "write":
            check = can_start_worker(conn, "write", owner_role="dashboard")
        else:
            check = can_start_execution_group(conn, "mixed", owner_role="integrator")
    if not bool(check.get("allowed")):
        raise BackendError(
            "Parallelism budget prevents starting this worker.",
            error_type="parallelism_budget_exhausted",
            details=check,
        )
    return check

def command_worker_run_read_only(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    strategy = dashboard_app.dashboard_worker_strategy(target)
    name = compact_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    if name not in dashboard_app.WORKER_REPORT_STRATEGIES:
        raise BackendError(
            "A read-only worker is not supported by the current worker strategy.",
            error_type="worker_not_supported",
            details={"strategy": name},
        )
    budget_check = _budget_check_or_raise(target, "read_only")
    run_id = dashboard_app.dashboard_run_id("dashboard-worker-report")
    result = run_subprocess_streamed(
        args,
        dashboard_app.read_only_worker_command(target, strategy, run_id=run_id),
        cwd=target,
        stage="worker",
    )
    summary = run_subprocess_streamed(
        args,
        dashboard_app.worker_summary_command(target, run_id),
        cwd=target,
        stage="worker-summary",
    )
    write_dashboard_action_state(target, last_action="read_only_worker_completed", updates={"last_worker_run_id": run_id})
    return {
        "target": target_metadata(target),
        "run_id": run_id,
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "strategy": strategy,
        "budget_check": budget_check,
        "result": result,
        "summary": summary,
        "latest_worker_result": dashboard_app.latest_worker_result(target),
    }

def command_worker_run_write(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    strategy = dashboard_app.dashboard_worker_strategy(target)
    name = compact_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    if name != "WRITE_WORKERS":
        raise BackendError(
            "A write worker is not supported by the current worker strategy.",
            error_type="worker_not_supported",
            details={"strategy": name},
        )
    budget_check = _budget_check_or_raise(target, "write")
    try:
        ownership = dashboard_app.normalize_worker_ownership_scope(args.ownership)
    except ValueError as exc:
        raise BackendError(str(exc), exit_code=2, error_type="invalid_ownership") from exc
    run_id = dashboard_app.dashboard_run_id("dashboard-write-worker")
    result = run_subprocess_streamed(
        args,
        dashboard_app.write_worker_command(target, strategy, ownership, run_id=run_id),
        cwd=target,
        stage="worker",
    )
    summary = run_subprocess_streamed(
        args,
        dashboard_app.worker_summary_command(target, run_id),
        cwd=target,
        stage="worker-summary",
    )
    write_dashboard_action_state(target, last_action="write_worker_completed", updates={"last_worker_run_id": run_id})
    return {
        "target": target_metadata(target),
        "run_id": run_id,
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "strategy": strategy,
        "budget_check": budget_check,
        "ownership": ownership,
        "result": result,
        "summary": summary,
        "latest_worker_result": dashboard_app.latest_worker_result(target),
    }

def command_worker_run_integrator(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    strategy = dashboard_app.dashboard_worker_strategy(target)
    name = compact_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    if name != "INTEGRATION_ONLY":
        raise BackendError(
            "Integrator launch is not supported by the current worker strategy.",
            error_type="worker_not_supported",
            details={"strategy": name},
        )
    budget_check = _budget_check_or_raise(target, "integrator")
    run_id = dashboard_app.dashboard_run_id("dashboard-integrator")
    result = run_subprocess_streamed(
        args,
        dashboard_app.integration_only_command(target, run_id=run_id),
        cwd=target,
        stage="worker",
    )
    write_dashboard_action_state(target, last_action="integrator_worker_completed", updates={"last_worker_run_id": run_id})
    return {
        "target": target_metadata(target),
        "run_id": run_id,
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "strategy": strategy,
        "budget_check": budget_check,
        "result": result,
    }


def command_worker_launch_read_only_group(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    with closing(connect(database_path_for_target(target))) as conn:
        ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
        plan_parallel_execution_groups_conn(conn, target, selected_by="dashboard.worker_fanout")
        result = launch_read_only_execution_group_conn(
            conn,
            target,
            execution_group_id=str(getattr(args, "execution_group_id", "") or ""),
            selected_by="dashboard",
            max_workers=int(getattr(args, "max_workers", 2) or 2),
        )
    write_dashboard_action_state(
        target,
        last_action="read_only_worker_group_launched",
        updates={"last_worker_run_id": result.get("run_id") or ""},
    )
    return {
        "target": target_metadata(target),
        "result": result,
    }


def command_worker_launch_write_group(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    with closing(connect(database_path_for_target(target))) as conn:
        ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
        plan_parallel_execution_groups_conn(conn, target, selected_by="dashboard.write_worker_fanout")
        result = launch_write_execution_group_conn(
            conn,
            target,
            execution_group_id=str(getattr(args, "execution_group_id", "") or ""),
            selected_by="dashboard",
            max_workers=int(getattr(args, "max_workers", 0) or 0) or None,
        )
    write_dashboard_action_state(
        target,
        last_action="write_worker_group_launched",
        updates={"last_worker_run_id": result.get("run_id") or ""},
    )
    return {
        "target": target_metadata(target),
        "result": result,
    }


def _json_cell(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _execution_group_item_dict(row: Any) -> dict[str, Any]:
    required_leases = _json_cell(row["required_leases_json"], [])
    payload = _json_cell(row["payload_json"], {})
    return {
        "item_id": str(row["item_id"]),
        "execution_group_id": str(row["execution_group_id"] or ""),
        "task_id": str(row["task_id"] or ""),
        "graph_task_node_id": str(row["graph_task_node_id"] or ""),
        "owner_role": str(row["owner_role"] or ""),
        "action_kind": str(row["action_kind"] or ""),
        "required_leases": required_leases if isinstance(required_leases, list) else [],
        "context_pack_id": str(row["context_pack_id"] or ""),
        "status": str(row["status"] or ""),
        "reason": str(row["reason"] or ""),
        "payload": payload if isinstance(payload, dict) else {},
    }


def _execution_group_dict(conn: Any, row: Any) -> dict[str, Any]:
    payload = _json_cell(row["payload_json"], {})
    group_id = str(row["execution_group_id"])
    items = [
        _execution_group_item_dict(item)
        for item in conn.execute(
            """
            SELECT *
            FROM execution_group_items
            WHERE execution_group_id = ?
            ORDER BY item_id
            """,
            (group_id,),
        ).fetchall()
    ]
    workers = worker_agents_conn(conn, limit=50)
    workers = [worker for worker in workers if worker.get("execution_group_id") == group_id]
    validation_jobs = validation_jobs_conn(conn, limit=50)
    validation_jobs = [job for job in validation_jobs if job.get("execution_group_id") == group_id]
    patches = worker_patch_read_model_conn(conn)
    patch_items = [
        patch
        for collection in (
            patches.get("queued_worker_patches", []),
            patches.get("write_worker_conflicts", []),
            patches.get("integration_backlog_from_parallel_workers", []),
        )
        for patch in (collection if isinstance(collection, list) else [])
        if isinstance(patch, dict) and patch.get("execution_group_id") == group_id
    ]
    return {
        "execution_group_id": group_id,
        "status": str(row["status"] or ""),
        "mode": str(row["mode"] or ""),
        "created_at": str(row["created_at"] or ""),
        "started_at": str(row["started_at"] or ""),
        "finished_at": str(row["finished_at"] or ""),
        "selected_by": str(row["selected_by"] or ""),
        "reason": str(row["reason"] or ""),
        "payload": payload if isinstance(payload, dict) else {},
        "items": items,
        "workers": workers,
        "validation_jobs": validation_jobs,
        "patches": patch_items,
    }


def _execution_groups_by_status(conn: Any, statuses: set[str], *, limit: int = 12) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""
        SELECT *
        FROM execution_groups
        WHERE status IN ({placeholders})
        ORDER BY COALESCE(NULLIF(finished_at, ''), NULLIF(started_at, ''), created_at) DESC,
                 execution_group_id DESC
        LIMIT ?
        """,
        (*sorted(statuses), max(1, int(limit))),
    ).fetchall()
    return [_execution_group_dict(conn, row) for row in rows]


def _execution_group_by_id(conn: Any, group_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM execution_groups WHERE execution_group_id = ?", (group_id,)).fetchone()
    return _execution_group_dict(conn, row) if row else {}


def _dashboard_parallel_read_model(target: Path) -> dict[str, Any]:
    snapshot = state_snapshot(target)
    with closing(connect(database_path_for_target(target))) as conn:
        proposed = _execution_groups_by_status(conn, {"proposed"}, limit=16)
        active = _execution_groups_by_status(conn, {"running"}, limit=16)
        recent = _execution_groups_by_status(conn, {"completed", "failed", "cancelled"}, limit=16)
        contracts = worker_contracts_conn(conn)[:40]
        validation_jobs = validation_job_read_model_conn(conn)
        return {
            "target": target_metadata(target),
            "proposed_execution_groups": snapshot.get("proposed_execution_groups", []),
            "proposed_execution_group_rows": proposed,
            "active_execution_groups": active,
            "recent_execution_groups": recent,
            "blocked_parallel_candidates": snapshot.get("blocked_parallel_candidates", []),
            "parallelization_summary": snapshot.get("parallelization_summary", {}),
            "parallelism_budgets": snapshot.get("parallelism_budgets", []),
            "active_parallel_counts": snapshot.get("active_parallel_counts", {}),
            "budget_exhaustion_reasons": snapshot.get("budget_exhaustion_reasons", []),
            "worker_contracts": contracts,
            "worker_reports": worker_reports_read_model_conn(conn),
            "active_leases": active_resource_leases_conn(conn),
            "conflicting_leases": current_conflicting_resource_leases_conn(conn),
            "validation_jobs": validation_jobs,
            "integration_backlog_from_parallel_workers": snapshot.get("integration_backlog_from_parallel_workers", []),
            "queued_worker_patches": snapshot.get("queued_worker_patches", []),
            "write_worker_conflicts": snapshot.get("write_worker_conflicts", []),
            "warnings": _parallel_warnings(snapshot),
        }


def _parallel_warnings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    control = snapshot.get("automation_control") if isinstance(snapshot.get("automation_control"), dict) else {}
    worker = control.get("worker") if isinstance(control.get("worker"), dict) else {}
    if not bool(worker.get("write_workers_allowed")):
        warnings.append({"kind": "write_workers_disabled", "severity": "info", "message": "Write workers are disabled for this target."})
    for item in snapshot.get("stale_graph_warnings", []) if isinstance(snapshot.get("stale_graph_warnings"), list) else []:
        if isinstance(item, dict):
            warnings.append({"kind": item.get("kind") or "graph_stale", "severity": item.get("severity") or "warn", "message": item.get("message") or "Graph context may be stale."})
    for item in snapshot.get("budget_exhaustion_reasons", []) if isinstance(snapshot.get("budget_exhaustion_reasons"), list) else []:
        if isinstance(item, dict):
            warnings.append({"kind": "budget_exhausted", "severity": "warn", "message": item.get("reason") or "A parallelism budget is exhausted."})
    if bool(snapshot.get("worker_finding_disposition_required")):
        warnings.append({"kind": "worker_report_disposition", "severity": "warn", "message": "One or more worker reports need main-agent disposition."})
    backlog = snapshot.get("integration_backlog_from_parallel_workers") if isinstance(snapshot.get("integration_backlog_from_parallel_workers"), list) else []
    if len(backlog) >= 3:
        warnings.append({"kind": "integration_backlog_large", "severity": "warn", "message": f"{len(backlog)} worker patches are waiting for serialized integration."})
    for candidate in snapshot.get("blocked_parallel_candidates", []) if isinstance(snapshot.get("blocked_parallel_candidates"), list) else []:
        if isinstance(candidate, dict) and str(candidate.get("reason_kind") or "") in {"unknown_impact", "unknown_write_impact"}:
            warnings.append({"kind": "unknown_impact", "severity": "warn", "message": candidate.get("reason") or "A candidate was skipped because impact was unknown."})
            break
    return warnings


def command_execution_group_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    data = _dashboard_parallel_read_model(target)
    group_id = str(getattr(args, "execution_group_id", "") or "").strip()
    if group_id:
        with closing(connect(database_path_for_target(target))) as conn:
            data["execution_group"] = _execution_group_by_id(conn, group_id)
    return data


def command_validation_jobs_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    with closing(connect(database_path_for_target(target))) as conn:
        ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
        return {
            "target": target_metadata(target),
            "validation_jobs": validation_job_read_model_conn(conn),
            "jobs": validation_jobs_conn(conn, limit=50),
        }


def command_execution_group_start(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    group_id = str(getattr(args, "execution_group_id", "") or "").strip()
    mode = str(getattr(args, "mode", "") or "auto").strip().lower()
    max_workers = int(getattr(args, "max_workers", 0) or 0)
    with closing(connect(database_path_for_target(target))) as conn:
        ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
        if mode == "validation" or (mode == "auto" and not group_id):
            result = run_parallel_validation_conn(conn, target, selected_by="dashboard.validation")
        else:
            plan_parallel_execution_groups_conn(conn, target, selected_by="dashboard.execution_group_start")
            group = _execution_group_by_id(conn, group_id) if group_id else {}
            payload = group.get("payload") if isinstance(group.get("payload"), dict) else {}
            execution_mode = mode if mode != "auto" else str(payload.get("execution_mode") or group.get("mode") or "read_only")
            if execution_mode in {"read_only", "dry_run"}:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    selected_by="dashboard",
                    max_workers=max_workers or 2,
                )
            elif execution_mode in {"write_workers", "write"}:
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    selected_by="dashboard",
                    max_workers=max_workers or None,
                )
            else:
                raise BackendError(
                    "This execution group mode cannot be started from the dashboard.",
                    exit_code=2,
                    error_type="unsupported_execution_group_mode",
                    details={"execution_group_id": group_id, "mode": execution_mode},
                )
    write_dashboard_action_state(target, last_action="execution_group_started", updates={"last_execution_group_id": result.get("execution_group_id", group_id)})
    return {"target": target_metadata(target), "result": result}


def command_execution_group_cancel(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    group_id = str(getattr(args, "execution_group_id", "") or "").strip()
    if not group_id:
        raise BackendError("An execution group id is required.", exit_code=2, error_type="missing_execution_group_id")
    now = utc_now()
    with closing(connect(database_path_for_target(target))) as conn:
        group = _execution_group_by_id(conn, group_id)
        if not group:
            raise BackendError("Execution group was not found.", exit_code=2, error_type="execution_group_not_found", details={"execution_group_id": group_id})
        released_leases: list[dict[str, Any]] = []
        with conn:
            conn.execute(
                "UPDATE execution_groups SET status = 'cancelled', finished_at = ?, reason = ? WHERE execution_group_id = ? AND status IN ('proposed', 'running', 'failed')",
                (now, "cancelled from dashboard", group_id),
            )
            conn.execute(
                "UPDATE execution_group_items SET status = 'cancelled', reason = ? WHERE execution_group_id = ? AND status IN ('proposed', 'running', 'failed')",
                ("cancelled from dashboard", group_id),
            )
            conn.execute(
                "UPDATE worker_agents SET status = 'cancelled', finished_at = ?, failure_reason = ? WHERE execution_group_id = ? AND status IN ('queued', 'running')",
                (now, "cancelled from dashboard", group_id),
            )
            conn.execute(
                "UPDATE validation_jobs SET status = 'cancelled', finished_at = ? WHERE execution_group_id = ? AND status IN ('queued', 'running')",
                (now, group_id),
            )
            for lease in active_resource_leases_conn(conn):
                payload = lease.get("payload") if isinstance(lease.get("payload"), dict) else {}
                if payload.get("execution_group_id") == group_id:
                    released = release_resource_lease_conn(conn, str(lease.get("lease_id") or ""), released_at=now, status="released")
                    if released.get("released"):
                        released_leases.append(released.get("lease", {}))
            append_event(
                conn,
                StateEvent(
                    stream_id=f"stream:execution-group:{group_id}",
                    event_type="execution_group.cancelled",
                    actor_role="dashboard",
                    phase="parallel_execution",
                    status="ACTIVE",
                    run_id=group_id,
                    payload={"execution_group_id": group_id, "released_lease_count": len(released_leases)},
                ),
            )
        updated = _execution_group_by_id(conn, group_id)
    write_dashboard_action_state(target, last_action="execution_group_cancelled", updates={"last_execution_group_id": group_id})
    return {"target": target_metadata(target), "execution_group": updated, "released_leases": released_leases}


def command_execution_group_retry_failed(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    group_id = str(getattr(args, "execution_group_id", "") or "").strip()
    with closing(connect(database_path_for_target(target))) as conn:
        if not group_id:
            row = conn.execute(
                "SELECT execution_group_id FROM execution_groups WHERE status = 'failed' ORDER BY finished_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
            group_id = str(row["execution_group_id"]) if row else ""
        if not group_id:
            return {"target": target_metadata(target), "result": {"status": "skipped", "reason": "No failed execution group is available."}}
        group = _execution_group_by_id(conn, group_id)
        if not group:
            raise BackendError("Execution group was not found.", exit_code=2, error_type="execution_group_not_found", details={"execution_group_id": group_id})
        if str(group.get("mode") or "") == "validation":
            rows = conn.execute(
                "SELECT * FROM validation_jobs WHERE execution_group_id = ? AND status IN ('failed', 'warning', 'cancelled') ORDER BY job_id",
                (group_id,),
            ).fetchall()
            commands = []
            for row in rows:
                payload = _json_cell(row["payload_json"], {})
                commands.append(
                    {
                        "command": str(row["command"] or ""),
                        "cwd": str(row["cwd"] or "."),
                        "gate_id": str(row["gate_id"] or ""),
                        "plan_id": str(row["plan_id"] or ""),
                        "required": bool(payload.get("required", True)) if isinstance(payload, dict) else True,
                        "classification": str(payload.get("classification") or "unknown") if isinstance(payload, dict) else "unknown",
                    }
                )
            result = run_parallel_validation_conn(conn, target, commands, selected_by="dashboard.retry_failed", plan_id=f"retry:{group_id}")
        else:
            with conn:
                conn.execute("UPDATE execution_groups SET status = 'proposed', finished_at = '', reason = ? WHERE execution_group_id = ?", ("retry requested from dashboard", group_id))
                conn.execute("UPDATE execution_group_items SET status = 'proposed', reason = ? WHERE execution_group_id = ? AND status IN ('failed', 'cancelled')", ("retry requested from dashboard", group_id))
            result = {"status": "proposed", "execution_group_id": group_id, "reason": "Failed group was returned to proposed state."}
    write_dashboard_action_state(target, last_action="execution_group_retry_requested", updates={"last_execution_group_id": group_id})
    return {"target": target_metadata(target), "result": result}


def command_lease_release_stale(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    lease_id = str(getattr(args, "lease_id", "") or "").strip()
    if not lease_id:
        raise BackendError("A lease id is required.", exit_code=2, error_type="missing_lease_id")
    with closing(connect(database_path_for_target(target))) as conn:
        result = release_resource_lease_conn(conn, lease_id=lease_id)
    write_dashboard_action_state(target, last_action="stale_lease_released", updates={"last_released_lease_id": lease_id})
    return {"target": target_metadata(target), "result": result}


def command_execution_group_export_debug_bundle(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    output_dir = target_path(target, "target/parallel_debug_bundles")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bundle_path = output_dir / f"Diffmogger-parallel-debug-{timestamp}.zip"
    data = _dashboard_parallel_read_model(target)
    bundle = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": data["target"],
        "parallel": {key: value for key, value in data.items() if key != "target"},
        "omitted": [
            "raw project source contents",
            "environment variable values",
            "credential and secret files",
            "arbitrary files outside typed dashboard state",
        ],
    }
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("parallel-state.json", stable_json(bundle) + "\n")
    write_dashboard_action_state(target, last_action="parallel_debug_bundle_exported", updates={"last_parallel_debug_bundle": str(bundle_path)})
    return {
        "target": target_metadata(target),
        "bundle_path": str(bundle_path),
        "included": ["parallel-state.json"],
        "omitted": bundle["omitted"],
    }
