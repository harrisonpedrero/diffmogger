#!/usr/bin/env python3
"""Run a work-conserving Diffmogger automation conveyor.

The conveyor is a local scheduler for generated targets. It does not mutate the
checkout directly; it chooses the next runnable lane and invokes the existing
target-local wrappers. Multi-role role runners still own isolated worktrees, and
the integrator still owns the main mutation lock.
"""

from __future__ import annotations

import argparse
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


ROLES = ("planner", "builder", "hardener", "integrator")
ACTIVE_STATUSES = {"ACTIVE", "ACTIVE_WITH_PENDING_USER_INPUT"}
DEFAULT_AUTOMATION_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
DEFAULT_IDLE_SLEEP_SECONDS = 60
DEFAULT_ERROR_SLEEP_SECONDS = 300
DEFAULT_CYCLE_COOLDOWN_SECONDS = 5
DEFAULT_PLANNER_INTERVAL_SECONDS = 3600
DEFAULT_LOCK_STALE_SECONDS = 43200
DEFAULT_NO_PROGRESS_THRESHOLD = 2
STATE_HISTORY_LIMIT = 60
NO_PROGRESS_STATE_KEY = "integrator_no_progress"
DECISION_QUEUE_LIMIT = 8

CHILD: subprocess.Popen[str] | None = None
TERMINATE_REQUESTED = False


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


def read_lock_fields(path: Path) -> dict[str, str]:
    text = read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items()}
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def lock_is_active(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "no lock"
    fields = read_lock_fields(path)
    pid_text = fields.get("pid", "")
    pid = int(pid_text) if pid_text.isdigit() else None
    epoch_text = fields.get("created_at_epoch", "")
    stale_text = fields.get("stale_after_seconds", "")
    now_epoch = int(time.time())
    created_epoch = int(epoch_text) if epoch_text.isdigit() else int(path.stat().st_mtime)
    stale_after = int(stale_text) if stale_text.isdigit() else 14400
    age = max(0, now_epoch - created_epoch)
    if process_alive(pid):
        return True, f"pid {pid} is still running"
    if age < stale_after:
        run = fields.get("run_id", "unknown")
        return True, f"lock {run} is fresh but owner pid is not visible"
    return False, f"stale lock age_seconds={age}"


def acquire_scheduler_lock(path: Path, stale_seconds: int) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    now_epoch = int(time.time())
    if path.exists():
        fields = read_lock_fields(path)
        pid_text = fields.get("pid", "")
        pid = int(pid_text) if pid_text.isdigit() else None
        epoch_text = fields.get("created_at_epoch", "")
        created_epoch = int(epoch_text) if epoch_text.isdigit() else int(path.stat().st_mtime)
        age = max(0, now_epoch - created_epoch)
        if process_alive(pid):
            print(f"CONVEYOR_LOCK_ACTIVE path={path} pid={pid}", flush=True)
            return False
        if age < stale_seconds:
            print(f"CONVEYOR_LOCK_FRESH path={path} age_seconds={age}", flush=True)
            return False
        path.unlink()

    payload = {
        "pid": os.getpid(),
        "created_at": utc_now(),
        "created_at_epoch": now_epoch,
        "stale_after_seconds": stale_seconds,
        "command": "run_conveyor_automation.py",
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        print(f"CONVEYOR_LOCK_RACE path={path}", flush=True)
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"CONVEYOR_LOCK_ACQUIRED path={path} pid={os.getpid()}", flush=True)
    return True


def release_scheduler_lock(path: Path) -> None:
    if not path.exists():
        return
    fields = read_lock_fields(path)
    pid_text = fields.get("pid", "")
    if pid_text and pid_text != str(os.getpid()):
        print(f"CONVEYOR_LOCK_NOT_RELEASED path={path} owner_pid={pid_text}", flush=True)
        return
    try:
        path.unlink()
        print(f"CONVEYOR_LOCK_RELEASED path={path}", flush=True)
    except OSError as exc:
        print(f"CONVEYOR_LOCK_RELEASE_FAILED path={path} error={exc}", flush=True)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "cycles": 0, "role_counts": {}, "history": []}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "cycles": 0, "role_counts": {}, "history": []}
    if not isinstance(state, dict):
        return {"schema_version": 1, "cycles": 0, "role_counts": {}, "history": []}
    state.setdefault("schema_version", 1)
    state.setdefault("cycles", 0)
    state.setdefault("role_counts", {})
    state.setdefault("history", [])
    return state


def write_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def write_no_progress_progress_note(target: Path, info: dict[str, Any]) -> None:
    progress = target / "docs" / "MULTI_ROLE_PROGRESS.md"
    if not progress.exists():
        return
    text = read_text(progress)
    header, sections, order = split_h2_sections(text)
    if not header:
        header = "# Multi-Role Progress"
    reason = re.sub(r"\s+", " ", str(info.get("reason") or "integrator made no patch progress")).strip()
    reason = reason[:240] if len(reason) > 240 else reason
    stamp = utc_now()
    entry = "\n".join(
        [
            f"### {stamp} conveyor-no-progress",
            "",
            f"- circuit_breaker: active after {info.get('streak', 0)} no-progress integrator cycle(s).",
            f"- reason: {reason}",
            "- next_lane: planner handoff or idle until the blocked condition changes.",
        ]
    )
    recent = sections.get("Recent Activity Log", "").strip()
    if recent == "- No multi-role integrator runs yet.":
        recent = ""
    sections["Recent Activity Log"] = (recent.rstrip() + "\n\n" + entry).strip()
    role_health = sections.get("Role Health", "").splitlines()
    role_health = [line for line in role_health if not line.startswith("- conveyor:")]
    role_health.append(f"- conveyor: no-progress circuit breaker active; {reason}")
    sections["Role Health"] = "\n".join(line for line in role_health if line.strip())
    if "Recent Activity Log" not in order:
        order.append("Recent Activity Log")
    if "Role Health" not in order:
        order.append("Role Health")
    body = header.rstrip() + "\n\n"
    for section in order:
        body += f"## {section}\n\n{sections.get(section, '').strip()}\n\n"
    progress.write_text(body.rstrip() + "\n", encoding="utf-8")


def automation_status(target: Path) -> str:
    task_text = read_text(target / "docs" / "CODEX_AUTOMATION_TASKS.md")
    match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", task_text, re.MULTILINE)
    return match.group(1).strip().upper() if match else "UNKNOWN"


def unhandled_human_inbox_count(target: Path) -> int:
    text = read_text(target / "docs" / "HUMAN_INBOX.md")
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return len(re.findall(r"^\s*-\s*status:\s*unhandled\s*$", text, re.MULTILINE | re.IGNORECASE))


def target_has_multi_role(target: Path) -> bool:
    if not (target / "scripts" / "run_role_automation.sh").exists():
        return False
    return all((target / ".agentic" / "roles" / f"{role}.md").exists() for role in ROLES)


def queued_manifests(target: Path) -> list[Path]:
    queue_root = target / "target" / "automation_queue"
    manifests: list[Path] = []
    for path in sorted(queue_root.glob("*/*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "queued":
            manifests.append(path)
    return manifests


def normalized_deferral_signature(manifest: dict[str, Any]) -> str:
    reason = str(manifest.get("deferral_reason") or "other")
    detail = re.sub(r"\s+", " ", str(manifest.get("deferral_detail") or "")).strip()
    lowered = detail.lower()
    if "no module named pytest" in lowered or "pytest: command not found" in lowered:
        detail_class = "missing_pytest"
    elif re.search(r"/(?:user" + r"s|tmp|private/tmp|var/folders)/", lowered) or (
        "agentic-kit-" + "lab"
    ) in lowered:
        detail_class = "local_path_reference"
    else:
        detail_class = detail[:120] if detail else "no_detail"
    return f"{reason}:{detail_class}"


def queue_snapshot(target: Path) -> dict[str, Any]:
    queue_root = target / "target" / "automation_queue"
    counts = {"queued": 0, "deferred": 0, "applied": 0, "failed": 0, "skipped": 0}
    applied_by_role = {"planner": 0, "builder": 0, "hardener": 0}
    deferred_by_role = {"planner": 0, "builder": 0, "hardener": 0}
    queued_by_role = {"planner": 0, "builder": 0, "hardener": 0}
    deferred_signatures: dict[str, int] = {}
    for path in sorted(queue_root.glob("*/*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("role") or "") not in {"planner", "builder", "hardener"}:
            continue
        status = str(data.get("status") or "unknown")
        if status in counts:
            counts[status] += 1
        role = str(data.get("role") or "")
        if status == "queued" and role in queued_by_role:
            queued_by_role[role] += 1
        if status == "applied":
            if role in applied_by_role:
                applied_by_role[role] += 1
        if status == "deferred":
            if role in deferred_by_role:
                deferred_by_role[role] += 1
            signature = normalized_deferral_signature(data)
            deferred_signatures[signature] = deferred_signatures.get(signature, 0) + 1
    signature_parts = sorted(deferred_signatures)
    return {
        **counts,
        "applied_by_role": applied_by_role,
        "deferred_by_role": deferred_by_role,
        "queued_by_role": queued_by_role,
        "deferred_signature": "|".join(signature_parts) if signature_parts else "none",
        "deferred_signature_counts": deferred_signatures,
    }


def no_progress_info(state: dict[str, Any]) -> dict[str, Any]:
    info = state.get(NO_PROGRESS_STATE_KEY)
    return info if isinstance(info, dict) else {}


def no_progress_active(state: dict[str, Any], threshold: int) -> bool:
    info = no_progress_info(state)
    return bool(info.get("active")) and int(info.get("streak", 0)) >= threshold


def update_integrator_no_progress(
    state: dict[str, Any],
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    exit_code: int,
    threshold: int,
    finished_at: str,
) -> dict[str, Any]:
    accepted_delta = max(0, int(after.get("applied", 0)) - int(before.get("applied", 0)))
    deferred_delta = int(after.get("deferred", 0)) - int(before.get("deferred", 0))
    before_by_role = before.get("applied_by_role") if isinstance(before.get("applied_by_role"), dict) else {}
    after_by_role = after.get("applied_by_role") if isinstance(after.get("applied_by_role"), dict) else {}
    accepted_by_role = {
        role: max(0, int(after_by_role.get(role, 0)) - int(before_by_role.get(role, 0)))
        for role in ("planner", "builder", "hardener")
    }
    before_deferred_by_role = (
        before.get("deferred_by_role") if isinstance(before.get("deferred_by_role"), dict) else {}
    )
    after_deferred_by_role = (
        after.get("deferred_by_role") if isinstance(after.get("deferred_by_role"), dict) else {}
    )
    deferred_delta_by_role = {
        role: int(after_deferred_by_role.get(role, 0)) - int(before_deferred_by_role.get(role, 0))
        for role in ("planner", "builder", "hardener")
    }
    previous = no_progress_info(state)
    signature = str(after.get("deferred_signature") or "none")
    same_signature = bool(signature and signature != "none" and signature == previous.get("signature"))
    stuck_same_reason = same_signature and int(after.get("deferred", 0)) >= int(before.get("deferred", 0))
    no_progress = exit_code == 0 and accepted_delta == 0 and (deferred_delta > 0 or stuck_same_reason)

    metadata = {
        "accepted_delta": accepted_delta,
        "deferred_delta": deferred_delta,
        "queued_before": int(before.get("queued", 0)),
        "queued_after": int(after.get("queued", 0)),
        "deferred_after": int(after.get("deferred", 0)),
        "deferred_signature": signature,
        "accepted_by_role": accepted_by_role,
        "deferred_by_role": {
            role: int(after_deferred_by_role.get(role, 0)) for role in ("planner", "builder", "hardener")
        },
        "deferred_delta_by_role": deferred_delta_by_role,
        "no_progress": no_progress,
    }

    if exit_code == 0 and accepted_delta > 0:
        state[NO_PROGRESS_STATE_KEY] = {
            "active": False,
            "streak": 0,
            "reason": "integrator accepted patches",
            "cleared_at": finished_at,
        }
        metadata["progress_success"] = True
        metadata["just_tripped"] = False
        return metadata

    if no_progress:
        streak = int(previous.get("streak", 0)) + 1 if same_signature else 1
        active = streak >= threshold
        state[NO_PROGRESS_STATE_KEY] = {
            "active": active,
            "streak": streak,
            "threshold": threshold,
            "signature": signature,
            "reason": (
                f"integrator accepted 0 patches; deferred queue "
                f"{'grew' if deferred_delta > 0 else 'stayed blocked'} for {signature}"
            ),
            "last_seen_at": finished_at,
            "last_snapshot": after,
            "planner_requested_at": previous.get("planner_requested_at") if same_signature else None,
        }
        metadata["progress_success"] = False
        metadata["just_tripped"] = active and not bool(previous.get("active"))
        return metadata

    metadata["progress_success"] = exit_code == 0
    metadata["just_tripped"] = False
    return metadata


def planner_due(state: dict[str, Any], interval_seconds: int) -> bool:
    last_success = (
        state.get("last_success_by_role", {})
        if isinstance(state.get("last_success_by_role"), dict)
        else {}
    )
    raw = str(last_success.get("planner") or "")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - last).total_seconds() >= interval_seconds


def last_integrator_metadata(state: dict[str, Any]) -> dict[str, Any] | None:
    history = state.get("history")
    if not isinstance(history, list):
        return None
    for entry in reversed(history):
        if not isinstance(entry, dict) or entry.get("role") != "integrator":
            continue
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            return None
        return metadata
    return None


def last_integrator_accepted_by_role(state: dict[str, Any]) -> dict[str, int] | None:
    metadata = last_integrator_metadata(state)
    if not metadata:
        return None
    raw = metadata.get("accepted_by_role")
    if not isinstance(raw, dict):
        return None
    return {role: int(raw.get(role, 0) or 0) for role in ("planner", "builder", "hardener")}


def planner_fast_follow_after_deferral(state: dict[str, Any]) -> bool:
    if str(state.get("last_completed_role") or "") != "integrator":
        return False
    metadata = last_integrator_metadata(state)
    if not metadata:
        return False
    deferred_delta = metadata.get("deferred_delta_by_role")
    if not isinstance(deferred_delta, dict):
        return False
    return int(deferred_delta.get("planner", 0) or 0) > 0


def role_after_integrator(state: dict[str, Any]) -> tuple[str, str]:
    accepted_by_role = last_integrator_accepted_by_role(state)
    if not accepted_by_role:
        return "builder", "builder-first policy: last integration has no source-role metadata"
    if int(accepted_by_role.get("builder", 0)) > 0:
        return "hardener", "builder patch integrated; hardener gets one verification pass"
    accepted_total = sum(int(value) for value in accepted_by_role.values())
    if accepted_total > 0:
        return "builder", "builder-first policy: last integration did not accept builder patches"
    return "builder", "builder-first policy: last integration accepted no patches"


def choose_next(
    target: Path,
    state: dict[str, Any],
    planner_interval_seconds: int,
    no_progress_threshold: int = DEFAULT_NO_PROGRESS_THRESHOLD,
) -> tuple[str | None, str, bool]:
    status = automation_status(target)
    if status == "CRITICAL_STOP":
        return None, "automation status is CRITICAL_STOP", True
    if status not in ACTIVE_STATUSES:
        return None, f"automation status is {status}; waiting", False

    active, detail = lock_is_active(target / "target" / "codex_automation.lock")
    if active:
        return None, f"main automation lock active: {detail}", False

    if not target_has_multi_role(target):
        return "single_lane", "multi-role files not found; running single-lane wrapper", False

    queue_depth = len(queued_manifests(target))
    if queue_depth:
        return "integrator", f"{queue_depth} queued role patch(es) need integration", False

    if no_progress_active(state, no_progress_threshold):
        info = no_progress_info(state)
        reason = str(info.get("reason") or "integrator made no patch progress")
        if not info.get("planner_requested_at"):
            return "planner", f"no-progress circuit breaker tripped: {reason}", False
        return None, f"no-progress circuit breaker active after planner handoff: {reason}", False

    if unhandled_human_inbox_count(target) and planner_due(state, min(planner_interval_seconds, 900)):
        return "planner", "unhandled human inbox message(s) need triage", False

    if planner_fast_follow_after_deferral(state):
        return "planner", "planner patch deferred by latest integration; fast-follow replanning before hourly interval", False

    if planner_due(state, planner_interval_seconds):
        return "planner", "planner interval elapsed", False

    last_role = str(state.get("last_completed_role") or "")
    if last_role == "integrator":
        role, reason = role_after_integrator(state)
        return role, reason, False
    if last_role == "builder":
        return "hardener", "builder lane completed without queued work; hardener gets the next look", False
    return "builder", "builder lane is next runnable work", False


def conveyor_decision_queue(
    target: Path,
    state: dict[str, Any],
    next_role: str | None,
    next_reason: str,
    planner_interval_seconds: int,
    no_progress_threshold: int,
) -> list[dict[str, str]]:
    """Build a small display queue for observability; choose_next remains authoritative."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(role: str | None, state_name: str, reason: str) -> None:
        key = role or "idle"
        if key in seen:
            return
        seen.add(key)
        entries.append(
            {
                "role": key,
                "state": state_name,
                "reason": re.sub(r"\s+", " ", reason).strip()[:240],
            }
        )

    add(next_role, "next" if next_role else "idle", next_reason)
    if len(entries) >= DECISION_QUEUE_LIMIT:
        return entries

    status = automation_status(target)
    if status == "CRITICAL_STOP":
        add(None, "blocked", "automation status is CRITICAL_STOP")
        return entries[:DECISION_QUEUE_LIMIT]
    if status not in ACTIVE_STATUSES:
        add(None, "blocked", f"automation status is {status}; waiting")
        return entries[:DECISION_QUEUE_LIMIT]

    active, detail = lock_is_active(target / "target" / "codex_automation.lock")
    if active:
        add(None, "blocked", f"main automation lock active: {detail}")
        return entries[:DECISION_QUEUE_LIMIT]

    if not target_has_multi_role(target):
        add("single_lane", "ready", "multi-role files not found; running single-lane wrapper")
        return entries[:DECISION_QUEUE_LIMIT]

    queue_depth = len(queued_manifests(target))
    if queue_depth:
        add("integrator", "ready", f"{queue_depth} queued role patch(es) need integration")

    if no_progress_active(state, no_progress_threshold):
        info = no_progress_info(state)
        reason = str(info.get("reason") or "integrator made no patch progress")
        if not info.get("planner_requested_at"):
            add("planner", "ready", f"no-progress circuit breaker tripped: {reason}")
        else:
            add(None, "blocked", f"no-progress circuit breaker active after planner handoff: {reason}")
    elif unhandled_human_inbox_count(target) and planner_due(state, min(planner_interval_seconds, 900)):
        add("planner", "ready", "unhandled human inbox message(s) need triage")
    elif planner_fast_follow_after_deferral(state):
        add("planner", "ready", "planner patch deferred by latest integration; fast-follow replanning before hourly interval")
    elif planner_due(state, planner_interval_seconds):
        add("planner", "ready", "planner interval elapsed")

    last_role = str(state.get("last_completed_role") or "")
    if last_role == "integrator":
        role, reason = role_after_integrator(state)
        add(role, "planned", reason)
    elif last_role == "builder":
        add("hardener", "planned", "builder lane completed without queued work")
    else:
        add("builder", "planned", "builder lane is the default momentum lane")

    add("hardener", "standby", "hardener verifies recently changed work when integration or builder output exists")
    add("builder", "standby", "builder can create the next implementation patch when planning is fresh")
    return entries[:DECISION_QUEUE_LIMIT]


def command_for_role(role: str) -> list[str]:
    if role == "single_lane":
        return ["bash", "scripts/run_codex_automation.sh"]
    return ["bash", "scripts/run_role_automation.sh", "--role", role]


def terminate_child() -> None:
    global CHILD
    child = CHILD
    if child and child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            child.terminate()


def handle_signal(signum: int, _frame: Any) -> None:
    global TERMINATE_REQUESTED
    TERMINATE_REQUESTED = True
    print(f"CONVEYOR_SIGNAL signal={signum}", flush=True)
    terminate_child()


def run_role(
    target: Path,
    role: str,
    allow_remotes: bool,
    *,
    state_path: Path | None = None,
    reason: str = "",
    started_at: str = "",
) -> int:
    global CHILD
    env = os.environ.copy()
    env["TARGET"] = str(target)
    run_id_value = run_id(role)
    env["CODEX_RUN_ID"] = run_id_value
    env["PATH"] = env.get("CODEX_AUTOMATION_PATH", DEFAULT_AUTOMATION_PATH)
    if allow_remotes:
        env["MULTI_ROLE_ALLOW_REMOTES"] = "1"
    command = command_for_role(role)
    print(f"CONVEYOR_RUN role={role} run_id={run_id_value} command={command_display(command)}", flush=True)
    CHILD = subprocess.Popen(
        command,
        cwd=str(target),
        env=env,
        text=True,
        start_new_session=True,
    )
    if state_path is not None:
        state = load_state(state_path)
        state["active_role_run"] = {
            "role": role,
            "run_id": run_id_value,
            "reason": reason,
            "started_at": started_at or utc_now(),
            "pid": CHILD.pid,
            "command": command,
            "command_display": command_display(command),
            "status": "running",
        }
        write_state(state_path, state)
    try:
        return CHILD.wait()
    finally:
        CHILD = None


def finish_active_role_run(state: dict[str, Any], *, exit_code: int, finished_at: str) -> None:
    active = state.get("active_role_run")
    if not isinstance(active, dict):
        return
    finished = dict(active)
    finished["status"] = "finished"
    finished["exit_code"] = exit_code
    finished["finished_at"] = finished_at
    state["last_active_role_run"] = finished
    state["active_role_run"] = None


def record_cycle(
    state: dict[str, Any],
    *,
    role: str,
    reason: str,
    exit_code: int,
    started_at: str,
    finished_at: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    counts = state.setdefault("role_counts", {})
    if isinstance(counts, dict):
        counts[role] = int(counts.get(role, 0)) + 1
    successes = state.setdefault("last_success_by_role", {})
    progress_success = bool(metadata.get("progress_success", exit_code == 0))
    if isinstance(successes, dict) and exit_code == 0 and progress_success:
        successes[role] = finished_at
    history = state.setdefault("history", [])
    entry = {
        "role": role,
        "reason": reason,
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
        "progress_success": progress_success,
    }
    if metadata:
        entry["metadata"] = metadata
    if isinstance(history, list):
        history.append(entry)
        del history[:-STATE_HISTORY_LIMIT]
    if role == "planner" and no_progress_active(state, int(no_progress_info(state).get("threshold", DEFAULT_NO_PROGRESS_THRESHOLD))):
        info = no_progress_info(state)
        info["planner_requested_at"] = finished_at
        state[NO_PROGRESS_STATE_KEY] = info
    state["cycles"] = int(state.get("cycles", 0)) + 1
    state["last_completed_role"] = role
    state["last_completed_at"] = finished_at
    state["last_exit_code"] = exit_code
    state["last_progress_success"] = progress_success
    return state


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=os.environ.get("TARGET", "."), help="Target project directory")
    parser.add_argument("--once", action="store_true", help="Run one conveyor decision, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Print the next decision without running anything")
    parser.add_argument("--allow-remotes", action="store_true", help="Pass MULTI_ROLE_ALLOW_REMOTES=1 to role runs")
    parser.add_argument("--max-cycles", type=positive_int, default=0, help="Maximum role cycles before exiting; 0 means unlimited")
    parser.add_argument("--idle-sleep-seconds", type=positive_int, default=DEFAULT_IDLE_SLEEP_SECONDS)
    parser.add_argument("--error-sleep-seconds", type=positive_int, default=DEFAULT_ERROR_SLEEP_SECONDS)
    parser.add_argument("--cycle-cooldown-seconds", type=positive_int, default=DEFAULT_CYCLE_COOLDOWN_SECONDS)
    parser.add_argument("--planner-interval-seconds", type=positive_int, default=DEFAULT_PLANNER_INTERVAL_SECONDS)
    parser.add_argument("--scheduler-lock-stale-seconds", type=positive_int, default=DEFAULT_LOCK_STALE_SECONDS)
    parser.add_argument("--no-progress-threshold", type=positive_int, default=DEFAULT_NO_PROGRESS_THRESHOLD)
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    state_path = target / "target" / "automation_conveyor_state.json"
    lock_path = target / "target" / "automation_conveyor.lock"
    state = load_state(state_path)
    role, reason, stop = choose_next(target, state, args.planner_interval_seconds, args.no_progress_threshold)

    if args.dry_run:
        queue = conveyor_decision_queue(
            target,
            state,
            role,
            reason,
            args.planner_interval_seconds,
            args.no_progress_threshold,
        )
        print(
            json.dumps(
                {
                    "target": str(target),
                    "next_role": role,
                    "reason": reason,
                    "stop": stop,
                    "decision_queue": queue,
                    "queued_patch_count": len(queued_manifests(target)),
                    "automation_status": automation_status(target),
                    "integrator_no_progress": no_progress_info(state),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if not acquire_scheduler_lock(lock_path, args.scheduler_lock_stale_seconds):
        return 0

    cycles = 0
    last_exit = 0
    allow_remotes = args.allow_remotes or os.environ.get("MULTI_ROLE_ALLOW_REMOTES") == "1"
    try:
        while not TERMINATE_REQUESTED:
            state = load_state(state_path)
            role, reason, stop = choose_next(target, state, args.planner_interval_seconds, args.no_progress_threshold)
            state["last_decision"] = {"role": role, "reason": reason, "decided_at": utc_now()}
            state["decision_queue"] = conveyor_decision_queue(
                target,
                state,
                role,
                reason,
                args.planner_interval_seconds,
                args.no_progress_threshold,
            )
            write_state(state_path, state)
            print(f"CONVEYOR_DECISION role={role or 'idle'} reason={reason}", flush=True)

            if stop:
                return 0
            if role is None:
                if args.once:
                    return 0
                time.sleep(args.idle_sleep_seconds)
                continue

            started_at = utc_now()
            before_snapshot = queue_snapshot(target) if role == "integrator" else None
            exit_code = run_role(
                target,
                role,
                allow_remotes,
                state_path=state_path,
                reason=reason,
                started_at=started_at,
            )
            finished_at = utc_now()
            state = load_state(state_path)
            finish_active_role_run(state, exit_code=exit_code, finished_at=finished_at)
            metadata: dict[str, Any] = {}
            if role == "integrator" and before_snapshot is not None:
                after_snapshot = queue_snapshot(target)
                metadata = update_integrator_no_progress(
                    state,
                    before=before_snapshot,
                    after=after_snapshot,
                    exit_code=exit_code,
                    threshold=args.no_progress_threshold,
                    finished_at=finished_at,
                )
                if metadata.get("just_tripped"):
                    write_no_progress_progress_note(target, no_progress_info(state))
            record_cycle(
                state,
                role=role,
                reason=reason,
                exit_code=exit_code,
                started_at=started_at,
                finished_at=finished_at,
                metadata=metadata,
            )
            write_state(state_path, state)
            print(
                f"CONVEYOR_RESULT role={role} exit={exit_code} progress={state.get('last_progress_success')}",
                flush=True,
            )
            last_exit = exit_code
            cycles += 1

            if args.once:
                return exit_code
            if args.max_cycles and cycles >= args.max_cycles:
                return last_exit
            if TERMINATE_REQUESTED:
                return 143
            if exit_code != 0:
                time.sleep(args.error_sleep_seconds)
            elif args.cycle_cooldown_seconds:
                time.sleep(args.cycle_cooldown_seconds)
        return 143
    finally:
        terminate_child()
        release_scheduler_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
