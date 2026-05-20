#!/usr/bin/env python3
"""Preflight readiness report for the first long DAG parallelization run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from diffmogger.runtime.state_store import (
    PARALLEL_SCOPING_READ_CONFIDENCE_THRESHOLD,
    PARALLEL_WRITE_TOUCH_CONFIDENCE_THRESHOLD,
    state_snapshot,
)


PREFLIGHT_REPORT_VERSION = 1
PREFLIGHT_REQUIRED_PHASES = (
    "indexing",
    "resolution",
    "impact_scoring",
    "scheduling",
    "dashboard_rendering",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _budget_by_scope(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    budgets: dict[str, dict[str, Any]] = {}
    for item in _list(snapshot.get("parallelism_budgets")):
        if not isinstance(item, Mapping):
            continue
        scope = _text(item.get("scope"))
        if scope:
            budgets[scope] = dict(item)
    return budgets


def _commands(capability: Mapping[str, Any]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for item in _list(capability.get("commands")):
        if isinstance(item, Mapping):
            commands.append(dict(item))
    return commands


def _extractor_health_by_language(file_index: Iterable[Any]) -> dict[str, dict[str, Any]]:
    health: dict[str, dict[str, Any]] = {}
    for item in file_index:
        if not isinstance(item, Mapping):
            continue
        language = _text(item.get("language")) or "unknown"
        bucket = health.setdefault(
            language,
            {
                "file_count": 0,
                "ok_count": 0,
                "failed_count": 0,
                "stale_count": 0,
                "symbol_count": 0,
                "parser_confidence_total": 0.0,
                "parser_confidence_count": 0,
                "failure_reasons": [],
            },
        )
        parse_status = _text(item.get("parse_status")).lower()
        failure_reason = _text(item.get("failure_reason"))
        parser_confidence = _number(item.get("parser_confidence"), 0.0)
        bucket["file_count"] += 1
        bucket["symbol_count"] += _int(item.get("symbol_count"), 0)
        if bool(item.get("is_stale")):
            bucket["stale_count"] += 1
        if parse_status in {"ok", "empty", "not_applicable", "skipped"} and not failure_reason:
            bucket["ok_count"] += 1
        else:
            bucket["failed_count"] += 1
            if failure_reason:
                reasons = bucket["failure_reasons"]
                if isinstance(reasons, list) and failure_reason not in reasons:
                    reasons.append(failure_reason)
        if parser_confidence > 0:
            bucket["parser_confidence_total"] += parser_confidence
            bucket["parser_confidence_count"] += 1
    for bucket in health.values():
        confidence_count = _int(bucket.pop("parser_confidence_count", 0), 0)
        confidence_total = _number(bucket.pop("parser_confidence_total", 0.0), 0.0)
        bucket["average_parser_confidence"] = round(confidence_total / confidence_count, 3) if confidence_count else 0.0
    return health


def _semantic_resolution_coverage(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    graph_summary = _mapping(snapshot.get("codebase_graph_summary"))
    latest_graph = _mapping(graph_summary.get("latest_graph_snapshot"))
    node_counts = _mapping(latest_graph.get("node_counts"))
    edge_counts = _mapping(latest_graph.get("edge_counts"))
    code_intel = _mapping(snapshot.get("code_intelligence"))
    fact_counts = _mapping(code_intel.get("fact_counts"))
    provider_availability = _mapping(code_intel.get("provider_availability"))
    symbol_count = _int(node_counts.get("symbol"), 0)
    ownership_edges = _int(edge_counts.get("owns_symbol"), 0)
    import_edges = sum(
        _int(edge_counts.get(kind), 0)
        for kind in ("imports", "imports_module", "imports_symbol", "depends_on_import")
    )
    semantic_edge_count = sum(
        _int(edge_counts.get(kind), 0)
        for kind in (
            "owns_symbol",
            "defines_module",
            "imports",
            "imports_module",
            "imports_symbol",
            "references",
            "interface_match",
            "cross_language_interface",
        )
    )
    lsp_fact_count = _int(code_intel.get("fact_count"), 0)
    coverage_ratio = round(min(1.0, semantic_edge_count / max(symbol_count, 1)), 3) if symbol_count else 0.0
    return {
        "symbol_nodes": symbol_count,
        "ownership_edges": ownership_edges,
        "import_edges": import_edges,
        "semantic_edges": semantic_edge_count,
        "semantic_edge_per_symbol": coverage_ratio,
        "lsp_fact_count": lsp_fact_count,
        "lsp_fact_counts": dict(fact_counts),
        "lsp_available_count": _int(provider_availability.get("available_count"), 0),
        "lsp_missing_count": _int(provider_availability.get("missing_count"), 0),
        "lsp_policy": dict(_mapping(provider_availability.get("policy"))),
        "fallback": _text(code_intel.get("fallback")),
    }


def _signal_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(item.get("payload"))
    touches = _list(payload.get("likely_touches"))
    signal_kinds: set[str] = set()
    sources: set[str] = set()
    paths: set[str] = set()
    symbols: set[str] = set()
    confidence = 0.0
    reasons: list[str] = []
    for touch in touches:
        if not isinstance(touch, Mapping):
            continue
        signal = _text(touch.get("signal_kind"))
        source = _text(touch.get("source"))
        path = _text(touch.get("path"))
        symbol = _text(touch.get("qualified_name") or touch.get("symbol_name"))
        reason = _text(touch.get("reason"))
        if signal:
            signal_kinds.add(signal)
        if source:
            sources.add(source)
        if path:
            paths.add(path)
        if symbol:
            symbols.add(symbol)
        if reason and reason not in reasons:
            reasons.append(reason)
        confidence = max(confidence, _number(touch.get("confidence"), 0.0))
    context_pack = _mapping(payload.get("context_pack_preview"))
    for context_item in _list(context_pack.get("items")):
        if not isinstance(context_item, Mapping):
            continue
        signal = _text(context_item.get("signal_kind"))
        source = _text(context_item.get("source"))
        path = _text(context_item.get("path"))
        reason = _text(context_item.get("reason"))
        if signal:
            signal_kinds.add(signal)
        if source:
            sources.add(source)
        if path:
            paths.add(path)
        if reason and reason not in reasons:
            reasons.append(reason)
        confidence = max(confidence, _number(context_item.get("confidence"), 0.0))
    return {
        "confidence": round(confidence, 3),
        "signal_kinds": sorted(signal_kinds),
        "sources": sorted(sources),
        "paths": sorted(paths),
        "symbols": sorted(symbols),
        "reasons": reasons[:5],
    }


def _expected_parallelization(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for group in _list(snapshot.get("proposed_execution_groups")):
        if not isinstance(group, Mapping):
            continue
        items = [item for item in _list(group.get("items")) if isinstance(item, Mapping)]
        payload = _mapping(group.get("payload"))
        group_items: list[dict[str, Any]] = []
        for item in items:
            item_payload = _mapping(item.get("payload"))
            signals = _signal_summary(item)
            required_leases = [dict(lease) for lease in _list(item.get("required_leases")) if isinstance(lease, Mapping)]
            group_items.append(
                {
                    "task_id": _text(item.get("task_id")),
                    "dag_node_id": _text(item.get("dag_node_id") or item.get("graph_task_node_id") or item_payload.get("dag_node_id")),
                    "action_type": _text(item.get("canonical_action_type") or item.get("action_type") or item_payload.get("canonical_action_type")),
                    "owner_role": _text(item.get("owner_role") or item_payload.get("owner_role")),
                    "confidence": signals["confidence"],
                    "paths": signals["paths"],
                    "symbols": signals["symbols"],
                    "signals": signals["signal_kinds"],
                    "required_leases": required_leases,
                    "why": _text(item.get("reason")) or "ready DAG node has a compatible ownership surface",
                }
            )
        execution_mode = _text(payload.get("execution_mode"))
        if not execution_mode and group_items:
            execution_mode = "write_workers" if any(item.get("action_type") == "build" for item in group_items) else "read_only_workers"
        groups.append(
            {
                "execution_group_id": _text(group.get("execution_group_id")),
                "execution_mode": execution_mode,
                "item_count": len(group_items),
                "same_wave_parallel": len(group_items) > 1,
                "reason": _text(group.get("reason")) or "ready DAG nodes have compatible dependencies and ownership surfaces",
                "why": _text(payload.get("why_together"))
                or _text(group.get("reason"))
                or "DAG dependencies are satisfied and resource leases do not overlap.",
                "items": group_items,
            }
        )
    return groups


def _blocked_candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": _text(candidate.get("task_id")),
        "dag_node_id": _text(candidate.get("dag_node_id") or candidate.get("graph_task_node_id")),
        "action_type": _text(candidate.get("canonical_action_type") or candidate.get("action_type")),
        "owner_role": _text(candidate.get("owner_role")),
        "reason_kind": _text(candidate.get("reason_kind")),
        "reason": _text(candidate.get("reason") or candidate.get("blocked_reason")),
        "missing_confidence_signal": _text(candidate.get("missing_confidence_signal")),
        "confidence_signals": list(_list(candidate.get("confidence_signals"))),
        "lease_conflicts": list(_list(candidate.get("lease_conflicts"))),
    }


def _serialized_tasks(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(item: Mapping[str, Any], reason_kind: str, reason: str) -> None:
        dag_node_id = _text(item.get("dag_node_id") or item.get("node_id") or item.get("id") or item.get("graph_task_node_id"))
        task_id = _text(item.get("task_id") or item.get("ticket_id"))
        key = (task_id, dag_node_id, reason_kind)
        if key in seen:
            return
        seen.add(key)
        serialized.append(
            {
                "task_id": task_id,
                "dag_node_id": dag_node_id,
                "action_type": _text(item.get("canonical_action_type") or item.get("action_type")),
                "owner_role": _text(item.get("owner_role")),
                "status": _text(item.get("status")),
                "reason_kind": reason_kind,
                "reason": reason,
            }
        )

    for candidate in _list(snapshot.get("blocked_parallel_candidates")):
        if not isinstance(candidate, Mapping):
            continue
        summary = _blocked_candidate_summary(candidate)
        key = (summary["task_id"], summary["dag_node_id"], summary["reason_kind"])
        if key not in seen:
            seen.add(key)
            serialized.append(summary)

    execution_dag = _mapping(snapshot.get("execution_dag"))
    for node in _list(execution_dag.get("nodes")):
        if not isinstance(node, Mapping):
            continue
        status = _text(node.get("status")).lower()
        action_type = _text(node.get("canonical_action_type") or node.get("action_type")).lower()
        if action_type == "integrate" and status not in {"completed", "done", "skipped"}:
            add(node, "integration_serialized", "Integration nodes remain serialized by policy.")
        if status in {"blocked", "blocked_on_user", "blocked_on_environment"}:
            add(node, "blocked_node_not_parallelized", "Human or environment annotations route through serial unblocker work, not parallel workers.")
    return serialized


def _scheduler_config(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    capability = _mapping(snapshot.get("capability_manifest"))
    parallelization = _mapping(snapshot.get("parallelization_summary"))
    policy = _mapping(parallelization.get("policy"))
    budgets = _budget_by_scope(snapshot)
    worker_setup = _mapping(_mapping(snapshot.get("automation_control")).get("worker"))
    return {
        "planner_source": _text(parallelization.get("planner_source")),
        "scheduler_basis": _text(parallelization.get("scheduler_basis")),
        "parallel_execution_mode": _text(worker_setup.get("parallel_execution_mode"))
        or _text(_mapping(capability.get("setup")).get("parallel_execution_mode"))
        or "aggressive",
        "policy": dict(policy),
        "confidence_thresholds": {
            "parallel_write_min_confidence": _number(
                policy.get("direct_write_confidence_threshold"),
                PARALLEL_WRITE_TOUCH_CONFIDENCE_THRESHOLD,
            ),
            "parallel_write_direct_confidence": _number(
                policy.get("direct_write_confidence_threshold"),
                PARALLEL_WRITE_TOUCH_CONFIDENCE_THRESHOLD,
            ),
            "parallel_scope_min_confidence": _number(
                policy.get("scoping_read_only_confidence_threshold"),
                PARALLEL_SCOPING_READ_CONFIDENCE_THRESHOLD,
            ),
        },
        "budgets": budgets,
        "active_parallel_counts": dict(_mapping(snapshot.get("active_parallel_counts"))),
        "budget_exhaustion_reasons": list(_list(snapshot.get("budget_exhaustion_reasons"))),
    }


def _validation_readiness(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    commands = _commands(_mapping(snapshot.get("capability_manifest")))
    validation_commands = [
        command
        for command in commands
        if _text(command.get("kind")).lower() in {"test", "typecheck", "lint", "build", "validation"}
    ]
    summary = _mapping(snapshot.get("validation_job_summary"))
    return {
        "command_count": len(validation_commands),
        "commands": validation_commands,
        "job_summary": dict(summary),
        "parallel_validation_available": bool(snapshot.get("parallel_validation_available")),
        "budget_status": dict(_mapping(snapshot.get("validation_budget_status"))),
    }


def _dashboard_readiness(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    execution_dag = _mapping(snapshot.get("execution_dag"))
    automation_activity = _mapping(snapshot.get("automation_activity"))
    projection = _mapping(_mapping(snapshot.get("projections")).get("execution_dag"))
    node_count = _int(execution_dag.get("node_count"), 0)
    activity_node_count = _int(_mapping(automation_activity.get("summary")).get("node_count"), 0)
    return {
        "available": node_count > 0 and activity_node_count > 0,
        "activity_model": "automation_activity" if activity_node_count > 0 else "missing",
        "node_count": node_count,
        "activity_node_count": activity_node_count,
        "edge_count": _int(execution_dag.get("edge_count"), 0),
        "projection_exists": bool(projection.get("exists")),
        "projection_updated_at": _text(projection.get("updated_at")),
    }


def _telemetry_readiness(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    performance = _mapping(snapshot.get("runtime_performance") or snapshot.get("performance"))
    latest_by_phase = _mapping(performance.get("latest_by_phase"))
    missing_phases = [phase for phase in PREFLIGHT_REQUIRED_PHASES if phase not in latest_by_phase]
    return {
        "available": not missing_phases,
        "required_phases": list(PREFLIGHT_REQUIRED_PHASES),
        "missing_phases": missing_phases,
        "latest_by_phase": {phase: dict(_mapping(latest_by_phase.get(phase))) for phase in latest_by_phase},
        "slow_phases": [dict(item) for item in _list(snapshot.get("slow_phase_warnings")) if isinstance(item, Mapping)],
        "compaction": dict(_mapping(snapshot.get("runtime_telemetry_compaction"))),
    }


def _append_risk(risks: list[dict[str, Any]], severity: str, area: str, reason: str, evidence: Mapping[str, Any] | None = None) -> None:
    risks.append(
        {
            "severity": severity,
            "area": area,
            "reason": reason,
            "evidence": dict(evidence or {}),
        }
    )


def _risk_areas(
    snapshot: Mapping[str, Any],
    *,
    dashboard: Mapping[str, Any],
    validation: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    scheduler: Mapping[str, Any],
    expected_parallelization: list[Mapping[str, Any]],
    serialized: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    graph_summary = _mapping(snapshot.get("codebase_graph_summary"))
    latest_graph = _mapping(graph_summary.get("latest_graph_snapshot"))
    storage = _mapping(latest_graph.get("snapshot_storage"))
    stale_file_count = _int(snapshot.get("stale_file_count") or graph_summary.get("stale_file_count"), 0)
    failed_file_count = _int(snapshot.get("failed_file_count") or graph_summary.get("failed_file_count"), 0)
    conflicting_leases = _list(snapshot.get("conflicting_leases"))
    policy = _mapping(scheduler.get("policy"))
    budgets = _mapping(scheduler.get("budgets"))
    write_budget = _mapping(budgets.get("write_workers"))

    if not dashboard.get("available"):
        _append_risk(
            risks,
            "block",
            "dashboard_dag",
            "Dashboard run data does not expose execution_dag as the primary progress model.",
            dashboard,
        )
    if _text(scheduler.get("planner_source")) != "execution_dag" or _text(scheduler.get("scheduler_basis")) != "dag_action_capabilities":
        _append_risk(
            risks,
            "block",
            "scheduler_basis",
            "Scheduler dry run is not based on execution DAG action capabilities.",
            {
                "planner_source": scheduler.get("planner_source"),
                "scheduler_basis": scheduler.get("scheduler_basis"),
            },
        )
    if validation.get("command_count", 0) <= 0:
        _append_risk(
            risks,
            "block",
            "validation_commands",
            "No validation, test, typecheck, lint, or build commands were detected before the long run.",
            validation,
        )
    if conflicting_leases:
        _append_risk(
            risks,
            "block",
            "lease_conflicts",
            "Active resource lease conflicts would make the first parallel wave unsafe.",
            {"conflicting_leases": conflicting_leases[:8]},
        )
    has_write_group = any(_text(group.get("execution_mode")) == "write_workers" for group in expected_parallelization)
    if has_write_group and (not bool(write_budget.get("enabled")) or _int(write_budget.get("max_concurrent"), 0) <= 0):
        _append_risk(
            risks,
            "block",
            "write_worker_budget",
            "Ready write nodes exist but the write-worker budget is disabled.",
            {"write_budget": dict(write_budget)},
        )
    if stale_file_count:
        _append_risk(
            risks,
            "warn",
            "symbol_index_freshness",
            "The codebase graph has stale file facts; symbol evidence may be downgraded.",
            {"stale_file_count": stale_file_count},
        )
    if failed_file_count:
        _append_risk(
            risks,
            "warn",
            "extractor_health",
            "Some files failed symbol extraction and will fall back to file-level facts.",
            {"failed_file_count": failed_file_count},
        )
    if bool(latest_graph.get("storage_truncated")) or bool(storage.get("storage_truncated")):
        _append_risk(
            risks,
            "warn",
            "snapshot_size",
            "The latest graph snapshot was storage-bounded; dashboard and context previews may omit bulky details.",
            {"snapshot_storage": dict(storage)},
        )
    if not telemetry.get("available"):
        _append_risk(
            risks,
            "warn",
            "telemetry_collection",
            "Runtime phase telemetry is incomplete for the phases needed to judge the 24h run.",
            {"missing_phases": telemetry.get("missing_phases", [])},
        )
    if telemetry.get("slow_phases"):
        _append_risk(
            risks,
            "warn",
            "slow_phases",
            "One or more runtime phases already crossed the slow-phase threshold.",
            {"slow_phases": list(telemetry.get("slow_phases", []))[:8]},
        )
    if not expected_parallelization and not serialized:
        _append_risk(
            risks,
            "warn",
            "no_ready_dag_work",
            "No ready parallel groups or serialized DAG reasons were found for the preflight snapshot.",
            {},
        )
    if _number(policy.get("direct_write_confidence_threshold"), PARALLEL_WRITE_TOUCH_CONFIDENCE_THRESHOLD) < PARALLEL_WRITE_TOUCH_CONFIDENCE_THRESHOLD:
        _append_risk(
            risks,
            "warn",
            "confidence_thresholds",
            "Configured direct-write threshold is below the starter-kit default.",
            {"policy": dict(policy)},
        )
    return risks


def _overall_status(risks: Iterable[Mapping[str, Any]]) -> str:
    severities = {_text(item.get("severity")) for item in risks}
    if "block" in severities:
        return "block"
    if "warn" in severities:
        return "warn"
    return "ready"


def build_parallelization_preflight_report(target: Path, *, event_limit: int = 20) -> dict[str, Any]:
    """Return a bounded readiness report for the first long DAG parallelization run."""

    target = target.expanduser().resolve()
    snapshot = state_snapshot(target, event_limit=event_limit)
    graph_summary = _mapping(snapshot.get("codebase_graph_summary"))
    file_index = list(_list(snapshot.get("file_index") or graph_summary.get("file_index")))
    scheduler = _scheduler_config(snapshot)
    validation = _validation_readiness(snapshot)
    dashboard = _dashboard_readiness(snapshot)
    telemetry = _telemetry_readiness(snapshot)
    expected_parallelization = _expected_parallelization(snapshot)
    serialized = _serialized_tasks(snapshot)
    risks = _risk_areas(
        snapshot,
        dashboard=dashboard,
        validation=validation,
        telemetry=telemetry,
        scheduler=scheduler,
        expected_parallelization=expected_parallelization,
        serialized=serialized,
    )
    return {
        "report": "parallelization_preflight_v1",
        "schema_version": PREFLIGHT_REPORT_VERSION,
        "target": str(target),
        "status": _overall_status(risks),
        "checks": {
            "symbol_index_freshness": {
                "indexed_file_count": _int(snapshot.get("indexed_file_count") or graph_summary.get("indexed_file_count"), 0),
                "file_index_count": len(file_index),
                "stale_file_count": _int(snapshot.get("stale_file_count") or graph_summary.get("stale_file_count"), 0),
                "failed_file_count": _int(snapshot.get("failed_file_count") or graph_summary.get("failed_file_count"), 0),
                "graph_refresh_mode": _text(snapshot.get("graph_refresh_mode") or graph_summary.get("graph_refresh_mode")),
                "graph_refresh_reason": _text(snapshot.get("graph_refresh_reason") or graph_summary.get("graph_refresh_reason")),
            },
            "extractor_health_by_language": _extractor_health_by_language(file_index),
            "semantic_resolution_coverage": _semantic_resolution_coverage(snapshot),
            "scheduler_config": scheduler,
            "lease_conflicts": {
                "active_leases": list(_list(snapshot.get("active_leases"))),
                "conflicting_leases": list(_list(snapshot.get("conflicting_leases"))),
                "lease_suggestions": list(_list(snapshot.get("lease_suggestions_for_next_action"))),
            },
            "validation_commands": validation,
            "dashboard_dag": dashboard,
            "telemetry_collection": telemetry,
        },
        "expected_parallelization": expected_parallelization,
        "serialized_tasks": serialized,
        "risk_areas": risks,
    }


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        f"Parallelization preflight: {report.get('status', 'unknown')}",
        f"Target: {report.get('target', '')}",
        "",
    ]
    checks = _mapping(report.get("checks"))
    freshness = _mapping(checks.get("symbol_index_freshness"))
    validation = _mapping(checks.get("validation_commands"))
    dashboard = _mapping(checks.get("dashboard_dag"))
    lines.extend(
        [
            "Checks:",
            (
                "- symbol index: "
                f"{freshness.get('indexed_file_count', 0)} files, "
                f"{freshness.get('stale_file_count', 0)} stale, "
                f"{freshness.get('failed_file_count', 0)} failed"
            ),
            f"- validation commands: {validation.get('command_count', 0)}",
            f"- dashboard DAG: {'available' if dashboard.get('available') else 'missing'}",
            "",
            "Expected parallelization:",
        ]
    )
    groups = _list(report.get("expected_parallelization"))
    if groups:
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            label = "same wave" if group.get("same_wave_parallel") else "single ready node"
            item_labels = [
                f"{_text(item.get('task_id'))}:{_text(item.get('action_type'))}"
                for item in _list(group.get("items"))
                if isinstance(item, Mapping)
            ]
            lines.append(f"- {label} via {group.get('execution_mode') or 'unknown'}: {', '.join(item_labels)}")
            reason = _text(group.get("why") or group.get("reason"))
            if reason:
                lines.append(f"  reason: {reason}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Serialized:")
    serialized = _list(report.get("serialized_tasks"))
    if serialized:
        for item in serialized:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- {_text(item.get('task_id'))}:{_text(item.get('action_type'))} "
                f"({item.get('reason_kind') or 'serialized'})"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Risks:")
    risks = _list(report.get("risk_areas"))
    if risks:
        for risk in risks:
            if not isinstance(risk, Mapping):
                continue
            lines.append(f"- {risk.get('severity')}: {risk.get('area')} - {risk.get('reason')}")
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=Path("."), help="Target repository to preflight.")
    parser.add_argument("--event-limit", type=int, default=20, help="Recent event count included in the backing snapshot.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a compact text report.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when the report status is block.")
    args = parser.parse_args(argv)

    report = build_parallelization_preflight_report(args.target, event_limit=max(0, args.event_limit))
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_render_human(report))
    if args.strict and report.get("status") == "block":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
