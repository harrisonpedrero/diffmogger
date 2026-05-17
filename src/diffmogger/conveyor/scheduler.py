from __future__ import annotations

import json
import re
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from diffmogger.conveyor.baseline import automation_status
from diffmogger.conveyor.state import ACTIVE_STATUSES, DEFAULT_NO_PROGRESS_THRESHOLD
from diffmogger.conveyor.tickets import ticket_campaign_terminal
from diffmogger.runtime import ticket_run as ticket_runtime
from diffmogger.runtime.state_store import (
    COMPATIBILITY_CONVEYOR_TASK_IDS,
    connect,
    can_start_execution_group,
    create_refresh_index_nodes_for_stale_evidence_conn,
    database_path_for_target,
    ensure_automation_control_conn,
    ensure_codebase_graph_conn,
    ensure_parallelism_budgets_conn,
    execution_dag_action_capability,
    execution_dag_read_model,
    expire_stale_leases_conn,
    failed_validation_jobs_requiring_dag_action_conn,
    materialize_execution_dag_conn,
    plan_parallel_execution_groups_conn,
    ready_integration_patch_ids_conn,
    refresh_capability_manifest_conn,
    refresh_impact_graph_conn,
    refresh_task_graph_conn,
    sync_queued_role_manifests_into_worker_patches_conn,
    utc_now,
    validation_jobs_conn,
    worker_patch_integration_preflight_conn,
    worker_patches_conn,
    write_scheduler_decision_conn,
)


DAG_RUNNER_ACTIONS = {
    "launch_scope_group",
    "launch_write_group",
    "launch_validation_group",
    "launch_review_group",
    "run_serial_role",
    "run_serial_integration",
    "reconcile_worker_results",
    "create_repair_nodes",
    "refresh_index",
}


def _brief(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(0, limit - 3)].rstrip() + "..." if len(text) > limit else text


def _candidate(
    *,
    action_kind: str,
    role: str,
    score: float,
    reason: str,
    dag_node_id: str = "",
    task_id: str = "",
    execution_group_id: str = "",
    group: Mapping[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
    skipped_reason: str = "",
    patch_ids: list[str] | None = None,
    integration_preflight: Mapping[str, Any] | None = None,
    next_evidence_hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    group_payload = group.get("payload") if isinstance(group, Mapping) and isinstance(group.get("payload"), Mapping) else {}
    group_items = group.get("items") if isinstance(group, Mapping) and isinstance(group.get("items"), list) else []
    item_payloads = [
        item.get("payload")
        for item in group_items
        if isinstance(item, Mapping) and isinstance(item.get("payload"), Mapping)
    ]
    first_context_pack = next(
        (
            payload.get("context_pack_preview")
            for payload in item_payloads
            if isinstance(payload.get("context_pack_preview"), Mapping)
        ),
        {},
    )
    required_leases = [
        dict(lease)
        for item in group_items
        if isinstance(item, Mapping)
        for lease in (item.get("required_leases") if isinstance(item.get("required_leases"), list) else [])
        if isinstance(lease, Mapping)
    ]
    scope_evidence = [
        dict(payload.get("scope_evidence"))
        for payload in item_payloads
        if isinstance(payload.get("scope_evidence"), Mapping)
    ]
    evidence_hints: list[dict[str, Any]] = [dict(item) for item in (next_evidence_hints or []) if isinstance(item, Mapping)]
    for payload in [group_payload, *item_payloads]:
        hints = payload.get("next_evidence_hints") if isinstance(payload, Mapping) and isinstance(payload.get("next_evidence_hints"), list) else []
        for hint in hints:
            if isinstance(hint, Mapping):
                evidence_hints.append(dict(hint))
    for blocker in blockers or []:
        if not isinstance(blocker, Mapping):
            continue
        reason_kind = str(blocker.get("reason_kind") or "")
        if reason_kind:
            evidence_hints.append(
                {
                    "reason_kind": reason_kind,
                    "next_action": str(blocker.get("next_action") or blocker.get("reason") or "inspect blocked scheduler candidate"),
                    "source": "scheduler_blocker",
                }
            )
    if integration_preflight:
        for key, next_action in (
            ("likely_conflict_count", "review conflicting queued patch surfaces before integration"),
            ("stale_base_count", "refresh or rebase stale queued patches before integration"),
            ("missing_metadata_count", "reconcile patch metadata before integration"),
        ):
            if int(integration_preflight.get(key) or 0):
                evidence_hints.append({"reason_kind": key, "next_action": next_action, "source": "integration_preflight"})
    first_group_task_id = next(
        (
            str(item.get("task_id") or item.get("graph_task_node_id") or "")
            for item in group_items
            if isinstance(item, Mapping) and str(item.get("task_id") or item.get("graph_task_node_id") or "")
        ),
        "",
    )
    resolved_task_id = task_id or str(group_payload.get("task_id") or "") or first_group_task_id
    return {
        "role": role,
        "task_id": resolved_task_id,
        "public_task_id": resolved_task_id,
        "dag_node_id": dag_node_id,
        "execution_group_id": execution_group_id or (str(group.get("execution_group_id") or "") if isinstance(group, Mapping) else ""),
        "action_kind": action_kind,
        "score": round(float(score), 4),
        "reasons": [_brief(reason)],
        "blockers": list(blockers or []),
        "required_leases": required_leases[:8],
        "suggested_leases": [],
        "acquired_leases": [],
        "context_pack_preview": dict(first_context_pack) if isinstance(first_context_pack, Mapping) else {},
        "scope_evidence": scope_evidence[:6],
        "scope_evidence_required": bool(group_payload.get("scope_evidence_required")),
        "patch_ids": list(patch_ids or [])[:20],
        "integration_preflight": dict(integration_preflight or {}),
        "next_evidence_hints": evidence_hints[:12],
        "skipped_reason": skipped_reason,
        "stop": False,
        "source": "execution_dag_scheduler",
        "scheduler_fallback_used": False,
    }


def _idle_candidate(reason: str, *, stop: bool = False) -> dict[str, Any]:
    return {
        "role": "",
        "task_id": "",
        "public_task_id": "",
        "dag_node_id": "",
        "execution_group_id": "",
        "action_kind": "idle" if not stop else "terminal_stop",
        "score": 0.0 if not stop else 100.0,
        "reasons": [_brief(reason)],
        "blockers": [],
        "required_leases": [],
        "suggested_leases": [],
        "acquired_leases": [],
        "context_pack_preview": {},
        "skipped_reason": "",
        "stop": stop,
        "source": "execution_dag_scheduler",
        "scheduler_fallback_used": False,
    }


def _group_action(group: Mapping[str, Any]) -> tuple[str, str, float, str]:
    payload = group.get("payload") if isinstance(group.get("payload"), Mapping) else {}
    execution_mode = str(payload.get("execution_mode") or "").strip()
    items = group.get("items") if isinstance(group.get("items"), list) else []
    action_types = {
        str((item.get("payload") if isinstance(item, Mapping) and isinstance(item.get("payload"), Mapping) else {}).get("action_type") or "")
        for item in items
        if isinstance(item, Mapping)
    }
    canonical_actions = {
        str(execution_dag_action_capability(action_type).get("canonical_action_type") or action_type)
        for action_type in action_types
    }
    if execution_mode == "write_workers":
        return "launch_write_group", "builder", 80.0, "ready DAG write nodes form a compatible ownership wave"
    if canonical_actions.intersection({"review", "audit"}):
        return "launch_review_group", "hardener", 72.0, "ready DAG review nodes can fan out to bounded review workers"
    if execution_mode == "validation":
        return "launch_validation_group", "hardener", 75.0, "ready DAG validation nodes can run as a validation group"
    return "launch_scope_group", "planner", 70.0, "ready DAG scope/decompose nodes can fan out to bounded read-only workers"


def _scope_group_budget_skip(conn, group: Mapping[str, Any], action_kind: str, role: str) -> tuple[list[dict[str, Any]], str]:
    payload = group.get("payload") if isinstance(group.get("payload"), Mapping) else {}
    if action_kind != "launch_scope_group" or str(payload.get("execution_mode") or "") != "read_only":
        return [], ""
    items = group.get("items") if isinstance(group.get("items"), list) else []
    item_count = min(max(1, len([item for item in items if isinstance(item, Mapping)])), 2)
    check = can_start_execution_group(conn, "read_only", item_count=item_count, owner_role=role)
    if bool(check.get("allowed")):
        return [], ""
    reasons = [str(item) for item in check.get("reasons", []) if str(item)]
    reason = "; ".join(reasons) or "read-only scope worker budget is not available"
    blocker = {
        "reason_kind": "read_only_scope_budget_blocked",
        "reason": _brief(reason),
        "budget_check": check,
    }
    return [blocker], f"read-only scope fanout unavailable: {reason}"


def _ready_integration_nodes(dag_model: Mapping[str, Any]) -> list[dict[str, Any]]:
    ready = dag_model.get("ready_nodes") if isinstance(dag_model.get("ready_nodes"), list) else []
    return [
        dict(item)
        for item in ready
        if isinstance(item, Mapping)
        and str(execution_dag_action_capability(item.get("action_type")).get("canonical_action_type") or "") == "integrate"
        and str(item.get("task_id") or "") not in COMPATIBILITY_CONVEYOR_TASK_IDS
    ]


def _integration_node_patch_id(conn, node: Mapping[str, Any]) -> str:
    patch = node.get("patch") if isinstance(node.get("patch"), Mapping) else {}
    metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
    patch_id = str(patch.get("id") or metadata.get("patch_id") or "")
    if patch_id:
        return patch_id
    node_id = str(node.get("node_id") or "")
    if not node_id:
        return ""
    row = conn.execute("SELECT patch_id, metadata_json FROM execution_dag_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if row is None:
        return ""
    patch_id = str(row["patch_id"] or "")
    if patch_id:
        return patch_id
    try:
        row_metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        row_metadata = {}
    return str(row_metadata.get("patch_id") or "") if isinstance(row_metadata, Mapping) else ""


def _ready_integration_nodes_by_patch(conn, ready_integrations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_patch: dict[str, dict[str, Any]] = {}
    for node in ready_integrations:
        patch_id = _integration_node_patch_id(conn, node)
        if patch_id and patch_id not in by_patch:
            by_patch[patch_id] = node
    return by_patch


def _unreconciled_worker_patches(conn, patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unreconciled: list[dict[str, Any]] = []
    for patch in patches:
        patch_id = str(patch.get("patch_id") or "")
        if not patch_id:
            continue
        row = conn.execute(
            """
            SELECT 1
            FROM execution_dag_nodes
            WHERE action_type IN ('integrate', 'integration') AND patch_id = ?
            LIMIT 1
            """,
            (patch_id,),
        ).fetchone()
        if row is None:
            unreconciled.append(patch)
    return unreconciled


def _all_queued_patches_ready_for_integration(conn, patches: list[dict[str, Any]]) -> bool:
    patch_ids = {str(patch.get("patch_id") or "") for patch in patches if str(patch.get("patch_id") or "")}
    if not patch_ids:
        return False
    return patch_ids.issubset(ready_integration_patch_ids_conn(conn))


def _stale_index_records(parallel_dry_run: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    candidates = parallel_dry_run.get("blocked_parallel_candidates") if isinstance(parallel_dry_run.get("blocked_parallel_candidates"), list) else []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        confidence_signals = {
            str(item).strip().lower()
            for item in (candidate.get("confidence_signals") if isinstance(candidate.get("confidence_signals"), list) else [])
            if str(item).strip()
        }
        reason_kind = str(candidate.get("reason_kind") or "").strip().lower()
        reason = str(candidate.get("reason") or "").lower()
        if reason_kind == "stale_symbol" or "stale_symbol" in confidence_signals or ("stale" in reason and "symbol" in reason):
            records.append(dict(candidate))
    why_not = parallel_dry_run.get("why_not_parallel") if isinstance(parallel_dry_run.get("why_not_parallel"), Mapping) else {}
    reason_groups = why_not.get("reason_groups") if isinstance(why_not.get("reason_groups"), list) else []
    for group in reason_groups:
        if not isinstance(group, Mapping) or str(group.get("reason_kind") or "") != "stale_symbol":
            continue
        examples = group.get("examples") if isinstance(group.get("examples"), list) else []
        for example in examples:
            if isinstance(example, Mapping):
                records.append(dict(example))
    return records[:8]


def _node_canonical_action(node: Mapping[str, Any]) -> str:
    action_type = str(node.get("action_type") or "")
    capability = execution_dag_action_capability(action_type)
    return str(capability.get("canonical_action_type") or action_type)


def _is_worker_patch_handoff_node(node: Mapping[str, Any]) -> bool:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
    return str(metadata.get("source") or "") == "worker_patches" or bool(str(node.get("patch_id") or ""))


def _ready_single_action_candidates(dag_model: Mapping[str, Any]) -> list[dict[str, Any]]:
    ready = dag_model.get("ready_nodes") if isinstance(dag_model.get("ready_nodes"), list) else []
    full_nodes = dag_model.get("nodes") if isinstance(dag_model.get("nodes"), list) else []
    full_node_by_id = {
        str(item.get("node_id") or ""): item
        for item in full_nodes
        if isinstance(item, Mapping) and str(item.get("node_id") or "")
    }
    candidates: list[dict[str, Any]] = []
    for node in ready:
        if not isinstance(node, Mapping):
            continue
        dag_node_id = str(node.get("node_id") or "")
        full_node = full_node_by_id.get(dag_node_id) if dag_node_id else None
        node_detail = full_node if isinstance(full_node, Mapping) else node
        action_type = str(node.get("action_type") or "")
        capability = execution_dag_action_capability(action_type)
        canonical_action = _node_canonical_action(node)
        task_id = str(node.get("task_id") or "")
        if not task_id or task_id in COMPATIBILITY_CONVEYOR_TASK_IDS or canonical_action in {"ticket", "blocker", "build", "repair", "integrate", "completion"}:
            continue
        if canonical_action in {"orchestrate", "decompose", "scope", "calibrate"}:
            candidates.append(
                _candidate(
                    action_kind="launch_scope_group",
                    role=str(capability.get("role_family") or "planner"),
                    score=55.0,
                    reason=f"single ready DAG {canonical_action} node is runnable",
                    dag_node_id=dag_node_id,
                    task_id=task_id,
                )
            )
        elif canonical_action in {"review", "audit"}:
            worker_handoff = _is_worker_patch_handoff_node(node_detail)
            candidates.append(
                _candidate(
                    action_kind="launch_review_group",
                    role=str(capability.get("role_family") or "hardener"),
                    score=76.0 if worker_handoff else 58.0,
                    reason=(
                        f"queued worker patch {canonical_action} handoff is runnable"
                        if worker_handoff
                        else f"single ready DAG {canonical_action} node is runnable"
                    ),
                    dag_node_id=dag_node_id,
                    task_id=task_id,
                )
            )
        elif canonical_action == "validate":
            candidates.append(
                _candidate(
                    action_kind="launch_validation_group",
                    role=str(capability.get("role_family") or "hardener"),
                    score=60.0,
                    reason="single ready DAG validation node is runnable",
                    dag_node_id=dag_node_id,
                    task_id=task_id,
                )
            )
    return candidates


def _ticket_action_node_id(dag_model: Mapping[str, Any], *, ticket_id: str, canonical_action: str) -> str:
    nodes = dag_model.get("nodes") if isinstance(dag_model.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        if str(node.get("task_id") or "") != ticket_id:
            continue
        if _node_canonical_action(node) == canonical_action:
            return str(node.get("node_id") or "")
    return ""


def _serial_fallback_trigger_actions(role: str) -> set[str]:
    if role == "builder":
        return {"build", "scope", "decompose"}
    if role == "hardener":
        return {"review", "audit", "validate"}
    return set()


def _selected_ticket_context(target: Path) -> dict[str, Any]:
    try:
        data, _path, _text = ticket_runtime.load_ticket_run(target)
        selection = ticket_runtime.next_ticket_selection(data)
    except Exception:
        return {}
    if str(selection.get("status") or "") != "selected":
        return {}
    ticket = selection.get("ticket") if isinstance(selection.get("ticket"), Mapping) else {}
    ticket_id = str(ticket.get("id") or "").strip()
    if not ticket_id:
        return {}
    action = str(selection.get("action") or "").strip()
    if action in {"implement_pending", "resume_in_progress"}:
        role = "builder"
        reason = "dependency-ready ticket needs serialized builder work"
    elif action == "verify_candidate":
        role = "hardener"
        reason = "candidate_done ticket needs serialized hardener verification"
    else:
        return {}
    return {
        "ticket_id": ticket_id,
        "ticket": dict(ticket),
        "action": action,
        "role": role,
        "reason": reason,
    }


def _serial_ticket_fallback_candidate(
    target: Path,
    dag_model: Mapping[str, Any],
    parallel_dry_run: Mapping[str, Any],
) -> dict[str, Any] | None:
    context = _selected_ticket_context(target)
    ticket_id = str(context.get("ticket_id") or "")
    role = str(context.get("role") or "")
    if not ticket_id or not role:
        return None
    trigger_actions = _serial_fallback_trigger_actions(role)
    if not trigger_actions:
        return None
    ready = dag_model.get("ready_nodes") if isinstance(dag_model.get("ready_nodes"), list) else []
    ready_for_ticket = [
        item
        for item in ready
        if isinstance(item, Mapping)
        and str(item.get("task_id") or "") == ticket_id
        and _node_canonical_action(item) in trigger_actions
    ]
    blocked = (
        parallel_dry_run.get("blocked_parallel_candidates")
        if isinstance(parallel_dry_run.get("blocked_parallel_candidates"), list)
        else []
    )
    blocked_for_ticket = [
        item
        for item in blocked
        if isinstance(item, Mapping)
        and str(item.get("task_id") or "") == ticket_id
        and str(item.get("canonical_action_type") or item.get("action_type") or "") in trigger_actions
    ]
    if not ready_for_ticket and not blocked_for_ticket:
        return None
    action_priority = {"build": 0, "scope": 1, "review": 2, "validate": 3, "audit": 4, "decompose": 5}
    selected_node = (
        sorted(
            ready_for_ticket,
            key=lambda item: (
                action_priority.get(_node_canonical_action(item), 9),
                str(item.get("node_id") or ""),
            ),
        )[0]
        if ready_for_ticket
        else {}
    )
    selected_blocked = blocked_for_ticket[0] if blocked_for_ticket else {}
    reason_kind = str(selected_blocked.get("reason_kind") or "")
    reason = str(context.get("reason") or "dependency-ready ticket needs serialized role work")
    if reason_kind:
        reason = f"{reason}; parallel DAG launch is blocked by {reason_kind}"
    selected_node_id = str(selected_node.get("node_id") or selected_blocked.get("dag_node_id") or "")
    dag_node_id = _ticket_action_node_id(dag_model, ticket_id=ticket_id, canonical_action="build") if role == "builder" else selected_node_id
    candidate = _candidate(
        action_kind="run_serial_role",
        role=role,
        score=68.0 if role == "hardener" else 66.0,
        reason=reason,
        dag_node_id=dag_node_id or selected_node_id,
        task_id=ticket_id,
    )
    ticket = context.get("ticket") if isinstance(context.get("ticket"), Mapping) else {}
    candidate["ticket_action"] = str(context.get("action") or "")
    candidate["ticket_summary"] = str(ticket.get("summary") or "")
    candidate["parallel_block_reason_kind"] = reason_kind
    if selected_node_id and selected_node_id != str(candidate.get("dag_node_id") or ""):
        candidate["trigger_dag_node_id"] = selected_node_id
    return candidate


def _persist_and_return(
    conn,
    *,
    candidates: list[dict[str, Any]],
    selected: dict[str, Any],
    graph_signals_used: Mapping[str, Any],
) -> None:
    for candidate in candidates:
        candidate.setdefault("state", "ready")
    selected["state"] = "selected"
    write_scheduler_decision_conn(
        conn,
        candidates=candidates,
        selected_candidate=selected,
        fallback_used=False,
        graph_signals_used=graph_signals_used,
        lease_conflicts_considered=[],
        legacy_result={},
        generated_at=utc_now(),
    )


def choose_next_graph_aware(
    target: Path,
    state: dict[str, Any],
    legacy_result: tuple[str | None, str, bool] | None = None,
) -> tuple[str | None, str, bool]:
    del legacy_result
    target = target.expanduser().resolve()
    status = automation_status(target)
    if status == "CRITICAL_STOP":
        selected = _idle_candidate("automation status is CRITICAL_STOP", stop=True)
        with closing(connect(database_path_for_target(target))) as conn:
            _persist_and_return(conn, candidates=[selected], selected=selected, graph_signals_used={"scheduler_source": "execution_dag"})
        return None, "automation status is CRITICAL_STOP", True
    if status not in ACTIVE_STATUSES:
        selected = _idle_candidate(f"automation status is {status}; waiting")
        with closing(connect(database_path_for_target(target))) as conn:
            _persist_and_return(conn, candidates=[selected], selected=selected, graph_signals_used={"scheduler_source": "execution_dag"})
        return None, f"automation status is {status}; waiting", False

    ticket_state, ticket_reason = ticket_campaign_terminal(target)
    if ticket_state == "complete":
        selected = _idle_candidate(ticket_reason, stop=True)
        with closing(connect(database_path_for_target(target))) as conn:
            _persist_and_return(conn, candidates=[selected], selected=selected, graph_signals_used={"scheduler_source": "execution_dag"})
        return None, ticket_reason, True

    try:
        with closing(connect(database_path_for_target(target))) as conn:
            capability = refresh_capability_manifest_conn(conn, target)
            codebase_summary = ensure_codebase_graph_conn(conn, target, capability=capability)
            control = ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
            ensure_parallelism_budgets_conn(conn, control)
            dag_summary = materialize_execution_dag_conn(
                conn,
                target,
                state,
                event_id=None,
                event_type="scheduler.execution_dag_refreshed",
            )
            task_summary = refresh_task_graph_conn(conn, target)
            impact_summary = refresh_impact_graph_conn(conn, target)
            expire_stale_leases_conn(conn)
            parallel_dry_run = plan_parallel_execution_groups_conn(conn, target, selected_by="execution_dag_scheduler")
            dag_model = execution_dag_read_model(conn)
            role_manifest_sync = sync_queued_role_manifests_into_worker_patches_conn(
                conn,
                target,
                selected_by="execution_dag_scheduler.role_manifest_sync",
            )
            queued_patches = worker_patches_conn(conn, statuses={"queued"}, limit=20)
            failed_validation_jobs = failed_validation_jobs_requiring_dag_action_conn(
                conn,
                validation_jobs_conn(conn, statuses={"failed"}, limit=20),
            )
            candidates: list[dict[str, Any]] = []

            if failed_validation_jobs:
                candidates.append(
                    _candidate(
                        action_kind="create_repair_nodes",
                        role="builder",
                        score=100.0,
                        reason=f"{len(failed_validation_jobs)} failed validation job(s) require targeted repair DAG nodes",
                    )
                )

            stale_records = _stale_index_records(parallel_dry_run)
            refresh_index_result = (
                create_refresh_index_nodes_for_stale_evidence_conn(
                    conn,
                    target,
                    stale_records,
                    selected_by="execution_dag_scheduler.stale_index",
                )
                if stale_records
                else {"status": "skipped", "nodes": []}
            )
            refresh_nodes = [
                node
                for node in (refresh_index_result.get("nodes") if isinstance(refresh_index_result.get("nodes"), list) else [])
                if isinstance(node, Mapping)
            ]
            if refresh_nodes:
                first_refresh = refresh_nodes[0]
                candidates.append(
                    _candidate(
                        action_kind="refresh_index",
                        role="planner",
                        score=99.0,
                        reason=f"{len(stale_records)} stale scheduler evidence record(s) need a targeted codebase index refresh",
                        dag_node_id=str(first_refresh.get("node_id") or ""),
                        task_id=str(first_refresh.get("task_id") or ""),
                        next_evidence_hints=[
                            {
                                "reason_kind": "stale_symbol",
                                "next_action": "refresh affected codebase index paths, then re-run scheduler readiness",
                                "source": "why_not_parallel",
                            }
                        ],
                    )
                )

            ready_integrations = _ready_integration_nodes(dag_model)
            unreconciled_patches = _unreconciled_worker_patches(conn, queued_patches)
            integration_preflight = worker_patch_integration_preflight_conn(conn, target=target, limit=20)
            ready_patch_ids = ready_integration_patch_ids_conn(conn)
            safe_ready_patch_ids = [
                str(patch_id)
                for patch_id in integration_preflight.get("safe_patch_ids", [])
                if str(patch_id) in ready_patch_ids
            ]
            ready_integration_by_patch = _ready_integration_nodes_by_patch(conn, ready_integrations)
            safe_ready_nodes = [
                ready_integration_by_patch[patch_id]
                for patch_id in safe_ready_patch_ids
                if patch_id in ready_integration_by_patch
            ]
            if queued_patches and safe_ready_nodes:
                first = safe_ready_nodes[0]
                preflight_summary = {
                    "schema_version": 1,
                    "safe_patch_ids": safe_ready_patch_ids,
                    "safe_order": integration_preflight.get("safe_order", [])[:8]
                    if isinstance(integration_preflight.get("safe_order"), list)
                    else [],
                    "likely_conflict_count": int(integration_preflight.get("likely_conflict_count") or 0),
                    "stale_base_count": int(integration_preflight.get("stale_base_count") or 0),
                    "missing_metadata_count": int(integration_preflight.get("missing_metadata_count") or 0),
                }
                candidates.append(
                    _candidate(
                        action_kind="run_serial_integration",
                        role="integrator",
                        score=98.0,
                        reason=f"{len(safe_ready_patch_ids)} queued worker patch(es) passed integration preflight for serialized apply",
                        dag_node_id=str(first.get("node_id") or ""),
                        task_id=str(first.get("task_id") or ""),
                        patch_ids=safe_ready_patch_ids,
                        integration_preflight=preflight_summary,
                    )
                )
            elif unreconciled_patches:
                candidates.append(
                    _candidate(
                        action_kind="reconcile_worker_results",
                        role="integrator",
                        score=96.0,
                        reason=f"{len(unreconciled_patches)} queued worker patch(es) need review/validation/integration DAG handoff nodes",
                    )
                )

            groups = (
                parallel_dry_run.get("proposed_execution_groups")
                if isinstance(parallel_dry_run.get("proposed_execution_groups"), list)
                else []
            )
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                action_kind, role, score, reason = _group_action(group)
                blockers, skipped_reason = _scope_group_budget_skip(conn, group, action_kind, role)
                candidates.append(
                    _candidate(
                        action_kind=action_kind,
                        role=role,
                        score=score,
                        reason=reason,
                        execution_group_id=str(group.get("execution_group_id") or ""),
                        group=group,
                        blockers=blockers,
                        skipped_reason=skipped_reason,
                    )
                )
            candidates.extend(_ready_single_action_candidates(dag_model))
            serial_fallback = _serial_ticket_fallback_candidate(target, dag_model, parallel_dry_run)
            if serial_fallback is not None:
                candidates.append(serial_fallback)

            parallel_summary = (
                parallel_dry_run.get("parallelization_summary")
                if isinstance(parallel_dry_run.get("parallelization_summary"), Mapping)
                else {}
            )
            graph_signals_used = {
                "scheduler_source": "execution_dag",
                "legacy_scheduler_fallback": False,
                "codebase_snapshot_id": str(codebase_summary.get("latest_snapshot_id") or ""),
                "codebase_refresh_mode": str(codebase_summary.get("graph_refresh_mode") or ""),
                "task_snapshot_id": str(task_summary.get("latest_snapshot_id") or ""),
                "impact_snapshot_id": str(impact_summary.get("latest_snapshot_id") or ""),
                "execution_dag_digest": str(dag_summary.get("digest") or ""),
                "execution_dag_ready_count": len(dag_summary.get("ready_nodes") or [])
                if isinstance(dag_summary.get("ready_nodes"), list)
                else 0,
                "parallel_dry_run_group_count": int(parallel_summary.get("group_count") or 0),
                "scheduler_basis": str(parallel_summary.get("scheduler_basis") or "dag_action_capabilities"),
                "role_specialization_telemetry": parallel_summary.get("role_specialization_telemetry") or {},
                "queued_worker_patch_count": len(queued_patches),
                "unreconciled_worker_patch_count": len(unreconciled_patches),
                "worker_patch_integration_preflight": {
                    "safe_count": int(integration_preflight.get("safe_count") or 0),
                    "likely_conflict_count": int(integration_preflight.get("likely_conflict_count") or 0),
                    "missing_metadata_count": int(integration_preflight.get("missing_metadata_count") or 0),
                    "stale_base_count": int(integration_preflight.get("stale_base_count") or 0),
                },
                "role_manifest_sync": role_manifest_sync,
                "failed_validation_job_count": len(failed_validation_jobs),
                "stale_index_record_count": len(stale_records),
                "refresh_index_result": refresh_index_result,
            }
            runnable = [candidate for candidate in candidates if not str(candidate.get("skipped_reason") or "")]
            if runnable:
                selected = max(runnable, key=lambda item: (float(item.get("score") or 0), str(item.get("action_kind") or "")))
                for candidate in candidates:
                    if candidate is selected:
                        continue
                    candidate["state"] = "ready"
                _persist_and_return(conn, candidates=candidates, selected=selected, graph_signals_used=graph_signals_used)
                reason = "; ".join(str(item) for item in selected.get("reasons", [])[:3])
                role = str(selected.get("role") or "")
                return role or None, _brief(reason, limit=500), False

            has_handoff_nodes = any(
                isinstance(node, Mapping)
                and (node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}).get("source") == "worker_patches"
                for node in dag_model.get("nodes", [])
                if isinstance(dag_model.get("nodes"), list)
            )
            idle_reason = (
                "queued worker patch handoff has no runnable DAG node"
                if queued_patches and has_handoff_nodes
                else "no DAG-ready scheduler action is currently runnable"
            )
            selected = _idle_candidate(idle_reason)
            _persist_and_return(conn, candidates=[selected], selected=selected, graph_signals_used=graph_signals_used)
            return None, idle_reason, False
    except Exception as exc:
        selected = _idle_candidate(f"execution DAG scheduler error: {type(exc).__name__}")
        try:
            with closing(connect(database_path_for_target(target))) as conn:
                _persist_and_return(
                    conn,
                    candidates=[selected],
                    selected=selected,
                    graph_signals_used={"scheduler_source": "execution_dag", "error": type(exc).__name__},
                )
        except Exception:
            pass
        return None, f"execution DAG scheduler error: {type(exc).__name__}", False


def choose_next_dag(
    target: Path,
    state: dict[str, Any],
    no_progress_threshold: int = DEFAULT_NO_PROGRESS_THRESHOLD,
) -> tuple[str | None, str, bool]:
    del no_progress_threshold
    return choose_next_graph_aware(target, state, None)
