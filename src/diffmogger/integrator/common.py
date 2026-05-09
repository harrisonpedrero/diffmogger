from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shutil
import shlex
import subprocess
import stat
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from diffmogger.runtime.paths import existing_or_target_path, load_manifest, manifest_list as manifest_path_list, sidecar_rel, target_path

QUEUE_ROLES = ("planner", "builder", "hardener")

ALL_ROLES = (*QUEUE_ROLES, "integrator")

DEFERRAL_REASONS = {
    "staleness",
    "conflict",
    "verification_failure",
    "verification_environment_failure",
    "baseline_verification_blocker",
    "guardrail_violation",
    "other",
}

BASELINE_VERIFICATION_RELATIVE = Path("target/baseline_verification.json")

BASELINE_SCHEMA_VERSION = 1

RUNTIME_STATE_WHITELIST = {
    ".agentic/automation_prompt.md",
    ".agentic/smoke_commands.txt",
    ".agentic/verification_commands.txt",
    ".agentic/roles/planner.md",
    ".agentic/roles/builder.md",
    ".agentic/roles/hardener.md",
    ".agentic/roles/integrator.md",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "target/automation_runner.json",
}

RUNTIME_STATE_ALLOWED_PREFIXES = (".agentic/", "docs/")

RUNTIME_STATE_DENY_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "automation_queue",
    "automation_worktrees",
    "automation_logs",
    "automation_venvs",
}

RUNTIME_STATE_DENY_NAMES = {".DS_Store", "codex_automation.lock", "automation_conveyor.lock"}

RUNTIME_STATE_DENY_SUFFIXES = (
    ".7z",
    ".db",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".lock",
    ".log",
    ".pdf",
    ".png",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".tar",
    ".tgz",
    ".zip",
)

RUNTIME_STATE_MAX_BYTES = 1024 * 1024

RUNTIME_STATE_BLOCKING_STATUSES = {"blocked", "conflict", "error", "rejected"}

RUNTIME_STATE_VOLATILE_PATHS = {"target/automation_runner.json", sidecar_rel("target/automation_runner.json")}

PROGRESS_SECTIONS = [
    "Project State At Last Integration",
    "Cumulative Metrics",
    "Recent Activity Log",
    "Historical Summary",
    "Deferred-Patch Backlog",
    "Architectural Decisions",
    "Role Health",
]

NOTIFIER_URL = "http://127.0.0.1:8765/api/notify"

ENVIRONMENT_FAILURE_CATEGORIES = {
    "db_schema_drift",
    "missing_local_database",
    "missing_env_var",
    "missing_verification_config",
    "missing_package_executable",
    "missing_pytest",
}

REPAIRABLE_LOCAL_SERVICE_CATEGORIES = {
    "missing_local_database",
    "missing_env_var",
}

TYPESCRIPT_COMPILER_ERROR_RE = re.compile(r"\berror\s+TS\d{3,5}\b", re.IGNORECASE)

DEFAULT_GIT_INDEX_LOCK_STALE_SECONDS = 120

DEFAULT_GIT_INDEX_LOCK_WAIT_SECONDS = 30

DEFAULT_GIT_INDEX_LOCK_RETRY_SECONDS = 5

GIT_INDEX_LOCK_MUTATING_COMMANDS = {
    "add",
    "am",
    "apply",
    "checkout",
    "cherry-pick",
    "commit",
    "merge",
    "mv",
    "read-tree",
    "rebase",
    "reset",
    "restore",
    "rm",
    "stash",
    "switch",
    "update-index",
}

SEMANTIC_COMMIT_TYPES = {"feat", "fix", "docs", "test", "refactor", "chore", "build", "ci", "perf", "style"}

AUTOMATION_BOOKKEEPING_FILES = {
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    sidecar_rel("docs/CODEX_AUTOMATION_TASKS.md"),
    sidecar_rel("docs/MULTI_ROLE_PROGRESS.md"),
    sidecar_rel("target/automation_runner.json"),
}

CONVENTIONAL_SUBJECT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?:\s+(?P<action>.+)$")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

LOCAL_PATH_RE = re.compile(r"(?<![\w.])/(?:Users|private/tmp|tmp|var/folders)/[^\s`'\"<>)]*")

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def now_id() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")

def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def project_intake(target: Path) -> dict[str, Any]:
    return read_json(existing_or_target_path(target, ".agentic/project_intake.json"))

def dpath(target: Path, legacy_rel: str | Path) -> Path:
    return existing_or_target_path(target, legacy_rel)

def runtime_path(target: Path, legacy_rel: str | Path) -> Path:
    return target_path(target, legacy_rel)

def human_bridge_mode(target: Path) -> str:
    mode = str(project_intake(target).get("human_bridge_mode") or "file_only").strip().lower()
    return mode if mode in {"disabled", "file_only", "local_notifier", "discord_notifier"} else "file_only"

def run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = False,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )

def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(0, parsed)

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file() or path.is_symlink():
        return None
    return sha256_bytes(path.read_bytes())

def scrub_local_references(text: str, target: Path) -> str:
    text = ANSI_RE.sub("", str(text))
    replacements = {
        str(target): "<target>",
        str(Path.home()): "<home>",
        "agentic-kit-" + "lab": "<workspace>",
    }
    for old, new in replacements.items():
        if old:
            text = text.replace(old, new)
    return LOCAL_PATH_RE.sub("<local-path>", text)

def progress_inline(text: str, target: Path, *, limit: int = 240) -> str:
    scrubbed = scrub_local_references(text, target)
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip()
    if not scrubbed:
        return "No detail."
    if len(scrubbed) > limit:
        return scrubbed[: limit - 3].rstrip() + "..."
    return scrubbed
