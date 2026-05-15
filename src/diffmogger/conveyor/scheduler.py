from __future__ import annotations

import re
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from diffmogger.runtime.state_store import (
    IMPACT_CONTEXT_PACK_LIMIT,
    build_context_pack_conn,
    connect,
    database_path_for_target,
    ensure_codebase_graph_conn,
    expire_stale_leases_conn,
    impact_graph_read_model,
    lease_suggestions_for_next_action_conn,
    plan_parallel_execution_groups_conn,
    refresh_capability_manifest_conn,
    refresh_impact_graph_conn,
    refresh_task_graph_conn,
    task_graph_read_model,
    utc_now,
    write_scheduler_decision_conn,
)


GRAPH_NORMAL_ACTIONS = {"normal_builder_work", "legacy_fallback"}


def _brief(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(0, limit - 3)].rstrip() + "..." if len(text) > limit else text


def _legacy_action_kind(role: str | None, reason: str, stop: bool) -> tuple[str, float]:
    lowered = reason.lower()
    if stop:
        return "terminal_stop", 100.0
    if "queued role patch" in lowered or "queued patch" in lowered:
        return "integrate_queued_patch", 98.0
    if "baseline verification ledger" in lowered or "clean-head preflight" in lowered:
        return "baseline_preflight", 96.0
    if "verification_scope=baseline_repair" in lowered or "baseline local-service repair" in lowered:
        return "baseline_repair", 94.0
    if "human message" in lowered:
        return "human_triage", 92.0
    if "bounded campaign is blocked" in lowered or "bounded campaign blocked" in lowered:
        return "ticket_terminal_or_repair", 91.0
    if "candidate_done ticket" in lowered:
        return "candidate_done_validation", 88.0
    if "no-progress" in lowered:
        return "no_progress_recovery", 86.0
    if "duplicate builder deferred" in lowered or "guardrail deferrals" in lowered:
        return "deferred_patch_triage", 85.0
    if role == "builder":
        return "normal_builder_work", 45.0
    if role in {"planner", "hardener", "integrator"}:
        return "normal_role_rotation", 50.0
    return "legacy_fallback", 40.0


def _legacy_candidate(role: str | None, reason: str, stop: bool) -> dict[str, Any]:
    action_kind, score = _legacy_action_kind(role, reason, stop)
    return {
        "role": role or "",
        "task_id": "",
        "action_kind": action_kind,
        "score": score,
        "reasons": [_brief(reason)],
        "blockers": [],
        "required_leases": [],
        "suggested_leases": [],
        "acquired_leases": [],
        "context_pack_preview": {},
        "skipped_reason": "",
        "stop": stop,
        "source": "legacy_choose_next",
    }


def _validation_debt(conn) -> int:
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM validation_receipts
        GROUP BY status
        """
    ).fetchall()
    debt_statuses = {"failed", "failing", "error", "blocked", "not_recorded", "stale"}
    return sum(int(row["count"] or 0) for row in rows if str(row["status"] or "").lower() in debt_statuses)


def _candidate_conflicts(required_leases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for lease in required_leases:
        raw = lease.get("conflicts") if isinstance(lease.get("conflicts"), list) else []
        conflicts.extend(item for item in raw if isinstance(item, dict))
    return conflicts


def _lease_conflicts_considered(candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    considered: list[dict[str, Any]] = []
    for candidate in candidates:
        required = candidate.get("required_leases") if isinstance(candidate.get("required_leases"), list) else []
        for lease in required:
            if not isinstance(lease, Mapping):
                continue
            conflicts = lease.get("conflicts") if isinstance(lease.get("conflicts"), list) else []
            for conflict in conflicts[:3]:
                if not isinstance(conflict, Mapping):
                    continue
                considered.append(
                    {
                        "candidate_task_id": str(candidate.get("public_task_id") or candidate.get("task_id") or ""),
                        "candidate_action_kind": str(candidate.get("action_kind") or ""),
                        "scope_kind": str(lease.get("scope_kind") or ""),
                        "scope_node_id": str(lease.get("scope_node_id") or ""),
                        "path": str(lease.get("path") or ""),
                        "reason": _brief(conflict.get("reason") or lease.get("reason"), limit=180),
                    }
                )
    return considered[:12]


def _lease_summary(lease: Mapping[str, Any]) -> dict[str, Any]:
    conflicts = lease.get("conflicts") if isinstance(lease.get("conflicts"), list) else []
    return {
        "scope_kind": str(lease.get("scope_kind") or ""),
        "scope_node_id": str(lease.get("scope_node_id") or ""),
        "path": str(lease.get("path") or ""),
        "name": str(lease.get("name") or ""),
        "confidence": float(lease.get("confidence") or 0),
        "reason": _brief(lease.get("reason")),
        "recommended": bool(lease.get("recommended")),
        "caution": bool(lease.get("caution")),
        "conflict_count": len(conflicts),
        "conflicts": conflicts[:3],
    }


def _context_pack_preview(pack: Mapping[str, Any]) -> dict[str, Any]:
    items = pack.get("items") if isinstance(pack.get("items"), list) else []
    return {
        "impact_snapshot_id": str(pack.get("impact_snapshot_id") or ""),
        "item_count": int(pack.get("item_count") or len(items)),
        "max_items": int(pack.get("max_items") or IMPACT_CONTEXT_PACK_LIMIT),
        "stale_context_warning": str(pack.get("stale_context_warning") or ""),
        "items": [
            {
                "category": str(item.get("category") or ""),
                "path": str(item.get("path") or ""),
                "name": str(item.get("name") or ""),
                "confidence": float(item.get("confidence") or 0),
                "reason": _brief(item.get("reason"), limit=140),
                "is_stale": bool(item.get("is_stale")),
            }
            for item in items[:6]
            if isinstance(item, dict)
        ],
    }


def _graph_ticket_candidates(conn, target: Path) -> list[dict[str, Any]]:
    ready_model = task_graph_read_model(conn)
    ready_tasks = [
        item
        for item in ready_model.get("ready_task_nodes", [])
        if isinstance(item, dict) and str(item.get("kind") or "") == "ticket"
    ]
    validation_debt = _validation_debt(conn)
    candidates: list[dict[str, Any]] = []
    for task in ready_tasks[:12]:
        public_id = str(task.get("id") or "")
        task_node_id = str(task.get("node_id") or "")
        pack = build_context_pack_conn(
            conn,
            target,
            ticket_id=public_id,
            task_node_id=task_node_id,
            max_items=IMPACT_CONTEXT_PACK_LIMIT,
        )
        items = pack.get("items") if isinstance(pack.get("items"), list) else []
        confidence = max((float(item.get("confidence") or 0) for item in items if isinstance(item, dict)), default=0.0)
        required_leases = [
            _lease_summary(item)
            for item in lease_suggestions_for_next_action_conn(
                conn,
                target,
                ticket_id=public_id,
                task_node_id=task_node_id,
            )
            if isinstance(item, dict) and bool(item.get("recommended"))
        ]
        conflicts = _candidate_conflicts(required_leases)
        stale_warning = str(pack.get("stale_context_warning") or "")
        score = 58.0 + confidence * 24.0 + min(len(items), 6) * 1.5
        if any(item.get("category") == "commands" for item in items if isinstance(item, dict)):
            score += 4.0
        if validation_debt:
            score -= min(8.0, validation_debt * 1.5)
        if stale_warning:
            score -= 8.0
        reasons = [
            f"task graph marks ticket {public_id or task_node_id} ready",
            f"context pack has {len(items)} item(s)",
        ]
        if confidence:
            reasons.append(f"top impact confidence {confidence:.2f}")
        if required_leases:
            reasons.append(f"{len(required_leases)} recommended lease scope(s)")
        else:
            reasons.append("unknown impact surface; no automatic repo lock")
            score -= 6.0
        blockers: list[dict[str, Any]] = []
        skipped_reason = ""
        if conflicts:
            skipped_reason = f"resource lease conflict on {len(conflicts)} scope(s)"
            blockers.append({"kind": "resource_lease_conflict", "count": len(conflicts)})
            score -= 40.0
        if stale_warning:
            blockers.append({"kind": "stale_context_warning", "detail": stale_warning})
        candidates.append(
            {
                "role": "builder",
                "task_id": task_node_id or public_id,
                "public_task_id": public_id,
                "action_kind": "implement_ready_ticket",
                "score": round(score, 4),
                "reasons": reasons,
                "blockers": blockers,
                "required_leases": required_leases,
                "suggested_leases": required_leases,
                "acquired_leases": [],
                "context_pack_preview": _context_pack_preview(pack),
                "skipped_reason": skipped_reason,
                "stop": False,
                "source": "graph_scheduler",
            }
        )
    return candidates


def _persist_and_return(
    conn,
    *,
    candidates: list[dict[str, Any]],
    selected: dict[str, Any],
    fallback_used: bool,
    graph_signals_used: Mapping[str, Any] | None = None,
    legacy_result: Mapping[str, Any] | None = None,
) -> None:
    for candidate in candidates:
        candidate.setdefault("state", "ready")
    selected["state"] = "selected"
    write_scheduler_decision_conn(
        conn,
        candidates=candidates,
        selected_candidate=selected,
        fallback_used=fallback_used,
        graph_signals_used=graph_signals_used or {},
        lease_conflicts_considered=_lease_conflicts_considered(candidates),
        legacy_result=legacy_result or {},
        generated_at=utc_now(),
    )


def _legacy_result_payload(role: str | None, reason: str, stop: bool, legacy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "role": role or "",
        "reason": _brief(reason, limit=500),
        "stop": bool(stop),
        "action_kind": str(legacy.get("action_kind") or ""),
    }


def choose_next_graph_aware(
    target: Path,
    state: dict[str, Any],
    legacy_result: tuple[str | None, str, bool],
) -> tuple[str | None, str, bool]:
    legacy_role, legacy_reason, legacy_stop = legacy_result
    legacy = _legacy_candidate(legacy_role, legacy_reason, legacy_stop)
    legacy_payload = _legacy_result_payload(legacy_role, legacy_reason, legacy_stop, legacy)
    legacy_action = str(legacy.get("action_kind") or "")
    graph_can_select = legacy_role == "builder" and legacy_action in GRAPH_NORMAL_ACTIONS and not legacy_stop
    target = target.expanduser().resolve()
    try:
        with closing(connect(database_path_for_target(target))) as conn:
            capability = refresh_capability_manifest_conn(conn, target)
            codebase_summary = ensure_codebase_graph_conn(conn, target, capability=capability)
            task_summary = refresh_task_graph_conn(conn, target)
            impact_summary = refresh_impact_graph_conn(conn, target)
            expire_stale_leases_conn(conn)
            impact_model = impact_graph_read_model(conn, target)
            parallel_dry_run = plan_parallel_execution_groups_conn(conn, target, selected_by="graph_scheduler")

            graph_candidates = _graph_ticket_candidates(conn, target)
            graph_signals_used = {
                "legacy_action_kind": legacy_action,
                "graph_can_select": graph_can_select,
                "codebase_snapshot_id": str(codebase_summary.get("latest_snapshot_id") or ""),
                "codebase_refresh_mode": str(codebase_summary.get("graph_refresh_mode") or ""),
                "task_snapshot_id": str(task_summary.get("latest_snapshot_id") or ""),
                "ready_task_count": int(task_summary.get("ready_task_count") or 0),
                "impact_snapshot_id": str(impact_summary.get("latest_snapshot_id") or ""),
                "graph_candidate_count": len(graph_candidates),
                "stale_context_warning": str(impact_model.get("stale_context_warning") or ""),
                "parallel_dry_run_group_count": int(
                    (parallel_dry_run.get("parallelization_summary") or {}).get("group_count") or 0
                )
                if isinstance(parallel_dry_run.get("parallelization_summary"), Mapping)
                else 0,
                "parallel_dry_run_blocked_count": int(
                    (parallel_dry_run.get("parallelization_summary") or {}).get("blocked_candidate_count") or 0
                )
                if isinstance(parallel_dry_run.get("parallelization_summary"), Mapping)
                else 0,
            }
            candidates: list[dict[str, Any]] = []
            selected = dict(legacy)
            fallback_used = False
            if legacy_action not in GRAPH_NORMAL_ACTIONS or legacy_stop or legacy_role != "builder":
                selected["score"] = max(float(selected.get("score") or 0), 90.0)
                candidates.append(selected)
                for candidate in graph_candidates:
                    candidate["state"] = "skipped"
                    candidate["skipped_reason"] = "existing scheduler priority outranks graph-normal work"
                    candidates.append(candidate)
                _persist_and_return(
                    conn,
                    candidates=candidates,
                    selected=selected,
                    fallback_used=False,
                    graph_signals_used=graph_signals_used,
                    legacy_result=legacy_payload,
                )
                return legacy_result

            ready_graph = [item for item in graph_candidates if not str(item.get("skipped_reason") or "")]
            skipped_graph = [item for item in graph_candidates if str(item.get("skipped_reason") or "")]
            if ready_graph and graph_can_select:
                selected = max(ready_graph, key=lambda item: float(item.get("score") or 0))
                reason = (
                    f"{legacy_reason}; graph-aware scheduler selected ready ticket "
                    f"{selected.get('public_task_id') or selected.get('task_id')} "
                    f"(score={float(selected.get('score') or 0):.1f}); "
                    f"{'; '.join(str(item) for item in selected.get('reasons', [])[:3])}"
                )
                candidates.append(selected)
                for candidate in ready_graph:
                    if candidate is selected:
                        continue
                    candidate["state"] = "ready"
                    candidates.append(candidate)
                for candidate in skipped_graph:
                    candidate["state"] = "skipped"
                    candidates.append(candidate)
                _persist_and_return(
                    conn,
                    candidates=candidates,
                    selected=selected,
                    fallback_used=False,
                    graph_signals_used=graph_signals_used,
                    legacy_result=legacy_payload,
                )
                return selected["role"], _brief(reason, limit=500), False

            fallback_used = True
            selected = dict(legacy)
            selected["state"] = "selected"
            selected["reasons"] = [*selected.get("reasons", []), "graph-aware scheduler had no safe ready candidate"]
            candidates.append(selected)
            for candidate in skipped_graph:
                candidate["state"] = "skipped"
                candidates.append(candidate)
            _persist_and_return(
                conn,
                candidates=candidates,
                selected=selected,
                fallback_used=fallback_used,
                graph_signals_used=graph_signals_used,
                legacy_result=legacy_payload,
            )
            return legacy_result
    except Exception as exc:
        try:
            with closing(connect(database_path_for_target(target))) as conn:
                fallback = dict(legacy)
                fallback["state"] = "selected"
                fallback["reasons"] = [*fallback.get("reasons", []), f"graph-aware scheduler fallback: {type(exc).__name__}"]
                write_scheduler_decision_conn(
                    conn,
                    candidates=[fallback],
                    selected_candidate=fallback,
                    fallback_used=True,
                    graph_signals_used={"error": type(exc).__name__, "legacy_action_kind": legacy_action},
                    lease_conflicts_considered=[],
                    legacy_result=legacy_payload,
                    generated_at=utc_now(),
                )
        except Exception:
            pass
        return legacy_result
