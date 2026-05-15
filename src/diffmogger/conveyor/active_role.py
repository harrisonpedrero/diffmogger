from __future__ import annotations

from diffmogger.runtime.run_process_watchdog import terminate_related_processes

from .state import *

def active_role_age_seconds(active: dict[str, Any], now: datetime | None = None) -> int | None:
    started = parse_timestamp(active.get("started_at"))
    if started is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0, int((current - started).total_seconds()))

def watchdog_status_for_active_run(target: Path, active: dict[str, Any]) -> dict[str, Any]:
    path_text = str(active.get("watchdog_status_path") or "").strip()
    if path_text:
        path = Path(path_text)
    else:
        role = str(active.get("role") or "")
        run_id_value = str(active.get("run_id") or "")
        if role in QUEUE_ROLES and run_id_value:
            path = runtime_path(target, f"target/automation_queue/{role}/{run_id_value}/codex.watchdog.json")
        else:
            return {}
    if not path.is_absolute():
        path = target / path
    data = read_json(path)
    if data:
        data["_path"] = str(path)
    return data

def terminate_process_tree(pid: int, grace_seconds: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "pid": pid,
        "terminated": False,
        "killed": False,
        "signal": None,
        "related_process_cleanup": {},
    }
    if pid <= 0 or pid == os.getpid() or not process_alive(pid):
        return result
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = None
    try:
        sid = os.getsid(pid)
    except OSError:
        sid = None
    use_group = pgid is not None and pgid != os.getpgrp()

    def send(signum: int) -> None:
        if use_group and pgid is not None:
            os.killpg(pgid, signum)
        else:
            os.kill(pid, signum)

    try:
        send(signal.SIGTERM)
        result["terminated"] = True
        result["signal"] = "SIGTERM"
    except ProcessLookupError:
        result["related_process_cleanup"] = terminate_related_processes(
            root_pid=pid,
            root_sid=sid,
            tracked_pids=set(),
            tracked_pgids=set(),
            grace_seconds=grace_seconds,
        )
        return result
    except OSError as exc:
        result["error"] = str(exc)
        return result

    result["related_process_cleanup"] = terminate_related_processes(
        root_pid=pid,
        root_sid=sid,
        tracked_pids=set(),
        tracked_pgids=set(),
        grace_seconds=grace_seconds,
    )
    deadline = time.monotonic() + grace_seconds
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if process_alive(pid):
        try:
            send(signal.SIGKILL)
            result["killed"] = True
            result["signal"] = "SIGKILL"
        except ProcessLookupError:
            pass
        except OSError as exc:
            result["kill_error"] = str(exc)
    return result

def update_timeout_streak(state: dict[str, Any], role: str, *, timed_out: bool, finished_at: str) -> None:
    if not role:
        return
    streaks = state.setdefault("role_timeout_streaks", {})
    if not isinstance(streaks, dict):
        streaks = {}
        state["role_timeout_streaks"] = streaks
    current = streaks.get(role) if isinstance(streaks.get(role), dict) else {}
    if timed_out:
        streaks[role] = {
            "count": int(current.get("count", 0) or 0) + 1,
            "last_timed_out_at": finished_at,
        }
    else:
        streaks.pop(role, None)

def timeout_streak_count(state: dict[str, Any], role: str | None) -> int:
    if not role:
        return 0
    streaks = state.get("role_timeout_streaks")
    if not isinstance(streaks, dict):
        return 0
    entry = streaks.get(role)
    if not isinstance(entry, dict):
        return 0
    return int(entry.get("count", 0) or 0)

def record_active_role_recovery(
    state: dict[str, Any],
    *,
    active: dict[str, Any],
    status: str,
    reason: str,
    exit_code: int,
    finished_at: str,
    metadata: dict[str, Any],
) -> None:
    role = str(active.get("role") or "unknown")
    finished = dict(active)
    finished["status"] = status
    finished["exit_code"] = exit_code
    finished["finished_at"] = finished_at
    finished["recovery_reason"] = reason
    if metadata:
        finished["metadata"] = metadata
    state["last_active_role_run"] = finished
    state["active_role_run"] = None
    history = state.setdefault("history", [])
    entry = {
        "role": role,
        "reason": reason,
        "exit_code": exit_code,
        "started_at": str(active.get("started_at") or ""),
        "finished_at": finished_at,
        "progress_success": False,
        "metadata": {"active_role_recovery": status, **metadata},
    }
    if isinstance(history, list):
        history.append(entry)
        del history[:-STATE_HISTORY_LIMIT]
    state["last_completed_role"] = role
    state["last_completed_at"] = finished_at
    state["last_exit_code"] = exit_code
    state["last_progress_success"] = False
    update_timeout_streak(state, role, timed_out=exit_code == ROLE_TIMEOUT_EXIT_CODE, finished_at=finished_at)

def recover_stale_active_role_run(
    target: Path,
    state: dict[str, Any],
    *,
    timeout_seconds: int | None = None,
    grace_seconds: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    active = state.get("active_role_run")
    if not isinstance(active, dict):
        return None
    pid = int(active.get("pid") or 0)
    timeout = role_timeout_seconds() if timeout_seconds is None else timeout_seconds
    grace = role_termination_grace_seconds() if grace_seconds is None else grace_seconds
    finished_at = utc_now()
    metadata: dict[str, Any] = {
        "pid": pid,
        "run_id": str(active.get("run_id") or ""),
        "role_timeout_seconds": timeout,
        "role_termination_grace_seconds": grace,
    }
    watchdog = watchdog_status_for_active_run(target, active)
    if watchdog:
        metadata["watchdog_status_path"] = watchdog.get("_path")
        metadata["watchdog_process_pid"] = watchdog.get("process_pid")
        metadata["watchdog_process_group_id"] = watchdog.get("process_group_id")

    if not process_alive(pid):
        watchdog_pid = int(watchdog.get("process_pid") or 0) if watchdog else 0
        if process_alive(watchdog_pid):
            metadata["watchdog_process_recovery"] = terminate_process_tree(watchdog_pid, grace)
        reason = "active role run owner pid is gone; clearing orphaned state"
        record_active_role_recovery(
            state,
            active=active,
            status="orphaned",
            reason=reason,
            exit_code=1,
            finished_at=finished_at,
            metadata=metadata,
        )
        return {"status": "orphaned", "reason": reason, "metadata": metadata}

    age = active_role_age_seconds(active, now)
    metadata["age_seconds"] = age
    if age is None or age <= timeout + grace:
        return None

    termination = terminate_process_tree(pid, grace)
    metadata["termination"] = termination
    watchdog_pid = int(watchdog.get("process_pid") or 0) if watchdog else 0
    if watchdog_pid and watchdog_pid != pid and process_alive(watchdog_pid):
        metadata["watchdog_process_recovery"] = terminate_process_tree(watchdog_pid, grace)
    reason = (
        f"active role run exceeded timeout budget: age_seconds={age} "
        f"timeout_seconds={timeout} grace_seconds={grace}"
    )
    record_active_role_recovery(
        state,
        active=active,
        status="timed_out",
        reason=reason,
        exit_code=ROLE_TIMEOUT_EXIT_CODE,
        finished_at=finished_at,
        metadata=metadata,
    )
    return {"status": "timed_out", "reason": reason, "metadata": metadata}

def active_role_run_blocker(state: dict[str, Any]) -> str | None:
    active = state.get("active_role_run")
    if not isinstance(active, dict):
        return None
    role = str(active.get("role") or "unknown")
    run_id_value = str(active.get("run_id") or "unknown")
    pid = int(active.get("pid") or 0)
    age = active_role_age_seconds(active)
    age_text = "unknown" if age is None else str(age)
    if process_alive(pid):
        return f"active role run still running: role={role} run_id={run_id_value} pid={pid} age_seconds={age_text}"
    return f"active role run has stale owner pid and needs recovery: role={role} run_id={run_id_value} pid={pid}"
