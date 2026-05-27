from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from diffmogger.runtime.paths import existing_or_target_path, target_path, target_rel

ROLES = ("planner", "designer", "builder", "hardener", "integrator")

QUEUE_STATUSES = ("queued", "deferred", "applied", "failed", "skipped", "superseded")

MAX_MANIFESTS = 18

MAX_OUTCOMES = 12

MAX_HISTORY = 80

MAX_LOG_FILES = 8

MAX_LOG_LINE_CHARS = 220

MAX_REVIEW_ITEMS = 6

MAX_CHECK_ITEMS = 8

MAX_SCORECARD_ITEMS = 8

MAX_RECOMMENDATION_HISTORY = 5

MAX_WORKER_STRATEGY_REASONS = 4

ACTION_PLAN_HISTORY_RELATIVE = Path("target/action_plan_history.json")

INTEGRATION_SAFETY_RECORD_RELATIVE = Path("target/integration_safety_check.json")

FIRST_REVIEW_OBSERVATORY_FILENAME = "Diffmogger-observatory.html"

FIRST_REVIEW_SELF_REVIEW_FILENAME = "Diffmogger-self-review.md"

FIRST_REVIEW_MARKERS = (
    ("starter validation", "bash scripts/validate_starter_kit.sh"),
    ("dashboard safety", "Run Safety Check"),
    ("observatory HTML", FIRST_REVIEW_OBSERVATORY_FILENAME),
    ("Markdown self-review", FIRST_REVIEW_SELF_REVIEW_FILENAME),
)

FIRST_REVIEW_DOC_CANDIDATES = (
    "docs/DEVELOPMENT.md",
    "README.md",
    "docs/DASHBOARD.md",
    "docs/FRESH_PROJECT_SETUP.md",
    "services/agentic-dashboard/README.md",
)

DEFERRAL_REASON_ACTIONS = {
    "staleness": "Refresh or recreate the patch from current HEAD, then retry only if the change still matters.",
    "conflict": "Inspect the listed files and replace the patch with a freshly reconciled local change.",
    "verification_failure": "Re-run the failing command locally, fix the source or test issue, then submit a new verified patch.",
    "verification_environment_failure": "Repair project-local tooling or fixtures first, then rerun verification before retrying.",
    "baseline_verification_blocker": "Repair the clean-HEAD full-suite baseline, then retry full-suite-required patches.",
    "guardrail_violation": "Do not apply as-is; replace it with a guardrail-compliant local patch or archive it.",
    "other": "Inspect the manifest and summary, then choose retry, replacement, archival, or documentation.",
}

DEFERRAL_REASON_ORDER = tuple(DEFERRAL_REASON_ACTIONS)

EMPTY_DEFERRED_BACKLOG_MARKERS = {
    "none",
    "none.",
    "no deferred backlog recorded",
    "no deferred backlog recorded.",
}

EMPTY_STATES = {
    "next_up": "No activity decision yet. After the first automation cycle, the next local role lane and reason will appear here.",
    "patch_queue": "No queued or deferred patches yet. First role patch manifests will appear here after planner, designer, builder, or hardener lanes write local queue outputs.",
    "recent_outcomes": "No integration outcomes yet. Applied, failed, skipped, and deferred role outputs appear here after integrator review.",
    "timeline": "No activity timeline yet. Completed role runs will appear here with exit status, progress result, and integration notes.",
}

CONVENTIONAL_SUBJECT_RE = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([a-z0-9-]+\))?!?: .+"
)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def read_text(path: Path, limit: int | None = None) -> str:
    try:
        if limit is None:
            return path.read_text(encoding="utf-8", errors="replace")
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
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

def read_tail_text(path: Path, max_bytes: int = 40_000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""

def process_alive(pid: Any) -> bool:
    try:
        parsed = int(pid)
    except (TypeError, ValueError):
        return False
    if parsed <= 0:
        return False
    try:
        os.kill(parsed, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def clean_text(value: Any, *, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
    if len(text) > limit:
        return text[: max(0, limit - 15)].rstrip() + " ... [truncated]"
    return text

def first_nonempty_section_line(text: str, heading: str) -> str:
    section = markdown_section(text, heading)
    for raw in section.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            return clean_text(re.sub(r"^[-*]\s+", "", line), limit=220)
    return ""

def markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end]

def section_bullets(text: str, heading: str, *, limit: int = MAX_REVIEW_ITEMS) -> list[str]:
    section = markdown_section(text, heading)
    bullets: list[str] = []
    in_code_block = False
    for raw in section.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line.startswith("- "):
            continue
        item = clean_text(line[2:], limit=260)
        if item:
            bullets.append(item)
        if len(bullets) >= limit:
            break
    return bullets

def keyed_section_value(text: str, heading: str, keys: list[str]) -> str:
    section = markdown_section(text, heading)
    for key in keys:
        match = re.search(rf"^-\s*{re.escape(key)}:\s*(.+)", section, re.MULTILINE)
        if match:
            value = clean_text(match.group(1), limit=260)
            if value:
                return value
    return ""

def task_bool_value(text: str, label: str, *, default: bool) -> bool:
    match = re.search(rf"^-\s*{re.escape(label)}:\s*(true|false)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return default
    return match.group(1).lower() == "true"

def task_int_value(text: str, label: str, *, default: int, minimum: int = 0, maximum: int = 10) -> int:
    match = re.search(rf"^-\s*{re.escape(label)}:\s*(\d+)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return default
    try:
        value = int(match.group(1))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)

def strip_fenced_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)

def concrete_record_heading(prefix: str) -> re.Pattern[str]:
    return re.compile(
        rf"^(#{{2,6}})\s+({re.escape(prefix)}-\d{{4}}-\d{{2}}-\d{{2}}(?:-[A-Za-z0-9]+)+)\s*$",
        re.MULTILINE,
    )

def concrete_record_ranges(text: str, prefix: str) -> list[tuple[str, str]]:
    text = strip_fenced_code_blocks(text)
    record_matches = list(concrete_record_heading(prefix).finditer(text))
    all_headings = list(re.finditer(r"^(#{1,6})\s+.+$", text, re.MULTILINE))
    records: list[tuple[str, str]] = []
    for match in record_matches:
        level = len(match.group(1))
        end = len(text)
        for heading_match in all_headings:
            if heading_match.start() <= match.start():
                continue
            if len(heading_match.group(1)) <= level:
                end = heading_match.start()
                break
        records.append((match.group(2), text[match.end() : end]))
    return records

def count_concrete_records(path: Path, prefix: str) -> int:
    return len(concrete_record_ranges(read_text(path), prefix))

def count_concrete_records_with_status(
    path: Path,
    prefix: str,
    active_statuses: set[str],
) -> int:
    count = 0
    for _record_id, record in concrete_record_ranges(read_text(path), prefix):
        status_match = re.search(r"^-\s*status:\s*([A-Za-z0-9_-]+)", record, re.MULTILINE | re.IGNORECASE)
        status = status_match.group(1).lower() if status_match else ""
        if status in active_statuses:
            count += 1
    return count
