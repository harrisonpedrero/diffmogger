#!/usr/bin/env python3
"""Native local dashboard for configuring and observing Diffmogger projects."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import plistlib
import queue
import re
import shlex
import select
import signal
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


KIT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = KIT_ROOT / "scripts"
SCAFFOLD_SCRIPT = SCRIPTS_DIR / "scaffold_project_docs.py"
CHECK_REQUIRED_SCRIPT = SCRIPTS_DIR / "check_required_files.py"
OBSERVATORY_SCRIPT = SCRIPTS_DIR / "run_observatory.py"
INTEGRATION_SAFETY_SCRIPT = SCRIPTS_DIR / "check_integration_safety.py"
DEFAULT_REVIEW_BUNDLE_DIR = Path("/tmp/Diffmogger-review")
INTEGRATION_SAFETY_RECORD_RELATIVE = Path("target/integration_safety_check.json")
LAUNCHD_LABEL_PREFIX = "com.diffmogger.automation"
SCHEDULABLE_STATUSES = {"ACTIVE", "ACTIVE_WITH_PENDING_USER_INPUT"}
MIN_CADENCE_MINUTES = 30
MAX_CADENCE_MINUTES = 10080
DEFAULT_CADENCE_MINUTES = 60
MAX_WRITE_WORKER_COUNT = 10
DEFAULT_WRITE_WORKER_COUNT = 3
DEFAULT_MULTI_ROLE_BASE_CADENCE_MINUTES = 30
DEFAULT_AUTOMATION_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
MULTI_ROLE_PROFILE = "planner_builder_hardener_integrator"
MULTI_ROLE_ROLES = ("planner", "builder", "hardener", "integrator")
MULTI_ROLE_START_MINUTES = {
    "planner": [0],
    "builder": [10, 40],
    "hardener": [20, 50],
    "integrator": [25, 55],
}
SCHEDULE_STRATEGY_SINGLE = "single_lane_interval"
SCHEDULE_STRATEGY_FIXED_MULTI_ROLE = "fixed_multi_role"
SCHEDULE_STRATEGY_CONVEYOR = "continuous_conveyor"
SCHEDULE_STRATEGY_LABELS = {
    SCHEDULE_STRATEGY_SINGLE: "Periodic sprint",
    SCHEDULE_STRATEGY_FIXED_MULTI_ROLE: "Fixed multi-role cadence",
    SCHEDULE_STRATEGY_CONVEYOR: "Continuous conveyor",
}
SCHEDULE_STRATEGY_BY_LABEL = {label: key for key, label in SCHEDULE_STRATEGY_LABELS.items()}
ENV_ACCESS_PROJECT_COMMANDS_ONLY = "project_commands_only"
ENV_ACCESS_DIRECT = "direct_env_files_allowed"
ENV_ACCESS_LABELS = {
    ENV_ACCESS_PROJECT_COMMANDS_ONLY: "Project commands only",
    ENV_ACCESS_DIRECT: "Allow direct .env reads",
}
ENV_ACCESS_BY_LABEL = {label: key for key, label in ENV_ACCESS_LABELS.items()}
MAX_DASHBOARD_LOG_LINES = 1200
MAX_DASHBOARD_LOG_LINE_CHARS = 4000
DASHBOARD_STATE_FILE = ".agentic/dashboard_state.json"
CONTEXT_IMPORTS_START = "<!-- DIFFMOGGER:CONTEXT-IMPORTS:START -->"
CONTEXT_IMPORTS_END = "<!-- DIFFMOGGER:CONTEXT-IMPORTS:END -->"
WORKER_STRATEGY_NAMES = {"NO_WORKERS", "READ_ONLY_REPORTS", "WRITE_WORKERS", "INTEGRATION_ONLY"}
WORKER_REPORT_STRATEGIES = {"READ_ONLY_REPORTS", "WRITE_WORKERS"}

DOC_CHOICES = {
    "Automation Tasks": "docs/CODEX_AUTOMATION_TASKS.md",
    "Multi-Role Progress": "docs/MULTI_ROLE_PROGRESS.md",
    "Project Context": "docs/PROJECT_CONTEXT.md",
    "Human Requests": "docs/HUMAN_REQUESTS.md",
    "Human Inbox": "docs/HUMAN_INBOX.md",
    "Human Outbox": "docs/HUMAN_OUTBOX.md",
    "Daily Review": "docs/DAILY_AUTOMATION_REVIEW.md",
    "Experiment Log": "docs/AUTONOMY_EXPERIMENT_LOG.md",
    "Initial Bootstrap Prompt": "docs/INITIAL_BOOTSTRAP_PROMPT.md",
    "Automation Prompt": ".agentic/automation_prompt.md",
}

HUMAN_DOC_CHOICES = {
    "Requests From Automation": "docs/HUMAN_REQUESTS.md",
    "Messages Waiting For Next Run": "docs/HUMAN_INBOX.md",
    "Sent Updates & Delivery Log": "docs/HUMAN_OUTBOX.md",
    "Resolved Conversation History": "docs/HUMAN_RESPONSES_ARCHIVE.md",
}

INTENT_CHOICES = {
    "General note": "info",
    "Done / completed": "done",
    "Skip this request": "skip",
    "Approved": "approve",
    "Rejected": "reject",
    "Not sure": "unknown",
}

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    TK_AVAILABLE = True
    TK_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - depends on host Python build.
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    ScrolledText = None  # type: ignore[assignment]
    TK_AVAILABLE = False
    TK_IMPORT_ERROR = str(exc)


@dataclass(frozen=True)
class PrerequisiteItem:
    name: str
    ok: bool
    required: bool
    detail: str


@dataclass(frozen=True)
class ContextRecord:
    rel_path: str
    original_name: str
    size_bytes: int


def load_scaffold_module() -> Any:
    spec = importlib.util.spec_from_file_location("diffmogger_scaffold", SCAFFOLD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load scaffold script at {SCAFFOLD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_observatory_module() -> Any:
    spec = importlib.util.spec_from_file_location("diffmogger_observatory", OBSERVATORY_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load observatory script at {OBSERVATORY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw in value.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        lines.append(line)
    return lines


def nearest_existing_parent(path: Path) -> Path:
    current = path.expanduser()
    if current.exists():
        return current if current.is_dir() else current.parent
    for parent in current.parents:
        if parent.exists():
            return parent
    return Path.cwd()


def path_is_under(child: Path, parent: Path) -> bool:
    try:
        child.expanduser().resolve().relative_to(parent.expanduser().resolve())
        return True
    except ValueError:
        return False
    except OSError:
        return False


def command_detail(command: str, args: list[str] | None = None, timeout: int = 4) -> tuple[bool, str]:
    path = shutil.which(command)
    if not path:
        return False, f"`{command}` not found on PATH."
    if not args:
        return True, path
    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return True, f"{path}; version check failed: {exc}"
    output = (result.stdout or result.stderr).strip().splitlines()
    suffix = output[0] if output else "installed"
    return True, f"{path}; {suffix}"


def parse_cadence_seconds(value: str) -> int:
    text = value.strip()
    if not re.fullmatch(r"\d+", text):
        raise ValueError("Automation cadence must be an integer number of minutes greater than 30.")
    minutes = int(text)
    if minutes < MIN_CADENCE_MINUTES:
        raise ValueError("Automation cadence must be greater than 30 minutes.")
    if minutes > MAX_CADENCE_MINUTES:
        raise ValueError("Automation cadence must be 10080 minutes or less.")
    return minutes * 60


def cadence_minutes_from_text(value: Any) -> int:
    text = str(value or "").strip().lower()
    if not text:
        return DEFAULT_CADENCE_MINUTES
    if re.fullmatch(r"\d+", text):
        minutes = int(text)
    else:
        minute_match = re.search(r"(\d+)\s*(?:minutes?|mins?|m)\b", text)
        hour_match = re.search(r"(\d+)\s*(?:hours?|hrs?|h)\b", text)
        if "hourly" in text or text == "hour":
            minutes = 60
        elif "daily" in text:
            minutes = 1440
        elif minute_match:
            minutes = int(minute_match.group(1))
        elif hour_match:
            minutes = int(hour_match.group(1)) * 60
        else:
            return DEFAULT_CADENCE_MINUTES
    return min(MAX_CADENCE_MINUTES, max(MIN_CADENCE_MINUTES, minutes))


def multi_role_cadence_minutes_from_text(value: Any) -> int:
    if value is None or str(value).strip() == "":
        return DEFAULT_MULTI_ROLE_BASE_CADENCE_MINUTES
    return max(DEFAULT_MULTI_ROLE_BASE_CADENCE_MINUTES, cadence_minutes_from_text(value))


def schedule_strategy_from_value(value: Any, *, multi_role_enabled: bool = False) -> str:
    text = str(value or "").strip()
    if text in SCHEDULE_STRATEGY_BY_LABEL:
        return SCHEDULE_STRATEGY_BY_LABEL[text]
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if normalized in SCHEDULE_STRATEGY_LABELS:
        return normalized
    if any(term in normalized for term in ("conveyor", "continuous", "work_conserving", "workconserving")):
        return SCHEDULE_STRATEGY_CONVEYOR
    if any(term in normalized for term in ("fixed", "staggered", "calendar", "role")):
        return SCHEDULE_STRATEGY_FIXED_MULTI_ROLE
    if any(term in normalized for term in ("single", "periodic", "interval", "cadence")):
        return SCHEDULE_STRATEGY_SINGLE
    return SCHEDULE_STRATEGY_FIXED_MULTI_ROLE if multi_role_enabled else SCHEDULE_STRATEGY_SINGLE


def env_access_policy_from_value(value: Any) -> str:
    text = str(value or "").strip()
    if text in ENV_ACCESS_LABELS:
        return text
    if text in ENV_ACCESS_BY_LABEL:
        return ENV_ACCESS_BY_LABEL[text]
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if normalized in {"direct_env_files_allowed", "allow_direct_env_files", "allow_env_files"}:
        return ENV_ACCESS_DIRECT
    return ENV_ACCESS_PROJECT_COMMANDS_ONLY


def write_worker_count_from_text(value: Any, *, enabled: bool) -> int:
    if not enabled:
        return 0
    text = str(value or "").strip()
    match = re.search(r"\d+", text)
    count = int(match.group(0)) if match else DEFAULT_WRITE_WORKER_COUNT
    return min(MAX_WRITE_WORKER_COUNT, max(1, count))


def bool_from_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def format_interval(seconds: int) -> str:
    minutes = max(1, seconds // 60)
    return f"every {minutes} minutes"


def launchd_label(target: Path) -> str:
    target = target.expanduser().resolve()
    base = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-") or "project"
    digest = hashlib.sha1(str(target).encode("utf-8")).hexdigest()[:10]
    return f"{LAUNCHD_LABEL_PREFIX}.{base}.{digest}"


def launchd_role_label(target: Path, role: str) -> str:
    return f"{launchd_label(target)}.{role}"


def launchd_conveyor_label(target: Path) -> str:
    return f"{launchd_label(target)}.conveyor"


def launchd_plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def launchd_service_target(label: str) -> str:
    return f"gui/{os.getuid()}/{label}"


def launchd_domain_target() -> str:
    return f"gui/{os.getuid()}"


def launchd_log_dir(target: Path) -> Path:
    return target.expanduser().resolve() / "target" / "automation_logs"


def dashboard_state_path(target: Path) -> Path:
    return target.expanduser().resolve() / DASHBOARD_STATE_FILE


def default_browser_cache_dir() -> Path:
    configured = os.environ.get("DIFFMOGGER_BROWSER_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "diffmogger" / "browsers"


def managed_browser_path() -> str | None:
    cache_dir = default_browser_cache_dir()
    if not cache_dir.exists():
        return None
    names = {"chrome-headless-shell", "chrome", "Google Chrome for Testing", "Chromium"}
    candidates = [
        path
        for path in cache_dir.rglob("*")
        if path.is_file() and path.name in names and os.access(path, os.X_OK) and "Crashpad" not in path.parts
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return str(candidates[0]) if candidates else None


def automation_environment(target: Path, *, allow_remotes: bool = False) -> dict[str, str]:
    environment = {
        "TARGET": str(target),
        "PATH": DEFAULT_AUTOMATION_PATH,
        "HOME": str(Path.home()),
        "DIFFMOGGER_BROWSER_CACHE": str(default_browser_cache_dir()),
    }
    env_browser = os.environ.get("DIFFMOGGER_BROWSER_PATH", "").strip() or os.environ.get("CHROME_PATH", "").strip()
    browser_path = env_browser or managed_browser_path()
    if browser_path:
        environment["DIFFMOGGER_BROWSER_PATH"] = browser_path
        environment["CHROME_PATH"] = browser_path
    if allow_remotes:
        environment["MULTI_ROLE_ALLOW_REMOTES"] = "1"
    return environment


def write_launchd_plist(target: Path, cadence_seconds: int) -> tuple[str, Path]:
    target = target.expanduser().resolve()
    label = launchd_label(target)
    plist_path = launchd_plist_path(label)
    log_dir = launchd_log_dir(target)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": label,
        "ProgramArguments": ["/bin/bash", str(target / "scripts" / "run_codex_automation.sh")],
        "WorkingDirectory": str(target),
        "RunAtLoad": True,
        "StartInterval": cadence_seconds,
        "StandardOutPath": str(log_dir / "stdout.log"),
        "StandardErrorPath": str(log_dir / "stderr.log"),
        "EnvironmentVariables": automation_environment(target),
    }
    plist_path.write_bytes(plistlib.dumps(plist, sort_keys=True))
    return label, plist_path


def write_role_launchd_plist(target: Path, role: str, *, allow_remotes: bool = False) -> tuple[str, Path]:
    if role not in MULTI_ROLE_ROLES:
        raise ValueError(f"Invalid multi-role automation role: {role}")
    target = target.expanduser().resolve()
    label = launchd_role_label(target, role)
    plist_path = launchd_plist_path(label)
    log_dir = launchd_log_dir(target)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    minutes = MULTI_ROLE_START_MINUTES[role]
    intervals: dict[str, int] | list[dict[str, int]]
    if len(minutes) == 1:
        intervals = {"Minute": minutes[0]}
    else:
        intervals = [{"Minute": minute} for minute in minutes]
    environment = automation_environment(target, allow_remotes=allow_remotes)
    plist = {
        "Label": label,
        "ProgramArguments": [
            "/bin/bash",
            str(target / "scripts" / "run_role_automation.sh"),
            "--role",
            role,
        ],
        "WorkingDirectory": str(target),
        "RunAtLoad": False,
        "StartCalendarInterval": intervals,
        "StandardOutPath": str(log_dir / f"{role}.stdout.log"),
        "StandardErrorPath": str(log_dir / f"{role}.stderr.log"),
        "EnvironmentVariables": environment,
    }
    plist_path.write_bytes(plistlib.dumps(plist, sort_keys=True))
    return label, plist_path


def write_conveyor_launchd_plist(target: Path, *, allow_remotes: bool = False) -> tuple[str, Path]:
    target = target.expanduser().resolve()
    label = launchd_conveyor_label(target)
    plist_path = launchd_plist_path(label)
    log_dir = launchd_log_dir(target)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    environment = automation_environment(target, allow_remotes=allow_remotes)
    plist = {
        "Label": label,
        "ProgramArguments": [
            "/bin/bash",
            str(target / "scripts" / "run_conveyor_automation.sh"),
        ],
        "WorkingDirectory": str(target),
        "RunAtLoad": True,
        "StandardOutPath": str(log_dir / "conveyor.stdout.log"),
        "StandardErrorPath": str(log_dir / "conveyor.stderr.log"),
        "EnvironmentVariables": environment,
    }
    plist_path.write_bytes(plistlib.dumps(plist, sort_keys=True))
    return label, plist_path


def target_has_initial_commit(target: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def context_record_line(record: ContextRecord) -> str:
    return f"- `{record.rel_path}` ({record.original_name}, {record.size_bytes} bytes)"


def render_context_imports_section(project_name: str, lines: list[str]) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body = "\n".join(lines) if lines else "- No imported context files are currently indexed."
    return f"""{CONTEXT_IMPORTS_START}
## Diffmogger Imported Context Files

Managed context index for `{project_name}`. Do not place secrets, credentials, paid-account exports, or private production data here.

Generated at: {now}

{body}
{CONTEXT_IMPORTS_END}
"""


def upsert_context_imports(existing: str, project_name: str, records: list[ContextRecord]) -> str:
    lines_by_rel: dict[str, str] = {}
    pattern = re.compile(
        rf"{re.escape(CONTEXT_IMPORTS_START)}(?P<body>.*?){re.escape(CONTEXT_IMPORTS_END)}",
        re.DOTALL,
    )
    match = pattern.search(existing)
    if match:
        for line in match.group("body").splitlines():
            line = line.strip()
            rel_match = re.match(r"- `([^`]+)`", line)
            if rel_match:
                lines_by_rel[rel_match.group(1)] = line
    for record in records:
        lines_by_rel[record.rel_path] = context_record_line(record)
    section = render_context_imports_section(project_name, list(lines_by_rel.values()))
    if match:
        return pattern.sub(section.rstrip(), existing).rstrip() + "\n"
    separator = "\n\n" if existing.rstrip() else ""
    return existing.rstrip() + separator + section


def fetch_notifier_health(timeout: float = 0.6) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        configured = payload.get("target_repo_configured")
        discord = payload.get("discord_configured")
        local = payload.get("local_notifications_enabled")
        return True, (
            "agentic-notifier is reachable; "
            f"target_repo_configured={configured}; discord_configured={discord}; "
            f"local_notifications_enabled={local}."
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return False, f"agentic-notifier is not reachable on 127.0.0.1:8765 ({exc})."


def check_prerequisites(target: Path, human_bridge_mode: str) -> list[PrerequisiteItem]:
    items: list[PrerequisiteItem] = []

    py_ok = sys.version_info >= (3, 10)
    items.append(
        PrerequisiteItem(
            "Python 3.10+",
            py_ok,
            True,
            f"Running {sys.version.split()[0]}.",
        )
    )
    items.append(
        PrerequisiteItem(
            "Tkinter GUI runtime",
            TK_AVAILABLE,
            True,
            "Available." if TK_AVAILABLE else TK_IMPORT_ERROR,
        )
    )

    codex_ok, codex_detail = command_detail("codex", ["--version"])
    items.append(
        PrerequisiteItem(
            "Codex CLI installed and signed in",
            codex_ok,
            True,
            codex_detail if codex_ok else codex_detail + " Install and run `codex` once before bootstrapping.",
        )
    )

    bash_ok, bash_detail = command_detail("bash", ["--version"])
    items.append(PrerequisiteItem("bash available", bash_ok, True, bash_detail))

    git_ok, git_detail = command_detail("git", ["--version"])
    items.append(PrerequisiteItem("git available", git_ok, True, git_detail))

    parent = nearest_existing_parent(target)
    writable = parent.exists() and os.access(parent, os.W_OK)
    items.append(
        PrerequisiteItem(
            "Target parent directory writable",
            writable,
            True,
            f"Nearest existing parent: {parent}",
        )
    )

    codex_home = Path.home() / ".codex"
    items.append(
        PrerequisiteItem(
            "Codex home accessible for nested workers",
            codex_home.exists(),
            False,
            f"{codex_home} exists." if codex_home.exists() else f"{codex_home} does not exist yet; run `codex` interactively once if workers fail.",
        )
    )

    if sys.platform == "darwin" and path_is_under(target, Path.home() / "Documents"):
        items.append(
            PrerequisiteItem(
                "macOS Documents permission note",
                False,
                False,
                "Targets under ~/Documents may need Full Disk Access for /bin/bash and the Node executable used by Codex when scheduled.",
            )
        )
    else:
        items.append(
            PrerequisiteItem(
                "macOS Documents permission note",
                True,
                False,
                "No Documents-folder advisory for the selected target.",
            )
        )

    if human_bridge_mode in {"local_notifier", "discord_notifier"}:
        notifier_ok, notifier_detail = fetch_notifier_health()
        items.append(
            PrerequisiteItem(
                "Optional local notifier reachable",
                notifier_ok,
                False,
                notifier_detail + " File-only handoff remains available if notifier setup is incomplete.",
            )
        )

    return items


def format_prerequisites(items: list[PrerequisiteItem]) -> str:
    required = [item for item in items if item.required]
    optional = [item for item in items if not item.required]
    lines = ["Required before starting automation:"]
    for item in required:
        marker = "OK" if item.ok else "MISSING"
        lines.append(f"- [{marker}] {item.name}: {item.detail}")
    lines.append("")
    lines.append("Advisory and optional checks:")
    for item in optional:
        marker = "OK" if item.ok else "CHECK"
        lines.append(f"- [{marker}] {item.name}: {item.detail}")
    return "\n".join(lines)


def required_failures(items: list[PrerequisiteItem]) -> list[PrerequisiteItem]:
    return [item for item in items if item.required and not item.ok]


def has_integration_safety_tree(target: Path) -> bool:
    target = target.expanduser()
    return (
        (target / "scripts" / "check_integration_safety.py").is_file()
        and (target / "services" / "agentic-notifier").is_dir()
    )


def resolve_integration_safety_target(target: Path) -> Path:
    target = target.expanduser()
    if has_integration_safety_tree(target):
        return target.resolve()
    return KIT_ROOT


def integration_safety_command(target: Path) -> list[str]:
    return [
        sys.executable,
        str(INTEGRATION_SAFETY_SCRIPT),
        str(resolve_integration_safety_target(target)),
    ]


def integration_safety_record_path(target: Path) -> Path:
    return target.expanduser().resolve() / INTEGRATION_SAFETY_RECORD_RELATIVE


def write_integration_safety_record(
    selected_target: Path,
    checked_target: Path,
    command: list[str],
    exit_code: int,
) -> Path:
    selected_target = selected_target.expanduser().resolve()
    checked_target = checked_target.expanduser().resolve()
    status = "pass" if exit_code == 0 else "fail"
    status_word = "passed" if status == "pass" else "failed"
    checked_label = "the Diffmogger kit source" if checked_target == KIT_ROOT else str(checked_target)
    selected_label = selected_target.name or str(selected_target)
    if selected_target == checked_target:
        summary = f"Dashboard Run Safety Check {status_word} for {checked_label}."
    else:
        summary = (
            f"Dashboard Run Safety Check {status_word} against {checked_label} "
            f"for selected target {selected_label}."
        )
    record = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "dashboard_run_safety_check",
        "status": status,
        "exit_code": exit_code,
        "command": shlex.join(str(part) for part in command),
        "selected_target": str(selected_target),
        "checked_target": str(checked_target),
        "summary": summary,
    }
    record_path = integration_safety_record_path(selected_target)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record_path


def review_bundle_command(target: Path, review_dir: Path = DEFAULT_REVIEW_BUNDLE_DIR) -> list[str]:
    return [
        sys.executable,
        str(OBSERVATORY_SCRIPT),
        "--target",
        str(target.expanduser().resolve()),
        "--review-dir",
        str(review_dir),
    ]


def compact_dashboard_text(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def dashboard_run_id(prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-") or "dashboard"
    return f"{slug}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def dashboard_worker_strategy(target: Path) -> dict[str, Any]:
    module = load_observatory_module()
    snapshot = module.build_snapshot(target.expanduser().resolve())
    strategy = snapshot.get("worker_strategy") if isinstance(snapshot, dict) else {}
    if not isinstance(strategy, dict):
        return {}
    name = compact_dashboard_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    if name not in WORKER_STRATEGY_NAMES:
        strategy = dict(strategy)
        strategy["strategy"] = "NO_WORKERS"
    return strategy


def worker_strategy_summary(strategy: dict[str, Any]) -> str:
    if not strategy:
        return "Next worker strategy: unavailable until the observatory can read target state."
    name = compact_dashboard_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    try:
        budget = int(strategy.get("parallelism_budget") or 0)
    except (TypeError, ValueError):
        budget = 0
    lane = compact_dashboard_text(strategy.get("action_lane") or "local", limit=80)
    summary = compact_dashboard_text(
        strategy.get("summary") or "No next-run worker strategy summary recorded.",
        limit=360,
    )
    return f"Next worker strategy: {name} / budget {budget} / lane {lane}. {summary}"


def worker_summary_command(target: Path, run_id: str) -> list[str]:
    target = target.expanduser().resolve()
    return [
        sys.executable,
        str(target / "scripts" / "summarize_worker_outputs.py"),
        str(target),
        "--run-id",
        run_id,
    ]


def latest_worker_result(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    runs_dir = target / "target" / "agent_runs"
    result: dict[str, Any] = {
        "label": "Latest worker result: none yet.",
        "run_id": None,
        "report_count": 0,
        "summary_path": None,
        "summary_exists": False,
    }
    if not runs_dir.exists():
        return result

    run_dirs = [
        path
        for path in runs_dir.iterdir()
        if path.is_dir()
        and any(
            child.name.startswith("worker_")
            and child.name != "worker_summary.md"
            and child.suffix == ".md"
            for child in path.iterdir()
        )
    ]
    if not run_dirs:
        return result

    def newest_child_mtime(path: Path) -> float:
        children = [child for child in path.iterdir() if child.is_file()]
        if not children:
            return path.stat().st_mtime
        return max(child.stat().st_mtime for child in children)

    latest = max(run_dirs, key=newest_child_mtime)
    reports = sorted(
        path
        for path in latest.glob("worker_*.md")
        if path.name != "worker_summary.md"
    )
    summary_path = latest / "summary.md"
    report_word = "report" if len(reports) == 1 else "reports"
    if summary_path.exists():
        result["label"] = (
            f"Latest worker result: {latest.name} / {len(reports)} {report_word} / "
            f"summary ready at {summary_path.relative_to(target)}."
        )
        result["summary_path"] = str(summary_path)
        result["summary_exists"] = True
    else:
        result["label"] = (
            f"Latest worker result: {latest.name} / {len(reports)} {report_word} / "
            "summary not generated yet."
        )
    result["run_id"] = latest.name
    result["report_count"] = len(reports)
    return result


def worker_role_from_strategy(strategy: dict[str, Any]) -> str:
    lane = compact_dashboard_text(strategy.get("action_lane") or "review", limit=40).lower()
    if lane in {"planner", "builder", "hardener", "integrator"}:
        return f"{lane}_strategy"
    name = compact_dashboard_text(strategy.get("strategy") or "review", limit=40).lower()
    return f"{name}_strategy"


def worker_assignment_prompt(strategy: dict[str, Any], *, mode: str) -> str:
    summary = compact_dashboard_text(strategy.get("summary") or "", limit=600)
    reasons = [
        compact_dashboard_text(item, limit=300)
        for item in list(strategy.get("reasons") or [])
        if item
    ][:4]
    next_steps = [
        compact_dashboard_text(item, limit=360)
        for item in list(strategy.get("next_steps") or [])
        if item
    ][:5]
    lines = [
        f"Use the dashboard-observed next-run worker strategy `{compact_dashboard_text(strategy.get('strategy') or 'NO_WORKERS', limit=80)}`.",
        f"Action lane: `{compact_dashboard_text(strategy.get('action_lane') or 'local', limit=80)}`.",
    ]
    if summary:
        lines.append(f"Strategy summary: {summary}")
    if reasons:
        lines.append("Reasons:")
        lines.extend(f"- {reason}" for reason in reasons)
    if next_steps:
        lines.append("Suggested next steps:")
        lines.extend(f"- {step}" for step in next_steps)
    if mode == "write":
        lines.extend(
            [
                "",
                "Implement exactly one bounded slice inside the supplied ownership scope.",
                "Keep the main agent responsible for reviewing, integrating, and verifying your output.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Produce a concise read-only report that helps the next main automation run decide whether to follow this strategy, narrow it, or avoid it.",
            ]
        )
    return "\n".join(lines)


def normalize_worker_ownership_scope(ownership_scope: str) -> str:
    scope = re.sub(r"\s+", " ", str(ownership_scope or "").strip())
    if not scope:
        raise ValueError("write workers require a non-empty ownership scope")
    return scope


def read_only_worker_command(target: Path, strategy: dict[str, Any], *, run_id: str | None = None) -> list[str]:
    target = target.expanduser().resolve()
    return [
        "bash",
        str(target / "scripts" / "spawn_worker_agent.sh"),
        "--target",
        str(target),
        "--run-id",
        run_id or dashboard_run_id("dashboard-worker-report"),
        "--role",
        worker_role_from_strategy(strategy),
        "--read-only",
        "--prompt",
        worker_assignment_prompt(strategy, mode="read-only"),
    ]


def write_worker_command(
    target: Path,
    strategy: dict[str, Any],
    ownership_scope: str,
    *,
    run_id: str | None = None,
) -> list[str]:
    target = target.expanduser().resolve()
    ownership_scope = normalize_worker_ownership_scope(ownership_scope)
    return [
        "bash",
        str(target / "scripts" / "spawn_worker_agent.sh"),
        "--target",
        str(target),
        "--run-id",
        run_id or dashboard_run_id("dashboard-write-worker"),
        "--role",
        worker_role_from_strategy(strategy),
        "--write",
        "--ownership",
        ownership_scope,
        "--prompt",
        worker_assignment_prompt(strategy, mode="write"),
    ]


def integration_only_command(target: Path, *, run_id: str | None = None) -> list[str]:
    target = target.expanduser().resolve()
    return [
        "env",
        f"CODEX_RUN_ID={run_id or dashboard_run_id('dashboard-integrator')}",
        "bash",
        str(target / "scripts" / "run_role_automation.sh"),
        "--target",
        str(target),
        "--role",
        "integrator",
    ]


def safe_context_filename(name: str) -> str:
    source = Path(name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip(".-") or "context"
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", source.suffix)
    return f"{stem}{suffix}"


def copy_context_files(
    target: Path,
    context_paths: list[Path],
    log: Callable[[str], None],
) -> list[ContextRecord]:
    if not context_paths:
        return []

    context_dir = target / "docs" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    records: list[ContextRecord] = []
    used_names: set[str] = set()

    for source in context_paths:
        source = source.expanduser().resolve()
        if not source.exists() or not source.is_file():
            log(f"Skipping missing context file: {source}")
            continue
        base_name = safe_context_filename(source.name)
        candidate = base_name
        counter = 2
        while candidate in used_names or (context_dir / candidate).exists():
            stem = Path(base_name).stem
            suffix = Path(base_name).suffix
            candidate = f"{stem}-{counter}{suffix}"
            counter += 1
        used_names.add(candidate)
        dest = context_dir / candidate
        if source == dest.resolve():
            log(f"Context file already in target: {dest}")
        else:
            shutil.copy2(source, dest)
            log(f"Copied context file: {source.name} -> docs/context/{candidate}")
        records.append(
            ContextRecord(
                rel_path=f"docs/context/{candidate}",
                original_name=source.name,
                size_bytes=dest.stat().st_size,
            )
        )

    return records


def render_project_context(project_name: str, records: list[ContextRecord]) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    file_lines = (
        "\n".join(context_record_line(record) for record in records)
        if records
        else "- No additional context files were provided during scaffolding."
    )
    return f"""# Project Context

Additional reusable context for `{project_name}`.

Generated at: {now}

Use this file as an index for supplemental research, PDFs, notes, designs, and other source material copied into this target project. Do not place secrets, credentials, paid-account exports, or private production data here.

## Context Files

{file_lines}

## Automation Notes

- During bootstrap, inspect relevant context files when they help clarify the product goal, constraints, domain, or desired demo.
- Prefer concise summaries in task files instead of copying long passages from context sources.
- Treat binary context such as PDFs as reference material, not as executable input.
"""


def next_inbox_id(inbox_path: Path, now: datetime) -> str:
    date_prefix = now.strftime("%Y-%m-%d")
    if inbox_path.exists():
        text = inbox_path.read_text(encoding="utf-8")
    else:
        text = ""
    pattern = re.compile(rf"^## INBOX-{re.escape(date_prefix)}-(\d{{3,}})", re.MULTILINE)
    existing = [int(match.group(1)) for match in pattern.finditer(text)]
    return f"INBOX-{date_prefix}-{max(existing, default=0) + 1:03d}"


def append_manual_inbox_entry(
    target: Path,
    body: str,
    *,
    request_id: str,
    parsed_intent: str,
) -> str:
    docs_dir = target / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    inbox_path = docs_dir / "HUMAN_INBOX.md"
    if not inbox_path.exists():
        inbox_path.write_text(
            "# Human Inbox\n\nActive inbox for replies from the human owner.\n\n",
            encoding="utf-8",
        )
    now = datetime.now().astimezone()
    inbox_id = next_inbox_id(inbox_path, now)
    safe_request_id = request_id.strip() or "unknown"
    entry = f"""## {inbox_id}

- received_at: {now.isoformat(timespec="seconds")}
- channel: manual-dashboard
- from: dashboard
- to: automation
- request_id: {safe_request_id}
- parsed_intent: {parsed_intent.strip() or "info"}
    - message_id: manual-dashboard-{now.strftime("%Y%m%d%H%M%S")}
- status: unhandled

### Body

{body.strip()}

### Expected automation behavior

The next target project automation run should handle this message, update any related request state, then remove this entry from `docs/HUMAN_INBOX.md` and archive a concise resolution note in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
"""
    text = inbox_path.read_text(encoding="utf-8").rstrip()
    inbox_path.write_text(text + "\n\n" + entry + "\n", encoding="utf-8")
    return inbox_id


if TK_AVAILABLE:

    class DiffmoggerDashboard:
        def __init__(self, root: Any, initial_target: str = "") -> None:
            self.root = root
            self.root.title("Diffmogger Dashboard")
            self.root.geometry("1180x780")
            self.root.minsize(900, 620)
            self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
            self.running = False
            self.current_process: subprocess.Popen[str] | None = None
            self.observatory_processes: list[subprocess.Popen[str]] = []
            self.context_files: list[Path] = []
            self.bootstrap_completed_targets: set[Path] = set()
            self.log_line_count = 0

            self.target_var = tk.StringVar(value=initial_target)
            self.project_name_var = tk.StringVar(value="New Project")
            self.existing_project_var = tk.BooleanVar(value=False)
            self.human_bridge_enabled_var = tk.BooleanVar(value=True)
            self.bridge_mode_var = tk.StringVar(value="file_only")
            self.human_text_responses_var = tk.BooleanVar(value=True)
            self.local_notifications_enabled_var = tk.BooleanVar(value=True)
            self.cadence_var = tk.StringVar(value=str(DEFAULT_CADENCE_MINUTES))
            self.schedule_strategy_var = tk.StringVar(value=SCHEDULE_STRATEGY_LABELS[SCHEDULE_STRATEGY_SINGLE])
            self.force_var = tk.BooleanVar(value=False)
            self.worker_agents_var = tk.BooleanVar(value=True)
            self.codex_workers_var = tk.BooleanVar(value=True)
            self.write_worker_agents_var = tk.BooleanVar(value=False)
            self.max_write_worker_count_var = tk.StringVar(value=str(DEFAULT_WRITE_WORKER_COUNT))
            self.automation_signals_enabled_var = tk.BooleanVar(value=False)
            self.env_access_policy_var = tk.StringVar(value=ENV_ACCESS_LABELS[ENV_ACCESS_PROJECT_COMMANDS_ONLY])
            self.multi_role_automations_var = tk.BooleanVar(value=False)
            self.automation_role_profile_var = tk.StringVar(value="single_lane")
            self.automation_checkpoint_commits_var = tk.BooleanVar(value=True)
            self.multi_role_base_cadence_var = tk.StringVar(value=str(DEFAULT_MULTI_ROLE_BASE_CADENCE_MINUTES))
            self.multi_role_allow_remotes_var = tk.BooleanVar(value=False)
            self.ticket_campaign_enabled_var = tk.BooleanVar(value=False)
            self.ticket_run_file_var = tk.StringVar(value="docs/TICKET_RUN.md")
            self.ticket_completion_notify_var = tk.BooleanVar(value=True)
            self.status_var = tk.StringVar(value="No target loaded.")
            self.schedule_status_var = tk.StringVar(value="Schedule: target not loaded.")
            self.worker_strategy_var = tk.StringVar(value="Next worker strategy: not loaded.")
            self.worker_results_var = tk.StringVar(value="Latest worker result: none yet.")
            self.write_worker_ownership_var = tk.StringVar(value="")
            self.doc_choice_var = tk.StringVar(value="Automation Tasks")
            self.human_doc_choice_var = tk.StringVar(value="Requests From Automation")
            self.intent_var = tk.StringVar(value="General note")
            self.prereq_summary_var = tk.StringVar(value="Run prerequisite checks before bootstrapping.")

            self.text_fields: dict[str, Any] = {}
            self.entry_fields: dict[str, Any] = {}
            self.current_worker_strategy: dict[str, Any] = {}
            self.latest_worker_summary_path: Path | None = None

            self._build_ui()
            self.root.protocol("WM_DELETE_WINDOW", self.close_dashboard)
            if initial_target:
                self.load_project_state(Path(initial_target).expanduser(), announce=False)
            else:
                self.refresh_prerequisites()
                self._set_run_automation_state()
            self._drain_events()

        def _build_ui(self) -> None:
            self._configure_styles()
            notebook = ttk.Notebook(self.root)
            notebook.pack(fill="both", expand=True)

            self.setup_tab = ttk.Frame(notebook, padding=12)
            self.monitor_tab = ttk.Frame(notebook, padding=12)
            self.human_tab = ttk.Frame(notebook, padding=12)
            self.prereq_tab = ttk.Frame(notebook, padding=12)

            notebook.add(self.setup_tab, text="Setup Wizard")
            notebook.add(self.monitor_tab, text="Monitor")
            notebook.add(self.human_tab, text="Messages")
            notebook.add(self.prereq_tab, text="Readiness")

            self._build_setup_tab()
            self._build_monitor_tab()
            self._build_human_tab()
            self._build_prereq_tab()

        def _configure_styles(self) -> None:
            style = ttk.Style()
            style.configure("Title.TLabel", font=("TkDefaultFont", 16, "bold"))
            style.configure("Section.TLabel", font=("TkDefaultFont", 12, "bold"))
            style.configure("Help.TLabel", font=("TkDefaultFont", 10))
            style.configure("Card.TFrame", padding=10)

        def _build_setup_tab(self) -> None:
            self.setup_tab.columnconfigure(0, weight=1)
            self.setup_tab.rowconfigure(2, weight=5, minsize=260)
            self.setup_tab.rowconfigure(5, weight=1, minsize=120)
            header = ttk.Label(
                self.setup_tab,
                text="New Project Setup",
                style="Title.TLabel",
            )
            header.grid(row=0, column=0, sticky="ew")
            ttk.Label(
                self.setup_tab,
                text="Describe the project clearly enough that Codex can make good first-run decisions, then choose where to create it.",
                style="Help.TLabel",
                wraplength=980,
            ).grid(row=1, column=0, sticky="ew", pady=(2, 10))

            setup_pages = ttk.Notebook(self.setup_tab)
            setup_pages.grid(row=2, column=0, sticky="nsew")

            basics = self._new_form_page(setup_pages, "1. Basics")
            product = self._new_form_page(setup_pages, "2. Product")
            rules = self._new_form_page(setup_pages, "3. Rules")
            automation = self._new_form_page(setup_pages, "4. Run Config")
            progression = self._new_form_page(setup_pages, "5. Progression")
            context = self._new_form_page(setup_pages, "6. Context")

            row = 0
            row = self._add_entry(basics, row, "Project Name", self.project_name_var)
            row = self._add_entry(basics, row, "Target Directory", self.target_var, browse=True)
            project_mode_frame = ttk.Frame(basics)
            project_mode_frame.grid(row=row, column=1, sticky="ew", pady=4)
            project_mode_frame.columnconfigure(0, weight=1)
            ttk.Label(basics, text="Project Type", style="Section.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=4)
            ttk.Checkbutton(
                project_mode_frame,
                text="Integrating into an existing project",
                variable=self.existing_project_var,
            ).grid(row=0, column=0, sticky="w")
            project_mode_help = ttk.Label(
                project_mode_frame,
                text="For existing repos, Diffmogger keeps your current AGENTS.md and docs/DEVELOPMENT.md content, adding a managed automation block.",
                style="Help.TLabel",
                wraplength=680,
                justify="left",
            )
            project_mode_help.grid(row=1, column=0, sticky="ew", pady=(3, 0))
            project_mode_frame.bind(
                "<Configure>",
                lambda event, label=project_mode_help: label.configure(wraplength=max(320, event.width - 12)),
            )
            row += 1
            row = self._add_text(
                basics,
                row,
                "Product Goal",
                "Build a local-first workspace that helps solo builders turn project goals into weekly boards, daily focus plans, and review summaries.",
                help_text="Be specific enough for Codex to choose product decisions without asking you. Describe the problem, the core workflow, the value created, the rough product shape, and what a useful first version should accomplish.",
                height=4,
            )
            row = self._add_text(
                basics,
                row,
                "Target User",
                "Solo founders, engineers, and creative builders managing one to three active projects.",
                help_text="Describe who this is for, what they are trying to do, their current pain, their technical comfort, and what would make the product feel useful to them.",
                height=4,
            )

            row = 0
            row = self._add_text(
                product,
                row,
                "Desired First Demo",
                "A user can create a project, add goals, generate a weekly board from seed data, mark tasks done, and view a daily summary.",
                help_text="Spell out the exact local path you want after bootstrap: what the user opens, clicks, enters, sees, exports, or verifies. Include fixture data or example content if useful.",
                height=4,
            )
            row = self._add_text(
                product,
                row,
                "Tech Preferences",
                "- TypeScript\n- Next.js or another simple web app stack\n- Local JSON or SQLite storage for first demo\n- Minimal dependencies",
                help_text="List preferred language, framework, storage, testing tools, styling approach, libraries to prefer or avoid, and whether Codex should follow an existing repo stack.",
                height=4,
            )
            row = self._add_text(
                product,
                row,
                "Verification Commands",
                "- npm test\n- npm run lint\n- npm run build",
                help_text="List expected checks, even if Codex may need to create them during bootstrap. Include tests, lint, typecheck, build, demo, or smoke scripts.",
                height=4,
            )

            row = 0
            row = self._add_text(
                rules,
                row,
                "Hard Constraints",
                "- Local-first demo\n- No paid services required\n- Keep setup under ten minutes",
                help_text="List non-negotiable product, technical, schedule, architecture, data, licensing, platform, or local-first constraints.",
                height=4,
            )
            row = self._add_text(
                rules,
                row,
                "Safety Constraints",
                "- Do not send notifications externally in the first demo\n- Do not publish or deploy without approval\n- Never print, store, or commit secrets",
                help_text="List safety rules that should guide implementation. Include privacy, security, external side effects, compliance, or domain-risk limits.",
                height=4,
            )
            ttk.Label(rules, text="Environment Access", style="Section.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)
            env_frame = ttk.Frame(rules)
            env_frame.grid(row=row, column=1, sticky="ew", pady=6)
            env_combo = ttk.Combobox(
                env_frame,
                textvariable=self.env_access_policy_var,
                values=list(ENV_ACCESS_LABELS.values()),
                state="readonly",
                width=28,
            )
            env_combo.pack(side="left")
            ttk.Label(
                env_frame,
                text="Use direct .env only for disposable or explicitly approved local/live test runs.",
                style="Help.TLabel",
            ).pack(side="left", padx=(8, 0))
            row += 1
            row = self._add_text(
                rules,
                row,
                "External Services",
                "- Optional calendar integration later\n- Optional Discord or email notifications later",
                help_text="List integrations that may matter now or later. Say whether each is required, optional, mocked, dry-run only, or blocked until human approval.",
                height=4,
            )
            row = self._add_text(
                rules,
                row,
                "Automation Must Never Do",
                "- Never print, store, or commit secrets\n- Never spend money, deploy publicly, publish externally, or contact real users without explicit approval\n- Never delete user data or rewrite history without approval",
                help_text="List absolute prohibitions. These become generated guardrails, so write them as direct commands.",
                height=4,
            )

            row = 0
            row = self._add_cadence_control(
                automation,
                row,
                "Automation Cadence Minutes",
                self.cadence_var,
                help_text="Number of minutes between launchd runs. Must be an integer greater than 30.",
            )
            ttk.Label(automation, text="Scheduling Strategy", style="Section.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)
            strategy_frame = ttk.Frame(automation)
            strategy_frame.grid(row=row, column=1, sticky="ew", pady=6)
            strategy_combo = ttk.Combobox(
                strategy_frame,
                textvariable=self.schedule_strategy_var,
                values=list(SCHEDULE_STRATEGY_LABELS.values()),
                state="readonly",
                width=32,
            )
            strategy_combo.pack(side="left")
            strategy_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_prerequisites())
            ttk.Label(
                strategy_frame,
                text="Use continuous conveyor to keep the next runnable lane moving.",
                style="Help.TLabel",
            ).pack(side="left", padx=(8, 0))
            row += 1

            bridge_enabled_frame = ttk.Frame(automation)
            bridge_enabled_frame.grid(row=row, column=1, sticky="w", pady=6)
            ttk.Label(automation, text="Human Bridge Enabled", style="Section.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)
            ttk.Checkbutton(
                bridge_enabled_frame,
                text="Allow automation to ask for manual unlocks and receive replies",
                variable=self.human_bridge_enabled_var,
                command=self.refresh_prerequisites,
            ).pack(side="left")
            row += 1

            bridge_label_frame = ttk.Frame(automation)
            bridge_label_frame.grid(row=row, column=0, sticky="new", padx=(0, 12), pady=6)
            ttk.Label(bridge_label_frame, text="Human Bridge Mode", style="Section.TLabel").pack(anchor="w")
            ttk.Label(
                bridge_label_frame,
                text="Choose file-only for Markdown replies, local notifier for desktop notifications, Discord notifier for channel updates, or disabled for no human queue.",
                style="Help.TLabel",
                wraplength=260,
                justify="left",
            ).pack(anchor="w", pady=(3, 0))
            bridge = ttk.Combobox(
                automation,
                textvariable=self.bridge_mode_var,
                values=["file_only", "local_notifier", "discord_notifier", "disabled"],
                state="readonly",
            )
            bridge.grid(row=row, column=1, sticky="ew", pady=6)
            bridge.bind("<<ComboboxSelected>>", lambda _event: self.refresh_prerequisites())
            row += 1

            text_response_frame = ttk.Frame(automation)
            text_response_frame.grid(row=row, column=1, sticky="w", pady=6)
            ttk.Label(automation, text="Notifier Text Responses", style="Section.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)
            ttk.Checkbutton(
                text_response_frame,
                text="Freeform human requests should receive direct notifier messages when the notifier is available",
                variable=self.human_text_responses_var,
            ).pack(side="left")
            row += 1

            local_notify_frame = ttk.Frame(automation)
            local_notify_frame.grid(row=row, column=1, sticky="w", pady=6)
            ttk.Label(automation, text="Local Notifications", style="Section.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)
            ttk.Checkbutton(
                local_notify_frame,
                text="Enable native desktop notifications for notifier modes",
                variable=self.local_notifications_enabled_var,
                command=self.refresh_prerequisites,
            ).pack(side="left")
            row += 1

            checks = ttk.LabelFrame(automation, text="Worker Agents")
            checks.grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
            checks.columnconfigure(1, weight=1)
            ttk.Checkbutton(checks, text="Worker agents are allowed", variable=self.worker_agents_var).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
            ttk.Checkbutton(checks, text="Codex CLI worker reports are expected on broad runs", variable=self.codex_workers_var).grid(row=0, column=1, sticky="w", padx=8, pady=(8, 4))
            ttk.Checkbutton(checks, text="Allow write-capable workers", variable=self.write_worker_agents_var).grid(row=1, column=0, sticky="w", padx=8, pady=4)
            count_frame = ttk.Frame(checks)
            count_frame.grid(row=1, column=1, sticky="w", padx=8, pady=4)
            ttk.Label(count_frame, text="Max write workers").pack(side="left")
            write_worker_spinbox_cls = getattr(ttk, "Spinbox", tk.Spinbox)
            validate_write_workers = self.root.register(lambda value: value == "" or value.isdigit())
            write_worker_spinbox = write_worker_spinbox_cls(
                count_frame,
                from_=1,
                to=MAX_WRITE_WORKER_COUNT,
                increment=1,
                textvariable=self.max_write_worker_count_var,
                width=4,
                validate="key",
                validatecommand=(validate_write_workers, "%P"),
            )
            write_worker_spinbox.pack(side="left", padx=(8, 0))
            ttk.Checkbutton(checks, text="Overwrite existing scaffold files", variable=self.force_var).grid(row=2, column=0, sticky="w", padx=8, pady=(4, 8))
            ttk.Label(
                checks,
                text="Write-capable workers are optional bounded acceleration. Use as much parallelism as the task can safely absorb, while keeping ownership reviewable and main-agent integration explicit.",
                style="Help.TLabel",
                wraplength=660,
                justify="left",
            ).grid(row=2, column=1, sticky="ew", padx=8, pady=(4, 8))
            row += 1
            ttk.Checkbutton(
                automation,
                text="Enable recurring local automation signals",
                variable=self.automation_signals_enabled_var,
            ).grid(row=row, column=1, sticky="w", pady=6)
            ttk.Label(automation, text="Automation Signals", style="Section.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)
            row += 1
            row = self._add_text(
                automation,
                row,
                "Write Worker Guidance",
                "Use the most parallelism the task can safely absorb. Write workers are optional acceleration for broad work with reviewable ownership boundaries; keep coordination lightweight and let the main agent integrate and verify.",
                help_text="Optional project-specific guidance for write-capable workers. Keep it generic and focused on useful parallelism, ownership boundaries, integration, and verification.",
                height=3,
            )
            ticket_campaign = ttk.LabelFrame(automation, text="Ticket Campaign")
            ticket_campaign.grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
            ticket_campaign.columnconfigure(1, weight=1)
            ttk.Checkbutton(
                ticket_campaign,
                text="Enable bounded ticket campaign mode",
                variable=self.ticket_campaign_enabled_var,
                command=self.refresh_prerequisites,
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
            ttk.Label(ticket_campaign, text="Ticket file").grid(row=1, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(ticket_campaign, textvariable=self.ticket_run_file_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
            ttk.Checkbutton(
                ticket_campaign,
                text="Send native macOS desktop notification when the ticket run halts",
                variable=self.ticket_completion_notify_var,
                command=self.refresh_prerequisites,
            ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=4)
            ttk.Label(
                ticket_campaign,
                text="Tickets are edited in the generated Markdown file. Bootstrap is readiness-only; normal campaign runs use dependency-aware one-ticket selection. Populate the fenced JSON block with ticket IDs, optional depends_on arrays, acceptance criteria, verification commands, evidence, and blockers before leaving automation unattended.",
                style="Help.TLabel",
                wraplength=680,
                justify="left",
            ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
            row += 1
            multi_role = ttk.LabelFrame(automation, text="Multi-Role Automation")
            multi_role.grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
            multi_role.columnconfigure(1, weight=1)
            ttk.Checkbutton(
                multi_role,
                text="Enable planner, builder, hardener, and integrator role schedules",
                variable=self.multi_role_automations_var,
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
            ttk.Label(multi_role, text="Role profile").grid(row=1, column=0, sticky="w", padx=8, pady=4)
            ttk.Combobox(
                multi_role,
                textvariable=self.automation_role_profile_var,
                values=["single_lane", MULTI_ROLE_PROFILE],
                state="readonly",
                width=36,
            ).grid(row=1, column=1, sticky="w", padx=8, pady=4)
            ttk.Checkbutton(
                multi_role,
                text="Integrator may create local checkpoint commits for dirty main changes",
                variable=self.automation_checkpoint_commits_var,
            ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=4)
            ttk.Checkbutton(
                multi_role,
                text="Allow local-only multi-role automation when this repo has git remotes",
                variable=self.multi_role_allow_remotes_var,
            ).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=4)
            cadence_frame = ttk.Frame(multi_role)
            cadence_frame.grid(row=4, column=1, sticky="w", padx=8, pady=4)
            ttk.Label(multi_role, text="Base cadence").grid(row=4, column=0, sticky="w", padx=8, pady=4)
            multi_cadence_spinbox = getattr(ttk, "Spinbox", tk.Spinbox)(
                cadence_frame,
                from_=DEFAULT_MULTI_ROLE_BASE_CADENCE_MINUTES,
                to=MAX_CADENCE_MINUTES,
                increment=30,
                textvariable=self.multi_role_base_cadence_var,
                width=5,
                validate="key",
                validatecommand=(self.root.register(lambda value: value == "" or value.isdigit()), "%P"),
            )
            multi_cadence_spinbox.pack(side="left")
            ttk.Label(cadence_frame, text="minutes; fixed cadence uses staggered role minutes", style="Help.TLabel").pack(side="left", padx=(8, 0))
            ttk.Label(
                multi_role,
                text="Advanced opt-in. Multi-role mode is local-only, requires an initialized git repo, and can run as fixed role jobs or one continuous conveyor. The remote option only permits local automation in repos with remotes; it does not allow pushes, fetches, pulls, or remote configuration.",
                style="Help.TLabel",
                wraplength=680,
                justify="left",
            ).grid(row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
            row += 1

            row = 0
            row = self._add_text(
                progression,
                row,
                "Meaningful Deliverable",
                "A runnable UI or local workflow improvement backed by tests, build, or a demo script.",
                help_text="Define what counts as a real integrated increment. This prevents runs from stopping after tiny doc-only or placeholder changes.",
                height=4,
            )
            row = self._add_text(
                progression,
                row,
                "Long-Run Direction",
                "Add recurring review capsules, local import/export, richer planning views, and optional notification adapters behind feature gates.",
                help_text="Describe what the automation should aim for after the initial scope. Ticket campaigns can leave this empty.",
                height=4,
            )
            row = self._add_text(
                progression,
                row,
                "Assumptions",
                "- The first version does not need authentication\n- Local data is acceptable for the first demo",
                help_text="List assumptions Codex may rely on until contradicted. These are useful for ambiguous product or technical choices.",
                height=4,
            )

            context.columnconfigure(0, weight=1)
            context.rowconfigure(0, weight=1)
            row = 0
            context_frame = ttk.LabelFrame(context, text="Additional Context Files")
            context_frame.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=10)
            context_frame.rowconfigure(0, weight=1)
            context_frame.columnconfigure(0, weight=1)
            self.context_listbox = tk.Listbox(context_frame, height=8)
            self.context_listbox.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=8, pady=8)
            ttk.Button(context_frame, text="Add Files", command=self.add_context_files).grid(row=0, column=1, sticky="ew", padx=8, pady=(8, 4))
            ttk.Button(context_frame, text="Remove Selected", command=self.remove_context_file).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
            ttk.Label(
                context_frame,
                text="Files are copied into docs/context/ and indexed in docs/PROJECT_CONTEXT.md. Do not add secrets.",
                wraplength=360,
            ).grid(row=2, column=1, sticky="ew", padx=8, pady=(4, 8))
            row += 1

            action_row = ttk.Frame(self.setup_tab)
            action_row.grid(row=3, column=0, sticky="ew", pady=(10, 6))
            action_row.columnconfigure(0, weight=1)
            primary_actions = ttk.Frame(action_row)
            primary_actions.grid(row=0, column=0, sticky="ew")
            schedule_actions = ttk.Frame(action_row)
            schedule_actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            self.scaffold_button = ttk.Button(
                primary_actions,
                text="Scaffold & Bootstrap",
                command=self.start_scaffold_bootstrap,
            )
            self.open_project_button = ttk.Button(
                primary_actions,
                text="Open Diffmogger Project",
                command=self.open_project,
            )
            self.cancel_button = ttk.Button(primary_actions, text="Cancel Current Dashboard Run", command=self.cancel_process, state="disabled")
            refresh_button = ttk.Button(primary_actions, text="Refresh Dashboard", command=self.refresh_all)
            self.run_automation_button = ttk.Button(
                schedule_actions,
                text="Start Scheduled Automation",
                command=self.start_scheduled_automation,
                state="disabled",
            )
            self.pause_automation_button = ttk.Button(
                schedule_actions,
                text="Pause Scheduled Automation",
                command=self.pause_scheduled_automation,
                state="disabled",
            )
            self.remove_schedule_button = ttk.Button(
                schedule_actions,
                text="Remove Schedule",
                command=self.remove_scheduled_automation,
                state="disabled",
            )
            self._wrap_button_row(
                primary_actions,
                [self.open_project_button, self.scaffold_button, self.cancel_button, refresh_button],
                min_button_width=250,
            )
            self._wrap_button_row(
                schedule_actions,
                [self.run_automation_button, self.pause_automation_button, self.remove_schedule_button],
                min_button_width=270,
            )

            schedule_status_frame = ttk.Frame(self.setup_tab)
            schedule_status_frame.grid(row=4, column=0, sticky="ew", pady=(2, 8))
            schedule_status_frame.columnconfigure(0, weight=1)
            self.schedule_status_label = ttk.Label(
                schedule_status_frame,
                textvariable=self.schedule_status_var,
                style="Help.TLabel",
                justify="left",
                wraplength=980,
            )
            self.schedule_status_label.grid(row=0, column=0, sticky="ew")
            schedule_status_frame.bind(
                "<Configure>",
                lambda event: self.schedule_status_label.configure(wraplength=max(360, event.width - 8)),
            )

            log_frame = ttk.LabelFrame(self.setup_tab, text="Run Log")
            log_frame.grid(row=5, column=0, sticky="nsew")
            self.log_text = ScrolledText(log_frame, height=4, wrap="word")
            self.log_text.pack(fill="both", expand=True)
            self.log_text.configure(state="disabled")

        def _wrap_button_row(
            self,
            frame: Any,
            buttons: list[Any],
            *,
            min_button_width: int,
        ) -> None:
            state: dict[str, int | None] = {"columns": None}

            def relayout(event: Any | None = None) -> None:
                width = event.width if event is not None else frame.winfo_width()
                columns = max(1, min(len(buttons), max(1, width // min_button_width)))
                if state["columns"] == columns:
                    return
                state["columns"] = columns
                for button in buttons:
                    button.grid_forget()
                for column in range(len(buttons)):
                    frame.columnconfigure(column, weight=0, uniform="")
                for index, button in enumerate(buttons):
                    row, column = divmod(index, columns)
                    frame.columnconfigure(column, weight=1, uniform=str(id(frame)))
                    button.grid(
                        row=row,
                        column=column,
                        sticky="ew",
                        padx=(0 if column == 0 else 8, 0),
                        pady=(0 if row == 0 else 6, 0),
                    )

            frame.bind("<Configure>", relayout)
            frame.after_idle(relayout)

        def _build_monitor_tab(self) -> None:
            self.monitor_tab.columnconfigure(0, weight=1)
            self.monitor_tab.rowconfigure(3, weight=1)

            target_row = ttk.Frame(self.monitor_tab)
            target_row.grid(row=0, column=0, sticky="ew")
            target_row.columnconfigure(1, weight=1)
            ttk.Label(target_row, text="Target Directory").grid(row=0, column=0, padx=(0, 8))
            ttk.Entry(target_row, textvariable=self.target_var).grid(row=0, column=1, sticky="ew")
            ttk.Button(target_row, text="Browse", command=self.browse_target).grid(row=0, column=2, padx=8)
            ttk.Button(target_row, text="Refresh", command=self.refresh_all).grid(row=0, column=3)
            ttk.Button(target_row, text="Launch Observatory", command=self.launch_observatory).grid(row=0, column=4, padx=(8, 0))
            self.review_bundle_button = ttk.Button(
                target_row,
                text="Export Review Bundle",
                command=self.export_review_bundle,
            )
            self.review_bundle_button.grid(row=0, column=5, padx=(8, 0))
            self.integration_safety_button = ttk.Button(
                target_row,
                text="Run Safety Check",
                command=self.run_integration_safety_check,
            )
            self.integration_safety_button.grid(row=0, column=6, padx=(8, 0))

            summary = ttk.LabelFrame(self.monitor_tab, text="Status")
            summary.grid(row=1, column=0, sticky="ew", pady=10)
            summary.columnconfigure(0, weight=1)
            ttk.Label(summary, textvariable=self.status_var, justify="left", wraplength=980).grid(row=0, column=0, sticky="w", padx=8, pady=8)

            worker_controls = ttk.LabelFrame(self.monitor_tab, text="Worker Strategy Controls")
            worker_controls.grid(row=2, column=0, sticky="ew", pady=(0, 10))
            worker_controls.columnconfigure(0, weight=1)
            ttk.Label(
                worker_controls,
                textvariable=self.worker_strategy_var,
                justify="left",
                wraplength=980,
            ).grid(row=0, column=0, columnspan=5, sticky="ew", padx=8, pady=(8, 4))
            self.read_only_worker_button = ttk.Button(
                worker_controls,
                text="Run Read-Only Worker",
                command=self.run_read_only_worker_report,
                state="disabled",
            )
            self.write_worker_button = ttk.Button(
                worker_controls,
                text="Run Write Worker",
                command=self.run_write_worker_lane,
                state="disabled",
            )
            self.integration_only_button = ttk.Button(
                worker_controls,
                text="Run Integrator",
                command=self.run_integration_only_lane,
                state="disabled",
            )
            self.worker_summary_button = ttk.Button(
                worker_controls,
                text="Load Worker Summary",
                command=self.load_worker_summary,
                state="disabled",
            )
            self.read_only_worker_button.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))
            self.write_worker_button.grid(row=1, column=1, sticky="ew", padx=8, pady=(4, 8))
            self.integration_only_button.grid(row=1, column=2, sticky="ew", padx=8, pady=(4, 8))
            ttk.Label(worker_controls, text="Write ownership", style="Help.TLabel").grid(
                row=1,
                column=3,
                sticky="e",
                padx=(8, 4),
                pady=(4, 8),
            )
            ttk.Entry(worker_controls, textvariable=self.write_worker_ownership_var, width=36).grid(
                row=1,
                column=4,
                sticky="ew",
                padx=(4, 8),
                pady=(4, 8),
            )
            worker_controls.columnconfigure(4, weight=1)
            ttk.Label(
                worker_controls,
                textvariable=self.worker_results_var,
                justify="left",
                wraplength=760,
            ).grid(row=2, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 8))
            self.worker_summary_button.grid(row=2, column=4, sticky="e", padx=8, pady=(0, 8))

            viewer_frame = ttk.LabelFrame(self.monitor_tab, text="Markdown Viewer")
            viewer_frame.grid(row=3, column=0, sticky="nsew")
            viewer_frame.rowconfigure(1, weight=1)
            viewer_frame.columnconfigure(0, weight=1)
            doc_row = ttk.Frame(viewer_frame)
            doc_row.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
            ttk.Combobox(
                doc_row,
                textvariable=self.doc_choice_var,
                values=list(DOC_CHOICES.keys()),
                state="readonly",
                width=32,
            ).pack(side="left")
            ttk.Button(doc_row, text="Load", command=self.load_selected_doc).pack(side="left", padx=8)
            self.markdown_text = ScrolledText(viewer_frame, wrap="word")
            self.markdown_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
            self._configure_markdown_tags(self.markdown_text)
            self.markdown_text.configure(state="disabled")

        def _build_human_tab(self) -> None:
            self.human_tab.columnconfigure(0, weight=1)
            self.human_tab.rowconfigure(2, weight=1)

            compose = ttk.LabelFrame(self.human_tab, text="Message The Automation")
            compose.grid(row=0, column=0, sticky="ew")
            compose.columnconfigure(1, weight=1)
            ttk.Label(
                compose,
                text="Write a message for the next automation run. This is the dashboard-friendly way to reply when notifier delivery is disabled or unavailable.",
                wraplength=980,
                style="Help.TLabel",
            ).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))
            ttk.Label(compose, text="Related request").grid(row=1, column=0, sticky="w", padx=8, pady=4)
            self.reply_request_entry = ttk.Entry(compose)
            self.reply_request_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
            ttk.Label(compose, text="Message type").grid(row=1, column=2, sticky="w", padx=8, pady=4)
            ttk.Combobox(
                compose,
                textvariable=self.intent_var,
                values=list(INTENT_CHOICES.keys()),
                state="readonly",
                width=18,
            ).grid(row=1, column=3, sticky="ew", padx=8, pady=4)
            ttk.Label(
                compose,
                text="Optional. Use the request id shown in Requests From Automation, such as HR-001.",
                style="Help.TLabel",
                wraplength=420,
            ).grid(row=2, column=1, sticky="w", padx=8, pady=(0, 4))
            ttk.Label(compose, text="Your message").grid(row=3, column=0, sticky="nw", padx=8, pady=4)
            self.reply_body = ScrolledText(compose, height=5, wrap="word")
            self.reply_body.grid(row=3, column=1, columnspan=3, sticky="ew", padx=8, pady=4)
            self.reply_body.configure(font=("TkDefaultFont", 11))
            ttk.Label(
                compose,
                text="Examples: 'HR-001 DONE, key added locally.' or 'Please focus next run on the demo polish.'",
                style="Help.TLabel",
                wraplength=720,
            ).grid(row=4, column=1, columnspan=3, sticky="w", padx=8, pady=(0, 6))
            ttk.Button(compose, text="Send To Next Run", command=self.add_inbox_reply).grid(row=5, column=1, sticky="w", padx=8, pady=(4, 8))
            ttk.Button(compose, text="Check Texting Service", command=self.check_notifier_health).grid(row=5, column=2, sticky="w", padx=8, pady=(4, 8))

            doc_row = ttk.Frame(self.human_tab)
            doc_row.grid(row=1, column=0, sticky="ew", pady=8)
            ttk.Label(doc_row, text="Conversation view").pack(side="left", padx=(0, 8))
            ttk.Combobox(
                doc_row,
                textvariable=self.human_doc_choice_var,
                values=list(HUMAN_DOC_CHOICES.keys()),
                state="readonly",
                width=34,
            ).pack(side="left")
            ttk.Button(doc_row, text="Load", command=self.load_selected_human_doc).pack(side="left", padx=8)
            ttk.Button(doc_row, text="Refresh", command=self.refresh_human).pack(side="left")

            self.human_text = ScrolledText(self.human_tab, wrap="word")
            self.human_text.grid(row=2, column=0, sticky="nsew")
            self._configure_markdown_tags(self.human_text)
            self.human_text.configure(state="disabled")

        def _build_prereq_tab(self) -> None:
            self.prereq_tab.columnconfigure(0, weight=1)
            self.prereq_tab.rowconfigure(2, weight=1)
            top = ttk.Frame(self.prereq_tab)
            top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            ttk.Label(
                top,
                text="Readiness Checks",
                style="Title.TLabel",
            ).pack(side="left")
            ttk.Button(top, text="Check Prerequisites", command=self.refresh_prerequisites).pack(side="right")
            ttk.Label(
                self.prereq_tab,
                textvariable=self.prereq_summary_var,
                style="Help.TLabel",
                wraplength=980,
            ).grid(row=1, column=0, sticky="ew", pady=(0, 8))

            table_frame = ttk.Frame(self.prereq_tab)
            table_frame.grid(row=2, column=0, sticky="nsew")
            table_frame.rowconfigure(0, weight=1)
            table_frame.columnconfigure(0, weight=1)
            self.prereq_tree = ttk.Treeview(
                table_frame,
                columns=("status", "required", "check", "detail"),
                show="headings",
                selectmode="browse",
            )
            self.prereq_tree.heading("status", text="Status")
            self.prereq_tree.heading("required", text="Type")
            self.prereq_tree.heading("check", text="Check")
            self.prereq_tree.heading("detail", text="Detail")
            self.prereq_tree.column("status", width=90, stretch=False)
            self.prereq_tree.column("required", width=90, stretch=False)
            self.prereq_tree.column("check", width=240, stretch=False)
            self.prereq_tree.column("detail", width=720, stretch=True)
            self.prereq_tree.tag_configure("ok", foreground="#2e7d32")
            self.prereq_tree.tag_configure("missing", foreground="#b00020")
            self.prereq_tree.tag_configure("check", foreground="#9a6700")
            self.prereq_tree.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.prereq_tree.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            self.prereq_tree.configure(yscrollcommand=scrollbar.set)

        def _add_entry(
            self,
            parent: Any,
            row: int,
            label: str,
            var: Any,
            browse: bool = False,
            help_text: str = "",
        ) -> int:
            label_frame = ttk.Frame(parent)
            label_frame.grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=4)
            ttk.Label(label_frame, text=label).pack(anchor="w")
            if help_text:
                ttk.Label(
                    label_frame,
                    text=help_text,
                    style="Help.TLabel",
                    wraplength=260,
                    justify="left",
                ).pack(anchor="w", pady=(3, 0))
            frame = ttk.Frame(parent)
            frame.grid(row=row, column=1, sticky="ew", pady=4)
            frame.columnconfigure(0, weight=1)
            entry = ttk.Entry(frame, textvariable=var)
            entry.grid(row=0, column=0, sticky="ew")
            if browse:
                ttk.Button(frame, text="Browse", command=self.browse_target).grid(row=0, column=1, padx=(8, 0))
            self.entry_fields[label] = entry
            return row + 1

        def _add_cadence_control(
            self,
            parent: Any,
            row: int,
            label: str,
            var: Any,
            help_text: str,
        ) -> int:
            label_frame = ttk.Frame(parent)
            label_frame.grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=4)
            ttk.Label(label_frame, text=label).pack(anchor="w")
            ttk.Label(
                label_frame,
                text=help_text,
                style="Help.TLabel",
                wraplength=260,
                justify="left",
            ).pack(anchor="w", pady=(3, 0))

            frame = ttk.Frame(parent)
            frame.grid(row=row, column=1, sticky="ew", pady=4)
            validate_digits = self.root.register(lambda value: value == "" or value.isdigit())
            spinbox_cls = getattr(ttk, "Spinbox", tk.Spinbox)
            spinbox = spinbox_cls(
                frame,
                from_=MIN_CADENCE_MINUTES,
                to=MAX_CADENCE_MINUTES,
                increment=15,
                textvariable=var,
                width=8,
                validate="key",
                validatecommand=(validate_digits, "%P"),
            )
            spinbox.grid(row=0, column=0, sticky="w")
            ttk.Label(frame, text="minutes between runs", style="Help.TLabel").grid(
                row=0,
                column=1,
                sticky="w",
                padx=(8, 0),
            )
            self.entry_fields[label] = spinbox
            return row + 1

        def _new_form_page(self, notebook: Any, title: str) -> Any:
            outer = ttk.Frame(notebook)
            outer.rowconfigure(0, weight=1)
            outer.columnconfigure(0, weight=1)
            background = ttk.Style().lookup("TFrame", "background") or self.root.cget("background")
            canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0, background=background)
            scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")

            page = ttk.Frame(canvas, padding=10)
            page.columnconfigure(1, weight=1)
            window_id = canvas.create_window((0, 0), window=page, anchor="nw")
            wheel_bound_widgets: set[str] = set()

            def update_scrollbar() -> None:
                needs_scroll = page.winfo_reqheight() > canvas.winfo_height()
                if needs_scroll:
                    scrollbar.grid(row=0, column=1, sticky="ns")
                    canvas.configure(yscrollcommand=scrollbar.set)
                else:
                    scrollbar.grid_remove()
                    canvas.yview_moveto(0)

            def on_page_configure(_event: Any) -> None:
                canvas.configure(scrollregion=canvas.bbox("all"))
                bind_mousewheel_tree(page)
                update_scrollbar()

            def on_canvas_configure(event: Any) -> None:
                canvas.itemconfigure(window_id, width=event.width)
                update_scrollbar()

            def on_mousewheel(event: Any) -> str | None:
                if page.winfo_reqheight() <= canvas.winfo_height():
                    return None
                delta = getattr(event, "delta", 0)
                if delta == 0:
                    return None
                direction = -1 if delta > 0 else 1
                canvas.yview_scroll(direction * 3, "units")
                return "break"

            def on_scroll_up(_event: Any) -> str | None:
                if page.winfo_reqheight() <= canvas.winfo_height():
                    return None
                canvas.yview_scroll(-3, "units")
                return "break"

            def on_scroll_down(_event: Any) -> str | None:
                if page.winfo_reqheight() <= canvas.winfo_height():
                    return None
                canvas.yview_scroll(3, "units")
                return "break"

            def bind_mousewheel_tree(widget: Any) -> None:
                widget_id = str(widget)
                if widget_id not in wheel_bound_widgets:
                    widget.bind("<MouseWheel>", on_mousewheel)
                    widget.bind("<Button-4>", on_scroll_up)
                    widget.bind("<Button-5>", on_scroll_down)
                    wheel_bound_widgets.add(widget_id)
                for child in widget.winfo_children():
                    bind_mousewheel_tree(child)

            page.bind("<Configure>", on_page_configure)
            canvas.bind("<Configure>", on_canvas_configure)
            canvas.bind("<MouseWheel>", on_mousewheel)
            canvas.bind("<Button-4>", on_scroll_up)
            canvas.bind("<Button-5>", on_scroll_down)
            notebook.add(outer, text=title)
            return page

        def _add_section(self, parent: Any, row: int, title: str) -> int:
            ttk.Label(parent, text=title, style="Title.TLabel").grid(
                row=row,
                column=0,
                columnspan=2,
                sticky="ew",
                pady=(16, 6),
            )
            return row + 1

        def _add_text(
            self,
            parent: Any,
            row: int,
            label: str,
                default: str,
                *,
                help_text: str = "",
                height: int = 4,
        ) -> int:
            label_frame = ttk.Frame(parent)
            label_frame.grid(row=row, column=0, sticky="new", padx=(0, 12), pady=6)
            ttk.Label(label_frame, text=label, style="Section.TLabel").pack(anchor="w")
            if help_text:
                ttk.Label(
                    label_frame,
                    text=help_text,
                    style="Help.TLabel",
                    wraplength=260,
                    justify="left",
                ).pack(anchor="w", pady=(3, 0))
            text = tk.Text(parent, height=height, wrap="word", undo=True)
            text.grid(row=row, column=1, sticky="ew", pady=6)
            text.configure(font=("TkDefaultFont", 11))
            text.insert("1.0", default)
            self.text_fields[label] = text
            return row + 1

        def _text_value(self, label: str) -> str:
            return self.text_fields[label].get("1.0", "end").strip()

        def browse_target(self) -> None:
            selected = filedialog.askdirectory(title="Choose target project directory")
            if selected:
                target = Path(selected).expanduser()
                if self._target_has_dashboard_state(target):
                    self.load_project_state(target, announce=True)
                else:
                    self.target_var.set(str(target))
                    self.refresh_prerequisites()
                    self._set_run_automation_state()

        def open_project(self) -> None:
            selected = filedialog.askdirectory(title="Open Diffmogger-managed project")
            if selected:
                self.load_project_state(Path(selected).expanduser(), announce=True)

        def _target_has_dashboard_state(self, target: Path) -> bool:
            target = target.expanduser()
            return (
                dashboard_state_path(target).exists()
                or (target / ".agentic" / "project_intake.json").exists()
                or (target / "docs" / "CODEX_AUTOMATION_TASKS.md").exists()
            )

        def load_project_state(self, target: Path, *, announce: bool) -> None:
            target = target.expanduser().resolve()
            self.target_var.set(str(target))
            intake_path = target / ".agentic" / "project_intake.json"
            state_path = dashboard_state_path(target)
            loaded = False

            if intake_path.exists():
                try:
                    intake = json.loads(intake_path.read_text(encoding="utf-8"))
                    self._apply_intake_to_form(intake)
                    loaded = True
                except (OSError, json.JSONDecodeError) as exc:
                    self._append_log(f"Could not load {intake_path}: {exc}")

            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    self._apply_dashboard_state(state)
                    loaded = True
                except (OSError, json.JSONDecodeError) as exc:
                    self._append_log(f"Could not load {state_path}: {exc}")

            self.context_files.clear()
            self.context_listbox.delete(0, "end")
            self.refresh_all()
            if loaded:
                self.write_dashboard_state(target, last_action="opened")
                if announce:
                    self._append_log(f"Opened Diffmogger project state from {target}.")
            elif announce:
                messagebox.showwarning(
                    "No Diffmogger state found",
                    "The selected directory does not have Diffmogger dashboard state or project intake files yet.",
                )

        def _apply_intake_to_form(self, intake: dict[str, Any]) -> None:
            self.project_name_var.set(str(intake.get("project_name") or "New Project"))
            self.existing_project_var.set(str(intake.get("project_mode") or "fresh_project") == "existing_project")
            self._set_text_field("Product Goal", intake.get("product_goal", ""))
            self._set_text_field("Target User", intake.get("target_user", ""))
            self._set_text_field("Desired First Demo", intake.get("desired_first_demo", ""))
            self._set_text_field("Tech Preferences", intake.get("tech_preferences", []))
            self._set_text_field("Hard Constraints", intake.get("hard_constraints", []))
            self._set_text_field("Safety Constraints", intake.get("safety_constraints", []))
            self._set_text_field("External Services", intake.get("external_services", []))
            self._set_text_field("Verification Commands", intake.get("verification_commands", []))
            self._set_text_field("Automation Must Never Do", intake.get("automation_must_never_do", []))
            env_policy = env_access_policy_from_value(intake.get("env_access_policy"))
            self.env_access_policy_var.set(ENV_ACCESS_LABELS[env_policy])
            self._set_text_field("Meaningful Deliverable", intake.get("meaningful_deliverable", ""))
            self._set_text_field("Long-Run Direction", intake.get("beyond_mvp", ""))
            self._set_text_field("Assumptions", intake.get("assumptions", []))
            self._set_text_field("Write Worker Guidance", intake.get("write_worker_guidance", ""))

            mode = str(intake.get("human_bridge_mode") or "file_only")
            if mode not in {"file_only", "local_notifier", "discord_notifier", "disabled"}:
                mode = "file_only"
            enabled = bool(intake.get("human_bridge_enabled", mode != "disabled")) and mode != "disabled"
            self.human_bridge_enabled_var.set(enabled)
            self.bridge_mode_var.set(mode if enabled else "disabled")
            self.human_text_responses_var.set(bool(intake.get("human_requested_text_responses", True)))
            self.local_notifications_enabled_var.set(bool_from_value(intake.get("local_notifications_enabled"), True))
            self.worker_agents_var.set(bool(intake.get("worker_agents_allowed", True)))
            self.codex_workers_var.set(bool(intake.get("codex_cli_workers_expected_on_broad_runs", True)))
            self.automation_signals_enabled_var.set(bool(intake.get("automation_signals_enabled", False)))
            write_workers_enabled = bool(intake.get("write_worker_agents_allowed", False))
            self.write_worker_agents_var.set(write_workers_enabled)
            self.max_write_worker_count_var.set(
                str(write_worker_count_from_text(intake.get("max_write_worker_count"), enabled=write_workers_enabled))
                if write_workers_enabled
                else str(DEFAULT_WRITE_WORKER_COUNT)
            )
            multi_role_enabled = bool(intake.get("multi_role_automations_allowed", False))
            profile = str(intake.get("automation_role_profile") or ("planner_builder_hardener_integrator" if multi_role_enabled else "single_lane"))
            if profile not in {"single_lane", MULTI_ROLE_PROFILE}:
                profile = MULTI_ROLE_PROFILE if multi_role_enabled else "single_lane"
            self.multi_role_automations_var.set(multi_role_enabled)
            self.automation_role_profile_var.set(profile)
            self.automation_checkpoint_commits_var.set(bool(intake.get("automation_checkpoint_commits", True)))
            self.multi_role_base_cadence_var.set(str(multi_role_cadence_minutes_from_text(intake.get("multi_role_base_cadence_minutes"))))
            self.multi_role_allow_remotes_var.set(bool(intake.get("multi_role_allow_remotes", False)))
            automation_run_mode = str(intake.get("automation_run_mode") or "continuous_improvement").strip()
            self.ticket_campaign_enabled_var.set(automation_run_mode == "ticket_campaign")
            self.ticket_run_file_var.set(str(intake.get("ticket_run_file") or "docs/TICKET_RUN.md"))
            self.ticket_completion_notify_var.set(bool_from_value(intake.get("ticket_completion_notify"), True))
            strategy = schedule_strategy_from_value(intake.get("automation_schedule_strategy"), multi_role_enabled=multi_role_enabled)
            self.schedule_strategy_var.set(SCHEDULE_STRATEGY_LABELS[strategy])
            self.cadence_var.set(str(cadence_minutes_from_text(intake.get("desired_cadence"))))

        def _apply_dashboard_state(self, state: dict[str, Any]) -> None:
            cadence = state.get("cadence_minutes")
            if cadence is not None:
                self.cadence_var.set(str(cadence_minutes_from_text(cadence)))
            if "overwrite_existing_scaffold_files" in state:
                self.force_var.set(bool(state.get("overwrite_existing_scaffold_files")))
            if "write_worker_agents_allowed" in state:
                write_workers_enabled = bool(state.get("write_worker_agents_allowed"))
                self.write_worker_agents_var.set(write_workers_enabled)
                self.max_write_worker_count_var.set(
                    str(write_worker_count_from_text(state.get("max_write_worker_count"), enabled=write_workers_enabled))
                    if write_workers_enabled
                    else str(DEFAULT_WRITE_WORKER_COUNT)
                )
            if "automation_signals_enabled" in state:
                self.automation_signals_enabled_var.set(bool(state.get("automation_signals_enabled")))
            if "local_notifications_enabled" in state:
                self.local_notifications_enabled_var.set(bool_from_value(state.get("local_notifications_enabled"), True))
            if "env_access_policy" in state:
                env_policy = env_access_policy_from_value(state.get("env_access_policy"))
                self.env_access_policy_var.set(ENV_ACCESS_LABELS[env_policy])
            if "multi_role_automations_allowed" in state:
                multi_role_enabled = bool(state.get("multi_role_automations_allowed"))
                self.multi_role_automations_var.set(multi_role_enabled)
                profile = str(state.get("automation_role_profile") or ("planner_builder_hardener_integrator" if multi_role_enabled else "single_lane"))
                self.automation_role_profile_var.set(profile if profile in {"single_lane", MULTI_ROLE_PROFILE} else "single_lane")
                self.automation_checkpoint_commits_var.set(bool(state.get("automation_checkpoint_commits", True)))
                self.multi_role_base_cadence_var.set(str(multi_role_cadence_minutes_from_text(state.get("multi_role_base_cadence_minutes"))))
                self.multi_role_allow_remotes_var.set(bool(state.get("multi_role_allow_remotes", False)))
            if "automation_run_mode" in state:
                self.ticket_campaign_enabled_var.set(str(state.get("automation_run_mode")) == "ticket_campaign")
            if "ticket_run_file" in state:
                self.ticket_run_file_var.set(str(state.get("ticket_run_file") or "docs/TICKET_RUN.md"))
            if "ticket_completion_notify" in state:
                self.ticket_completion_notify_var.set(bool_from_value(state.get("ticket_completion_notify"), True))
            if "automation_schedule_strategy" in state:
                strategy = schedule_strategy_from_value(
                    state.get("automation_schedule_strategy"),
                    multi_role_enabled=bool(self.multi_role_automations_var.get()),
                )
                self.schedule_strategy_var.set(SCHEDULE_STRATEGY_LABELS[strategy])

        def _set_text_field(self, label: str, value: Any) -> None:
            if label not in self.text_fields:
                return
            if isinstance(value, list):
                text = "\n".join(f"- {item}" for item in value)
            else:
                text = str(value or "")
            widget = self.text_fields[label]
            widget.delete("1.0", "end")
            widget.insert("1.0", text)

        def write_dashboard_state(self, target: Path, *, last_action: str) -> None:
            target = target.expanduser().resolve()
            if target == KIT_ROOT:
                self._append_log("Skipped dashboard state write for the Diffmogger kit repo.")
                return
            try:
                cadence_minutes = self.cadence_minutes()
            except ValueError:
                cadence_minutes = DEFAULT_CADENCE_MINUTES
            label = launchd_label(target)
            plist_path = launchd_plist_path(label)
            multi_role_enabled = bool(self.multi_role_automations_var.get())
            schedule_strategy = self.schedule_strategy()
            ready, reason = self._automation_ready(target)
            role_schedule = {
                role: {
                    "launchd_label": launchd_role_label(target, role),
                    "launchd_plist": str(launchd_plist_path(launchd_role_label(target, role))),
                    "launchd_loaded": self._launchd_loaded(launchd_role_label(target, role)),
                    "launchd_disabled": self._launchd_disabled(launchd_role_label(target, role)),
                    "start_minutes": MULTI_ROLE_START_MINUTES[role],
                }
                for role in MULTI_ROLE_ROLES
            }
            state = {
                "schema_version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "project_name": self.project_name_var.get().strip() or "New Project",
                "project_mode": "existing_project" if bool(self.existing_project_var.get()) else "fresh_project",
                "cadence_minutes": cadence_minutes,
                "automation_schedule_strategy": schedule_strategy,
                "human_bridge_enabled": bool(self.human_bridge_enabled_var.get()),
                "human_bridge_mode": self.bridge_mode_var.get(),
                "human_requested_text_responses": bool(self.human_text_responses_var.get()),
                "local_notifications_enabled": bool(self.local_notifications_enabled_var.get()),
                "env_access_policy": env_access_policy_from_value(self.env_access_policy_var.get()),
                "worker_agents_allowed": bool(self.worker_agents_var.get()),
                "codex_cli_workers_expected_on_broad_runs": bool(self.codex_workers_var.get()),
                "automation_signals_enabled": bool(self.automation_signals_enabled_var.get()),
                "write_worker_agents_allowed": bool(self.write_worker_agents_var.get()) and bool(self.worker_agents_var.get()),
                "max_write_worker_count": write_worker_count_from_text(
                    self.max_write_worker_count_var.get(),
                    enabled=bool(self.write_worker_agents_var.get()) and bool(self.worker_agents_var.get()),
                ),
                "multi_role_automations_allowed": multi_role_enabled,
                "automation_role_profile": MULTI_ROLE_PROFILE if multi_role_enabled else "single_lane",
                "automation_checkpoint_commits": bool(self.automation_checkpoint_commits_var.get()),
                "multi_role_base_cadence_minutes": multi_role_cadence_minutes_from_text(self.multi_role_base_cadence_var.get()),
                "multi_role_allow_remotes": bool(self.multi_role_allow_remotes_var.get()),
                "automation_run_mode": "ticket_campaign" if bool(self.ticket_campaign_enabled_var.get()) else "continuous_improvement",
                "ticket_run_file": self.ticket_run_file_var.get().strip() or "docs/TICKET_RUN.md",
                "ticket_completion_notify": bool(self.ticket_completion_notify_var.get()),
                "overwrite_existing_scaffold_files": bool(self.force_var.get()),
                "last_action": last_action,
                "automation_ready": ready,
                "automation_ready_reason": reason,
                "launchd_label": label,
                "launchd_plist": str(plist_path),
                "launchd_loaded": self._launchd_loaded(label),
                "launchd_disabled": self._launchd_disabled(label),
                "conveyor_schedule": {
                    "launchd_label": launchd_conveyor_label(target),
                    "launchd_plist": str(launchd_plist_path(launchd_conveyor_label(target))),
                    "launchd_loaded": self._launchd_loaded(launchd_conveyor_label(target)),
                    "launchd_disabled": self._launchd_disabled(launchd_conveyor_label(target)),
                },
                "multi_role_schedule": role_schedule,
            }
            path = dashboard_state_path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        def close_dashboard(self) -> None:
            target_text = self.target_var.get().strip()
            if target_text:
                target = Path(target_text).expanduser()
                if self._target_has_dashboard_state(target):
                    try:
                        self.write_dashboard_state(target, last_action="closed")
                    except Exception:
                        pass
            self._terminate_observatories()
            self.root.destroy()

        def _terminate_observatories(self) -> None:
            for process in list(self.observatory_processes):
                if process.poll() is not None:
                    continue
                try:
                    process.terminate()
                    process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                except OSError:
                    pass
            self.observatory_processes = [
                process for process in self.observatory_processes if process.poll() is None
            ]

        def add_context_files(self) -> None:
            paths = filedialog.askopenfilenames(
                title="Choose additional project context files",
                filetypes=[
                    ("Context files", "*.pdf *.md *.txt *.csv *.json *.docx *.pptx *.xlsx"),
                    ("All files", "*.*"),
                ],
            )
            existing = {path.expanduser().resolve() for path in self.context_files}
            for raw in paths:
                path = Path(raw).expanduser().resolve()
                if path not in existing:
                    self.context_files.append(path)
                    self.context_listbox.insert("end", str(path))
                    existing.add(path)

        def remove_context_file(self) -> None:
            selected = list(self.context_listbox.curselection())
            for index in reversed(selected):
                self.context_listbox.delete(index)
                del self.context_files[index]

        def cadence_minutes(self) -> int:
            return parse_cadence_seconds(self.cadence_var.get()) // 60

        def schedule_strategy(self) -> str:
            return schedule_strategy_from_value(
                self.schedule_strategy_var.get(),
                multi_role_enabled=bool(self.multi_role_automations_var.get()),
            )

        def collect_intake(self) -> dict[str, Any]:
            mode = self.bridge_mode_var.get()
            bridge_enabled = bool(self.human_bridge_enabled_var.get()) and mode != "disabled"
            context_names = [f"docs/context/{safe_context_filename(path.name)}" for path in self.context_files]
            cadence_minutes = self.cadence_minutes()
            write_workers_enabled = bool(self.write_worker_agents_var.get()) and bool(self.worker_agents_var.get())
            max_write_workers = write_worker_count_from_text(
                self.max_write_worker_count_var.get(),
                enabled=write_workers_enabled,
            )
            multi_role_enabled = bool(self.multi_role_automations_var.get())
            multi_role_cadence = multi_role_cadence_minutes_from_text(self.multi_role_base_cadence_var.get())
            schedule_strategy = self.schedule_strategy()
            ticket_file = self.ticket_run_file_var.get().strip() or "docs/TICKET_RUN.md"
            return {
                "project_name": self.project_name_var.get().strip() or "New Project",
                "project_mode": "existing_project" if bool(self.existing_project_var.get()) else "fresh_project",
                "product_goal": self._text_value("Product Goal"),
                "target_user": self._text_value("Target User"),
                "desired_first_demo": self._text_value("Desired First Demo"),
                "tech_preferences": split_lines(self._text_value("Tech Preferences")),
                "hard_constraints": split_lines(self._text_value("Hard Constraints")),
                "safety_constraints": split_lines(self._text_value("Safety Constraints")),
                "automation_must_never_do": split_lines(self._text_value("Automation Must Never Do")),
                "external_services": split_lines(self._text_value("External Services")),
                "env_access_policy": env_access_policy_from_value(self.env_access_policy_var.get()),
                "verification_commands": split_lines(self._text_value("Verification Commands")),
                "desired_cadence": f"every {cadence_minutes} minutes",
                "human_bridge_enabled": bridge_enabled,
                "human_bridge_mode": mode if bridge_enabled else "disabled",
                "human_requested_text_responses": bool(self.human_text_responses_var.get()),
                "local_notifications_enabled": bool(self.local_notifications_enabled_var.get()),
                "worker_agents_allowed": bool(self.worker_agents_var.get()),
                "codex_cli_workers_expected_on_broad_runs": bool(self.codex_workers_var.get()),
                "automation_signals_enabled": bool(self.automation_signals_enabled_var.get()),
                "write_worker_agents_allowed": write_workers_enabled,
                "max_write_worker_count": max_write_workers,
                "write_worker_guidance": self._text_value("Write Worker Guidance"),
                "multi_role_automations_allowed": multi_role_enabled,
                "automation_role_profile": MULTI_ROLE_PROFILE if multi_role_enabled else "single_lane",
                "automation_checkpoint_commits": bool(self.automation_checkpoint_commits_var.get()),
                "multi_role_base_cadence_minutes": multi_role_cadence,
                "automation_schedule_strategy": schedule_strategy,
                "multi_role_allow_remotes": bool(self.multi_role_allow_remotes_var.get()),
                "automation_run_mode": "ticket_campaign" if bool(self.ticket_campaign_enabled_var.get()) else "continuous_improvement",
                "ticket_run_file": ticket_file,
                "ticket_completion_notify": bool(self.ticket_completion_notify_var.get()),
                "meaningful_deliverable": self._text_value("Meaningful Deliverable"),
                "beyond_mvp": self._text_value("Long-Run Direction"),
                "assumptions": split_lines(self._text_value("Assumptions")),
                "additional_context_files": context_names,
            }

        def refresh_prerequisites(self) -> None:
            target_text = self.target_var.get().strip() or str(Path.cwd() / "my-project")
            target = Path(target_text).expanduser()
            mode = self.bridge_mode_var.get() if self.human_bridge_enabled_var.get() else "disabled"
            items = check_prerequisites(target, mode)
            if (
                bool(self.local_notifications_enabled_var.get())
                and mode in {"local_notifier", "discord_notifier"}
            ):
                osascript_path = shutil.which("osascript")
                items.append(
                    PrerequisiteItem(
                        "macOS desktop notifications",
                        bool(osascript_path),
                        False,
                        osascript_path or "osascript unavailable; notifier delivery will record LOCAL_NOTIFICATION_FAILED in docs/HUMAN_OUTBOX.md.",
                    )
                )
            self._show_prerequisites(items)

        def _show_prerequisites(self, items: list[PrerequisiteItem]) -> None:
            if not hasattr(self, "prereq_tree"):
                return
            for item_id in self.prereq_tree.get_children():
                self.prereq_tree.delete(item_id)

            required = [item for item in items if item.required]
            optional = [item for item in items if not item.required]
            required_missing = [item for item in required if not item.ok]
            advisory_attention = [item for item in optional if not item.ok]
            if required_missing:
                self.prereq_summary_var.set(
                    f"{len(required_missing)} required check(s) need attention before bootstrapping."
                )
            elif advisory_attention:
                self.prereq_summary_var.set(
                    "Required checks passed. Review advisory items before scheduling recurring runs."
                )
            else:
                self.prereq_summary_var.set(
                    "All required checks passed. You can start the scaffold/bootstrap pipeline."
                )

            for item in items:
                if item.ok:
                    status = "OK"
                    tag = "ok"
                elif item.required:
                    status = "Missing"
                    tag = "missing"
                else:
                    status = "Review"
                    tag = "check"
                kind = "Required" if item.required else "Advisory"
                self.prereq_tree.insert(
                    "",
                    "end",
                    values=(status, kind, item.name, item.detail),
                    tags=(tag,),
                )

        def start_scaffold_bootstrap(self) -> None:
            if self.running:
                messagebox.showinfo("Bootstrap running", "A scaffold/bootstrap pipeline is already running.")
                return
            target_text = self.target_var.get().strip()
            if not target_text:
                messagebox.showerror("Missing target", "Choose where to create the target project directory.")
                return
            target = Path(target_text).expanduser().resolve()
            try:
                intake = self.collect_intake()
            except ValueError as exc:
                messagebox.showerror("Invalid automation cadence", str(exc))
                return
            items = check_prerequisites(target, intake["human_bridge_mode"])
            self._show_prerequisites(items)
            failures = required_failures(items)
            if failures:
                messagebox.showerror(
                    "Prerequisites missing",
                    "Fix required prerequisites before starting automation:\n\n"
                    + "\n".join(f"- {item.name}: {item.detail}" for item in failures),
                )
                return
            advisory = [item for item in items if not item.required and not item.ok]
            if advisory:
                proceed = messagebox.askyesno(
                    "Advisory checks",
                    "Some advisory checks need attention. Continue anyway?\n\n"
                    + "\n".join(f"- {item.name}: {item.detail}" for item in advisory),
                )
                if not proceed:
                    return

            target.mkdir(parents=True, exist_ok=True)
            self.write_dashboard_state(target, last_action="scaffold_bootstrap_started")
            self.running = True
            self.open_project_button.configure(state="disabled")
            self.scaffold_button.configure(state="disabled")
            self.run_automation_button.configure(state="disabled")
            self.pause_automation_button.configure(state="disabled")
            self.remove_schedule_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self._set_worker_action_state()
            self._append_log("Starting combined scaffold/bootstrap pipeline.")
            thread = threading.Thread(
                target=self._scaffold_bootstrap_worker,
                args=(target, intake, bool(self.force_var.get()), list(self.context_files)),
                daemon=True,
            )
            thread.start()

        def _scaffold_bootstrap_worker(
            self,
            target: Path,
            intake: dict[str, Any],
            force: bool,
            context_paths: list[Path],
        ) -> None:
            try:
                self._thread_log(f"Target: {target}")
                target.mkdir(parents=True, exist_ok=True)
                context_index_existed = (target / "docs" / "PROJECT_CONTEXT.md").exists()
                records = copy_context_files(target, context_paths, self._thread_log)
                intake["additional_context_files"] = [record.rel_path for record in records]

                agentic_dir = target / ".agentic"
                agentic_dir.mkdir(parents=True, exist_ok=True)
                intake_path = agentic_dir / "project_intake.json"
                intake_path.write_text(json.dumps(intake, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                self._thread_log("Wrote .agentic/project_intake.json")

                scaffold_module = load_scaffold_module()
                values = scaffold_module.placeholders(intake)
                written = scaffold_module.scaffold(target, values, force)
                self._thread_log(f"Scaffolded {len(written)} files.")
                for path in written[:20]:
                    self._thread_log(f"  wrote {path.relative_to(target)}")
                if len(written) > 20:
                    self._thread_log(f"  ... {len(written) - 20} more files")

                context_path = target / "docs" / "PROJECT_CONTEXT.md"
                if records and (force or not context_index_existed):
                    context_text = render_project_context(intake["project_name"], records)
                    context_path.write_text(context_text, encoding="utf-8")
                    self._thread_log("Updated docs/PROJECT_CONTEXT.md with imported context files.")
                elif records:
                    existing_context = context_path.read_text(encoding="utf-8", errors="replace") if context_path.exists() else ""
                    context_path.write_text(
                        upsert_context_imports(existing_context, intake["project_name"], records),
                        encoding="utf-8",
                    )
                    self._thread_log("Updated managed context-file index in docs/PROJECT_CONTEXT.md.")

                check_cmd = [
                    sys.executable,
                    str(CHECK_REQUIRED_SCRIPT),
                    "--human-bridge-mode",
                    intake["human_bridge_mode"],
                    str(target),
                ]
                if intake.get("write_worker_agents_allowed"):
                    check_cmd.insert(-1, "--write-workers-enabled")
                if intake.get("multi_role_automations_allowed"):
                    check_cmd.insert(-1, "--multi-role-enabled")
                if intake.get("automation_run_mode") == "ticket_campaign":
                    check_cmd.insert(-1, "--ticket-campaign-enabled")
                check_code = self._run_command(check_cmd, cwd=KIT_ROOT)
                if check_code != 0:
                    raise RuntimeError("Required-file check failed; bootstrap was not started.")

                prompt_path = target / "docs" / "INITIAL_BOOTSTRAP_PROMPT.md"
                prompt = prompt_path.read_text(encoding="utf-8")
                self._thread_log("Starting Codex bootstrap run.")
                code = self._run_command(["codex", "exec", "--full-auto", "--skip-git-repo-check", prompt], cwd=target)
                if code != 0:
                    raise RuntimeError(f"Codex bootstrap exited with code {code}.")
                self._thread_log("Codex bootstrap completed.")
                self.events.put(("bootstrap_done", str(target)))
                self.events.put(("refresh", None))
            except Exception as exc:
                self._thread_log(f"ERROR: {exc}")
            finally:
                self.current_process = None
                self.events.put(("done", None))

        def _run_command(self, cmd: list[str], cwd: Path) -> int:
            self._thread_log("$ " + self._format_command_for_log(cmd))
            process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
            self.current_process = process
            assert process.stdout is not None
            while process.poll() is None:
                self._read_available_process_output(process, timeout=0.12)
            code = process.wait()
            self._terminate_process_group(
                process,
                reason="command completed; cleaning up lingering child processes",
                from_thread=True,
                force=False,
            )
            self._read_available_process_output(process, timeout=0)
            return code

        def _format_command_for_log(self, cmd: list[str]) -> str:
            rendered: list[str] = []
            for part in cmd:
                if len(part) > 240:
                    rendered.append(f"<{len(part)} chars omitted>")
                else:
                    rendered.append(part)
            return " ".join(rendered)

        def _read_available_process_output(
            self,
            process: subprocess.Popen[str],
            *,
            timeout: float,
        ) -> None:
            if process.stdout is None:
                return
            try:
                ready, _, _ = select.select([process.stdout], [], [], timeout)
            except (OSError, ValueError):
                return
            while ready:
                line = process.stdout.readline()
                if not line:
                    return
                self._thread_log(line.rstrip())
                try:
                    ready, _, _ = select.select([process.stdout], [], [], 0)
                except (OSError, ValueError):
                    return

        def _terminate_process_group(
            self,
            process: subprocess.Popen[str],
            *,
            reason: str,
            from_thread: bool,
            force: bool,
        ) -> None:
            def emit(message: str) -> None:
                if from_thread:
                    self._thread_log(message)
                else:
                    self._append_log(message)

            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            except PermissionError as exc:
                emit(f"Could not terminate process group after {reason}: {exc}")
                return
            except OSError:
                return

            if process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    force = True

            if force:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    emit(f"Force-killed dashboard-launched process group after {reason}.")
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    emit(f"Could not force-kill process group after {reason}: {exc}")
                return

            time.sleep(0.15)
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            except OSError:
                return
            try:
                os.killpg(process.pid, signal.SIGKILL)
                emit(f"Cleaned up lingering child processes after {reason}.")
            except ProcessLookupError:
                pass
            except OSError as exc:
                emit(f"Could not clean up lingering child processes after {reason}: {exc}")

        def cancel_process(self) -> None:
            if self.current_process and self.current_process.poll() is None:
                self._terminate_process_group(
                    self.current_process,
                    reason="dashboard cancellation",
                    from_thread=False,
                    force=True,
                )
                self._append_log("Sent terminate signal to dashboard-launched process group.")

        def refresh_all(self) -> None:
            self.refresh_prerequisites()
            self.refresh_monitor()
            self.load_selected_doc()
            self.refresh_human()
            self._set_run_automation_state()

        def refresh_monitor(self) -> None:
            target = Path(self.target_var.get().strip() or ".").expanduser()
            task_path = target / "docs" / "CODEX_AUTOMATION_TASKS.md"
            if not task_path.exists():
                self.status_var.set("No generated automation task file found for the selected target.")
                self.current_worker_strategy = {}
                self.latest_worker_summary_path = None
                self.worker_strategy_var.set("Next worker strategy: unavailable because no automation task file was found.")
                self.worker_results_var.set("Latest worker result: none yet.")
                self._set_worker_action_state()
                self._set_run_automation_state()
                return
            text = task_path.read_text(encoding="utf-8", errors="replace")
            status = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", text, re.MULTILINE)
            updated = re.search(r"^Last updated:\s*(.+)", text, re.MULTILINE)
            horizon = re.search(r"^- Current horizon:\s*(.+)", text, re.MULTILINE)
            horizon_decision = re.search(r"^- Advancement decision:\s*(.+)", text, re.MULTILINE)
            requests_path = target / "docs" / "HUMAN_REQUESTS.md"
            inbox_path = target / "docs" / "HUMAN_INBOX.md"
            outbox_path = target / "docs" / "HUMAN_OUTBOX.md"
            request_count = self._count_marker(requests_path, r"^##\s+HR-")
            inbox_count = self._count_marker(inbox_path, r"status:\s*unhandled")
            outbox_count = self._count_marker(outbox_path, r"^##\s+OUTBOX-")
            worker_reports = sorted((target / "target" / "agent_runs").glob("*/worker_*.md")) if (target / "target" / "agent_runs").exists() else []
            try:
                self.current_worker_strategy = dashboard_worker_strategy(target)
                worker_summary = worker_strategy_summary(self.current_worker_strategy)
            except Exception as exc:
                self.current_worker_strategy = {}
                worker_summary = f"Next worker strategy: unavailable ({compact_dashboard_text(exc, limit=180)})."
            self.worker_strategy_var.set(worker_summary)
            worker_result = latest_worker_result(target)
            self.worker_results_var.set(str(worker_result["label"]))
            summary_path = worker_result.get("summary_path")
            self.latest_worker_summary_path = Path(str(summary_path)) if summary_path else None
            parts = [
                f"Status: {status.group(1) if status else 'unknown'}",
                f"Horizon: {horizon.group(1) if horizon else 'unknown'}",
                f"Horizon decision: {horizon_decision.group(1) if horizon_decision else 'unknown'}",
                f"Last updated: {updated.group(1) if updated else 'unknown'}",
                f"Pending request headings: {request_count}",
                f"Unhandled inbox entries: {inbox_count}",
                f"Outbound records: {outbox_count}",
                f"Worker reports: {worker_result.get('report_count') or len(worker_reports)} latest / {len(worker_reports)} total",
                f"Worker strategy: {compact_dashboard_text(self.current_worker_strategy.get('strategy') or 'unknown', limit=80)}",
            ]
            self.status_var.set("  |  ".join(parts))
            self._set_worker_action_state()
            self._set_run_automation_state()

        def _count_marker(self, path: Path, pattern: str) -> int:
            if not path.exists():
                return 0
            text = path.read_text(encoding="utf-8", errors="replace")
            return len(re.findall(pattern, text, re.MULTILINE))

        def _set_worker_action_state(self) -> None:
            if not hasattr(self, "read_only_worker_button"):
                return
            buttons = [
                self.read_only_worker_button,
                self.write_worker_button,
                self.integration_only_button,
                self.worker_summary_button,
            ]
            if self.running:
                for button in buttons:
                    button.configure(state="disabled")
                return
            target_text = self.target_var.get().strip()
            if not target_text:
                for button in buttons:
                    button.configure(state="disabled")
                return
            target = Path(target_text).expanduser().resolve()
            strategy = compact_dashboard_text(
                self.current_worker_strategy.get("strategy") or "NO_WORKERS",
                limit=80,
            )
            worker_helper_exists = (target / "scripts" / "spawn_worker_agent.sh").exists()
            integrator_helper_exists = (
                (target / "scripts" / "run_role_automation.sh").exists()
                and (target / ".agentic" / "roles" / "integrator.md").exists()
            )
            self.read_only_worker_button.configure(
                state="normal" if worker_helper_exists and strategy in WORKER_REPORT_STRATEGIES else "disabled"
            )
            self.write_worker_button.configure(
                state="normal" if worker_helper_exists and strategy == "WRITE_WORKERS" else "disabled"
            )
            self.integration_only_button.configure(
                state="normal" if integrator_helper_exists and strategy == "INTEGRATION_ONLY" else "disabled"
            )
            self.worker_summary_button.configure(
                state="normal"
                if self.latest_worker_summary_path and self.latest_worker_summary_path.exists()
                else "disabled"
            )

        def load_worker_summary(self) -> None:
            summary_path = self.latest_worker_summary_path
            if not summary_path or not summary_path.exists():
                messagebox.showinfo(
                    "Worker summary unavailable",
                    "No worker summary has been generated for the selected target yet.",
                )
                return
            self._load_markdown_file(self.markdown_text, summary_path)
            self._append_log(f"Loaded worker summary: {summary_path}")

        def run_read_only_worker_report(self) -> None:
            if self.running:
                messagebox.showinfo("Process running", "A dashboard-launched process is already running.")
                return
            target = Path(self.target_var.get().strip() or ".").expanduser().resolve()
            strategy = self.current_worker_strategy or dashboard_worker_strategy(target)
            name = compact_dashboard_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
            if name not in WORKER_REPORT_STRATEGIES:
                messagebox.showinfo(
                    "Worker report not recommended",
                    f"The current next-run worker strategy is {name}. Refresh the target or use the observatory before spawning a worker report.",
                )
                return
            run_id = dashboard_run_id("dashboard-worker-report")
            self._start_monitor_command(
                read_only_worker_command(target, strategy, run_id=run_id),
                cwd=target,
                start_message="Starting a bounded read-only worker report from the dashboard recommendation.",
                success_message="Read-only worker report completed.",
                failure_message="Read-only worker report failed",
                worker_summary_run_id=run_id,
            )

        def run_write_worker_lane(self) -> None:
            if self.running:
                messagebox.showinfo("Process running", "A dashboard-launched process is already running.")
                return
            target = Path(self.target_var.get().strip() or ".").expanduser().resolve()
            strategy = self.current_worker_strategy or dashboard_worker_strategy(target)
            name = compact_dashboard_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
            if name != "WRITE_WORKERS":
                messagebox.showinfo(
                    "Write worker not recommended",
                    f"The current next-run worker strategy is {name}. Write workers are enabled only when the observatory recommends WRITE_WORKERS.",
                )
                return
            ownership = self.write_worker_ownership_var.get().strip()
            if not ownership:
                messagebox.showerror(
                    "Missing ownership scope",
                    "Enter a disjoint file or module ownership scope before launching a write worker.",
                )
                return
            run_id = dashboard_run_id("dashboard-write-worker")
            self._start_monitor_command(
                write_worker_command(target, strategy, ownership, run_id=run_id),
                cwd=target,
                start_message="Starting one bounded write worker from the dashboard recommendation.",
                success_message="Write worker completed. Review its changed files and report before integrating anything.",
                failure_message="Write worker failed",
                worker_summary_run_id=run_id,
            )

        def run_integration_only_lane(self) -> None:
            if self.running:
                messagebox.showinfo("Process running", "A dashboard-launched process is already running.")
                return
            target = Path(self.target_var.get().strip() or ".").expanduser().resolve()
            strategy = self.current_worker_strategy or dashboard_worker_strategy(target)
            name = compact_dashboard_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
            if name != "INTEGRATION_ONLY":
                messagebox.showinfo(
                    "Integrator not recommended",
                    f"The current next-run worker strategy is {name}. Use this control when the observatory recommends INTEGRATION_ONLY.",
                )
                return
            self._start_monitor_command(
                integration_only_command(target),
                cwd=target,
                start_message="Starting one local integrator lane from the dashboard recommendation.",
                success_message="Integrator lane completed.",
                failure_message="Integrator lane failed",
            )

        def _start_monitor_command(
            self,
            command: list[str],
            *,
            cwd: Path,
            start_message: str,
            success_message: str,
            failure_message: str,
            worker_summary_run_id: str | None = None,
        ) -> None:
            self.running = True
            self._set_run_automation_state()
            self._set_worker_action_state()
            self.cancel_button.configure(state="normal")
            self._append_log(start_message)
            thread = threading.Thread(
                target=self._monitor_command_worker,
                args=(command, cwd, success_message, failure_message, worker_summary_run_id),
                daemon=True,
            )
            thread.start()

        def _monitor_command_worker(
            self,
            command: list[str],
            cwd: Path,
            success_message: str,
            failure_message: str,
            worker_summary_run_id: str | None,
        ) -> None:
            try:
                code = self._run_command(command, cwd=cwd)
                summary_path = (
                    self._summarize_worker_run(cwd, worker_summary_run_id)
                    if worker_summary_run_id
                    else None
                )
                if code == 0:
                    self._thread_log(success_message)
                    if summary_path:
                        self._thread_log(f"Worker summary ready: {summary_path}")
                else:
                    self._thread_log(f"{failure_message} with code {code}.")
                    if summary_path:
                        self._thread_log(f"Worker failure summary ready: {summary_path}")
            except Exception as exc:
                self._thread_log(f"ERROR: {exc}")
            finally:
                self.current_process = None
                self.events.put(("refresh", None))
                self.events.put(("done", None))

        def _summarize_worker_run(self, target: Path, run_id: str) -> Path | None:
            script = target / "scripts" / "summarize_worker_outputs.py"
            run_dir = target / "target" / "agent_runs" / run_id
            if not script.exists():
                self._thread_log(f"Worker summary helper is missing: {script}")
                return None
            if not run_dir.exists():
                self._thread_log(f"Worker run directory was not created: {run_dir}")
                return None
            code = self._run_command(worker_summary_command(target, run_id), cwd=target)
            if code != 0:
                self._thread_log(f"Worker summary generation failed with code {code}.")
                return None
            summary_path = run_dir / "summary.md"
            if not summary_path.exists():
                self._thread_log(f"Worker summary command completed but did not write {summary_path}.")
                return None
            return summary_path

        def load_selected_doc(self) -> None:
            target = Path(self.target_var.get().strip() or ".").expanduser()
            rel = DOC_CHOICES.get(self.doc_choice_var.get(), "docs/CODEX_AUTOMATION_TASKS.md")
            self._load_markdown_file(self.markdown_text, target / rel)

        def launch_observatory(self) -> None:
            target_text = self.target_var.get().strip()
            if not target_text:
                messagebox.showerror("Missing target", "Choose a target project directory first.")
                return
            target = Path(target_text).expanduser().resolve()
            if not target.exists():
                messagebox.showerror("Missing target", f"Target directory does not exist:\n\n{target}")
                return
            if not OBSERVATORY_SCRIPT.exists():
                messagebox.showerror("Observatory unavailable", f"Missing observatory helper:\n\n{OBSERVATORY_SCRIPT}")
                return
            self.observatory_processes = [
                process for process in self.observatory_processes if process.poll() is None
            ]
            try:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(OBSERVATORY_SCRIPT),
                        "--target",
                        str(target),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "0",
                        "--open",
                    ],
                    cwd=str(KIT_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                )
            except OSError as exc:
                messagebox.showerror("Could not launch observatory", str(exc))
                return
            self.observatory_processes.append(process)
            self._append_log("Launched local observatory page for the selected target.")

        def export_review_bundle(self) -> None:
            if self.running:
                messagebox.showinfo("Process running", "A dashboard-launched process is already running.")
                return
            if not OBSERVATORY_SCRIPT.exists():
                messagebox.showerror("Review export unavailable", f"Missing observatory helper:\n\n{OBSERVATORY_SCRIPT}")
                return
            target_text = self.target_var.get().strip()
            selected_target = Path(target_text).expanduser() if target_text else KIT_ROOT
            if not selected_target.exists():
                messagebox.showerror("Missing target", f"Target directory does not exist:\n\n{selected_target}")
                return
            review_dir = DEFAULT_REVIEW_BUNDLE_DIR
            self.running = True
            self.open_project_button.configure(state="disabled")
            self.scaffold_button.configure(state="disabled")
            self.run_automation_button.configure(state="disabled")
            self.pause_automation_button.configure(state="disabled")
            self.remove_schedule_button.configure(state="disabled")
            self.review_bundle_button.configure(state="disabled")
            self.integration_safety_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self._set_worker_action_state()
            self._append_log(f"Exporting first-review bundle for {selected_target.resolve()} to {review_dir}.")
            thread = threading.Thread(
                target=self._review_bundle_worker,
                args=(selected_target.resolve(), review_dir),
                daemon=True,
            )
            thread.start()

        def _review_bundle_worker(self, target: Path, review_dir: Path) -> None:
            try:
                code = self._run_command(review_bundle_command(target, review_dir), cwd=KIT_ROOT)
                if code == 0:
                    self._thread_log(f"Review bundle exported to {review_dir}.")
                    self._thread_log(f"Open {review_dir / 'Diffmogger-observatory.html'} and inspect {review_dir / 'Diffmogger-self-review.md'}.")
                else:
                    self._thread_log(f"Review bundle export failed with code {code}.")
            except Exception as exc:
                self._thread_log(f"ERROR: {exc}")
            finally:
                self.current_process = None
                self.events.put(("refresh", None))
                self.events.put(("done", None))

        def run_integration_safety_check(self) -> None:
            if self.running:
                messagebox.showinfo("Process running", "A dashboard-launched process is already running.")
                return
            if not INTEGRATION_SAFETY_SCRIPT.exists():
                messagebox.showerror(
                    "Safety check unavailable",
                    f"Missing integration-safety helper:\n\n{INTEGRATION_SAFETY_SCRIPT}",
                )
                return
            target_text = self.target_var.get().strip()
            selected_target = Path(target_text).expanduser() if target_text else KIT_ROOT
            selected_target = selected_target.resolve()
            check_target = resolve_integration_safety_target(selected_target)
            if check_target == KIT_ROOT and not has_integration_safety_tree(selected_target):
                self._append_log(
                    "Selected target does not include starter-kit integration files; checking the Diffmogger kit source instead."
                )
            self.running = True
            self.open_project_button.configure(state="disabled")
            self.scaffold_button.configure(state="disabled")
            self.run_automation_button.configure(state="disabled")
            self.pause_automation_button.configure(state="disabled")
            self.remove_schedule_button.configure(state="disabled")
            self.review_bundle_button.configure(state="disabled")
            self.integration_safety_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self._set_worker_action_state()
            self._append_log(f"Starting integration safety check for {check_target}.")
            thread = threading.Thread(
                target=self._integration_safety_worker,
                args=(selected_target, check_target),
                daemon=True,
            )
            thread.start()

        def _integration_safety_worker(self, selected_target: Path, target: Path) -> None:
            try:
                command = integration_safety_command(target)
                code = self._run_command(command, cwd=KIT_ROOT)
                if selected_target.exists():
                    try:
                        record_path = write_integration_safety_record(selected_target, target, command, code)
                        self._thread_log(f"Recorded integration safety result at {record_path}.")
                    except OSError as exc:
                        self._thread_log(f"Could not record integration safety result: {exc}")
                else:
                    self._thread_log(
                        f"Selected target no longer exists; skipped durable safety record for {selected_target}."
                    )
                if code == 0:
                    self._thread_log("Integration safety check passed.")
                else:
                    self._thread_log(f"Integration safety check failed with code {code}.")
            except Exception as exc:
                self._thread_log(f"ERROR: {exc}")
            finally:
                self.current_process = None
                self.events.put(("refresh", None))
                self.events.put(("done", None))

        def load_selected_human_doc(self) -> None:
            target = Path(self.target_var.get().strip() or ".").expanduser()
            rel = HUMAN_DOC_CHOICES.get(self.human_doc_choice_var.get(), "docs/HUMAN_REQUESTS.md")
            self._load_markdown_file(self.human_text, target / rel)

        def refresh_human(self) -> None:
            self.load_selected_human_doc()

        def _automation_ready(self, target: Path) -> tuple[bool, str]:
            target = target.expanduser().resolve()
            schedule_strategy = self._target_schedule_strategy(target)
            required = [
                target / ".agentic" / "project_intake.json",
                target / ".agentic" / "automation_prompt.md",
                target / "docs" / "INITIAL_BOOTSTRAP_PROMPT.md",
                target / "docs" / "CODEX_AUTOMATION_TASKS.md",
                target / "scripts" / "run_codex_automation.sh",
            ]
            if schedule_strategy == SCHEDULE_STRATEGY_CONVEYOR:
                required.extend(
                    [
                        target / "scripts" / "run_conveyor_automation.sh",
                        target / "scripts" / "run_conveyor_automation.py",
                    ]
                )
            if self._target_multi_role_enabled(target):
                required.extend(
                    [
                        target / ".agentic" / "roles" / "planner.md",
                        target / ".agentic" / "roles" / "builder.md",
                        target / ".agentic" / "roles" / "hardener.md",
                        target / ".agentic" / "roles" / "integrator.md",
                        target / "docs" / "MULTI_ROLE_PROGRESS.md",
                        target / "scripts" / "run_role_automation.sh",
                        target / "scripts" / "integrate_role_outputs.py",
                        target / "scripts" / "list_deferred_patches.py",
                    ]
                )
            if self._target_ticket_campaign_enabled(target):
                required.append(target / "docs" / "TICKET_RUN.md")
            missing = [path.relative_to(target).as_posix() for path in required if not path.exists()]
            if missing:
                return False, "Missing " + ", ".join(missing)
            requires_initial_commit = (
                self._target_multi_role_enabled(target)
                or schedule_strategy == SCHEDULE_STRATEGY_CONVEYOR
            )
            if requires_initial_commit and not self._target_has_initial_commit(target):
                return False, "Multi-role or conveyor scheduling requires an initialized git repo with an initial commit."
            task_text = (target / "docs" / "CODEX_AUTOMATION_TASKS.md").read_text(
                encoding="utf-8",
                errors="replace",
            )
            if "Current baseline: not bootstrapped yet" in task_text:
                return False, "Bootstrap has not completed yet."
            status_match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", task_text, re.MULTILINE)
            if not status_match:
                return False, "Missing AUTOMATION_STATUS in docs/CODEX_AUTOMATION_TASKS.md."
            status = status_match.group(1).strip().upper()
            if status not in SCHEDULABLE_STATUSES:
                return False, f"Automation status is {status}; scheduling requires ACTIVE or ACTIVE_WITH_PENDING_USER_INPUT."
            return True, "Ready."

        def _launchd_loaded(self, label: str) -> bool:
            if sys.platform != "darwin":
                return False
            result = subprocess.run(
                ["launchctl", "print", launchd_service_target(label)],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0

        def _launchd_disabled(self, label: str) -> bool:
            if sys.platform != "darwin":
                return False
            result = subprocess.run(
                ["launchctl", "print-disabled", launchd_domain_target()],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return False
            output = result.stdout or result.stderr
            return re.search(rf'"{re.escape(label)}"\s*=>\s*true', output) is not None

        def _target_human_bridge_mode(self, target: Path) -> str:
            intake_path = target / ".agentic" / "project_intake.json"
            if intake_path.exists():
                try:
                    intake = json.loads(intake_path.read_text(encoding="utf-8"))
                    mode = str(intake.get("human_bridge_mode") or "disabled")
                    enabled = bool(intake.get("human_bridge_enabled", mode != "disabled"))
                    return mode if enabled and mode in {"file_only", "local_notifier", "discord_notifier"} else "disabled"
                except (OSError, json.JSONDecodeError):
                    pass
            return self.bridge_mode_var.get() if self.human_bridge_enabled_var.get() else "disabled"

        def _target_multi_role_enabled(self, target: Path) -> bool:
            intake_path = target / ".agentic" / "project_intake.json"
            if intake_path.exists():
                try:
                    intake = json.loads(intake_path.read_text(encoding="utf-8"))
                    return bool(intake.get("multi_role_automations_allowed", False))
                except (OSError, json.JSONDecodeError):
                    pass
            state_path = dashboard_state_path(target)
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    return bool(state.get("multi_role_automations_allowed", False))
                except (OSError, json.JSONDecodeError):
                    pass
            for marker_path in [
                target / ".agentic" / "automation_prompt.md",
                target / "docs" / "CODEX_AUTOMATION_TASKS.md",
            ]:
                if marker_path.exists():
                    text = marker_path.read_text(encoding="utf-8", errors="replace")
                    if "Multi-role automations allowed: true" in text:
                        return True
                    if "Multi-role automations allowed: false" in text:
                        return False
            return bool(self.multi_role_automations_var.get())

        def _target_ticket_campaign_enabled(self, target: Path) -> bool:
            intake_path = target / ".agentic" / "project_intake.json"
            if intake_path.exists():
                try:
                    intake = json.loads(intake_path.read_text(encoding="utf-8"))
                    return str(intake.get("automation_run_mode") or "continuous_improvement") == "ticket_campaign"
                except (OSError, json.JSONDecodeError):
                    pass
            state_path = dashboard_state_path(target)
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    return str(state.get("automation_run_mode") or "continuous_improvement") == "ticket_campaign"
                except (OSError, json.JSONDecodeError):
                    pass
            return bool(self.ticket_campaign_enabled_var.get())

        def _target_ticket_completion_notify_enabled(self, target: Path) -> bool:
            intake_path = target / ".agentic" / "project_intake.json"
            if intake_path.exists():
                try:
                    intake = json.loads(intake_path.read_text(encoding="utf-8"))
                    return bool_from_value(intake.get("ticket_completion_notify"), True)
                except (OSError, json.JSONDecodeError):
                    pass
            state_path = dashboard_state_path(target)
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    return bool_from_value(state.get("ticket_completion_notify"), True)
                except (OSError, json.JSONDecodeError):
                    pass
            return bool(self.ticket_completion_notify_var.get())

        def _target_local_notifications_enabled(self, target: Path) -> bool:
            intake_path = target / ".agentic" / "project_intake.json"
            if intake_path.exists():
                try:
                    intake = json.loads(intake_path.read_text(encoding="utf-8"))
                    return bool_from_value(intake.get("local_notifications_enabled"), True)
                except (OSError, json.JSONDecodeError):
                    pass
            state_path = dashboard_state_path(target)
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    return bool_from_value(state.get("local_notifications_enabled"), True)
                except (OSError, json.JSONDecodeError):
                    pass
            return bool(self.local_notifications_enabled_var.get())

        def _target_schedule_strategy(self, target: Path) -> str:
            state_path = dashboard_state_path(target)
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if "automation_schedule_strategy" in state:
                        return schedule_strategy_from_value(
                            state.get("automation_schedule_strategy"),
                            multi_role_enabled=self._target_multi_role_enabled(target),
                        )
                except (OSError, json.JSONDecodeError):
                    pass
            intake_path = target / ".agentic" / "project_intake.json"
            if intake_path.exists():
                try:
                    intake = json.loads(intake_path.read_text(encoding="utf-8"))
                    if "automation_schedule_strategy" in intake:
                        return schedule_strategy_from_value(
                            intake.get("automation_schedule_strategy"),
                            multi_role_enabled=self._target_multi_role_enabled(target),
                        )
                except (OSError, json.JSONDecodeError):
                    pass
            return self.schedule_strategy()

        def _target_multi_role_allow_remotes(self, target: Path) -> bool:
            state_path = dashboard_state_path(target)
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if "multi_role_allow_remotes" in state:
                        return bool(state.get("multi_role_allow_remotes"))
                except (OSError, json.JSONDecodeError):
                    pass
            intake_path = target / ".agentic" / "project_intake.json"
            if intake_path.exists():
                try:
                    intake = json.loads(intake_path.read_text(encoding="utf-8"))
                    if "multi_role_allow_remotes" in intake:
                        return bool(intake.get("multi_role_allow_remotes"))
                except (OSError, json.JSONDecodeError):
                    pass
            return bool(self.multi_role_allow_remotes_var.get())

        def _target_is_git_repo(self, target: Path) -> bool:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(target),
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"

        def _target_has_initial_commit(self, target: Path) -> bool:
            return target_has_initial_commit(target)

        def _target_git_remotes(self, target: Path) -> str:
            result = subprocess.run(
                ["git", "remote", "-v"],
                cwd=str(target),
                capture_output=True,
                text=True,
                check=False,
            )
            return (result.stdout or result.stderr).strip() if result.returncode == 0 else ""

        def _schedule_labels(self, target: Path) -> list[str]:
            strategy = self._target_schedule_strategy(target)
            if strategy == SCHEDULE_STRATEGY_CONVEYOR:
                return [launchd_conveyor_label(target)]
            if strategy == SCHEDULE_STRATEGY_FIXED_MULTI_ROLE and self._target_multi_role_enabled(target):
                return [launchd_role_label(target, role) for role in MULTI_ROLE_ROLES]
            return [launchd_label(target)]

        def _all_schedule_labels(self, target: Path) -> list[str]:
            return [
                launchd_label(target),
                launchd_conveyor_label(target),
                *[launchd_role_label(target, role) for role in MULTI_ROLE_ROLES],
            ]

        def _schedule_plists(self, target: Path) -> list[Path]:
            return [launchd_plist_path(label) for label in self._schedule_labels(target)]

        def _schedule_prerequisites(self, target: Path) -> list[PrerequisiteItem]:
            items = check_prerequisites(target, self._target_human_bridge_mode(target))
            launchctl_path = shutil.which("launchctl") if sys.platform == "darwin" else None
            items.append(
                PrerequisiteItem(
                    "launchctl available for scheduled automation",
                    bool(launchctl_path),
                    True,
                    launchctl_path or "launchctl is required for dashboard-managed schedules on macOS.",
                )
            )
            strategy = self._target_schedule_strategy(target)
            requires_initial_commit = (
                self._target_multi_role_enabled(target)
                or strategy == SCHEDULE_STRATEGY_CONVEYOR
            )
            if requires_initial_commit:
                has_initial_commit = self._target_has_initial_commit(target)
                items.append(
                    PrerequisiteItem(
                        "Initial git commit for scheduled automation",
                        has_initial_commit,
                        True,
                        "Target has an initial git commit." if has_initial_commit else "Run `git init`, `git add .`, and `git commit -m 'chore: initial commit'` before starting multi-role or conveyor scheduling.",
                    )
                )
            if (
                self._target_human_bridge_mode(target) in {"local_notifier", "discord_notifier"}
                and self._target_local_notifications_enabled(target)
            ):
                osascript_path = shutil.which("osascript")
                items.append(
                    PrerequisiteItem(
                        "macOS desktop notifications",
                        bool(osascript_path),
                        False,
                        osascript_path or "osascript unavailable; notifier delivery will record LOCAL_NOTIFICATION_FAILED in docs/HUMAN_OUTBOX.md.",
                    )
                )
            return items

        def _set_run_automation_state(self) -> None:
            if not hasattr(self, "run_automation_button"):
                return
            if not hasattr(self, "pause_automation_button"):
                return
            if not hasattr(self, "remove_schedule_button"):
                return
            if self.running:
                if hasattr(self, "open_project_button"):
                    self.open_project_button.configure(state="disabled")
                if hasattr(self, "review_bundle_button"):
                    self.review_bundle_button.configure(state="disabled")
                if hasattr(self, "integration_safety_button"):
                    self.integration_safety_button.configure(state="disabled")
                self.run_automation_button.configure(state="disabled")
                self.pause_automation_button.configure(state="disabled")
                self.remove_schedule_button.configure(state="disabled")
                self._set_worker_action_state()
                return
            if hasattr(self, "open_project_button"):
                self.open_project_button.configure(state="normal")
            if hasattr(self, "review_bundle_button"):
                self.review_bundle_button.configure(state="normal" if OBSERVATORY_SCRIPT.exists() else "disabled")
            if hasattr(self, "integration_safety_button"):
                self.integration_safety_button.configure(state="normal" if INTEGRATION_SAFETY_SCRIPT.exists() else "disabled")
            target_text = self.target_var.get().strip()
            if not target_text:
                self.run_automation_button.configure(state="disabled")
                self.pause_automation_button.configure(state="disabled")
                self.remove_schedule_button.configure(state="disabled")
                self.schedule_status_var.set("Schedule: target not loaded.")
                self._set_worker_action_state()
                return
            target = Path(target_text).expanduser().resolve()
            ready, reason = self._automation_ready(target)
            labels = self._all_schedule_labels(target)
            plists = [launchd_plist_path(label) for label in labels]
            loaded_labels = [label for label in labels if self._launchd_loaded(label)]
            existing_plists = [path for path in plists if path.exists()]
            disabled_labels = [label for label in labels if self._launchd_disabled(label)]
            strategy = self._target_schedule_strategy(target)
            if sys.platform != "darwin":
                self.run_automation_button.configure(state="disabled")
                self.pause_automation_button.configure(state="disabled")
                self.remove_schedule_button.configure(state="disabled")
                self.schedule_status_var.set("Schedule: launchd scheduling is available on macOS only.")
                self._set_worker_action_state()
                return
            self.run_automation_button.configure(state="normal" if ready else "disabled")
            self.pause_automation_button.configure(state="normal" if loaded_labels or existing_plists else "disabled")
            self.remove_schedule_button.configure(state="normal" if loaded_labels or existing_plists else "disabled")
            if loaded_labels:
                if any(label == launchd_conveyor_label(target) for label in loaded_labels):
                    self.schedule_status_var.set(f"Schedule: running continuous conveyor ({launchd_conveyor_label(target)}).")
                elif any(label.endswith(tuple(f".{role}" for role in MULTI_ROLE_ROLES)) for label in loaded_labels):
                    self.schedule_status_var.set(f"Schedule: running multi-role launchd group ({len(loaded_labels)} role job(s) loaded).")
                else:
                    self.schedule_status_var.set(f"Schedule: running via launchd ({loaded_labels[0]}).")
            elif existing_plists and disabled_labels:
                if strategy == SCHEDULE_STRATEGY_CONVEYOR:
                    self.schedule_status_var.set("Schedule: conveyor paused and disabled. Remove Schedule deletes the LaunchAgent plist.")
                elif strategy == SCHEDULE_STRATEGY_FIXED_MULTI_ROLE:
                    self.schedule_status_var.set("Schedule: multi-role group paused and disabled. Remove Schedule deletes the role LaunchAgent plists.")
                else:
                    self.schedule_status_var.set(f"Schedule: paused and disabled. Remove Schedule deletes the LaunchAgent plist.")
            elif existing_plists:
                self.schedule_status_var.set(f"Schedule: installed but not loaded: {', '.join(str(path) for path in existing_plists[:4])}.")
            elif ready:
                self.schedule_status_var.set(f"Schedule: not installed. Start scheduled automation to load launchd ({SCHEDULE_STRATEGY_LABELS[strategy]}).")
            else:
                self.schedule_status_var.set(f"Schedule: not ready. {reason}")
            self._set_worker_action_state()

        def start_scheduled_automation(self) -> None:
            if self.running:
                messagebox.showinfo("Process running", "A dashboard-launched process is already running.")
                return
            if sys.platform != "darwin":
                messagebox.showerror("launchd unavailable", "Scheduled automation from the dashboard currently requires macOS launchd.")
                return
            target_text = self.target_var.get().strip()
            if not target_text:
                messagebox.showerror("Missing target", "Choose a target project directory first.")
                return
            target = Path(target_text).expanduser().resolve()
            ready, reason = self._automation_ready(target)
            if not ready:
                messagebox.showerror(
                    "Automation not ready",
                    "Run Scaffold & Bootstrap first. Current blocker:\n\n" + reason,
                )
                self._set_run_automation_state()
                return
            items = self._schedule_prerequisites(target)
            self._show_prerequisites(items)
            failures = required_failures(items)
            if failures:
                messagebox.showerror(
                    "Prerequisites missing",
                    "Fix required prerequisites before starting scheduled automation:\n\n"
                    + "\n".join(f"- {item.name}: {item.detail}" for item in failures),
                )
                return
            advisory = [item for item in items if not item.required and not item.ok]
            if advisory:
                proceed = messagebox.askyesno(
                    "Advisory checks",
                    "Some advisory checks need attention before scheduling. Continue anyway?\n\n"
                    + "\n".join(f"- {item.name}: {item.detail}" for item in advisory),
                )
                if not proceed:
                    return
            try:
                strategy = self.schedule_strategy()
                allow_remotes = bool(self.multi_role_allow_remotes_var.get())
                multi_role_enabled = self._target_multi_role_enabled(target)
                remotes = self._target_git_remotes(target) if multi_role_enabled else ""
                if remotes and strategy in {SCHEDULE_STRATEGY_FIXED_MULTI_ROLE, SCHEDULE_STRATEGY_CONVEYOR} and not allow_remotes:
                    messagebox.showerror(
                        "Multi-role remote opt-in required",
                        "This repo has configured git remotes, so local-only multi-role automation is blocked by default.\n\n"
                        + remotes
                        + "\n\nEnable the advanced option \"Allow local-only multi-role automation when this repo has git remotes\" to set MULTI_ROLE_ALLOW_REMOTES=1 in the launchd job. This still does not allow pushes, fetches, pulls, or remote configuration.",
                    )
                    return
                for label in self._all_schedule_labels(target):
                    plist_path = launchd_plist_path(label)
                    if self._launchd_loaded(label):
                        result = self._launchctl(["bootout", launchd_service_target(label)], allow_failure=True)
                        if result.returncode != 0:
                            self._launchctl(["bootout", launchd_domain_target(), str(plist_path)], allow_failure=True)
                    if plist_path.exists():
                        self._launchctl(["disable", launchd_service_target(label)], allow_failure=True)

                if strategy == SCHEDULE_STRATEGY_CONVEYOR:
                    label, plist_path = write_conveyor_launchd_plist(target, allow_remotes=allow_remotes)
                    self._launchctl(["enable", launchd_service_target(label)], allow_failure=True)
                    self._launchctl(["bootstrap", launchd_domain_target(), str(plist_path)])
                    self._launchctl(["enable", launchd_service_target(label)])
                    self._append_log(
                        f"Started continuous conveyor automation: {label}. It will choose the next runnable lane from local state."
                    )
                    self._append_log(f"LaunchAgent: {plist_path}")
                elif strategy == SCHEDULE_STRATEGY_FIXED_MULTI_ROLE and multi_role_enabled:
                    if not self._target_has_initial_commit(target):
                        raise RuntimeError("Multi-role scheduling requires an initialized git repo with an initial commit.")
                    loaded: list[str] = []
                    for role in MULTI_ROLE_ROLES:
                        label, plist_path = write_role_launchd_plist(target, role, allow_remotes=allow_remotes)
                        self._launchctl(["enable", launchd_service_target(label)], allow_failure=True)
                        self._launchctl(["bootstrap", launchd_domain_target(), str(plist_path)])
                        self._launchctl(["enable", launchd_service_target(label)])
                        loaded.append(label)
                        self._append_log(f"LaunchAgent: {plist_path}")
                    self._append_log(
                        "Started scheduled multi-role automation: "
                        + ", ".join(loaded)
                        + " (planner :00; builder :10/:40; hardener :20/:50; integrator :25/:55)."
                    )
                else:
                    interval = parse_cadence_seconds(self.cadence_var.get())
                    label, plist_path = write_launchd_plist(target, interval)
                    self._launchctl(["enable", launchd_service_target(label)], allow_failure=True)
                    if self._launchd_loaded(label):
                        self._launchctl(["bootout", launchd_service_target(label)], allow_failure=True)
                        self._launchctl(["bootout", launchd_domain_target(), str(plist_path)], allow_failure=True)
                    self._launchctl(["bootstrap", launchd_domain_target(), str(plist_path)])
                    self._launchctl(["enable", launchd_service_target(label)])
                    self._append_log(
                        f"Started scheduled automation: {label} ({format_interval(interval)})."
                    )
                    self._append_log(f"LaunchAgent: {plist_path}")
                self._append_log(f"Logs: {launchd_log_dir(target)}")
                self.write_dashboard_state(target, last_action="schedule_started")
                self._set_run_automation_state()
            except Exception as exc:
                messagebox.showerror("Could not start schedule", str(exc))
                self._append_log(f"ERROR: {exc}")
                self._set_run_automation_state()

        def pause_scheduled_automation(self) -> None:
            if sys.platform != "darwin":
                messagebox.showerror("launchd unavailable", "Scheduled automation from the dashboard currently requires macOS launchd.")
                return
            target_text = self.target_var.get().strip()
            if not target_text:
                messagebox.showerror("Missing target", "Choose a target project directory first.")
                return
            target = Path(target_text).expanduser().resolve()
            try:
                found = False
                for label in self._all_schedule_labels(target):
                    plist_path = launchd_plist_path(label)
                    if self._launchd_loaded(label):
                        result = self._launchctl(["bootout", launchd_service_target(label)], allow_failure=True)
                        if result.returncode != 0:
                            self._launchctl(["bootout", launchd_domain_target(), str(plist_path)], allow_failure=True)
                    if plist_path.exists():
                        self._launchctl(["disable", launchd_service_target(label)], allow_failure=True)
                        self._append_log(f"Paused and disabled scheduled automation: {label}.")
                        found = True
                if not found:
                    self._append_log("Scheduled automation plist was not found.")
                self.write_dashboard_state(target, last_action="schedule_paused")
                self._set_run_automation_state()
            except Exception as exc:
                messagebox.showerror("Could not pause schedule", str(exc))
                self._append_log(f"ERROR: {exc}")
                self._set_run_automation_state()

        def remove_scheduled_automation(self) -> None:
            if sys.platform != "darwin":
                messagebox.showerror("launchd unavailable", "Scheduled automation from the dashboard currently requires macOS launchd.")
                return
            target_text = self.target_var.get().strip()
            if not target_text:
                messagebox.showerror("Missing target", "Choose a target project directory first.")
                return
            target = Path(target_text).expanduser().resolve()
            proceed = messagebox.askyesno(
                "Remove schedule",
                "Remove the dashboard-managed LaunchAgent schedule for this target?\n\n"
                "This stops future scheduled runs and deletes the plist(s). Generated project files are not deleted.",
            )
            if not proceed:
                return
            try:
                removed = False
                for label in self._all_schedule_labels(target):
                    plist_path = launchd_plist_path(label)
                    if self._launchd_loaded(label):
                        result = self._launchctl(["bootout", launchd_service_target(label)], allow_failure=True)
                        if result.returncode != 0:
                            self._launchctl(["bootout", launchd_domain_target(), str(plist_path)], allow_failure=True)
                    self._launchctl(["disable", launchd_service_target(label)], allow_failure=True)
                    self._launchctl(["enable", launchd_service_target(label)], allow_failure=True)
                    if plist_path.exists():
                        plist_path.unlink()
                        self._append_log(f"Removed scheduled automation LaunchAgent: {plist_path}")
                        removed = True
                if not removed:
                    self._append_log("Scheduled automation plist was not found.")
                self.write_dashboard_state(target, last_action="schedule_removed")
                self._set_run_automation_state()
            except Exception as exc:
                messagebox.showerror("Could not remove schedule", str(exc))
                self._append_log(f"ERROR: {exc}")
                self._set_run_automation_state()

        def _launchctl(self, args: list[str], allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
            self._append_log("$ launchctl " + " ".join(args))
            result = subprocess.run(
                ["launchctl", *args],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
            output = (result.stdout or result.stderr).strip()
            if output:
                self._append_log(output)
            if result.returncode != 0 and not allow_failure:
                raise RuntimeError(output or f"launchctl exited with code {result.returncode}")
            return result

        def add_inbox_reply(self) -> None:
            target = Path(self.target_var.get().strip() or ".").expanduser()
            body = self.reply_body.get("1.0", "end").strip()
            if not body:
                messagebox.showerror("Missing reply", "Write the reply body first.")
                return
            inbox_id = append_manual_inbox_entry(
                target,
                body,
                request_id=self.reply_request_entry.get().strip(),
                parsed_intent=INTENT_CHOICES.get(self.intent_var.get(), "info"),
            )
            self.reply_body.delete("1.0", "end")
            self._append_log(f"Queued message for next automation run: {inbox_id}.")
            self.refresh_human()

        def check_notifier_health(self) -> None:
            ok, detail = fetch_notifier_health(timeout=1.2)
            title = "Notifier reachable" if ok else "Notifier unavailable"
            messagebox.showinfo(title, detail)

        def _load_markdown_file(self, widget: Any, path: Path) -> None:
            if path.exists() and path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                self._render_markdown(widget, text)
            else:
                self._set_text(widget, f"{path} does not exist yet.")

        def _configure_markdown_tags(self, widget: Any) -> None:
            widget.tag_configure("h1", font=("TkDefaultFont", 18, "bold"), spacing1=8, spacing3=6)
            widget.tag_configure("h2", font=("TkDefaultFont", 14, "bold"), spacing1=8, spacing3=4)
            widget.tag_configure("h3", font=("TkDefaultFont", 12, "bold"), spacing1=6, spacing3=3)
            widget.tag_configure("code", font=("TkFixedFont", 10), background="#f4f4f4")
            widget.tag_configure("bullet", lmargin1=20, lmargin2=36)

        def _render_markdown(self, widget: Any, text: str) -> None:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            in_code = False
            for raw_line in text.splitlines(keepends=True):
                line = raw_line.rstrip("\n")
                tag = None
                if line.startswith("```"):
                    in_code = not in_code
                    tag = "code"
                elif in_code:
                    tag = "code"
                elif line.startswith("# "):
                    tag = "h1"
                elif line.startswith("## "):
                    tag = "h2"
                elif line.startswith("### "):
                    tag = "h3"
                elif line.startswith("- ") or re.match(r"^\d+\.\s", line):
                    tag = "bullet"
                widget.insert("end", raw_line, tag)
            widget.configure(state="disabled")

        def _set_text(self, widget: Any, text: str) -> None:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(state="disabled")

        def _append_log(self, text: str) -> None:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.configure(state="normal")
            lines = str(text).splitlines() or [""]
            for line in lines:
                if len(line) > MAX_DASHBOARD_LOG_LINE_CHARS:
                    line = line[:MAX_DASHBOARD_LOG_LINE_CHARS] + " ... [truncated]"
                self.log_text.insert("end", f"[{timestamp}] {line}\n")
                self.log_line_count += 1
            if self.log_line_count > MAX_DASHBOARD_LOG_LINES:
                excess = self.log_line_count - MAX_DASHBOARD_LOG_LINES
                self.log_text.delete("1.0", f"{excess + 1}.0")
                self.log_line_count = MAX_DASHBOARD_LOG_LINES
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        def _thread_log(self, text: str) -> None:
            self.events.put(("log", text))

        def _drain_events(self) -> None:
            try:
                while True:
                    event, payload = self.events.get_nowait()
                    if event == "log":
                        self._append_log(str(payload))
                    elif event == "refresh":
                        self.refresh_all()
                    elif event == "bootstrap_done":
                        target = Path(str(payload)).expanduser().resolve()
                        self.bootstrap_completed_targets.add(target)
                        self.write_dashboard_state(target, last_action="bootstrap_completed")
                        self._set_run_automation_state()
                    elif event == "done":
                        self.running = False
                        self.open_project_button.configure(state="normal")
                        self.scaffold_button.configure(state="normal")
                        self._set_run_automation_state()
                        self.cancel_button.configure(state="disabled")
                        self._append_log("Process finished.")
            except queue.Empty:
                pass
            self.root.after(120, self._drain_events)


def smoke_check() -> int:
    problems: list[str] = []
    for path in [SCAFFOLD_SCRIPT, CHECK_REQUIRED_SCRIPT, OBSERVATORY_SCRIPT, INTEGRATION_SAFETY_SCRIPT]:
        if not path.exists():
            problems.append(f"Missing required script: {path}")
    if "--review-dir" not in " ".join(review_bundle_command(KIT_ROOT)):
        problems.append("Review bundle command is not wired to --review-dir.")
    smoke_strategy = {"strategy": "READ_ONLY_REPORTS", "parallelism_budget": 1, "action_lane": "builder"}
    if "--read-only" not in read_only_worker_command(KIT_ROOT, smoke_strategy, run_id="dashboard-smoke"):
        problems.append("Dashboard read-only worker command is not wired to --read-only.")
    if "--write" not in write_worker_command(KIT_ROOT, {"strategy": "WRITE_WORKERS", "action_lane": "builder"}, "docs/** only", run_id="dashboard-smoke"):
        problems.append("Dashboard write-worker command is not wired to --write.")
    if "summarize_worker_outputs.py" not in " ".join(worker_summary_command(KIT_ROOT, "dashboard-smoke")):
        problems.append("Dashboard worker summary command is not wired to summarize_worker_outputs.py.")
    if "--role" not in integration_only_command(KIT_ROOT, run_id="dashboard-smoke"):
        problems.append("Dashboard integration-only command is not wired to run_role_automation.sh.")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print("OK: dashboard module smoke check passed")
    if not TK_AVAILABLE:
        print(f"NOTE: Tkinter is unavailable in this Python environment: {TK_IMPORT_ERROR}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="", help="Optional target project directory to prefill")
    parser.add_argument("--smoke-check", action="store_true", help="Check dashboard wiring without launching the GUI")
    args = parser.parse_args(argv)

    if args.smoke_check:
        return smoke_check()

    if not TK_AVAILABLE:
        print(
            "Tkinter is required for the standalone Diffmogger dashboard but is not available: "
            + TK_IMPORT_ERROR,
            file=sys.stderr,
        )
        return 1

    root = tk.Tk()
    DiffmoggerDashboard(root, initial_target=args.target)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
