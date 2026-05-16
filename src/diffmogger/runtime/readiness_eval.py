#!/usr/bin/env python3
"""Evaluate symbol graph and DAG scheduler readiness against fixture repos."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from diffmogger.runtime.state_store import (
    IMPACT_CONTEXT_PACK_LIMIT,
    PARALLEL_SCOPING_READ_CONFIDENCE_THRESHOLD,
    PARALLEL_WRITE_TOUCH_CONFIDENCE_THRESHOLD,
    build_context_pack_conn,
    codebase_graph_summary,
    connect,
    database_path_for_target,
    ensure_codebase_graph_conn,
    execution_dag_read_model,
    impact_graph_summary,
    plan_parallel_execution_groups_conn,
    refresh_capability_manifest_conn,
    refresh_codebase_graph_staleness_conn,
    refresh_impact_graph_conn,
    refresh_task_graph_conn,
    upsert_execution_dag_node,
    write_ticket_run_state,
)


DEFAULT_DIRECT_WRITE_PRECISION_MIN = 0.95
DEFAULT_ADVISORY_IMPACT_RECALL_MIN = 0.75
DEFAULT_SCHEDULER_READINESS_MIN = 0.85


@dataclass(frozen=True)
class ReadinessThresholds:
    direct_write_precision_min: float = DEFAULT_DIRECT_WRITE_PRECISION_MIN
    advisory_impact_recall_min: float = DEFAULT_ADVISORY_IMPACT_RECALL_MIN
    scheduler_readiness_min: float = DEFAULT_SCHEDULER_READINESS_MIN


@dataclass(frozen=True)
class EvalDagNode:
    node_id: str
    task_id: str
    summary: str
    paths: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    action_type: str = "build"
    status: str = "ready"
    owner_role: str = "builder"
    confidence: float = 0.9


@dataclass(frozen=True)
class EvalScenario:
    name: str
    description: str
    coverage_tags: tuple[str, ...]
    files: Mapping[str, str]
    tickets: tuple[Mapping[str, Any], ...]
    expected_direct_paths: Mapping[str, frozenset[str]] = field(default_factory=dict)
    expected_advisory_paths: Mapping[str, frozenset[str]] = field(default_factory=dict)
    preindex_before_mutations: bool = False
    mutations_after_index: Mapping[str, str] = field(default_factory=dict)
    dag_nodes: tuple[EvalDagNode, ...] = ()
    expect_group_task_sets: tuple[frozenset[str], ...] = ()
    forbid_group_task_sets: tuple[frozenset[str], ...] = ()
    expect_group_dag_node_sets: tuple[frozenset[str], ...] = ()
    expect_blocked: tuple[Mapping[str, Any], ...] = ()
    expect_no_groups: bool = False
    expect_stale_file_count_min: int = 0
    expect_symbol_leases: bool = False


def _fs(*items: str) -> frozenset[str]:
    return frozenset(items)


def readiness_eval_scenarios() -> list[EvalScenario]:
    return [
        EvalScenario(
            name="direct_path",
            description="Authored task metadata names the file that may be written.",
            coverage_tags=("direct_paths",),
            files={
                "src/auth.py": "AUTH_ENABLED = True\n",
            },
            tickets=(
                {
                    "id": "PATH-1",
                    "summary": "Update the authentication toggle.",
                    "status": "pending",
                    "paths": ["src/auth.py"],
                },
            ),
            expected_direct_paths={"PATH-1": _fs("src/auth.py")},
        ),
        EvalScenario(
            name="exact_symbol",
            description="An exact Python symbol owner unlocks a direct write candidate without a path mention.",
            coverage_tags=("exact_symbols",),
            files={
                "src/payments.py": "def calculate_total(items):\n    return sum(items)\n",
            },
            tickets=(
                {
                    "id": "SYM-1",
                    "summary": "Adjust the total calculation behavior.",
                    "status": "pending",
                    "symbols": ["calculate_total"],
                },
            ),
            expected_direct_paths={"SYM-1": _fs("src/payments.py")},
        ),
        EvalScenario(
            name="ambiguous_symbol",
            description="Same-name symbol owners must remain advisory and explain the missing confidence signal.",
            coverage_tags=("ambiguous_symbols",),
            files={
                "src/alpha.py": "class Shared:\n    pass\n",
                "src/beta.py": "class Shared:\n    pass\n",
            },
            tickets=(
                {
                    "id": "AMB-1",
                    "summary": "Update Shared behavior.",
                    "status": "pending",
                    "symbols": ["Shared"],
                },
            ),
            expected_direct_paths={"AMB-1": frozenset()},
            expect_no_groups=True,
            expect_blocked=(
                {
                    "task_id": "AMB-1",
                    "reason_kind": "missing_direct_write_signal",
                    "confidence_signal": "ambiguous_symbol",
                    "missing_confidence_signal": "direct_path_or_exact_symbol",
                },
            ),
        ),
        EvalScenario(
            name="stale_index",
            description="A stale exact symbol is downgraded before the scheduler can treat it as write ownership.",
            coverage_tags=("stale_indexes",),
            files={
                "src/auth.py": "class AuthService:\n    pass\n",
            },
            tickets=(
                {
                    "id": "STALE-1",
                    "summary": "Update AuthService behavior.",
                    "status": "pending",
                    "symbols": ["AuthService"],
                },
            ),
            expected_direct_paths={"STALE-1": frozenset()},
            preindex_before_mutations=True,
            mutations_after_index={
                "src/auth.py": "class AuthService:\n    pass\n\nSTALE_SENTINEL = True\n",
            },
            expect_no_groups=True,
            expect_stale_file_count_min=1,
            expect_blocked=(
                {
                    "task_id": "STALE-1",
                    "reason_kind": "missing_direct_write_signal",
                    "confidence_signal": "stale_symbol",
                    "missing_confidence_signal": "direct_path_or_exact_symbol",
                },
            ),
        ),
        EvalScenario(
            name="import_adjacency",
            description="A direct owner path pulls importer files into advisory impact recall.",
            coverage_tags=("imports",),
            files={
                "src/__init__.py": "",
                "src/util.py": "def normalize_name(value):\n    return value.strip().lower()\n",
                "src/consumer.py": "from src.util import normalize_name\nRESULT = normalize_name(' Ada ')\n",
            },
            tickets=(
                {
                    "id": "IMP-1",
                    "summary": "Update utility normalization behavior.",
                    "status": "pending",
                    "paths": ["src/util.py"],
                },
            ),
            expected_direct_paths={"IMP-1": _fs("src/util.py")},
            expected_advisory_paths={"IMP-1": _fs("src/consumer.py")},
        ),
        EvalScenario(
            name="cross_language_interface",
            description="OpenAPI and generated-client route matches are advisory cross-language context.",
            coverage_tags=("cross_language_interfaces", "mixed_language_repos"),
            files={
                "api/openapi.yaml": (
                    "openapi: 3.1.0\n"
                    "paths:\n"
                    "  /api/users/{id}:\n"
                    "    get:\n"
                    "      operationId: getUser\n"
                    "components:\n"
                    "  schemas:\n"
                    "    User:\n"
                    "      type: object\n"
                ),
                "src/users.ts": "export class UsersApi { getUser() { return fetch('/api/users/:id'); } }\n",
            },
            tickets=(
                {
                    "id": "XIF-1",
                    "summary": "Update the user contract.",
                    "status": "pending",
                    "paths": ["api/openapi.yaml"],
                },
            ),
            expected_direct_paths={"XIF-1": _fs("api/openapi.yaml")},
            expected_advisory_paths={"XIF-1": _fs("src/users.ts")},
        ),
        EvalScenario(
            name="overlapping_ownership",
            description="Two high-confidence writes to the same file cannot share a wave.",
            coverage_tags=("overlapping_ownership",),
            files={
                "src/shared.py": "SHARED = True\n",
            },
            tickets=(
                {
                    "id": "OVL-1",
                    "summary": "Update shared login behavior.",
                    "status": "pending",
                    "paths": ["src/shared.py"],
                },
                {
                    "id": "OVL-2",
                    "summary": "Update shared session behavior.",
                    "status": "pending",
                    "paths": ["src/shared.py"],
                },
            ),
            forbid_group_task_sets=(_fs("OVL-1", "OVL-2"),),
            expect_no_groups=True,
            expect_blocked=(
                {
                    "task_id": "OVL-2",
                    "reason_kind": "write_surface_overlap",
                    "reason_contains": "overlap",
                },
            ),
        ),
        EvalScenario(
            name="same_file_disjoint_symbols",
            description="Same-file writes can share a wave only when exact symbol leases are disjoint and fresh.",
            coverage_tags=("same_file_disjoint_symbols",),
            files={
                "src/auth.py": "class AuthLogin:\n    pass\n\nclass AuthTokens:\n    pass\n",
            },
            tickets=(
                {
                    "id": "SAME-1",
                    "summary": "Completed shell for split symbol ownership.",
                    "status": "done",
                },
            ),
            expected_direct_paths={"SAME-1": _fs("src/auth.py")},
            dag_nodes=(
                EvalDagNode(
                    node_id="dag-node:eval:SAME-1:login",
                    task_id="SAME-1",
                    summary="Update AuthLogin behavior.",
                    symbols=("AuthLogin",),
                ),
                EvalDagNode(
                    node_id="dag-node:eval:SAME-1:tokens",
                    task_id="SAME-1",
                    summary="Update AuthTokens behavior.",
                    symbols=("AuthTokens",),
                ),
            ),
            expect_group_dag_node_sets=(_fs("dag-node:eval:SAME-1:login", "dag-node:eval:SAME-1:tokens"),),
            expect_symbol_leases=True,
        ),
    ]


def _write_text(root: Path, rel_path: str, text: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_fixture_files(target: Path, files: Mapping[str, str]) -> None:
    for rel_path, text in sorted(files.items()):
        _write_text(target, rel_path, text)


def _write_project_setup(target: Path) -> None:
    setup_path = target / ".agentic" / "project_intake.json"
    setup_path.parent.mkdir(parents=True, exist_ok=True)
    setup_path.write_text(
        json.dumps(
            {
                "project_name": f"Readiness Fixture {target.name}",
                "campaign_mode": "bounded",
                "worker_agents_allowed": True,
                "write_worker_agents_allowed": True,
                "max_write_worker_count": 4,
                "parallel_execution_mode": "aggressive",
                "symbol_graph_languages": ["python", "typescript", "javascript", "rust", "go", "java"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_ticket_run(target: Path, scenario: EvalScenario) -> None:
    if not scenario.tickets:
        return
    write_ticket_run_state(
        target,
        {
            "run_id": f"readiness-{scenario.name}",
            "halt_when_complete": True,
            "notify_on_complete": False,
            "tickets": [dict(item) for item in scenario.tickets],
        },
        actor_role="readiness_eval",
        event_type="readiness_eval.ticket_run_seeded",
    )


def _seed_dag_nodes(target: Path, scenario: EvalScenario) -> None:
    if not scenario.dag_nodes:
        return
    with closing(connect(database_path_for_target(target))) as conn:
        with conn:
            for node in scenario.dag_nodes:
                metadata: dict[str, Any] = {
                    "source": "readiness_eval",
                    "summary": node.summary,
                }
                if node.paths:
                    metadata["paths"] = list(node.paths)
                if node.symbols:
                    metadata["symbols"] = list(node.symbols)
                upsert_execution_dag_node(
                    conn,
                    node_id=node.node_id,
                    task_id=node.task_id,
                    action_type=node.action_type,
                    status=node.status,
                    owner_role=node.owner_role,
                    confidence=node.confidence,
                    metadata=metadata,
                )


def _prepare_graph(target: Path) -> dict[str, Any]:
    with closing(connect(database_path_for_target(target))) as conn:
        capability = refresh_capability_manifest_conn(conn, target)
        return ensure_codebase_graph_conn(conn, target, capability=capability)


def _mark_stale_after_mutations(target: Path, graph_summary: Mapping[str, Any]) -> None:
    snapshot_id = str(graph_summary.get("latest_snapshot_id") or "")
    if not snapshot_id:
        return
    with closing(connect(database_path_for_target(target))) as conn:
        refresh_codebase_graph_staleness_conn(conn, target, snapshot_id=snapshot_id)


def _candidate_task_sets(plan: Mapping[str, Any]) -> list[frozenset[str]]:
    groups = plan.get("proposed_execution_groups") if isinstance(plan.get("proposed_execution_groups"), list) else []
    task_sets: list[frozenset[str]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        items = group.get("items") if isinstance(group.get("items"), list) else []
        task_sets.append(frozenset(str(item.get("task_id") or "") for item in items if isinstance(item, Mapping)))
    return task_sets


def _candidate_dag_node_sets(plan: Mapping[str, Any]) -> list[frozenset[str]]:
    groups = plan.get("proposed_execution_groups") if isinstance(plan.get("proposed_execution_groups"), list) else []
    node_sets: list[frozenset[str]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        nodes: set[str] = set()
        for item in group.get("items") if isinstance(group.get("items"), list) else []:
            if not isinstance(item, Mapping):
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            node_id = str(payload.get("dag_node_id") or item.get("dag_node_id") or "")
            if node_id:
                nodes.add(node_id)
        node_sets.append(frozenset(nodes))
    return node_sets


def _direct_predictions(plan: Mapping[str, Any]) -> dict[str, set[str]]:
    predicted: dict[str, set[str]] = {}
    groups = plan.get("proposed_execution_groups") if isinstance(plan.get("proposed_execution_groups"), list) else []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        for item in group.get("items") if isinstance(group.get("items"), list) else []:
            if not isinstance(item, Mapping):
                continue
            task_id = str(item.get("task_id") or "")
            payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            touches = payload.get("likely_touches") if isinstance(payload.get("likely_touches"), list) else []
            for touch in touches:
                if not isinstance(touch, Mapping):
                    continue
                path = str(touch.get("path") or "")
                if path:
                    predicted.setdefault(task_id, set()).add(path)
    return predicted


def _advisory_predictions(context_packs: Mapping[str, Mapping[str, Any]]) -> dict[str, set[str]]:
    predicted: dict[str, set[str]] = {}
    for task_id, pack in context_packs.items():
        paths: set[str] = set()
        items = pack.get("items") if isinstance(pack.get("items"), list) else []
        direct_paths = {
            str(item.get("path") or "")
            for item in items
            if isinstance(item, Mapping) and bool(item.get("write_candidate")) and str(item.get("path") or "")
        }
        for item in items:
            if not isinstance(item, Mapping):
                continue
            path = str(item.get("path") or "")
            if (
                path
                and path not in direct_paths
                and not bool(item.get("write_candidate"))
                and float(item.get("confidence") or 0) >= PARALLEL_SCOPING_READ_CONFIDENCE_THRESHOLD
            ):
                paths.add(path)
        symbol_context = pack.get("symbol_context") if isinstance(pack.get("symbol_context"), Mapping) else {}
        for bucket in ("likely_tests", "dependency_neighbors", "interface_edges"):
            for item in symbol_context.get(bucket) if isinstance(symbol_context.get(bucket), list) else []:
                if not isinstance(item, Mapping):
                    continue
                path = str(item.get("path") or item.get("owner_file_path") or "")
                if (
                    path
                    and path not in direct_paths
                    and float(item.get("confidence") or 0) >= PARALLEL_SCOPING_READ_CONFIDENCE_THRESHOLD
                ):
                    paths.add(path)
        predicted[task_id] = paths
    return predicted


def _blocked_candidates(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        item
        for item in (plan.get("blocked_parallel_candidates") if isinstance(plan.get("blocked_parallel_candidates"), list) else [])
        if isinstance(item, Mapping)
    ]


def _symbol_leases(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    leases: list[Mapping[str, Any]] = []
    groups = plan.get("proposed_execution_groups") if isinstance(plan.get("proposed_execution_groups"), list) else []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        for item in group.get("items") if isinstance(group.get("items"), list) else []:
            if not isinstance(item, Mapping):
                continue
            for lease in item.get("required_leases") if isinstance(item.get("required_leases"), list) else []:
                if isinstance(lease, Mapping) and str(lease.get("scope_kind") or "") == "symbol":
                    leases.append(lease)
    return leases


def _check_blocked_expectation(blocked: list[Mapping[str, Any]], expectation: Mapping[str, Any]) -> tuple[bool, str]:
    for item in blocked:
        if expectation.get("task_id") and str(item.get("task_id") or "") != str(expectation.get("task_id") or ""):
            continue
        if expectation.get("dag_node_id") and str(item.get("dag_node_id") or "") != str(expectation.get("dag_node_id") or ""):
            continue
        if expectation.get("reason_kind") and str(item.get("reason_kind") or "") != str(expectation.get("reason_kind") or ""):
            continue
        if expectation.get("confidence_signal"):
            signals = item.get("confidence_signals") if isinstance(item.get("confidence_signals"), list) else []
            if str(expectation.get("confidence_signal") or "") not in {str(signal) for signal in signals}:
                continue
        if expectation.get("missing_confidence_signal") and str(item.get("missing_confidence_signal") or "") != str(
            expectation.get("missing_confidence_signal") or ""
        ):
            continue
        if expectation.get("reason_contains") and str(expectation.get("reason_contains") or "") not in str(item.get("reason") or ""):
            continue
        return True, ""
    return False, f"blocked candidate expectation not met: {dict(expectation)}"


def _scheduler_checks(scenario: EvalScenario, plan: Mapping[str, Any], codebase_summary: Mapping[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    groups = plan.get("proposed_execution_groups") if isinstance(plan.get("proposed_execution_groups"), list) else []
    task_sets = _candidate_task_sets(plan)
    dag_node_sets = _candidate_dag_node_sets(plan)
    blocked = _blocked_candidates(plan)

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if scenario.expect_no_groups:
        add("expect_no_groups", not groups, "no proposed execution groups expected")
    for expected in scenario.expect_group_task_sets:
        add(
            f"expect_group_tasks:{','.join(sorted(expected))}",
            any(expected.issubset(group) for group in task_sets),
            f"expected one group to include tasks {sorted(expected)}",
        )
    for forbidden in scenario.forbid_group_task_sets:
        add(
            f"forbid_group_tasks:{','.join(sorted(forbidden))}",
            not any(forbidden.issubset(group) for group in task_sets),
            f"forbidden same-wave task set {sorted(forbidden)}",
        )
    for expected in scenario.expect_group_dag_node_sets:
        add(
            f"expect_group_dag_nodes:{','.join(sorted(expected))}",
            any(expected.issubset(group) for group in dag_node_sets),
            f"expected one group to include DAG nodes {sorted(expected)}",
        )
    for expectation in scenario.expect_blocked:
        passed, detail = _check_blocked_expectation(blocked, expectation)
        add("expect_blocked", passed, detail or f"expected blocked candidate {dict(expectation)}")
    if scenario.expect_stale_file_count_min:
        stale_count = int(codebase_summary.get("stale_file_count") or 0)
        add(
            "expect_stale_file_count",
            stale_count >= scenario.expect_stale_file_count_min,
            f"expected at least {scenario.expect_stale_file_count_min} stale file(s), saw {stale_count}",
        )
    if scenario.expect_symbol_leases:
        leases = _symbol_leases(plan)
        add(
            "expect_symbol_leases",
            bool(leases) and all(float(lease.get("confidence") or 0) >= PARALLEL_WRITE_TOUCH_CONFIDENCE_THRESHOLD for lease in leases),
            f"expected direct symbol leases above {PARALLEL_WRITE_TOUCH_CONFIDENCE_THRESHOLD:.2f}",
        )

    passed = sum(1 for item in checks if item["passed"])
    total = len(checks)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "readiness": 1.0 if total == 0 else round(passed / total, 4),
        "checks": checks,
    }


def _build_context_packs(target: Path, scenario: EvalScenario) -> dict[str, dict[str, Any]]:
    packs: dict[str, dict[str, Any]] = {}
    with closing(connect(database_path_for_target(target))) as conn:
        for ticket in scenario.tickets:
            task_id = str(ticket.get("id") or "")
            if not task_id:
                continue
            packs[task_id] = build_context_pack_conn(
                conn,
                target,
                ticket_id=task_id,
                max_items=IMPACT_CONTEXT_PACK_LIMIT,
            )
    return packs


def run_eval_scenario(root: Path, scenario: EvalScenario) -> dict[str, Any]:
    target = root / scenario.name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    _write_project_setup(target)
    _write_fixture_files(target, scenario.files)

    preindex_summary: dict[str, Any] = {}
    if scenario.preindex_before_mutations:
        preindex_summary = _prepare_graph(target)

    _seed_ticket_run(target, scenario)

    if not scenario.preindex_before_mutations:
        _prepare_graph(target)

    if scenario.mutations_after_index:
        _write_fixture_files(target, scenario.mutations_after_index)
        _mark_stale_after_mutations(target, preindex_summary)

    _seed_dag_nodes(target, scenario)

    with closing(connect(database_path_for_target(target))) as conn:
        refresh_task_graph_conn(conn, target)
        refresh_impact_graph_conn(conn, target)
        codebase_summary = codebase_graph_summary(conn)
        impact_summary = impact_graph_summary(conn)
        dag_model = execution_dag_read_model(conn)
        plan = plan_parallel_execution_groups_conn(conn, target, selected_by="readiness_eval", persist=False)

    context_packs = _build_context_packs(target, scenario)
    direct_predicted = _direct_predictions(plan)
    advisory_predicted = _advisory_predictions(context_packs)
    scheduler = _scheduler_checks(scenario, plan, codebase_summary)

    return {
        "name": scenario.name,
        "description": scenario.description,
        "coverage_tags": list(scenario.coverage_tags),
        "target": str(target),
        "expected_direct_paths": {task_id: sorted(paths) for task_id, paths in scenario.expected_direct_paths.items()},
        "predicted_direct_paths": {task_id: sorted(paths) for task_id, paths in sorted(direct_predicted.items())},
        "expected_advisory_paths": {task_id: sorted(paths) for task_id, paths in scenario.expected_advisory_paths.items()},
        "predicted_advisory_paths": {task_id: sorted(paths) for task_id, paths in sorted(advisory_predicted.items())},
        "scheduler_checks": scheduler,
        "parallelization_summary": plan.get("parallelization_summary") if isinstance(plan.get("parallelization_summary"), Mapping) else {},
        "blocked_parallel_candidates": list(plan.get("blocked_parallel_candidates") or [])[:8],
        "proposed_group_count": len(plan.get("proposed_execution_groups") or []),
        "codebase_graph": {
            "snapshot_id": str(codebase_summary.get("latest_snapshot_id") or ""),
            "indexed_file_count": int((codebase_summary.get("latest_graph_snapshot") or {}).get("indexed_file_count") or 0)
            if isinstance(codebase_summary.get("latest_graph_snapshot"), Mapping)
            else 0,
            "stale_file_count": int(codebase_summary.get("stale_file_count") or 0),
            "stale_node_count": int(codebase_summary.get("stale_node_count") or 0),
        },
        "impact_graph": {
            "snapshot_id": str(impact_summary.get("latest_snapshot_id") or ""),
            "edge_count": int((impact_summary.get("latest_graph_snapshot") or {}).get("edge_count") or 0)
            if isinstance(impact_summary.get("latest_graph_snapshot"), Mapping)
            else 0,
        },
        "execution_dag": {
            "node_count": len(dag_model.get("nodes") or []) if isinstance(dag_model.get("nodes"), list) else 0,
            "ready_count": len(dag_model.get("ready_nodes") or []) if isinstance(dag_model.get("ready_nodes"), list) else 0,
            "blocked_count": len(dag_model.get("blocked_nodes") or []) if isinstance(dag_model.get("blocked_nodes"), list) else 0,
        },
    }


def _score_path_sets(
    scenarios: list[Mapping[str, Any]],
    *,
    expected_key: str,
    predicted_key: str,
) -> dict[str, Any]:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    task_results: list[dict[str, Any]] = []
    for scenario in scenarios:
        expected_by_task = scenario.get(expected_key) if isinstance(scenario.get(expected_key), Mapping) else {}
        predicted_by_task = scenario.get(predicted_key) if isinstance(scenario.get(predicted_key), Mapping) else {}
        task_ids = sorted({*expected_by_task.keys(), *predicted_by_task.keys()})
        for task_id in task_ids:
            expected = {str(item) for item in expected_by_task.get(task_id, [])}
            predicted = {str(item) for item in predicted_by_task.get(task_id, [])}
            tp = len(expected.intersection(predicted))
            fp = len(predicted - expected)
            fn = len(expected - predicted)
            true_positive += tp
            false_positive += fp
            false_negative += fn
            task_results.append(
                {
                    "scenario": str(scenario.get("name") or ""),
                    "task_id": str(task_id),
                    "true_positive": tp,
                    "false_positive": fp,
                    "false_negative": fn,
                    "expected": sorted(expected),
                    "predicted": sorted(predicted),
                }
            )
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = 1.0 if precision_denominator == 0 else true_positive / precision_denominator
    recall = 1.0 if recall_denominator == 0 else true_positive / recall_denominator
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "task_results": task_results,
    }


def _scheduler_readiness(scenarios: list[Mapping[str, Any]]) -> dict[str, Any]:
    total = 0
    passed = 0
    failures: list[dict[str, Any]] = []
    for scenario in scenarios:
        checks = scenario.get("scheduler_checks") if isinstance(scenario.get("scheduler_checks"), Mapping) else {}
        total += int(checks.get("total") or 0)
        passed += int(checks.get("passed") or 0)
        for item in checks.get("checks") if isinstance(checks.get("checks"), list) else []:
            if isinstance(item, Mapping) and not bool(item.get("passed")):
                failures.append({"scenario": str(scenario.get("name") or ""), **dict(item)})
    readiness = 1.0 if total == 0 else passed / total
    return {
        "passed": passed,
        "total": total,
        "failed": total - passed,
        "readiness": round(readiness, 4),
        "failures": failures,
    }


def _coverage_summary(scenarios: list[Mapping[str, Any]]) -> dict[str, Any]:
    tags: set[str] = set()
    for scenario in scenarios:
        tags.update(str(item) for item in scenario.get("coverage_tags", []) if str(item))
    required = {
        "direct_paths",
        "exact_symbols",
        "ambiguous_symbols",
        "stale_indexes",
        "imports",
        "cross_language_interfaces",
        "overlapping_ownership",
        "same_file_disjoint_symbols",
    }
    return {
        "required_tags": sorted(required),
        "covered_tags": sorted(tags),
        "missing_tags": sorted(required - tags),
        "complete": not bool(required - tags),
    }


def build_readiness_report(
    scenario_results: list[Mapping[str, Any]],
    *,
    thresholds: ReadinessThresholds = ReadinessThresholds(),
    fixture_root: Path | None = None,
) -> dict[str, Any]:
    direct = _score_path_sets(
        scenario_results,
        expected_key="expected_direct_paths",
        predicted_key="predicted_direct_paths",
    )
    advisory = _score_path_sets(
        scenario_results,
        expected_key="expected_advisory_paths",
        predicted_key="predicted_advisory_paths",
    )
    scheduler = _scheduler_readiness(scenario_results)
    coverage = _coverage_summary(scenario_results)
    overall = round(
        (
            float(direct.get("precision") or 0)
            + float(advisory.get("recall") or 0)
            + float(scheduler.get("readiness") or 0)
        )
        / 3,
        4,
    )
    report = {
        "schema_version": 1,
        "harness": "symbol_scheduler_readiness_v1",
        "fixture_root": str(fixture_root or ""),
        "scenario_count": len(scenario_results),
        "coverage": coverage,
        "thresholds": {
            "direct_write_precision_min": float(thresholds.direct_write_precision_min),
            "advisory_impact_recall_min": float(thresholds.advisory_impact_recall_min),
            "scheduler_readiness_min": float(thresholds.scheduler_readiness_min),
        },
        "metrics": {
            "direct_write_precision": direct["precision"],
            "direct_write_recall": direct["recall"],
            "advisory_impact_precision": advisory["precision"],
            "advisory_impact_recall": advisory["recall"],
            "scheduler_readiness": scheduler["readiness"],
            "overall_readiness": overall,
            "direct_write": direct,
            "advisory_impact": advisory,
            "scheduler": scheduler,
        },
        "scenarios": list(scenario_results),
    }
    report["gate"] = readiness_gate(report, thresholds=thresholds, enforcement="report")
    return report


def readiness_gate(
    report: Mapping[str, Any],
    *,
    thresholds: ReadinessThresholds = ReadinessThresholds(),
    enforcement: str = "warn",
) -> dict[str, Any]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    failures: list[dict[str, Any]] = []
    comparisons = [
        ("direct_write_precision", float(thresholds.direct_write_precision_min)),
        ("advisory_impact_recall", float(thresholds.advisory_impact_recall_min)),
        ("scheduler_readiness", float(thresholds.scheduler_readiness_min)),
    ]
    for metric, threshold in comparisons:
        value = float(metrics.get(metric) or 0)
        if value < threshold:
            failures.append({"metric": metric, "value": round(value, 4), "threshold": round(threshold, 4)})
    coverage = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
    if not bool(coverage.get("complete", True)):
        failures.append({"metric": "coverage", "missing_tags": list(coverage.get("missing_tags") or [])})
    normalized_enforcement = str(enforcement or "warn").strip().lower()
    if normalized_enforcement not in {"report", "warn", "block"}:
        normalized_enforcement = "warn"
    status = "pass"
    exit_code = 0
    if failures and normalized_enforcement == "block":
        status = "blocked"
        exit_code = 2
    elif failures and normalized_enforcement == "warn":
        status = "warn"
    elif failures:
        status = "below_threshold"
    return {
        "schema_version": 1,
        "status": status,
        "enforcement": normalized_enforcement,
        "threshold_failures": failures,
        "exit_code": exit_code,
    }


def run_readiness_eval(
    *,
    fixture_root: Path | None = None,
    keep_fixtures: bool = False,
    thresholds: ReadinessThresholds = ReadinessThresholds(),
) -> dict[str, Any]:
    scenarios = readiness_eval_scenarios()
    if fixture_root is not None:
        root = fixture_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        scenario_results = [run_eval_scenario(root, scenario) for scenario in scenarios]
        return build_readiness_report(scenario_results, thresholds=thresholds, fixture_root=root)

    temp = tempfile.TemporaryDirectory(prefix="diffmogger-readiness-eval-")
    root = Path(temp.name)
    try:
        scenario_results = [run_eval_scenario(root, scenario) for scenario in scenarios]
        report = build_readiness_report(scenario_results, thresholds=thresholds, fixture_root=root)
        if keep_fixtures:
            kept = root.parent / f"{root.name}-kept"
            if kept.exists():
                shutil.rmtree(kept)
            shutil.move(str(root), str(kept))
            report["fixture_root"] = str(kept)
            temp.cleanup()
        return report
    finally:
        if not keep_fixtures:
            temp.cleanup()


def _threshold_from_env(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


def _format_metric(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def _print_human_report(report: Mapping[str, Any]) -> None:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    direct = metrics.get("direct_write") if isinstance(metrics.get("direct_write"), Mapping) else {}
    advisory = metrics.get("advisory_impact") if isinstance(metrics.get("advisory_impact"), Mapping) else {}
    scheduler = metrics.get("scheduler") if isinstance(metrics.get("scheduler"), Mapping) else {}
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    print("Diffmogger symbol scheduler readiness")
    print(f"Fixture scenarios: {int(report.get('scenario_count') or 0)}")
    print(
        "Direct-write precision: "
        f"{_format_metric(metrics.get('direct_write_precision'))} "
        f"({int(direct.get('true_positive') or 0)} TP / {int(direct.get('false_positive') or 0)} FP)"
    )
    print(
        "Advisory impact recall: "
        f"{_format_metric(metrics.get('advisory_impact_recall'))} "
        f"({int(advisory.get('true_positive') or 0)} TP / {int(advisory.get('false_negative') or 0)} FN)"
    )
    print(
        "Scheduler readiness: "
        f"{_format_metric(metrics.get('scheduler_readiness'))} "
        f"({int(scheduler.get('passed') or 0)}/{int(scheduler.get('total') or 0)} checks)"
    )
    print(f"Overall readiness: {_format_metric(metrics.get('overall_readiness'))}")
    print(f"Gate status: {str(gate.get('status') or 'pass')}")
    failures = gate.get("threshold_failures") if isinstance(gate.get("threshold_failures"), list) else []
    if failures:
        print("Threshold failures:")
        for failure in failures:
            print(f"- {failure}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, help="Directory where fixture repos should be created.")
    parser.add_argument("--keep-fixtures", action="store_true", help="Keep generated temporary fixture repos for inspection.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    parser.add_argument("--first-24h", action="store_true", help="Run as the first-24h DAG readiness gate.")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when metrics are below configured thresholds.")
    parser.add_argument(
        "--direct-write-precision-min",
        type=float,
        default=_threshold_from_env("DIFFMOGGER_READINESS_DIRECT_WRITE_PRECISION_MIN", DEFAULT_DIRECT_WRITE_PRECISION_MIN),
    )
    parser.add_argument(
        "--advisory-impact-recall-min",
        type=float,
        default=_threshold_from_env("DIFFMOGGER_READINESS_ADVISORY_IMPACT_RECALL_MIN", DEFAULT_ADVISORY_IMPACT_RECALL_MIN),
    )
    parser.add_argument(
        "--scheduler-readiness-min",
        type=float,
        default=_threshold_from_env("DIFFMOGGER_READINESS_SCHEDULER_READINESS_MIN", DEFAULT_SCHEDULER_READINESS_MIN),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    thresholds = ReadinessThresholds(
        direct_write_precision_min=float(args.direct_write_precision_min),
        advisory_impact_recall_min=float(args.advisory_impact_recall_min),
        scheduler_readiness_min=float(args.scheduler_readiness_min),
    )
    report = run_readiness_eval(
        fixture_root=args.fixture_root,
        keep_fixtures=bool(args.keep_fixtures),
        thresholds=thresholds,
    )
    env_enforcement = os.environ.get("DIFFMOGGER_READINESS_ENFORCEMENT") or os.environ.get("DIFFMOGGER_FIRST_24H_READINESS_ENFORCEMENT")
    enforcement = "block" if args.strict else str(env_enforcement or ("warn" if args.first_24h else "report"))
    gate = readiness_gate(report, thresholds=thresholds, enforcement=enforcement)
    report["gate"] = gate

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_report(report)

    if gate["status"] in {"warn", "blocked"}:
        print(
            "READINESS_WARNING: symbol scheduler readiness is below configured threshold(s): "
            + json.dumps(gate["threshold_failures"], sort_keys=True),
            file=sys.stderr,
        )
    return int(gate.get("exit_code") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
