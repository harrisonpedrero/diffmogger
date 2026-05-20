from __future__ import annotations

import argparse
import hashlib
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

from diffmogger.runtime.state_store import load_conveyor_state, write_conveyor_state
from diffmogger.runtime.paths import existing_or_target_path, target_path

ROLES = ("planner", "builder", "hardener", "integrator")

QUEUE_ROLES = ("planner", "builder", "hardener")

ACTIVE_STATUSES = {
    "ACTIVE",
    "ACTIVE_WITH_PENDING_USER_INPUT",
    "BLOCKED_ON_USER",
    "BLOCKED_ON_ENVIRONMENT",
}

DEFAULT_AUTOMATION_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

DEFAULT_IDLE_SLEEP_SECONDS = 60

DEFAULT_ERROR_SLEEP_SECONDS = 300

DEFAULT_CYCLE_COOLDOWN_SECONDS = 5

DEFAULT_LOCK_STALE_SECONDS = 43200

DEFAULT_NO_PROGRESS_THRESHOLD = 2

DEFAULT_ROLE_TIMEOUT_SECONDS = 5400

DEFAULT_ROLE_TERMINATION_GRACE_SECONDS = 20

DEFAULT_ROLE_TIMEOUT_STREAK_LIMIT = 2

ROLE_TIMEOUT_EXIT_CODE = 124

STATE_HISTORY_LIMIT = 60

NO_PROGRESS_STATE_KEY = "integrator_no_progress"

DECISION_QUEUE_LIMIT = 8

BASELINE_VERIFICATION_RELATIVE = Path("target/baseline_verification.json")

FINAL_VERIFICATION_RE = re.compile(
    r"\b(hardener|final(?:ization)?|final\s+verification|verified\s+by\s+hardener|acceptance\s+verification)\b",
    re.IGNORECASE,
)

TYPESCRIPT_COMPILER_ERROR_RE = re.compile(r"\berror\s+TS\d{3,5}\b", re.IGNORECASE)

TICKET_FENCE_RE = re.compile(r"```(?:json\s+ticket-run|ticket-run-json)\s*\n(.*?)\n```", re.DOTALL)

TICKET_TOKEN_RE = re.compile(r"(?<![\w-])#\d+\b|\b[A-Z][A-Z0-9]{0,12}-\d+\b")

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

def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def dpath(target: Path, legacy_rel: str | Path) -> Path:
    return existing_or_target_path(target, legacy_rel)

def runtime_path(target: Path, legacy_rel: str | Path) -> Path:
    return target_path(target, legacy_rel)

def script_path(target: Path, legacy_rel: str | Path) -> Path:
    return existing_or_target_path(target, legacy_rel)

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

def env_non_negative_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value >= 0 else default

def role_timeout_seconds() -> int:
    return env_non_negative_int("CODEX_ROLE_TIMEOUT_SECONDS", DEFAULT_ROLE_TIMEOUT_SECONDS)

def role_termination_grace_seconds() -> int:
    return env_non_negative_int("CODEX_ROLE_TERMINATION_GRACE_SECONDS", DEFAULT_ROLE_TERMINATION_GRACE_SECONDS)

def role_timeout_streak_limit() -> int:
    return env_non_negative_int("CODEX_ROLE_TIMEOUT_STREAK_LIMIT", DEFAULT_ROLE_TIMEOUT_STREAK_LIMIT)

def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def load_state(path: Path) -> dict[str, Any]:
    return load_conveyor_state(path)

def write_state(
    path: Path,
    state: dict[str, Any],
    *,
    event_type: str = "conveyor.state_projection_updated",
    actor_role: str = "conveyor",
    phase: str = "",
    status: str = "ACTIVE",
    payload: dict[str, Any] | None = None,
) -> None:
    write_conveyor_state(
        path,
        state,
        event_type=event_type,
        actor_role=actor_role,
        phase=phase,
        status=status,
        payload=payload,
    )

def command_display(command: list[str]) -> str:
    return " ".join(command)

def split_h2_sections(text: str) -> tuple[str, dict[str, str], list[str]]:
    lines = text.splitlines()
    header_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current: str | None = None
    for line in lines:
        if line.startswith("## "):
            current = line.removeprefix("## ").strip()
            sections[current] = []
            order.append(current)
        elif current is None:
            header_lines.append(line)
        else:
            sections[current].append(line)
    return "\n".join(header_lines).strip(), {key: "\n".join(value).strip() for key, value in sections.items()}, order

def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed

def git_head_status(target: Path) -> tuple[str, str]:
    if not target.exists():
        return ("not_a_repo", f"{target} does not exist")
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return ("error", "git executable not found on PATH")
    if proc.returncode == 0:
        return ("ok", "")
    stderr = (proc.stderr or "").strip()
    if "not a git repository" in stderr.lower():
        return ("not_a_repo", f"{target} is not a git repository")
    if "ambiguous argument 'head'" in stderr.lower() or "unknown revision" in stderr.lower():
        return ("no_commits", "git repository has no commits yet")
    return ("error", stderr or f"git rev-parse exited {proc.returncode}")

def report_preflight_failure(status: str, detail: str, target: Path) -> None:
    lines = [
        f"CONVEYOR_PREFLIGHT_FAILED status={status} target={target}",
        f"  reason: {detail}",
    ]
    if status == "no_commits":
        lines.append(
            "  fix: run `git add . && git commit -m 'chore: initial commit'` in the target."
        )
        lines.append(
            "  the conveyor needs a HEAD commit to branch role worktrees from."
        )
    elif status == "not_a_repo":
        lines.append(
            "  fix: run `git init && git add . && git commit -m 'chore: initial commit'` in the target."
        )
    print("\n".join(lines), file=sys.stderr, flush=True)
