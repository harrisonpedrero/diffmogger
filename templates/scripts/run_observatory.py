#!/usr/bin/env python3
"""Run a local visual observatory for Diffmogger automation state."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROLES = ("planner", "builder", "hardener", "integrator")
QUEUE_STATUSES = ("queued", "deferred", "applied", "failed", "skipped")
MAX_MANIFESTS = 18
MAX_OUTCOMES = 12
MAX_HISTORY = 14
MAX_LOG_FILES = 8
MAX_LOG_LINE_CHARS = 220
MAX_SIGNALS = 8
MAX_REVIEW_ITEMS = 6
MAX_CHECK_ITEMS = 8


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
    text = re.sub(r"\s+", " ", str(value or "")).strip()
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


def validation_snapshot(text: str) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    counts = {"pass": 0, "fail": 0, "warn": 0, "pending": 0, "info": 0}
    for bullet in section_bullets(text, "Checks From Last Run", limit=MAX_CHECK_ITEMS):
        lower = bullet.lower()
        if lower.startswith("preferred commands"):
            continue
        if bullet.startswith("`") and any(item["status"] == "pending" for item in checks):
            continue
        status = "info"
        if lower.startswith("pass"):
            status = "pass"
        elif lower.startswith("fail"):
            status = "fail"
        elif lower.startswith("warn"):
            status = "warn"
        elif "not run" in lower:
            status = "pending"
        counts[status] += 1
        checks.append({"status": status, "text": bullet})

    if not checks:
        return {
            "summary": "No validation results recorded yet.",
            "counts": counts,
            "items": [],
        }

    if counts["fail"]:
        summary = f"{counts['pass']} pass, {counts['fail']} fail or environment note."
    elif counts["pass"]:
        summary = f"{counts['pass']} passing check(s) recorded."
    elif counts["pending"]:
        summary = "Validation is recorded as not run yet."
    else:
        summary = "Validation notes are recorded without pass/fail status."
    return {"summary": summary, "counts": counts, "items": checks}


def count_section_matches(path: Path, heading: str, pattern: str) -> int:
    section = markdown_section(read_text(path), heading)
    return len(re.findall(pattern, section, re.MULTILINE | re.IGNORECASE))


def count_section_records_with_status(
    path: Path,
    heading: str,
    record_heading_pattern: str,
    active_statuses: set[str],
) -> int:
    section = markdown_section(read_text(path), heading)
    matches = list(re.finditer(record_heading_pattern, section, re.MULTILINE | re.IGNORECASE))
    count = 0
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        record = section[match.end() : next_start]
        status_match = re.search(r"^-\s*status:\s*([A-Za-z0-9_-]+)", record, re.MULTILINE | re.IGNORECASE)
        status = status_match.group(1).lower() if status_match else ""
        if status in active_statuses:
            count += 1
    return count


def parse_task_state(target: Path) -> dict[str, Any]:
    text = read_text(target / "docs" / "CODEX_AUTOMATION_TASKS.md")
    status = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", text, re.MULTILINE)
    updated = re.search(r"^Last updated:\s*(.+)", text, re.MULTILINE)
    horizon = re.search(r"^-\s*Current horizon:\s*(.+)", text, re.MULTILINE)
    decision = re.search(r"^-\s*Advancement decision:\s*(.+)", text, re.MULTILINE)
    current_assessment = keyed_section_value(
        text,
        "Current Project State",
        ["Current assessment", "Current baseline", "Goal"],
    )
    return {
        "status": status.group(1).strip() if status else "UNKNOWN",
        "last_updated": clean_text(updated.group(1), limit=120) if updated else "unknown",
        "horizon": clean_text(horizon.group(1), limit=160) if horizon else "unknown",
        "horizon_decision": clean_text(decision.group(1), limit=160) if decision else "unknown",
        "current_assessment": current_assessment or first_nonempty_section_line(text, "Current Project State") or "No current assessment recorded yet.",
        "best_next_milestone": first_nonempty_section_line(text, "Best Next Milestone") or "No milestone recorded yet.",
        "suggested_next_task": first_nonempty_section_line(text, "Suggested Next Sprint-Sized Task") or "No sprint task recorded yet.",
        "known_issue": first_nonempty_section_line(text, "Known Issues") or "No active issue summary.",
        "known_issues": section_bullets(text, "Known Issues", limit=MAX_REVIEW_ITEMS),
        "validation": validation_snapshot(text),
    }


def queue_snapshot(target: Path) -> dict[str, Any]:
    queue_root = target / "target" / "automation_queue"
    counts: dict[str, dict[str, int]] = {
        role: {status: 0 for status in QUEUE_STATUSES} for role in ROLES
    }
    totals = {status: 0 for status in QUEUE_STATUSES}
    manifests: list[dict[str, Any]] = []

    for manifest_path in sorted(queue_root.glob("*/*/manifest.json")):
        manifest = read_json(manifest_path)
        role = str(manifest.get("role") or manifest_path.parent.parent.name)
        if role not in counts:
            continue
        status = str(manifest.get("status") or "unknown")
        if status in counts[role]:
            counts[role][status] += 1
            totals[status] += 1
        timestamp = manifest.get("integrated_at") or manifest.get("created_at") or ""
        manifests.append(
            {
                "role": role,
                "run_id": clean_text(manifest.get("run_id") or manifest_path.parent.name, limit=80),
                "status": status,
                "created_at": clean_text(manifest.get("created_at"), limit=80),
                "timestamp": clean_text(timestamp, limit=80),
                "summary": clean_text(manifest.get("summary") or "No summary.", limit=180),
                "deferral_reason": clean_text(manifest.get("deferral_reason"), limit=80),
                "changed_files": [
                    clean_text(item, limit=80)
                    for item in list(manifest.get("changed_files") or [])[:5]
                ],
            }
        )

    def manifest_sort_key(item: dict[str, Any]) -> tuple[int, str]:
        status_rank = {"queued": 0, "deferred": 1}.get(str(item.get("status")), 4)
        return status_rank, str(item.get("timestamp") or item.get("created_at") or "")

    actionable = [item for item in manifests if item.get("status") in {"queued", "deferred"}]
    outcomes = [item for item in manifests if item.get("status") in {"applied", "failed", "skipped"}]

    return {
        "counts_by_role": counts,
        "totals": totals,
        "manifests": sorted(actionable, key=manifest_sort_key)[:MAX_MANIFESTS],
        "recent_outcomes": sorted(
            outcomes,
            key=lambda item: str(item.get("timestamp") or item.get("created_at") or ""),
            reverse=True,
        )[:MAX_OUTCOMES],
    }


def git_snapshot(target: Path) -> dict[str, Any]:
    def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(target),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
            check=False,
        )

    branch_result = run_git(["branch", "--show-current"])
    status_result = run_git(["status", "--short"])
    log_result = run_git(["log", "--oneline", "-5"])
    dirty_lines = [line for line in (status_result.stdout or "").splitlines() if line.strip()]
    return {
        "branch": clean_text(branch_result.stdout.strip() or "unknown", limit=80) if branch_result.returncode == 0 else "unknown",
        "dirty_count": len(dirty_lines) if status_result.returncode == 0 else 0,
        "recent_commits": [
            clean_text(line, limit=120)
            for line in (log_result.stdout or "").splitlines()
            if line.strip()
        ][:5]
        if log_result.returncode == 0
        else [],
    }


def log_snapshot(target: Path) -> list[dict[str, Any]]:
    log_dir = target / "target" / "automation_logs"
    if not log_dir.exists():
        return []
    files = sorted(
        [path for path in log_dir.glob("*.log") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    for path in files[:MAX_LOG_FILES]:
        text = read_tail_text(path)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        items.append(
            {
                "name": path.name,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                "tail": clean_text(lines[-1] if lines else "No log lines yet.", limit=MAX_LOG_LINE_CHARS),
            }
        )
    return items


def signals_snapshot(target: Path) -> dict[str, Any]:
    data = read_json(target / "target" / "automation_signals.json")
    raw_signals = data.get("signals") if isinstance(data.get("signals"), list) else []
    priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    active: list[dict[str, Any]] = []
    recent_completed: list[dict[str, Any]] = []

    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        item = {
            "id": clean_text(raw.get("id") or "unknown", limit=80),
            "owner_role": clean_text(raw.get("owner_role") or "unknown", limit=40),
            "priority": clean_text(raw.get("priority") or "medium", limit=40),
            "cadence": clean_text(raw.get("cadence") or "unknown", limit=60),
            "instructions": clean_text(raw.get("instructions") or "No instructions recorded.", limit=180),
            "next_due_at": clean_text(raw.get("next_due_at") or "", limit=80),
            "last_completed_at": clean_text(raw.get("last_completed_at") or "", limit=80),
            "last_completed_by": clean_text(raw.get("last_completed_by") or "", limit=40),
        }
        if raw.get("active"):
            active.append(item)
        if raw.get("last_completed_at"):
            recent_completed.append(item)

    active.sort(
        key=lambda item: (
            priority_rank.get(str(item.get("priority")).lower(), 4),
            str(item.get("next_due_at") or ""),
            str(item.get("id") or ""),
        )
    )
    recent_completed.sort(key=lambda item: str(item.get("last_completed_at") or ""), reverse=True)
    return {
        "active_count": len(active),
        "active": active[:MAX_SIGNALS],
        "recent_completed": recent_completed[:MAX_SIGNALS],
        "updated_at": clean_text(data.get("updated_at") or "never", limit=80),
    }


def decision_queue(conveyor: dict[str, Any], queue: dict[str, Any]) -> list[dict[str, Any]]:
    raw = conveyor.get("decision_queue")
    if isinstance(raw, list) and raw:
        return [
            {
                "role": clean_text(item.get("role") or "idle", limit=40),
                "state": clean_text(item.get("state") or "planned", limit=40),
                "reason": clean_text(item.get("reason") or "", limit=180),
            }
            for item in raw[:8]
            if isinstance(item, dict)
        ]

    last = conveyor.get("last_decision") if isinstance(conveyor.get("last_decision"), dict) else {}
    role = str(last.get("role") or "idle")
    reason = str(last.get("reason") or "No conveyor decision recorded yet.")
    entries = [{"role": role, "state": "next", "reason": clean_text(reason, limit=180)}]
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}
    if int(totals.get("queued", 0) or 0):
        entries.insert(0, {"role": "integrator", "state": "ready", "reason": f"{totals.get('queued')} queued patch(es) need integration"})
    return entries[:8]


def active_run(conveyor: dict[str, Any]) -> dict[str, Any]:
    active = conveyor.get("active_role_run")
    if not isinstance(active, dict):
        return {}
    alive = process_alive(active.get("pid"))
    return {
        "role": clean_text(active.get("role") or "unknown", limit=40),
        "run_id": clean_text(active.get("run_id") or "unknown", limit=80),
        "reason": clean_text(active.get("reason") or "", limit=180),
        "started_at": clean_text(active.get("started_at") or "", limit=80),
        "pid": active.get("pid"),
        "alive": alive,
        "status": "running" if alive else "stale",
    }


def conveyor_health(conveyor: dict[str, Any]) -> dict[str, Any]:
    history = conveyor.get("history") if isinstance(conveyor.get("history"), list) else []
    roles = [
        str(item.get("role") or "")
        for item in history
        if isinstance(item, dict) and item.get("role")
    ]
    recent = roles[-6:]
    churn_sequences = (
        ["hardener", "integrator", "hardener", "integrator"],
        ["integrator", "hardener", "integrator", "hardener"],
    )
    churn = any(recent[-4:] == sequence for sequence in churn_sequences) if len(recent) >= 4 else False
    if churn:
        return {
            "status": "warning",
            "summary": "hardener/integrator churn detected; builder-first policy should route the next idle cycle to builder.",
            "recent_roles": recent,
        }
    return {
        "status": "ok",
        "summary": "builder-first conveyor policy active; hardener runs once after integrated builder work.",
        "recent_roles": recent,
    }


def progress_snapshot(progress_text: str) -> dict[str, Any]:
    deferred_depth = 0
    match = re.search(r"^-\s*Current deferred queue depth:\s*(\d+)", progress_text, re.MULTILINE)
    if match:
        deferred_depth = int(match.group(1))
    return {
        "recent_activity": first_nonempty_section_line(progress_text, "Recent Activity Log") or "No multi-role activity recorded yet.",
        "deferred_queue_depth": deferred_depth,
        "deferred_backlog": section_bullets(progress_text, "Deferred-Patch Backlog", limit=MAX_REVIEW_ITEMS),
    }


def self_review_snapshot(
    task: dict[str, Any],
    queue: dict[str, Any],
    signals: dict[str, Any],
    conveyor: dict[str, Any],
    human: dict[str, int],
    progress: dict[str, Any],
) -> dict[str, Any]:
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}
    queued = int(totals.get("queued", 0) or 0)
    deferred = int(totals.get("deferred", 0) or 0)
    progress_deferred = int(progress.get("deferred_queue_depth", 0) or 0)
    if queued or deferred or progress_deferred:
        queue_parts = [f"{queued} queued", f"{deferred} deferred manifest(s)"]
        if progress_deferred and progress_deferred != deferred:
            queue_parts.append(f"progress file reports {progress_deferred} deferred backlog item(s)")
        queue_summary = "; ".join(queue_parts) + "."
    else:
        queue_summary = "No queued or deferred role patches."

    active_signals = signals.get("active") if isinstance(signals.get("active"), list) else []
    if active_signals:
        names = [
            f"{item.get('id', 'signal')} ({item.get('owner_role', 'unknown')})"
            for item in active_signals[:3]
            if isinstance(item, dict)
        ]
        signal_summary = f"{signals.get('active_count', len(active_signals))} active: {', '.join(names)}."
    else:
        signal_summary = "No active signal nudges."

    active_run = conveyor.get("active_role_run") if isinstance(conveyor.get("active_role_run"), dict) else {}
    if active_run.get("role"):
        reason = clean_text(active_run.get("reason") or "no reason recorded", limit=160).rstrip(".")
        conveyor_summary = f"{active_run.get('role')} is {active_run.get('status', 'recorded')}: {reason}."
    else:
        decisions = conveyor.get("decision_queue") if isinstance(conveyor.get("decision_queue"), list) else []
        if decisions:
            first = decisions[0] if isinstance(decisions[0], dict) else {}
            reason = clean_text(first.get("reason") or "no reason recorded", limit=160).rstrip(".")
            conveyor_summary = f"Next lane: {first.get('role', 'idle')} ({first.get('state', 'planned')}) - {reason}."
        else:
            conveyor_summary = "No conveyor decision recorded yet."

    pending_human = int(human.get("pending_requests", 0) or 0)
    inbox = int(human.get("unhandled_inbox", 0) or 0)
    human_summary = (
        f"{pending_human} pending request(s), {inbox} unhandled inbox message(s)."
        if pending_human or inbox
        else "No pending human requests or unhandled inbox messages."
    )

    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    return {
        "items": [
            {"label": "Current assessment", "body": task.get("current_assessment") or "No current assessment recorded yet."},
            {"label": "Validation", "body": validation.get("summary") or "No validation results recorded yet."},
            {"label": "Signals", "body": signal_summary},
            {"label": "Queue and conveyor", "body": f"{queue_summary} {conveyor_summary}"},
            {"label": "Human bridge", "body": human_summary},
            {"label": "Next sprint", "body": task.get("suggested_next_task") or "No sprint task recorded yet."},
        ],
        "checks": list(validation.get("items") or [])[:MAX_CHECK_ITEMS],
        "known_issues": list(task.get("known_issues") or [])[:MAX_REVIEW_ITEMS],
    }


def build_snapshot(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    conveyor = read_json(target / "target" / "automation_conveyor_state.json")
    queue = queue_snapshot(target)
    task = parse_task_state(target)
    progress_text = read_text(target / "docs" / "MULTI_ROLE_PROGRESS.md", limit=40_000)
    progress = progress_snapshot(progress_text)
    human = {
        "pending_requests": count_section_records_with_status(
            target / "docs" / "HUMAN_REQUESTS.md",
            "Active Requests",
            r"^###\s+HR-",
            {"awaiting_user"},
        ),
        "unhandled_inbox": count_section_matches(target / "docs" / "HUMAN_INBOX.md", "Active Inbound Messages", r"status:\s*unhandled"),
        "outbound_records": count_section_matches(target / "docs" / "HUMAN_OUTBOX.md", "Outbound Records", r"^###\s+OUTBOX-"),
    }
    signals = signals_snapshot(target)
    conveyor_state = {
        "cycles": int(conveyor.get("cycles", 0) or 0),
        "updated_at": clean_text(conveyor.get("updated_at") or "never", limit=80),
        "last_decision": conveyor.get("last_decision") if isinstance(conveyor.get("last_decision"), dict) else {},
        "active_role_run": active_run(conveyor),
        "last_active_role_run": conveyor.get("last_active_role_run") if isinstance(conveyor.get("last_active_role_run"), dict) else {},
        "decision_queue": decision_queue(conveyor, queue),
        "health": conveyor_health(conveyor),
        "no_progress": conveyor.get("integrator_no_progress") if isinstance(conveyor.get("integrator_no_progress"), dict) else {},
        "history": list(conveyor.get("history") or [])[-MAX_HISTORY:] if isinstance(conveyor.get("history"), list) else [],
    }
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "target_name": target.name or "target",
        "task": task,
        "human": human,
        "git": git_snapshot(target),
        "queue": queue,
        "signals": signals,
        "conveyor": conveyor_state,
        "progress": progress,
        "review": self_review_snapshot(task, queue, signals, conveyor_state, human, progress),
        "progress_recent": progress.get("recent_activity") or "No multi-role activity recorded yet.",
        "logs": log_snapshot(target),
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Diffmogger Observatory</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101214;
      --panel: #181c20;
      --panel-2: #20262b;
      --text: #f3f1e8;
      --muted: #a8b0aa;
      --line: #333b40;
      --green: #57c785;
      --blue: #67a6ff;
      --amber: #f0b84f;
      --red: #ff6b6b;
      --violet: #b993ff;
      --cyan: #59d0cf;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    header {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 24px;
      align-items: end;
      padding: 24px 28px 18px;
      border-bottom: 1px solid var(--line);
      background: #13171a;
    }
    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 56px);
      line-height: .95;
      letter-spacing: 0;
    }
    .subtitle {
      margin-top: 10px;
      color: var(--muted);
      max-width: 780px;
      font-size: 15px;
    }
    .clock {
      min-width: 260px;
      text-align: right;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }
    main {
      display: grid;
      grid-template-columns: minmax(300px, 1.1fr) minmax(420px, 1.8fr) minmax(300px, 1fr);
      gap: 16px;
      padding: 16px;
    }
    section, .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    section > h2 {
      margin: 0;
      padding: 12px 14px;
      font-size: 13px;
      letter-spacing: 0;
      color: var(--muted);
      text-transform: uppercase;
      border-bottom: 1px solid var(--line);
      background: var(--panel-2);
    }
    .stack { display: grid; gap: 16px; align-content: start; }
    .content { padding: 14px; }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #15191c;
      min-height: 88px;
    }
    .metric b {
      display: block;
      font-size: 26px;
      line-height: 1;
      font-variant-numeric: tabular-nums;
    }
    .metric span {
      display: block;
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .belt {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 14px;
    }
    .role {
      position: relative;
      min-height: 154px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #14181b;
    }
    .role.running {
      border-color: var(--green);
      box-shadow: 0 0 0 1px rgba(87,199,133,.35) inset;
    }
    .role.next {
      border-color: var(--blue);
    }
    .role h3 {
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
      text-transform: capitalize;
    }
    .role .state {
      margin-top: 10px;
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 4px 8px;
      border-radius: 999px;
      color: #08100c;
      background: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .role.running .state { background: var(--green); }
    .role.next .state { background: var(--blue); color: #07111f; }
    .role .counts {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }
    .active-run {
      margin: 0 14px 14px;
      padding: 14px;
      border: 1px solid rgba(87,199,133,.45);
      border-radius: 8px;
      background: rgba(87,199,133,.08);
    }
    .active-run strong { color: var(--green); }
    .queue-list, .timeline, .logs { display: grid; gap: 10px; }
    .health {
      margin: 0 14px 14px;
      padding: 12px 14px;
      border: 1px solid rgba(87,199,133,.45);
      border-radius: 8px;
      background: rgba(87,199,133,.07);
      color: var(--muted);
    }
    .health.warning {
      border-color: rgba(240,184,79,.65);
      background: rgba(240,184,79,.09);
    }
    .health strong { display: block; color: var(--green); margin-bottom: 4px; }
    .health.warning strong { color: var(--amber); }
    .item {
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #14181b;
    }
    .item-title {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 6px;
      font-weight: 700;
    }
    .muted { color: var(--muted); }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
    .chip {
      display: inline-flex;
      min-height: 24px;
      align-items: center;
      padding: 3px 7px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
    }
    .chip.queued { color: var(--blue); border-color: rgba(103,166,255,.5); }
    .chip.deferred { color: var(--amber); border-color: rgba(240,184,79,.5); }
    .chip.failed { color: var(--red); border-color: rgba(255,107,107,.5); }
    .chip.applied { color: var(--green); border-color: rgba(87,199,133,.5); }
    .chip.skipped { color: var(--muted); border-color: rgba(168,176,170,.45); }
    .mission {
      display: grid;
      gap: 12px;
    }
    .mission p { margin: 0; color: var(--muted); }
    .mission strong { display: block; color: var(--text); margin-bottom: 4px; }
    .review-list, .check-list {
      display: grid;
      gap: 10px;
    }
    .check-list {
      margin-top: 12px;
    }
    .status-line {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    .status-pill {
      padding: 6px 9px;
      border-radius: 999px;
      background: #111518;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
    .status-pill.good { color: var(--green); }
    .status-pill.warn { color: var(--amber); }
    .status-pill.info { color: var(--cyan); }
    .progress-note {
      color: var(--muted);
      min-height: 72px;
    }
    .signal-list {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }
    .signal-meta {
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    @media (max-width: 1180px) {
      main { grid-template-columns: 1fr; }
      .belt { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      header { grid-template-columns: 1fr; }
      .clock { text-align: left; min-width: 0; }
    }
    @media (max-width: 640px) {
      main { padding: 10px; }
      header { padding: 18px 16px 14px; }
      .belt, .metric-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>Diffmogger Observatory</h1>
        <div class="subtitle" id="subtitle">Local automation telemetry for a running target.</div>
      </div>
      <div class="clock">
        <div id="generated">Waiting for state...</div>
        <div id="targetName"></div>
      </div>
    </header>
    <main>
      <div class="stack">
        <section>
          <h2>Mission State</h2>
          <div class="content mission" id="mission"></div>
        </section>
        <section>
          <h2>Self Review</h2>
          <div class="content">
            <div class="review-list" id="selfReview"></div>
            <div class="check-list" id="checkList"></div>
          </div>
        </section>
        <section>
          <h2>Signals</h2>
          <div class="content">
            <div class="metric-grid" id="metrics"></div>
            <div class="signal-list" id="signalsList"></div>
          </div>
        </section>
        <section>
          <h2>Recent Logs</h2>
          <div class="content logs" id="logs"></div>
        </section>
      </div>
      <div class="stack">
        <section>
          <h2>Conveyor Belt</h2>
          <div class="belt" id="belt"></div>
          <div id="activeRun"></div>
        </section>
        <section>
          <h2>Conveyor Health</h2>
          <div class="content" id="health"></div>
        </section>
        <section>
          <h2>Next Up</h2>
          <div class="content queue-list" id="nextUp"></div>
        </section>
        <section>
          <h2>Patch Queue</h2>
          <div class="content queue-list" id="patches"></div>
        </section>
        <section>
          <h2>Recent Outcomes</h2>
          <div class="content queue-list" id="outcomes"></div>
        </section>
      </div>
      <div class="stack">
        <section>
          <h2>Timeline</h2>
          <div class="content timeline" id="timeline"></div>
        </section>
        <section>
          <h2>Progress Pulse</h2>
          <div class="content progress-note" id="progress"></div>
        </section>
        <section>
          <h2>Local Repo</h2>
          <div class="content" id="repo"></div>
        </section>
      </div>
    </main>
  </div>
  <script>
    const INITIAL_STATE = __INITIAL_STATE__;
    const STATE_URL = __STATE_URL__;
    const ROLES = ["planner", "builder", "hardener", "integrator"];

    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function clear(node) {
      while (node.firstChild) node.removeChild(node.firstChild);
    }

    function renderMetric(label, value) {
      const node = el("div", "metric");
      node.appendChild(el("b", "", String(value)));
      node.appendChild(el("span", "", label));
      return node;
    }

    function historyLabel(item) {
      if (!item.progress_success) return "no progress";
      const role = item.role || "";
      if (role === "integrator") {
        const accepted = ((item.metadata || {}).accepted_by_role) || {};
        const total = Object.values(accepted).reduce((sum, value) => sum + Number(value || 0), 0);
        return total ? "accepted " + total : "integrated";
      }
      if (role === "planner") return "planned";
      if (role === "builder") return "built";
      if (role === "hardener") return "hardened";
      return "progress";
    }

    function acceptedRoleText(item) {
      const accepted = ((item.metadata || {}).accepted_by_role) || {};
      const parts = Object.entries(accepted).filter(([, value]) => Number(value || 0) > 0).map(([role, value]) => role + ": " + value);
      return parts.length ? "accepted by role: " + parts.join(", ") : "";
    }

    function renderManifest(item) {
      const row = el("div", "item");
      const title = el("div", "item-title");
      title.appendChild(el("span", "", item.role + " / " + item.run_id));
      title.appendChild(el("span", "chip " + item.status, item.status));
      row.appendChild(title);
      row.appendChild(el("div", "", item.summary || "No summary."));
      if (item.deferral_reason) row.appendChild(el("div", "muted", "deferral: " + item.deferral_reason));
      const chips = el("div", "chips");
      (item.changed_files || []).forEach(file => chips.appendChild(el("span", "chip", file)));
      if (chips.children.length) row.appendChild(chips);
      return row;
    }

    function checkChipClass(status) {
      if (status === "pass") return "applied";
      if (status === "fail") return "failed";
      if (status === "warn") return "deferred";
      if (status === "pending") return "queued";
      return "skipped";
    }

    function render(data) {
      document.getElementById("generated").textContent = "Updated " + (data.generated_at || "now");
      document.getElementById("targetName").textContent = data.target_name || "target";
      document.getElementById("subtitle").textContent = "Conveyor, queue, role, and verification state for " + (data.target_name || "the selected target") + ".";

      const mission = document.getElementById("mission");
      clear(mission);
      [
        ["Automation status", data.task.status],
        ["Current horizon", data.task.horizon],
        ["Best next milestone", data.task.best_next_milestone],
        ["Suggested next task", data.task.suggested_next_task],
        ["Known issue", data.task.known_issue]
      ].forEach(([title, body]) => {
        const p = el("p");
        p.appendChild(el("strong", "", title));
        p.appendChild(document.createTextNode(body || "unknown"));
        mission.appendChild(p);
      });
      const pills = el("div", "status-line");
      const statusClass = (data.task.status || "").startsWith("ACTIVE") ? "good" : "warn";
      pills.appendChild(el("span", "status-pill " + statusClass, data.task.status || "UNKNOWN"));
      pills.appendChild(el("span", "status-pill info", "horizon: " + (data.task.horizon_decision || "unknown")));
      pills.appendChild(el("span", "status-pill", "last: " + (data.task.last_updated || "unknown")));
      mission.appendChild(pills);

      const review = data.review || {};
      const selfReview = document.getElementById("selfReview");
      clear(selfReview);
      (review.items || []).forEach(item => {
        const row = el("div", "item");
        row.appendChild(el("div", "item-title", item.label || "Review item"));
        row.appendChild(el("div", "muted", item.body || "No detail recorded."));
        selfReview.appendChild(row);
      });
      (review.known_issues || []).slice(0, 3).forEach(issue => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Known issue"));
        title.appendChild(el("span", "chip deferred", "watch"));
        row.appendChild(title);
        row.appendChild(el("div", "muted", issue));
        selfReview.appendChild(row);
      });
      if (!selfReview.children.length) selfReview.appendChild(el("div", "item muted", "No self-review state recorded yet."));

      const checkList = document.getElementById("checkList");
      clear(checkList);
      (review.checks || []).forEach(check => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Validation"));
        title.appendChild(el("span", "chip " + checkChipClass(check.status), check.status || "info"));
        row.appendChild(title);
        row.appendChild(el("div", "muted", check.text || "No check detail."));
        checkList.appendChild(row);
      });
      if (!checkList.children.length) checkList.appendChild(el("div", "item muted", "No validation checks recorded yet."));

      const metrics = document.getElementById("metrics");
      clear(metrics);
      const signalState = data.signals || {};
      const activeSignalCount = Number(signalState.active_count || ((signalState.active || []).length) || 0);
      metrics.appendChild(renderMetric("Active Signals", activeSignalCount));
      metrics.appendChild(renderMetric("Queued patches", data.queue.totals.queued || 0));
      metrics.appendChild(renderMetric("Deferred patches", data.queue.totals.deferred || 0));
      metrics.appendChild(renderMetric("Unhandled inbox", data.human.unhandled_inbox || 0));

      const signalsList = document.getElementById("signalsList");
      clear(signalsList);
      (signalState.active || []).forEach(item => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", item.id || "signal"));
        const priorityClass = item.priority === "high" ? "deferred" : (item.priority === "critical" ? "failed" : "queued");
        title.appendChild(el("span", "chip " + priorityClass, item.priority || "medium"));
        row.appendChild(title);
        row.appendChild(el("div", "", item.instructions || "No instructions recorded."));
        row.appendChild(el("div", "signal-meta", "owner: " + (item.owner_role || "unknown") + " | cadence: " + (item.cadence || "unknown") + " | due: " + (item.next_due_at || "unknown")));
        signalsList.appendChild(row);
      });
      if (!signalsList.children.length) signalsList.appendChild(el("div", "item muted", "No active automation signals."));

      const active = data.conveyor.active_role_run || {};
      const visibleDecisionQueue = (data.conveyor.decision_queue || []).filter(item => !(active.status === "running" && item.role === active.role));
      const nextRoles = new Set(visibleDecisionQueue.map(item => item.role));
      const belt = document.getElementById("belt");
      clear(belt);
      ROLES.forEach(role => {
        const counts = (data.queue.counts_by_role || {})[role] || {};
        const card = el("div", "role" + (active.role === role && active.status === "running" ? " running" : "") + (nextRoles.has(role) ? " next" : ""));
        card.appendChild(el("h3", "", role));
        const state = active.role === role && active.status === "running" ? "running" : (nextRoles.has(role) ? "next" : "standby");
        card.appendChild(el("div", "state", state));
        const countGrid = el("div", "counts");
        ["queued", "deferred", "applied", "failed", "skipped"].forEach(status => {
          countGrid.appendChild(el("div", "", status + ": " + (counts[status] || 0)));
        });
        card.appendChild(countGrid);
        belt.appendChild(card);
      });

      const activeRun = document.getElementById("activeRun");
      clear(activeRun);
      if (active.role) {
        const node = el("div", "active-run");
        node.appendChild(el("strong", "", active.status === "running" ? "Running now: " + active.role : "Last active run looks stale: " + active.role));
        node.appendChild(el("div", "muted", (active.run_id || "unknown") + " | " + (active.reason || "no reason recorded")));
          activeRun.appendChild(node);
      }

      const health = document.getElementById("health");
      clear(health);
      const healthData = (data.conveyor || {}).health || {};
      const healthNode = el("div", "health " + (healthData.status || "ok"));
      healthNode.appendChild(el("strong", "", (healthData.status || "ok").toUpperCase()));
      healthNode.appendChild(el("div", "", healthData.summary || "builder-first conveyor policy active."));
      if ((healthData.recent_roles || []).length) healthNode.appendChild(el("div", "muted", "recent roles: " + healthData.recent_roles.join(" -> ")));
      health.appendChild(healthNode);

      const nextUp = document.getElementById("nextUp");
      clear(nextUp);
      visibleDecisionQueue.forEach(item => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", item.role || "idle"));
        title.appendChild(el("span", "chip " + (item.state || ""), item.state || "planned"));
        row.appendChild(title);
        row.appendChild(el("div", "muted", item.reason || "No reason recorded."));
        nextUp.appendChild(row);
      });
      if (!nextUp.children.length) nextUp.appendChild(el("div", "item muted", active.status === "running" ? "Current role is running; next decision refreshes after it exits." : "No conveyor decision recorded yet."));

      const patches = document.getElementById("patches");
      clear(patches);
      (data.queue.manifests || []).forEach(item => {
        patches.appendChild(renderManifest(item));
      });
      if (!patches.children.length) patches.appendChild(el("div", "item muted", "No queued or deferred patches yet."));

      const outcomes = document.getElementById("outcomes");
      clear(outcomes);
      (data.queue.recent_outcomes || []).forEach(item => {
        outcomes.appendChild(renderManifest(item));
      });
      if (!outcomes.children.length) outcomes.appendChild(el("div", "item muted", "No recent applied, failed, or skipped role outputs yet."));

      const timeline = document.getElementById("timeline");
      clear(timeline);
      (data.conveyor.history || []).slice().reverse().forEach(item => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", item.role || "role"));
        title.appendChild(el("span", "chip " + (item.progress_success ? "applied" : "deferred"), historyLabel(item)));
        row.appendChild(title);
        row.appendChild(el("div", "muted", (item.finished_at || "") + " | exit " + item.exit_code));
        row.appendChild(el("div", "", item.reason || "No reason recorded."));
        const acceptedText = acceptedRoleText(item);
        if (acceptedText) row.appendChild(el("div", "muted", acceptedText));
        timeline.appendChild(row);
      });
      if (!timeline.children.length) timeline.appendChild(el("div", "item muted", "No conveyor history yet."));

      const progress = document.getElementById("progress");
      progress.textContent = data.progress_recent || "No progress pulse yet.";

      const logs = document.getElementById("logs");
      clear(logs);
      (data.logs || []).forEach(item => {
        const row = el("div", "item");
        row.appendChild(el("div", "item-title", item.name || "log"));
        row.appendChild(el("div", "muted", item.tail || "No log lines."));
        logs.appendChild(row);
      });
      if (!logs.children.length) logs.appendChild(el("div", "item muted", "No automation logs yet."));

      const repo = document.getElementById("repo");
      clear(repo);
      repo.appendChild(renderMetric("Dirty files", data.git.dirty_count || 0));
      const commits = el("div", "chips");
      (data.git.recent_commits || []).forEach(commit => commits.appendChild(el("span", "chip", commit)));
      repo.appendChild(commits);
    }

    async function refresh() {
      if (!STATE_URL) {
        render(INITIAL_STATE);
        return;
      }
      try {
        const response = await fetch(STATE_URL + "?t=" + Date.now(), {cache: "no-store"});
        render(await response.json());
      } catch (error) {
        const fallback = INITIAL_STATE || {target_name: "target", generated_at: new Date().toISOString(), task: {}, human: {}, git: {}, queue: {totals: {}, counts_by_role: {}, manifests: []}, signals: {active_count: 0, active: []}, conveyor: {decision_queue: [], history: []}, review: {items: [], checks: [], known_issues: []}, logs: []};
        fallback.progress_recent = "Observatory refresh failed: " + error;
        render(fallback);
      }
    }

    refresh();
    if (STATE_URL) setInterval(refresh, 2500);
  </script>
</body>
</html>
"""


def render_html(snapshot: dict[str, Any], *, live: bool) -> str:
    initial_json = json.dumps(snapshot, sort_keys=True).replace("</", "<\\/")
    state_url = '"/state.json"' if live else "null"
    return (
        HTML_TEMPLATE.replace("__INITIAL_STATE__", initial_json)
        .replace("__STATE_URL__", state_url)
    )


def append_markdown_bullets(lines: list[str], items: list[Any], *, empty: str) -> None:
    if not items:
        lines.append(f"- {empty}")
        return
    for item in items:
        lines.append(f"- {clean_text(item, limit=420)}")


def render_review_markdown(snapshot: dict[str, Any]) -> str:
    task = snapshot.get("task") if isinstance(snapshot.get("task"), dict) else {}
    review = snapshot.get("review") if isinstance(snapshot.get("review"), dict) else {}
    signals = snapshot.get("signals") if isinstance(snapshot.get("signals"), dict) else {}
    queue = snapshot.get("queue") if isinstance(snapshot.get("queue"), dict) else {}
    conveyor = snapshot.get("conveyor") if isinstance(snapshot.get("conveyor"), dict) else {}
    human = snapshot.get("human") if isinstance(snapshot.get("human"), dict) else {}
    progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}

    lines = [
        "# Diffmogger Self-Review Snapshot",
        "",
        f"- generated_at: {clean_text(snapshot.get('generated_at') or 'unknown', limit=120)}",
        f"- target: `{clean_text(snapshot.get('target_name') or 'target', limit=120)}`",
        f"- automation_status: `{clean_text(task.get('status') or 'UNKNOWN', limit=80)}`",
        f"- current_horizon: {clean_text(task.get('horizon') or 'unknown', limit=180)}",
        f"- horizon_decision: {clean_text(task.get('horizon_decision') or 'unknown', limit=120)}",
        "",
        "## Review Summary",
        "",
    ]

    review_item_count = 0
    for item in list(review.get("items") or [])[:MAX_REVIEW_ITEMS]:
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label") or "Review item", limit=80)
        body = clean_text(item.get("body") or "No detail recorded.", limit=420)
        lines.append(f"- **{label}:** {body}")
        review_item_count += 1
    if not review_item_count:
        lines.append("- No self-review state recorded yet.")

    lines.extend(["", "## Validation", ""])
    checks = [item for item in list(review.get("checks") or []) if isinstance(item, dict)]
    if checks:
        for check in checks[:MAX_CHECK_ITEMS]:
            status = clean_text(check.get("status") or "info", limit=40).upper()
            text = clean_text(check.get("text") or "No check detail.", limit=420)
            text = re.sub(
                r"^(PASS(?:\s+fallback)?|FAIL(?:\s+with\s+environment\s+note)?|WARN|PENDING|INFO):\s*",
                "",
                text,
                flags=re.IGNORECASE,
            )
            lines.append(f"- {status}: {text}")
    else:
        lines.append("- No validation checks recorded yet.")

    lines.extend(["", "## Active Signals", ""])
    active_signals = [item for item in list(signals.get("active") or []) if isinstance(item, dict)]
    if active_signals:
        for item in active_signals[:MAX_SIGNALS]:
            signal_id = clean_text(item.get("id") or "signal", limit=80)
            owner = clean_text(item.get("owner_role") or "unknown", limit=40)
            priority = clean_text(item.get("priority") or "medium", limit=40)
            due = clean_text(item.get("next_due_at") or "unknown", limit=80)
            lines.append(f"- `{signal_id}`: {priority}, owner `{owner}`, due {due}")
    else:
        lines.append("- No active signal nudges.")

    lines.extend(["", "## Queue And Conveyor", ""])
    lines.append(f"- queued_patches: {int(totals.get('queued', 0) or 0)}")
    lines.append(f"- deferred_patches: {int(totals.get('deferred', 0) or 0)}")
    lines.append(f"- applied_patches: {int(totals.get('applied', 0) or 0)}")
    lines.append(f"- failed_patches: {int(totals.get('failed', 0) or 0)}")
    health = conveyor.get("health") if isinstance(conveyor.get("health"), dict) else {}
    lines.append(f"- conveyor_health: {clean_text(health.get('summary') or 'No conveyor health recorded.', limit=420)}")
    decisions = [item for item in list(conveyor.get("decision_queue") or []) if isinstance(item, dict)]
    if decisions:
        first = decisions[0]
        role = clean_text(first.get("role") or "idle", limit=40)
        state = clean_text(first.get("state") or "planned", limit=40)
        reason = clean_text(first.get("reason") or "No reason recorded.", limit=300)
        lines.append(f"- next_lane: `{role}` ({state}) - {reason}")
    else:
        lines.append("- next_lane: No conveyor decision recorded yet.")
    append_markdown_bullets(
        lines,
        list(progress.get("deferred_backlog") or [])[:MAX_REVIEW_ITEMS],
        empty="No deferred backlog recorded in progress state.",
    )

    lines.extend(["", "## Human Bridge", ""])
    lines.append(f"- pending_requests: {int(human.get('pending_requests', 0) or 0)}")
    lines.append(f"- unhandled_inbox: {int(human.get('unhandled_inbox', 0) or 0)}")
    lines.append(f"- outbound_records: {int(human.get('outbound_records', 0) or 0)}")

    lines.extend(["", "## Known Issues", ""])
    append_markdown_bullets(
        lines,
        list(review.get("known_issues") or [])[:MAX_REVIEW_ITEMS],
        empty="No known issues recorded.",
    )

    lines.extend(
        [
            "",
            "## Next Sprint",
            "",
            f"- {clean_text(task.get('suggested_next_task') or 'No sprint task recorded yet.', limit=500)}",
            "",
        ]
    )
    return "\n".join(lines)


def write_output_file(path_value: str, body: str, *, label: str) -> None:
    if path_value == "-":
        sys.stdout.write(body)
        if not body.endswith("\n"):
            sys.stdout.write("\n")
        return
    output = Path(path_value).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body, encoding="utf-8")
    print(f"Wrote {label}: {output}")


class ObservatoryHandler(BaseHTTPRequestHandler):
    target: Path

    def _send(self, body: str | bytes, content_type: str, status: int = 200) -> None:
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._send(render_html(build_snapshot(self.target), live=True), "text/html; charset=utf-8")
            return
        if path == "/state.json":
            self._send(json.dumps(build_snapshot(self.target), indent=2, sort_keys=True) + "\n", "application/json; charset=utf-8")
            return
        self._send("Not found\n", "text/plain; charset=utf-8", status=404)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def run_server(target: Path, host: str, port: int, open_browser: bool) -> int:
    class Handler(ObservatoryHandler):
        pass

    Handler.target = target
    server = ThreadingHTTPServer((host, port), Handler)
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    print(f"Diffmogger observatory: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=".", help="Target project directory to observe")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for the local observatory server")
    parser.add_argument("--port", type=int, default=0, help="Bind port; 0 chooses a free local port")
    parser.add_argument("--open", action="store_true", help="Open the observatory URL in the default browser")
    parser.add_argument("--once", action="store_true", help="Render a standalone HTML snapshot and exit")
    parser.add_argument("--output", default="", help="Output path for --once; stdout is used when omitted")
    parser.add_argument(
        "--review-output",
        default="",
        help="Write a compact Markdown self-review report; use '-' for stdout",
    )
    args = parser.parse_args(argv)
    if args.once and not args.output and args.review_output == "-":
        parser.error("--review-output - cannot be combined with --once unless --output is also set")

    target = Path(args.target).expanduser().resolve()
    snapshot = build_snapshot(target)
    if args.once:
        body = render_html(snapshot, live=False)
        if args.output:
            write_output_file(args.output, body, label="observatory snapshot")
        else:
            sys.stdout.write(body)
    if args.review_output:
        write_output_file(args.review_output, render_review_markdown(snapshot), label="self-review report")
    if args.once or args.review_output:
        return 0

    return run_server(target, args.host, args.port, args.open)


if __name__ == "__main__":
    raise SystemExit(main())
