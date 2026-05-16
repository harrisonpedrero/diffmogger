from __future__ import annotations

import re
from contextlib import closing

from .scheduler import choose_next_dag
from .state import *
from diffmogger.runtime.state_store import connect, database_path_for_target, latest_scheduler_decision_conn

def choose_next(
    target: Path,
    state: dict[str, Any],
    no_progress_threshold: int = DEFAULT_NO_PROGRESS_THRESHOLD,
) -> tuple[str | None, str, bool]:
    return choose_next_dag(target, state, no_progress_threshold)

def conveyor_decision_queue(
    target: Path,
    state: dict[str, Any],
    next_role: str | None,
    next_reason: str,
    no_progress_threshold: int,
) -> list[dict[str, str]]:
    """Build a display queue from the latest execution-DAG scheduler decision."""
    del state, no_progress_threshold
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(role: str | None, state_name: str, reason: str, *, action_kind: str = "") -> None:
        key = role or "idle"
        action = action_kind or key
        seen_key = f"{key}:{action}:{state_name}"
        if seen_key in seen:
            return
        seen.add(seen_key)
        entries.append(
            {
                "role": key,
                "action_kind": action_kind,
                "state": state_name,
                "reason": re.sub(r"\s+", " ", reason).strip()[:240],
            }
        )

    try:
        with closing(connect(database_path_for_target(target))) as conn:
            scheduler_decision = latest_scheduler_decision_conn(conn)
    except Exception:
        scheduler_decision = {}
    candidates = (
        scheduler_decision.get("scheduling_candidates")
        if isinstance(scheduler_decision.get("scheduling_candidates"), list)
        else []
    )
    if not candidates:
        add(next_role, "next" if next_role else "idle", next_reason)
        return entries[:DECISION_QUEUE_LIMIT]

    selected = scheduler_decision.get("selected_candidate") if isinstance(scheduler_decision.get("selected_candidate"), dict) else {}
    if selected:
        reason_items = selected.get("reasons") if isinstance(selected.get("reasons"), list) else []
        reason = "; ".join(str(item) for item in reason_items[:2]) or next_reason
        add(
            str(selected.get("role") or next_role or ""),
            "next" if not bool(selected.get("stop")) else "blocked",
            reason,
            action_kind=str(selected.get("action_kind") or ""),
        )
    else:
        add(next_role, "next" if next_role else "idle", next_reason)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        state_name = str(candidate.get("state") or "ready")
        if state_name == "selected":
            continue
        task_label = str(candidate.get("public_task_id") or candidate.get("task_id") or candidate.get("execution_group_id") or "")
        action_kind = str(candidate.get("action_kind") or "")
        reason_items = candidate.get("reasons") if isinstance(candidate.get("reasons"), list) else []
        reason = "; ".join(str(item) for item in reason_items[:2])
        if state_name == "skipped":
            reason = str(candidate.get("skipped_reason") or reason or "DAG candidate is not currently runnable")
        if task_label:
            reason = f"{action_kind or 'dag action'} for {task_label}: {reason or state_name}"
        else:
            reason = f"{action_kind or 'dag action'}: {reason or state_name}"
        add(
            str(candidate.get("role") or ""),
            state_name if state_name in {"ready", "skipped", "blocked"} else "ready",
            reason,
            action_kind=action_kind,
        )
        if len(entries) >= DECISION_QUEUE_LIMIT:
            break
    return entries[:DECISION_QUEUE_LIMIT]
