#!/usr/bin/env python3
"""Manage bounded Diffmogger ticket-campaign runs."""

from __future__ import annotations

import argparse
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

from diffmogger_paths import existing_or_target_path, target_path


DEFAULT_TICKET_FILE = "docs/TICKET_RUN.md"
COMPLETION_STATE = "target/ticket_run_completion.json"
NOTIFIER_URL = "http://127.0.0.1:8765/api/notify"
TICKET_STATUSES = {"pending", "in_progress", "candidate_done", "done", "blocked"}
TERMINAL_STATUSES = {"done", "blocked"}
FENCE_RE = re.compile(r"```(?:json\s+ticket-run|ticket-run-json)\s*\n(.*?)\n```", re.DOTALL)
PLACEHOLDER_TICKET_ID = "TICKET-001"
PLACEHOLDER_TICKET_SUMMARY = "Replace this sample with the first startup ticket."


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def project_intake(target: Path) -> dict[str, Any]:
    return read_json(existing_or_target_path(target, ".agentic/project_intake.json"))


def ticket_file_path(target: Path) -> Path:
    intake = project_intake(target)
    configured = str(intake.get("ticket_run_file") or "").strip()
    if configured:
        return target / configured
    return target_path(target, DEFAULT_TICKET_FILE)


def load_ticket_run(target: Path, ticket_file: Path | None = None) -> tuple[dict[str, Any], Path, str]:
    path = ticket_file or ticket_file_path(target)
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
        return [value.strip()]
    return []


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
            "reason": "ticket source has no tickets",
            "ticket": None,
            "selection_order": [entry[0] for entry in order],
            **report,
        }
    if len(report["placeholder_tickets"]) == len(items):
        return {
            "status": "blocked",
            "reason": "ticket source still contains placeholder tickets",
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
    path = target_path(target, "docs/HUMAN_OUTBOX.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Human Outbox\n"
    entry = (
        f"\n## {utc_now()} ticket-run-notification\n\n"
        f"- status: {status}\n"
        f"- detail: {detail}\n"
        f"- message_body: {message}\n"
    )
    path.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8")


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


def command_should_halt(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    path = Path(args.ticket_file).resolve() if args.ticket_file else ticket_file_path(target)
    if not path.exists():
        if args.json:
            print(json.dumps({"status": "inactive", "should_halt": False, "ticket_file": str(path)}, indent=2))
        return 1
    data, path, _text = load_ticket_run(target, path)
    summary = ticket_summary(data, target)
    payload: dict[str, Any] = {"ticket_file": str(path), **summary}
    if args.finalize and summary["should_halt"]:
        payload = finalize(target, ticket_file=path)
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

    next_parser = subparsers.add_parser("next", help="Select the next dependency-ready ticket without writing files.")
    next_parser.add_argument("--json", action="store_true")
    next_parser.set_defaults(func=command_next)

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
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
