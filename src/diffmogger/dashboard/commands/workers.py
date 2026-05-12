from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

from .run_control import run_subprocess_streamed

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
        "result": result,
    }
