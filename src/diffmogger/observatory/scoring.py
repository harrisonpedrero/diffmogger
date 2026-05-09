from __future__ import annotations

from .common import *
from .queue_state import no_progress_summary, role_count_summary

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
    data = read_json(runtime_path(target, ACTION_PLAN_HISTORY_RELATIVE))
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
        "storage_path": target_rel(target, ACTION_PLAN_HISTORY_RELATIVE.as_posix()),
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
    path = runtime_path(target, ACTION_PLAN_HISTORY_RELATIVE)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": clean_text(snapshot.get("generated_at") or utc_now(), limit=80),
        "records": records,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    snapshot["recommendation_history"] = {
        "storage_path": target_rel(target, ACTION_PLAN_HISTORY_RELATIVE.as_posix()),
        "summary": recommendation_history_summary(records),
        "records": records,
    }
    return snapshot

def worker_strategy_snapshot(
    task: dict[str, Any],
    queue: dict[str, Any],
    conveyor: dict[str, Any],
    progress: dict[str, Any],
    action_plan: dict[str, Any],
    recommendation_history: dict[str, Any],
) -> dict[str, Any]:
    worker_config = task.get("worker") if isinstance(task.get("worker"), dict) else {}
    worker_agents_allowed = bool(worker_config.get("agents_allowed", True))
    write_workers_allowed = bool(worker_config.get("write_workers_allowed"))
    max_write_workers = history_int(worker_config.get("max_write_worker_count", 0))
    action_lane = clean_text(action_plan.get("lane") or "local", limit=40)
    action_priority = clean_text(action_plan.get("priority") or "normal", limit=40).lower()
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}
    queued = history_int(totals.get("queued", 0))
    deferred_manifest_count = history_int(totals.get("deferred", 0))
    deferred_backlog = history_int(progress.get("deferred_queue_depth", 0))
    deferred_pressure = max(deferred_manifest_count, deferred_backlog)
    no_progress = conveyor.get("no_progress") if isinstance(conveyor.get("no_progress"), dict) else {}
    records = [
        item
        for item in list(recommendation_history.get("records") or [])
        if isinstance(item, dict)
    ]
    pending_or_no_progress = sum(
        1
        for record in records
        if (
            clean_text(record.get("status") or "", limit=40) == "still_pending"
            or clean_text(record.get("no_progress") or "inactive", limit=80) != "inactive"
        )
    )

    reasons: list[str] = []
    next_steps: list[str] = []

    def result(strategy: str, budget: int, summary: str) -> dict[str, Any]:
        return {
            "strategy": strategy,
            "parallelism_budget": max(0, budget),
            "summary": clean_text(summary, limit=420),
            "reasons": [clean_text(item, limit=260) for item in reasons[:MAX_WORKER_STRATEGY_REASONS]],
            "next_steps": [clean_text(item, limit=320) for item in next_steps[:MAX_REVIEW_ITEMS]],
            "action_lane": action_lane,
        }

    if not worker_agents_allowed:
        reasons.append("Worker agents are disabled in the target task state.")
        next_steps.extend(
            [
                "Keep the next run in the main agent.",
                "Re-enable workers only through reviewed target-local automation settings.",
            ]
        )
        return result("NO_WORKERS", 0, "Run without workers because target-local worker agents are disabled.")

    if action_lane == "human" or action_priority == "blocked":
        reasons.append("The current action plan is blocked on human input.")
        next_steps.extend(
            [
                "Wait for or archive the human bridge reply before spawning workers.",
                "Continue only reversible local work that does not depend on the reply.",
            ]
        )
        return result("NO_WORKERS", 0, "Do not spawn workers while the highest-priority lane is blocked on human input.")

    if action_lane == "integrator" or queued or deferred_pressure:
        if queued:
            reasons.append(f"{queued} queued patch(es) need main-agent integration.")
        if deferred_pressure:
            reasons.append(f"{deferred_pressure} deferred backlog item(s) need triage.")
        next_steps.extend(
            [
                "Run the integrator lane locally and keep patch acceptance or deferral decisions in the main agent.",
                "Use workers only after the queue is clear or a specific non-overlapping triage audit is needed.",
            ]
        )
        return result("INTEGRATION_ONLY", 0, "Use an integration-only run before creating more worker output.")

    if no_progress.get("active") or pending_or_no_progress >= 2:
        if no_progress.get("active"):
            reasons.append(no_progress_summary(no_progress))
        if pending_or_no_progress >= 2:
            reasons.append(f"{pending_or_no_progress} recent recommendation-history record(s) show pending or no-progress evidence.")
        next_steps.extend(
            [
                "Ask one read-only worker to identify the smallest unblock or stale-loop cause.",
                "Keep implementation local until the no-progress pattern has a concrete next action.",
            ]
        )
        return result("READ_ONLY_REPORTS", 1, "Use one read-only worker report to diagnose repeated pending or no-progress evidence.")

    if action_lane in {"planner", "hardener"}:
        reasons.append(f"The current action plan points at the `{action_lane}` lane, where review coverage is usually higher value than parallel edits.")
        next_steps.extend(
            [
                f"Use one bounded read-only `{action_lane}` report if the scope is broad.",
                "Keep any code changes in the main agent unless ownership can be split cleanly.",
            ]
        )
        return result("READ_ONLY_REPORTS", 1, f"Use one read-only worker report for the next `{action_lane}` pass if the task is broad.")

    if action_lane == "builder" and write_workers_allowed and max_write_workers:
        budget = min(max_write_workers, 2)
        reasons.append("The current action plan points at builder momentum with no queue, validation, human, or no-progress blocker ahead of it.")
        reasons.append(f"Write-capable workers are enabled with a configured cap of {max_write_workers}.")
        next_steps.extend(
            [
                "Split work into disjoint file or module ownership before launching write workers.",
                "Keep the main agent responsible for reviewing, integrating, and verifying worker diffs.",
            ]
        )
        return result("WRITE_WORKERS", budget, f"Use up to {budget} bounded write worker(s) only when the builder increment splits cleanly.")

    if action_lane == "builder":
        reasons.append("The current action plan points at builder momentum, but write-capable workers are not enabled in target task state.")
        next_steps.extend(
            [
                "Use one read-only design or test-gap report for broad builder work.",
                "Keep implementation in the main agent unless target-local settings explicitly enable write workers.",
            ]
        )
        return result("READ_ONLY_REPORTS", 1, "Use one read-only worker report for broad builder work; keep edits in the main agent.")

    reasons.append("No worker-friendly split is visible from the current local state.")
    next_steps.extend(
        [
            "Keep the next run in the main agent.",
            "Reconsider workers after the action plan names independent review or implementation lanes.",
        ]
    )
    return result("NO_WORKERS", 0, "Run without workers until the next action has a clearer parallelization boundary.")

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
                "Do not use Discord, notifier APIs, or external channels in file-only mode.",
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
        "why": "No human bridge item, validation failure, queued patch, deferred backlog, or conveyor handoff currently outranks builder work.",
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
