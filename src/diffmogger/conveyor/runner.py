from __future__ import annotations

from contextlib import closing

from .state import *
from diffmogger.runtime.state_store import (
    connect,
    create_repair_nodes_for_failed_validation_conn,
    database_path_for_target,
    ensure_execution_group_for_dag_node_conn,
    launch_read_only_execution_group_conn,
    launch_write_execution_group_conn,
    mark_worker_patches_integrated_conn,
    plan_parallel_execution_groups_conn,
    record_validation_group_result_on_execution_dag_conn,
    reconcile_worker_results_into_execution_dag_conn,
    run_refresh_index_node_conn,
    run_parallel_validation_conn,
    sync_queued_role_manifests_into_worker_patches_conn,
    update_execution_dag_node_status_conn,
    update_execution_group_dag_nodes_conn,
)

CHILD: subprocess.Popen[str] | None = None
TERMINATE_REQUESTED = False

def command_for_role(target: Path, role: str) -> list[str]:
    if role not in ROLES:
        raise ValueError(f"Unsupported conveyor role: {role}")
    return ["bash", str(script_path(target, "scripts/run_role_automation.sh")), "--role", role]

def terminate_child() -> None:
    global CHILD
    child = CHILD
    if child and child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            child.terminate()

def kill_child() -> None:
    global CHILD
    child = CHILD
    if child and child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            child.kill()

def sleep_interruptibly(seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while not TERMINATE_REQUESTED:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1.0))

def handle_signal(signum: int, _frame: Any) -> None:
    global TERMINATE_REQUESTED
    TERMINATE_REQUESTED = True
    print(f"CONVEYOR_SIGNAL signal={signum}", flush=True)
    terminate_child()

def run_role(
    target: Path,
    role: str,
    allow_remotes: bool,
    *,
    state_path: Path | None = None,
    reason: str = "",
    started_at: str = "",
    extra_env: dict[str, str] | None = None,
) -> int:
    global CHILD
    env = os.environ.copy()
    env["TARGET"] = str(target)
    run_id_value = run_id(role)
    env["CODEX_RUN_ID"] = run_id_value
    env["PATH"] = env.get("CODEX_AUTOMATION_PATH", DEFAULT_AUTOMATION_PATH)
    if reason:
        env["CONVEYOR_DECISION_REASON"] = reason
    if allow_remotes:
        env["MULTI_ROLE_ALLOW_REMOTES"] = "1"
    if extra_env:
        env.update({str(key): str(value) for key, value in extra_env.items()})
    command = command_for_role(target, role)
    watchdog_status_path = ""
    if role in QUEUE_ROLES:
        watchdog_status_path = str(runtime_path(target, "target/automation_queue") / role / run_id_value / "codex.watchdog.json")
    print(f"CONVEYOR_RUN role={role} run_id={run_id_value} command={command_display(command)}", flush=True)
    CHILD = subprocess.Popen(
        command,
        cwd=str(target),
        env=env,
        text=True,
        start_new_session=True,
    )
    if state_path is not None:
        state = load_state(state_path)
        state["active_role_run"] = {
            "role": role,
            "run_id": run_id_value,
            "reason": reason,
            "started_at": started_at or utc_now(),
            "pid": CHILD.pid,
            "started_at_epoch": int(time.time()),
            "command": command,
            "command_display": command_display(command),
            "status": "running",
        }
        if watchdog_status_path:
            state["active_role_run"]["watchdog_status_path"] = watchdog_status_path
        write_state(
            state_path,
            state,
            event_type="role_run.started",
            actor_role=role,
            phase="role_execution",
            payload={"role": role, "run_id": run_id_value, "reason": reason, "command": command},
        )
    try:
        while True:
            if TERMINATE_REQUESTED:
                terminate_child()
                try:
                    return CHILD.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    kill_child()
                    return CHILD.wait(timeout=1)
            try:
                return CHILD.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                continue
    finally:
        CHILD = None


def _action_success(status: str) -> bool:
    return str(status or "") in {"completed", "passed", "warning", "already_launched", "reconciled", "created", "integrated", "skipped"}


def run_scheduler_action(
    target: Path,
    candidate: dict[str, Any],
    allow_remotes: bool,
    *,
    state_path: Path | None = None,
    reason: str = "",
    started_at: str = "",
) -> int:
    action = str(candidate.get("action_kind") or "").strip()
    if action in {"", "idle", "terminal_stop"}:
        return 0
    run_id_value = run_id(action)
    if state_path is not None:
        state = load_state(state_path)
        state["active_role_run"] = {
            "role": str(candidate.get("role") or ""),
            "action_kind": action,
            "run_id": run_id_value,
            "reason": reason,
            "started_at": started_at or utc_now(),
            "pid": os.getpid(),
            "started_at_epoch": int(time.time()),
            "command": ["dag_scheduler_action", action],
            "command_display": f"dag_scheduler_action {action}",
            "status": "running",
            "dag_node_id": str(candidate.get("dag_node_id") or ""),
            "execution_group_id": str(candidate.get("execution_group_id") or ""),
        }
        write_state(
            state_path,
            state,
            event_type="dag_scheduler.action_started",
            actor_role=str(candidate.get("role") or "scheduler"),
            phase="dag_scheduler",
            payload={"action_kind": action, "candidate": candidate},
        )
    print(f"DAG_SCHEDULER_ACTION action={action} run_id={run_id_value}", flush=True)
    target = target.expanduser().resolve()
    result: dict[str, Any]
    if action == "run_serial_role":
        role = str(candidate.get("role") or "").strip()
        if role not in ROLES:
            print(f"DAG_SCHEDULER_RESULT action={action} status=failed", flush=True)
            return 1
        exit_code = run_role(
            target,
            role,
            allow_remotes,
            state_path=None,
            reason=reason or "serialized ticket role fallback",
            started_at=started_at,
        )
        if exit_code == 0:
            with closing(connect(database_path_for_target(target))) as conn:
                dag_node_id = str(candidate.get("dag_node_id") or "")
                if dag_node_id:
                    update_execution_dag_node_status_conn(conn, dag_node_id, status="done", selected_by="dag_scheduler.run_serial_role")
                sync_queued_role_manifests_into_worker_patches_conn(
                    conn,
                    target,
                    selected_by="dag_scheduler.run_serial_role",
                )
        return exit_code
    if action == "run_serial_integration":
        patch_ids = [str(item) for item in (candidate.get("patch_ids") or []) if str(item)]
        exit_code = run_role(
            target,
            "integrator",
            allow_remotes,
            state_path=None,
            reason=reason or "serialized integration DAG action",
            started_at=started_at,
            extra_env={"DIFFMOGGER_SELECTED_PATCH_IDS": ",".join(patch_ids)} if patch_ids else {},
        )
        if exit_code == 0:
            with closing(connect(database_path_for_target(target))) as conn:
                mark_worker_patches_integrated_conn(
                    conn,
                    target=target,
                    selected_by="dag_scheduler.run_serial_integration",
                    patch_ids=patch_ids or None,
                )
        return exit_code
    with closing(connect(database_path_for_target(target))) as conn:
        if action in {"launch_scope_group", "launch_review_group"}:
            plan_parallel_execution_groups_conn(conn, target, selected_by=f"dag_scheduler.{action}")
            execution_group_id = str(candidate.get("execution_group_id") or "")
            dag_node_id = str(candidate.get("dag_node_id") or "")
            if dag_node_id:
                selected_group = ensure_execution_group_for_dag_node_conn(
                    conn,
                    target,
                    dag_node_id,
                    selected_by=f"dag_scheduler.{action}",
                    exact=True,
                )
                execution_group_id = str(selected_group.get("execution_group_id") or execution_group_id)
            if not execution_group_id and dag_node_id:
                result = {
                    "status": "skipped",
                    "reason_kind": "no_selected_read_only_group",
                    "reason": "No read-only execution group could be prepared for the selected DAG node.",
                    "dag_node_id": dag_node_id,
                }
            else:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=execution_group_id,
                    selected_by=f"dag_scheduler.{action}",
                )
            if _action_success(str(result.get("status") or "")) and str(result.get("execution_group_id") or ""):
                update_execution_group_dag_nodes_conn(
                    conn,
                    str(result.get("execution_group_id") or ""),
                    status="done",
                    selected_by=f"dag_scheduler.{action}",
                )
            elif _action_success(str(result.get("status") or "")) and str(candidate.get("dag_node_id") or ""):
                update_execution_dag_node_status_conn(
                    conn,
                    str(candidate.get("dag_node_id") or ""),
                    status="done",
                    selected_by=f"dag_scheduler.{action}",
                )
        elif action == "launch_write_group":
            plan_parallel_execution_groups_conn(conn, target, selected_by="dag_scheduler.launch_write_group")
            result = launch_write_execution_group_conn(
                conn,
                target,
                execution_group_id=str(candidate.get("execution_group_id") or ""),
                selected_by="dag_scheduler.launch_write_group",
            )
            if _action_success(str(result.get("status") or "")) and str(result.get("execution_group_id") or ""):
                update_execution_group_dag_nodes_conn(
                    conn,
                    str(result.get("execution_group_id") or ""),
                    status="done",
                    selected_by="dag_scheduler.launch_write_group",
                )
                reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="dag_scheduler.launch_write_group")
        elif action == "launch_validation_group":
            dag_group_id = str(candidate.get("execution_group_id") or candidate.get("dag_node_id") or "")
            result = run_parallel_validation_conn(
                conn,
                target,
                selected_by="dag_scheduler.launch_validation_group",
                plan_id=dag_group_id,
            )
            if dag_group_id:
                record_validation_group_result_on_execution_dag_conn(
                    conn,
                    dag_group_id,
                    result,
                    selected_by="dag_scheduler.launch_validation_group",
                )
            if str(result.get("status") or "") == "failed":
                repair_result = create_repair_nodes_for_failed_validation_conn(conn, selected_by="dag_scheduler.launch_validation_group")
                if _action_success(str(repair_result.get("status") or "")):
                    result = {
                        **result,
                        "status": str(repair_result.get("status") or "created"),
                        "validation_status": "failed",
                        "repair_result": repair_result,
                    }
        elif action == "reconcile_worker_results":
            result = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="dag_scheduler.reconcile_worker_results")
        elif action == "create_repair_nodes":
            result = create_repair_nodes_for_failed_validation_conn(conn, selected_by="dag_scheduler.create_repair_nodes")
        elif action == "refresh_index":
            result = run_refresh_index_node_conn(
                conn,
                target,
                dag_node_id=str(candidate.get("dag_node_id") or ""),
                selected_by="dag_scheduler.refresh_index",
            )
        else:
            result = {"status": "failed", "reason": f"unsupported DAG scheduler action: {action}"}
    print(f"DAG_SCHEDULER_RESULT action={action} status={result.get('status')}", flush=True)
    return 0 if _action_success(str(result.get("status") or "")) else 1

def finish_active_role_run(state: dict[str, Any], *, exit_code: int, finished_at: str) -> None:
    active = state.get("active_role_run")
    if not isinstance(active, dict):
        return
    finished = dict(active)
    finished["status"] = "timed_out" if exit_code == ROLE_TIMEOUT_EXIT_CODE else "finished"
    finished["exit_code"] = exit_code
    finished["finished_at"] = finished_at
    state["last_active_role_run"] = finished
    state["active_role_run"] = None
