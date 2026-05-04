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
MAX_HISTORY = 80
MAX_LOG_FILES = 8
MAX_LOG_LINE_CHARS = 220
MAX_SIGNALS = 8
MAX_REVIEW_ITEMS = 6
MAX_CHECK_ITEMS = 8
MAX_SCORECARD_ITEMS = 8
MAX_RECOMMENDATION_HISTORY = 5
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
    "next_up": "No conveyor decision yet. After the first conveyor cycle, the next local role lane and reason will appear here.",
    "patch_queue": "No queued or deferred patches yet. First role patch manifests will appear here after builder, hardener, or planner lanes write local queue outputs.",
    "recent_outcomes": "No integration outcomes yet. Applied, failed, skipped, and deferred role outputs appear here after integrator review.",
    "timeline": "No conveyor timeline yet. Completed role runs will appear here with exit status, progress result, and integration notes.",
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


def integration_safety_record_snapshot(target: Path) -> dict[str, Any]:
    record = read_json(target / INTEGRATION_SAFETY_RECORD_RELATIVE)
    if not record:
        return {}

    raw_status = str(record.get("status") or "info").lower()
    status = raw_status if raw_status in {"pass", "fail", "warn", "pending", "info"} else "info"
    command = clean_text(record.get("command") or "python3 scripts/check_integration_safety.py", limit=180)
    checked_at = clean_text(record.get("checked_at") or "", limit=80)
    detail = clean_text(record.get("summary") or "", limit=360)
    if not detail:
        status_word = {
            "pass": "passed",
            "fail": "failed",
            "warn": "reported a warning",
            "pending": "is pending",
        }.get(status, "was recorded")
        detail = f"Dashboard Run Safety Check {status_word}: `{command}`."
    recorded_text = f"{checked_at}: {detail}" if checked_at else detail
    return {
        "status": status,
        "summary": detail,
        "command": command,
        "recorded_text": recorded_text,
        "source": clean_text(record.get("source") or "target/integration_safety_check.json", limit=80),
    }


def integration_safety_snapshot(validation: dict[str, Any], target: Path | None = None) -> dict[str, Any]:
    items = [item for item in list(validation.get("items") or []) if isinstance(item, dict)]
    for item in items:
        text = clean_text(item.get("text") or "", limit=420)
        lower = text.lower()
        if "scripts/check_integration_safety.py" not in lower and "integration safety" not in lower and "integration-safety" not in lower:
            continue
        status = clean_text(item.get("status") or "info", limit=40)
        command_match = re.search(r"`([^`]*(?:scripts/check_integration_safety\.py|integration[- ]safety)[^`]*)`", text, re.I)
        command = clean_text(command_match.group(1), limit=180) if command_match else "python3 scripts/check_integration_safety.py"
        if status == "pass":
            summary = f"Latest recorded integration-safety check passed: `{command}`."
        elif status == "fail":
            summary = f"Latest recorded integration-safety check failed: `{command}`."
        elif status == "warn":
            summary = f"Latest recorded integration-safety check has a warning: `{command}`."
        elif status == "pending":
            summary = f"Integration-safety check is recorded as pending: `{command}`."
        else:
            summary = f"Integration-safety check was recorded without pass/fail status: `{command}`."
        return {
            "status": status,
            "summary": summary,
            "command": command,
            "recorded_text": text,
        }

    if target is not None:
        record_snapshot = integration_safety_record_snapshot(target)
        if record_snapshot:
            return record_snapshot

    return {
        "status": "not_recorded",
        "summary": "No integration-safety check result is recorded in the latest task-state checks.",
        "command": "python3 scripts/check_integration_safety.py",
        "recorded_text": "",
    }


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
    validation = validation_snapshot(text)
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
        "validation": validation,
        "integration_safety": integration_safety_snapshot(validation, target),
    }


def first_review_doc_coverage(target: Path) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    marker_total = len(FIRST_REVIEW_MARKERS)
    for relative in FIRST_REVIEW_DOC_CANDIDATES:
        text = read_text(target / relative)
        if not text or "First Review Checklist" not in text:
            continue
        present = [label for label, marker in FIRST_REVIEW_MARKERS if marker in text]
        missing = [label for label, marker in FIRST_REVIEW_MARKERS if marker not in text]
        docs.append(
            {
                "path": relative,
                "present": present,
                "missing": missing,
                "present_count": len(present),
            }
        )

    complete = [item for item in docs if not item["missing"]]
    if complete:
        paths = ", ".join(item["path"] for item in complete[:3])
        if len(complete) > 3:
            paths += f", +{len(complete) - 3} more"
        return {
            "status": "pass",
            "detail": f"{len(complete)} first-review checklist doc(s) cover all {marker_total} markers: {paths}.",
            "docs": docs,
            "missing": [],
        }

    if docs:
        best = sorted(docs, key=lambda item: int(item["present_count"]), reverse=True)[0]
        missing = [clean_text(item, limit=80) for item in best["missing"]]
        return {
            "status": "warn",
            "detail": (
                f"{best['path']} covers {best['present_count']}/{marker_total} first-review markers; "
                f"missing {', '.join(missing)}."
            ),
            "docs": docs,
            "missing": missing,
        }

    return {
        "status": "fail",
        "detail": "No first-review checklist doc was found in the target-local docs.",
        "docs": [],
        "missing": [label for label, _marker in FIRST_REVIEW_MARKERS],
    }


def first_review_snapshot(target: Path, task: dict[str, Any]) -> dict[str, Any]:
    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    validation_counts = validation.get("counts") if isinstance(validation.get("counts"), dict) else {}
    pass_count = int(validation_counts.get("pass", 0) or 0)
    fail_count = int(validation_counts.get("fail", 0) or 0)
    integration_safety = task.get("integration_safety") if isinstance(task.get("integration_safety"), dict) else {}
    integration_status = clean_text(integration_safety.get("status") or "not_recorded", limit=40)
    docs = first_review_doc_coverage(target)

    if fail_count:
        validation_status = "fail"
        validation_detail = validation.get("summary") or f"{fail_count} validation issue(s) recorded."
    elif pass_count:
        validation_status = "pass"
        validation_detail = validation.get("summary") or f"{pass_count} passing check(s) recorded."
    else:
        validation_status = "warn"
        validation_detail = "No passing validation run is recorded in the task file yet."

    safety_status = "pass" if integration_status == "pass" else ("fail" if integration_status == "fail" else "warn")
    safety_detail = integration_safety.get("summary") or "No integration-safety check result is recorded yet."

    items = [
        {"label": "Checklist docs", "status": docs["status"], "detail": docs["detail"]},
        {"label": "Validation", "status": validation_status, "detail": validation_detail},
        {"label": "Run Safety Check", "status": safety_status, "detail": safety_detail},
    ]
    missing_actions: list[str] = []
    if docs["status"] != "pass":
        missing_actions.append("Update a first-review checklist doc with the validation, safety, observatory, and Markdown export steps.")
    if validation_status != "pass":
        missing_actions.append("Record a passing `bash scripts/validate_starter_kit.sh` run.")
    if safety_status != "pass":
        missing_actions.append("Run dashboard **Run Safety Check** or `python3 scripts/check_integration_safety.py` and record the result.")

    status = "ready" if not missing_actions else "attention"
    if status == "ready":
        summary = "First-review path is ready: checklist docs, validation, and integration safety are all recorded."
    else:
        summary = f"First-review path needs attention on {len(missing_actions)} item(s)."

    return {
        "status": status,
        "summary": summary,
        "items": items,
        "missing_actions": missing_actions,
        "docs": docs.get("docs", []),
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


def classify_path(path: str) -> str:
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("templates/"):
        return "templates"
    if path.startswith("services/"):
        return "services"
    if path.startswith("scripts/"):
        return "scripts"
    if path.startswith("docs/") or path.endswith(".md"):
        return "docs"
    return "other"


def describe_path(path: str) -> str:
    if path.endswith("run_observatory.py"):
        return "observatory/review logic"
    if path.endswith("run_conveyor_automation.py"):
        return "conveyor scheduler"
    if path.endswith("run_role_automation.sh"):
        return "role runner"
    if path.endswith("integrate_role_outputs.py"):
        return "integrator"
    if path.endswith("validate_starter_kit.sh"):
        return "starter-kit validation"
    if path.endswith("check_integration_safety.py"):
        return "integration safety checker"
    if path.endswith("check_required_files.py"):
        return "generated-target contract checker"
    if path.endswith("test_run_observatory.py"):
        return "observatory regression tests"
    if path.endswith("test_integrate_role_outputs.py"):
        return "integrator/runtime-state tests"
    if path.endswith("test_check_integration_safety.py"):
        return "safety checker tests"
    if path.endswith("test_check_required_files.py"):
        return "required-file contract tests"
    if "agentic_dashboard/app.py" in path:
        return "dashboard app surface"
    if "agentic-notifier" in path:
        return "notifier guardrails"
    if path.endswith("README.md"):
        return "public docs"
    if path.startswith("docs/"):
        return "operator docs"
    if path.startswith("templates/"):
        return "generated target mirror"
    return classify_path(path)


def run_git_output(target: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(target),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def commit_numstat(target: Path, commit_hash: str) -> list[dict[str, Any]]:
    output = run_git_output(target, ["show", "--format=", "--numstat", "--no-renames", commit_hash])
    files: list[dict[str, Any]] = []
    for raw in output.splitlines():
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        add_s, del_s, path = parts[0], parts[1], parts[2]
        additions = 0 if add_s == "-" else int(add_s or 0)
        deletions = 0 if del_s == "-" else int(del_s or 0)
        files.append(
            {
                "path": clean_text(path, limit=140),
                "additions": additions,
                "deletions": deletions,
                "area": classify_path(path),
                "label": describe_path(path),
            }
        )
    return sorted(files, key=lambda item: item["additions"] + item["deletions"], reverse=True)


def commit_summary_from_files(subject: str, files: list[dict[str, Any]]) -> str:
    paths = [str(item.get("path") or "") for item in files]
    joined = "\n".join(paths)
    if "check_required_files.py" in joined and "test_check_required_files.py" in joined:
        return "Generated-target contract checks changed, with validation coverage."
    if "check_integration_safety.py" in joined:
        return "Integration safety guardrails changed, with local regression coverage."
    if "agentic_dashboard/app.py" in joined:
        return "Dashboard controls or status surfaces changed."
    if "run_role_automation.sh" in joined and "integrate_role_outputs.py" in joined:
        return "Runtime-state handoff changed so ignored automation state reaches main."
    if "run_observatory.py" in joined and "test_run_observatory.py" in joined:
        return "Observatory reporting changed, with matching regression tests."
    if "run_conveyor_automation.py" in joined and "test_run_conveyor_automation.py" in joined:
        return "Conveyor scheduling changed, with policy coverage."
    if paths and all(path.startswith("docs/") or path.endswith(".md") for path in paths):
        return "Operator documentation and durable planning state changed."
    return subject


def git_commits_snapshot(target: Path, *, max_count: int = 80) -> list[dict[str, Any]]:
    output = run_git_output(
        target,
        ["log", "--date=iso-strict", f"--max-count={max_count}", "--pretty=format:%h%x09%cI%x09%s"],
    )
    commits: list[dict[str, Any]] = []
    for raw in output.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        commit_hash, commit_time, subject = parts
        files = commit_numstat(target, commit_hash)
        additions = sum(int(item.get("additions") or 0) for item in files)
        deletions = sum(int(item.get("deletions") or 0) for item in files)
        role_match = re.search(r"\((planner|builder|hardener|integrator|observatory|conveyor|dashboard|scaffold|safety|docs)\)", subject)
        commits.append(
            {
                "hash": commit_hash,
                "time": commit_time,
                "subject": clean_text(subject, limit=220),
                "semantic": bool(CONVENTIONAL_SUBJECT_RE.match(subject)),
                "role": role_match.group(1) if role_match else "commit",
                "files": files[:8],
                "file_count": len(files),
                "additions": additions,
                "deletions": deletions,
                "summary": commit_summary_from_files(subject, files),
            }
        )
    return commits


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
        "commits": git_commits_snapshot(target),
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
    has_last_decision = bool(last.get("role") or last.get("reason"))
    reason = str(last.get("reason") or EMPTY_STATES["next_up"])
    entries = [
        {
            "role": role,
            "state": "next" if has_last_decision else "first-run",
            "reason": clean_text(reason, limit=180),
        }
    ]
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
        "summary": "planner deferral fast-follow and builder-first conveyor policy active; hardener runs once after integrated builder work.",
        "recent_roles": recent,
    }


def no_progress_summary(no_progress: dict[str, Any]) -> str:
    if not no_progress.get("active"):
        return ""
    streak = int(no_progress.get("streak", 0) or 0)
    threshold = int(no_progress.get("threshold", 0) or 0)
    reason = clean_text(no_progress.get("reason") or "integrator made no patch progress", limit=260)
    if threshold:
        summary = f"No-progress circuit breaker active after {streak}/{threshold} integrator no-progress cycle(s): {reason}"
    else:
        summary = f"No-progress circuit breaker active after {streak} integrator no-progress cycle(s): {reason}"
    planner_requested = clean_text(no_progress.get("planner_requested_at") or "", limit=80)
    if planner_requested:
        summary += f"; planner handoff requested at {planner_requested}"
    return summary


def normalized_deferral_reason(value: Any) -> str:
    reason = clean_text(value, limit=120).lower().replace("-", "_")
    if reason in {"stale", "staleness"}:
        return "staleness"
    if reason in DEFERRAL_REASON_ACTIONS:
        return reason
    if "environment" in reason and ("verification" in reason or "validation" in reason):
        return "verification_environment_failure"
    if "verification" in reason or "validation" in reason:
        return "verification_failure"
    if "conflict" in reason:
        return "conflict"
    if "stale" in reason:
        return "staleness"
    if "guardrail" in reason or "unsafe" in reason:
        return "guardrail_violation"
    return "other"


def deferred_backlog_items(progress_text: str) -> list[str]:
    items: list[str] = []
    for item in section_bullets(progress_text, "Deferred-Patch Backlog", limit=MAX_REVIEW_ITEMS):
        if clean_text(item, limit=120).lower() in EMPTY_DEFERRED_BACKLOG_MARKERS:
            continue
        items.append(item)
    return items


def parse_deferred_backlog_item(item: str) -> dict[str, str]:
    text = clean_text(item, limit=520)
    structured = re.match(
        r"^(?P<role>[A-Za-z0-9_-]+)\s+`(?P<run_id>[^`]+)`:\s*(?P<reason>[A-Za-z0-9_-]+)\s*;\s*(?P<detail>.+)$",
        text,
    )
    if structured:
        role = structured.group("role")
        run_id = structured.group("run_id")
        raw_reason = structured.group("reason")
        detail = structured.group("detail")
    else:
        role_match = re.match(r"^(?P<role>[A-Za-z0-9_-]+)\b", text)
        role = role_match.group("role") if role_match and role_match.group("role") in ROLES else "unknown"
        run_match = re.search(r"`([^`]+)`", text)
        run_id = run_match.group(1) if run_match else "unknown"
        raw_reason = text
        detail = text
    reason = normalized_deferral_reason(raw_reason)
    return {
        "role": clean_text(role, limit=40),
        "run_id": clean_text(run_id, limit=80),
        "reason": reason,
        "raw_reason": clean_text(raw_reason, limit=80),
        "detail": clean_text(detail, limit=320),
        "raw": text,
    }


def compact_counts(counts: dict[str, int], *, empty: str) -> str:
    parts = [f"{name} {count}" for name, count in sorted(counts.items()) if count]
    return ", ".join(parts) if parts else empty


def deferred_backlog_triage(backlog_items: list[str]) -> dict[str, Any]:
    entries = [parse_deferred_backlog_item(item) for item in backlog_items]
    if not entries:
        return {
            "summary": "No deferred patch backlog recorded.",
            "recommended_next_action": "No local deferred-patch triage action is needed.",
            "groups": [],
            "items": [],
        }

    buckets: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        buckets.setdefault(entry["reason"], []).append(entry)

    def reason_sort_key(reason: str) -> tuple[int, str]:
        try:
            return DEFERRAL_REASON_ORDER.index(reason), reason
        except ValueError:
            return len(DEFERRAL_REASON_ORDER), reason

    groups: list[dict[str, Any]] = []
    for reason in sorted(buckets, key=reason_sort_key):
        reason_entries = buckets[reason]
        role_counts: dict[str, int] = {}
        for entry in reason_entries:
            role_counts[entry["role"]] = role_counts.get(entry["role"], 0) + 1
        examples = [
            f"{entry['role']} `{entry['run_id']}`: {entry['detail']}"
            for entry in reason_entries[:2]
        ]
        groups.append(
            {
                "reason": reason,
                "count": len(reason_entries),
                "roles": compact_counts(role_counts, empty="unknown"),
                "action": DEFERRAL_REASON_ACTIONS.get(reason, DEFERRAL_REASON_ACTIONS["other"]),
                "examples": examples,
            }
        )

    summary = f"{len(entries)} deferred backlog item(s): " + ", ".join(
        f"{group['count']} {group['reason']}" for group in groups
    ) + "."
    top = groups[0]
    recommended = f"Start with `{top['reason']}` ({top['count']} item(s)): {top['action']}"
    return {
        "summary": summary,
        "recommended_next_action": recommended,
        "groups": groups,
        "items": entries,
    }


def progress_snapshot(progress_text: str) -> dict[str, Any]:
    accepted_by_role = cumulative_role_counts(progress_text, "Accepted patches by role")
    deferred_by_role = cumulative_role_counts(progress_text, "Deferred patches by role")
    deferred_depth = 0
    match = re.search(r"^-\s*Current deferred queue depth:\s*(\d+)", progress_text, re.MULTILINE)
    if match:
        deferred_depth = int(match.group(1))
    backlog = deferred_backlog_items(progress_text)
    return {
        "recent_activity": first_nonempty_section_line(progress_text, "Recent Activity Log") or "No multi-role activity recorded yet.",
        "integrator_runs": cumulative_metric_int(progress_text, "Total integrator runs"),
        "accepted_by_role": accepted_by_role,
        "accepted_total": sum(accepted_by_role.values()),
        "deferred_by_role": deferred_by_role,
        "deferred_total": sum(deferred_by_role.values()),
        "deferred_queue_depth": deferred_depth,
        "deferred_backlog": backlog,
        "deferred_triage": deferred_backlog_triage(backlog),
    }


def cumulative_metric_int(progress_text: str, key: str) -> int:
    section = markdown_section(progress_text, "Cumulative Metrics")
    match = re.search(rf"^-\s*{re.escape(key)}:\s*(\d+)", section, re.MULTILINE)
    return int(match.group(1)) if match else 0


def cumulative_role_counts(progress_text: str, key: str) -> dict[str, int]:
    section = markdown_section(progress_text, "Cumulative Metrics")
    counts = {role: 0 for role in ROLES if role != "integrator"}
    in_target_block = False
    for raw in section.splitlines():
        if re.match(rf"^-\s*{re.escape(key)}:\s*$", raw):
            in_target_block = True
            continue
        if not in_target_block:
            continue
        if raw.startswith("- "):
            break
        item = re.match(r"\s+-\s+([A-Za-z0-9_-]+):\s*(\d+)\s*$", raw)
        if not item:
            continue
        role = item.group(1)
        if role in counts:
            counts[role] = int(item.group(2))
    return counts


def role_count_summary(counts: dict[str, int], *, empty: str) -> str:
    parts = [f"{role} {int(counts.get(role, 0) or 0)}" for role in ROLES if role in counts and int(counts.get(role, 0) or 0)]
    return ", ".join(parts) if parts else empty


def infer_recommended_lane(text: Any, *, fallback: str = "") -> str:
    lower = clean_text(text, limit=700).lower()
    if not lower:
        return clean_text(fallback, limit=40)
    if any(marker in lower for marker in ("human input", "awaiting user", "blocked on user", "request human")):
        return "human"
    if any(marker in lower for marker in ("integrator", "integration", "deferred", "queued patch", "patch triage")):
        return "integrator"
    if any(marker in lower for marker in ("validation", "validate", "failing check", "pytest", "unittest", "py_compile", "hardener", "repair")):
        return "hardener"
    if any(marker in lower for marker in ("builder", "build", "implement", "add ", "dashboard", "observatory", "increment", "scaffold")):
        return "builder"
    if any(marker in lower for marker in ("planner", "planning", "plan ", "prompt", "roadmap", "backlog", "inbox")):
        return "planner"
    return clean_text(fallback, limit=40)


def latest_observed_lane_result(queue: dict[str, Any], conveyor: dict[str, Any]) -> dict[str, Any]:
    active = conveyor.get("active_role_run") if isinstance(conveyor.get("active_role_run"), dict) else {}
    if active.get("role") and active.get("status") == "running":
        role = clean_text(active.get("role") or "unknown", limit=40)
        return {
            "source": "active_role_run",
            "lane": role,
            "result": f"{role} running",
            "detail": clean_text(active.get("reason") or "Active role run is still in progress.", limit=360),
            "timestamp": clean_text(active.get("started_at") or "", limit=80),
            "completed": False,
        }

    history = [item for item in list(conveyor.get("history") or []) if isinstance(item, dict)]
    if history:
        entry = history[-1]
        role = clean_text(entry.get("role") or "unknown", limit=40)
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        progress_success = entry.get("progress_success")
        exit_code = entry.get("exit_code")
        if progress_success is True:
            result = f"{role} completed with progress"
        elif progress_success is False:
            result = f"{role} completed with no progress"
        elif exit_code not in (None, "", 0, "0"):
            result = f"{role} exited with code {clean_text(exit_code, limit=20)}"
        else:
            result = f"{role} completed"
        detail_parts = []
        if role == "integrator":
            accepted = role_count_summary(
                metadata.get("accepted_by_role") if isinstance(metadata.get("accepted_by_role"), dict) else {},
                empty="",
            )
            deferred_delta = role_count_summary(
                metadata.get("deferred_delta_by_role") if isinstance(metadata.get("deferred_delta_by_role"), dict) else {},
                empty="",
            )
            if accepted:
                detail_parts.append(f"accepted {accepted}")
            if deferred_delta:
                detail_parts.append(f"deferred delta {deferred_delta}")
        reason = clean_text(entry.get("reason") or "", limit=360)
        if reason:
            detail_parts.append(reason)
        return {
            "source": "conveyor_history",
            "lane": role,
            "result": result,
            "detail": "; ".join(detail_parts) if detail_parts else "No outcome detail recorded.",
            "timestamp": clean_text(entry.get("finished_at") or entry.get("started_at") or "", limit=80),
            "completed": True,
        }

    outcomes = [item for item in list(queue.get("recent_outcomes") or []) if isinstance(item, dict)]
    if outcomes:
        item = outcomes[0]
        role = clean_text(item.get("role") or "unknown", limit=40)
        status = clean_text(item.get("status") or "outcome", limit=40)
        run_id = clean_text(item.get("run_id") or "unknown", limit=80)
        return {
            "source": "queue_outcome",
            "lane": role,
            "result": f"{status} `{run_id}`",
            "detail": clean_text(item.get("summary") or "No queue outcome summary recorded.", limit=360),
            "timestamp": clean_text(item.get("timestamp") or item.get("created_at") or "", limit=80),
            "completed": True,
        }

    decisions = [item for item in list(conveyor.get("decision_queue") or []) if isinstance(item, dict)]
    if decisions:
        first = decisions[0]
        role = clean_text(first.get("role") or "idle", limit=40)
        state = clean_text(first.get("state") or "planned", limit=40)
        return {
            "source": "decision_queue",
            "lane": role,
            "result": f"{role} {state}",
            "detail": clean_text(first.get("reason") or "No conveyor reason recorded.", limit=360),
            "timestamp": "",
            "completed": False,
        }

    return {
        "source": "none",
        "lane": "none",
        "result": "No conveyor or queue outcome recorded yet.",
        "detail": "The previous recommendation is still waiting for a visible local outcome.",
        "timestamp": "",
        "completed": False,
    }


def action_plan_follow_through(
    task: dict[str, Any],
    queue: dict[str, Any],
    conveyor: dict[str, Any],
    progress: dict[str, Any],
    action_plan: dict[str, Any],
) -> dict[str, Any]:
    previous = clean_text(
        task.get("suggested_next_task")
        or task.get("best_next_milestone")
        or action_plan.get("recommendation")
        or "",
        limit=500,
    )
    current_lane = clean_text(action_plan.get("lane") or "local", limit=40)
    expected_lane = infer_recommended_lane(previous, fallback=current_lane) or "unknown"
    observed = latest_observed_lane_result(queue, conveyor)
    observed_lane = clean_text(observed.get("lane") or "none", limit=40)
    priority = clean_text(action_plan.get("priority") or "normal", limit=40).lower()
    completed = bool(observed.get("completed"))
    high_priority = priority in {"critical", "high", "blocked"}

    if completed and expected_lane != "unknown" and observed_lane == expected_lane:
        status = "followed"
        reason = "The latest completed local outcome matches the lane inferred from the previous recommendation."
    elif completed and expected_lane != "unknown" and observed_lane != expected_lane:
        status = "superseded"
        reason = "A different completed local lane ran after the previous recommendation."
    elif expected_lane != "unknown" and high_priority and current_lane != expected_lane:
        status = "superseded"
        reason = "The current action plan has a higher-priority lane than the previous recommendation."
    else:
        status = "still_pending"
        reason = "No completed local outcome for the inferred lane has been observed yet."

    return {
        "status": status,
        "previous_recommendation": previous or "No previous recommendation recorded.",
        "expected_lane": expected_lane,
        "observed_lane": observed_lane,
        "observed_result": clean_text(observed.get("result") or "No observed result recorded.", limit=220),
        "observed_detail": clean_text(observed.get("detail") or "", limit=420),
        "observed_source": clean_text(observed.get("source") or "none", limit=80),
        "observed_at": clean_text(observed.get("timestamp") or "", limit=80),
        "current_recommendation": clean_text(action_plan.get("recommendation") or "No current action plan recorded.", limit=500),
        "current_lane": current_lane,
        "status_reason": reason,
        "accepted_total": int(progress.get("accepted_total", 0) or 0),
        "deferred_queue_depth": int(progress.get("deferred_queue_depth", 0) or 0),
    }


def follow_through_summary(follow_through: dict[str, Any]) -> str:
    if not follow_through:
        return "No action-plan follow-through state recorded yet."
    status = clean_text(follow_through.get("status") or "still_pending", limit=40).replace("_", " ")
    previous = clean_text(follow_through.get("previous_recommendation") or "No previous recommendation recorded.", limit=260)
    expected = clean_text(follow_through.get("expected_lane") or "unknown", limit=40)
    observed_lane = clean_text(follow_through.get("observed_lane") or "none", limit=40)
    observed_result = clean_text(follow_through.get("observed_result") or "No observed result recorded.", limit=180)
    reason = clean_text(follow_through.get("status_reason") or "", limit=260)
    return (
        f"{status}: previous recommendation was `{previous}`. "
        f"Expected `{expected}`; observed `{observed_lane}` as {observed_result}. {reason}"
    )


def no_progress_history_value(no_progress: dict[str, Any]) -> str:
    if not no_progress.get("active"):
        return "inactive"
    streak = int(no_progress.get("streak", 0) or 0)
    threshold = int(no_progress.get("threshold", 0) or 0)
    if threshold:
        return f"active after {streak}/{threshold}"
    return f"active after {streak}"


def history_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_recommendation_history_record(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "recorded_at": clean_text(raw.get("recorded_at") or raw.get("generated_at") or "", limit=80),
        "status": clean_text(raw.get("status") or "still_pending", limit=40),
        "previous_recommendation": clean_text(
            raw.get("previous_recommendation") or "No previous recommendation recorded.",
            limit=500,
        ),
        "expected_lane": clean_text(raw.get("expected_lane") or "unknown", limit=80),
        "observed_lane": clean_text(raw.get("observed_lane") or "none", limit=80),
        "observed_result": clean_text(
            raw.get("observed_result") or "No observed result recorded.",
            limit=420,
        ),
        "current_recommendation": clean_text(
            raw.get("current_recommendation") or "No current action plan recorded.",
            limit=500,
        ),
        "current_lane": clean_text(raw.get("current_lane") or "local", limit=80),
        "no_progress": clean_text(raw.get("no_progress") or "inactive", limit=80),
        "accepted_total": history_int(raw.get("accepted_total", 0)),
        "deferred_queue_depth": history_int(raw.get("deferred_queue_depth", 0)),
    }


def recommendation_history_identity(record: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(record.get("status") or ""),
        str(record.get("previous_recommendation") or ""),
        str(record.get("expected_lane") or ""),
        str(record.get("observed_lane") or ""),
        str(record.get("observed_result") or ""),
        str(record.get("current_recommendation") or ""),
        str(record.get("current_lane") or ""),
        str(record.get("no_progress") or ""),
        str(record.get("accepted_total") or 0),
        str(record.get("deferred_queue_depth") or 0),
    )


def recommendation_history_record(
    generated_at: str,
    follow_through: dict[str, Any],
    conveyor: dict[str, Any],
) -> dict[str, Any]:
    no_progress = conveyor.get("no_progress") if isinstance(conveyor.get("no_progress"), dict) else {}
    return normalize_recommendation_history_record(
        {
            "recorded_at": generated_at,
            "status": follow_through.get("status") or "still_pending",
            "previous_recommendation": follow_through.get("previous_recommendation"),
            "expected_lane": follow_through.get("expected_lane"),
            "observed_lane": follow_through.get("observed_lane"),
            "observed_result": follow_through.get("observed_result"),
            "current_recommendation": follow_through.get("current_recommendation"),
            "current_lane": follow_through.get("current_lane"),
            "no_progress": no_progress_history_value(no_progress),
            "accepted_total": follow_through.get("accepted_total", 0),
            "deferred_queue_depth": follow_through.get("deferred_queue_depth", 0),
        }
    )


def merge_recommendation_history(current: dict[str, Any], stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for raw in [current, *stored]:
        record = normalize_recommendation_history_record(raw)
        if not record:
            continue
        key = recommendation_history_identity(record)
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
        if len(records) >= MAX_RECOMMENDATION_HISTORY:
            break
    return records


def load_recommendation_history(target: Path) -> list[dict[str, Any]]:
    data = read_json(target / ACTION_PLAN_HISTORY_RELATIVE)
    raw_records = data.get("records") if isinstance(data.get("records"), list) else []
    records = [normalize_recommendation_history_record(item) for item in raw_records]
    return [item for item in records if item][:MAX_RECOMMENDATION_HISTORY]


def recommendation_history_summary(records: list[dict[str, Any]]) -> str:
    if not records:
        return "No recommendation history recorded yet."
    status_counts: dict[str, int] = {}
    no_progress_count = 0
    for record in records:
        status = clean_text(record.get("status") or "still_pending", limit=40).replace("_", " ")
        status_counts[status] = status_counts.get(status, 0) + 1
        if str(record.get("no_progress") or "inactive") != "inactive":
            no_progress_count += 1
    latest = records[0]
    statuses = ", ".join(f"{count} {status}" for status, count in sorted(status_counts.items()))
    latest_status = clean_text(latest.get("status") or "still_pending", limit=40).replace("_", " ")
    expected = clean_text(latest.get("expected_lane") or "unknown", limit=40)
    observed = clean_text(latest.get("observed_lane") or "none", limit=40)
    return (
        f"{len(records)} recommendation follow-through record(s): {statuses}. "
        f"Latest {latest_status}; expected `{expected}`, observed `{observed}`. "
        f"{no_progress_count} no-progress warning record(s)."
    )


def recommendation_history_snapshot(
    target: Path,
    generated_at: str,
    follow_through: dict[str, Any],
    conveyor: dict[str, Any],
) -> dict[str, Any]:
    current = recommendation_history_record(generated_at, follow_through, conveyor)
    records = merge_recommendation_history(current, load_recommendation_history(target))
    return {
        "storage_path": ACTION_PLAN_HISTORY_RELATIVE.as_posix(),
        "summary": recommendation_history_summary(records),
        "records": records,
    }


def persist_recommendation_history(target: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    history = snapshot.get("recommendation_history") if isinstance(snapshot.get("recommendation_history"), dict) else {}
    records = [
        normalize_recommendation_history_record(item)
        for item in list(history.get("records") or [])
    ]
    records = [item for item in records if item][:MAX_RECOMMENDATION_HISTORY]
    path = target / ACTION_PLAN_HISTORY_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": clean_text(snapshot.get("generated_at") or utc_now(), limit=80),
        "records": records,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    snapshot["recommendation_history"] = {
        "storage_path": ACTION_PLAN_HISTORY_RELATIVE.as_posix(),
        "summary": recommendation_history_summary(records),
        "records": records,
    }
    return snapshot


def scorecard_action_plan(
    task: dict[str, Any],
    queue: dict[str, Any],
    signals: dict[str, Any],
    conveyor: dict[str, Any],
    human: dict[str, int],
    progress: dict[str, Any],
) -> dict[str, Any]:
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}
    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    validation_counts = validation.get("counts") if isinstance(validation.get("counts"), dict) else {}
    deferred_triage = progress.get("deferred_triage") if isinstance(progress.get("deferred_triage"), dict) else {}
    active_signals = [item for item in list(signals.get("active") or []) if isinstance(item, dict)]
    decisions = [item for item in list(conveyor.get("decision_queue") or []) if isinstance(item, dict)]
    queued = int(totals.get("queued", 0) or 0)
    deferred_manifest_count = int(totals.get("deferred", 0) or 0)
    deferred_backlog = int(progress.get("deferred_queue_depth", 0) or 0)
    deferred_pressure = max(deferred_manifest_count, deferred_backlog)
    fail_count = int(validation_counts.get("fail", 0) or 0)
    pending_requests = int(human.get("pending_requests", 0) or 0)
    unhandled_inbox = int(human.get("unhandled_inbox", 0) or 0)

    if unhandled_inbox:
        return {
            "label": "Process human inbox",
            "lane": "planner",
            "priority": "high",
            "recommendation": f"Process {unhandled_inbox} unhandled human inbox message(s) before role work.",
            "why": "Human-provided instructions can change scope or unblock existing requests.",
            "next_steps": [
                "Read `docs/HUMAN_INBOX.md` and classify each unhandled entry.",
                "Complete or intentionally defer the requested action locally.",
                "Archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md` before removing handled inbox entries.",
            ],
        }
    if pending_requests:
        return {
            "label": "Request human input",
            "lane": "human",
            "priority": "blocked",
            "recommendation": f"Wait for or request human input on {pending_requests} active request(s).",
            "why": "A pending human request remains the highest-order local bridge item.",
            "next_steps": [
                "Keep reversible local work moving if it does not depend on the reply.",
                "Do not use notifier, SMS, WhatsApp, or external channels in file-only mode.",
                "Resume the blocked path after the human response is archived.",
            ],
        }
    if queued or deferred_pressure:
        summary = clean_text(
            deferred_triage.get("summary") or f"{deferred_pressure} deferred backlog item(s).",
            limit=260,
        )
        triage_action = clean_text(
            deferred_triage.get("recommended_next_action") or "Review queued and deferred patches locally.",
            limit=300,
        )
        if queued and not deferred_pressure:
            recommendation = f"Run integrator on {queued} queued patch(es)."
        elif queued:
            recommendation = f"Run integrator triage for {queued} queued patch(es) and {deferred_pressure} deferred backlog item(s)."
        else:
            recommendation = f"Run integrator triage for {deferred_pressure} deferred backlog item(s)."
        return {
            "label": "Run integrator triage",
            "lane": "integrator",
            "priority": "high",
            "recommendation": recommendation,
            "why": summary,
            "next_steps": [
                triage_action,
                "Repair locally now: retry clean conflicts or verification failures only after local patch checks and validation.",
                "Archive or document stale work that no longer applies instead of keeping it in the active deferred backlog.",
            ],
        }
    if fail_count:
        return {
            "label": "Repair validation",
            "lane": "hardener",
            "priority": "high",
            "recommendation": f"Repair or document {fail_count} validation issue(s) before expanding scope.",
            "why": clean_text(validation.get("summary") or "The latest recorded checks include failures.", limit=260),
            "next_steps": [
                "Re-run the failing local check or the nearest focused test.",
                "Use project-local dependency repair only; do not install global packages.",
                "Record any environment-only blocker in the task file with the exact command.",
            ],
        }
    if active_signals:
        first = active_signals[0]
        signal_id = clean_text(first.get("id") or "signal", limit=80)
        owner = clean_text(first.get("owner_role") or "planner", limit=40)
        return {
            "label": "Handle active signal",
            "lane": owner,
            "priority": clean_text(first.get("priority") or "medium", limit=40),
            "recommendation": f"Run `{owner}` work for active signal `{signal_id}`.",
            "why": clean_text(first.get("instructions") or "A recurring local automation nudge is due.", limit=260),
            "next_steps": [
                "Confirm the signal still matches the current project state.",
                "Complete the smallest useful local increment for the signal owner role.",
                "Mark the signal complete only when that role actually handled it.",
            ],
        }
    if decisions:
        first = decisions[0]
        role = clean_text(first.get("role") or "builder", limit=40)
        state = clean_text(first.get("state") or "planned", limit=40)
        reason = clean_text(first.get("reason") or "No conveyor reason recorded.", limit=260)
        if role == "idle" or state == "first-run":
            role = "builder"
            recommendation = "Continue builder momentum with the next scoped local increment."
        else:
            recommendation = f"Continue with the `{role}` lane."
        return {
            "label": "Continue builder momentum" if role == "builder" else f"Continue {role}",
            "lane": role,
            "priority": "normal",
            "recommendation": recommendation,
            "why": reason,
            "next_steps": [
                "Keep ownership narrow enough for clean integration.",
                "Update tests, fixtures, or docs that belong with the implementation.",
                "Run the relevant local validation path and record the result.",
            ],
        }
    return {
        "label": "Continue builder momentum",
        "lane": "builder",
        "priority": "normal",
        "recommendation": "Continue builder momentum with the next scoped local increment.",
        "why": "No human bridge item, validation failure, queued patch, deferred backlog, active signal, or conveyor handoff currently outranks builder work.",
        "next_steps": [
            "Choose the highest-value task from the current horizon.",
            "Keep the patch generic, local-first, and reviewable.",
            "Run focused tests plus starter-kit validation when applicable.",
        ],
    }


def scorecard_snapshot(
    task: dict[str, Any],
    queue: dict[str, Any],
    signals: dict[str, Any],
    conveyor: dict[str, Any],
    human: dict[str, int],
    progress: dict[str, Any],
    first_review: dict[str, Any],
) -> dict[str, Any]:
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}
    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    validation_counts = validation.get("counts") if isinstance(validation.get("counts"), dict) else {}
    accepted_by_role = progress.get("accepted_by_role") if isinstance(progress.get("accepted_by_role"), dict) else {}
    deferred_by_role = progress.get("deferred_by_role") if isinstance(progress.get("deferred_by_role"), dict) else {}
    deferred_triage = progress.get("deferred_triage") if isinstance(progress.get("deferred_triage"), dict) else {}
    integration_safety = task.get("integration_safety") if isinstance(task.get("integration_safety"), dict) else {}
    accepted_total = int(progress.get("accepted_total", 0) or 0)
    cumulative_deferred = int(progress.get("deferred_total", 0) or 0)
    queued = int(totals.get("queued", 0) or 0)
    deferred_manifest_count = int(totals.get("deferred", 0) or 0)
    deferred_backlog = int(progress.get("deferred_queue_depth", 0) or 0)
    deferred_pressure = max(deferred_manifest_count, deferred_backlog)
    active_signals = int(signals.get("active_count", 0) or 0)
    pending_human = int(human.get("pending_requests", 0) or 0) + int(human.get("unhandled_inbox", 0) or 0)
    pass_count = int(validation_counts.get("pass", 0) or 0)
    fail_count = int(validation_counts.get("fail", 0) or 0)
    no_progress = conveyor.get("no_progress") if isinstance(conveyor.get("no_progress"), dict) else {}
    no_progress_active = bool(no_progress.get("active"))
    first_review_status = clean_text(first_review.get("status") or "unknown", limit=40)

    attention_count = sum(
        1
        for flag in [
            bool(fail_count),
            bool(active_signals),
            bool(queued or deferred_pressure),
            bool(pending_human),
            no_progress_active,
            first_review_status != "ready",
        ]
        if flag
    )
    status = "attention" if attention_count else "clear"
    queue_detail = (
        f"{queued} queued, {deferred_pressure} deferred backlog item(s), {cumulative_deferred} cumulative deferral(s)."
        if queued or deferred_pressure or cumulative_deferred
        else "No queued or deferred patch pressure recorded."
    )
    if deferred_pressure and deferred_triage.get("summary"):
        queue_detail = f"{queue_detail} {deferred_triage['summary']}"
    validation_detail = (
        f"{pass_count} pass, {fail_count} fail from the last recorded run."
        if pass_count or fail_count
        else validation.get("summary") or "No validation checks recorded yet."
    )
    integration_status = clean_text(integration_safety.get("status") or "not_recorded", limit=40)
    integration_kind = {
        "pass": "good",
        "fail": "bad",
        "warn": "warn",
        "pending": "warn",
    }.get(integration_status, "info")
    first_review_kind = "good" if first_review_status == "ready" else "warn"
    summary_parts = [
        f"{accepted_total} accepted patch(es)",
        f"{queued} queued / {deferred_pressure} deferred",
        f"{active_signals} active signal(s)",
        f"{fail_count} validation issue(s)",
        f"integration safety {integration_status.replace('_', ' ')}",
        f"first review {first_review_status.replace('_', ' ')}",
    ]
    if pending_human:
        summary_parts.append(f"{pending_human} human bridge item(s)")
    if no_progress_active:
        summary_parts.append("no-progress circuit active")

    return {
        "status": status,
        "summary": "; ".join(summary_parts) + ".",
        "action_plan": scorecard_action_plan(task, queue, signals, conveyor, human, progress),
        "items": [
            {
                "label": "Accepted patches",
                "value": accepted_total,
                "detail": role_count_summary(accepted_by_role, empty="No accepted role patches recorded."),
                "kind": "good" if accepted_total else "info",
            },
            {
                "label": "Deferred pressure",
                "value": f"{queued}/{deferred_pressure}",
                "detail": queue_detail,
                "kind": "warn" if queued or deferred_pressure else "good",
            },
            {
                "label": "Validation",
                "value": f"{pass_count}/{fail_count}",
                "detail": validation_detail,
                "kind": "bad" if fail_count else ("good" if pass_count else "info"),
            },
            {
                "label": "Integration safety",
                "value": integration_status.replace("_", " "),
                "detail": integration_safety.get("summary") or "No integration-safety check result recorded yet.",
                "kind": integration_kind,
            },
            {
                "label": "First review",
                "value": first_review_status.replace("_", " "),
                "detail": first_review.get("summary") or "No first-review readiness state recorded yet.",
                "kind": first_review_kind,
            },
            {
                "label": "Signals due",
                "value": active_signals,
                "detail": f"{active_signals} active recurring automation nudge(s).",
                "kind": "warn" if active_signals else "good",
            },
            {
                "label": "Human bridge",
                "value": pending_human,
                "detail": f"{int(human.get('pending_requests', 0) or 0)} pending request(s), {int(human.get('unhandled_inbox', 0) or 0)} unhandled inbox message(s).",
                "kind": "warn" if pending_human else "good",
            },
            {
                "label": "Conveyor cycles",
                "value": int(conveyor.get("cycles", 0) or 0),
                "detail": f"{int(progress.get('integrator_runs', 0) or 0)} integrator run(s); cumulative deferrals by role: {role_count_summary(deferred_by_role, empty='none')}.",
                "kind": "warn" if no_progress_active else "info",
            },
        ][:MAX_SCORECARD_ITEMS],
    }


def self_review_snapshot(
    task: dict[str, Any],
    queue: dict[str, Any],
    signals: dict[str, Any],
    conveyor: dict[str, Any],
    human: dict[str, int],
    progress: dict[str, Any],
    first_review: dict[str, Any],
    follow_through: dict[str, Any] | None = None,
    recommendation_history: dict[str, Any] | None = None,
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
        queue_summary = EMPTY_STATES["patch_queue"]

    no_progress = conveyor.get("no_progress") if isinstance(conveyor.get("no_progress"), dict) else {}
    no_progress_note = no_progress_summary(no_progress)
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
    if no_progress_note:
        conveyor_summary = f"{conveyor_summary} {no_progress_note}."

    pending_human = int(human.get("pending_requests", 0) or 0)
    inbox = int(human.get("unhandled_inbox", 0) or 0)
    human_summary = (
        f"{pending_human} pending request(s), {inbox} unhandled inbox message(s)."
        if pending_human or inbox
        else "No pending human requests or unhandled inbox messages."
    )

    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    integration_safety = task.get("integration_safety") if isinstance(task.get("integration_safety"), dict) else {}
    deferred_triage = progress.get("deferred_triage") if isinstance(progress.get("deferred_triage"), dict) else {}
    action_plan = scorecard_action_plan(task, queue, signals, conveyor, human, progress)
    deferred_summary = clean_text(
        deferred_triage.get("summary") or "No deferred patch backlog recorded.",
        limit=300,
    )
    deferred_action = clean_text(
        deferred_triage.get("recommended_next_action") or "No local deferred-patch triage action is needed.",
        limit=360,
    )
    history_records = (
        list(recommendation_history.get("records") or [])
        if isinstance(recommendation_history, dict)
        else []
    )
    history_summary = recommendation_history_summary(
        [item for item in history_records if isinstance(item, dict)]
    )
    return {
        "items": [
            {"label": "Current assessment", "body": task.get("current_assessment") or "No current assessment recorded yet."},
            {"label": "First review", "body": first_review.get("summary") or "No first-review readiness state recorded yet."},
            {"label": "Validation", "body": validation.get("summary") or "No validation results recorded yet."},
            {"label": "Integration safety", "body": integration_safety.get("summary") or "No integration-safety check result recorded yet."},
            {"label": "Signals", "body": signal_summary},
            {"label": "Queue and conveyor", "body": f"{queue_summary} {conveyor_summary}"},
            {"label": "Human bridge", "body": human_summary},
            {"label": "Action plan", "body": f"{action_plan['recommendation']} {action_plan['why']}"},
            {"label": "Action follow-through", "body": follow_through_summary(follow_through or {})},
            {"label": "Recommendation history", "body": history_summary},
            {"label": "Deferred triage", "body": f"{deferred_summary} {deferred_action}"},
            {"label": "Next sprint", "body": task.get("suggested_next_task") or "No sprint task recorded yet."},
        ],
        "checks": list(validation.get("items") or [])[:MAX_CHECK_ITEMS],
        "known_issues": list(task.get("known_issues") or [])[:MAX_REVIEW_ITEMS],
    }


def build_snapshot(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    generated_at = utc_now()
    conveyor = read_json(target / "target" / "automation_conveyor_state.json")
    queue = queue_snapshot(target)
    task = parse_task_state(target)
    progress_text = read_text(target / "docs" / "MULTI_ROLE_PROGRESS.md", limit=40_000)
    progress = progress_snapshot(progress_text)
    human = {
        "pending_requests": count_concrete_records_with_status(
            target / "docs" / "HUMAN_REQUESTS.md",
            "HR",
            {"active", "awaiting_user"},
        ),
        "unhandled_inbox": count_concrete_records_with_status(
            target / "docs" / "HUMAN_INBOX.md",
            "INBOX",
            {"unhandled"},
        ),
        "outbound_records": count_concrete_records(target / "docs" / "HUMAN_OUTBOX.md", "OUTBOX"),
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
    first_review = first_review_snapshot(target, task)
    scorecard = scorecard_snapshot(task, queue, signals, conveyor_state, human, progress, first_review)
    follow_through = action_plan_follow_through(
        task,
        queue,
        conveyor_state,
        progress,
        scorecard.get("action_plan") if isinstance(scorecard.get("action_plan"), dict) else {},
    )
    recommendation_history = recommendation_history_snapshot(target, generated_at, follow_through, conveyor_state)
    review = self_review_snapshot(
        task,
        queue,
        signals,
        conveyor_state,
        human,
        progress,
        first_review,
        follow_through=follow_through,
        recommendation_history=recommendation_history,
    )
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "target_name": target.name or "target",
        "task": task,
        "human": human,
        "git": git_snapshot(target),
        "queue": queue,
        "signals": signals,
        "conveyor": conveyor_state,
        "progress": progress,
        "scorecard": scorecard,
        "first_review": first_review,
        "follow_through": follow_through,
        "recommendation_history": recommendation_history,
        "review": review,
        "empty_states": dict(EMPTY_STATES),
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
    .score-summary {
      margin-bottom: 10px;
      color: var(--muted);
    }
    .action-plan {
      margin-bottom: 10px;
    }
    .action-plan .item-title {
      align-items: center;
    }
    .action-plan ol {
      margin: 8px 0 0;
      padding-left: 20px;
      color: var(--muted);
    }
    .scorecard-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .scorecard-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #14181b;
      min-height: 112px;
    }
    .scorecard-item b {
      display: block;
      font-size: 24px;
      line-height: 1;
      font-variant-numeric: tabular-nums;
    }
    .scorecard-item strong {
      display: block;
      margin: 8px 0 4px;
    }
    .scorecard-item.good { border-color: rgba(87,199,133,.5); }
    .scorecard-item.warn { border-color: rgba(240,184,79,.6); }
    .scorecard-item.bad { border-color: rgba(255,107,107,.6); }
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
          <h2>Scorecard</h2>
          <div class="content">
            <div class="score-summary" id="scoreSummary"></div>
            <div class="action-plan" id="actionPlan"></div>
            <div class="scorecard-grid" id="scorecard"></div>
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

    function followStatusClass(status) {
      if (status === "followed") return "applied";
      if (status === "superseded") return "deferred";
      if (status === "still_pending") return "queued";
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

      const scorecardState = data.scorecard || {};
      const scoreSummary = document.getElementById("scoreSummary");
      scoreSummary.textContent = (scorecardState.summary || "No scorecard metrics recorded yet.") + " Status: " + (scorecardState.status || "unknown") + ".";
      const actionPlan = document.getElementById("actionPlan");
      clear(actionPlan);
      const plan = scorecardState.action_plan || {};
      if (plan.recommendation) {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", plan.label || "Action Plan"));
        title.appendChild(el("span", "chip " + (plan.priority === "high" || plan.priority === "blocked" ? "deferred" : "queued"), plan.lane || "local"));
        row.appendChild(title);
        row.appendChild(el("div", "", plan.recommendation));
        row.appendChild(el("div", "muted", plan.why || "No rationale recorded."));
        const steps = Array.isArray(plan.next_steps) ? plan.next_steps : [];
        if (steps.length) {
          const list = document.createElement("ol");
          steps.slice(0, 3).forEach(step => list.appendChild(el("li", "", step)));
          row.appendChild(list);
        }
        actionPlan.appendChild(row);
      } else {
        actionPlan.appendChild(el("div", "item muted", "No action plan recorded yet."));
      }
      const follow = data.follow_through || {};
      if (follow.status) {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Action Follow-Through"));
        title.appendChild(el("span", "chip " + followStatusClass(follow.status), String(follow.status || "still_pending").replace("_", " ")));
        row.appendChild(title);
        row.appendChild(el("div", "", follow.previous_recommendation || "No previous recommendation recorded."));
        row.appendChild(el("div", "muted", "expected " + (follow.expected_lane || "unknown") + "; observed " + (follow.observed_lane || "none") + " - " + (follow.observed_result || "No observed result recorded.")));
        if (follow.status_reason) row.appendChild(el("div", "muted", follow.status_reason));
        actionPlan.appendChild(row);
      }
      const historyState = data.recommendation_history || {};
      const historyRecords = Array.isArray(historyState.records) ? historyState.records : [];
      if (historyRecords.length) {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Recommendation History"));
        title.appendChild(el("span", "chip queued", String(historyRecords.length) + " recent"));
        row.appendChild(title);
        row.appendChild(el("div", "muted", historyState.summary || "No recommendation history summary recorded."));
        historyRecords.slice(0, 5).forEach(record => {
          const status = String(record.status || "still_pending").replace("_", " ");
          const line = (record.recorded_at || "unknown") + ": " + status + "; expected " + (record.expected_lane || "unknown") + ", observed " + (record.observed_lane || "none") + " - " + (record.observed_result || "No observed result recorded.");
          row.appendChild(el("div", "", line));
          row.appendChild(el("div", "muted", "no-progress " + (record.no_progress || "inactive") + "; accepted " + String(record.accepted_total || 0) + ", deferred depth " + String(record.deferred_queue_depth || 0)));
        });
        actionPlan.appendChild(row);
      }
      const scorecard = document.getElementById("scorecard");
      clear(scorecard);
      (scorecardState.items || []).forEach(item => {
        const row = el("div", "scorecard-item " + (item.kind || "info"));
        row.appendChild(el("b", "", String(item.value ?? "0")));
        row.appendChild(el("strong", "", item.label || "Metric"));
        row.appendChild(el("div", "muted", item.detail || "No detail recorded."));
        scorecard.appendChild(row);
      });
      if (!scorecard.children.length) scorecard.appendChild(el("div", "item muted", "No scorecard metrics recorded yet."));

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
      const noProgress = ((data.conveyor || {}).no_progress) || {};
      if (noProgress.active) {
        const noProgressNode = el("div", "health warning");
        noProgressNode.appendChild(el("strong", "", "NO-PROGRESS CIRCUIT"));
        const streak = Number(noProgress.streak || 0);
        const threshold = Number(noProgress.threshold || 0);
        const countText = threshold ? streak + "/" + threshold : String(streak);
        noProgressNode.appendChild(el("div", "", "No-progress circuit breaker active after " + countText + " integrator cycle(s)."));
        noProgressNode.appendChild(el("div", "muted", noProgress.reason || "Integrator made no patch progress."));
        if (noProgress.planner_requested_at) noProgressNode.appendChild(el("div", "muted", "planner handoff requested at " + noProgress.planner_requested_at));
        health.appendChild(noProgressNode);
      }

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
      const emptyStates = data.empty_states || {};
      if (!nextUp.children.length) nextUp.appendChild(el("div", "item muted", active.status === "running" ? "Current role is running; next decision refreshes after it exits." : (emptyStates.next_up || "No conveyor decision recorded yet.")));

      const patches = document.getElementById("patches");
      clear(patches);
      (data.queue.manifests || []).forEach(item => {
        patches.appendChild(renderManifest(item));
      });
      if (!patches.children.length) patches.appendChild(el("div", "item muted", emptyStates.patch_queue || "No queued or deferred patches yet."));

      const outcomes = document.getElementById("outcomes");
      clear(outcomes);
      (data.queue.recent_outcomes || []).forEach(item => {
        outcomes.appendChild(renderManifest(item));
      });
      if (!outcomes.children.length) outcomes.appendChild(el("div", "item muted", emptyStates.recent_outcomes || "No recent applied, failed, or skipped role outputs yet."));

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
      if (!timeline.children.length) timeline.appendChild(el("div", "item muted", emptyStates.timeline || "No conveyor history yet."));

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
        const fallback = INITIAL_STATE || {target_name: "target", generated_at: new Date().toISOString(), task: {}, human: {}, git: {}, queue: {totals: {}, counts_by_role: {}, manifests: []}, signals: {active_count: 0, active: []}, conveyor: {decision_queue: [], history: []}, scorecard: {items: []}, first_review: {}, follow_through: {}, recommendation_history: {records: []}, review: {items: [], checks: [], known_issues: []}, empty_states: {}, logs: []};
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


REPLAY_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Diffmogger Observatory</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f1316;
      --panel: #1b2227;
      --panel-dark: #13181c;
      --panel-head: #222a30;
      --line: #334048;
      --text: #f4f1ea;
      --muted: #aab2b4;
      --subtle: #77828a;
      --green: #5fd68b;
      --blue: #70a8ff;
      --amber: #eebe4e;
      --red: #f46b69;
      --cyan: #4fd3df;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 14px;
      padding: 28px 30px 18px;
    }
    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 20px;
      align-items: end;
    }
    h1 {
      margin: 0;
      font-size: clamp(34px, 5vw, 62px);
      line-height: .95;
      letter-spacing: 0;
    }
    .subtitle { margin-top: 10px; color: var(--muted); font-size: 17px; }
    .clock { color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
    .chips, .meta-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .chip {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: none;
    }
    .chip.good, .chip.applied, .chip.accepted { color: var(--green); border-color: rgba(95,214,139,.55); }
    .chip.info, .chip.queued, .chip.built { color: var(--blue); border-color: rgba(112,168,255,.55); }
    .chip.warn, .chip.deferred, .chip.planned, .chip.no-progress { color: var(--amber); border-color: rgba(238,190,78,.6); }
    .chip.bad, .chip.failed, .chip.retry { color: var(--red); border-color: rgba(244,107,105,.6); }
    .grid {
      display: grid;
      grid-template-columns: minmax(280px, .88fr) minmax(560px, 1.65fr) minmax(340px, 1fr);
      gap: 18px;
      min-height: 0;
    }
    .stack { display: grid; align-content: start; gap: 18px; min-height: 0; }
    section {
      min-width: 0;
      overflow: hidden;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    section > h2 {
      margin: 0;
      padding: 12px 16px;
      color: var(--muted);
      background: var(--panel-head);
      border-bottom: 1px solid var(--line);
      font-size: 13px;
      letter-spacing: 0;
      text-transform: uppercase;
    }
    .content { padding: 16px; }
    .mission { display: grid; gap: 18px; }
    .mission-block strong { display: block; margin-bottom: 5px; color: var(--text); }
    .mission-block div { color: var(--muted); overflow-wrap: anywhere; }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .metric {
      min-height: 92px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-dark);
    }
    .metric b { display: block; font-size: 42px; line-height: .95; font-variant-numeric: tabular-nums; }
    .metric span { display: block; margin-top: 8px; color: var(--muted); }
    .belt {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      padding: 16px;
    }
    .role {
      min-height: 178px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-dark);
    }
    .role.active { border-color: var(--green); box-shadow: 0 0 0 1px rgba(95,214,139,.35) inset; }
    .role.next { border-color: var(--blue); }
    .role h3 { margin: 0 0 12px; font-size: 24px; letter-spacing: 0; text-transform: capitalize; }
    .role-counts {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 9px 14px;
      margin-top: 15px;
      color: var(--muted);
      font-size: 13px;
      font-variant-numeric: tabular-nums;
    }
    .runner-strip {
      margin: 0 16px 16px;
      padding: 14px 16px;
      border: 1px solid rgba(95,214,139,.45);
      border-radius: 8px;
      background: rgba(95,214,139,.08);
    }
    .runner-strip strong { color: var(--green); }
    .runner-strip div { color: var(--muted); overflow-wrap: anywhere; }
    .story-panel {
      min-height: 330px;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .story-body {
      min-height: 0;
      overflow: auto;
      padding: 16px;
    }
    .story-title-row { display: flex; justify-content: space-between; gap: 14px; align-items: start; }
    .story-title {
      min-width: 0;
      margin: 0;
      font-size: clamp(28px, 3.2vw, 42px);
      line-height: 1.08;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }
    .story-detail {
      margin-top: 12px;
      color: var(--muted);
      font-size: 18px;
      overflow-wrap: anywhere;
    }
    .landed-now {
      margin-top: 24px;
      display: grid;
      gap: 10px;
    }
    .commit-title {
      color: var(--text);
      font-size: 20px;
      font-weight: 800;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }
    .commit-summary { color: var(--muted); overflow-wrap: anywhere; }
    .file-row {
      display: grid;
      grid-template-columns: 92px minmax(120px, .9fr) minmax(120px, 1fr);
      gap: 12px;
      align-items: baseline;
      color: var(--muted);
      font-size: 13px;
    }
    .file-row code { color: var(--subtle); overflow-wrap: anywhere; }
    .stat { color: var(--green); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .commit-list {
      max-height: calc(100vh - 250px);
      overflow: auto;
      display: grid;
      gap: 12px;
    }
    .commit-card, .support-card, .timeline-card {
      padding: 13px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-dark);
    }
    .commit-meta { margin-top: 8px; color: var(--subtle); font-variant-numeric: tabular-nums; }
    .support-grid { display: grid; gap: 12px; }
    .support-card strong { display: block; margin-bottom: 6px; }
    .support-card div { color: var(--muted); overflow-wrap: anywhere; }
    .timeline-shell {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }
    .timeline-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 14px;
      color: var(--muted);
      background: var(--panel-head);
      border-bottom: 1px solid var(--line);
      text-transform: uppercase;
      font-size: 13px;
      font-weight: 800;
    }
    .timeline-track {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      overscroll-behavior-x: contain;
      padding: 12px 14px 14px;
      scroll-snap-type: x proximity;
    }
    .timeline-card {
      flex: 0 0 260px;
      cursor: pointer;
      scroll-snap-align: start;
      text-align: left;
      color: inherit;
    }
    .timeline-card.selected { border-color: var(--green); box-shadow: 0 0 0 1px rgba(95,214,139,.35) inset; }
    .timeline-role { display: flex; justify-content: space-between; gap: 8px; font-weight: 800; text-transform: capitalize; }
    .timeline-time { margin-top: 6px; color: var(--subtle); font-size: 12px; font-variant-numeric: tabular-nums; }
    .timeline-reason { margin-top: 6px; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
    @media (max-width: 1260px) {
      .grid { grid-template-columns: 1fr; }
      .commit-list { max-height: none; }
    }
    @media (max-width: 760px) {
      .app { padding: 18px 12px 12px; }
      header { grid-template-columns: 1fr; }
      .clock { text-align: left; }
      .belt, .metric-grid { grid-template-columns: 1fr; }
      .file-row { grid-template-columns: 1fr; gap: 2px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div>
        <h1>Diffmogger Autonomous Build Log</h1>
        <div class="subtitle">Diffmogger Observatory view: replay-style automation progress reconstructed from conveyor events, commits, and diff stats.</div>
      </div>
      <div class="clock">
        <div id="generated">Waiting for state...</div>
        <div id="targetName"></div>
      </div>
    </header>
    <main class="grid">
      <div class="stack">
        <section>
          <h2>Mission State</h2>
          <div class="content mission" id="mission"></div>
        </section>
        <section>
          <h2>Scorecard</h2>
          <div class="content">
            <div class="metric-grid" id="metrics"></div>
          </div>
        </section>
        <section>
          <h2>Action Plan</h2>
          <div class="content support-grid" id="actionPlan"></div>
        </section>
      </div>
      <div class="stack">
        <section>
          <h2>Conveyor Belt</h2>
          <div class="belt" id="belt"></div>
          <div id="activeRun"></div>
        </section>
        <section class="story-panel">
          <h2>Progress Story</h2>
          <div class="story-body" id="progressStory"></div>
        </section>
        <section>
          <h2>Conveyor Health</h2>
          <div class="content support-grid" id="health"></div>
        </section>
      </div>
      <div class="stack">
        <section>
          <h2>Landed Work</h2>
          <div class="content commit-list" id="landedWork"></div>
        </section>
        <section>
          <h2>Recent Outcomes</h2>
          <div class="content support-grid" id="recentOutcomes"></div>
        </section>
        <section>
          <h2>First Review / Active Signals</h2>
          <div class="content support-grid" id="support"></div>
        </section>
      </div>
    </main>
    <section class="timeline-shell">
      <div class="timeline-header">
        <span>Event Timeline</span>
        <span id="timelineCount">0 events</span>
      </div>
      <div class="timeline-track" id="timeline"></div>
    </section>
  </div>
  <script>
    const INITIAL_STATE = __INITIAL_STATE__;
    const STATE_URL = __STATE_URL__;
    const ROLES = ["planner", "builder", "hardener", "integrator"];
    let selectedEventIndex = null;
    let currentData = null;

    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
    function text(value, fallback = "") { return value === undefined || value === null || value === "" ? fallback : String(value); }
    function timeLabel(value) {
      if (!value) return "unknown";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? value : date.toISOString().slice(11, 19) + " UTC";
    }
    function metric(label, value, colorClass = "") {
      const node = el("div", "metric");
      const number = el("b", colorClass, text(value, "0"));
      node.appendChild(number);
      node.appendChild(el("span", "", label));
      return node;
    }
    function chip(label, cls = "") { return el("span", "chip " + cls, label); }
    function eventStatus(event) {
      if (event.status === "running") return "running";
      if (event.role === "integrator") {
        const accepted = Number(((event.metadata || {}).accepted_delta) || 0);
        const deferred = Number(((event.metadata || {}).deferred_delta) || 0);
        if (accepted) return "accepted";
        if (deferred) return "deferred";
        return event.progress_success ? "accepted" : "no-progress";
      }
      if (event.exit_code !== 0 && event.exit_code !== undefined && event.exit_code !== null) return "retry";
      if (event.role === "planner") return "planned";
      if (event.role === "builder") return "built";
      if (event.role === "hardener") return "accepted";
      return event.progress_success ? "accepted" : "no-progress";
    }
    function eventTitle(event) {
      const role = text(event.role, "role");
      if (event.status === "running") return role + " is running now";
      if (role === "integrator") {
        const accepted = Number(((event.metadata || {}).accepted_delta) || 0);
        const deferred = Number(((event.metadata || {}).deferred_delta) || 0);
        if (accepted) return "Integrator accepted " + accepted + " patch" + (accepted === 1 ? "" : "es");
        if (deferred) return "Integrator deferred " + deferred + " patch" + (deferred === 1 ? "" : "es");
        return "Integrator checked the queue";
      }
      if (role === "planner") return "Planner refreshed the plan";
      if (role === "builder") return "Builder produced a patch";
      if (role === "hardener") return "Hardener verified the lane";
      return role + " completed";
    }
    function eventTime(event) { return event.finished_at || event.started_at || event.time || ""; }
    function eventsFor(data) {
      const history = Array.isArray(data.conveyor?.history) ? data.conveyor.history.slice() : [];
      const active = data.conveyor?.active_role_run || {};
      if (active.role) {
        history.push({
          role: active.role,
          reason: active.reason,
          started_at: active.started_at,
          finished_at: active.started_at,
          status: active.status,
          progress_success: active.status === "running",
          exit_code: null,
        });
      }
      return history;
    }
    function commitsFor(data) { return Array.isArray(data.git?.commits) ? data.git.commits.slice() : []; }
    function latestCommitFor(data, event) {
      const commits = commitsFor(data).sort((a, b) => new Date(a.time || 0) - new Date(b.time || 0));
      const eventDate = new Date(eventTime(event) || Date.now());
      let latest = commits[commits.length - 1] || null;
      for (const commit of commits) {
        const commitDate = new Date(commit.time || 0);
        if (!Number.isNaN(eventDate.getTime()) && commitDate <= eventDate) latest = commit;
      }
      return latest;
    }
    function renderCommit(commit, compact = false) {
      const card = el("div", compact ? "support-card" : "commit-card");
      card.appendChild(el("div", "commit-title", text(commit.subject, "Commit landed")));
      const meta = el("div", "meta-row commit-meta");
      meta.appendChild(chip(text(commit.hash, ""), "info"));
      meta.appendChild(el("span", "", timeLabel(commit.time)));
      meta.appendChild(el("span", "", text(commit.file_count, 0) + " files"));
      meta.appendChild(el("span", "stat", "+" + text(commit.additions, 0) + " / -" + text(commit.deletions, 0)));
      card.appendChild(meta);
      if (commit.summary) card.appendChild(el("div", "commit-summary", commit.summary));
      (commit.files || []).slice(0, compact ? 3 : 4).forEach(file => {
        const row = el("div", "file-row");
        row.appendChild(el("span", "stat", "+" + text(file.additions, 0) + " / -" + text(file.deletions, 0)));
        row.appendChild(el("strong", "", text(file.label, file.area || "change")));
        row.appendChild(el("code", "", text(file.path, "")));
        card.appendChild(row);
      });
      return card;
    }
    function renderMission(data) {
      const mission = document.getElementById("mission");
      clear(mission);
      [
        ["Automation status", data.task?.status],
        ["Current horizon", data.task?.horizon],
        ["Mission", data.task?.current_assessment],
        ["Best next milestone", data.task?.best_next_milestone],
        ["Known issue", data.task?.known_issue],
      ].forEach(([label, value]) => {
        const block = el("div", "mission-block");
        block.appendChild(el("strong", "", label));
        block.appendChild(el("div", "", text(value, "unknown")));
        mission.appendChild(block);
      });
      const chips = el("div", "chips");
      chips.appendChild(chip(text(data.task?.status, "UNKNOWN"), String(data.task?.status || "").startsWith("ACTIVE") ? "good" : "warn"));
      chips.appendChild(chip("horizon: " + text(data.task?.horizon_decision, "unknown"), "info"));
      chips.appendChild(chip("last: " + text(data.task?.last_updated, "unknown")));
      mission.appendChild(chips);
    }
    function renderMetrics(data) {
      const metrics = document.getElementById("metrics");
      clear(metrics);
      const totals = data.queue?.totals || {};
      const progress = data.progress || {};
      metrics.appendChild(metric("Conveyor cycles", data.conveyor?.cycles || 0, "info"));
      metrics.appendChild(metric("Accepted patches", progress.accepted_total || totals.applied || 0, "good"));
      metrics.appendChild(metric("Deferred patches", totals.deferred || progress.deferred_queue_depth || 0, "warn"));
      metrics.appendChild(metric("Unhandled inbox", data.human?.unhandled_inbox || 0));
    }
    function renderBelt(data) {
      const belt = document.getElementById("belt");
      clear(belt);
      const active = data.conveyor?.active_role_run || {};
      const decisions = Array.isArray(data.conveyor?.decision_queue) ? data.conveyor.decision_queue : [];
      const nextRoles = new Set(decisions.map(item => item.role));
      ROLES.forEach(role => {
        const counts = (data.queue?.counts_by_role || {})[role] || {};
        const state = active.role === role && active.status === "running" ? "active" : (nextRoles.has(role) ? "next" : "");
        const card = el("div", "role " + state);
        card.appendChild(el("h3", "", role));
        card.appendChild(chip(state === "active" ? "running" : (state === "next" ? "next" : "standby"), state === "active" ? "good" : (state === "next" ? "info" : "")));
        const grid = el("div", "role-counts");
        ["queued", "deferred", "applied", "failed", "skipped"].forEach(status => grid.appendChild(el("div", "", status + ": " + text(counts[status], 0))));
        card.appendChild(grid);
        belt.appendChild(card);
      });
      const activeRun = document.getElementById("activeRun");
      clear(activeRun);
      if (active.role) {
        const node = el("div", "runner-strip");
        node.appendChild(el("strong", "", active.status === "running" ? "Running now: " + active.role : "Last active role: " + active.role));
        node.appendChild(el("div", "", text(active.run_id, "unknown") + " | " + text(active.reason, "no reason recorded")));
        activeRun.appendChild(node);
      }
    }
    function renderStory(data) {
      const story = document.getElementById("progressStory");
      clear(story);
      const events = eventsFor(data);
      const index = events.length ? Math.min(selectedEventIndex ?? events.length - 1, events.length - 1) : -1;
      const event = index >= 0 ? events[index] : null;
      const titleRow = el("div", "story-title-row");
      const title = el("h3", "story-title", event ? eventTitle(event) : "No conveyor timeline yet");
      titleRow.appendChild(title);
      if (event) titleRow.appendChild(chip(eventStatus(event), eventStatus(event)));
      story.appendChild(titleRow);
      story.appendChild(el("div", "story-detail", event ? text(event.reason, "No reason recorded.") : text(data.empty_states?.timeline, "No conveyor timeline yet.")));
      const commit = event ? latestCommitFor(data, event) : commitsFor(data)[0];
      const latest = el("div", "landed-now");
      latest.appendChild(el("strong", "", "Latest landed work"));
      if (commit) latest.appendChild(renderCommit(commit, true));
      else latest.appendChild(el("div", "support-card", "No commits recorded yet."));
      story.appendChild(latest);
    }
    function renderLanded(data) {
      const node = document.getElementById("landedWork");
      clear(node);
      const commits = commitsFor(data);
      commits.slice(0, 10).forEach(commit => node.appendChild(renderCommit(commit)));
      if (!node.children.length) node.appendChild(el("div", "commit-card", "No landed work recorded yet."));
    }
    function renderSupport(data) {
      const action = document.getElementById("actionPlan");
      clear(action);
      const plan = data.scorecard?.action_plan || {};
      const planCard = el("div", "support-card");
      planCard.appendChild(el("strong", "", text(plan.label, "Action Plan")));
      planCard.appendChild(el("div", "", text(plan.recommendation, "No action plan recorded yet.")));
      if (plan.why) planCard.appendChild(el("div", "", plan.why));
      action.appendChild(planCard);
      const follow = data.follow_through || {};
      const followCard = el("div", "support-card");
      followCard.appendChild(el("strong", "", "Action Follow-Through"));
      followCard.appendChild(el("div", "", text(follow.status, "No follow-through record yet.")));
      followCard.appendChild(el("div", "", text(follow.observed_result, "")));
      action.appendChild(followCard);
      const historyCard = el("div", "support-card");
      historyCard.appendChild(el("strong", "", "Recommendation History"));
      historyCard.appendChild(el("div", "", text(data.recommendation_history?.summary, "No recommendation history recorded.")));
      action.appendChild(historyCard);

      const health = document.getElementById("health");
      clear(health);
      const healthData = data.conveyor?.health || {};
      const healthCard = el("div", "support-card");
      healthCard.appendChild(el("strong", "", "Conveyor Health"));
      healthCard.appendChild(el("div", "", text(healthData.summary, "No conveyor health recorded.")));
      if (Array.isArray(healthData.recent_roles)) healthCard.appendChild(el("div", "", "recent roles: " + healthData.recent_roles.join(" -> ")));
      health.appendChild(healthCard);
      const noProgress = data.conveyor?.no_progress || {};
      if (noProgress.active) {
        const card = el("div", "support-card");
        card.appendChild(el("strong", "", "NO-PROGRESS CIRCUIT"));
        card.appendChild(el("div", "", "no_progress_circuit: active after " + text(noProgress.streak, 0) + "/" + text(noProgress.threshold, "?")));
        card.appendChild(el("div", "", text(noProgress.reason, "")));
        health.appendChild(card);
      }

      const outcomes = document.getElementById("recentOutcomes");
      clear(outcomes);
      (data.queue?.recent_outcomes || []).slice(0, 5).forEach(item => {
        const card = el("div", "support-card");
        card.appendChild(el("strong", "", text(item.role, "role") + " / " + text(item.run_id, "run")));
        card.appendChild(el("div", "", text(item.status, "status") + ": " + text(item.summary, "No summary.")));
        outcomes.appendChild(card);
      });
      if (!outcomes.children.length) outcomes.appendChild(el("div", "support-card", text(data.empty_states?.recent_outcomes, "No recent outcomes.")));

      const support = document.getElementById("support");
      clear(support);
      const first = el("div", "support-card");
      first.appendChild(el("strong", "", "First review"));
      first.appendChild(el("div", "", text(data.first_review?.summary, "No first review state recorded.")));
      support.appendChild(first);
      const safety = el("div", "support-card");
      safety.appendChild(el("strong", "", "Integration safety"));
      safety.appendChild(el("div", "", text(data.task?.integration_safety?.summary, "No integration safety result recorded.")));
      support.appendChild(safety);
      const signals = el("div", "support-card");
      signals.appendChild(el("strong", "", "Active Signals"));
      const activeSignals = Array.isArray(data.signals?.active) ? data.signals.active : [];
      signals.appendChild(el("div", "", activeSignals.length ? activeSignals.map(item => item.id).join(", ") : "No active automation signals."));
      support.appendChild(signals);
      const triage = el("div", "support-card");
      triage.appendChild(el("strong", "", "Deferred triage"));
      triage.appendChild(el("div", "", text(data.progress?.deferred_triage?.summary, "No deferred patch backlog recorded.")));
      support.appendChild(triage);
    }
    function renderTimeline(data) {
      const events = eventsFor(data);
      const timeline = document.getElementById("timeline");
      clear(timeline);
      document.getElementById("timelineCount").textContent = events.length + " event" + (events.length === 1 ? "" : "s");
      if (!events.length) {
        timeline.appendChild(el("div", "timeline-card selected", text(data.empty_states?.timeline, "No conveyor timeline yet.")));
        return;
      }
      if (selectedEventIndex === null || selectedEventIndex >= events.length) selectedEventIndex = events.length - 1;
      events.forEach((event, index) => {
        const card = el("button", "timeline-card" + (index === selectedEventIndex ? " selected" : ""));
        card.type = "button";
        const row = el("div", "timeline-role");
        row.appendChild(el("span", "", text(event.role, "role")));
        row.appendChild(chip(eventStatus(event), eventStatus(event)));
        card.appendChild(row);
        card.appendChild(el("div", "timeline-time", timeLabel(eventTime(event)) + " | exit " + text(event.exit_code, "running")));
        card.appendChild(el("div", "timeline-reason", text(event.reason, "No reason recorded.")));
        card.addEventListener("click", () => {
          selectedEventIndex = index;
          renderStory(currentData);
          renderTimeline(currentData);
        });
        timeline.appendChild(card);
      });
    }
    function render(data) {
      currentData = data || {};
      document.getElementById("generated").textContent = "Updated " + text(currentData.generated_at, "now");
      document.getElementById("targetName").textContent = text(currentData.target_name, "target");
      renderMission(currentData);
      renderMetrics(currentData);
      renderBelt(currentData);
      renderStory(currentData);
      renderLanded(currentData);
      renderSupport(currentData);
      renderTimeline(currentData);
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
        const fallback = INITIAL_STATE || {target_name: "target", generated_at: new Date().toISOString(), task: {}, human: {}, git: {commits: []}, queue: {totals: {}, counts_by_role: {}, manifests: [], recent_outcomes: []}, conveyor: {decision_queue: [], history: []}, scorecard: {items: []}, review: {}, empty_states: {}};
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
        REPLAY_HTML_TEMPLATE.replace("__INITIAL_STATE__", initial_json)
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
    scorecard = snapshot.get("scorecard") if isinstance(snapshot.get("scorecard"), dict) else {}
    review = snapshot.get("review") if isinstance(snapshot.get("review"), dict) else {}
    signals = snapshot.get("signals") if isinstance(snapshot.get("signals"), dict) else {}
    queue = snapshot.get("queue") if isinstance(snapshot.get("queue"), dict) else {}
    conveyor = snapshot.get("conveyor") if isinstance(snapshot.get("conveyor"), dict) else {}
    human = snapshot.get("human") if isinstance(snapshot.get("human"), dict) else {}
    progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
    follow_through = snapshot.get("follow_through") if isinstance(snapshot.get("follow_through"), dict) else {}
    first_review = snapshot.get("first_review") if isinstance(snapshot.get("first_review"), dict) else {}
    integration_safety = task.get("integration_safety") if isinstance(task.get("integration_safety"), dict) else {}
    recommendation_history = (
        snapshot.get("recommendation_history")
        if isinstance(snapshot.get("recommendation_history"), dict)
        else {}
    )
    empty_states = snapshot.get("empty_states") if isinstance(snapshot.get("empty_states"), dict) else {}
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}
    no_progress = conveyor.get("no_progress") if isinstance(conveyor.get("no_progress"), dict) else {}
    deferred_triage = progress.get("deferred_triage") if isinstance(progress.get("deferred_triage"), dict) else {}
    action_plan = scorecard.get("action_plan") if isinstance(scorecard.get("action_plan"), dict) else {}

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

    lines.extend(["", "## Action Plan", ""])
    if action_plan:
        lines.append(
            f"- recommendation: {clean_text(action_plan.get('recommendation') or 'No local recommendation recorded.', limit=500)}"
        )
        lines.append(f"- lane: `{clean_text(action_plan.get('lane') or 'local', limit=80)}`")
        lines.append(f"- priority: {clean_text(action_plan.get('priority') or 'normal', limit=80)}")
        lines.append(f"- why: {clean_text(action_plan.get('why') or 'No rationale recorded.', limit=500)}")
        steps = [item for item in list(action_plan.get("next_steps") or []) if item]
        if steps:
            lines.append("- next_steps:")
            for step in steps[:MAX_REVIEW_ITEMS]:
                lines.append(f"  - {clean_text(step, limit=420)}")
    else:
        lines.append("- No action plan recorded yet.")

    lines.extend(["", "## Action Follow-Through", ""])
    if follow_through:
        status = clean_text(follow_through.get("status") or "still_pending", limit=40).replace("_", " ")
        lines.append(f"- status: {status}")
        lines.append(
            f"- previous_recommendation: {clean_text(follow_through.get('previous_recommendation') or 'No previous recommendation recorded.', limit=500)}"
        )
        lines.append(f"- expected_lane: `{clean_text(follow_through.get('expected_lane') or 'unknown', limit=80)}`")
        lines.append(f"- observed_lane: `{clean_text(follow_through.get('observed_lane') or 'none', limit=80)}`")
        lines.append(
            f"- observed_result: {clean_text(follow_through.get('observed_result') or 'No observed result recorded.', limit=420)}"
        )
        detail = clean_text(follow_through.get("observed_detail") or "", limit=420)
        if detail:
            lines.append(f"- observed_detail: {detail}")
        source = clean_text(follow_through.get("observed_source") or "none", limit=80)
        timestamp = clean_text(follow_through.get("observed_at") or "", limit=80)
        lines.append(f"- observed_source: `{source}`" + (f" at {timestamp}" if timestamp else ""))
        lines.append(
            f"- current_recommendation: {clean_text(follow_through.get('current_recommendation') or 'No current action plan recorded.', limit=500)}"
        )
        lines.append(
            f"- status_reason: {clean_text(follow_through.get('status_reason') or 'No follow-through reason recorded.', limit=500)}"
        )
    else:
        lines.append("- No action-plan follow-through state recorded yet.")

    lines.extend(["", "## Recommendation History", ""])
    history_records = [
        item
        for item in list(recommendation_history.get("records") or [])
        if isinstance(item, dict)
    ]
    if history_records:
        lines.append(
            f"- summary: {clean_text(recommendation_history.get('summary') or recommendation_history_summary(history_records), limit=500)}"
        )
        storage_path = clean_text(recommendation_history.get("storage_path") or ACTION_PLAN_HISTORY_RELATIVE.as_posix(), limit=160)
        lines.append(f"- history_file: `{storage_path}`")
        for record in history_records[:MAX_RECOMMENDATION_HISTORY]:
            recorded_at = clean_text(record.get("recorded_at") or "unknown", limit=80)
            status = clean_text(record.get("status") or "still_pending", limit=40).replace("_", " ")
            expected = clean_text(record.get("expected_lane") or "unknown", limit=80)
            observed = clean_text(record.get("observed_lane") or "none", limit=80)
            observed_result = clean_text(record.get("observed_result") or "No observed result recorded.", limit=360)
            lines.append(f"- {recorded_at}: {status}; expected `{expected}`, observed `{observed}` - {observed_result}")
            lines.append(
                f"  - previous_recommendation: {clean_text(record.get('previous_recommendation') or 'No previous recommendation recorded.', limit=420)}"
            )
            lines.append(
                f"  - current_recommendation: {clean_text(record.get('current_recommendation') or 'No current action plan recorded.', limit=420)}"
            )
            lines.append(f"  - no_progress: {clean_text(record.get('no_progress') or 'inactive', limit=80)}")
            lines.append(f"  - accepted_total: {history_int(record.get('accepted_total', 0))}")
            lines.append(f"  - deferred_queue_depth: {history_int(record.get('deferred_queue_depth', 0))}")
    else:
        lines.append("- No recommendation history recorded yet.")

    lines.extend(["", "## Scorecard", ""])
    lines.append(f"- status: {clean_text(scorecard.get('status') or 'unknown', limit=80)}")
    lines.append(f"- summary: {clean_text(scorecard.get('summary') or 'No scorecard metrics recorded yet.', limit=500)}")
    scorecard_items = [item for item in list(scorecard.get("items") or []) if isinstance(item, dict)]
    if scorecard_items:
        for item in scorecard_items[:MAX_SCORECARD_ITEMS]:
            label = clean_text(item.get("label") or "Metric", limit=80)
            value = clean_text(item.get("value") if item.get("value") is not None else "0", limit=80)
            detail = clean_text(item.get("detail") or "No detail recorded.", limit=420)
            lines.append(f"- {label}: {value} - {detail}")
    else:
        lines.append("- No scorecard metrics recorded yet.")

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

    lines.extend(["", "## Integration Safety", ""])
    lines.append(f"- status: {clean_text(integration_safety.get('status') or 'not_recorded', limit=80)}")
    lines.append(
        f"- summary: {clean_text(integration_safety.get('summary') or 'No integration-safety check result recorded yet.', limit=500)}"
    )
    lines.append(f"- command: `{clean_text(integration_safety.get('command') or 'python3 scripts/check_integration_safety.py', limit=180)}`")
    recorded_text = clean_text(integration_safety.get("recorded_text") or "", limit=420)
    if recorded_text:
        lines.append(f"- recorded_check: {recorded_text}")

    lines.extend(["", "## First Review Readiness", ""])
    lines.append(f"- status: {clean_text(first_review.get('status') or 'unknown', limit=80)}")
    lines.append(f"- summary: {clean_text(first_review.get('summary') or 'No first-review readiness state recorded yet.', limit=500)}")
    first_review_items = [item for item in list(first_review.get("items") or []) if isinstance(item, dict)]
    if first_review_items:
        for item in first_review_items[:MAX_REVIEW_ITEMS]:
            label = clean_text(item.get("label") or "Checklist item", limit=80)
            status = clean_text(item.get("status") or "info", limit=40)
            detail = clean_text(item.get("detail") or "No detail recorded.", limit=420)
            lines.append(f"- {label}: {status} - {detail}")
    else:
        lines.append("- No first-review checklist items recorded.")
    missing_actions = [item for item in list(first_review.get("missing_actions") or []) if item]
    if missing_actions:
        lines.append("- missing_actions:")
        for action in missing_actions[:MAX_REVIEW_ITEMS]:
            lines.append(f"  - {clean_text(action, limit=420)}")

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
    if not any(int(totals.get(status, 0) or 0) for status in QUEUE_STATUSES):
        lines.append(
            f"- first_run_queue_state: {clean_text(empty_states.get('patch_queue') or EMPTY_STATES['patch_queue'], limit=420)}"
        )
    health = conveyor.get("health") if isinstance(conveyor.get("health"), dict) else {}
    lines.append(f"- conveyor_health: {clean_text(health.get('summary') or 'No conveyor health recorded.', limit=420)}")
    if no_progress.get("active"):
        streak = int(no_progress.get("streak", 0) or 0)
        threshold = int(no_progress.get("threshold", 0) or 0)
        count_text = f"{streak}/{threshold}" if threshold else str(streak)
        lines.append(
            f"- no_progress_circuit: active after {count_text} integrator cycle(s) - "
            f"{clean_text(no_progress.get('reason') or 'integrator made no patch progress', limit=360)}"
        )
        planner_requested = clean_text(no_progress.get("planner_requested_at") or "", limit=80)
        if planner_requested:
            lines.append(f"- no_progress_planner_handoff: {planner_requested}")
    else:
        lines.append("- no_progress_circuit: inactive")
    decisions = [item for item in list(conveyor.get("decision_queue") or []) if isinstance(item, dict)]
    if decisions:
        first = decisions[0]
        role = clean_text(first.get("role") or "idle", limit=40)
        state = clean_text(first.get("state") or "planned", limit=40)
        reason = clean_text(first.get("reason") or "No reason recorded.", limit=300)
        lines.append(f"- next_lane: `{role}` ({state}) - {reason}")
    else:
        lines.append("- next_lane: No conveyor decision recorded yet.")

    lines.extend(["", "## Deferred Patch Triage", ""])
    lines.append(
        f"- summary: {clean_text(deferred_triage.get('summary') or 'No deferred patch backlog recorded.', limit=500)}"
    )
    lines.append(
        f"- recommended_next_action: {clean_text(deferred_triage.get('recommended_next_action') or 'No local deferred-patch triage action is needed.', limit=500)}"
    )
    triage_groups = [item for item in list(deferred_triage.get("groups") or []) if isinstance(item, dict)]
    if triage_groups:
        for group in triage_groups[:MAX_REVIEW_ITEMS]:
            reason = clean_text(group.get("reason") or "other", limit=80)
            count = int(group.get("count", 0) or 0)
            roles = clean_text(group.get("roles") or "unknown", limit=160)
            action = clean_text(group.get("action") or DEFERRAL_REASON_ACTIONS["other"], limit=420)
            lines.append(f"- {reason}: {count} item(s); roles: {roles}; action: {action}")
            examples = [item for item in list(group.get("examples") or []) if item]
            if examples:
                lines.append(f"- example: {clean_text(examples[0], limit=420)}")
    else:
        lines.append("- No deferred backlog groups.")
    lines.extend(["", "### Raw Deferred Backlog", ""])
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


def write_review_bundle(path_value: str, snapshot: dict[str, Any]) -> None:
    output_dir = Path(path_value).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_output_file(
        str(output_dir / FIRST_REVIEW_OBSERVATORY_FILENAME),
        render_html(snapshot, live=False),
        label="observatory snapshot",
    )
    write_output_file(
        str(output_dir / FIRST_REVIEW_SELF_REVIEW_FILENAME),
        render_review_markdown(snapshot),
        label="self-review report",
    )


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
    parser.add_argument(
        "--review-dir",
        default="",
        help=(
            "Write first-review HTML and Markdown artifacts to this directory "
            f"as {FIRST_REVIEW_OBSERVATORY_FILENAME} and {FIRST_REVIEW_SELF_REVIEW_FILENAME}"
        ),
    )
    args = parser.parse_args(argv)
    if args.review_dir:
        if args.review_dir.strip() == "-":
            parser.error("--review-dir requires a directory path")
        if args.once or args.output or args.review_output:
            parser.error("--review-dir cannot be combined with --once, --output, or --review-output")
    if args.once and not args.output and args.review_output == "-":
        parser.error("--review-output - cannot be combined with --once unless --output is also set")

    target = Path(args.target).expanduser().resolve()
    snapshot = build_snapshot(target)
    if args.review_dir or (args.review_output and args.review_output != "-"):
        snapshot = persist_recommendation_history(target, snapshot)
    if args.review_dir:
        write_review_bundle(args.review_dir, snapshot)
        return 0
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
