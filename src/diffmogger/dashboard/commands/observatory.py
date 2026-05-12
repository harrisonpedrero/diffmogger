from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

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
        badge("Safety", safety.get("status") or "pending", "good" if safety.get("status") == "pass" else "warn"),
        badge("Human", pending_human, "warn" if pending_human else "good"),
    ]
    queue_totals = {name: as_int(totals.get(name)) for name in ["queued", "deferred", "applied", "failed", "skipped"]}
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
