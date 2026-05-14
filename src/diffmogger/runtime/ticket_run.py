#!/usr/bin/env python3
"""Manage bounded Diffmogger ticket-campaign runs."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from diffmogger.runtime.paths import existing_or_target_path, target_path
from diffmogger.runtime.state_store import (
    database_path_for_target,
    load_ticket_run_state,
    record_human_message,
    sha256_text,
    stable_json,
    write_ticket_run_state,
)


DEFAULT_TICKET_FILE = "docs/TICKET_RUN.md"
COMPLETION_STATE = "target/ticket_run_completion.json"
NOTIFIER_URL = "http://127.0.0.1:8765/api/notify"
TICKET_STATUSES = {"pending", "in_progress", "candidate_done", "done", "blocked"}
TERMINAL_STATUSES = {"done", "blocked"}
FENCE_RE = re.compile(r"```(?:json\s+ticket-run|ticket-run-json)\s*\n(.*?)\n```", re.DOTALL)
PLACEHOLDER_TICKET_ID = "TICKET-001"
PLACEHOLDER_TICKET_SUMMARY = "Replace this sample with the first startup ticket."
TICKET_LIST_FIELDS = {
    "depends_on",
    "acceptance_criteria",
    "verification_commands",
    "evidence",
    "related_commits",
}
TICKET_STRING_FIELDS = {"id", "summary", "status", "blocker"}
TICKET_IMPORT_FORMATS = {"markdown", "csv", "json"}
TICKET_IMPORT_MODES = {"append", "replace-placeholder", "replace-all"}


def role_worktree_context(path: Path) -> dict[str, Any] | None:
    """Return canonical target metadata for a transient role worktree path."""
    parts = path.parts
    patterns = [
        (".diffmogger", "runtime", "automation_worktrees"),
        ("target", "automation_worktrees"),
    ]
    for pattern in patterns:
        pattern_len = len(pattern)
        for index in range(0, len(parts) - pattern_len + 1):
            if tuple(parts[index : index + pattern_len]) != pattern:
                continue
            if index == 0 or len(parts) <= index + pattern_len + 1:
                continue
            candidate = Path(*parts[:index])
            if (candidate / ".diffmogger" / "manifest.json").exists() or (candidate / ".agentic").exists():
                role = parts[index + pattern_len]
                run_id = parts[index + pattern_len + 1]
                return {
                    "target": candidate.resolve(),
                    "role": role,
                    "run_id": run_id,
                    "worktree_root": Path(*parts[: index + pattern_len + 2]).resolve(),
                }
    return None


def canonical_target_from_role_worktree(path: Path) -> Path | None:
    """Return the owning target for a transient role worktree path."""
    context = role_worktree_context(path)
    return Path(context["target"]) if context else None


def env_target_root() -> Path | None:
    for key in ("DIFFMOGGER_TARGET_ROOT", "TARGET"):
        value = os.getenv(key, "").strip()
        if not value:
            continue
        candidate = Path(value).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if (resolved / ".diffmogger" / "manifest.json").exists() or (resolved / ".agentic").exists():
            return resolved
    return None


def resolve_ticket_target(target: Path) -> Path:
    resolved = target.expanduser().resolve()
    env_root = env_target_root()
    if env_root is not None:
        worktree_root = target_path(env_root, "target/automation_worktrees").resolve()
        try:
            resolved.relative_to(worktree_root)
            return env_root
        except ValueError:
            pass
    return canonical_target_from_role_worktree(resolved) or resolved


def ticket_state_actions_path(target: Path) -> Path | None:
    configured = os.getenv("DIFFMOGGER_TICKET_STATE_ACTIONS_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    context = role_worktree_context(target.expanduser().resolve())
    if not context:
        return None
    worktree = Path(context["worktree_root"])
    role = str(context["role"])
    run_id = str(context["run_id"])
    return target_path(worktree, f"target/automation_queue/{role}/{run_id}/ticket_state_actions.json")


def should_stage_ticket_actions(target: Path) -> bool:
    return ticket_state_actions_path(target) is not None and os.getenv("DIFFMOGGER_TICKET_STATE_DIRECT", "").strip() != "1"


def ticket_digest(ticket: dict[str, Any]) -> str:
    return sha256_text(stable_json(dict(ticket)))


def ticket_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or "").strip(): dict(item) for item in tickets(data) if str(item.get("id") or "").strip()}


def staged_ticket_actions(previous: dict[str, Any], next_data: dict[str, Any]) -> list[dict[str, Any]]:
    previous_by_id = ticket_by_id(previous)
    next_items = tickets(next_data)
    next_ids = {str(item.get("id") or "").strip() for item in next_items if str(item.get("id") or "").strip()}
    actions: list[dict[str, Any]] = []
    for item in next_items:
        ticket_id = str(item.get("id") or "").strip()
        if not ticket_id:
            continue
        desired = dict(item)
        current = previous_by_id.get(ticket_id)
        if current == desired:
            continue
        actions.append(
            {
                "action": "update_ticket",
                "ticket_id": ticket_id,
                "start_hash": ticket_digest(current) if current is not None else None,
                "end_hash": ticket_digest(desired),
                "ticket": desired,
            }
        )
    for ticket_id, current in previous_by_id.items():
        if ticket_id in next_ids:
            continue
        actions.append(
            {
                "action": "delete_ticket",
                "ticket_id": ticket_id,
                "start_hash": ticket_digest(current),
            }
        )
    return actions


def append_ticket_state_actions(path: Path, actions: list[dict[str, Any]]) -> None:
    if not actions:
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {}
    existing_actions = existing.get("actions") if isinstance(existing, dict) else None
    merged = [item for item in existing_actions if isinstance(item, dict)] if isinstance(existing_actions, list) else []
    merged.extend(actions)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps({"schema_version": 1, "actions": merged}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def ticket_state_readonly_snapshot_path() -> Path | None:
    configured = os.getenv("DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT", "").strip()
    if not configured:
        return None
    return Path(configured).expanduser().resolve()


def read_ticket_state_readonly_snapshot() -> dict[str, Any] | None:
    path = ticket_state_readonly_snapshot_path()
    if path is None:
        return None
    payload = read_json(path)
    if not payload:
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("tickets"), list):
        return None
    return data


def load_ticket_run_state_for_staged_role(target: Path) -> dict[str, Any] | None:
    snapshot = read_ticket_state_readonly_snapshot()
    if snapshot is not None:
        return snapshot
    return load_ticket_run_state(target, read_only=True)


def project_intake(target: Path) -> dict[str, Any]:
    return read_json(existing_or_target_path(target, ".agentic/project_intake.json"))


def ticket_file_path(target: Path) -> Path:
    intake = project_intake(target)
    configured = str(intake.get("ticket_run_file") or "").strip()
    if configured:
        return target / configured
    legacy = target_path(target, DEFAULT_TICKET_FILE)
    if legacy.exists():
        return legacy
    return ticket_state_path(target)


def ticket_state_path(target: Path) -> Path:
    return database_path_for_target(target)


def empty_ticket_run(target: Path) -> dict[str, Any]:
    intake = project_intake(target)
    return {
        "run_id": "ticket-run",
        "halt_when_complete": True,
        "notify_on_complete": bool_value(intake.get("ticket_completion_notify", True), True),
        "tickets": [],
    }


def read_ticket_run_markdown(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Ticket run file not found: {path} ({exc})") from exc
    match = FENCE_RE.search(text)
    if not match:
        raise SystemExit(
            f"{path} must contain a fenced JSON block marked `json ticket-run` or `ticket-run-json`."
        )
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Malformed ticket-run JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Ticket-run JSON in {path} must be an object.")
    return data, text


def load_ticket_run(target: Path, ticket_file: Path | None = None) -> tuple[dict[str, Any], Path, str]:
    requested_target = target
    stage_actions = should_stage_ticket_actions(requested_target)
    target = resolve_ticket_target(target)
    if ticket_file is not None:
        path = ticket_file
        data, text = read_ticket_run_markdown(path)
        if not stage_actions:
            write_ticket_run_state(
                target,
                data,
                actor_role="ticket-cli",
                event_type="compatibility.ticket_markdown_imported",
                source_path=str(path),
            )
        return data, ticket_state_path(target), text

    state = load_ticket_run_state_for_staged_role(target) if stage_actions else load_ticket_run_state(target)
    if state:
        return state, ticket_state_path(target), ""

    path = ticket_file_path(target)
    if path == ticket_state_path(target):
        return empty_ticket_run(target), path, ""
    data, text = read_ticket_run_markdown(path)
    if not stage_actions:
        write_ticket_run_state(
            target,
            data,
            actor_role="migration",
            event_type="compatibility.legacy_ticket_markdown_imported",
            source_path=str(path),
        )
    return data, path, text


def normalize_status(value: Any) -> str:
    status = str(value or "pending").strip().lower()
    return status if status in TICKET_STATUSES else "pending"


def tickets(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("tickets")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        if "\n" in stripped:
            return [
                re.sub(r"^[-*]\s+", "", line.strip())
                for line in stripped.splitlines()
                if re.sub(r"^[-*]\s+", "", line.strip())
            ]
        return [stripped]
    return []


def split_multi_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r"\r?\n|[;|]", text)
    if len(parts) == 1 and "," in text:
        parts = text.split(",")
    values: list[str] = []
    for part in parts:
        cleaned = re.sub(r"^[-*]\s+", "", part.strip())
        if cleaned:
            values.append(cleaned)
    return values


def next_ticket_id(data: dict[str, Any], *, prefix: str = "TICKET") -> str:
    used = {str(item.get("id") or "").strip() for item in tickets(data)}
    highest = 0
    for ticket_id in used:
        match = re.search(r"(\d+)$", ticket_id)
        if match:
            highest = max(highest, int(match.group(1)))
    number = highest + 1
    while True:
        candidate = f"{prefix}-{number:03d}"
        if candidate not in used:
            return candidate
        number += 1


def normalize_ticket(ticket: dict[str, Any], *, fallback_id: str | None = None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in TICKET_STRING_FIELDS:
        value = str(ticket.get(key) or "").strip()
        normalized[key] = normalize_status(value) if key == "status" else value
    if not normalized["id"] and fallback_id:
        normalized["id"] = fallback_id
    for key in TICKET_LIST_FIELDS:
        normalized[key] = split_multi_value(ticket.get(key))
    normalized.setdefault("status", "pending")
    normalized.setdefault("blocker", "")
    return normalized


def normalized_tickets(items: list[dict[str, Any]], existing: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used = {str(item.get("id") or "").strip() for item in tickets(existing or {"tickets": []})}
    next_number = 1
    for item in items:
        fallback = str(item.get("id") or "").strip()
        if not fallback:
            while f"TICKET-{next_number:03d}" in used:
                next_number += 1
            fallback = f"TICKET-{next_number:03d}"
        normalized = normalize_ticket(item, fallback_id=fallback)
        used.add(str(normalized.get("id") or ""))
        result.append(normalized)
    return result


def bool_value(value: Any, default: bool) -> bool:
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


def has_verification_evidence(ticket: dict[str, Any]) -> bool:
    evidence = list_value(ticket.get("evidence"))
    checks = list_value(ticket.get("checks_run"))
    commits = list_value(ticket.get("related_commits"))
    return bool(evidence or checks or commits)


def queued_patch_count(target: Path) -> int:
    queue_root = target_path(target, "target/automation_queue")
    count = 0
    for path in queue_root.glob("*/*/manifest.json"):
        data = read_json(path)
        if data.get("status") == "queued":
            count += 1
    return count


def git_lines(target: Path, *args: str) -> list[str]:
    result = subprocess.run(["git", *args], cwd=target, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def ticket_summary(data: dict[str, Any], target: Path | None = None) -> dict[str, Any]:
    items = tickets(data)
    counts = {status: 0 for status in TICKET_STATUSES}
    done_missing_evidence: list[str] = []
    for item in items:
        status = normalize_status(item.get("status"))
        counts[status] += 1
        if status == "done" and not has_verification_evidence(item):
            done_missing_evidence.append(str(item.get("id") or item.get("summary") or "unknown"))
    total = len(items)
    terminal = counts["done"] + counts["blocked"]
    queued = queued_patch_count(target) if target else 0
    all_done = total > 0 and counts["done"] == total and not done_missing_evidence and queued == 0
    all_terminal = total > 0 and terminal == total and queued == 0
    blocked_terminal = all_terminal and counts["blocked"] > 0
    status = "complete" if all_done else "blocked" if blocked_terminal else "active"
    return {
        "run_id": str(data.get("run_id") or "ticket-run"),
        "status": status,
        "counts": counts,
        "total": total,
        "queued_patch_count": queued,
        "done_missing_evidence": done_missing_evidence,
        "should_halt": status in {"complete", "blocked"} and bool_value(data.get("halt_when_complete"), True),
        "reason": f"ticket campaign {status}" if status in {"complete", "blocked"} else "ticket campaign active",
    }


def ticket_identifier(ticket: dict[str, Any], index: int) -> str:
    ticket_id = str(ticket.get("id") or "").strip()
    return ticket_id or f"ticket[{index}]"


def ticket_dependency_ids(ticket: dict[str, Any]) -> list[str]:
    return list_value(ticket.get("depends_on"))


def dependency_satisfied(ticket: dict[str, Any]) -> bool:
    return normalize_status(ticket.get("status")) == "done" and has_verification_evidence(ticket)


def ticket_brief(ticket: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "id": ticket_identifier(ticket, index),
        "summary": str(ticket.get("summary") or "").strip(),
        "status": normalize_status(ticket.get("status")),
        "depends_on": ticket_dependency_ids(ticket),
    }


def is_placeholder_ticket(ticket: dict[str, Any]) -> bool:
    ticket_id = str(ticket.get("id") or "").strip()
    summary = str(ticket.get("summary") or "").strip()
    return ticket_id == PLACEHOLDER_TICKET_ID and summary == PLACEHOLDER_TICKET_SUMMARY


def dependency_report(data: dict[str, Any]) -> dict[str, Any]:
    items = tickets(data)
    id_to_ticket: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    for item in items:
        ticket_id = str(item.get("id") or "").strip()
        if not ticket_id:
            continue
        if ticket_id in id_to_ticket and ticket_id not in duplicate_ids:
            duplicate_ids.append(ticket_id)
        id_to_ticket[ticket_id] = item

    missing: list[dict[str, str]] = []
    waiting: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    done_missing_evidence: list[dict[str, str]] = []
    open_graph: dict[str, list[str]] = {}

    for index, item in enumerate(items):
        ticket_id = ticket_identifier(item, index)
        status = normalize_status(item.get("status"))
        dependencies = ticket_dependency_ids(item)
        if status in TERMINAL_STATUSES:
            continue
        for dependency_id in dependencies:
            dependency = id_to_ticket.get(dependency_id)
            if dependency is None:
                missing.append({"ticket_id": ticket_id, "depends_on": dependency_id})
                continue
            dependency_status = normalize_status(dependency.get("status"))
            if dependency_status == "blocked":
                blocked.append({"ticket_id": ticket_id, "depends_on": dependency_id})
            elif dependency_status == "done" and not has_verification_evidence(dependency):
                done_missing_evidence.append({"ticket_id": ticket_id, "depends_on": dependency_id})
            elif dependency_status != "done":
                waiting.append(
                    {
                        "ticket_id": ticket_id,
                        "depends_on": dependency_id,
                        "dependency_status": dependency_status,
                    }
                )
            if dependency_status not in TERMINAL_STATUSES and str(item.get("id") or "").strip():
                open_graph.setdefault(ticket_id, []).append(dependency_id)

    return {
        "duplicate_ticket_ids": duplicate_ids,
        "placeholder_tickets": [
            ticket_brief(item, index) for index, item in enumerate(items) if is_placeholder_ticket(item)
        ],
        "missing_dependencies": missing,
        "blocked_dependencies": blocked,
        "done_dependencies_missing_evidence": done_missing_evidence,
        "waiting_on_dependencies": waiting,
        "dependency_cycles": dependency_cycles(open_graph),
    }


def ticket_validation_issues(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = tickets(data)
    report = dependency_report(data)
    issues: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        ticket_id = ticket_identifier(item, index)
        if not str(item.get("id") or "").strip():
            issues.append({"level": "error", "type": "missing_id", "ticket_id": ticket_id, "detail": "Ticket is missing an id."})
        if not str(item.get("summary") or "").strip():
            issues.append({"level": "error", "type": "missing_summary", "ticket_id": ticket_id, "detail": "Ticket is missing a summary."})
        status = str(item.get("status") or "").strip().lower()
        if status and status not in TICKET_STATUSES:
            issues.append({"level": "warning", "type": "unknown_status", "ticket_id": ticket_id, "detail": f"Status {status!r} will be treated as pending."})
    for ticket_id in report["duplicate_ticket_ids"]:
        issues.append({"level": "error", "type": "duplicate_id", "ticket_id": ticket_id, "detail": "Ticket id is duplicated."})
    for item in report["missing_dependencies"]:
        issues.append({"level": "error", "type": "missing_dependency", **item, "detail": "Ticket depends on an unknown ticket id."})
    for cycle in report["dependency_cycles"]:
        issues.append({"level": "error", "type": "dependency_cycle", "ticket_ids": cycle, "detail": "Ticket dependencies contain a cycle."})
    for item in report["blocked_dependencies"]:
        issues.append({"level": "warning", "type": "blocked_dependency", **item, "detail": "Ticket depends on a blocked ticket."})
    for item in report["done_dependencies_missing_evidence"]:
        issues.append({"level": "warning", "type": "dependency_missing_evidence", **item, "detail": "Ticket depends on a done ticket without evidence."})
    return issues


def ticket_run_payload(data: dict[str, Any], target: Path | None = None) -> dict[str, Any]:
    return {
        "summary": ticket_summary(data, target),
        "dependency_report": dependency_report(data),
        "next": next_ticket_selection(data),
        "validation_issues": ticket_validation_issues(data),
        "tickets": tickets(data),
    }


def ticket_source_state(target: Path, ticket_file: Path | None = None) -> dict[str, Any]:
    target = resolve_ticket_target(target)
    try:
        data, path, _text = load_ticket_run(target, ticket_file)
    except SystemExit as exc:
        path = ticket_file or ticket_file_path(target)
        return {
            "path": str(path),
            "confirmed": False,
            "actionable": False,
            "reason": str(exc),
            "start_reason": str(exc),
            "summary": {},
            "next": {},
            "validation_issues": [{"level": "error", "detail": str(exc)}],
        }

    payload = ticket_run_payload(data, target)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    next_payload = payload.get("next") if isinstance(payload.get("next"), dict) else {}
    issues = [issue for issue in list(payload.get("validation_issues") or []) if isinstance(issue, dict)]
    errors = [issue for issue in issues if str(issue.get("level") or "").lower() == "error"]
    total = int(summary.get("total") or 0)
    placeholders = list(next_payload.get("placeholder_tickets") or [])
    placeholder_only = total > 0 and len(placeholders) == total

    if errors:
        reason = str(errors[0].get("detail") or errors[0].get("type") or "Ticket queue has validation errors.")
    elif total <= 0:
        reason = "Ticket queue has no tickets."
    elif placeholder_only:
        reason = "Ticket queue still contains placeholder tickets."
    else:
        reason = "Ticket queue is populated and confirmed."

    confirmed = bool(total > 0 and not placeholder_only and not errors)
    actionable = confirmed and str(next_payload.get("status") or "") == "selected"
    selected = next_payload.get("ticket") if isinstance(next_payload.get("ticket"), dict) else {}
    selected_id = str(selected.get("id") or "").strip()
    if actionable:
        start_reason = f"Ready to run ticket campaign starting with {selected_id}." if selected_id else "Ready to run ticket campaign."
    elif confirmed and summary.get("status") in {"complete", "blocked"}:
        start_reason = f"Ticket campaign is {summary.get('status')}."
    elif confirmed:
        start_reason = f"Ticket campaign has no actionable ticket: {next_payload.get('reason') or reason}."
    else:
        start_reason = reason

    return {
        "path": str(path),
        "confirmed": confirmed,
        "actionable": actionable,
        "reason": reason,
        "start_reason": start_reason,
        "summary": summary,
        "next": next_payload,
        "validation_issues": issues,
    }


def dependency_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visiting: list[str] = []
    visited: set[str] = set()
    seen: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        if node in visiting:
            cycle = visiting[visiting.index(node) :] + [node]
            key = tuple(cycle)
            if key not in seen:
                seen.add(key)
                cycles.append(cycle)
            return
        if node in visited:
            return
        visiting.append(node)
        for dependency_id in graph.get(node, []):
            if dependency_id in graph:
                visit(dependency_id)
        visiting.pop()
        visited.add(node)

    for node in graph:
        visit(node)
    return cycles


def dependencies_are_satisfied(ticket: dict[str, Any], id_to_ticket: dict[str, dict[str, Any]]) -> bool:
    for dependency_id in ticket_dependency_ids(ticket):
        dependency = id_to_ticket.get(dependency_id)
        if dependency is None or not dependency_satisfied(dependency):
            return False
    return True


def next_ticket_selection(data: dict[str, Any]) -> dict[str, Any]:
    items = tickets(data)
    id_to_ticket = {
        str(item.get("id") or "").strip(): item for item in items if str(item.get("id") or "").strip()
    }
    report = dependency_report(data)
    order = [
        ("candidate_done", "verify_candidate"),
        ("in_progress", "resume_in_progress"),
        ("pending", "implement_pending"),
    ]
    if report["duplicate_ticket_ids"]:
        return {
            "status": "blocked",
            "reason": "duplicate ticket ids",
            "ticket": None,
            "selection_order": [entry[0] for entry in order],
            **report,
        }
    if not items:
        return {
            "status": "blocked",
            "reason": "ticket queue has no tickets",
            "ticket": None,
            "selection_order": [entry[0] for entry in order],
            **report,
        }
    if len(report["placeholder_tickets"]) == len(items):
        return {
            "status": "blocked",
            "reason": "ticket queue still contains placeholder tickets",
            "ticket": None,
            "selection_order": [entry[0] for entry in order],
            **report,
        }
    for status, action in order:
        for index, item in enumerate(items):
            if normalize_status(item.get("status")) != status:
                continue
            if is_placeholder_ticket(item):
                continue
            if not dependencies_are_satisfied(item, id_to_ticket):
                continue
            return {
                "status": "selected",
                "reason": f"selected {status} ticket",
                "action": action,
                "ticket": ticket_brief(item, index),
                "selection_order": [entry[0] for entry in order],
                **report,
            }

    summary = ticket_summary(data)
    if summary["status"] in {"complete", "blocked"}:
        reason = summary["reason"]
        status = summary["status"]
    elif report["missing_dependencies"]:
        reason = "missing ticket dependency"
        status = "blocked"
    elif report["dependency_cycles"]:
        reason = "dependency cycle"
        status = "blocked"
    elif report["blocked_dependencies"]:
        reason = "dependency blocked"
        status = "blocked"
    elif report["done_dependencies_missing_evidence"]:
        reason = "dependency done without verification evidence"
        status = "waiting"
    elif report["waiting_on_dependencies"]:
        reason = "waiting on dependencies"
        status = "waiting"
    else:
        reason = "no actionable ticket"
        status = "waiting"
    return {
        "status": status,
        "reason": reason,
        "ticket": None,
        "selection_order": [entry[0] for entry in order],
        **report,
    }


def default_report_path(target: Path, data: dict[str, Any]) -> Path:
    run_id = str(data.get("run_id") or "ticket-run").strip() or "ticket-run"
    configured = str(data.get("report_path") or "").strip()
    if configured:
        return target / configured
    return target_path(target, f"target/ticket_run_reports/{run_id}.md")


def report_markdown(target: Path, data: dict[str, Any], summary: dict[str, Any]) -> str:
    commits = git_lines(target, "log", "--oneline", "--decorate", "-20")
    diffstat = git_lines(target, "diff", "--stat", "HEAD")
    lines = [
        f"# Ticket Campaign Report: {summary['run_id']}",
        "",
        f"- finalized_at: {utc_now()}",
        f"- status: {summary['status']}",
        f"- tickets_done: {summary['counts'].get('done', 0)} / {summary['total']}",
        f"- tickets_blocked: {summary['counts'].get('blocked', 0)}",
        f"- queued_role_patches: {summary['queued_patch_count']}",
        "",
        "## Tickets",
        "",
    ]
    for item in tickets(data):
        ticket_id = str(item.get("id") or "ticket")
        status = normalize_status(item.get("status"))
        lines.append(f"### {ticket_id}: {item.get('summary', '').strip() or 'Untitled ticket'}")
        lines.append("")
        lines.append(f"- status: {status}")
        criteria = list_value(item.get("acceptance_criteria"))
        if criteria:
            lines.append("- acceptance criteria:")
            lines.extend(f"  - {value}" for value in criteria)
        checks = list_value(item.get("verification_commands"))
        if checks:
            lines.append("- verification commands:")
            lines.extend(f"  - `{value}`" for value in checks)
        evidence = list_value(item.get("evidence"))
        if evidence:
            lines.append("- evidence:")
            lines.extend(f"  - {value}" for value in evidence)
        related = list_value(item.get("related_commits"))
        if related:
            lines.append("- related commits:")
            lines.extend(f"  - `{value}`" for value in related)
        blocker = str(item.get("blocker") or "").strip()
        if blocker:
            lines.append(f"- blocker: {blocker}")
        lines.append("")
    lines.extend(["## Recent Local Commits", ""])
    lines.extend(f"- `{line}`" for line in commits[:20]) if commits else lines.append("- No commits available.")
    lines.extend(["", "## Uncommitted Diffstat", ""])
    lines.extend(f"- `{line}`" for line in diffstat) if diffstat else lines.append("- No uncommitted diffstat.")
    lines.extend(
        [
            "",
            "## Manual Verification",
            "",
            "1. Review the local commits and changed files.",
            "2. Run the verification commands listed for each completed ticket.",
            "3. Push or open a PR manually after review; Diffmogger did not touch remotes.",
        ]
    )
    if summary["status"] == "blocked":
        lines.extend(["", "## Blockers", ""])
        for item in tickets(data):
            if normalize_status(item.get("status")) == "blocked":
                lines.append(f"- {item.get('id', 'ticket')}: {item.get('blocker', 'blocked')}")
    return "\n".join(lines).rstrip() + "\n"


def clip_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def notification_ticket_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in tickets(data):
        ticket_id = str(item.get("id") or "ticket")
        summary = clip_text(item.get("summary") or "Untitled ticket", 92)
        status = normalize_status(item.get("status")).upper()
        lines.append(f"- {ticket_id} [{status}] {summary}")
        evidence = list_value(item.get("evidence"))
        if evidence:
            lines.append(f"  Evidence: {clip_text(evidence[0], 160)}")
        checks = list_value(item.get("checks_run"))
        if checks:
            lines.append(f"  Check: {clip_text(checks[-1], 160)}")
        blocker = str(item.get("blocker") or "").strip()
        if blocker:
            lines.append(f"  Blocker: {clip_text(blocker, 170)}")
    return lines


def notification_diffstat(target: Path) -> list[str]:
    diffstat = git_lines(target, "diff", "--stat", "HEAD")
    if not diffstat:
        return ["- No uncommitted diffstat."]
    return [f"- {clip_text(line, 150)}" for line in diffstat[:8]]


def ticket_notification_message(target: Path, data: dict[str, Any], summary: dict[str, Any], report_path: Path) -> str:
    status = str(summary["status"]).upper()
    done = summary["counts"].get("done", 0)
    blocked = summary["counts"].get("blocked", 0)
    active = summary["total"] - done - blocked
    lines = [
        f"**Ticket campaign {summary['run_id']}: {status}**",
        f"Done: {done}/{summary['total']} | Active: {active} | Blocked: {blocked} | Queued patches: {summary['queued_patch_count']}",
        "",
        "**Tickets**",
        *notification_ticket_lines(data),
        "",
        "**Changed files**",
        *notification_diffstat(target),
        "",
        "**What happens now**",
        "- Remote push/PR creation is still manual.",
        f"- Local report: {report_path.relative_to(target) if report_path.is_relative_to(target) else report_path}",
    ]
    if summary["status"] == "complete":
        lines.insert(-2, "- Diffmogger has halted this ticket campaign because all tickets are done.")
        lines.append("- Recommended next step: review the diff, rerun the listed verification commands, then push or open a PR.")
    elif summary["status"] == "blocked":
        lines.insert(-2, "- Diffmogger has halted this ticket campaign because all remaining tickets are blocked.")
        lines.append("- Recommended next step: address the blockers above, move those tickets back to `in_progress`, and restart the conveyor.")
    else:
        lines.insert(-2, "- Diffmogger has not halted this ticket campaign; runnable work remains.")
        lines.append("- Recommended next step: continue verification and move tickets to `done` only with evidence.")
    return "\n".join(lines).strip()


def append_outbox(target: Path, message: str, status: str, detail: str) -> None:
    record_human_message(
        target,
        kind="outbound",
        body=message,
        request_id="ticket-run-notification",
        status=status,
        channel="notifier-fallback",
        sender="automation",
        recipient="human",
        summary=detail,
        actor_role="ticket-run",
    )


def post_notifier(payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("LOCAL_NOTIFY_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        os.getenv("DIFFMOGGER_NOTIFY_URL", NOTIFIER_URL),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"ok": True, "raw_body": body[:500]}


def notify_completion(target: Path, data: dict[str, Any], summary: dict[str, Any], report_path: Path) -> dict[str, Any]:
    intake = project_intake(target)
    notify_enabled = bool_value(
        data.get("notify_on_complete", intake.get("ticket_completion_notify", True)),
        True,
    )
    if not notify_enabled:
        return {"status": "disabled", "detail": "ticket completion notify disabled"}
    mode = str(intake.get("human_bridge_mode") or "file_only").strip().lower()
    if mode not in {"local_notifier", "discord_notifier"}:
        return {"status": "disabled", "detail": f"human bridge mode {mode} does not use notifier delivery"}
    message = ticket_notification_message(target, data, summary, report_path)
    payload = {
        "request_id": f"TICKET-{summary['run_id']}",
        "type": f"ticket_campaign_{summary['status']}",
        "priority": "normal",
        "summary": f"Ticket campaign {summary['status']}",
        "event_kind": "progress",
        "message_body": message,
        "agent_recommendation": "Review the local report, run verification, then push or open a PR manually.",
        "minimum_user_action": "Review local commits and report.",
        "reply_format": "Optional follow-up request.",
        "unblocked_work_remaining": [],
        "dedupe_key": f"TICKET-{summary['run_id']}:{summary['status']}",
        "expects_reply": False,
        "local_notify": bool_value(intake.get("local_notifications_enabled"), True),
    }
    try:
        delivered = post_notifier(payload)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        append_outbox(target, message, "NOTIFIER_UNREACHABLE", str(exc))
        return {
            "status": "fallback_outbox",
            "channel": "human_outbox",
            "detail": str(exc),
        }
    if delivered.get("ok"):
        return {"status": "sent_notifier", "channel": mode, "detail": delivered}
    detail = json.dumps(delivered, sort_keys=True)[:1000]
    append_outbox(target, message, "NOTIFIER_UNREACHABLE", detail)
    return {
        "status": "fallback_outbox",
        "channel": "human_outbox",
        "detail": detail,
    }


def completion_state_path(target: Path) -> Path:
    return target_path(target, COMPLETION_STATE)


def finalize(target: Path, *, ticket_file: Path | None = None) -> dict[str, Any]:
    target = resolve_ticket_target(target)
    data, path, _text = load_ticket_run(target, ticket_file)
    summary = ticket_summary(data, target)
    if not summary["should_halt"]:
        return {"finalized": False, "summary": summary, "ticket_file": str(path)}
    completion_path = completion_state_path(target)
    existing = read_json(completion_path)
    if existing.get("run_id") == summary["run_id"] and existing.get("status") == summary["status"]:
        return {**existing, "already_finalized": True}
    report_path = default_report_path(target, data)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_markdown(target, data, summary), encoding="utf-8")
    notification = notify_completion(target, data, summary, report_path)
    payload = {
        "schema_version": 1,
        "finalized": True,
        "run_id": summary["run_id"],
        "status": summary["status"],
        "reason": summary["reason"],
        "ticket_file": str(path),
        "report_path": str(report_path),
        "notification": notification,
        "finalized_at": utc_now(),
        "summary": summary,
    }
    completion_path.parent.mkdir(parents=True, exist_ok=True)
    completion_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_ticket_run_data(path: Path, text: str, data: dict[str, Any]) -> None:
    match = FENCE_RE.search(text)
    if not match:
        raise SystemExit(f"{path} must contain a fenced JSON block marked `json ticket-run` or `ticket-run-json`.")
    rendered = json.dumps(data, indent=2, sort_keys=False)
    updated = text[: match.start(1)] + rendered + text[match.end(1) :]
    path.write_text(updated, encoding="utf-8")


def ticket_from_line(line: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
    cleaned = re.sub(r"^\[[ xX-]\]\s+", "", cleaned).strip()
    if not cleaned:
        return None
    match = re.match(r"(?P<id>[A-Za-z][A-Za-z0-9_-]*-\d+)\s*(?:[:|-]|\s+-\s+)\s*(?P<summary>.+)$", cleaned)
    if match:
        return {"id": match.group("id"), "summary": match.group("summary").strip(), "status": "pending"}
    if len(cleaned) >= 8:
        return {"summary": cleaned, "status": "pending"}
    return None


def parse_markdown_tickets(text: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish() -> None:
        nonlocal current
        if current:
            parsed.append(current)
            current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^#{1,6}\s+(?P<body>.+)$", line)
        if heading:
            candidate = ticket_from_line(heading.group("body"))
            if candidate:
                finish()
                current = candidate
            continue
        field = re.match(r"^(?:[-*]\s*)?(?P<key>depends_on|depends on|acceptance|acceptance_criteria|criteria|verification|verification_commands|evidence|related_commits|commits|blocker|status)\s*:\s*(?P<value>.+)$", line, re.I)
        if field and current is not None:
            key = field.group("key").lower().replace(" ", "_")
            key = {
                "acceptance": "acceptance_criteria",
                "criteria": "acceptance_criteria",
                "verification": "verification_commands",
                "commits": "related_commits",
            }.get(key, key)
            value = field.group("value").strip()
            if key in TICKET_LIST_FIELDS:
                current[key] = [*list_value(current.get(key)), *split_multi_value(value)]
            else:
                current[key] = value
            continue
        bullet_ticket = ticket_from_line(line)
        if bullet_ticket and (line.startswith(("-", "*")) or re.match(r"^\d+[.)]\s+", line)):
            finish()
            current = bullet_ticket
    finish()
    if parsed:
        return parsed
    return [ticket for raw in text.splitlines() if (ticket := ticket_from_line(raw))]


def parse_csv_tickets(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames:
        return []
    aliases = {
        "depends": "depends_on",
        "depends_on": "depends_on",
        "depends on": "depends_on",
        "acceptance": "acceptance_criteria",
        "criteria": "acceptance_criteria",
        "verification": "verification_commands",
        "checks": "verification_commands",
        "commits": "related_commits",
    }
    parsed: list[dict[str, Any]] = []
    for row in reader:
        item: dict[str, Any] = {}
        for raw_key, raw_value in row.items():
            if raw_key is None:
                continue
            normalized_key = raw_key.strip().lower().replace("-", "_")
            key = aliases.get(normalized_key, aliases.get(raw_key.strip().lower(), normalized_key))
            if key in TICKET_LIST_FIELDS:
                item[key] = split_multi_value(raw_value)
            elif key in TICKET_STRING_FIELDS:
                item[key] = str(raw_value or "").strip()
        if item:
            parsed.append(item)
    return parsed


def parse_json_tickets(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Ticket import JSON is malformed: {exc}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("tickets"), list):
        raw = payload["tickets"]
    elif isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        raw = [payload]
    else:
        raw = []
    return [item for item in raw if isinstance(item, dict)]


def parse_import_tickets(text: str, import_format: str) -> list[dict[str, Any]]:
    fmt = import_format.strip().lower()
    if fmt == "markdown":
        parsed = parse_markdown_tickets(text)
    elif fmt == "csv":
        parsed = parse_csv_tickets(text)
    elif fmt == "json":
        parsed = parse_json_tickets(text)
    else:
        raise SystemExit(f"Unsupported ticket import format: {import_format}")
    return normalized_tickets(parsed)


def default_import_mode(data: dict[str, Any]) -> str:
    items = tickets(data)
    return "replace-placeholder" if items and all(is_placeholder_ticket(item) for item in items) else "append"


def data_with_imported_tickets(data: dict[str, Any], imported: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    if mode not in TICKET_IMPORT_MODES:
        raise SystemExit(f"Unsupported ticket import mode: {mode}")
    next_data = dict(data)
    current = tickets(data)
    if mode == "replace-all":
        combined = imported
    elif mode == "replace-placeholder" and current and all(is_placeholder_ticket(item) for item in current):
        combined = imported
    else:
        combined = [*current, *imported]
    next_data["tickets"] = [normalize_ticket(item) for item in combined]
    return next_data


def read_ticket_json_arg(raw: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--ticket-json must be valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("--ticket-json must decode to a JSON object.")
    fallback = next_ticket_id(data or {"tickets": []}) if data is not None else None
    return normalize_ticket(payload, fallback_id=fallback)


def read_import_text(args: argparse.Namespace) -> str:
    provided = [bool(args.input_file), bool(args.input_text), bool(args.input_json)]
    if sum(1 for item in provided if item) != 1:
        raise SystemExit("Provide exactly one of --input-file, --input-text, or --input-json.")
    if args.input_file:
        return Path(args.input_file).expanduser().read_text(encoding="utf-8")
    if args.input_json:
        return str(args.input_json)
    return str(args.input_text)


def write_if_valid(
    target: Path,
    path: Path,
    text: str,
    data: dict[str, Any],
    *,
    allow_warnings: bool = True,
    actor_role: str = "dashboard",
    event_type: str = "ticket.run_updated",
) -> dict[str, Any]:
    issues = ticket_validation_issues(data)
    blocking = [issue for issue in issues if issue.get("level") == "error"]
    if blocking:
        return {"written": False, "ticket_file": str(path), "validation_issues": issues, **ticket_run_payload(data, target)}
    canonical_target = resolve_ticket_target(target)
    state_path = ticket_state_path(canonical_target)
    source_path = "" if path == state_path else str(path)
    staged_actions_path = ticket_state_actions_path(target)
    if staged_actions_path is not None and should_stage_ticket_actions(target):
        previous = load_ticket_run_state_for_staged_role(canonical_target) or empty_ticket_run(canonical_target)
        actions = staged_ticket_actions(previous, data)
        append_ticket_state_actions(staged_actions_path, actions)
        return {
            "written": True,
            "staged": True,
            "ticket_file": str(state_path),
            "ticket_store": str(state_path),
            "ticket_source": "typed_state_action",
            "ticket_actions_path": str(staged_actions_path),
            "staged_action_count": len(actions),
            "validation_issues": issues,
            **ticket_run_payload(data, canonical_target),
        }
    write_ticket_run_state(canonical_target, data, actor_role=actor_role, event_type=event_type, source_path=source_path)
    if source_path and text and path.exists():
        write_ticket_run_data(path, text, data)
    return {
        "written": True,
        "ticket_file": str(state_path),
        "ticket_store": str(state_path),
        "ticket_source": "sqlite",
        "validation_issues": issues,
        **ticket_run_payload(data, target),
    }


def command_status(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, _text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    summary = ticket_summary(data, target)
    payload = {"ticket_file": str(path), **summary}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{summary['status']}: {summary['counts'].get('done', 0)}/{summary['total']} done")
    return 0


def command_snapshot(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, _text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    canonical_target = resolve_ticket_target(target)
    payload = {
        "schema_version": 1,
        "ticket_file": str(path),
        "ticket_store": str(ticket_state_path(canonical_target)),
        "data": data,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(str(path))
    return 0


def command_list(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, _text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    payload = {"ticket_file": str(path), **ticket_run_payload(data, target)}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{len(payload['tickets'])} ticket(s) in {path}")
    return 0


def command_add(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    ticket = read_ticket_json_arg(args.ticket_json, data)
    next_data = dict(data)
    next_data["tickets"] = [*tickets(data), ticket]
    payload = write_if_valid(target, path, text, next_data)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("added" if payload["written"] else "not written")
    return 0 if payload["written"] else 1


def command_update(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    replacement = read_ticket_json_arg(args.ticket_json)
    target_id = str(args.ticket_id or "").strip()
    updated = False
    next_items: list[dict[str, Any]] = []
    for item in tickets(data):
        if str(item.get("id") or "").strip() == target_id:
            merged = {**item, **replacement}
            merged["id"] = target_id
            next_items.append(normalize_ticket(merged))
            updated = True
        else:
            next_items.append(item)
    if not updated:
        raise SystemExit(f"Ticket id not found: {target_id}")
    next_data = dict(data)
    next_data["tickets"] = next_items
    payload = write_if_valid(target, path, text, next_data)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("updated" if payload["written"] else "not written")
    return 0 if payload["written"] else 1


def command_delete(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    target_id = str(args.ticket_id or "").strip()
    current = tickets(data)
    next_items = [item for item in current if str(item.get("id") or "").strip() != target_id]
    if len(next_items) == len(current):
        raise SystemExit(f"Ticket id not found: {target_id}")
    next_data = dict(data)
    next_data["tickets"] = next_items
    payload = write_if_valid(target, path, text, next_data)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("deleted" if payload["written"] else "not written")
    return 0 if payload["written"] else 1


def command_import(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    imported = parse_import_tickets(read_import_text(args), args.format)
    mode = args.mode or default_import_mode(data)
    next_data = data_with_imported_tickets(data, imported, mode)
    payload: dict[str, Any] = {
        "written": False,
        "preview": bool(args.preview),
        "ticket_file": str(path),
        "imported_count": len(imported),
        "mode": mode,
        "imported_tickets": imported,
        **ticket_run_payload(next_data, target),
    }
    if not args.preview:
        write_payload = write_if_valid(target, path, text, next_data)
        payload.update(write_payload)
        payload["imported_count"] = len(imported)
        payload["mode"] = mode
        payload["imported_tickets"] = imported
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(("previewed" if args.preview else "imported") + f" {len(imported)} ticket(s)")
    return 0 if args.preview or payload.get("written") else 1


def command_next(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, _text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    payload = {"ticket_file": str(path), **next_ticket_selection(data)}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        ticket = payload.get("ticket")
        if isinstance(ticket, dict):
            print(f"{payload['action']}: {ticket['id']}")
        else:
            print(str(payload["reason"]))
    return 0


def data_with_claimed_next_ticket(
    data: dict[str, Any],
    *,
    actor_role: str = "",
    run_id: str = "",
    claimed_at: str = "",
) -> tuple[dict[str, Any], dict[str, Any], str]:
    selection = next_ticket_selection(data)
    selected = selection.get("ticket") if isinstance(selection.get("ticket"), dict) else {}
    ticket_id = str(selected.get("id") or "").strip()
    action = str(selection.get("action") or "")
    if action != "implement_pending" or not ticket_id:
        return data, selection, "next ticket is not a pending implementation ticket"

    next_items: list[dict[str, Any]] = []
    claimed = False
    for item in tickets(data):
        if str(item.get("id") or "").strip() == ticket_id and normalize_status(item.get("status")) == "pending":
            claimed_item = dict(item)
            claimed_item["status"] = "in_progress"
            claimed_item["claimed_at"] = claimed_at or utc_now()
            if actor_role:
                claimed_item["claimed_by"] = actor_role
            if run_id:
                claimed_item["claimed_run_id"] = run_id
            next_items.append(claimed_item)
            claimed = True
        else:
            next_items.append(item)
    if not claimed:
        return data, selection, "selected ticket is no longer pending"
    next_data = dict(data)
    next_data["tickets"] = next_items
    return next_data, selection, "claimed pending ticket"


def command_claim_next(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    data, path, text = load_ticket_run(target, Path(args.ticket_file).resolve() if args.ticket_file else None)
    next_data, selection, claim_reason = data_with_claimed_next_ticket(
        data,
        actor_role=str(args.role or "").strip(),
        run_id=str(args.run_id or "").strip(),
    )
    claimed = next_data is not data
    payload: dict[str, Any] = {
        "ticket_file": str(path),
        "claimed": claimed,
        "claim_reason": claim_reason,
        "claim_role": str(args.role or "").strip(),
        "claim_run_id": str(args.run_id or "").strip(),
        "selected": selection,
    }
    if claimed:
        payload.update(
            write_if_valid(
                target,
                path,
                text,
                next_data,
                actor_role=str(args.role or "").strip() or "ticket-cli",
                event_type="ticket.claimed",
            )
        )
    else:
        payload.update(ticket_run_payload(data, target))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        selected = selection.get("ticket") if isinstance(selection.get("ticket"), dict) else {}
        ticket_id = str(selected.get("id") or "").strip()
        if claimed and ticket_id:
            print(f"claimed: {ticket_id}")
        else:
            print(claim_reason)
    return 0 if not claimed or payload.get("written") else 1


def command_should_halt(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    ticket_file = Path(args.ticket_file).resolve() if args.ticket_file else None
    data, path, _text = load_ticket_run(target, ticket_file)
    summary = ticket_summary(data, target)
    payload: dict[str, Any] = {"ticket_file": str(path), **summary}
    if args.finalize and summary["should_halt"]:
        payload = finalize(target, ticket_file=ticket_file)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if summary["should_halt"] else 1


def command_finalize(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    payload = finalize(target, ticket_file=Path(args.ticket_file).resolve() if args.ticket_file else None)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload.get("reason") or payload.get("status") or "ticket campaign active")
    return 0 if payload.get("finalized") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("--ticket-file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Summarize the ticket campaign.")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    snapshot = subparsers.add_parser("snapshot", help="Write a readonly ticket-state snapshot.")
    snapshot.add_argument("--json", action="store_true")
    snapshot.set_defaults(func=command_snapshot)

    list_parser = subparsers.add_parser("list", help="List tickets and validation state.")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=command_list)

    add_parser = subparsers.add_parser("add", help="Add one normalized ticket.")
    add_parser.add_argument("--ticket-json", required=True)
    add_parser.add_argument("--json", action="store_true")
    add_parser.set_defaults(func=command_add)

    update_parser = subparsers.add_parser("update", help="Update one ticket by id.")
    update_parser.add_argument("--ticket-id", required=True)
    update_parser.add_argument("--ticket-json", required=True)
    update_parser.add_argument("--json", action="store_true")
    update_parser.set_defaults(func=command_update)

    delete_parser = subparsers.add_parser("delete", help="Delete one ticket by id.")
    delete_parser.add_argument("--ticket-id", required=True)
    delete_parser.add_argument("--json", action="store_true")
    delete_parser.set_defaults(func=command_delete)

    import_parser = subparsers.add_parser("import", help="Import tickets from Markdown, CSV, or JSON.")
    import_parser.add_argument("--format", choices=sorted(TICKET_IMPORT_FORMATS), required=True)
    import_parser.add_argument("--mode", choices=sorted(TICKET_IMPORT_MODES))
    import_parser.add_argument("--input-file", default="")
    import_parser.add_argument("--input-json", default="")
    import_parser.add_argument("--input-text", default="")
    import_parser.add_argument("--preview", action="store_true")
    import_parser.add_argument("--json", action="store_true")
    import_parser.set_defaults(func=command_import)

    next_parser = subparsers.add_parser("next", help="Select the next dependency-ready ticket without writing files.")
    next_parser.add_argument("--json", action="store_true")
    next_parser.set_defaults(func=command_next)

    claim_next = subparsers.add_parser("claim-next", help="Mark the next pending ticket as in_progress for a role run.")
    claim_next.add_argument("--role", default="builder")
    claim_next.add_argument("--run-id", default="")
    claim_next.add_argument("--json", action="store_true")
    claim_next.set_defaults(func=command_claim_next)

    should_halt = subparsers.add_parser("should-halt", help="Exit 0 when the campaign should halt.")
    should_halt.add_argument("--finalize", action="store_true")
    should_halt.add_argument("--json", action="store_true")
    should_halt.set_defaults(func=command_should_halt)

    finalize_parser = subparsers.add_parser("finalize", help="Write the final report and notification state.")
    finalize_parser.add_argument("--json", action="store_true")
    finalize_parser.set_defaults(func=command_finalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "target", None):
        args.target = str(resolve_ticket_target(Path(args.target)))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
