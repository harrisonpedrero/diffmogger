"""Run a work-conserving Diffmogger automation conveyor."""

from __future__ import annotations

from contextlib import closing

from . import runner as conveyor_runner
from .active_role import active_role_run_blocker, recover_stale_active_role_run
from .baseline import automation_status, baseline_record
from .decisions import choose_next, conveyor_decision_queue
from .locks import acquire_conveyor_lock, release_conveyor_lock
from .progress import (
    no_progress_info,
    record_cycle,
)
from .queue_state import queued_manifests
from .runner import finish_active_role_run
from .state import *
from .tickets import finalize_ticket_campaign, ticket_campaign_terminal
from diffmogger.runtime.state_store import connect, database_path_for_target, human_messages_snapshot, latest_scheduler_decision_conn


def _latest_selected_scheduler_candidate(target: Path) -> dict[str, Any]:
    try:
        with closing(connect(database_path_for_target(target))) as conn:
            decision = latest_scheduler_decision_conn(conn)
    except Exception:
        return {}
    selected = decision.get("selected_candidate") if isinstance(decision.get("selected_candidate"), dict) else {}
    return dict(selected)


def _role_run_status(target: Path, exit_code: int) -> str:
    if exit_code == 0:
        return "ACTIVE"
    try:
        human = human_messages_snapshot(target, import_legacy=False)
    except Exception:
        return "ACTIVE"
    counts = human.get("counts") if isinstance(human.get("counts"), dict) else {}
    pending = (
        int(counts.get("pending_requests") or 0)
        + int(counts.get("queued_notes") or 0)
        + int(counts.get("failed_notes") or 0)
    )
    return "ACTIVE_WITH_PENDING_USER_INPUT" if pending else "ACTIVE"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=os.environ.get("TARGET", "."), help="Target project directory")
    parser.add_argument("--once", action="store_true", help="Run one conveyor decision, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Print the next decision without running anything")
    parser.add_argument("--allow-remotes", action="store_true", help="Pass MULTI_ROLE_ALLOW_REMOTES=1 to role runs")
    parser.add_argument("--max-cycles", type=positive_int, default=0, help="Maximum role cycles before exiting; 0 means unlimited")
    parser.add_argument("--idle-sleep-seconds", type=positive_int, default=DEFAULT_IDLE_SLEEP_SECONDS)
    parser.add_argument("--error-sleep-seconds", type=positive_int, default=DEFAULT_ERROR_SLEEP_SECONDS)
    parser.add_argument("--cycle-cooldown-seconds", type=positive_int, default=DEFAULT_CYCLE_COOLDOWN_SECONDS)
    parser.add_argument("--conveyor-lock-stale-seconds", type=positive_int, default=DEFAULT_LOCK_STALE_SECONDS)
    parser.add_argument("--no-progress-threshold", type=positive_int, default=DEFAULT_NO_PROGRESS_THRESHOLD)
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()

    head_status, head_detail = git_head_status(target)
    if head_status != "ok":
        report_preflight_failure(head_status, head_detail, target)
        return 2

    state_path = runtime_path(target, "target/automation_conveyor_state.json")
    lock_path = runtime_path(target, "target/automation_conveyor.lock")
    state = load_state(state_path)
    active_blocker = active_role_run_blocker(state)
    if active_blocker:
        role, reason, stop = None, active_blocker, False
    else:
        role, reason, stop = choose_next(target, state, args.no_progress_threshold)
    ticket_state, ticket_reason = ticket_campaign_terminal(target)
    selected_candidate = _latest_selected_scheduler_candidate(target)

    if args.dry_run:
        queue = conveyor_decision_queue(
            target,
            state,
            role,
            reason,
            args.no_progress_threshold,
        )
        print(
            json.dumps(
                {
                    "target": str(target),
                    "next_role": role,
                    "reason": reason,
                    "stop": stop,
                    "decision_queue": queue,
                    "queued_patch_count": len(queued_manifests(target)),
                    "automation_status": automation_status(target),
                    "baseline_verification": baseline_record(target),
                    "integrator_no_progress": no_progress_info(state),
                    "state_machine": state.get("state_machine") if isinstance(state.get("state_machine"), dict) else {},
                    "selected_scheduler_candidate": selected_candidate,
                    "campaign": {"status": ticket_state or "active", "reason": ticket_reason},
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    signal.signal(signal.SIGTERM, conveyor_runner.handle_signal)
    signal.signal(signal.SIGINT, conveyor_runner.handle_signal)

    if not acquire_conveyor_lock(lock_path, args.conveyor_lock_stale_seconds):
        return 0

    cycles = 0
    last_exit = 0
    allow_remotes = args.allow_remotes or os.environ.get("MULTI_ROLE_ALLOW_REMOTES") == "1"
    try:
        while not conveyor_runner.TERMINATE_REQUESTED:
            state = load_state(state_path)
            recovery = recover_stale_active_role_run(
                target,
                state,
                timeout_seconds=role_timeout_seconds(),
                grace_seconds=role_termination_grace_seconds(),
            )
            if recovery:
                write_state(
                    state_path,
                    state,
                    event_type="role_run.recovered",
                    actor_role="conveyor",
                    phase="recovery",
                    payload=recovery,
                )
                print(
                    f"CONVEYOR_ACTIVE_ROLE_RECOVERED status={recovery['status']} reason={recovery['reason']}",
                    flush=True,
                )
            active_blocker = active_role_run_blocker(state)
            if active_blocker:
                role, reason, stop = None, active_blocker, False
            else:
                role, reason, stop = choose_next(target, state, args.no_progress_threshold)
            selected_candidate = _latest_selected_scheduler_candidate(target)
            state["last_decision"] = {"role": role, "reason": reason, "decided_at": utc_now()}
            state["decision_queue"] = conveyor_decision_queue(
                target,
                state,
                role,
                reason,
                args.no_progress_threshold,
            )
            write_state(
                state_path,
                state,
                event_type="conveyor.decision_recorded",
                actor_role="conveyor",
                phase="decision",
                payload={"role": role, "reason": reason, "stop": stop, "selected_scheduler_candidate": selected_candidate},
            )
            print(f"CONVEYOR_DECISION role={role or 'idle'} reason={reason}", flush=True)

            if stop:
                if reason in {"bounded campaign complete", "bounded campaign blocked"}:
                    finalize_ticket_campaign(target)
                return 0
            if role is None:
                if args.once:
                    return 0
                conveyor_runner.sleep_interruptibly(args.idle_sleep_seconds)
                continue

            started_at = utc_now()
            exit_code = conveyor_runner.run_scheduler_action(
                target,
                selected_candidate,
                allow_remotes,
                state_path=state_path,
                reason=reason,
                started_at=started_at,
            )
            finished_at = utc_now()
            state = load_state(state_path)
            finish_active_role_run(state, exit_code=exit_code, finished_at=finished_at)
            metadata: dict[str, Any] = {
                "scheduler_action": str(selected_candidate.get("action_kind") or ""),
                "dag_node_id": str(selected_candidate.get("dag_node_id") or ""),
                "execution_group_id": str(selected_candidate.get("execution_group_id") or ""),
            }
            record_cycle(
                state,
                role=role,
                reason=reason,
                exit_code=exit_code,
                started_at=started_at,
                finished_at=finished_at,
                metadata=metadata,
            )
            write_state(
                state_path,
                state,
                event_type="role_run.finished",
                actor_role=role,
                phase="role_execution",
                status=_role_run_status(target, exit_code),
                payload={
                    "role": role,
                    "reason": reason,
                    "exit_code": exit_code,
                    "metadata": metadata,
                },
            )
            print(
                f"CONVEYOR_RESULT role={role} exit={exit_code} progress={state.get('last_progress_success')}",
                flush=True,
            )
            last_exit = exit_code
            cycles += 1

            if args.once:
                return exit_code
            if args.max_cycles and cycles >= args.max_cycles:
                return last_exit
            if conveyor_runner.TERMINATE_REQUESTED:
                return 143
            if exit_code != 0:
                conveyor_runner.sleep_interruptibly(args.error_sleep_seconds)
            elif args.cycle_cooldown_seconds:
                conveyor_runner.sleep_interruptibly(args.cycle_cooldown_seconds)
        return 143
    finally:
        conveyor_runner.terminate_child()
        release_conveyor_lock(lock_path)

if __name__ == "__main__":
    raise SystemExit(main())
