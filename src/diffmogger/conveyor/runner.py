from __future__ import annotations

from .state import *

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
