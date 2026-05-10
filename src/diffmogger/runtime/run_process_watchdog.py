#!/usr/bin/env python3
"""Run a subprocess with a hard timeout and structured status output."""

from __future__ import annotations

import argparse
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
DEFAULT_TERMINATION_GRACE_SECONDS = 20
TIMEOUT_EXIT_CODE = 124

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout-file", required=True, type=Path)
    parser.add_argument("--stderr-file", required=True, type=Path)
    parser.add_argument("--status-file", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=None)
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
        "termination_grace_seconds": grace_seconds,
        "command": command_for_status(command),
        "command_display": shlex.join(command_for_status(command)),
        "process_pid": None,
        "process_group_id": None,
    }
    write_status(args.status_file, status)

    signal.signal(signal.SIGTERM, request_termination)
    signal.signal(signal.SIGINT, request_termination)

    args.stdout_file.parent.mkdir(parents=True, exist_ok=True)
    args.stderr_file.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = args.stdout_file.open("wb")
    stderr_handle = args.stderr_file.open("wb")
    threads: list[threading.Thread] = []
    child_return_code: int | None = None
    exit_code = 0

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
        while True:
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
