#!/usr/bin/env python3
"""Run a subprocess with hard and idle timeouts plus structured status output."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Any


DEFAULT_TIMEOUT_SECONDS = 5400
DEFAULT_IDLE_TIMEOUT_SECONDS = 600
DEFAULT_TERMINATION_GRACE_SECONDS = 20
TIMEOUT_EXIT_CODE = 124
PROCESS_SCAN_INTERVAL_SECONDS = 1.0
PROGRESS_SCAN_INTERVAL_SECONDS = 1.0
DEFAULT_PROGRESS_FILE_LIMIT = 4000
PROGRESS_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}

CHILD: subprocess.Popen[bytes] | None = None
TERMINATE_SIGNAL: int | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_non_negative_int(value: str | None, default: int, *, name: str) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError:
        print(f"{name} must be an integer, got {value!r}", file=sys.stderr)
        raise SystemExit(2)
    if parsed < 0:
        print(f"{name} must be zero or greater, got {value!r}", file=sys.stderr)
        raise SystemExit(2)
    return parsed


def progress_file_limit() -> int:
    return parse_non_negative_int(
        os.environ.get("CODEX_ROLE_IDLE_PROGRESS_FILE_LIMIT"),
        DEFAULT_PROGRESS_FILE_LIMIT,
        name="CODEX_ROLE_IDLE_PROGRESS_FILE_LIMIT",
    )


def command_for_status(command: list[str]) -> list[str]:
    sanitized: list[str] = []
    for arg in command:
        if len(arg) <= 500:
            sanitized.append(arg)
            continue
        sanitized.append(f"{arg[:240]}...<truncated {len(arg) - 240} chars>")
    return sanitized


def signal_name(signum: int | None) -> str | None:
    if signum is None:
        return None
    try:
        return signal.Signals(signum).name
    except ValueError:
        return str(signum)


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def progress_path_label(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def progress_entries_for_path(path: Path, *, file_limit: int) -> list[str]:
    """Return file metadata entries that represent observable subprocess progress."""
    label = progress_path_label(path)
    try:
        stat_result = path.stat()
    except OSError as exc:
        return [f"{label}\0missing\0{exc.__class__.__name__}"]

    if path.is_file():
        return [f"{label}\0file\0{stat_result.st_size}\0{stat_result.st_mtime_ns}"]
    if not path.is_dir():
        return [f"{label}\0other\0{stat_result.st_size}\0{stat_result.st_mtime_ns}"]

    entries = [f"{label}\0dir\0{stat_result.st_mtime_ns}"]
    seen = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [name for name in sorted(dirs) if name not in PROGRESS_SKIP_DIR_NAMES]
        root_path = Path(root)
        for name in sorted(files):
            if file_limit and seen >= file_limit:
                entries.append(f"{label}\0truncated\0{file_limit}")
                return entries
            file_path = root_path / name
            try:
                file_stat = file_path.stat()
            except OSError as exc:
                entries.append(f"{progress_path_label(file_path)}\0missing\0{exc.__class__.__name__}")
                seen += 1
                continue
            try:
                rel = file_path.relative_to(path)
            except ValueError:
                rel = file_path
            entries.append(f"{label}\0{rel}\0{file_stat.st_size}\0{file_stat.st_mtime_ns}")
            seen += 1
    return entries


def progress_signature(paths: list[Path], *, file_limit: int) -> tuple[str, dict[str, Any]]:
    entries: list[str] = []
    for path in paths:
        entries.extend(progress_entries_for_path(path, file_limit=file_limit))
    digest = hashlib.sha256("\n".join(entries).encode("utf-8", errors="surrogateescape")).hexdigest()
    return digest, {"path_count": len(paths), "entry_count": len(entries), "digest": digest}


def stream_to_file(stream: BinaryIO, output: BinaryIO) -> None:
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            output.write(chunk)
            output.flush()
    finally:
        try:
            stream.close()
        except OSError:
            pass


def child_signal(return_code: int | None) -> str | None:
    if return_code is None or return_code >= 0:
        return None
    return signal_name(-return_code)


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_table() -> list[dict[str, int]]:
    commands = (
        ["ps", "-axo", "pid=,ppid=,pgid=,sess="],
        ["ps", "-eo", "pid=,ppid=,pgid=,sess="],
        ["ps", "-axo", "pid=,ppid=,pgid=,sid="],
        ["ps", "-eo", "pid=,ppid=,pgid=,sid="],
    )
    output = ""
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            output = result.stdout
            break
    rows: list[dict[str, int]] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            pid, ppid, pgid, sid = (int(parts[index]) for index in range(4))
        except ValueError:
            continue
        rows.append({"pid": pid, "ppid": ppid, "pgid": pgid, "sid": sid})
    return rows


def related_child_processes(root_pid: int, root_sid: int | None) -> list[dict[str, int]]:
    """Return subprocesses related to the child by ancestry or session."""
    if root_pid <= 0:
        return []
    rows = process_table()
    children_by_parent: dict[int, list[dict[str, int]]] = {}
    for row in rows:
        children_by_parent.setdefault(row["ppid"], []).append(row)

    related_by_pid: dict[int, dict[str, int]] = {}
    stack = [root_pid]
    while stack:
        parent = stack.pop()
        for child in children_by_parent.get(parent, []):
            pid = child["pid"]
            if pid in related_by_pid:
                continue
            related_by_pid[pid] = child
            stack.append(pid)

    if root_sid is not None:
        for row in rows:
            if row["sid"] == root_sid and row["pid"] != root_pid:
                related_by_pid.setdefault(row["pid"], row)

    self_pid = os.getpid()
    return [row for pid, row in related_by_pid.items() if pid != self_pid]


def remember_related_processes(
    root_pid: int,
    root_sid: int | None,
    tracked_pids: set[int],
    tracked_pgids: set[int],
) -> list[dict[str, int]]:
    related = related_child_processes(root_pid, root_sid)
    current_pgid = os.getpgrp()
    for row in related:
        pid = row["pid"]
        pgid = row["pgid"]
        if pid > 0 and pid != os.getpid():
            tracked_pids.add(pid)
        if pgid > 0 and pgid != current_pgid:
            tracked_pgids.add(pgid)
    return related


def signal_child_group(proc: subprocess.Popen[bytes], signum: int) -> None:
    try:
        os.killpg(proc.pid, signum)
    except ProcessLookupError:
        return
    except OSError:
        try:
            proc.send_signal(signum)
        except ProcessLookupError:
            return


def request_termination(_signum: int, _frame: object) -> None:
    global TERMINATE_SIGNAL
    TERMINATE_SIGNAL = _signum
    child = CHILD
    if child and child.poll() is None:
        signal_child_group(child, signal.SIGTERM)


def wait_after_termination(proc: subprocess.Popen[bytes], grace_seconds: int) -> tuple[int | None, bool]:
    deadline = time.monotonic() + grace_seconds
    while True:
        return_code = proc.poll()
        if return_code is not None:
            return return_code, False
        if time.monotonic() >= deadline:
            break
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    signal_child_group(proc, signal.SIGKILL)
    return proc.wait(), True


def terminate_related_processes(
    *,
    root_pid: int,
    root_sid: int | None,
    tracked_pids: set[int],
    tracked_pgids: set[int],
    grace_seconds: int,
) -> dict[str, Any]:
    related = remember_related_processes(root_pid, root_sid, tracked_pids, tracked_pgids)
    current_pid = os.getpid()
    current_pgid = os.getpgrp()
    target_pids = {
        pid
        for pid in tracked_pids
        if pid > 0 and pid != current_pid and pid != root_pid and process_alive(pid)
    }
    target_pgids = {pgid for pgid in tracked_pgids if pgid > 0 and pgid != current_pgid}
    for row in related:
        pid = row["pid"]
        pgid = row["pgid"]
        if pid > 0 and pid != current_pid and pid != root_pid and process_alive(pid):
            target_pids.add(pid)
        if pgid > 0 and pgid != current_pgid:
            target_pgids.add(pgid)

    result: dict[str, Any] = {
        "target_pids": sorted(target_pids),
        "target_process_group_ids": sorted(target_pgids),
        "terminated": False,
        "killed": False,
        "errors": [],
    }
    if not target_pids and not target_pgids:
        return result

    def send_to_targets(signum: int) -> None:
        for pgid in sorted(target_pgids):
            try:
                os.killpg(pgid, signum)
            except ProcessLookupError:
                continue
            except OSError as exc:
                result["errors"].append({"target": f"pgid:{pgid}", "signal": signal_name(signum), "error": str(exc)})
        for pid in sorted(target_pids):
            if not process_alive(pid):
                continue
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = None
            if pgid in target_pgids:
                continue
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                continue
            except OSError as exc:
                result["errors"].append({"target": f"pid:{pid}", "signal": signal_name(signum), "error": str(exc)})

    send_to_targets(signal.SIGTERM)
    result["terminated"] = True
    deadline = time.monotonic() + grace_seconds
    while any(process_alive(pid) for pid in target_pids) and time.monotonic() < deadline:
        time.sleep(0.1)
    if any(process_alive(pid) for pid in target_pids):
        send_to_targets(signal.SIGKILL)
        result["killed"] = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout-file", required=True, type=Path)
    parser.add_argument("--stderr-file", required=True, type=Path)
    parser.add_argument("--status-file", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=None)
    parser.add_argument("--idle-timeout-seconds", type=int, default=None)
    parser.add_argument(
        "--progress-path",
        action="append",
        default=[],
        type=Path,
        help="File or directory whose size/mtime changes reset the idle timeout.",
    )
    parser.add_argument("--termination-grace-seconds", type=int, default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    global CHILD
    args = build_parser().parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("run_process_watchdog.py requires a command after --", file=sys.stderr)
        return 2

    timeout_seconds = args.timeout_seconds
    if timeout_seconds is None:
        timeout_seconds = parse_non_negative_int(
            os.environ.get("CODEX_ROLE_TIMEOUT_SECONDS"),
            DEFAULT_TIMEOUT_SECONDS,
            name="CODEX_ROLE_TIMEOUT_SECONDS",
        )
    if timeout_seconds < 0:
        print("--timeout-seconds must be zero or greater", file=sys.stderr)
        return 2

    idle_timeout_seconds = args.idle_timeout_seconds
    if idle_timeout_seconds is None:
        idle_timeout_seconds = parse_non_negative_int(
            os.environ.get("CODEX_ROLE_IDLE_TIMEOUT_SECONDS"),
            DEFAULT_IDLE_TIMEOUT_SECONDS,
            name="CODEX_ROLE_IDLE_TIMEOUT_SECONDS",
        )
    if idle_timeout_seconds < 0:
        print("--idle-timeout-seconds must be zero or greater", file=sys.stderr)
        return 2

    grace_seconds = args.termination_grace_seconds
    if grace_seconds is None:
        grace_seconds = parse_non_negative_int(
            os.environ.get("CODEX_ROLE_TERMINATION_GRACE_SECONDS"),
            DEFAULT_TERMINATION_GRACE_SECONDS,
            name="CODEX_ROLE_TERMINATION_GRACE_SECONDS",
        )
    if grace_seconds < 0:
        print("--termination-grace-seconds must be zero or greater", file=sys.stderr)
        return 2

    started = time.monotonic()
    args.stdout_file.parent.mkdir(parents=True, exist_ok=True)
    args.stderr_file.parent.mkdir(parents=True, exist_ok=True)
    args.stdout_file.touch(exist_ok=True)
    args.stderr_file.touch(exist_ok=True)
    progress_paths = [args.stdout_file, args.stderr_file, *args.progress_path]
    progress_limit = progress_file_limit()
    last_progress = started
    last_progress_at = utc_now()
    current_progress_signature, progress_detail = progress_signature(progress_paths, file_limit=progress_limit)
    status: dict[str, Any] = {
        "schema_version": 1,
        "started_at": utc_now(),
        "finished_at": None,
        "duration_seconds": None,
        "exit_code": None,
        "child_exit_code": None,
        "timed_out": False,
        "idle_timed_out": False,
        "terminated": False,
        "killed": False,
        "signal": None,
        "termination_reason": None,
        "timeout_seconds": timeout_seconds,
        "idle_timeout_seconds": idle_timeout_seconds,
        "last_progress_at": last_progress_at,
        "last_progress_reason": "initial_observation",
        "progress_paths": [progress_path_label(path) for path in progress_paths],
        "progress_observation": progress_detail,
        "termination_grace_seconds": grace_seconds,
        "command": command_for_status(command),
        "command_display": shlex.join(command_for_status(command)),
        "process_pid": None,
        "process_group_id": None,
        "process_session_id": None,
        "descendant_pids": [],
        "descendant_process_group_ids": [],
        "descendant_terminated": False,
        "descendant_killed": False,
    }
    write_status(args.status_file, status)

    signal.signal(signal.SIGTERM, request_termination)
    signal.signal(signal.SIGINT, request_termination)

    stdout_handle = args.stdout_file.open("wb")
    stderr_handle = args.stderr_file.open("wb")
    threads: list[threading.Thread] = []
    child_return_code: int | None = None
    exit_code = 0
    child_session_id: int | None = None
    tracked_descendant_pids: set[int] = set()
    tracked_descendant_pgids: set[int] = set()

    try:
        try:
            CHILD = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            status["termination_reason"] = "command_not_found"
            exit_code = 127
            return exit_code

        status["process_pid"] = CHILD.pid
        try:
            status["process_group_id"] = os.getpgid(CHILD.pid)
        except OSError:
            status["process_group_id"] = CHILD.pid
        try:
            child_session_id = os.getsid(CHILD.pid)
            status["process_session_id"] = child_session_id
        except OSError:
            child_session_id = None
        write_status(args.status_file, status)

        assert CHILD.stdout is not None
        assert CHILD.stderr is not None
        threads = [
            threading.Thread(target=stream_to_file, args=(CHILD.stdout, stdout_handle), daemon=True),
            threading.Thread(target=stream_to_file, args=(CHILD.stderr, stderr_handle), daemon=True),
        ]
        for thread in threads:
            thread.start()

        deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
        idle_deadline = time.monotonic() + idle_timeout_seconds if idle_timeout_seconds else None
        next_process_scan = 0.0
        next_progress_scan = 0.0
        while True:
            now = time.monotonic()
            if now >= next_process_scan:
                remember_related_processes(
                    CHILD.pid,
                    child_session_id,
                    tracked_descendant_pids,
                    tracked_descendant_pgids,
                )
                scan_interval = 0.1 if now - started < 5 else PROCESS_SCAN_INTERVAL_SECONDS
                next_process_scan = now + scan_interval
            if idle_timeout_seconds and now >= next_progress_scan:
                observed_signature, observed_detail = progress_signature(progress_paths, file_limit=progress_limit)
                if observed_signature != current_progress_signature:
                    current_progress_signature = observed_signature
                    progress_detail = observed_detail
                    last_progress = now
                    last_progress_at = utc_now()
                    idle_deadline = now + idle_timeout_seconds
                    status["last_progress_at"] = last_progress_at
                    status["last_progress_reason"] = "progress_path_changed"
                    status["progress_observation"] = progress_detail
                next_progress_scan = now + PROGRESS_SCAN_INTERVAL_SECONDS
            child_return_code = CHILD.poll()
            if child_return_code is not None:
                exit_code = child_return_code if child_return_code >= 0 else 128 + abs(child_return_code)
                break
            if TERMINATE_SIGNAL is not None:
                status["terminated"] = True
                status["signal"] = signal_name(TERMINATE_SIGNAL)
                status["termination_reason"] = "parent_signal"
                child_return_code, killed = wait_after_termination(CHILD, grace_seconds)
                status["killed"] = killed
                exit_code = 128 + int(TERMINATE_SIGNAL)
                break
            if idle_deadline is not None and time.monotonic() >= idle_deadline:
                status["idle_timed_out"] = True
                status["terminated"] = True
                status["signal"] = signal_name(signal.SIGTERM)
                status["termination_reason"] = "idle_timeout"
                status["idle_seconds"] = round(time.monotonic() - last_progress, 3)
                signal_child_group(CHILD, signal.SIGTERM)
                child_return_code, killed = wait_after_termination(CHILD, grace_seconds)
                status["killed"] = killed
                if killed:
                    status["signal"] = signal_name(signal.SIGKILL)
                exit_code = TIMEOUT_EXIT_CODE
                break
            if deadline is not None and time.monotonic() >= deadline:
                status["timed_out"] = True
                status["terminated"] = True
                status["signal"] = signal_name(signal.SIGTERM)
                status["termination_reason"] = "hard_timeout"
                signal_child_group(CHILD, signal.SIGTERM)
                child_return_code, killed = wait_after_termination(CHILD, grace_seconds)
                status["killed"] = killed
                if killed:
                    status["signal"] = signal_name(signal.SIGKILL)
                exit_code = TIMEOUT_EXIT_CODE
                break
            time.sleep(0.1)
    finally:
        child = CHILD
        if child is not None:
            cleanup = terminate_related_processes(
                root_pid=child.pid,
                root_sid=child_session_id,
                tracked_pids=tracked_descendant_pids,
                tracked_pgids=tracked_descendant_pgids,
                grace_seconds=grace_seconds,
            )
            status["descendant_pids"] = cleanup["target_pids"]
            status["descendant_process_group_ids"] = cleanup["target_process_group_ids"]
            status["descendant_terminated"] = cleanup["terminated"]
            status["descendant_killed"] = cleanup["killed"]
            if cleanup.get("errors"):
                status["descendant_cleanup_errors"] = cleanup["errors"]
        for thread in threads:
            thread.join(timeout=2)
        stdout_handle.close()
        stderr_handle.close()
        finished = time.monotonic()
        status["finished_at"] = utc_now()
        status["duration_seconds"] = round(finished - started, 3)
        status["child_exit_code"] = child_return_code
        status["exit_code"] = exit_code
        if status.get("signal") is None:
            status["signal"] = child_signal(child_return_code)
        write_status(args.status_file, status)
        CHILD = None

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
