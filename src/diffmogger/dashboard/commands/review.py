from __future__ import annotations

import hashlib

from ..errors import *
from ..jsonio import *
from ..target import *

from .run_schedule import automation_prerequisites, latest_run_log, prereq_rows

def is_integration_safety_check(text: str) -> bool:
    lower = text.lower()
    return (
        "scripts/check_integration_safety.py" in lower
        or "integration safety" in lower
        or "integration-safety" in lower
    )

def authoritative_safety_recorded(safety: dict[str, Any]) -> bool:
    status = str(safety.get("status") or "").lower()
    return status in {"pass", "fail", "warn"}

def review_validation_items(validation: dict[str, Any], safety: dict[str, Any]) -> list[dict[str, Any]]:
    items = validation.get("items") if isinstance(validation.get("items"), list) else []
    filtered: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").lower()
        body = str(item.get("text") or "")
        if status == "pending" and authoritative_safety_recorded(safety) and is_integration_safety_check(body):
            continue
        filtered.append(item)
    return filtered

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

def review_environment_limitations(
    snapshot: dict[str, Any],
    environment_blockers: list[dict[str, Any]],
    safety: dict[str, Any],
) -> list[dict[str, Any]]:
    task = snapshot.get("task") if isinstance(snapshot.get("task"), dict) else {}
    validation = task.get("validation") if isinstance(task.get("validation"), dict) else {}
    items = review_validation_items(validation, safety)
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

def review_snapshot_fingerprint(
    raw: dict[str, Any],
    changed_files: list[dict[str, Any]],
    changed_source: str,
    limitations: list[dict[str, Any]],
) -> str:
    task = raw.get("task") if isinstance(raw.get("task"), dict) else {}
    git = raw.get("git") if isinstance(raw.get("git"), dict) else {}
    scorecard = raw.get("scorecard") if isinstance(raw.get("scorecard"), dict) else {}
    payload = {
        "task_status": task.get("status"),
        "task_horizon": task.get("horizon"),
        "validation": task.get("validation") if isinstance(task.get("validation"), dict) else {},
        "integration_safety": task.get("integration_safety") if isinstance(task.get("integration_safety"), dict) else {},
        "changed_files": changed_files,
        "changed_files_source": changed_source,
        "latest_commits": git.get("commits")[:8] if isinstance(git.get("commits"), list) else [],
        "human": raw.get("human") if isinstance(raw.get("human"), dict) else {},
        "queue_totals": (raw.get("queue") or {}).get("totals") if isinstance(raw.get("queue"), dict) else {},
        "action_plan": scorecard.get("action_plan") if isinstance(scorecard.get("action_plan"), dict) else {},
        "limitations": limitations,
        "progress_recent": raw.get("progress_recent"),
    }
    encoded = json.dumps(payload, sort_keys=True, default=json_default).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def review_marker_snapshot(target: Path, *, current_fingerprint: str = "") -> dict[str, Any]:
    path = review_marker_path(target)
    data = read_json_file(path)
    if not data:
        return {
            "exists": False,
            "path": str(path),
            "reviewed_at": "",
            "note": "",
            "snapshot_generated_at": "",
            "review_fingerprint": "",
            "is_current_snapshot": False,
        }
    marker_fingerprint = data.get("review_fingerprint") or ""
    return {
        "exists": True,
        "path": str(path),
        "reviewed_at": data.get("reviewed_at") or "",
        "note": data.get("note") or "",
        "snapshot_generated_at": data.get("snapshot_generated_at") or "",
        "review_fingerprint": marker_fingerprint,
        "is_current_snapshot": bool(current_fingerprint and marker_fingerprint == current_fingerprint),
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
    prerequisites = automation_prerequisites(target, dashboard_app)
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
    validation_items = review_validation_items(validation, safety)
    limitations = review_environment_limitations(raw, environment_blockers, safety)
    review_fingerprint = review_snapshot_fingerprint(raw, changed_files[:24], changed_source, limitations)
    return {
        "target": target_metadata(target),
        "generated_at": raw.get("generated_at"),
        "review_fingerprint": review_fingerprint,
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
            "items": validation_items,
            "baseline": baseline,
        },
        "safety": safety or {
            "status": "pending",
            "summary": "Integration-safety check has not run yet.",
            "command": "python3 scripts/check_integration_safety.py",
        },
        "limitations": limitations,
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
        "reviewed": review_marker_snapshot(target, current_fingerprint=review_fingerprint),
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
    snapshot = review_load_snapshot(target)
    path = review_marker_path(target)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot_generated_at": snapshot.get("generated_at"),
        "review_fingerprint": snapshot.get("review_fingerprint") or "",
        "automation_status": (snapshot.get("latest_run") or {}).get("status") if isinstance(snapshot.get("latest_run"), dict) else "UNKNOWN",
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
        "reviewed": review_marker_snapshot(target, current_fingerprint=str(payload.get("review_fingerprint") or "")),
        "marker_path": str(path),
    }
