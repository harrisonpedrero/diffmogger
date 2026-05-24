"""Pure scheduling policy used by Temporal activities and tests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from diffmogger.contracts import (
    CodeFact,
    ConflictTelemetry,
    DagEdge,
    DagNode,
    ExecutionGroup,
    IntegrationDecision,
    OwnershipLease,
    RepairUnblockerWork,
    SchedulerCandidate,
    SchedulerRecord,
    SchedulerTelemetry,
    TicketRecord,
    ValidationGate,
    ValidationGroup,
    ValidationReceipt,
)


DEFAULT_MIN_WRITE_CONFIDENCE = 0.75
DEFAULT_FACT_TTL = timedelta(hours=24)


def _path_key(target_path: Path, value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw)
        if path.is_absolute():
            resolved = path.resolve()
            try:
                return resolved.relative_to(target_path.resolve()).as_posix().rstrip("/")
            except ValueError:
                return resolved.as_posix().rstrip("/")
        rel = path.as_posix()
        while rel.startswith("./"):
            rel = rel[2:]
        return rel.rstrip("/")
    except Exception:
        rel = raw.replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        return rel.rstrip("/")


def _paths(target_path: Path, values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for value in values:
        key = _path_key(target_path, value)
        if key and key not in seen:
            seen.add(key)
            paths.append(key)
    return paths


def _overlaps(left: Iterable[str], right: Iterable[str]) -> bool:
    left_norm = {item.rstrip("/") for item in left if item}
    right_norm = {item.rstrip("/") for item in right if item}
    for left_path in left_norm:
        for right_path in right_norm:
            if left_path == right_path or left_path.startswith(right_path + "/") or right_path.startswith(left_path + "/"):
                return True
    return False


def _stable_id(prefix: str, *parts: object) -> str:
    raw = ":".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _candidate_id(run_id: str, suffix: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_:" else "-" for ch in suffix)
    return f"candidate:{run_id}:{safe}"


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _fact_index(target_path: Path, code_facts: Iterable[CodeFact]) -> dict[str, list[CodeFact]]:
    index: dict[str, list[CodeFact]] = {}
    for fact in code_facts:
        key = _path_key(target_path, fact.file_path)
        if not key:
            continue
        index.setdefault(key, []).append(fact)
    return index


def _facts_for_paths(index: dict[str, list[CodeFact]], paths: Iterable[str]) -> list[CodeFact]:
    matched: list[CodeFact] = []
    for fact_path, facts in index.items():
        if _overlaps([fact_path], paths):
            matched.extend(facts)
    return matched


def _module_names(path: str) -> set[str]:
    without_suffix = str(Path(path).with_suffix("")).replace("\\", "/")
    dotted = without_suffix.replace("/", ".").strip(".")
    parts = dotted.split(".")
    names = {dotted, parts[-1] if parts else dotted}
    if parts and parts[0] == "src":
        names.add(".".join(parts[1:]))
    return {name for name in names if name}


def _fact_conflict(
    target_path: Path,
    left: SchedulerCandidate,
    right: SchedulerCandidate,
    index: dict[str, list[CodeFact]],
) -> tuple[str, str]:
    left_facts = _facts_for_paths(index, left.paths)
    right_facts = _facts_for_paths(index, right.paths)
    left_symbols = {fact.name for fact in left_facts if fact.kind == "symbol" and fact.name}
    right_symbols = {fact.name for fact in right_facts if fact.kind == "symbol" and fact.name}
    shared_symbols = left_symbols.intersection(right_symbols)
    if shared_symbols:
        return "symbol_overlap", "Both candidates define symbol(s): " + ", ".join(sorted(shared_symbols)[:5])

    left_modules = set().union(*(_module_names(path) for path in left.paths)) if left.paths else set()
    right_modules = set().union(*(_module_names(path) for path in right.paths)) if right.paths else set()
    left_imports = {fact.target for fact in left_facts if fact.kind == "import" and fact.target}
    right_imports = {fact.target for fact in right_facts if fact.kind == "import" and fact.target}
    for imported in left_imports:
        tail = imported.split(".")[-1]
        if imported in right_modules or tail in right_modules:
            return "import_coupling", f"{left.node_ids[0] if left.node_ids else left.candidate_id} imports {imported} from the other scope."
    for imported in right_imports:
        tail = imported.split(".")[-1]
        if imported in left_modules or tail in left_modules:
            return "import_coupling", f"{right.node_ids[0] if right.node_ids else right.candidate_id} imports {imported} from the other scope."
    return "", ""


def _scope_evidence(node: DagNode, facts: list[CodeFact]) -> list[str]:
    evidence = [str(item) for item in node.payload.get("scope_evidence", []) if str(item).strip()]
    for fact in facts:
        if fact.kind == "symbol" and fact.name:
            evidence.append(f"symbol:{fact.name}")
        elif fact.kind == "import" and fact.target:
            evidence.append(f"import:{fact.target}")
        elif fact.kind == "parser_unavailable":
            evidence.append(f"parser_unavailable:{fact.name}")
    seen: set[str] = set()
    deduped: list[str] = []
    for item in evidence:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:20]


def _active_and_stale_leases(
    leases: Iterable[OwnershipLease],
    now: datetime,
) -> tuple[list[OwnershipLease], list[OwnershipLease]]:
    active: list[OwnershipLease] = []
    stale: list[OwnershipLease] = []
    for lease in leases:
        if lease.status != "active":
            continue
        if lease.expires_at is not None and lease.expires_at <= now:
            stale.append(lease)
        else:
            active.append(lease)
    return active, stale


def _deps_satisfied(node: DagNode, nodes_by_id: dict[str, DagNode], edges: Iterable[DagEdge]) -> bool:
    for edge in edges:
        target = edge.to_node_id or str(getattr(edge, "target_node_id", ""))
        source = edge.from_node_id or str(getattr(edge, "source_node_id", ""))
        kind = edge.edge_type or str(getattr(edge, "dependency_kind", ""))
        if target != node.node_id or kind not in {"", "depends_on"}:
            continue
        upstream = nodes_by_id.get(source)
        if upstream is None or upstream.status != "done":
            return False
    return True


def _node_action_kind(node: DagNode, execution_mode: str) -> str:
    if execution_mode == "read_only_scope":
        return "launch_scope_work"
    if node.action_type == "validate":
        return "run_validation"
    if node.action_type == "integrate":
        return "integrate"
    return "launch_work"


def _candidate_from_node(
    *,
    target_path: Path,
    run_id: str,
    node: DagNode,
    facts: list[CodeFact],
    min_write_confidence: float,
) -> SchedulerCandidate:
    paths = _paths(target_path, node.paths)
    parser_unavailable = any(fact.kind == "parser_unavailable" for fact in facts)
    ambiguous_scope = not paths
    low_confidence = node.confidence < min_write_confidence
    if parser_unavailable:
        return SchedulerCandidate(
            candidate_id=_candidate_id(run_id, f"index-{node.node_id}"),
            action_kind="create_setup_work",
            execution_mode="setup",
            owner_role="planner",
            node_ids=[node.node_id],
            ticket_ids=[node.ticket_id] if node.ticket_id else [],
            paths=paths,
            scope_evidence=_scope_evidence(node, facts),
            code_fact_refs=[fact.fact_id for fact in facts],
            reason="Tree-sitter parser support is unavailable for this scope; create setup/indexing work.",
            fanout=1,
            confidence=node.confidence,
            telemetry={"parser_unavailable": True},
        )
    if ambiguous_scope or low_confidence:
        reason = "Ownership scope is ambiguous; run read-only scoping before write fanout."
        if low_confidence:
            reason = "Candidate confidence is below the write threshold; run read-only scoping before write fanout."
        return SchedulerCandidate(
            candidate_id=_candidate_id(run_id, f"scope-{node.node_id}"),
            action_kind="launch_scope_work",
            execution_mode="read_only_scope",
            owner_role=node.owner_role,
            node_ids=[node.node_id],
            ticket_ids=[node.ticket_id] if node.ticket_id else [],
            paths=paths,
            scope_evidence=_scope_evidence(node, facts),
            code_fact_refs=[fact.fact_id for fact in facts],
            reason=reason,
            fanout=1,
            confidence=node.confidence,
            telemetry={"ambiguous_scope": ambiguous_scope, "low_confidence": low_confidence},
        )
    action_kind = _node_action_kind(node, "write")
    execution_mode = "integrate" if action_kind == "integrate" else ("validate" if action_kind == "run_validation" else "write")
    return SchedulerCandidate(
        candidate_id=_candidate_id(run_id, f"node-{node.node_id}"),
        action_kind=action_kind,  # type: ignore[arg-type]
        execution_mode=execution_mode,  # type: ignore[arg-type]
        owner_role=node.owner_role,
        node_ids=[node.node_id],
        ticket_ids=[node.ticket_id] if node.ticket_id else [],
        paths=paths,
        scope_evidence=_scope_evidence(node, facts),
        code_fact_refs=[fact.fact_id for fact in facts],
        required_lease_ids=[_stable_id("lease", run_id, node.node_id, path) for path in paths] or [_stable_id("lease", run_id, node.node_id)],
        reason="Ready DAG node has explicit ownership scope and enough confidence for write execution.",
        fanout=1,
        confidence=node.confidence,
    )


def _conflict(
    *,
    run_id: str,
    left: SchedulerCandidate,
    right: SchedulerCandidate,
    conflict_type: str,
    detail: str,
    severity: str = "fanout_reduced",
) -> ConflictTelemetry:
    return ConflictTelemetry(
        conflict_id=_stable_id("conflict", run_id, left.candidate_id, right.candidate_id, conflict_type, detail),
        run_id=run_id,
        left_candidate_id=left.candidate_id,
        right_candidate_id=right.candidate_id,
        left_node_id=left.node_ids[0] if left.node_ids else "",
        right_node_id=right.node_ids[0] if right.node_ids else "",
        conflict_type=conflict_type,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        paths=sorted(set([*left.paths, *right.paths])),
        detail=detail,
    )


def _lease_conflict(
    *,
    target_path: Path,
    run_id: str,
    candidate: SchedulerCandidate,
    lease: OwnershipLease,
) -> ConflictTelemetry:
    return ConflictTelemetry(
        conflict_id=_stable_id("conflict", run_id, candidate.candidate_id, lease.lease_id, "lease_overlap"),
        run_id=run_id,
        left_candidate_id=candidate.candidate_id,
        right_candidate_id=lease.lease_id,
        left_node_id=candidate.node_ids[0] if candidate.node_ids else "",
        conflict_type="lease_overlap",
        severity="serialized",
        paths=sorted(set([*candidate.paths, *_paths(target_path, lease.paths)])),
        detail=f"Active {lease.mode} lease {lease.lease_id} overlaps candidate ownership.",
    )


def _selected_group(
    *,
    run_id: str,
    selected: SchedulerCandidate,
    max_fanout: int,
) -> ExecutionGroup:
    action_kind = {
        "launch_work": "work_wave",
        "launch_scope_work": "scope_wave",
        "run_validation": "validation_group",
        "integrate": "integration_gate",
        "create_repair_work": "repair_unblocker",
        "create_setup_work": "repair_unblocker",
        "idle_complete": "idle",
    }[selected.action_kind]
    return ExecutionGroup(
        group_id=_stable_id("group", run_id, selected.candidate_id, ",".join(selected.node_ids), ",".join(selected.ticket_ids)),
        run_id=run_id,
        action_kind=action_kind,  # type: ignore[arg-type]
        execution_mode=selected.execution_mode,
        owner_role=selected.owner_role,
        candidate_ids=[selected.candidate_id],
        node_ids=selected.node_ids,
        ticket_ids=selected.ticket_ids,
        paths=selected.paths,
        max_fanout=max_fanout,
        reason=selected.reason,
        telemetry=selected.telemetry,
    )


def _validation_group(run_id: str, group: ExecutionGroup, selected: SchedulerCandidate) -> ValidationGroup | None:
    if selected.action_kind not in {"launch_work", "launch_scope_work", "run_validation"}:
        return None
    gate = ValidationGate(
        gate_id=_stable_id("validation-gate", run_id, group.group_id, ",".join(selected.paths)),
        run_id=run_id,
        group_id=group.group_id,
        node_ids=selected.node_ids,
        paths=selected.paths,
        commands=[],
        required=selected.action_kind != "launch_scope_work",
        status="pending",
        failure_policy="repair" if selected.action_kind != "launch_scope_work" else "alternate_validation",
        payload={"scoped": True, "execution_mode": selected.execution_mode},
    )
    return ValidationGroup(
        validation_group_id=_stable_id("validation-group", run_id, group.group_id),
        run_id=run_id,
        group_id=group.group_id,
        gates=[gate],
        paths=selected.paths,
        payload={"candidate_id": selected.candidate_id},
    )


def _integration_decision(run_id: str, group: ExecutionGroup, selected: SchedulerCandidate) -> IntegrationDecision | None:
    if selected.action_kind not in {"launch_work", "integrate"}:
        return None
    return IntegrationDecision(
        decision_id=_stable_id("integration", run_id, group.group_id),
        run_id=run_id,
        group_id=group.group_id,
        status="apply_serially" if selected.action_kind == "integrate" else "queued",
        reason="Integration applies serialized when ownership overlaps; this group is queued for gate review.",
        paths=selected.paths,
        validation_group_ids=[group.validation_group_id] if group.validation_group_id else [],
        payload={"candidate_id": selected.candidate_id, "fanout": selected.fanout},
    )


def _repair_work_for_candidate(run_id: str, selected: SchedulerCandidate) -> list[RepairUnblockerWork]:
    if selected.action_kind not in {"create_repair_work", "create_setup_work"}:
        return []
    source_kind = "parser" if selected.telemetry.get("parser_unavailable") else "validation"
    action_type = "index_code_facts" if selected.telemetry.get("parser_unavailable") else ("setup" if selected.action_kind == "create_setup_work" else "repair")
    title = "Refresh parser/index support for scheduler ownership facts" if action_type == "index_code_facts" else selected.reason
    return [
        RepairUnblockerWork(
            work_id=_stable_id("repair", run_id, selected.candidate_id),
            run_id=run_id,
            source_kind=source_kind,  # type: ignore[arg-type]
            source_id=selected.node_ids[0] if selected.node_ids else selected.candidate_id,
            action_type=action_type,  # type: ignore[arg-type]
            title=title,
            node_ids=selected.node_ids,
            paths=selected.paths,
            reason=selected.reason,
            payload=selected.telemetry,
        )
    ]


def choose_scheduler_record(
    *,
    target_path: Path,
    run_id: str,
    tickets: list[TicketRecord],
    dag_nodes: list[DagNode],
    validation_receipts: list[ValidationReceipt],
    dag_edges: list[DagEdge] | None = None,
    ownership_leases: list[OwnershipLease] | None = None,
    code_facts: list[CodeFact] | None = None,
    max_fanout: int = 3,
    min_write_confidence: float = DEFAULT_MIN_WRITE_CONFIDENCE,
    fact_ttl: timedelta = DEFAULT_FACT_TTL,
) -> SchedulerRecord:
    """Choose the next useful work without freezing on ordinary uncertainty."""

    target_path = target_path.expanduser().resolve()
    now = datetime.now(timezone.utc)
    configured_fanout = max(1, min(32, max_fanout))
    dag_edges = dag_edges or []
    ownership_leases = ownership_leases or []
    code_facts = code_facts or []
    facts_by_path = _fact_index(target_path, code_facts)
    active_leases, stale_leases = _active_and_stale_leases(ownership_leases, now)
    active_scope_ticket_ids = {
        str(lease.payload.get("ticket_id") or "").strip()
        for lease in active_leases
        if lease.mode == "read" and str(lease.payload.get("action_kind") or "") == "launch_scope_work"
    }
    active_scope_ticket_ids.discard("")

    candidates: list[SchedulerCandidate] = []
    conflicts: list[ConflictTelemetry] = []
    parser_fallback_paths = sorted(
        {
            _path_key(target_path, fact.file_path)
            for fact in code_facts
            if fact.kind == "parser_unavailable"
        }
    )
    stale_fact_paths = sorted(
        {
            _path_key(target_path, fact.file_path)
            for fact in code_facts
            if fact.extracted_at < now - fact_ttl
        }
    )

    failed_required = [
        receipt
        for receipt in validation_receipts
        if receipt.required and receipt.status == "failed"
    ]
    failed_optional = [
        receipt
        for receipt in validation_receipts
        if not receipt.required and receipt.status == "failed"
    ]
    if failed_required:
        node_ids = sorted({receipt.node_id for receipt in failed_required if receipt.node_id})
        candidates.append(
            SchedulerCandidate(
                candidate_id=_candidate_id(run_id, "repair-validation"),
                action_kind="create_repair_work",
                execution_mode="repair",
                owner_role="builder",
                node_ids=node_ids,
                reason="Required validation failed; create repair/setup/harness work.",
                fanout=1,
                telemetry={"failed_required_receipts": [receipt.receipt_id for receipt in failed_required]},
            )
        )

    nodes_by_id = {node.node_id: node for node in dag_nodes}
    ready_nodes = [
        node
        for node in dag_nodes
        if node.status == "ready" and _deps_satisfied(node, nodes_by_id, dag_edges)
    ]
    node_candidates: list[SchedulerCandidate] = []
    for node in ready_nodes:
        node_paths = _paths(target_path, node.paths)
        facts = _facts_for_paths(facts_by_path, node_paths)
        candidate = _candidate_from_node(
            target_path=target_path,
            run_id=run_id,
            node=node,
            facts=facts,
            min_write_confidence=min_write_confidence,
        )
        node_candidates.append(candidate)

    selected_wave: list[SchedulerCandidate] = []
    active_lease_blocked_candidate_ids: set[str] = set()
    for candidate in node_candidates:
        if candidate.action_kind not in {"launch_work", "run_validation", "integrate"}:
            continue
        if selected_wave and candidate.action_kind != selected_wave[0].action_kind:
            conflicts.append(
                _conflict(
                    run_id=run_id,
                    left=selected_wave[0],
                    right=candidate,
                    conflict_type="validation_gate",
                    detail="Different execution phases run in separate scheduler groups.",
                )
            )
            continue
        lease_overlap = next(
            (
                lease
                for lease in active_leases
                if lease.mode != "read" and _overlaps(_paths(target_path, lease.paths), candidate.paths)
            ),
            None,
        )
        if lease_overlap is not None:
            conflicts.append(_lease_conflict(target_path=target_path, run_id=run_id, candidate=candidate, lease=lease_overlap))
            active_lease_blocked_candidate_ids.add(candidate.candidate_id)
            continue
        if stale_fact_paths and _overlaps(stale_fact_paths, candidate.paths) and selected_wave:
            conflicts.append(
                _conflict(
                    run_id=run_id,
                    left=selected_wave[0],
                    right=candidate,
                    conflict_type="stale_code_facts",
                    detail="Stale code facts reduce fanout; candidate can run in a later cycle after fact refresh.",
                )
            )
            continue
        blocked_by_selected = False
        for selected in selected_wave:
            if _overlaps(selected.paths, candidate.paths):
                conflicts.append(
                    _conflict(
                        run_id=run_id,
                        left=selected,
                        right=candidate,
                        conflict_type="path_overlap",
                        detail="Ownership paths overlap, so these candidates are serialized.",
                        severity="serialized",
                    )
                )
                blocked_by_selected = True
                break
            conflict_type, detail = _fact_conflict(target_path, selected, candidate, facts_by_path)
            if conflict_type:
                conflicts.append(
                    _conflict(
                        run_id=run_id,
                        left=selected,
                        right=candidate,
                        conflict_type=conflict_type,
                        detail=detail,
                    )
                )
                blocked_by_selected = True
                break
        if blocked_by_selected:
            continue
        selected_wave.append(candidate)

    if selected_wave:
        candidates.extend(
            candidate
            for candidate in node_candidates
            if candidate.action_kind in {"create_setup_work", "launch_scope_work"}
        )
        node_ids = [node_id for candidate in selected_wave for node_id in candidate.node_ids]
        ticket_ids = [ticket_id for candidate in selected_wave for ticket_id in candidate.ticket_ids]
        paths = [path for candidate in selected_wave for path in candidate.paths]
        action_kind = selected_wave[0].action_kind
        selected = SchedulerCandidate(
            candidate_id=_candidate_id(run_id, "ready-wave"),
            action_kind=action_kind,  # type: ignore[arg-type]
            execution_mode=selected_wave[0].execution_mode,
            owner_role=selected_wave[0].owner_role,
            node_ids=node_ids,
            ticket_ids=ticket_ids,
            paths=paths,
            scope_evidence=[evidence for candidate in selected_wave for evidence in candidate.scope_evidence],
            code_fact_refs=[fact_id for candidate in selected_wave for fact_id in candidate.code_fact_refs],
            required_lease_ids=[lease_id for candidate in selected_wave for lease_id in candidate.required_lease_ids],
            reason="Ready DAG nodes have non-overlapping ownership scopes for this safe wave.",
            fanout=len(selected_wave),
            confidence=min(candidate.confidence for candidate in selected_wave),
            telemetry={
                "wave_candidate_ids": [candidate.candidate_id for candidate in selected_wave],
                "configured_max_fanout": configured_fanout,
            },
        )
        candidates.append(selected)
    else:
        candidates.extend(
            candidate
            for candidate in node_candidates
            if candidate.candidate_id not in active_lease_blocked_candidate_ids
        )

    ready_tickets = [
        ticket
        for ticket in tickets
        if ticket.status in {"ready", "blocked", "waiting"}
        and ticket.ticket_id not in active_scope_ticket_ids
        and all(
            any(done.ticket_id == dependency and done.status == "done" for done in tickets)
            for dependency in ticket.depends_on
        )
    ]

    ready_scope_candidates: list[SchedulerCandidate] = []
    if ready_tickets and not any(candidate.action_kind in {"launch_work", "run_validation", "integrate"} for candidate in candidates):
        for ticket in ready_tickets:
            if ticket.status != "ready":
                continue
            ready_scope_candidates.append(
                SchedulerCandidate(
                    candidate_id=_candidate_id(run_id, f"ticket-{ticket.ticket_id}"),
                    action_kind="launch_scope_work",
                    execution_mode="read_only_scope",
                    owner_role="builder",
                    node_ids=[],
                    ticket_ids=[ticket.ticket_id],
                    paths=_paths(target_path, ticket.ownership_paths),
                    reason="Dependency-ready ticket needs scoped DAG work before write fanout.",
                    fanout=1,
                    telemetry={"ticket_scope_candidate": True},
                )
            )
        if ready_scope_candidates:
            selected_ticket_scopes = ready_scope_candidates
            candidates.extend(ready_scope_candidates)
            candidates.append(
                SchedulerCandidate(
                    candidate_id=_candidate_id(run_id, "ticket-scope-wave"),
                    action_kind="launch_scope_work",
                    execution_mode="read_only_scope",
                    owner_role="builder",
                    node_ids=[],
                    ticket_ids=[ticket_id for candidate in selected_ticket_scopes for ticket_id in candidate.ticket_ids],
                    paths=_dedupe(path for candidate in selected_ticket_scopes for path in candidate.paths),
                    reason="Dependency-ready tickets can be scoped in parallel before write fanout.",
                    fanout=len(selected_ticket_scopes),
                    confidence=min(candidate.confidence for candidate in selected_ticket_scopes),
                    telemetry={
                        "ticket_scope_wave": True,
                        "wave_candidate_ids": [candidate.candidate_id for candidate in selected_ticket_scopes],
                        "configured_max_fanout": configured_fanout,
                    },
                )
            )

    if ready_tickets and not any(
        candidate.action_kind in {"create_repair_work", "launch_work", "run_validation", "integrate", "launch_scope_work"}
        for candidate in candidates
    ):
        ticket = next((item for item in ready_tickets if item.status in {"blocked", "waiting"}), ready_tickets[0])
        candidates.append(
            SchedulerCandidate(
                candidate_id=_candidate_id(run_id, f"ticket-{ticket.ticket_id}"),
                action_kind="create_setup_work",
                execution_mode="setup",
                owner_role="builder",
                node_ids=[],
                ticket_ids=[ticket.ticket_id],
                paths=_paths(target_path, ticket.ownership_paths),
                reason="Ticket is blocked or waiting; create setup/mock/defer/split work.",
                fanout=1,
            )
        )

    if not candidates:
        candidates.append(
            SchedulerCandidate(
                candidate_id=_candidate_id(run_id, "idle-complete"),
                action_kind="idle_complete",
                execution_mode="idle",
                owner_role="scheduler",
                reason="No ready tickets, failed required validation, or ready DAG nodes remain.",
                fanout=0,
            )
        )

    priority = {
        "create_repair_work": 0,
        "launch_work": 1,
        "run_validation": 1,
        "integrate": 1,
        "launch_scope_work": 2,
        "create_setup_work": 3,
        "idle_complete": 9,
    }
    selected = sorted(candidates, key=lambda candidate: (priority[candidate.action_kind], -candidate.fanout, candidate.candidate_id))[0]
    group = _selected_group(run_id=run_id, selected=selected, max_fanout=configured_fanout)
    validation_group = _validation_group(run_id, group, selected)
    if validation_group is not None:
        group.validation_group_id = validation_group.validation_group_id
    integration_decision = _integration_decision(run_id, group, selected)
    if integration_decision is not None:
        group.integration_decision_id = integration_decision.decision_id
    for conflict in conflicts:
        conflict.group_id = group.group_id
    reduced_reasons = sorted({conflict.conflict_type for conflict in conflicts})
    telemetry = SchedulerTelemetry(
        telemetry_id=_stable_id("scheduler-telemetry", run_id, group.group_id),
        run_id=run_id,
        selected_group_id=group.group_id,
        candidate_count=len(candidates),
        selected_count=selected.fanout,
        max_fanout=configured_fanout,
        reduced_fanout_reasons=reduced_reasons,
        parser_fallbacks=parser_fallback_paths,
        stale_lease_ids=[lease.lease_id for lease in stale_leases],
        conflict_ids=[conflict.conflict_id for conflict in conflicts],
        payload={
            "failed_optional_receipts": [receipt.receipt_id for receipt in failed_optional],
            "stale_fact_paths": stale_fact_paths,
        },
    )
    return SchedulerRecord(
        decision_id=f"decision:{run_id}:{int(now.timestamp())}",
        target_path=str(target_path),
        run_id=run_id,
        selected=selected,
        candidates=candidates,
        execution_group=group,
        validation_group=validation_group,
        integration_decision=integration_decision,
        repair_work=_repair_work_for_candidate(run_id, selected),
        conflicts=conflicts,
        scheduler_telemetry=telemetry,
        telemetry={
            "tickets": len(tickets),
            "dag_nodes": len(dag_nodes),
            "validation_receipts": len(validation_receipts),
            "ready_dag_nodes": len(ready_nodes),
            "max_fanout": configured_fanout,
            "active_leases": len(active_leases),
            "stale_leases": len(stale_leases),
            "code_facts": len(code_facts),
            "parser_fallbacks": len(parser_fallback_paths),
            "failed_optional_validation": len(failed_optional),
        },
    )
