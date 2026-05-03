#!/usr/bin/env python3
"""Run a work-conserving Diffmogger automation conveyor.

The conveyor is a local scheduler for generated targets. It does not mutate the
checkout directly; it chooses the next runnable lane and invokes the existing
target-local wrappers. Multi-role role runners still own isolated worktrees, and
the integrator still owns the main mutation lock.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROLES = ("planner", "builder", "hardener", "integrator")
ACTIVE_STATUSES = {"ACTIVE", "ACTIVE_WITH_PENDING_USER_INPUT"}
DEFAULT_AUTOMATION_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
DEFAULT_IDLE_SLEEP_SECONDS = 60
DEFAULT_ERROR_SLEEP_SECONDS = 300
DEFAULT_CYCLE_COOLDOWN_SECONDS = 5
DEFAULT_PLANNER_INTERVAL_SECONDS = 3600
DEFAULT_LOCK_STALE_SECONDS = 43200
STATE_HISTORY_LIMIT = 60

CHILD: subprocess.Popen[str] | None = None
TERMINATE_REQUESTED = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_id(role: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-conveyor-{role}"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock_fields(path: Path) -> dict[str, str]:
    text = read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items()}
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def lock_is_active(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "no lock"
    fields = read_lock_fields(path)
    pid_text = fields.get("pid", "")
    pid = int(pid_text) if pid_text.isdigit() else None
    epoch_text = fields.get("created_at_epoch", "")
    stale_text = fields.get("stale_after_seconds", "")
    now_epoch = int(time.time())
    created_epoch = int(epoch_text) if epoch_text.isdigit() else int(path.stat().st_mtime)
    stale_after = int(stale_text) if stale_text.isdigit() else 14400
    age = max(0, now_epoch - created_epoch)
    if process_alive(pid):
        return True, f"pid {pid} is still running"
    if age < stale_after:
        run = fields.get("run_id", "unknown")
        return True, f"lock {run} is fresh but owner pid is not visible"
    return False, f"stale lock age_seconds={age}"


def acquire_scheduler_lock(path: Path, stale_seconds: int) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    now_epoch = int(time.time())
    if path.exists():
        fields = read_lock_fields(path)
        pid_text = fields.get("pid", "")
        pid = int(pid_text) if pid_text.isdigit() else None
        epoch_text = fields.get("created_at_epoch", "")
        created_epoch = int(epoch_text) if epoch_text.isdigit() else int(path.stat().st_mtime)
        age = max(0, now_epoch - created_epoch)
        if process_alive(pid):
            print(f"CONVEYOR_LOCK_ACTIVE path={path} pid={pid}", flush=True)
            return False
        if age < stale_seconds:
            print(f"CONVEYOR_LOCK_FRESH path={path} age_seconds={age}", flush=True)
            return False
        path.unlink()

    payload = {
        "pid": os.getpid(),
        "created_at": utc_now(),
        "created_at_epoch": now_epoch,
        "stale_after_seconds": stale_seconds,
        "command": "run_conveyor_automation.py",
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        print(f"CONVEYOR_LOCK_RACE path={path}", flush=True)
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"CONVEYOR_LOCK_ACQUIRED path={path} pid={os.getpid()}", flush=True)
    return True


def release_scheduler_lock(path: Path) -> None:
    if not path.exists():
        return
    fields = read_lock_fields(path)
    pid_text = fields.get("pid", "")
    if pid_text and pid_text != str(os.getpid()):
        print(f"CONVEYOR_LOCK_NOT_RELEASED path={path} owner_pid={pid_text}", flush=True)
        return
    try:
        path.unlink()
        print(f"CONVEYOR_LOCK_RELEASED path={path}", flush=True)
    except OSError as exc:
        print(f"CONVEYOR_LOCK_RELEASE_FAILED path={path} error={exc}", flush=True)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "cycles": 0, "role_counts": {}, "history": []}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "cycles": 0, "role_counts": {}, "history": []}
    if not isinstance(state, dict):
        return {"schema_version": 1, "cycles": 0, "role_counts": {}, "history": []}
    state.setdefault("schema_version", 1)
    state.setdefault("cycles", 0)
    state.setdefault("role_counts", {})
    state.setdefault("history", [])
    return state


def write_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def automation_status(target: Path) -> str:
    task_text = read_text(target / "docs" / "CODEX_AUTOMATION_TASKS.md")
    match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", task_text, re.MULTILINE)
    return match.group(1).strip().upper() if match else "UNKNOWN"


def unhandled_human_inbox_count(target: Path) -> int:
    text = read_text(target / "docs" / "HUMAN_INBOX.md")
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return len(re.findall(r"^\s*-\s*status:\s*unhandled\s*$", text, re.MULTILINE | re.IGNORECASE))


def target_has_multi_role(target: Path) -> bool:
    if not (target / "scripts" / "run_role_automation.sh").exists():
        return False
    return all((target / ".agentic" / "roles" / f"{role}.md").exists() for role in ROLES)


def queued_manifests(target: Path) -> list[Path]:
    queue_root = target / "target" / "automation_queue"
    manifests: list[Path] = []
    for path in sorted(queue_root.glob("*/*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "queued":
            manifests.append(path)
    return manifests


def planner_due(state: dict[str, Any], interval_seconds: int) -> bool:
    last_success = (
        state.get("last_success_by_role", {})
        if isinstance(state.get("last_success_by_role"), dict)
        else {}
    )
    raw = str(last_success.get("planner") or "")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - last).total_seconds() >= interval_seconds


def choose_next(target: Path, state: dict[str, Any], planner_interval_seconds: int) -> tuple[str | None, str, bool]:
    status = automation_status(target)
    if status == "CRITICAL_STOP":
        return None, "automation status is CRITICAL_STOP", True
    if status not in ACTIVE_STATUSES:
        return None, f"automation status is {status}; waiting", False

    active, detail = lock_is_active(target / "target" / "codex_automation.lock")
    if active:
        return None, f"main automation lock active: {detail}", False

    if not target_has_multi_role(target):
        return "single_lane", "multi-role files not found; running single-lane wrapper", False

    queue_depth = len(queued_manifests(target))
    if queue_depth:
        return "integrator", f"{queue_depth} queued role patch(es) need integration", False

    if unhandled_human_inbox_count(target) and planner_due(state, min(planner_interval_seconds, 900)):
        return "planner", "unhandled human inbox message(s) need triage", False

    if planner_due(state, planner_interval_seconds):
        return "planner", "planner interval elapsed", False

    last_role = str(state.get("last_completed_role") or "")
    if last_role == "integrator":
        return "hardener", "recent integration should be hardened or verified", False
    if last_role == "builder":
        return "hardener", "builder lane completed without queued work; hardener gets the next look", False
    return "builder", "builder lane is next runnable work", False


def command_for_role(role: str) -> list[str]:
    if role == "single_lane":
        return ["bash", "scripts/run_codex_automation.sh"]
    return ["bash", "scripts/run_role_automation.sh", "--role", role]


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


def handle_signal(signum: int, _frame: Any) -> None:
    global TERMINATE_REQUESTED
    TERMINATE_REQUESTED = True
    print(f"CONVEYOR_SIGNAL signal={signum}", flush=True)
    terminate_child()


def run_role(target: Path, role: str, allow_remotes: bool) -> int:
    global CHILD
    env = os.environ.copy()
    env["TARGET"] = str(target)
    env["CODEX_RUN_ID"] = run_id(role)
    env["PATH"] = env.get("CODEX_AUTOMATION_PATH", DEFAULT_AUTOMATION_PATH)
    if allow_remotes:
        env["MULTI_ROLE_ALLOW_REMOTES"] = "1"
    command = command_for_role(role)
    print(f"CONVEYOR_RUN role={role} command={' '.join(command)}", flush=True)
    CHILD = subprocess.Popen(
        command,
        cwd=str(target),
        env=env,
        text=True,
        start_new_session=True,
    )
    try:
        return CHILD.wait()
    finally:
        CHILD = None


def record_cycle(
    state: dict[str, Any],
    *,
    role: str,
    reason: str,
    exit_code: int,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    counts = state.setdefault("role_counts", {})
    if isinstance(counts, dict):
        counts[role] = int(counts.get(role, 0)) + 1
    successes = state.setdefault("last_success_by_role", {})
    if isinstance(successes, dict) and exit_code == 0:
        successes[role] = finished_at
    history = state.setdefault("history", [])
    entry = {
        "role": role,
        "reason": reason,
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    if isinstance(history, list):
        history.append(entry)
        del history[:-STATE_HISTORY_LIMIT]
    state["cycles"] = int(state.get("cycles", 0)) + 1
    state["last_completed_role"] = role
    state["last_completed_at"] = finished_at
    state["last_exit_code"] = exit_code
    return state


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


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
    parser.add_argument("--planner-interval-seconds", type=positive_int, default=DEFAULT_PLANNER_INTERVAL_SECONDS)
    parser.add_argument("--scheduler-lock-stale-seconds", type=positive_int, default=DEFAULT_LOCK_STALE_SECONDS)
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    state_path = target / "target" / "automation_conveyor_state.json"
    lock_path = target / "target" / "automation_conveyor.lock"
    state = load_state(state_path)
    role, reason, stop = choose_next(target, state, args.planner_interval_seconds)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "target": str(target),
                    "next_role": role,
                    "reason": reason,
                    "stop": stop,
                    "queued_patch_count": len(queued_manifests(target)),
                    "automation_status": automation_status(target),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if not acquire_scheduler_lock(lock_path, args.scheduler_lock_stale_seconds):
        return 0

    cycles = 0
    last_exit = 0
    allow_remotes = args.allow_remotes or os.environ.get("MULTI_ROLE_ALLOW_REMOTES") == "1"
    try:
        while not TERMINATE_REQUESTED:
            state = load_state(state_path)
            role, reason, stop = choose_next(target, state, args.planner_interval_seconds)
            state["last_decision"] = {"role": role, "reason": reason, "decided_at": utc_now()}
            write_state(state_path, state)
            print(f"CONVEYOR_DECISION role={role or 'idle'} reason={reason}", flush=True)

            if stop:
                return 0
            if role is None:
                if args.once:
                    return 0
                time.sleep(args.idle_sleep_seconds)
                continue

            started_at = utc_now()
            exit_code = run_role(target, role, allow_remotes)
            finished_at = utc_now()
            state = load_state(state_path)
            record_cycle(
                state,
                role=role,
                reason=reason,
                exit_code=exit_code,
                started_at=started_at,
                finished_at=finished_at,
            )
            write_state(state_path, state)
            print(f"CONVEYOR_RESULT role={role} exit={exit_code}", flush=True)
            last_exit = exit_code
            cycles += 1

            if args.once:
                return exit_code
            if args.max_cycles and cycles >= args.max_cycles:
                return last_exit
            if TERMINATE_REQUESTED:
                return 143
            if exit_code != 0:
                time.sleep(args.error_sleep_seconds)
            elif args.cycle_cooldown_seconds:
                time.sleep(args.cycle_cooldown_seconds)
        return 143
    finally:
        terminate_child()
        release_scheduler_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
