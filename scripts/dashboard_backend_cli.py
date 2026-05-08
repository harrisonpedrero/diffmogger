#!/usr/bin/env python3
"""JSON backend command layer for the Diffmogger native dashboard."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diffmogger_paths import existing_or_target_path, preferred_target_path, sidecar_rel, target_path


SCHEMA_VERSION = 1
KIT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = KIT_ROOT / "services" / "agentic-dashboard"
OBSERVATORY_SCRIPT = KIT_ROOT / "scripts" / "run_observatory.py"
CHECK_REQUIRED_SCRIPT = KIT_ROOT / "scripts" / "check_required_files.py"
CHECK_INTEGRATION_SAFETY_SCRIPT = KIT_ROOT / "scripts" / "check_integration_safety.py"
DEFAULT_REVIEW_HTML = "Diffmogger-observatory.html"
DEFAULT_REVIEW_MARKDOWN = "Diffmogger-self-review.md"
MAX_TEXT_BYTES = 1_000_000
MAX_HTML_BYTES = 5_000_000
LEGACY_TKINTER_CHECK = "Tkinter GUI runtime"
NATIVE_TKINTER_CHECK = "Legacy Tkinter dashboard runtime"


class BackendError(Exception):
    def __init__(
        self,
        message: str,
        *,
        exit_code: int = 1,
        error_type: str = "backend_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.error_type = error_type
        self.details = details or {}


def target_script_path(target: Path, legacy_rel: str) -> Path:
    return existing_or_target_path(target.expanduser().resolve(), legacy_rel)


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))


def emit_jsonl(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, default=json_default), flush=True)


def success(command: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": command,
        "data": data,
    }


def failure(command: str, error: BackendError) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "command": command,
        "message": error.message,
        "error": {
            "type": error.error_type,
            "details": error.details,
        },
    }


def stream_event(
    args: argparse.Namespace,
    stage: str,
    message: str,
    *,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    if not bool(getattr(args, "stream_jsonl", False)):
        return
    emit_jsonl(
        {
            "schema_version": SCHEMA_VERSION,
            "event": "log",
            "stage": stage,
            "level": level,
            "message": message,
            "data": data or {},
        }
    )


class BackendArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        error = BackendError(message, exit_code=2, error_type="argument_error")
        command = "unknown"
        emit(failure(command, error))
        raise SystemExit(error.exit_code)


def load_dashboard_module() -> Any:
    dashboard_root = str(DASHBOARD_ROOT)
    if dashboard_root not in sys.path:
        sys.path.insert(0, dashboard_root)
    try:
        from agentic_dashboard import app as dashboard_app  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - import failures are host-specific.
        raise BackendError(
            "Could not import the existing dashboard backend helpers.",
            error_type="dashboard_import_failed",
            details={"path": str(DASHBOARD_ROOT), "exception": str(exc)},
        ) from exc
    return dashboard_app


def load_repo_dotenv_for_backend() -> int:
    spec = importlib.util.spec_from_file_location("diffmogger_run_dashboard", KIT_ROOT / "scripts" / "run_dashboard.py")
    if spec is None or spec.loader is None:
        return 0
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loader = getattr(module, "load_repo_dotenv", None)
    if not callable(loader):
        return 0
    return int(loader(KIT_ROOT) or 0)


def load_observatory_module() -> Any:
    dashboard_app = load_dashboard_module()
    try:
        return dashboard_app.load_observatory_module()
    except Exception as exc:
        raise BackendError(
            "Could not import the existing Observatory helper.",
            error_type="observatory_import_failed",
            details={"path": str(OBSERVATORY_SCRIPT), "exception": str(exc)},
        ) from exc


def resolve_target(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise BackendError("A target path is required.", exit_code=2, error_type="invalid_target")
    target = Path(raw).expanduser()
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise BackendError(
            "Could not resolve target path.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(raw), "exception": str(exc)},
        ) from exc
    if not resolved.exists():
        raise BackendError(
            "Target path does not exist.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(resolved)},
        )
    if not resolved.is_dir():
        raise BackendError(
            "Target path must be a directory.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(resolved)},
        )
    return resolved


def resolve_review_dir(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise BackendError("A review directory is required.", exit_code=2, error_type="invalid_review_dir")
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise BackendError(
            "Could not resolve review directory.",
            exit_code=2,
            error_type="invalid_review_dir",
            details={"review_dir": str(raw), "exception": str(exc)},
        ) from exc
    if resolved.exists() and not resolved.is_dir():
        raise BackendError(
            "Review path exists but is not a directory.",
            exit_code=2,
            error_type="invalid_review_dir",
            details={"review_dir": str(resolved)},
        )
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackendError(
            "Could not create review directory.",
            exit_code=2,
            error_type="invalid_review_dir",
            details={"review_dir": str(resolved), "exception": str(exc)},
        ) from exc
    return resolved


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_text_file(path: Path, *, max_bytes: int = MAX_TEXT_BYTES) -> tuple[str, bool]:
    with path.open("rb") as handle:
        payload = handle.read(max_bytes + 1)
    truncated = len(payload) > max_bytes
    if truncated:
        payload = payload[:max_bytes]
    return payload.decode("utf-8", errors="replace"), truncated


def parse_json_arg(raw: str, *, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackendError(
            f"{label} must be valid JSON.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": label, "exception": str(exc)},
        ) from exc


def mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return None


def compact_text(value: Any, *, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def target_metadata(target: Path) -> dict[str, Any]:
    intake_path = existing_or_target_path(target, ".agentic/project_intake.json")
    dashboard_path = existing_or_target_path(target, ".agentic/dashboard_state.json")
    task_path = existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
    return {
        "path": str(target),
        "name": target.name or str(target),
        "exists": target.exists(),
        "is_dir": target.is_dir(),
        "is_diffmogger_project": intake_path.exists() or task_path.exists(),
        "project_intake_path": str(intake_path),
        "project_intake_exists": intake_path.exists(),
        "dashboard_state_path": str(dashboard_path),
        "dashboard_state_exists": dashboard_path.exists(),
        "automation_task_path": str(task_path),
        "automation_task_exists": task_path.exists(),
    }


def load_intake(target: Path) -> dict[str, Any]:
    return read_json_file(existing_or_target_path(target, ".agentic/project_intake.json"))


def load_dashboard_state(target: Path) -> dict[str, Any]:
    return read_json_file(existing_or_target_path(target, ".agentic/dashboard_state.json"))


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_dashboard_action_state(
    target: Path,
    *,
    last_action: str,
    updates: dict[str, Any] | None = None,
) -> Path:
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to write target dashboard state into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )
    state = load_dashboard_state(target)
    state.update(updates or {})
    state["schema_version"] = int(state.get("schema_version") or 1)
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["last_action"] = last_action
    state_path = preferred_target_path(target, ".agentic/dashboard_state.json")
    write_json_file(state_path, state)
    return state_path


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip().removeprefix("-").strip() for line in value.splitlines() if line.strip()]
    return []


def cadence_minutes_from_intake(intake: dict[str, Any], dashboard_app: Any) -> int:
    raw = intake.get("desired_cadence") or intake.get("cadence_minutes") or "every 60 minutes"
    try:
        return dashboard_app.cadence_minutes_from_text(raw)
    except Exception:
        return 60


def dashboard_state_from_intake(
    target: Path,
    intake: dict[str, Any],
    *,
    last_action: str,
) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    existing = load_dashboard_state(target)
    optional_mcp = dashboard_app.optional_mcp_servers_from_value(intake.get("optional_mcp_servers"))
    write_workers_enabled = bool(intake.get("write_worker_agents_allowed")) and bool(intake.get("worker_agents_allowed", True))
    multi_role_enabled = bool(intake.get("multi_role_automations_allowed"))
    schedule_strategy = dashboard_app.schedule_strategy_from_value(
        intake.get("automation_schedule_strategy"),
        multi_role_enabled=multi_role_enabled,
    )
    state = {
        **existing,
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_name": str(intake.get("project_name") or target.name or "New Project"),
        "project_mode": str(intake.get("project_mode") or "fresh_project"),
        "cadence_minutes": cadence_minutes_from_intake(intake, dashboard_app),
        "automation_schedule_strategy": schedule_strategy,
        "human_bridge_enabled": bool(intake.get("human_bridge_enabled", True)),
        "human_bridge_mode": str(intake.get("human_bridge_mode") or "file_only"),
        "human_requested_text_responses": bool(intake.get("human_requested_text_responses", True)),
        "local_notifications_enabled": bool(intake.get("local_notifications_enabled", True)),
        "env_access_policy": str(intake.get("env_access_policy") or "project_commands_only"),
        "worker_agents_allowed": bool(intake.get("worker_agents_allowed", True)),
        "codex_cli_workers_expected_on_broad_runs": bool(intake.get("codex_cli_workers_expected_on_broad_runs", True)),
        "automation_signals_enabled": bool(intake.get("automation_signals_enabled", False)),
        "optional_mcp_servers": optional_mcp,
        "write_worker_agents_allowed": write_workers_enabled,
        "max_write_worker_count": dashboard_app.write_worker_count_from_text(
            intake.get("max_write_worker_count"),
            enabled=write_workers_enabled,
        ),
        "multi_role_automations_allowed": multi_role_enabled,
        "automation_role_profile": "planner_builder_hardener_integrator" if multi_role_enabled else "single_lane",
        "automation_checkpoint_commits": bool(intake.get("automation_checkpoint_commits", True)),
        "multi_role_base_cadence_minutes": dashboard_app.multi_role_cadence_minutes_from_text(
            intake.get("multi_role_base_cadence_minutes"),
        ),
        "multi_role_allow_remotes": bool(intake.get("multi_role_allow_remotes", False)),
        "automation_run_mode": str(intake.get("automation_run_mode") or "continuous_improvement"),
        "ticket_run_file": str(intake.get("ticket_run_file") or sidecar_rel("docs/TICKET_RUN.md")),
        "ticket_completion_notify": bool(intake.get("ticket_completion_notify", True)),
        "overwrite_existing_scaffold_files": bool(intake.get("overwrite_existing_scaffold_files", False)),
        "brief_draft_intake": intake,
        "last_action": last_action,
    }
    return state


def project_intake_payload(intake: dict[str, Any]) -> dict[str, Any]:
    payload = dict(intake)
    payload.pop("overwrite_existing_scaffold_files", None)
    return payload


def write_dashboard_state_from_intake(target: Path, intake: dict[str, Any], *, last_action: str) -> Path:
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to write target dashboard state into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )
    state_path = preferred_target_path(target, ".agentic/dashboard_state.json")
    write_json_file(state_path, dashboard_state_from_intake(target, intake, last_action=last_action))
    return state_path


def detect_target_context(target: Path) -> dict[str, Any]:
    def exists(*parts: str) -> bool:
        return (target.joinpath(*parts)).exists()

    def read_package_scripts() -> dict[str, str]:
        package = read_json_file(target / "package.json")
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        return {str(key): str(value) for key, value in scripts.items()}

    def git_output(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(target),
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )

    package_manager = "unknown"
    if exists("pnpm-lock.yaml"):
        package_manager = "pnpm"
    elif exists("yarn.lock"):
        package_manager = "yarn"
    elif exists("package-lock.json"):
        package_manager = "npm"
    elif exists("bun.lockb") or exists("bun.lock"):
        package_manager = "bun"
    elif exists("uv.lock"):
        package_manager = "uv"
    elif exists("poetry.lock"):
        package_manager = "poetry"
    elif exists("package.json"):
        package_manager = "npm"
    elif exists("pyproject.toml"):
        package_manager = "python"

    scripts = read_package_scripts()
    suggested_commands: list[str] = []
    if scripts:
        runner = {"pnpm": "pnpm", "yarn": "yarn", "bun": "bun"}.get(package_manager, "npm run")
        for name in ["test", "lint", "typecheck", "build", "dev"]:
            if name in scripts:
                suggested_commands.append(f"{runner} {name}" if runner != "yarn" else f"yarn {name}")
    if exists("pyproject.toml"):
        if not suggested_commands:
            suggested_commands.extend(["python -m pytest", "python -m unittest"])
    if exists("Cargo.toml"):
        suggested_commands.extend(["cargo test", "cargo check"])

    try:
        branch = git_output(["branch", "--show-current"])
        status = git_output(["status", "--short"])
        remotes = git_output(["remote", "-v"])
        is_git_repo = branch.returncode == 0 or status.returncode == 0
        dirty_count = len([line for line in status.stdout.splitlines() if line.strip()]) if status.returncode == 0 else 0
    except OSError:
        is_git_repo = False
        dirty_count = 0
        branch = subprocess.CompletedProcess([], 1, "", "")
        remotes = subprocess.CompletedProcess([], 1, "", "")

    return {
        "is_git_repo": is_git_repo,
        "git_branch": branch.stdout.strip() if branch.returncode == 0 else "unknown",
        "git_dirty_count": dirty_count,
        "has_remotes": bool(remotes.stdout.strip()) if remotes.returncode == 0 else False,
        "package_manager": package_manager,
        "package_scripts": scripts,
        "suggested_verification_commands": suggested_commands,
        "detected_files": {
            "package_json": exists("package.json"),
            "pyproject_toml": exists("pyproject.toml"),
            "cargo_toml": exists("Cargo.toml"),
            "go_mod": exists("go.mod"),
            "makefile": exists("Makefile") or exists("makefile"),
        },
    }


def optional_mcp_from_state(target: Path, dashboard_app: Any) -> list[str]:
    dashboard_state = load_dashboard_state(target)
    if "optional_mcp_servers" in dashboard_state:
        return dashboard_app.optional_mcp_servers_from_value(dashboard_state.get("optional_mcp_servers"))
    intake = load_intake(target)
    return dashboard_app.optional_mcp_servers_from_value(intake.get("optional_mcp_servers"))


def human_bridge_mode_from_state(target: Path) -> str:
    for data in (load_intake(target), load_dashboard_state(target)):
        mode = str(data.get("human_bridge_mode") or "").strip()
        enabled = bool(data.get("human_bridge_enabled", mode != "disabled"))
        if enabled and mode in {"file_only", "local_notifier", "discord_notifier"}:
            return mode
        if mode == "disabled":
            return "disabled"
    return "file_only"


HUMAN_INTENTS = {"info", "done", "skip", "approve", "reject", "unknown"}
HUMAN_REQUEST_STATUSES = {"active", "awaiting_user", "awaiting_human", "pending", "open", "unresolved"}
HUMAN_ARCHIVE_STATUSES = {"resolved", "handled", "consumed", "archived", "done", "closed", "skipped"}


def human_file(target: Path, name: str) -> Path:
    return target_path(target, f"docs/{name}")


def parse_metadata_block(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*-\s+([A-Za-z0-9_-]+):\s*(.*)\s*$", line)
        if match:
            metadata[match.group(1).strip()] = match.group(2).strip()
    return metadata


def extract_markdown_body(section: str) -> str:
    body_match = re.search(r"^#{3,5}\s+Body\s*$", section, flags=re.IGNORECASE | re.MULTILINE)
    if body_match:
        body_start = body_match.end()
        next_heading = re.search(r"^#{3,5}\s+", section[body_start:], flags=re.MULTILINE)
        body_end = body_start + next_heading.start() if next_heading else len(section)
        return section[body_start:body_end].strip()
    stripped_lines = [
        line
        for line in section.splitlines()
        if not re.match(r"^\s*-\s+[A-Za-z0-9_-]+:\s*", line)
        and not re.match(r"^#{1,6}\s+", line)
        and not line.strip().startswith("```")
    ]
    return "\n".join(stripped_lines).strip()


def markdown_record_summary(section: str, metadata: dict[str, str], body: str) -> str:
    for key in ("summary", "action_taken", "remaining_followup", "blocker", "reason"):
        if metadata.get(key):
            return compact_text(metadata[key], limit=180)
    if body:
        return compact_text(body, limit=180)
    return "No message body recorded."


def parse_markdown_records(path: Path, prefixes: tuple[str, ...]) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    text, truncated = read_text_file(path)
    prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
    heading_pattern = re.compile(
        rf"^(?P<level>##+)\s+(?P<record_id>(?:{prefix_pattern})-[A-Za-z0-9_.:-]+)(?P<title>[^\n]*)$",
        flags=re.MULTILINE,
    )
    matches = list(heading_pattern.finditer(text))
    records: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        record_id = match.group("record_id").strip()
        if "YYYY" in record_id or record_id.endswith("-001`"):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        metadata_boundary = re.search(r"^#{3,5}\s+Body\s*$", section, flags=re.IGNORECASE | re.MULTILINE)
        metadata_text = section[: metadata_boundary.start()] if metadata_boundary else section
        metadata = parse_metadata_block(metadata_text)
        body = extract_markdown_body(section)
        raw_status = metadata.get("status", "").strip().lower()
        title = match.group("title").strip(" -:\t")
        records.append(
            {
                "id": record_id,
                "title": title or record_id,
                "status": raw_status or "unknown",
                "status_label": (raw_status or "unknown").replace("_", " ").title(),
                "timestamp": metadata.get("received_at")
                or metadata.get("created_at")
                or metadata.get("requested_at")
                or metadata.get("resolved_at")
                or metadata.get("timestamp")
                or "",
                "request_id": metadata.get("request_id", ""),
                "source_inbox_id": metadata.get("source_inbox_id", ""),
                "intent": metadata.get("parsed_intent") or metadata.get("intent") or "",
                "channel": metadata.get("channel", ""),
                "from": metadata.get("from", ""),
                "to": metadata.get("to", ""),
                "related": {
                    "request": metadata.get("request_id", ""),
                    "ticket": metadata.get("ticket_id") or metadata.get("related_ticket") or metadata.get("ticket") or "",
                    "run": metadata.get("run_id") or metadata.get("related_run") or "",
                    "file": metadata.get("file") or metadata.get("related_file") or metadata.get("path") or "",
                },
                "metadata": metadata,
                "body": body,
                "summary": markdown_record_summary(section, metadata, body),
                "source_file_key": "",
                "truncated": truncated,
            }
        )
    return records


def classify_request(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "").lower()
    if status in HUMAN_ARCHIVE_STATUSES:
        return "handled"
    if status in HUMAN_REQUEST_STATUSES:
        return "pending"
    return "unknown"


def classify_note(record: dict[str, Any], archived_inbox_ids: set[str]) -> str:
    status = str(record.get("status") or "").lower()
    record_id = str(record.get("id") or "")
    if record_id in archived_inbox_ids:
        return "archived"
    if status in {"handled", "consumed", "archived", "done", "closed"}:
        return "consumed"
    if status in {"failed", "error"}:
        return "failed"
    return "queued"


def inbox_snapshot(target: Path) -> dict[str, Any]:
    requests = parse_markdown_records(human_file(target, "HUMAN_REQUESTS.md"), ("HR",))
    notes = parse_markdown_records(human_file(target, "HUMAN_INBOX.md"), ("INBOX",))
    archive_records = parse_markdown_records(human_file(target, "HUMAN_RESPONSES_ARCHIVE.md"), ("HR", "INBOX", "ARCHIVE"))
    outbox = parse_markdown_records(human_file(target, "HUMAN_OUTBOX.md"), ("OUTBOX",))

    archived_inbox_ids = {
        str(record.get("source_inbox_id") or "")
        for record in archive_records
        if str(record.get("source_inbox_id") or "").strip()
    }
    for record in requests:
        record["kind"] = "request"
        record["ui_state"] = classify_request(record)
        record["source_file_key"] = "human.requests_from_automation"
    for record in notes:
        record["kind"] = "note"
        record["ui_state"] = classify_note(record, archived_inbox_ids)
        record["source_file_key"] = "human.messages_waiting_for_next_run"
    for record in archive_records:
        record["kind"] = "archive"
        record["ui_state"] = "archived"
        record["source_file_key"] = "human.resolved_conversation_history"
    for record in outbox:
        record["kind"] = "outbound"
        record["ui_state"] = "sent"
        record["source_file_key"] = "human.sent_updates_delivery_log"

    handled_requests = [record for record in requests if record.get("ui_state") == "handled"]
    active_requests = [record for record in requests if record.get("ui_state") == "pending"]
    active_notes = [record for record in notes if record.get("ui_state") in {"queued", "failed"}]
    archive_items = [*archive_records, *handled_requests, *[record for record in notes if record.get("ui_state") in {"archived", "consumed"}]]
    return {
        "target": target_metadata(target),
        "bridge_mode": human_bridge_mode_from_state(target),
        "requests": requests,
        "active_requests": active_requests,
        "notes": notes,
        "active_notes": active_notes,
        "archive": archive_items,
        "outbox": outbox,
        "counts": {
            "pending_requests": len(active_requests),
            "queued_notes": len([record for record in notes if record.get("ui_state") == "queued"]),
            "failed_notes": len([record for record in notes if record.get("ui_state") == "failed"]),
            "archived_items": len(archive_items),
            "outbound_records": len(outbox),
        },
        "raw_file_keys": [
            "human.requests_from_automation",
            "human.messages_waiting_for_next_run",
            "human.sent_updates_delivery_log",
            "human.resolved_conversation_history",
        ],
    }


def command_inbox_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    return inbox_snapshot(target)


def normalize_human_intent(raw: str) -> str:
    intent = str(raw or "info").strip().lower()
    if intent not in HUMAN_INTENTS:
        raise BackendError(
            "Intent is not supported by the file-only human bridge.",
            exit_code=2,
            error_type="invalid_human_intent",
            details={"intent": raw, "allowed": sorted(HUMAN_INTENTS)},
        )
    return intent


def command_inbox_send_note(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    body = str(args.body or "").strip()
    if not body:
        raise BackendError(
            "A message body is required.",
            exit_code=2,
            error_type="missing_body",
        )
    dashboard_app = load_dashboard_module()
    request_id = str(args.related or "").strip() or "general"
    inbox_id = dashboard_app.append_manual_inbox_entry(
        target,
        body,
        request_id=request_id,
        parsed_intent=normalize_human_intent(args.intent),
    )
    snapshot = inbox_snapshot(target)
    note = next((record for record in snapshot["notes"] if record.get("id") == inbox_id), None)
    return {
        "target": target_metadata(target),
        "inbox_id": inbox_id,
        "status": "queued",
        "note": note,
        "inbox_path": str(human_file(target, "HUMAN_INBOX.md")),
        "snapshot": snapshot,
    }


def command_inbox_reply_request(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    request_id = str(args.request_id or "").strip()
    if not request_id:
        raise BackendError(
            "A request id is required when replying to an automation request.",
            exit_code=2,
            error_type="missing_request_id",
        )
    body = str(args.body or "").strip()
    if not body:
        raise BackendError(
            "A reply body is required.",
            exit_code=2,
            error_type="missing_body",
        )
    dashboard_app = load_dashboard_module()
    inbox_id = dashboard_app.append_manual_inbox_entry(
        target,
        body,
        request_id=request_id,
        parsed_intent=normalize_human_intent(args.intent),
    )
    snapshot = inbox_snapshot(target)
    note = next((record for record in snapshot["notes"] if record.get("id") == inbox_id), None)
    return {
        "target": target_metadata(target),
        "request_id": request_id,
        "inbox_id": inbox_id,
        "status": "queued",
        "note": note,
        "inbox_path": str(human_file(target, "HUMAN_INBOX.md")),
        "snapshot": snapshot,
    }


def build_observatory_snapshot(target: Path) -> dict[str, Any]:
    module = load_observatory_module()
    try:
        return module.build_snapshot(target)
    except Exception as exc:
        raise BackendError(
            "Could not build Observatory snapshot for target.",
            error_type="snapshot_failed",
            details={"target": str(target), "exception": str(exc)},
        ) from exc


def file_category(rel_path: str, group: str, label: str) -> str:
    path = rel_path.replace("\\", "/")
    lower = f"{label} {path}".lower()
    if group == "human" or "human_" in lower:
        return "Human bridge"
    if any(term in lower for term in ("review", "observatory", "safety", "daily review", "experiment log")):
        return "Review"
    if "context" in lower:
        return "Context"
    if any(term in lower for term in ("multi-role", "multi_role", "conveyor", "automation_queue", "signals", "role")):
        return "Multi-role / conveyor"
    return "Core state"


def validation_kind_for_file(rel_path: str) -> str:
    if rel_path.endswith(".json"):
        return "json"
    if rel_path in {"docs/CODEX_AUTOMATION_TASKS.md", sidecar_rel("docs/CODEX_AUTOMATION_TASKS.md")}:
        return "required_files"
    if rel_path in {"target/integration_safety_check.json", sidecar_rel("target/integration_safety_check.json")}:
        return "integration_safety_record"
    return ""


def file_registry(dashboard_app: Any) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}

    def add(prefix: str, label: str, rel_path: str, *, editable: bool = True) -> None:
        key_base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "file"
        key = f"{prefix}.{key_base}"
        registry[key] = {
            "key": key,
            "label": label,
            "rel_path": rel_path,
            "group": prefix,
            "category": file_category(rel_path, prefix, label),
            "editable": editable,
            "validation": validation_kind_for_file(rel_path),
        }

    for label, rel_path in dashboard_app.DOC_CHOICES.items():
        add("monitor", label, rel_path)
    for label, rel_path in dashboard_app.HUMAN_DOC_CHOICES.items():
        add("human", label, rel_path)
    registry["state.project_intake"] = {
        "key": "state.project_intake",
        "label": "Project Intake JSON",
        "rel_path": sidecar_rel(".agentic/project_intake.json"),
        "group": "state",
        "category": "Core state",
        "editable": True,
        "validation": "json",
    }
    registry["state.dashboard"] = {
        "key": "state.dashboard",
        "label": "Dashboard State JSON",
        "rel_path": sidecar_rel(".agentic/dashboard_state.json"),
        "group": "state",
        "category": "Core state",
        "editable": True,
        "validation": "json",
    }
    registry["state.integration_safety"] = {
        "key": "state.integration_safety",
        "label": "Integration Safety Record",
        "rel_path": sidecar_rel("target/integration_safety_check.json"),
        "group": "state",
        "category": "Review",
        "editable": False,
        "validation": "json",
    }
    registry["review.self_review"] = {
        "key": "review.self_review",
        "label": "Self-Review Markdown",
        "rel_path": sidecar_rel(f"target/first-review/{DEFAULT_REVIEW_MARKDOWN}"),
        "group": "review",
        "category": "Review",
        "editable": True,
        "validation": "",
    }
    registry["review.observatory_html"] = {
        "key": "review.observatory_html",
        "label": "Observatory HTML Export",
        "rel_path": sidecar_rel(f"target/first-review/{DEFAULT_REVIEW_HTML}"),
        "group": "review",
        "category": "Review",
        "editable": False,
        "validation": "",
    }
    registry["state.conveyor"] = {
        "key": "state.conveyor",
        "label": "Conveyor State JSON",
        "rel_path": sidecar_rel("target/automation_conveyor_state.json"),
        "group": "state",
        "category": "Multi-role / conveyor",
        "editable": True,
        "validation": "json",
    }
    registry["state.action_plan_history"] = {
        "key": "state.action_plan_history",
        "label": "Action Plan History JSON",
        "rel_path": sidecar_rel("target/action_plan_history.json"),
        "group": "state",
        "category": "Review",
        "editable": True,
        "validation": "json",
    }
    return registry


def describe_registered_file(target: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = (target / record["rel_path"]).resolve()
    if target not in path.parents and path != target:
        raise BackendError(
            "Registered file resolved outside the target.",
            exit_code=2,
            error_type="invalid_file_key",
            details={"file_key": record["key"], "path": str(path)},
        )
    exists = path.exists() and path.is_file()
    size = path.stat().st_size if exists else None
    return {
        **record,
        "path": str(path),
        "exists": exists,
        "size_bytes": size,
        "modified_at": mtime_iso(path) if exists else None,
    }


def command_brief_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = load_intake(target)
    dashboard_state = load_dashboard_state(target)
    draft_intake = dashboard_state.get("brief_draft_intake")
    if not isinstance(draft_intake, dict):
        draft_intake = intake
    project_name = (
        draft_intake.get("project_name")
        or intake.get("project_name")
        or dashboard_state.get("project_name")
        or target.name
        or str(target)
    )
    return {
        "target": target_metadata(target),
        "exists": bool(intake),
        "project_name": project_name,
        "project_mode": draft_intake.get("project_mode") or intake.get("project_mode") or dashboard_state.get("project_mode") or "unknown",
        "intake": intake,
        "draft_intake": draft_intake,
        "dashboard_state": dashboard_state,
        "context_files": list(intake.get("additional_context_files") or []),
        "detected": detect_target_context(target),
    }


def command_brief_save_draft(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    state_path = write_dashboard_state_from_intake(target, intake, last_action="brief_draft_saved")
    return {
        "target": target_metadata(target),
        "dashboard_state_path": str(state_path),
        "intake": intake,
        "detected": detect_target_context(target),
    }


def context_record_to_dict(record: Any) -> dict[str, Any]:
    return {
        "rel_path": str(record.rel_path),
        "original_name": str(record.original_name),
        "size_bytes": int(record.size_bytes),
    }


def resolve_context_sources(raw_files: str) -> list[Path]:
    files = parse_json_arg(raw_files, label="files-json")
    if not isinstance(files, list):
        raise BackendError(
            "files-json must decode to a list of file paths.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "files-json"},
        )
    resolved: list[Path] = []
    for raw in files:
        path = Path(str(raw)).expanduser()
        try:
            source = path.resolve()
        except OSError as exc:
            raise BackendError(
                "Could not resolve context file path.",
                exit_code=2,
                error_type="invalid_context_file",
                details={"path": str(raw), "exception": str(exc)},
            ) from exc
        if not source.exists():
            raise BackendError(
                "Context file does not exist.",
                exit_code=2,
                error_type="invalid_context_file",
                details={"path": str(source)},
            )
        if not source.is_file():
            raise BackendError(
                "Context path must be a file.",
                exit_code=2,
                error_type="invalid_context_file",
                details={"path": str(source)},
            )
        resolved.append(source)
    return resolved


def merge_context_files(existing: Any, additions: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*normalize_string_list(existing), *additions]:
        if value not in merged:
            merged.append(value)
    return merged


def update_context_index(target: Path, project_name: str, records: list[Any], *, force: bool = False) -> Path | None:
    if not records:
        return None
    dashboard_app = load_dashboard_module()
    context_path = preferred_target_path(target, "docs/PROJECT_CONTEXT.md")
    context_index_existed = context_path.exists()
    if force or not context_index_existed:
        context_text = dashboard_app.render_project_context(project_name, records)
    else:
        existing_context = context_path.read_text(encoding="utf-8", errors="replace") if context_path.exists() else ""
        context_text = dashboard_app.upsert_context_imports(existing_context, project_name, records)
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(context_text, encoding="utf-8")
    return context_path


def command_context_import(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    context_sources = resolve_context_sources(args.files_json)
    dashboard_app = load_dashboard_module()
    logs: list[str] = []
    records = dashboard_app.copy_context_files(target, context_sources, logs.append)
    record_paths = [str(record.rel_path) for record in records]

    dashboard_state = load_dashboard_state(target)
    draft_intake = dashboard_state.get("brief_draft_intake")
    if not isinstance(draft_intake, dict):
        draft_intake = load_intake(target)
    project_name = str(args.project_name or draft_intake.get("project_name") or target.name or "New Project")
    if not draft_intake:
        draft_intake = {"project_name": project_name, "additional_context_files": []}
    context_path = update_context_index(target, project_name, records)

    intake_path = preferred_target_path(target, ".agentic/project_intake.json")
    if intake_path.exists():
        intake = load_intake(target)
        intake["additional_context_files"] = merge_context_files(intake.get("additional_context_files"), record_paths)
        write_json_file(intake_path, intake)

    draft_intake["additional_context_files"] = merge_context_files(draft_intake.get("additional_context_files"), record_paths)
    write_dashboard_state_from_intake(target, draft_intake, last_action="context_files_imported")

    return {
        "target": target_metadata(target),
        "records": [context_record_to_dict(record) for record in records],
        "imported_count": len(records),
        "project_context_path": str(context_path) if context_path else None,
        "dashboard_state_path": str(preferred_target_path(target, ".agentic/dashboard_state.json")),
        "log": logs,
    }


def run_required_file_check_for_intake(target: Path, intake: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        str(CHECK_REQUIRED_SCRIPT),
        "--human-bridge-mode",
        str(intake.get("human_bridge_mode") or "file_only"),
    ]
    if intake.get("write_worker_agents_allowed"):
        command.append("--write-workers-enabled")
    if intake.get("multi_role_automations_allowed"):
        command.append("--multi-role-enabled")
    if intake.get("automation_signals_enabled"):
        command.append("--automation-signals-enabled")
    if str(intake.get("automation_run_mode") or "") == "ticket_campaign":
        command.append("--ticket-campaign-enabled")
    if intake.get("optional_mcp_servers"):
        command.append("--optional-mcp-enabled")
    command.append(str(target))
    result = run_subprocess(command)
    result["status"] = "pass" if result["exit_code"] == 0 else "fail"
    return result


def scaffold_template_included(scaffold_module: Any, rel_path: str, values: dict[str, str]) -> bool:
    if values.get("HUMAN_BRIDGE_MODE") == "disabled" and rel_path in scaffold_module.HUMAN_BRIDGE_FILES:
        return False
    if values.get("AUTOMATION_SIGNALS_ENABLED") != "true" and rel_path in scaffold_module.AUTOMATION_SIGNAL_FILES:
        return False
    if values.get("AUTOMATION_RUN_MODE") != "ticket_campaign" and rel_path in scaffold_module.TICKET_RUN_FILES:
        return False
    if values.get("MULTI_ROLE_AUTOMATIONS_ALLOWED") != "true" and rel_path in scaffold_module.MULTI_ROLE_FILES:
        return False
    if values.get("MCP_ENABLED") != "true" and rel_path in scaffold_module.MCP_FILES:
        return False
    if values.get("PLAYWRIGHT_MCP_ENABLED") != "true" and rel_path in scaffold_module.PLAYWRIGHT_MCP_FILES:
        return False
    return True


def scaffold_file_preview(target: Path, intake: dict[str, Any], *, force: bool) -> list[dict[str, Any]]:
    scaffold_module = load_dashboard_module().load_scaffold_module()
    scaffold_intake = project_intake_payload(intake)
    values = scaffold_module.placeholders(scaffold_intake)
    mode = values.get("PROJECT_MODE", "fresh_project")
    records: list[dict[str, Any]] = []
    for template_path in sorted(scaffold_module.TEMPLATE_ROOT.rglob("*")):
        if template_path.is_dir():
            continue
        if "__pycache__" in template_path.parts or template_path.suffix == ".pyc":
            continue
        rel = template_path.relative_to(scaffold_module.TEMPLATE_ROOT)
        rel_path = rel.as_posix()
        if not scaffold_template_included(scaffold_module, rel_path, values):
            continue

        dest_rel = (
            scaffold_module.template_destination_rel(rel_path)
            if hasattr(scaffold_module, "template_destination_rel")
            else rel_path
        )
        dest = target / dest_rel
        exists = dest.exists()
        managed_kind = scaffold_module.MANAGED_EXISTING_PROJECT_FILES.get(rel_path)
        managed = False
        action = "create"
        detail = "Will create this target-local generated file."

        if mode == "existing_project" and managed_kind and exists:
            action = "managed_section_update"
            managed = True
            detail = f"Will update only the Diffmogger-managed {managed_kind} section and preserve surrounding content."
        elif mode == "existing_project" and managed_kind:
            managed = True
            detail = f"Will create this file with a Diffmogger-managed {managed_kind} section."
        elif exists and force:
            action = "overwrite"
            detail = "Will overwrite this scaffold-managed file because force is enabled."
        elif exists:
            if not dest_rel.startswith(".diffmogger/"):
                action = "conflict_requires_user_choice"
                detail = "A project-facing path already exists; Diffmogger will not silently overwrite or skip it."
            else:
                action = "skip_existing"
                detail = "Will not overwrite the existing sidecar file with force disabled."

        records.append(
            {
                "rel_path": dest_rel,
                "template_rel_path": rel_path,
                "path": str(dest),
                "exists": exists,
                "action": action,
                "managed_section": managed,
                "detail": detail,
            }
        )

    manifest = target / ".diffmogger" / "manifest.json"
    records.append(
        {
            "rel_path": ".diffmogger/manifest.json",
            "path": str(manifest),
            "exists": manifest.exists(),
            "action": "create" if not manifest.exists() else ("overwrite" if force else "skip_existing"),
            "managed_section": True,
            "detail": "Will write the sidecar ownership manifest used by runners, validation, and local excludes.",
        }
    )

    if (target / ".git").exists():
        exclude = target / ".git" / "info" / "exclude"
        records.append(
            {
                "rel_path": ".git/info/exclude",
                "path": str(exclude),
                "exists": exclude.exists(),
                "action": "update_local_exclude",
                "managed_section": True,
                "detail": "Will merge Diffmogger runtime ignore entries into the local git exclude file.",
            }
        )
    return records


def preview_summary(files: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for record in files:
        action = str(record.get("action") or "unknown")
        summary[action] = summary.get(action, 0) + 1
    return summary


def prereq_snapshot(target: Path, intake: dict[str, Any]) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    bridge_mode = str(intake.get("human_bridge_mode") or "file_only")
    optional_mcp = dashboard_app.optional_mcp_servers_from_value(intake.get("optional_mcp_servers"))
    items = dashboard_app.check_prerequisites(target, bridge_mode, optional_mcp)
    rows = [
        {
            "name": item.name,
            "ok": item.ok,
            "required": item.required,
            "detail": item.detail,
        }
        for item in items
    ]
    required_failures = [item for item in rows if item["required"] and not item["ok"]]
    advisory_warnings = [item for item in rows if not item["required"] and not item["ok"]]
    return {
        "status": "pass" if not required_failures else "fail",
        "items": rows,
        "required_failures": required_failures,
        "advisory_warnings": advisory_warnings,
    }


def git_warnings_from_detected(detected: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if detected.get("is_git_repo") and int(detected.get("git_dirty_count") or 0) > 0:
        warnings.append(
            {
                "type": "dirty_git",
                "level": "warning",
                "message": f"Git has {detected.get('git_dirty_count')} changed file(s). Review the working tree before scaffolding into an existing repo.",
            }
        )
    return warnings


def build_scaffold_preview(target: Path, intake: dict[str, Any], *, force: bool) -> dict[str, Any]:
    files = scaffold_file_preview(target, intake, force=force)
    detected = detect_target_context(target)
    prerequisites = prereq_snapshot(target, intake)
    warnings = git_warnings_from_detected(detected)
    warnings.extend(
        {
            "type": "missing_prerequisite",
            "level": "warning",
            "message": f"{item['name']}: {item['detail']}",
        }
        for item in prerequisites["required_failures"]
    )
    warnings.extend(
        {
            "type": "advisory_prerequisite",
            "level": "info",
            "message": f"{item['name']}: {item['detail']}",
        }
        for item in prerequisites["advisory_warnings"]
    )
    return {
        "target": target_metadata(target),
        "project_mode": str(intake.get("project_mode") or "fresh_project"),
        "force": force,
        "files": files,
        "summary": preview_summary(files),
        "warnings": warnings,
        "prerequisites": prerequisites,
        "detected": detected,
    }


def command_brief_scaffold_preview(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    return build_scaffold_preview(target, intake, force=bool(args.force))


def native_next_state_from_target(target: Path) -> dict[str, Any]:
    try:
        snapshot = build_observatory_snapshot(target)
    except BackendError as exc:
        return {
            "state": "READY_TO_RUN",
            "reason": f"Scaffold completed, but Observatory snapshot could not be built yet: {exc.message}",
            "first_review_status": "unknown",
            "task_status": "unknown",
        }
    first_review = snapshot.get("first_review") if isinstance(snapshot.get("first_review"), dict) else {}
    task = snapshot.get("task") if isinstance(snapshot.get("task"), dict) else {}
    first_review_status = str(first_review.get("status") or "unknown")
    if first_review_status != "ready":
        return {
            "state": "FIRST_REVIEW_NEEDED",
            "reason": first_review.get("summary") or "Scaffold completed; complete first-review readiness before leaving automation unattended.",
            "first_review_status": first_review_status,
            "task_status": task.get("status") or "unknown",
        }
    return {
        "state": "READY_TO_RUN",
        "reason": first_review.get("summary") or "Scaffold completed and first-review readiness is recorded.",
        "first_review_status": first_review_status,
        "task_status": task.get("status") or "unknown",
    }


def command_brief_scaffold_bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to scaffold into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )

    log_lines: list[dict[str, Any]] = []

    def log(stage: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        record = {
            "stage": stage,
            "level": level,
            "message": message,
            "data": data or {},
        }
        log_lines.append(record)
        stream_event(args, stage, message, level=level, data=data)

    log("preflight", "Building scaffold preview and prerequisite summary.")
    preflight = build_scaffold_preview(target, intake, force=bool(args.force))
    required_failures = list((preflight.get("prerequisites") or {}).get("required_failures") or [])
    if required_failures and bool(args.run_codex):
        log(
            "preflight",
            "Required prerequisites are missing; Codex bootstrap cannot start.",
            level="error",
            data={"required_failures": required_failures},
        )
        raise BackendError(
            "Required prerequisites are missing before Codex bootstrap.",
            error_type="prerequisites_failed",
            details={"required_failures": required_failures, "preflight": preflight, "log": log_lines[-12:]},
        )
    if required_failures:
        log(
            "preflight",
            "Required prerequisites are missing for full bootstrap; scaffold will continue without running Codex.",
            level="warning",
            data={"required_failures": required_failures},
        )

    log("state", "Writing target-local dashboard state.")
    state_path = write_dashboard_state_from_intake(target, intake, last_action="scaffold_bootstrap_started")
    intake_path = preferred_target_path(target, ".agentic/project_intake.json")
    intake_path.parent.mkdir(parents=True, exist_ok=True)
    scaffold_intake = project_intake_payload(intake)
    write_json_file(intake_path, scaffold_intake)
    log("state", f"Wrote {intake_path.relative_to(target)}.")

    scaffold_module = load_dashboard_module().load_scaffold_module()
    try:
        log("scaffold", "Rendering scaffold templates.")
        values = scaffold_module.placeholders(scaffold_intake)
        written = scaffold_module.scaffold(target, values, bool(args.force))
        log("scaffold", f"Scaffold wrote or updated {len(written)} file(s).")
        for path in written[:24]:
            log("scaffold", f"wrote {path.relative_to(target)}", data={"rel_path": str(path.relative_to(target))})
        if len(written) > 24:
            log("scaffold", f"... {len(written) - 24} more file(s).")
    except Exception as exc:
        log("scaffold", f"Scaffold generation failed: {exc}", level="error")
        raise BackendError(
            "Scaffold generation failed.",
            error_type="scaffold_failed",
            details={"target": str(target), "exception": str(exc), "log": log_lines[-20:]},
        ) from exc

    log("validation", "Running generated required-file validation.")
    required_files = run_required_file_check_for_intake(target, scaffold_intake)
    if required_files.get("stdout"):
        log("validation", str(required_files.get("stdout"))[:800], data={"exit_code": required_files.get("exit_code")})
    if required_files.get("stderr"):
        log("validation", str(required_files.get("stderr"))[:800], level="warning", data={"exit_code": required_files.get("exit_code")})
    if required_files["exit_code"] != 0:
        log("validation", "Required-file validation failed after scaffolding.", level="error")
        raise BackendError(
            "Required-file validation failed after scaffolding.",
            error_type="required_files_failed",
            details={**required_files, "log": log_lines[-20:]},
        )

    codex_result: dict[str, Any] = {
        "status": "skipped",
        "reason": "Codex bootstrap was not requested by this backend command.",
    }
    if bool(args.run_codex):
        log("bootstrap", "Starting Codex initial bootstrap run.")
        prompt_path = preferred_target_path(target, "docs/INITIAL_BOOTSTRAP_PROMPT.md")
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "Could not read the initial bootstrap prompt.",
                error_type="bootstrap_prompt_missing",
                details={"path": str(prompt_path), "exception": str(exc)},
            ) from exc
        codex_result = run_subprocess(
            ["codex", "exec", "--full-auto", "--skip-git-repo-check", prompt],
            cwd=target,
        )
        codex_result["status"] = "pass" if codex_result["exit_code"] == 0 else "fail"
        if codex_result.get("stdout"):
            log("bootstrap", str(codex_result.get("stdout"))[-1200:])
        if codex_result.get("stderr"):
            log("bootstrap", str(codex_result.get("stderr"))[-1200:], level="warning")
        if codex_result["exit_code"] != 0:
            log("bootstrap", "Codex bootstrap failed.", level="error", data={"exit_code": codex_result.get("exit_code")})
            raise BackendError(
                "Codex bootstrap failed.",
                error_type="codex_bootstrap_failed",
                details={**codex_result, "log": log_lines[-24:]},
            )
    else:
        log("bootstrap", "Skipped Codex initial bootstrap; Run controls can start automation after scaffold validation.")

    write_dashboard_state_from_intake(target, intake, last_action="bootstrap_completed")
    next_state = native_next_state_from_target(target)
    log("done", f"Scaffold pipeline completed: {next_state['state']}.", data=next_state)
    return {
        "target": target_metadata(target),
        "dashboard_state_path": str(state_path),
        "project_intake_path": str(intake_path),
        "written_files": [str(path.relative_to(target)) for path in written],
        "written_count": len(written),
        "required_files": required_files,
        "codex": codex_result,
        "preflight": preflight,
        "native_next_state": next_state,
        "log": log_lines,
        "log_excerpt": log_lines[-20:],
    }


def prereq_rows(items: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "ok": bool(item.ok),
            "required": bool(item.required),
            "category": "required" if bool(item.required) else "optional",
            "detail": item.detail,
        }
        for item in items
    ]


def effective_backend_path(dashboard_app: Any | None = None) -> str:
    native_path = os.environ.get("DIFFMOGGER_NATIVE_APP_PATH") or os.environ.get("PATH", "")
    explicit = os.environ.get("CODEX_AUTOMATION_PATH", "").strip()
    default_path = explicit
    if not default_path and dashboard_app is not None:
        default_path = str(getattr(dashboard_app, "DEFAULT_AUTOMATION_PATH", ""))
    if not default_path:
        default_path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    parts: list[str] = []
    seen: set[str] = set()
    for raw_path in [default_path, native_path]:
        for part in raw_path.split(os.pathsep):
            item = part.strip()
            if item and item not in seen:
                seen.add(item)
                parts.append(item)
    return os.pathsep.join(parts)


def tool_status(name: str, args: list[str], *, required: bool, path: str | None = None) -> dict[str, Any]:
    search_path = path or os.environ.get("PATH", "")
    resolved = shutil.which(name, path=search_path)
    if not resolved:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "path": "",
            "detail": f"{name} not found on PATH.",
        }
    try:
        result = subprocess.run(
            [resolved, *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=4,
            check=False,
            env={**os.environ, "PATH": search_path},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "path": resolved,
            "detail": str(exc),
        }
    detail = (result.stdout or result.stderr).strip().splitlines()
    first_detail = detail[0] if detail else resolved
    ok = result.returncode == 0
    if name == "python3":
        match = re.search(r"Python\s+(\d+)\.(\d+)(?:\.\d+)?", first_detail)
        if match:
            version_tuple = (int(match.group(1)), int(match.group(2)))
            if version_tuple < (3, 10):
                ok = False
                first_detail = f"{first_detail} (need Python 3.10+)."
    return {
        "name": name,
        "ok": ok,
        "required": required,
        "path": resolved,
        "detail": first_detail,
    }


def runtime_environment_snapshot(dashboard_app: Any | None = None) -> dict[str, Any]:
    dashboard_app = dashboard_app or load_dashboard_module()
    backend_path = effective_backend_path(dashboard_app)
    tools = [
        tool_status("python3", ["--version"], required=True, path=backend_path),
        tool_status("codex", ["--version"], required=True, path=backend_path),
        tool_status("bash", ["--version"], required=True, path=backend_path),
        tool_status("git", ["--version"], required=True, path=backend_path),
        tool_status("node", ["--version"], required=False, path=backend_path),
        tool_status("npm", ["--version"], required=False, path=backend_path),
        tool_status("npx", ["--version"], required=False, path=backend_path),
    ]
    return {
        "kit_root": str(KIT_ROOT),
        "backend_python": sys.executable,
        "backend_python_version": sys.version.split()[0],
        "native_app_path": os.environ.get("DIFFMOGGER_NATIVE_APP_PATH") or os.environ.get("PATH", ""),
        "effective_path": backend_path,
        "codex_automation_path_override": os.environ.get("CODEX_AUTOMATION_PATH", ""),
        "dotenv_loaded": bool(os.environ.get("DIFFMOGGER_BACKEND_DOTENV_LOADED")),
        "tools": tools,
    }


def setup_fix_suggestions(environment: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    environment = environment or runtime_environment_snapshot()
    tools = {str(item.get("name")): item for item in environment.get("tools", []) if isinstance(item, dict)}
    suggestions: list[dict[str, Any]] = []
    if not bool(tools.get("python3", {}).get("ok")):
        suggestions.append(
            {
                "id": "install-python",
                "title": "Install Homebrew Python",
                "detail": "Diffmogger's native backend needs Python 3.10 or newer.",
                "command": "brew install python",
            }
        )
    if not bool(tools.get("codex", {}).get("ok")):
        suggestions.append(
            {
                "id": "install-codex",
                "title": "Install and sign in to Codex CLI",
                "detail": "Run Codex once in Terminal so the native app and scheduled automation can reuse the same account.",
                "command": "npm install -g @openai/codex && codex",
            }
        )
    if not bool(tools.get("node", {}).get("ok")) or not bool(tools.get("npx", {}).get("ok")):
        suggestions.append(
            {
                "id": "install-node",
                "title": "Install Node for optional MCP integrations",
                "detail": "Node and npx are advisory unless Context7 or Playwright MCP are enabled.",
                "command": "brew install node",
            }
        )
    suggestions.append(
        {
            "id": "rerun-native-checks",
            "title": "Rerun native environment checks",
            "detail": "Use this exact backend command from the cloned Diffmogger repo to reproduce the native setup doctor.",
            "command": "python3 scripts/dashboard_backend_cli.py diagnostics.environment",
        }
    )
    return suggestions


def native_prerequisites(target: Path, dashboard_app: Any) -> list[Any]:
    items = dashboard_app.check_prerequisites(
        target,
        human_bridge_mode_from_state(target),
        optional_mcp_from_state(target, dashboard_app),
    )
    native_items: list[Any] = []
    for item in items:
        if item.name == LEGACY_TKINTER_CHECK:
            native_items.append(
                dashboard_app.PrerequisiteItem(
                    NATIVE_TKINTER_CHECK,
                    bool(item.ok),
                    False,
                    f"{item.detail} Required only for the old Tkinter dashboard, not for native backend commands.",
                )
            )
        else:
            native_items.append(item)
    return native_items


def target_multi_role_enabled(target: Path) -> bool:
    for data in (load_intake(target), load_dashboard_state(target)):
        if "multi_role_automations_allowed" in data:
            return bool(data.get("multi_role_automations_allowed"))
    for marker_path in [
        existing_or_target_path(target, ".agentic/automation_prompt.md"),
        existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"),
    ]:
        if marker_path.exists():
            text = marker_path.read_text(encoding="utf-8", errors="replace")
            if "Multi-role automations allowed: true" in text:
                return True
            if "Multi-role automations allowed: false" in text:
                return False
    return False


def target_ticket_campaign_enabled(target: Path) -> bool:
    for data in (load_intake(target), load_dashboard_state(target)):
        if str(data.get("automation_run_mode") or "") == "ticket_campaign":
            return True
    return False


def target_schedule_strategy(target: Path, dashboard_app: Any) -> str:
    multi_role_enabled = target_multi_role_enabled(target)
    for data in (load_dashboard_state(target), load_intake(target)):
        if "automation_schedule_strategy" in data:
            return dashboard_app.schedule_strategy_from_value(
                data.get("automation_schedule_strategy"),
                multi_role_enabled=multi_role_enabled,
            )
    return dashboard_app.schedule_strategy_from_value(None, multi_role_enabled=multi_role_enabled)


def target_allow_remotes(target: Path) -> bool:
    for data in (load_dashboard_state(target), load_intake(target)):
        if "multi_role_allow_remotes" in data:
            return bool(data.get("multi_role_allow_remotes"))
    return False


def target_cadence_seconds(target: Path, dashboard_app: Any) -> int:
    for data in (load_dashboard_state(target), load_intake(target)):
        if "cadence_minutes" in data:
            return dashboard_app.parse_cadence_seconds(str(data.get("cadence_minutes")))
        if "desired_cadence" in data:
            minutes = dashboard_app.cadence_minutes_from_text(data.get("desired_cadence"))
            return dashboard_app.parse_cadence_seconds(str(minutes))
    return dashboard_app.parse_cadence_seconds(str(dashboard_app.DEFAULT_CADENCE_MINUTES))


def target_git_remotes(target: Path) -> str:
    result = subprocess.run(
        ["git", "remote", "-v"],
        cwd=str(target),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return (result.stdout or result.stderr).strip() if result.returncode == 0 else ""


def automation_ready(target: Path, dashboard_app: Any) -> tuple[bool, str]:
    target = target.expanduser().resolve()
    strategy = target_schedule_strategy(target, dashboard_app)
    required = [
        existing_or_target_path(target, ".agentic/project_intake.json"),
        existing_or_target_path(target, ".agentic/automation_prompt.md"),
        existing_or_target_path(target, "docs/INITIAL_BOOTSTRAP_PROMPT.md"),
        existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"),
        target_script_path(target, "scripts/run_codex_automation.sh"),
    ]
    if strategy == dashboard_app.SCHEDULE_STRATEGY_CONVEYOR:
        required.extend(
            [
                target_script_path(target, "scripts/run_conveyor_automation.sh"),
                target_script_path(target, "scripts/run_conveyor_automation.py"),
            ]
        )
    if target_multi_role_enabled(target):
        required.extend(
            [
                existing_or_target_path(target, ".agentic/roles/planner.md"),
                existing_or_target_path(target, ".agentic/roles/builder.md"),
                existing_or_target_path(target, ".agentic/roles/hardener.md"),
                existing_or_target_path(target, ".agentic/roles/integrator.md"),
                existing_or_target_path(target, "docs/MULTI_ROLE_PROGRESS.md"),
                target_script_path(target, "scripts/run_role_automation.sh"),
                target_script_path(target, "scripts/integrate_role_outputs.py"),
                target_script_path(target, "scripts/list_deferred_patches.py"),
            ]
        )
    if target_ticket_campaign_enabled(target):
        required.append(existing_or_target_path(target, "docs/TICKET_RUN.md"))
    missing = [path.relative_to(target).as_posix() for path in required if not path.exists()]
    if missing:
        return False, "Missing " + ", ".join(missing)
    requires_initial_commit = (
        target_multi_role_enabled(target)
        or strategy == dashboard_app.SCHEDULE_STRATEGY_CONVEYOR
    )
    if requires_initial_commit and not dashboard_app.target_has_initial_commit(target):
        return False, "Multi-role or conveyor scheduling requires an initialized git repo with an initial commit."
    task_path = existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
    task_text = task_path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    if "Current baseline: not bootstrapped yet" in task_text:
        return False, "Bootstrap has not completed yet."
    status_match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", task_text, re.MULTILINE)
    if not status_match:
        return False, f"Missing AUTOMATION_STATUS in {task_path.relative_to(target)}."
    status = status_match.group(1).strip().upper()
    if status not in dashboard_app.SCHEDULABLE_STATUSES:
        return False, f"Automation status is {status}; scheduling requires ACTIVE or ACTIVE_WITH_PENDING_USER_INPUT."
    return True, "Ready."


def run_once_ready(target: Path, dashboard_app: Any) -> tuple[bool, str]:
    target = target.expanduser().resolve()
    required = [
        existing_or_target_path(target, ".agentic/automation_prompt.md"),
        existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"),
        target_script_path(target, "scripts/run_codex_automation.sh"),
    ]
    missing = [path.relative_to(target).as_posix() for path in required if not path.exists()]
    if missing:
        return False, "Missing " + ", ".join(missing)
    task_path = existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
    task_text = task_path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    status_match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", task_text, re.MULTILINE)
    if not status_match:
        return False, f"Missing AUTOMATION_STATUS in {task_path.relative_to(target)}."
    status = status_match.group(1).strip().upper()
    if status not in dashboard_app.SCHEDULABLE_STATUSES:
        return False, f"Automation status is {status}; run-once requires ACTIVE or ACTIVE_WITH_PENDING_USER_INPUT."
    return True, "Ready."


def launchd_loaded(label: str, dashboard_app: Any) -> bool:
    if sys.platform != "darwin":
        return False
    result = subprocess.run(
        ["launchctl", "print", dashboard_app.launchd_service_target(label)],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return result.returncode == 0


def launchd_disabled(label: str, dashboard_app: Any) -> bool:
    if sys.platform != "darwin":
        return False
    result = subprocess.run(
        ["launchctl", "print-disabled", dashboard_app.launchd_domain_target()],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return False
    return launchd_disabled_in_output(result.stdout or result.stderr, label)


def launchd_disabled_in_output(output: str, label: str) -> bool:
    return re.search(rf'"{re.escape(label)}"\s*=>\s*(?:true|disabled)\b', output) is not None


def path_equals_or_lives_under_target(raw: Any, target: Path) -> bool:
    if not raw:
        return False
    try:
        candidate = Path(str(raw)).expanduser().resolve()
    except OSError:
        candidate = Path(str(raw)).expanduser()
    return candidate == target or target in candidate.parents


def launchd_plist_targets_project(payload: dict[str, Any], target: Path) -> bool:
    if path_equals_or_lives_under_target(payload.get("WorkingDirectory"), target):
        return True
    environment = payload.get("EnvironmentVariables")
    if isinstance(environment, dict) and path_equals_or_lives_under_target(environment.get("TARGET"), target):
        return True
    arguments = payload.get("ProgramArguments")
    if isinstance(arguments, list):
        return any(path_equals_or_lives_under_target(argument, target) for argument in arguments)
    return False


def launchctl(args: list[str], dashboard_app: Any, *, allow_failure: bool = False) -> dict[str, Any]:
    result = run_subprocess(["launchctl", *args])
    if result["exit_code"] != 0 and not allow_failure:
        message = str(result.get("stderr") or result.get("stdout") or "launchctl failed")
        raise BackendError(
            message,
            error_type="launchctl_failed",
            details={"launchctl_args": args, "result": result},
        )
    result["service_target"] = args[0] if args else dashboard_app.launchd_domain_target()
    return result


def schedule_labels(target: Path, dashboard_app: Any) -> list[str]:
    strategy = target_schedule_strategy(target, dashboard_app)
    if strategy == dashboard_app.SCHEDULE_STRATEGY_CONVEYOR:
        return [dashboard_app.launchd_conveyor_label(target)]
    if strategy == dashboard_app.SCHEDULE_STRATEGY_FIXED_MULTI_ROLE and target_multi_role_enabled(target):
        return [dashboard_app.launchd_role_label(target, role) for role in dashboard_app.MULTI_ROLE_ROLES]
    return [dashboard_app.launchd_label(target)]


def all_schedule_labels(target: Path, dashboard_app: Any) -> list[str]:
    return [
        dashboard_app.launchd_label(target),
        dashboard_app.launchd_conveyor_label(target),
        *[dashboard_app.launchd_role_label(target, role) for role in dashboard_app.MULTI_ROLE_ROLES],
    ]


def managed_schedule_entries(target: Path, dashboard_app: Any) -> list[dict[str, Any]]:
    expected_labels = all_schedule_labels(target, dashboard_app)
    helper = getattr(dashboard_app, "managed_launchd_entries", None)
    if callable(helper):
        entries = helper(target, expected_labels)
        return [
            {
                "label": str(entry["label"]),
                "plist_path": Path(entry["plist_path"]),
            }
            for entry in entries
            if str(entry.get("label") or "").strip()
        ]

    target = target.expanduser().resolve()
    records: dict[str, Path] = {
        label: dashboard_app.launchd_plist_path(label)
        for label in expected_labels
    }
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    prefix = getattr(dashboard_app, "LAUNCHD_LABEL_PREFIX", "com.diffmogger.automation")
    if launch_dir.exists():
        for plist_path in sorted(launch_dir.glob(f"{prefix}*.plist")):
            try:
                payload = plistlib.loads(plist_path.read_bytes())
            except (OSError, plistlib.InvalidFileException):
                continue
            if not isinstance(payload, dict) or not launchd_plist_targets_project(payload, target):
                continue
            label = str(payload.get("Label") or plist_path.stem).strip()
            if label:
                records.setdefault(label, plist_path)
    return [
        {"label": label, "plist_path": plist_path}
        for label, plist_path in records.items()
    ]


def schedule_prerequisites(target: Path, dashboard_app: Any) -> list[Any]:
    items = native_prerequisites(target, dashboard_app)
    launchctl_path = shutil.which("launchctl") if sys.platform == "darwin" else None
    items.append(
        dashboard_app.PrerequisiteItem(
            "launchctl available for scheduled automation",
            bool(launchctl_path),
            True,
            launchctl_path or "launchctl is required for dashboard-managed schedules on macOS.",
        )
    )
    strategy = target_schedule_strategy(target, dashboard_app)
    requires_initial_commit = (
        target_multi_role_enabled(target)
        or strategy == dashboard_app.SCHEDULE_STRATEGY_CONVEYOR
    )
    if requires_initial_commit:
        has_initial_commit = dashboard_app.target_has_initial_commit(target)
        items.append(
            dashboard_app.PrerequisiteItem(
                "Initial git commit for scheduled automation",
                has_initial_commit,
                True,
                "Target has an initial git commit."
                if has_initial_commit
                else "Run `git init`, `git add .`, and `git commit -m 'chore: initial commit'` before starting multi-role or conveyor scheduling.",
            )
        )
    if (
        human_bridge_mode_from_state(target) in {"local_notifier", "discord_notifier"}
        and bool(load_dashboard_state(target).get("local_notifications_enabled", True))
    ):
        osascript_path = shutil.which("osascript")
        items.append(
            dashboard_app.PrerequisiteItem(
                "macOS desktop notifications",
                bool(osascript_path),
                False,
                osascript_path
                or f"osascript unavailable; notifier delivery will record LOCAL_NOTIFICATION_FAILED in {sidecar_rel('docs/HUMAN_OUTBOX.md')}.",
            )
        )
    return items


def schedule_status_snapshot(target: Path, dashboard_app: Any) -> dict[str, Any]:
    ready, ready_reason = automation_ready(target, dashboard_app)
    entries = managed_schedule_entries(target, dashboard_app)
    labels = [str(entry["label"]) for entry in entries]
    active_labels = schedule_labels(target, dashboard_app)
    loaded_labels = [label for label in labels if launchd_loaded(label, dashboard_app)]
    existing_entries = [entry for entry in entries if Path(entry["plist_path"]).exists()]
    existing_plists = [Path(entry["plist_path"]) for entry in existing_entries]
    disabled_labels = [label for label in labels if launchd_disabled(label, dashboard_app)]
    strategy = target_schedule_strategy(target, dashboard_app)
    strategy_label = dashboard_app.SCHEDULE_STRATEGY_LABELS.get(strategy, strategy)
    display_labels = loaded_labels or [str(entry["label"]) for entry in existing_entries] or active_labels
    if sys.platform != "darwin":
        state = "unavailable"
        message = "Schedule controls require macOS launchd."
    elif loaded_labels:
        state = "running"
        message = "Schedule is running via launchd."
    elif existing_plists and disabled_labels:
        state = "paused"
        message = "Schedule is paused and disabled."
    elif existing_plists:
        state = "installed"
        message = "Schedule plist exists but is not loaded."
    elif ready:
        state = "not_installed"
        message = f"Schedule is ready to start ({strategy_label})."
    else:
        state = "not_ready"
        message = f"Schedule is not ready. {ready_reason}"
    return {
        "state": state,
        "message": message,
        "platform": sys.platform,
        "strategy": strategy,
        "strategy_label": strategy_label,
        "cadence_seconds": target_cadence_seconds(target, dashboard_app),
        "active_labels": display_labels,
        "loaded_labels": loaded_labels,
        "disabled_labels": disabled_labels,
        "plist_paths": [str(path) for path in existing_plists],
        "log_dir": str(dashboard_app.launchd_log_dir(target)),
        "ready": ready,
        "ready_reason": ready_reason,
        "can_start": sys.platform == "darwin" and ready,
        "can_pause": sys.platform == "darwin" and bool(loaded_labels),
        "can_remove": sys.platform == "darwin" and bool(loaded_labels or existing_plists),
    }


def latest_run_log(target: Path, dashboard_app: Any, *, max_lines: int = 160) -> dict[str, Any]:
    log_dir = dashboard_app.launchd_log_dir(target)
    candidates: list[Path] = []
    if log_dir.exists():
        candidates.extend(path for path in log_dir.glob("*.log") if path.is_file())
    if not candidates:
        return {
            "exists": False,
            "path": None,
            "rel_path": None,
            "modified_at": None,
            "content": "",
            "lines": [],
            "truncated": False,
        }
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    text, truncated = read_text_file(latest, max_bytes=120_000)
    raw_lines = text.splitlines()[-max_lines:]
    modified_at = mtime_iso(latest)
    return {
        "exists": True,
        "path": str(latest),
        "rel_path": latest.relative_to(target).as_posix() if latest.is_relative_to(target) else str(latest),
        "modified_at": modified_at,
        "content": "\n".join(raw_lines),
        "lines": [{"timestamp": modified_at, "text": line} for line in raw_lines],
        "truncated": truncated or len(text.splitlines()) > max_lines,
    }


def worker_controls_snapshot(target: Path, dashboard_app: Any, strategy: dict[str, Any]) -> dict[str, Any]:
    name = compact_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    worker_helper_exists = target_script_path(target, "scripts/spawn_worker_agent.sh").exists()
    integrator_helper_exists = (
        target_script_path(target, "scripts/run_role_automation.sh").exists()
        and existing_or_target_path(target, ".agentic/roles/integrator.md").exists()
    )
    return {
        "strategy": name,
        "worker_helper_exists": worker_helper_exists,
        "integrator_helper_exists": integrator_helper_exists,
        "can_run_read_only": worker_helper_exists and name in dashboard_app.WORKER_REPORT_STRATEGIES,
        "can_run_write": worker_helper_exists and name == "WRITE_WORKERS",
        "can_run_integrator": integrator_helper_exists and name == "INTEGRATION_ONLY",
        "read_only_reason": "Supported by current worker strategy." if worker_helper_exists and name in dashboard_app.WORKER_REPORT_STRATEGIES else f"Current strategy is {name}.",
        "write_reason": "Supported by current worker strategy." if worker_helper_exists and name == "WRITE_WORKERS" else f"Current strategy is {name}.",
        "integrator_reason": "Supported by current worker strategy." if integrator_helper_exists and name == "INTEGRATION_ONLY" else f"Current strategy is {name}.",
    }


def run_controls_snapshot(target: Path, dashboard_app: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    ready, ready_reason = run_once_ready(target, dashboard_app)
    active_role_run = snapshot.get("conveyor", {}).get("active_role_run") if isinstance(snapshot.get("conveyor"), dict) else {}
    is_running = bool(active_role_run)
    schedule = schedule_status_snapshot(target, dashboard_app)
    return {
        "is_scaffolded": target_metadata(target)["automation_task_exists"],
        "is_running": is_running,
        "can_run_now": ready and not is_running,
        "run_now_reason": "Ready." if ready and not is_running else ("A role run is already active." if is_running else ready_reason),
        "can_start_schedule": bool(schedule.get("can_start")) and not is_running,
        "start_schedule_reason": schedule.get("message"),
        "can_pause_schedule": bool(schedule.get("can_pause")),
        "pause_schedule_reason": schedule.get("message"),
        "can_remove_schedule": bool(schedule.get("can_remove")) and not is_running,
        "remove_schedule_reason": "A role run is already active." if is_running else schedule.get("message"),
        "can_run_safety_check": True,
        "can_export_review": target_metadata(target)["automation_task_exists"],
    }


def run_subprocess_streamed(
    args: argparse.Namespace,
    command: list[str],
    *,
    cwd: Path,
    stage: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    stream_event(args, stage, "$ " + shlex.join(str(part) for part in command), data={"cwd": str(cwd)})
    lines: list[str] = []
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise BackendError(
            "Could not start backend command.",
            error_type="process_start_failed",
            details={"command": command, "cwd": str(cwd), "exception": str(exc)},
        ) from exc
    assert process.stdout is not None
    for line in process.stdout:
        text = line.rstrip("\n")
        lines.append(text)
        stream_event(args, stage, text)
    exit_code = process.wait()
    stream_event(
        args,
        stage,
        f"Command exited with code {exit_code}.",
        level="info" if exit_code == 0 else "error",
        data={"exit_code": exit_code},
    )
    return {
        "command": shlex.join(str(part) for part in command),
        "exit_code": exit_code,
        "stdout": "\n".join(lines).strip(),
        "stderr": "",
    }


def command_run_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    snapshot = build_observatory_snapshot(target)
    strategy = snapshot.get("worker_strategy") if isinstance(snapshot.get("worker_strategy"), dict) else {}
    schedule = schedule_status_snapshot(target, dashboard_app)
    controls = run_controls_snapshot(target, dashboard_app, snapshot)
    prerequisites = schedule_prerequisites(target, dashboard_app)
    environment_blockers = [
        row for row in prereq_rows(prerequisites)
        if row["required"] and not row["ok"]
    ]
    latest_worker_result = dashboard_app.latest_worker_result(target)
    return {
        "target": target_metadata(target),
        "task": snapshot.get("task") or {},
        "human": snapshot.get("human") or {},
        "git": snapshot.get("git") or {},
        "queue": snapshot.get("queue") or {},
        "conveyor": snapshot.get("conveyor") or {},
        "progress": snapshot.get("progress") or {},
        "signals": snapshot.get("signals") or {},
        "scorecard": snapshot.get("scorecard") or {},
        "first_review": snapshot.get("first_review") or {},
        "follow_through": snapshot.get("follow_through") or {},
        "recommendation_history": snapshot.get("recommendation_history") or {},
        "worker_strategy": snapshot.get("worker_strategy") or {},
        "review": snapshot.get("review") or {},
        "baseline_verification": snapshot.get("baseline_verification") or {},
        "progress_recent": snapshot.get("progress_recent"),
        "empty_states": snapshot.get("empty_states") or {},
        "logs": snapshot.get("logs") or [],
        "controls": controls,
        "schedule": schedule,
        "run_log": latest_run_log(target, dashboard_app),
        "worker_controls": worker_controls_snapshot(target, dashboard_app, strategy),
        "latest_worker_result": latest_worker_result,
        "environment_blockers": environment_blockers,
        "snapshot_generated_at": snapshot.get("generated_at"),
    }


def command_run_load_log(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    return {
        "target": target_metadata(target),
        "run_log": latest_run_log(target, dashboard_app, max_lines=500),
    }


def command_run_once(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    ready, reason = run_once_ready(target, dashboard_app)
    if not ready:
        raise BackendError(
            "Automation is not ready to run.",
            error_type="automation_not_ready",
            details={"reason": reason},
        )
    command = ["bash", str(target_script_path(target, "scripts/run_codex_automation.sh"))]
    env = {**os.environ, **dashboard_app.automation_environment(target)}
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_subprocess_streamed(args, command, cwd=target, stage="run", env=env)
    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_dashboard_action_state(
        target,
        last_action="run_once_completed" if result["exit_code"] == 0 else "run_once_failed",
        updates={
            "last_run_once_started_at": started_at,
            "last_run_once_finished_at": finished_at,
            "last_run_once_exit_code": result["exit_code"],
        },
    )
    return {
        "target": target_metadata(target),
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "started_at": started_at,
        "finished_at": finished_at,
        "result": result,
        "run_log": latest_run_log(target, dashboard_app),
    }


def command_schedule_start(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    if sys.platform != "darwin":
        raise BackendError(
            "Scheduled automation from the dashboard currently requires macOS launchd.",
            error_type="launchd_unavailable",
        )
    ready, reason = automation_ready(target, dashboard_app)
    if not ready:
        raise BackendError(
            "Automation is not ready to schedule.",
            error_type="automation_not_ready",
            details={"reason": reason},
        )
    items = schedule_prerequisites(target, dashboard_app)
    failures = dashboard_app.required_failures(items)
    if failures:
        raise BackendError(
            "Fix required prerequisites before starting scheduled automation.",
            error_type="prerequisites_failed",
            details={"failures": prereq_rows(failures)},
        )
    strategy = target_schedule_strategy(target, dashboard_app)
    allow_remotes = target_allow_remotes(target)
    multi_role_enabled = target_multi_role_enabled(target)
    remotes = target_git_remotes(target) if multi_role_enabled else ""
    if (
        remotes
        and strategy in {dashboard_app.SCHEDULE_STRATEGY_FIXED_MULTI_ROLE, dashboard_app.SCHEDULE_STRATEGY_CONVEYOR}
        and not allow_remotes
    ):
        raise BackendError(
            "Multi-role remote opt-in is required before starting this schedule.",
            error_type="remote_opt_in_required",
            details={"remotes": remotes},
        )
    log: list[dict[str, Any]] = []

    def record(message: str, data: dict[str, Any] | None = None) -> None:
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "message": message, "data": data or {}}
        log.append(payload)
        stream_event(args, "schedule", message, data=data)

    for entry in managed_schedule_entries(target, dashboard_app):
        label = str(entry["label"])
        plist_path = Path(entry["plist_path"])
        if launchd_loaded(label, dashboard_app):
            result = launchctl(["bootout", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
            if result["exit_code"] != 0:
                launchctl(["bootout", dashboard_app.launchd_domain_target(), str(plist_path)], dashboard_app, allow_failure=True)
        if plist_path.exists():
            launchctl(["disable", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)

    if strategy == dashboard_app.SCHEDULE_STRATEGY_CONVEYOR:
        label, plist_path = dashboard_app.write_conveyor_launchd_plist(target, allow_remotes=allow_remotes)
        launchctl(["enable", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
        launchctl(["bootstrap", dashboard_app.launchd_domain_target(), str(plist_path)], dashboard_app)
        launchctl(["enable", dashboard_app.launchd_service_target(label)], dashboard_app)
        record(f"Started continuous conveyor automation: {label}.", {"plist": str(plist_path)})
    elif strategy == dashboard_app.SCHEDULE_STRATEGY_FIXED_MULTI_ROLE and multi_role_enabled:
        if not dashboard_app.target_has_initial_commit(target):
            raise BackendError(
                "Multi-role scheduling requires an initialized git repo with an initial commit.",
                error_type="initial_commit_required",
            )
        loaded: list[str] = []
        for role in dashboard_app.MULTI_ROLE_ROLES:
            label, plist_path = dashboard_app.write_role_launchd_plist(target, role, allow_remotes=allow_remotes)
            launchctl(["enable", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
            launchctl(["bootstrap", dashboard_app.launchd_domain_target(), str(plist_path)], dashboard_app)
            launchctl(["enable", dashboard_app.launchd_service_target(label)], dashboard_app)
            loaded.append(label)
            record(f"LaunchAgent: {plist_path}", {"label": label})
        record("Started scheduled multi-role automation.", {"labels": loaded})
    else:
        interval = target_cadence_seconds(target, dashboard_app)
        label, plist_path = dashboard_app.write_launchd_plist(target, interval)
        launchctl(["enable", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
        if launchd_loaded(label, dashboard_app):
            launchctl(["bootout", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
            launchctl(["bootout", dashboard_app.launchd_domain_target(), str(plist_path)], dashboard_app, allow_failure=True)
        launchctl(["bootstrap", dashboard_app.launchd_domain_target(), str(plist_path)], dashboard_app)
        launchctl(["enable", dashboard_app.launchd_service_target(label)], dashboard_app)
        record(
            f"Started scheduled automation: {label} ({dashboard_app.format_interval(interval)}).",
            {"plist": str(plist_path), "interval_seconds": interval},
        )
    write_dashboard_action_state(target, last_action="schedule_started")
    return {
        "target": target_metadata(target),
        "schedule": schedule_status_snapshot(target, dashboard_app),
        "log": log,
        "log_dir": str(dashboard_app.launchd_log_dir(target)),
    }


def command_schedule_pause(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    if sys.platform != "darwin":
        raise BackendError(
            "Scheduled automation from the dashboard currently requires macOS launchd.",
            error_type="launchd_unavailable",
    )
    log: list[dict[str, Any]] = []
    entries = managed_schedule_entries(target, dashboard_app)
    loaded_entries = [
        entry
        for entry in entries
        if launchd_loaded(str(entry["label"]), dashboard_app)
    ]
    found = bool(loaded_entries)
    for entry in loaded_entries:
        label = str(entry["label"])
        plist_path = Path(entry["plist_path"])
        result = launchctl(["bootout", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
        if result["exit_code"] != 0:
            launchctl(["bootout", dashboard_app.launchd_domain_target(), str(plist_path)], dashboard_app, allow_failure=True)
        launchctl(["disable", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
        message = f"Paused and disabled scheduled automation: {label}."
        log.append({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "message": message})
        stream_event(args, "schedule", message)
    if not found:
        stream_event(args, "schedule", "Scheduled automation is not currently running.", level="warning")
    write_dashboard_action_state(target, last_action="schedule_paused")
    return {
        "target": target_metadata(target),
        "schedule": schedule_status_snapshot(target, dashboard_app),
        "found": found,
        "log": log,
    }


def command_schedule_remove(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    if sys.platform != "darwin":
        raise BackendError(
            "Scheduled automation from the dashboard currently requires macOS launchd.",
            error_type="launchd_unavailable",
        )
    log: list[dict[str, Any]] = []
    removed: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []

    def record(message: str, data: dict[str, Any] | None = None, *, level: str = "info") -> None:
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "message": message, "data": data or {}}
        log.append(payload)
        stream_event(args, "schedule", message, level=level, data=data)

    for entry in managed_schedule_entries(target, dashboard_app):
        label = str(entry["label"])
        plist_path = Path(entry["plist_path"])
        if launchd_loaded(label, dashboard_app):
            result = launchctl(["bootout", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
            if result["exit_code"] != 0:
                launchctl(["bootout", dashboard_app.launchd_domain_target(), str(plist_path)], dashboard_app, allow_failure=True)
        launchctl(["disable", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
        launchctl(["enable", dashboard_app.launchd_service_target(label)], dashboard_app, allow_failure=True)
        if plist_path.exists():
            try:
                plist_path.unlink()
            except OSError as exc:
                raise BackendError(
                    "Could not delete a scheduled automation LaunchAgent plist.",
                    error_type="schedule_remove_failed",
                    details={"label": label, "plist": str(plist_path), "exception": str(exc)},
                ) from exc
            record(f"Removed scheduled automation LaunchAgent: {plist_path}", {"label": label, "plist": str(plist_path)})
            removed.append({"label": label, "plist": str(plist_path)})
        else:
            missing.append({"label": label, "plist": str(plist_path)})
    if not removed:
        record("Scheduled automation plist was not found.", {"missing": missing}, level="warning")
    write_dashboard_action_state(target, last_action="schedule_removed")
    return {
        "target": target_metadata(target),
        "schedule": schedule_status_snapshot(target, dashboard_app),
        "removed": removed,
        "missing": missing,
        "removed_count": len(removed),
        "log": log,
    }


def command_safety_run_check(args: argparse.Namespace) -> dict[str, Any]:
    selected_target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    check_target = dashboard_app.resolve_integration_safety_target(selected_target)
    if check_target == KIT_ROOT and not dashboard_app.has_integration_safety_tree(selected_target):
        stream_event(
            args,
            "safety",
            "Selected target does not include starter-kit integration files; checking the Diffmogger kit source instead.",
            level="warning",
        )
    command = dashboard_app.integration_safety_command(check_target)
    result = run_subprocess_streamed(args, command, cwd=KIT_ROOT, stage="safety")
    try:
        record_path = dashboard_app.write_integration_safety_record(
            selected_target,
            check_target,
            command,
            int(result["exit_code"]),
        )
    except OSError as exc:
        raise BackendError(
            "Could not record integration safety result.",
            error_type="safety_record_failed",
            details={"target": str(selected_target), "exception": str(exc)},
        ) from exc
    write_dashboard_action_state(
        selected_target,
        last_action="safety_check_completed" if result["exit_code"] == 0 else "safety_check_failed",
        updates={"last_safety_check_exit_code": result["exit_code"]},
    )
    return {
        "target": target_metadata(selected_target),
        "checked_target": str(check_target),
        "record_path": str(record_path),
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "result": result,
    }


def command_worker_run_read_only(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    strategy = dashboard_app.dashboard_worker_strategy(target)
    name = compact_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    if name not in dashboard_app.WORKER_REPORT_STRATEGIES:
        raise BackendError(
            "A read-only worker is not supported by the current worker strategy.",
            error_type="worker_not_supported",
            details={"strategy": name},
        )
    run_id = dashboard_app.dashboard_run_id("dashboard-worker-report")
    result = run_subprocess_streamed(
        args,
        dashboard_app.read_only_worker_command(target, strategy, run_id=run_id),
        cwd=target,
        stage="worker",
    )
    summary = run_subprocess_streamed(
        args,
        dashboard_app.worker_summary_command(target, run_id),
        cwd=target,
        stage="worker-summary",
    )
    write_dashboard_action_state(target, last_action="read_only_worker_completed", updates={"last_worker_run_id": run_id})
    return {
        "target": target_metadata(target),
        "run_id": run_id,
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "strategy": strategy,
        "result": result,
        "summary": summary,
        "latest_worker_result": dashboard_app.latest_worker_result(target),
    }


def command_worker_run_write(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    strategy = dashboard_app.dashboard_worker_strategy(target)
    name = compact_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    if name != "WRITE_WORKERS":
        raise BackendError(
            "A write worker is not supported by the current worker strategy.",
            error_type="worker_not_supported",
            details={"strategy": name},
        )
    try:
        ownership = dashboard_app.normalize_worker_ownership_scope(args.ownership)
    except ValueError as exc:
        raise BackendError(str(exc), exit_code=2, error_type="invalid_ownership") from exc
    run_id = dashboard_app.dashboard_run_id("dashboard-write-worker")
    result = run_subprocess_streamed(
        args,
        dashboard_app.write_worker_command(target, strategy, ownership, run_id=run_id),
        cwd=target,
        stage="worker",
    )
    summary = run_subprocess_streamed(
        args,
        dashboard_app.worker_summary_command(target, run_id),
        cwd=target,
        stage="worker-summary",
    )
    write_dashboard_action_state(target, last_action="write_worker_completed", updates={"last_worker_run_id": run_id})
    return {
        "target": target_metadata(target),
        "run_id": run_id,
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "strategy": strategy,
        "ownership": ownership,
        "result": result,
        "summary": summary,
        "latest_worker_result": dashboard_app.latest_worker_result(target),
    }


def command_worker_run_integrator(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    strategy = dashboard_app.dashboard_worker_strategy(target)
    name = compact_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    if name != "INTEGRATION_ONLY":
        raise BackendError(
            "Integrator launch is not supported by the current worker strategy.",
            error_type="worker_not_supported",
            details={"strategy": name},
        )
    run_id = dashboard_app.dashboard_run_id("dashboard-integrator")
    result = run_subprocess_streamed(
        args,
        dashboard_app.integration_only_command(target, run_id=run_id),
        cwd=target,
        stage="worker",
    )
    write_dashboard_action_state(target, last_action="integrator_worker_completed", updates={"last_worker_run_id": run_id})
    return {
        "target": target_metadata(target),
        "run_id": run_id,
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "strategy": strategy,
        "result": result,
    }


def command_project_load_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    brief = command_brief_load(args)
    run = command_run_load(args)
    dashboard_app = load_dashboard_module()
    files = [
        describe_registered_file(target, record)
        for record in file_registry(dashboard_app).values()
    ]
    return {
        "target": target_metadata(target),
        "brief": brief,
        "run": run,
        "files": files,
        "home": {
            "title": str(brief.get("project_name") or target.name),
            "automation_status": (run.get("task") or {}).get("status") or "UNKNOWN",
            "current_horizon": (run.get("task") or {}).get("horizon") or "unknown",
            "next_action": ((run.get("scorecard") or {}).get("action_plan") or {}).get("recommendation")
            or (run.get("task") or {}).get("suggested_next_task")
            or "No next action recorded yet.",
            "pending_human_requests": int((run.get("human") or {}).get("pending_requests", 0) or 0),
            "unhandled_inbox": int((run.get("human") or {}).get("unhandled_inbox", 0) or 0),
            "queued_patches": int(((run.get("queue") or {}).get("totals") or {}).get("queued", 0) or 0),
            "deferred_patches": int(((run.get("queue") or {}).get("totals") or {}).get("deferred", 0) or 0),
        },
    }


def launchagent_recent_projects() -> list[dict[str, Any]]:
    dashboard_app = load_dashboard_module()
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    if launch_dir.exists():
        for plist_path in sorted(launch_dir.glob(f"{dashboard_app.LAUNCHD_LABEL_PREFIX}*.plist")):
            try:
                payload = plistlib.loads(plist_path.read_bytes())
            except (OSError, plistlib.InvalidFileException):
                continue
            target = str(payload.get("WorkingDirectory") or "").strip()
            if not target or target in seen:
                continue
            seen.add(target)
            records.append(
                {
                    "target": target,
                    "source": "launchagent",
                    "label": payload.get("Label") or plist_path.stem,
                    "plist": str(plist_path),
                    "modified_at": mtime_iso(plist_path),
                }
            )
    env_value = os.environ.get("DIFFMOGGER_RECENT_PROJECTS", "")
    for raw in [item for item in env_value.split(os.pathsep) if item.strip()]:
        target = str(Path(raw).expanduser())
        if target in seen:
            continue
        seen.add(target)
        records.append({"target": target, "source": "environment", "label": Path(target).name})
    return records


def command_project_list_recent(_args: argparse.Namespace) -> dict[str, Any]:
    return {"projects": launchagent_recent_projects()}


def generate_observatory_html(target: Path, review_dir: Path) -> dict[str, Any]:
    module = load_observatory_module()
    snapshot = build_observatory_snapshot(target)
    html = module.render_html(snapshot, live=False)
    output = review_dir / DEFAULT_REVIEW_HTML
    try:
        output.write_text(html, encoding="utf-8")
    except OSError as exc:
        raise BackendError(
            "Could not write Observatory HTML.",
            error_type="write_failed",
            details={"path": str(output), "exception": str(exc)},
        ) from exc
    return {
        "target": target_metadata(target),
        "review_dir": str(review_dir),
        "html_path": str(output),
        "bytes_written": output.stat().st_size,
        "snapshot_generated_at": snapshot.get("generated_at"),
    }


def command_observatory_generate_html(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    review_dir = resolve_review_dir(args.review_dir)
    return generate_observatory_html(target, review_dir)


def command_observatory_load_html(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    review_dir = resolve_review_dir(args.review_dir)
    data = generate_observatory_html(target, review_dir)
    html_path = Path(str(data["html_path"]))
    html, truncated = read_text_file(html_path, max_bytes=MAX_HTML_BYTES)
    data.update(
        {
            "html": html if not truncated else "",
            "html_truncated": truncated,
            "embeddable": not truncated,
            "title_marker_present": "Diffmogger Autonomous Build Log" in html,
            "visual_markers_present": all(
                marker in html
                for marker in [
                    "Mission State",
                    "Conveyor Belt",
                    "Progress Story",
                    "Landed Work",
                    "Scorecard",
                    "Recent Outcomes",
                    "Conveyor Health",
                ]
            ),
        }
    )
    return data


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def badge(label: str, value: Any, tone: str = "info") -> dict[str, Any]:
    return {"label": label, "value": compact_text(value, limit=80), "tone": tone}


def status_tone(status: Any) -> str:
    text = str(status or "").upper()
    if "CRITICAL" in text:
        return "critical"
    if "BLOCKED" in text:
        return "warn"
    if "PENDING" in text:
        return "warn"
    if text in {"ACTIVE", "ACTIVE_WITH_PENDING_USER_INPUT"}:
        return "good"
    return "info" if text and text != "UNKNOWN" else "quiet"


def role_status(role: str, active: dict[str, Any], next_roles: set[str]) -> tuple[str, str]:
    if active.get("role") == role and active.get("status") == "running":
        return "running", "good"
    if role in next_roles:
        return "next", "info"
    return "standby", "quiet"


def observatory_native_snapshot(raw: dict[str, Any], target: Path) -> dict[str, Any]:
    task = raw.get("task") if isinstance(raw.get("task"), dict) else {}
    git = raw.get("git") if isinstance(raw.get("git"), dict) else {}
    queue = raw.get("queue") if isinstance(raw.get("queue"), dict) else {}
    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    scorecard = raw.get("scorecard") if isinstance(raw.get("scorecard"), dict) else {}
    conveyor = raw.get("conveyor") if isinstance(raw.get("conveyor"), dict) else {}
    signals = raw.get("signals") if isinstance(raw.get("signals"), dict) else {}
    human = raw.get("human") if isinstance(raw.get("human"), dict) else {}
    baseline = raw.get("baseline_verification") if isinstance(raw.get("baseline_verification"), dict) else {}
    first_review = raw.get("first_review") if isinstance(raw.get("first_review"), dict) else {}
    review = raw.get("review") if isinstance(raw.get("review"), dict) else {}
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}
    counts_by_role = queue.get("counts_by_role") if isinstance(queue.get("counts_by_role"), dict) else {}
    active = conveyor.get("active_role_run") if isinstance(conveyor.get("active_role_run"), dict) else {}
    decisions = [item for item in list(conveyor.get("decision_queue") or []) if isinstance(item, dict)]
    next_roles = {
        str(item.get("role") or "")
        for item in decisions
        if not (active.get("status") == "running" and item.get("role") == active.get("role"))
    }
    roles = []
    for role in ["planner", "builder", "hardener", "integrator"]:
        counts = counts_by_role.get(role) if isinstance(counts_by_role.get(role), dict) else {}
        state, tone = role_status(role, active, next_roles)
        reason = ""
        for item in decisions:
            if item.get("role") == role:
                reason = compact_text(item.get("reason"), limit=180)
                break
        roles.append(
            {
                "role": role,
                "status": state,
                "badge": state,
                "tone": tone,
                "reason": reason or ("Currently running." if state == "running" else "Awaiting the next conveyor decision."),
                "counts": {name: as_int(counts.get(name)) for name in ["queued", "deferred", "applied", "failed", "skipped"]},
            }
        )

    commits = [item for item in list(git.get("commits") or []) if isinstance(item, dict)]
    landed_feed = [
        {
            "hash": compact_text(item.get("hash"), limit=40),
            "time": compact_text(item.get("time"), limit=80),
            "subject": compact_text(item.get("subject") or "Commit landed", limit=220),
            "role": compact_text(item.get("role") or "commit", limit=40),
            "summary": compact_text(item.get("summary") or "", limit=260),
            "file_count": as_int(item.get("file_count")),
            "additions": as_int(item.get("additions")),
            "deletions": as_int(item.get("deletions")),
            "files": list(item.get("files") or [])[:6],
        }
        for item in commits[:12]
    ]
    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    safety = task.get("integration_safety") if isinstance(task.get("integration_safety"), dict) else {}
    known_issues = list(task.get("known_issues") or [])
    known_issue = compact_text(known_issues[0] if known_issues else task.get("known_issue"), limit=220)
    if not known_issue:
        known_issue = "No active issue summary."
    status = compact_text(task.get("status") or "UNKNOWN", limit=60)
    pending_human = as_int(human.get("pending_requests")) + as_int(human.get("unhandled_inbox"))
    tag_rows = [
        badge("Status", status, status_tone(status)),
        badge("Horizon", task.get("horizon") or "unknown", "info"),
        badge("Branch", git.get("branch") or "unknown", "quiet"),
        badge("Safety", safety.get("status") or "not_recorded", "good" if safety.get("status") == "pass" else "warn"),
        badge("Human", pending_human, "warn" if pending_human else "good"),
    ]
    queue_totals = {name: as_int(totals.get(name)) for name in ["queued", "deferred", "applied", "failed", "skipped"]}
    signal_nudges = [
        {
            "id": compact_text(item.get("id") or "signal", limit=80),
            "owner_role": compact_text(item.get("owner_role") or "unknown", limit=40),
            "priority": compact_text(item.get("priority") or "medium", limit=40),
            "instructions": compact_text(item.get("instructions") or "No instructions recorded.", limit=240),
            "next_due_at": compact_text(item.get("next_due_at") or "", limit=80),
        }
        for item in list(signals.get("active") or [])
        if isinstance(item, dict)
    ]
    history = [
        {
            "role": compact_text(item.get("role") or "role", limit=40),
            "status": "accepted" if item.get("progress_success") else "deferred",
            "finished_at": compact_text(item.get("finished_at") or item.get("started_at") or "", limit=80),
            "exit_code": item.get("exit_code"),
            "reason": compact_text(item.get("reason") or "No reason recorded.", limit=220),
            "run_id": compact_text(item.get("run_id") or "", limit=80),
        }
        for item in reversed([item for item in list(conveyor.get("history") or []) if isinstance(item, dict)][-30:])
    ]
    return {
        "schema_version": 1,
        "generated_at": raw.get("generated_at"),
        "target": target_metadata(target),
        "title": "Diffmogger Autonomous Build Log",
        "subtitle": "Diffmogger Observatory view: replay-style automation progress reconstructed from conveyor events, commits, and diff stats.",
        "mission": {
            "project_name": raw.get("target_name") or target.name,
            "automation_status": status,
            "current_horizon": compact_text(task.get("horizon") or "unknown", limit=180),
            "mission_text": compact_text(task.get("current_assessment") or "No current assessment recorded yet.", limit=420),
            "best_next_milestone": compact_text(task.get("best_next_milestone") or task.get("suggested_next_task") or "No milestone recorded yet.", limit=260),
            "known_issue": known_issue,
            "tags": tag_rows,
        },
        "scorecard": {
            "status": scorecard.get("status") or "unknown",
            "summary": compact_text(scorecard.get("summary") or "No scorecard summary recorded yet.", limit=420),
            "counts": list(scorecard.get("items") or [])[:8],
        },
        "conveyor": {
            "cycles": as_int(conveyor.get("cycles")),
            "updated_at": conveyor.get("updated_at") or "never",
            "roles": roles,
            "active_run": active,
            "decision_queue": decisions,
            "health": conveyor.get("health") if isinstance(conveyor.get("health"), dict) else {},
            "no_progress": conveyor.get("no_progress") if isinstance(conveyor.get("no_progress"), dict) else {},
        },
        "progress": {
            "story": raw.get("progress_recent") or progress.get("recent_activity") or "No progress pulse yet.",
            "latest_landed_work": landed_feed[0] if landed_feed else {},
            "landed_work_feed": landed_feed,
            "recent_outcomes": list(queue.get("recent_outcomes") or [])[:8],
        },
        "validation_safety": {
            "validation": validation,
            "integration_safety": safety,
            "baseline_verification": baseline,
            "first_review": first_review,
        },
        "patches": {
            "queue_totals": queue_totals,
            "manifests": list(queue.get("manifests") or [])[:16],
            "deferred_backlog": list(progress.get("deferred_backlog") or [])[:12],
            "deferred_triage": progress.get("deferred_triage") if isinstance(progress.get("deferred_triage"), dict) else {},
            "recent_outcomes": list(queue.get("recent_outcomes") or [])[:12],
        },
        "signals": {
            "active_count": as_int(signals.get("active_count")),
            "updated_at": signals.get("updated_at") or "never",
            "nudges": signal_nudges,
            "recent_completed": list(signals.get("recent_completed") or [])[:8],
        },
        "timeline": history,
        "metrics": {
            "accepted_total": as_int(progress.get("accepted_total")),
            "deferred_total": as_int(progress.get("deferred_total")),
            "deferred_queue_depth": as_int(progress.get("deferred_queue_depth")),
            "queued_patches": queue_totals.get("queued", 0),
            "pending_human": pending_human,
            "dirty_files": as_int(git.get("dirty_count")),
        },
        "review": {
            "items": list(review.get("items") or [])[:8],
            "known_issues": list(review.get("known_issues") or [])[:8],
        },
    }


def command_observatory_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    raw = build_observatory_snapshot(target)
    return observatory_native_snapshot(raw, target)


def git_changed_files(target: Path) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=target,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    files: list[dict[str, Any]] = []
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        status = raw[:2].strip() or "changed"
        path = raw[3:].strip() if len(raw) > 3 else raw.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        files.append(
            {
                "path": compact_text(path, limit=180),
                "status": status,
                "kind": "git_status",
                "summary": {
                    "M": "Modified",
                    "A": "Added",
                    "D": "Deleted",
                    "R": "Renamed",
                    "C": "Copied",
                    "??": "Untracked",
                }.get(status, "Changed"),
            }
        )
    return files


def generated_target_files(target: Path, dashboard_app: Any, *, limit: int = 18) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for record in file_registry(dashboard_app).values():
        if record.get("group") == "state":
            continue
        description = describe_registered_file(target, record)
        if description.get("exists"):
            files.append(
                {
                    "path": description["rel_path"],
                    "status": "generated",
                    "kind": "generated_file",
                    "summary": description["label"],
                }
            )
    return files[:limit]


def review_environment_limitations(snapshot: dict[str, Any], environment_blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    task = snapshot.get("task") if isinstance(snapshot.get("task"), dict) else {}
    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    items = validation.get("items") if isinstance(validation.get("items"), list) else []
    limitations: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").lower()
        body = str(item.get("text") or "")
        lower = body.lower()
        if status in {"warn", "pending", "fail"} or any(term in lower for term in ("not run", "skipped", "playwright", "browser", "permission", "unavailable")):
            limitations.append(
                {
                    "status": status or "info",
                    "text": compact_text(body, limit=360),
                    "source": "validation",
                }
            )
    for item in environment_blockers:
        limitations.append(
            {
                "status": "blocked",
                "text": compact_text(item.get("detail") or item.get("label") or item, limit=360),
                "source": "environment",
            }
        )
    return limitations[:12]


def review_marker_path(target: Path) -> Path:
    return preferred_target_path(target, ".agentic/reviewed.json")


def review_marker_snapshot(target: Path) -> dict[str, Any]:
    path = review_marker_path(target)
    data = read_json_file(path)
    if not data:
        return {
            "exists": False,
            "path": str(path),
            "reviewed_at": "",
            "note": "",
        }
    return {
        "exists": True,
        "path": str(path),
        "reviewed_at": data.get("reviewed_at") or "",
        "note": data.get("note") or "",
        "snapshot_generated_at": data.get("snapshot_generated_at") or "",
    }


def review_load_snapshot(target: Path) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    module = load_observatory_module()
    raw = build_observatory_snapshot(target)
    task = raw.get("task") if isinstance(raw.get("task"), dict) else {}
    git = raw.get("git") if isinstance(raw.get("git"), dict) else {}
    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    review = raw.get("review") if isinstance(raw.get("review"), dict) else {}
    baseline = raw.get("baseline_verification") if isinstance(raw.get("baseline_verification"), dict) else {}
    scorecard = raw.get("scorecard") if isinstance(raw.get("scorecard"), dict) else {}
    latest_log = latest_run_log(target, dashboard_app)
    prerequisites = schedule_prerequisites(target, dashboard_app)
    environment_blockers = [
        row for row in prereq_rows(prerequisites)
        if row["required"] and not row["ok"]
    ]
    changed_files = git_changed_files(target)
    changed_source = "git_status"
    if not changed_files:
        commits = git.get("commits") if isinstance(git.get("commits"), list) else []
        if commits:
            first = commits[0] if isinstance(commits[0], dict) else {}
            files = first.get("files") if isinstance(first.get("files"), list) else []
            changed_files = [
                {
                    "path": item.get("path"),
                    "status": "landed",
                    "kind": "commit_file",
                    "summary": f"+{item.get('additions', 0)} / -{item.get('deletions', 0)}",
                }
                for item in files
                if isinstance(item, dict)
            ]
            changed_source = "latest_commit"
    if not changed_files:
        changed_files = generated_target_files(target, dashboard_app)
        changed_source = "generated_target"
    markdown = module.render_review_markdown(raw)
    review_dir = target_path(target, "target/first-review")
    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    safety = task.get("integration_safety") if isinstance(task.get("integration_safety"), dict) else {}
    commits = git.get("commits") if isinstance(git.get("commits"), list) else []
    return {
        "target": target_metadata(target),
        "generated_at": raw.get("generated_at"),
        "latest_run": {
            "status": task.get("status") or "UNKNOWN",
            "horizon": task.get("horizon") or "unknown",
            "summary": progress.get("recent_activity") or raw.get("progress_recent") or "No automation run summary recorded yet.",
            "log": latest_log,
            "action_plan": scorecard.get("action_plan") if isinstance(scorecard.get("action_plan"), dict) else {},
        },
        "changed_files": changed_files[:24],
        "changed_files_source": changed_source,
        "latest_commits": commits[:8],
        "verification": {
            "summary": validation.get("summary") or "No validation results recorded yet.",
            "counts": validation.get("counts") if isinstance(validation.get("counts"), dict) else {},
            "items": validation.get("items") if isinstance(validation.get("items"), list) else [],
            "baseline": baseline,
        },
        "safety": safety or {
            "status": "not_recorded",
            "summary": "No integration-safety check result recorded yet.",
            "command": "python3 scripts/check_integration_safety.py",
        },
        "limitations": review_environment_limitations(raw, environment_blockers),
        "self_review": {
            "markdown_preview": markdown[:20_000],
            "truncated": len(markdown) > 20_000,
            "default_markdown_path": str(review_dir / DEFAULT_REVIEW_MARKDOWN),
        },
        "bundle": {
            "review_dir": str(review_dir),
            "html_path": str(review_dir / DEFAULT_REVIEW_HTML),
            "markdown_path": str(review_dir / DEFAULT_REVIEW_MARKDOWN),
        },
        "review": review,
        "reviewed": review_marker_snapshot(target),
        "empty_states": raw.get("empty_states") if isinstance(raw.get("empty_states"), dict) else {},
    }


def command_review_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    return review_load_snapshot(target)


def command_review_export_bundle(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    review_dir = resolve_review_dir(args.review_dir)
    module = load_observatory_module()
    snapshot = build_observatory_snapshot(target)
    snapshot = module.persist_recommendation_history(target, snapshot)
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            module.write_review_bundle(str(review_dir), snapshot)
    except OSError as exc:
        raise BackendError(
            "Could not write review bundle.",
            error_type="write_failed",
            details={"review_dir": str(review_dir), "exception": str(exc)},
        ) from exc
    html_path = review_dir / DEFAULT_REVIEW_HTML
    markdown_path = review_dir / DEFAULT_REVIEW_MARKDOWN
    return {
        "target": target_metadata(target),
        "review_dir": str(review_dir),
        "html_path": str(html_path),
        "markdown_path": str(markdown_path),
        "action_plan_history_path": str(target_path(target, "target/action_plan_history.json")),
        "legacy_output": captured.getvalue().splitlines(),
        "snapshot_generated_at": snapshot.get("generated_at"),
    }


def command_review_mark_reviewed(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to write a reviewed marker into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )
    raw = build_observatory_snapshot(target)
    path = review_marker_path(target)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot_generated_at": raw.get("generated_at"),
        "automation_status": (raw.get("task") or {}).get("status") if isinstance(raw.get("task"), dict) else "UNKNOWN",
        "note": str(getattr(args, "note", "") or "").strip(),
        "source": "native_review_page",
    }
    write_json_file(path, payload)
    write_dashboard_action_state(
        target,
        last_action="review_marked",
        updates={"last_reviewed_at": payload["reviewed_at"]},
    )
    return {
        "target": target_metadata(target),
        "reviewed": review_marker_snapshot(target),
        "marker_path": str(path),
    }


def required_file_flags(target: Path) -> list[str]:
    intake = load_intake(target)
    flags: list[str] = []
    bridge_mode = human_bridge_mode_from_state(target)
    flags.extend(["--human-bridge-mode", bridge_mode])
    if bool(intake.get("write_worker_agents_allowed", False)):
        flags.append("--write-workers-enabled")
    if bool(intake.get("multi_role_automations_allowed", False)):
        flags.append("--multi-role-enabled")
    if bool(intake.get("automation_signals_enabled", False)):
        flags.append("--automation-signals-enabled")
    if str(intake.get("automation_run_mode") or "") == "ticket_campaign":
        flags.append("--ticket-campaign-enabled")
    if intake.get("optional_mcp_servers"):
        flags.append("--optional-mcp-enabled")
    return flags


def run_subprocess(command: list[str], *, cwd: Path = KIT_ROOT) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return {
        "command": " ".join(command),
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def command_diagnostics_run_checks(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    bridge_mode = human_bridge_mode_from_state(target)
    prerequisites = native_prerequisites(target, dashboard_app)
    prerequisite_rows = [
        {
            "name": item.name,
            "ok": item.ok,
            "required": item.required,
            "category": "required" if item.required else "optional",
            "detail": item.detail,
        }
        for item in prerequisites
    ]
    required_failures = [item for item in prerequisite_rows if item["required"] and not item["ok"]]

    has_generated_state = (
        existing_or_target_path(target, ".agentic/automation_prompt.md").exists()
        or existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md").exists()
    )
    if has_generated_state:
        required_files = run_subprocess(
            [
                sys.executable,
                str(CHECK_REQUIRED_SCRIPT),
                *required_file_flags(target),
                str(target),
            ]
        )
        required_files["status"] = "pass" if required_files["exit_code"] == 0 else "fail"
    else:
        required_files = {
            "status": "not_run",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "command": "",
            "reason": "Target does not contain generated Diffmogger automation state yet.",
        }

    safety_target = dashboard_app.resolve_integration_safety_target(target)
    safety = run_subprocess([sys.executable, str(CHECK_INTEGRATION_SAFETY_SCRIPT), str(safety_target)])
    safety["status"] = "pass" if safety["exit_code"] == 0 else "fail"
    safety["checked_target"] = str(safety_target)
    schedule = schedule_status_snapshot(target, dashboard_app)

    target_writable = os.access(target, os.W_OK)
    state_dir = preferred_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md").parent
    docs_writable = os.access(state_dir, os.W_OK) if state_dir.exists() else os.access(target, os.W_OK)
    runtime_environment = runtime_environment_snapshot(dashboard_app)
    fix_suggestions = setup_fix_suggestions(runtime_environment)
    backend_schema = {
        "schema_version": SCHEMA_VERSION,
        "commands": {
            "project": 1,
            "brief": 1,
            "run": 1,
            "inbox": 1,
            "review": 1,
            "advanced": 1,
        },
    }

    return {
        "target": target_metadata(target),
        "prerequisites": {
            "status": "pass" if not required_failures else "fail",
            "items": prerequisite_rows,
            "required_failures": required_failures,
        },
        "required_files": required_files,
        "integration_safety": safety,
        "tools": [
            tool_status("codex", ["--version"], required=True, path=runtime_environment.get("effective_path")),
            tool_status("python3", ["--version"], required=True, path=runtime_environment.get("effective_path")),
            tool_status("bash", ["--version"], required=True, path=runtime_environment.get("effective_path")),
            tool_status("git", ["--version"], required=True, path=runtime_environment.get("effective_path")),
        ],
        "target_writability": {
            "target": target_writable,
            "docs": docs_writable,
            "status": "pass" if target_writable and docs_writable else "fail",
        },
        "macos_permissions": {
            "status": "info",
            "detail": "On macOS, grant file access for target folders if folder picking or schedule logs fail.",
        },
        "notifier_health": {
            "configured": bridge_mode in {"local_notifier", "discord_notifier"},
            "bridge_mode": bridge_mode,
            "status": "not_configured" if bridge_mode == "file_only" else "unknown",
            "detail": "File-only mode does not require notifier credentials."
            if bridge_mode == "file_only"
            else "Use the notifier service health check before relying on external delivery.",
        },
        "schedule": schedule,
        "runtime_environment": runtime_environment,
        "fix_suggestions": fix_suggestions,
        "backend": backend_schema,
    }


def command_diagnostics_environment(args: argparse.Namespace) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    runtime_environment = runtime_environment_snapshot(dashboard_app)
    tools = runtime_environment.get("tools") if isinstance(runtime_environment.get("tools"), list) else []
    required_failures = [
        item for item in tools
        if isinstance(item, dict) and item.get("required") and not item.get("ok")
    ]
    return {
        "status": "pass" if not required_failures else "fail",
        "runtime_environment": runtime_environment,
        "fix_suggestions": setup_fix_suggestions(runtime_environment),
        "required_failures": required_failures,
        "setup_mode": "guide_and_copy",
    }


def command_advanced_list_files(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    files = [
        describe_registered_file(target, record)
        for record in file_registry(dashboard_app).values()
    ]
    categories: dict[str, int] = {}
    for file in files:
        categories[str(file.get("category") or "Core state")] = categories.get(str(file.get("category") or "Core state"), 0) + 1
    return {"target": target_metadata(target), "files": files, "categories": categories}


def registered_file_description(target: Path, file_key: str) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    registry = file_registry(dashboard_app)
    record = registry.get(file_key)
    if not record:
        raise BackendError(
            "Unknown file key.",
            exit_code=2,
            error_type="invalid_file_key",
            details={"file_key": file_key, "valid_keys": sorted(registry)},
        )
    return describe_registered_file(target, record)


def command_advanced_load_file(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    description = registered_file_description(target, args.file_key)
    if not description["exists"]:
        return {"target": target_metadata(target), "file": description, "content": "", "truncated": False}
    text, truncated = read_text_file(Path(description["path"]))
    return {"target": target_metadata(target), "file": description, "content": text, "truncated": truncated}


def command_advanced_save_file(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to save managed files into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )
    description = registered_file_description(target, args.file_key)
    if not bool(description.get("editable", True)):
        raise BackendError(
            "This managed file is read-only from Advanced.",
            exit_code=2,
            error_type="file_read_only",
            details={"file_key": args.file_key},
        )
    content = str(args.content or "")
    if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
        raise BackendError(
            "File content is too large for dashboard editing.",
            exit_code=2,
            error_type="content_too_large",
            details={"max_bytes": MAX_TEXT_BYTES},
        )
    path = Path(description["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    updated = registered_file_description(target, args.file_key)
    return {"target": target_metadata(target), "file": updated, "saved": True}


def command_advanced_validate_file(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    description = registered_file_description(target, args.file_key)
    validation = str(description.get("validation") or "")
    path = Path(description["path"])
    if not description["exists"]:
        return {"target": target_metadata(target), "file": description, "status": "missing", "items": [{"ok": False, "detail": "File does not exist yet."}]}
    if validation == "json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"target": target_metadata(target), "file": description, "status": "fail", "items": [{"ok": False, "detail": str(exc)}]}
        return {"target": target_metadata(target), "file": description, "status": "pass", "items": [{"ok": True, "detail": "JSON parses successfully."}]}
    if validation == "required_files":
        flags = required_file_flags(target)
        result = run_subprocess([sys.executable, str(CHECK_REQUIRED_SCRIPT), *flags, str(target)])
        return {
            "target": target_metadata(target),
            "file": description,
            "status": "pass" if result["exit_code"] == 0 else "fail",
            "items": [{"ok": result["exit_code"] == 0, "detail": result["stdout"] or result["stderr"] or "Required-file check completed."}],
            "result": result,
        }
    return {"target": target_metadata(target), "file": description, "status": "not_available", "items": [{"ok": True, "detail": "No validator is registered for this managed file."}]}


SECRET_KEY_RE = re.compile(r"(secret|token|password|api[_-]?key|credential|private[_-]?key|discord|webhook)", re.I)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API[_-]?KEY|CREDENTIAL|PRIVATE[_-]?KEY|WEBHOOK)[A-Z0-9_]*)\b\s*[:=]\s*([^\s]+)"
)
SECRET_VALUE_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{16,})\b")


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and SECRET_KEY_RE.search(value):
        return "[REDACTED]"
    return value


def redact_secret_text(text: str) -> str:
    redacted_lines: list[str] = []
    for line in text.splitlines():
        sanitized = SECRET_VALUE_RE.sub("[REDACTED]", line)
        if SECRET_ASSIGNMENT_RE.search(sanitized):
            redacted_lines.append(SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", sanitized))
        elif SECRET_KEY_RE.search(line):
            redacted_lines.append("[REDACTED LINE]")
        else:
            redacted_lines.append(sanitized)
    return "\n".join(redacted_lines)


def resolve_output_dir(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise BackendError("An output directory is required.", exit_code=2, error_type="invalid_output_dir")
    path = Path(raw).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise BackendError(
            "Output path exists but is not a directory.",
            exit_code=2,
            error_type="invalid_output_dir",
            details={"output_dir": str(path)},
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def command_advanced_export_debug_bundle(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    output_dir = resolve_output_dir(args.output_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bundle_path = output_dir / f"Diffmogger-debug-{target.name or 'target'}-{timestamp}.zip"
    diagnostics = command_diagnostics_run_checks(args)
    files = command_advanced_list_files(args)
    latest_log = latest_run_log(target, load_dashboard_module())
    debug_summary = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target_metadata(target),
        "diagnostics": diagnostics,
        "files": files,
        "latest_log": latest_log,
        "omitted": [
            ".env and .env.* files",
            "secret-like keys and values",
            "arbitrary project source files outside the managed file allowlist",
        ],
    }
    dashboard_state = load_dashboard_state(target)
    backend_command_log = {
        "last_action": dashboard_state.get("last_action", ""),
        "updated_at": dashboard_state.get("updated_at", ""),
        "last_run_once_started_at": dashboard_state.get("last_run_once_started_at", ""),
        "last_run_once_finished_at": dashboard_state.get("last_run_once_finished_at", ""),
        "last_run_once_exit_code": dashboard_state.get("last_run_once_exit_code", ""),
        "last_safety_check_exit_code": dashboard_state.get("last_safety_check_exit_code", ""),
        "last_worker_run_id": dashboard_state.get("last_worker_run_id", ""),
        "last_reviewed_at": dashboard_state.get("last_reviewed_at", ""),
    }
    safe_records = [
        ("debug-summary.json", json.dumps(redact_secrets(debug_summary), indent=2, sort_keys=True, default=json_default) + "\n"),
        ("dashboard-state.json", json.dumps(redact_secrets(dashboard_state), indent=2, sort_keys=True, default=json_default) + "\n"),
        ("project-intake.json", json.dumps(redact_secrets(load_intake(target)), indent=2, sort_keys=True, default=json_default) + "\n"),
        ("backend-command-log.json", json.dumps(redact_secrets(backend_command_log), indent=2, sort_keys=True, default=json_default) + "\n"),
        ("native-app-log-note.txt", "No native app log file is configured yet; backend command metadata and the latest target run log are included when present.\n"),
    ]
    safety_path = target_path(target, "target/integration_safety_check.json")
    if safety_path.exists():
        text, _truncated = read_text_file(safety_path)
        try:
            safety_payload = json.loads(text or "{}")
            safety_body = json.dumps(redact_secrets(safety_payload), indent=2, sort_keys=True, default=json_default) + "\n"
        except json.JSONDecodeError:
            safety_body = redact_secret_text(text)
        safe_records.append(("integration-safety-check.json", safety_body))
    if latest_log.get("content"):
        safe_records.append(("latest-run-log.txt", redact_secret_text(str(latest_log.get("content") or ""))))
    try:
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in safe_records:
                archive.writestr(name, body)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackendError(
            "Could not write debug bundle.",
            error_type="debug_bundle_failed",
            details={"output_dir": str(output_dir), "exception": str(exc)},
        ) from exc
    return {
        "target": target_metadata(target),
        "bundle_path": str(bundle_path),
        "included": [name for name, _body in safe_records],
        "omitted": debug_summary["omitted"],
    }


def add_target_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="Target project directory")


def add_review_dir_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--review-dir", required=True, help="Directory for generated review artifacts")


def build_parser() -> argparse.ArgumentParser:
    parser = BackendArgumentParser(description=__doc__)
    parser.add_argument("--stream-jsonl", action="store_true", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    commands: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
        "project.load_snapshot": command_project_load_snapshot,
        "project.list_recent": command_project_list_recent,
        "brief.load": command_brief_load,
        "brief.save_draft": command_brief_save_draft,
        "brief.scaffold_preview": command_brief_scaffold_preview,
        "brief.scaffold_bootstrap": command_brief_scaffold_bootstrap,
        "context.import": command_context_import,
        "inbox.load": command_inbox_load,
        "inbox.send_note": command_inbox_send_note,
        "inbox.reply_request": command_inbox_reply_request,
        "run.load": command_run_load,
        "run.load_log": command_run_load_log,
        "run.once": command_run_once,
        "schedule.start": command_schedule_start,
        "schedule.pause": command_schedule_pause,
        "schedule.remove": command_schedule_remove,
        "safety.run_check": command_safety_run_check,
        "worker.run_read_only": command_worker_run_read_only,
        "worker.run_write": command_worker_run_write,
        "worker.run_integrator": command_worker_run_integrator,
        "observatory.snapshot": command_observatory_snapshot,
        "observatory.generate_html": command_observatory_generate_html,
        "observatory.load_html": command_observatory_load_html,
        "review.load": command_review_load,
        "review.export_bundle": command_review_export_bundle,
        "review.mark_reviewed": command_review_mark_reviewed,
        "diagnostics.environment": command_diagnostics_environment,
        "diagnostics.run_checks": command_diagnostics_run_checks,
        "advanced.list_files": command_advanced_list_files,
        "advanced.load_file": command_advanced_load_file,
        "advanced.save_file": command_advanced_save_file,
        "advanced.validate_file": command_advanced_validate_file,
        "advanced.export_debug_bundle": command_advanced_export_debug_bundle,
    }
    for name, handler in commands.items():
        subparser = subparsers.add_parser(name)
        subparser.set_defaults(handler=handler)
        if name not in {"project.list_recent", "diagnostics.environment"}:
            add_target_arg(subparser)
        if name in {"observatory.generate_html", "observatory.load_html", "review.export_bundle"}:
            add_review_dir_arg(subparser)
        if name in {"advanced.load_file", "advanced.save_file", "advanced.validate_file"}:
            subparser.add_argument("--file-key", required=True, help="Allowlisted file key")
        if name == "advanced.save_file":
            subparser.add_argument("--content", required=True, help="Replacement UTF-8 file content")
        if name == "advanced.export_debug_bundle":
            subparser.add_argument("--output-dir", required=True, help="Directory for the generated debug bundle")
        if name in {"brief.save_draft", "brief.scaffold_preview", "brief.scaffold_bootstrap"}:
            subparser.add_argument("--intake-json", required=True, help="JSON object with intake fields")
        if name == "context.import":
            subparser.add_argument("--files-json", required=True, help="JSON list of context file paths")
            subparser.add_argument("--project-name", default="", help="Project name for the context index")
        if name in {"inbox.send_note", "inbox.reply_request"}:
            subparser.add_argument("--body", required=True, help="Human message body")
            subparser.add_argument("--intent", default="info", help="Parsed human intent")
        if name == "inbox.send_note":
            subparser.add_argument("--related", default="", help="Optional related request, ticket, file, or run")
        if name == "inbox.reply_request":
            subparser.add_argument("--request-id", required=True, help="Automation request id being replied to")
        if name == "review.mark_reviewed":
            subparser.add_argument("--note", default="", help="Optional reviewer note")
        if name == "worker.run_write":
            subparser.add_argument("--ownership", required=True, help="Disjoint file or module ownership scope")
        if name in {"brief.scaffold_preview", "brief.scaffold_bootstrap"}:
            subparser.add_argument("--force", action="store_true", help="Overwrite existing scaffold-managed files")
        if name == "brief.scaffold_bootstrap":
            subparser.add_argument("--run-codex", action="store_true", help="Run the initial Codex bootstrap after scaffolding")
    return parser


def main(argv: list[str] | None = None) -> int:
    loaded = load_repo_dotenv_for_backend()
    if loaded:
        os.environ["DIFFMOGGER_BACKEND_DOTENV_LOADED"] = "1"
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        command = str(args.command)
        data = args.handler(args)
        payload = success(command, data)
        if bool(getattr(args, "stream_jsonl", False)):
            emit_jsonl(payload)
        else:
            emit(payload)
        return 0
    except BackendError as exc:
        command = "unknown"
        if "args" in locals() and getattr(args, "command", None):
            command = str(args.command)
        payload = failure(command, exc)
        if "args" in locals() and bool(getattr(args, "stream_jsonl", False)):
            emit_jsonl(payload)
        else:
            emit(payload)
        return exc.exit_code
    except BrokenPipeError:  # pragma: no cover - shell pipeline behavior.
        return 1
    except Exception as exc:  # pragma: no cover - defensive structured fallback.
        command = "unknown"
        if "args" in locals() and getattr(args, "command", None):
            command = str(args.command)
        error = BackendError(
            "Unhandled backend CLI error.",
            error_type=exc.__class__.__name__,
            details={"exception": str(exc)},
        )
        payload = failure(command, error)
        if "args" in locals() and bool(getattr(args, "stream_jsonl", False)):
            emit_jsonl(payload)
        else:
            emit(payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
