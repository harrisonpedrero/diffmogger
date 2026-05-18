from __future__ import annotations

from .common import *
from .queue_state import active_run, no_progress_summary
from .scoring import (
    follow_through_summary,
    history_int,
    recommendation_history_summary,
    scorecard_action_plan,
)

def validation_check_status(text: str) -> str:
    lower = text.lower().strip()
    if lower.startswith("pass"):
        return "pass"
    if lower.startswith("fail"):
        return "fail"
    if lower.startswith("warn"):
        return "warn"
    if lower.startswith("pending") or lower.startswith("not run") or "not run yet" in lower:
        return "pending"
    if re.search(r"\bpassed\b", lower):
        return "pass"
    if re.search(r"\bfailed\b|\bfailure\b", lower):
        return "fail"
    if re.search(r"\bwarning\b|\bwarned\b", lower):
        return "warn"
    if re.search(r"\bnot run\b", lower):
        return "pending"
    return "info"

def is_integration_safety_check(text: str) -> bool:
    lower = text.lower()
    return (
        "scripts/check_integration_safety.py" in lower
        or "integration safety" in lower
        or "integration-safety" in lower
    )

def validation_snapshot(text: str) -> dict[str, Any]:
    """Compatibility parser for explicit review/import Markdown, not live Observatory state."""

    checks: list[dict[str, str]] = []
    counts = {"pass": 0, "fail": 0, "warn": 0, "pending": 0, "info": 0}
    counted_checks = 0
    for bullet in section_bullets(text, "Checks From Last Run", limit=MAX_CHECK_ITEMS):
        if bullet.lower().startswith("preferred commands"):
            continue
        if bullet.startswith("`") and any(item["status"] == "pending" for item in checks):
            continue
        status = validation_check_status(bullet)
        if status == "pending" and is_integration_safety_check(bullet):
            continue
        counts[status] += 1
        counted_checks += 1
        checks.append({"status": status, "text": bullet})

    if not checks:
        return {
            "summary": "No validation results recorded yet.",
            "counts": counts,
            "items": [],
        }
    if not counted_checks:
        return {"summary": "No validation results recorded yet.", "counts": counts, "items": checks}

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
    record = read_json(dpath(target, INTEGRATION_SAFETY_RECORD_RELATIVE))
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
    if target is not None:
        record_snapshot = integration_safety_record_snapshot(target)
        if record_snapshot:
            return record_snapshot

    items = [item for item in list(validation.get("items") or []) if isinstance(item, dict)]
    pending_snapshot: dict[str, Any] | None = None
    for item in items:
        text = clean_text(item.get("text") or "", limit=420)
        lower = text.lower()
        if not is_integration_safety_check(text):
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
            summary = f"Integration-safety check has not run yet; use dashboard Run Safety Check to record `{command}`."
        else:
            summary = f"Integration-safety check was recorded without pass/fail status: `{command}`."
        item_snapshot = {
            "status": status,
            "summary": summary,
            "command": command,
            "recorded_text": text,
        }
        if status == "pending":
            pending_snapshot = item_snapshot
            continue
        return item_snapshot

    if pending_snapshot:
        return pending_snapshot

    return {
        "status": "pending",
        "summary": "Integration-safety check has not run yet for this target; use dashboard Run Safety Check before the first review or unattended automation.",
        "command": "python3 scripts/check_integration_safety.py",
        "recorded_text": "",
        "source": "target/integration_safety_check.json",
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

def first_review_validation_detail(target: Path) -> str:
    if (target / "scripts" / "validate_starter_kit.sh").is_file():
        return "No passing validation run is recorded in the task file yet."
    return (
        "No passing target-local validation run is recorded yet. Generated targets usually show this "
        "until the first automation run creates or confirms the project's own checks."
    )

def first_review_validation_missing_action(target: Path) -> str:
    if (target / "scripts" / "validate_starter_kit.sh").is_file():
        return "Record a passing `bash scripts/validate_starter_kit.sh` run."
    return (
        "Complete the first automation run and record a passing target-local verification receipt in typed runtime state."
    )

def first_review_snapshot(target: Path, task: dict[str, Any]) -> dict[str, Any]:
    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    validation_counts = validation.get("counts") if isinstance(validation.get("counts"), dict) else {}
    pass_count = int(validation_counts.get("pass", 0) or 0)
    fail_count = int(validation_counts.get("fail", 0) or 0)
    integration_safety = task.get("integration_safety") if isinstance(task.get("integration_safety"), dict) else {}
    integration_status = clean_text(integration_safety.get("status") or "pending", limit=40)
    docs = first_review_doc_coverage(target)

    if fail_count:
        validation_status = "fail"
        validation_detail = validation.get("summary") or f"{fail_count} validation issue(s) recorded."
    elif pass_count:
        validation_status = "pass"
        validation_detail = validation.get("summary") or f"{pass_count} passing check(s) recorded."
    else:
        validation_status = "warn"
        validation_detail = first_review_validation_detail(target)

    safety_status = "pass" if integration_status == "pass" else ("fail" if integration_status == "fail" else "warn")
    safety_detail = integration_safety.get("summary") or "Integration-safety check has not run yet."

    items = [
        {"label": "Checklist docs", "status": docs["status"], "detail": docs["detail"]},
        {"label": "Validation", "status": validation_status, "detail": validation_detail},
        {"label": "Run Safety Check", "status": safety_status, "detail": safety_detail},
    ]
    missing_actions: list[str] = []
    missing_labels: list[str] = []
    if docs["status"] != "pass":
        missing_labels.append("checklist doc")
        missing_actions.append("Update a first-review checklist doc with the validation, safety, observatory, and Markdown export steps.")
    if validation_status != "pass":
        missing_labels.append("validation")
        missing_actions.append(first_review_validation_missing_action(target))
    if safety_status != "pass":
        missing_labels.append("run safety check")
        missing_actions.append("Run dashboard **Run Safety Check** or `python3 scripts/check_integration_safety.py` and record the result.")

    status = "ready" if not missing_actions else "attention"
    if status == "ready":
        summary = "First-review path is ready: checklist docs, validation, and integration safety are all recorded."
        short_status = "ready"
    elif missing_labels == ["checklist doc"]:
        summary = "First-review checklist doc is missing; validation and run safety are recorded."
        short_status = "checklist"
    else:
        summary = f"First-review setup needs {', '.join(missing_labels)}."
        short_status = "needs setup"

    return {
        "status": status,
        "short_status": short_status,
        "summary": summary,
        "items": items,
        "missing_actions": missing_actions,
        "missing_labels": missing_labels,
        "docs": docs.get("docs", []),
    }

def self_review_snapshot(
    task: dict[str, Any],
    queue: dict[str, Any],
    conveyor: dict[str, Any],
    human: dict[str, int],
    progress: dict[str, Any],
    first_review: dict[str, Any],
    follow_through: dict[str, Any] | None = None,
    recommendation_history: dict[str, Any] | None = None,
    worker_strategy: dict[str, Any] | None = None,
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
            conveyor_summary = "No runtime decision recorded yet."
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
    action_plan = scorecard_action_plan(task, queue, conveyor, human, progress)
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
    worker_strategy = worker_strategy if isinstance(worker_strategy, dict) else {}
    worker_summary = clean_text(
        worker_strategy.get("summary") or "No next-run worker strategy recorded yet.",
        limit=420,
    )
    if worker_strategy.get("strategy"):
        worker_summary = (
            f"{clean_text(worker_strategy.get('strategy'), limit=80)} with budget "
            f"{history_int(worker_strategy.get('parallelism_budget', 0))}: {worker_summary}"
        )
    return {
        "items": [
            {"label": "Current assessment", "body": task.get("current_assessment") or "No current assessment recorded yet."},
            {"label": "First review", "body": first_review.get("summary") or "No first-review readiness state recorded yet."},
            {"label": "Validation", "body": validation.get("summary") or "No validation results recorded yet."},
            {"label": "Integration safety", "body": integration_safety.get("summary") or "Integration-safety check has not run yet."},
            {"label": "Queue and activity", "body": f"{queue_summary} {conveyor_summary}"},
            {"label": "Human bridge", "body": human_summary},
            {"label": "Action plan", "body": f"{action_plan['recommendation']} {action_plan['why']}"},
            {"label": "Action follow-through", "body": follow_through_summary(follow_through or {})},
            {"label": "Recommendation history", "body": history_summary},
            {"label": "Worker strategy", "body": worker_summary},
            {"label": "Deferred triage", "body": f"{deferred_summary} {deferred_action}"},
            {"label": "Next sprint", "body": task.get("suggested_next_task") or "No sprint task recorded yet."},
        ],
        "checks": list(validation.get("items") or [])[:MAX_CHECK_ITEMS],
        "known_issues": list(task.get("known_issues") or [])[:MAX_REVIEW_ITEMS],
    }
