from __future__ import annotations

from .common import *
from .html_render import render_html
from .scoring import history_int, recommendation_history_summary

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
    worker_strategy = snapshot.get("worker_strategy") if isinstance(snapshot.get("worker_strategy"), dict) else {}
    baseline_verification = (
        snapshot.get("baseline_verification") if isinstance(snapshot.get("baseline_verification"), dict) else {}
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
        storage_path = clean_text(recommendation_history.get("storage_path") or target_rel(target, ACTION_PLAN_HISTORY_RELATIVE.as_posix()), limit=160)
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

    lines.extend(["", "## Next-Run Worker Strategy", ""])
    if worker_strategy:
        lines.append(f"- strategy: `{clean_text(worker_strategy.get('strategy') or 'NO_WORKERS', limit=80)}`")
        lines.append(f"- parallelism_budget: {history_int(worker_strategy.get('parallelism_budget', 0))}")
        lines.append(f"- action_lane: `{clean_text(worker_strategy.get('action_lane') or 'local', limit=80)}`")
        lines.append(
            f"- summary: {clean_text(worker_strategy.get('summary') or 'No next-run worker strategy recorded yet.', limit=500)}"
        )
        reasons = [item for item in list(worker_strategy.get("reasons") or []) if item]
        if reasons:
            lines.append("- reasons:")
            for reason in reasons[:MAX_WORKER_STRATEGY_REASONS]:
                lines.append(f"  - {clean_text(reason, limit=420)}")
        steps = [item for item in list(worker_strategy.get("next_steps") or []) if item]
        if steps:
            lines.append("- next_steps:")
            for step in steps[:MAX_REVIEW_ITEMS]:
                lines.append(f"  - {clean_text(step, limit=420)}")
    else:
        lines.append("- No next-run worker strategy recorded yet.")

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

    lines.extend(["", "## Baseline Verification", ""])
    lines.append(f"- status: {clean_text(baseline_verification.get('status') or 'not_recorded', limit=80)}")
    lines.append(
        f"- root_cause: {clean_text(baseline_verification.get('root_cause') or baseline_verification.get('summary') or 'No baseline verification ledger recorded yet.', limit=500)}"
    )
    lines.append(
        f"- next_action: {clean_text(baseline_verification.get('next_action') or 'Run integrator baseline preflight.', limit=500)}"
    )

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
