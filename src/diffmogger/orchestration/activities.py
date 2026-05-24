"""Temporal activities for local Diffmogger automation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from temporalio import activity

from diffmogger.contracts import (
    CodeFact,
    DagEdge,
    DagNode,
    ExecutionGroup,
    OwnershipLease,
    RepairUnblockerWork,
    SchedulerCycleRequest,
    SchedulerCycleResult,
    TicketRecord,
    ValidationReceipt,
    ValidationGroup,
    WorkerOutput,
    json_ready,
)
from diffmogger.orchestration.scheduler_policy import choose_scheduler_record
from diffmogger.runtime import code_facts as code_fact_extractor
from diffmogger.runtime.paths import existing_or_target_path
from diffmogger.state.db import (
    connect,
    database_path_for_target,
    persist_scheduler_record,
    rows_as_payloads,
    upsert_code_fact,
    upsert_dag_node,
    upsert_execution_group,
    upsert_ownership_lease,
    upsert_repair_unblocker_work,
    upsert_ticket,
    upsert_validation_group,
    upsert_worker_output,
)


def _payload_models(conn: sqlite3.Connection, table: str, order_by: str, model: type[Any]) -> list[Any]:
    values: list[Any] = []
    for payload in rows_as_payloads(conn, table, order_by):
        try:
            values.append(model.model_validate(payload))
        except Exception:
            continue
    return values


def _seed_default_ticket(conn: sqlite3.Connection, request: SchedulerCycleRequest) -> None:
    existing = int(conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0])
    if existing:
        return
    upsert_ticket(
        conn,
        TicketRecord(
            ticket_id="default-local-cycle",
            title="Run one local scheduler cycle",
            ownership_paths=[".diffmogger/runtime"],
            payload={"source": "temporal_activity_seed", "run_id": request.run_id},
        ),
    )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone() is not None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _json_cell(value: Any, default: Any) -> Any:
    try:
        data = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return default
    return data


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _ticket_status_from_item(value: Any) -> str:
    status = str(value or "pending").strip().lower().replace("-", "_")
    if status == "done":
        return "done"
    if status == "blocked":
        return "blocked"
    if status in {"in_progress", "candidate_done", "running"}:
        return "running"
    if status in {"deferred", "waiting"}:
        return "waiting"
    return "ready"


def _preserve_runtime_ticket_status(existing: TicketRecord | None, mapped_status: str) -> str:
    if existing is None:
        return mapped_status
    if existing.status in {"running", "done", "deferred"}:
        return existing.status
    if existing.status == "blocked" and mapped_status == "ready":
        return existing.status
    return mapped_status


def _sync_ticket_run_items(conn: sqlite3.Connection, request: SchedulerCycleRequest) -> None:
    if not _table_exists(conn, "ticket_items"):
        return
    rows = conn.execute(
        """
        SELECT ticket_id, run_id, position, summary, status, blocker, updated_at, payload_json
        FROM ticket_items
        ORDER BY position ASC, ticket_id ASC
        """
    ).fetchall()
    if not rows:
        return
    existing = {
        ticket.ticket_id: ticket
        for ticket in _payload_models(conn, "tickets", "ticket_id", TicketRecord)
    }
    known_statuses = {ticket_id: ticket.status for ticket_id, ticket in existing.items()}
    now = datetime.now(timezone.utc)
    for row in rows:
        payload = _json_cell(row["payload_json"], {})
        payload = payload if isinstance(payload, dict) else {}
        ticket_id = str(row["ticket_id"] or payload.get("id") or "").strip()
        if not ticket_id:
            continue
        title = _short_text(row["summary"] or payload.get("summary") or f"Ticket {ticket_id}", limit=160)
        mapped_status = _ticket_status_from_item(row["status"] or payload.get("status"))
        current = existing.get(ticket_id)
        ownership_paths = _text_list(payload.get("ownership_paths") or payload.get("paths")) or ["."]
        depends_on = _text_list(payload.get("depends_on"))
        if mapped_status == "ready" and depends_on and not all(known_statuses.get(dependency) == "done" for dependency in depends_on):
            mapped_status = "waiting"
        status = _preserve_runtime_ticket_status(current, mapped_status)
        ticket_payload = dict(current.payload) if current is not None else {}
        ticket_payload.update(
            {
                "source": "ticket_run_item",
                "ticket_run_id": str(row["run_id"] or ""),
                "run_id": request.run_id,
                "position": int(row["position"] or 0),
                "blocker": str(row["blocker"] or payload.get("blocker") or ""),
                "ticket_item_status": str(row["status"] or payload.get("status") or ""),
                "ticket_item_updated_at": str(row["updated_at"] or ""),
                "ticket_item": payload,
            }
        )
        upsert_ticket(
            conn,
            TicketRecord(
                ticket_id=ticket_id,
                title=title,
                status=status,  # type: ignore[arg-type]
                depends_on=depends_on,
                ownership_paths=ownership_paths,
                evidence=list(current.evidence) if current is not None else _text_list(payload.get("evidence")),
                payload=ticket_payload,
                updated_at=current.updated_at if current is not None else now,
            ),
        )
        known_statuses[ticket_id] = status


def _campaign_state_for_target(target: Path) -> dict[str, Any]:
    dashboard = _load_json(existing_or_target_path(target, ".agentic/dashboard_state.json"))
    intake = _load_json(existing_or_target_path(target, ".agentic/project_intake.json"))
    draft = dashboard.get("brief_draft_intake")
    if not isinstance(draft, dict):
        draft = {}
    return {**intake, **dashboard, **draft}


def _campaign_mode(state: dict[str, Any]) -> str:
    raw = state.get("campaign_mode", state.get("automation_run_mode"))
    text = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text == "ticket_campaign":
        return "bounded"
    if text == "continuous_improvement":
        return "ongoing"
    return text if text in {"bounded", "ongoing"} else ""


def _short_text(value: Any, *, limit: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _slug(value: Any, *, fallback: str = "item") -> str:
    text = str(value or "").strip().lower()
    chars = [ch if ch.isalnum() else "-" for ch in text]
    slug = "-".join("".join(chars).split("-"))
    return slug or fallback


def _ongoing_ticket_title(state: dict[str, Any]) -> str:
    demo = _short_text(state.get("desired_first_demo"), limit=72)
    if demo:
        return f"Build next demo slice: {demo}"
    goal = _short_text(state.get("product_goal"), limit=72)
    if goal:
        return f"Advance next product slice: {goal}"
    return "Draft and implement the next safe project milestone"


def _ongoing_ticket_paths(target: Path) -> list[str]:
    for rel in ("src", "app", "lib", "packages", "docs", "README.md"):
        if (target / rel).exists():
            return [rel]
    return ["."]


def _ongoing_ticket_id(tickets: list[TicketRecord]) -> str:
    existing = [
        ticket
        for ticket in tickets
        if ticket.payload.get("source") == "ongoing_campaign_draft" or ticket.ticket_id.startswith("ongoing-ticket-")
    ]
    return f"ongoing-ticket-{len(existing) + 1:03d}"


def _stable_runtime_id(prefix: str, *parts: object) -> str:
    raw = ":".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _scope_follow_up_node(nodes: list[DagNode], ticket_id: str) -> DagNode | None:
    for node in nodes:
        if node.ticket_id == ticket_id and node.payload.get("source") == "scope_follow_up":
            return node
    return None


def _ensure_scope_follow_up_node(
    conn: sqlite3.Connection,
    *,
    ticket: TicketRecord,
    paths: list[str],
    owner_role: str,
    group_id: str,
    run_id: str,
    now: datetime,
) -> DagNode:
    nodes = _payload_models(conn, "execution_dag_nodes", "node_id", DagNode)
    existing = _scope_follow_up_node(nodes, ticket.ticket_id)
    if existing is not None:
        return existing
    node = DagNode(
        node_id=_stable_runtime_id("node", ticket.ticket_id, "scope-follow-up"),
        ticket_id=ticket.ticket_id,
        action_type="build",
        status="ready",
        owner_role=owner_role or "builder",
        paths=paths or ticket.ownership_paths or ["."],
        summary=f"Implement scoped follow-up for ticket: {ticket.title}",
        confidence=0.75,
        payload={
            "source": "scope_follow_up",
            "scoped_group_id": group_id,
            "created_from_run_id": run_id,
            "ticket_title": ticket.title,
            "ticket_source": ticket.payload.get("source", ""),
        },
        updated_at=now,
    )
    upsert_dag_node(conn, node)
    conn.execute(
        """
        INSERT INTO runtime_events(event_type, actor, payload_json, created_at)
        VALUES('campaign.scope_follow_up_created', 'orchestration.local', ?, ?)
        """,
        (
            json.dumps(
                {
                    "run_id": run_id,
                    "ticket_id": ticket.ticket_id,
                    "node_id": node.node_id,
                    "paths": node.paths,
                    "source": "scope_follow_up",
                },
                sort_keys=True,
            ),
            now.isoformat(),
        ),
    )
    return node


def _owned_paths_from_scope_outputs(value: Any) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    if isinstance(value, dict):
        output = value.get("output")
        if isinstance(output, dict):
            payload = output.get("payload") if isinstance(output.get("payload"), dict) else {}
            input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
            ticket_id = str(input_payload.get("ticket_id") or payload.get("ticket_id") or "").strip()
            paths = _text_list(payload.get("owned_paths"))
            status = str(payload.get("owned_paths_status") or "").strip()
            detail = str(payload.get("owned_paths_detail") or "").strip()
            if ticket_id and (paths or status):
                results[ticket_id] = {"paths": paths, "status": status, "detail": detail}
        for item in value.values():
            results.update(_owned_paths_from_scope_outputs(item))
    elif isinstance(value, list):
        for item in value:
            results.update(_owned_paths_from_scope_outputs(item))
    return results


def _ensure_scoped_running_ticket_followups(
    conn: sqlite3.Connection,
    tickets: list[TicketRecord],
    nodes: list[DagNode],
    request: SchedulerCycleRequest,
) -> list[DagNode]:
    created: list[DagNode] = []
    now = datetime.now(timezone.utc)
    for ticket in tickets:
        if ticket.status != "running" or ticket.payload.get("last_action_kind") != "launch_scope_work":
            continue
        existing = _scope_follow_up_node([*nodes, *created], ticket.ticket_id)
        if existing is not None:
            if not ticket.payload.get("follow_up_node_id"):
                payload = dict(ticket.payload)
                payload["follow_up_node_id"] = existing.node_id
                upsert_ticket(conn, ticket.model_copy(update={"payload": payload, "updated_at": now}))
            continue
        node = _ensure_scope_follow_up_node(
            conn,
            ticket=ticket,
            paths=ticket.ownership_paths,
            owner_role="builder",
            group_id=str(ticket.payload.get("last_execution_group_id") or ""),
            run_id=request.run_id,
            now=now,
        )
        payload = dict(ticket.payload)
        payload["follow_up_node_id"] = node.node_id
        payload["follow_up_node_recovered_at"] = now.isoformat()
        upsert_ticket(conn, ticket.model_copy(update={"payload": payload, "updated_at": now}))
        created.append(node)
    return created


def _has_active_runtime_work(
    tickets: list[TicketRecord],
    nodes: list[DagNode],
    receipts: list[ValidationReceipt],
) -> bool:
    if any(ticket.status in {"ready", "running", "blocked", "waiting"} for ticket in tickets):
        return True
    if any(node.status in {"ready", "running", "waiting"} for node in nodes):
        return True
    return any(receipt.required and receipt.status == "failed" for receipt in receipts)


def _maybe_draft_ongoing_ticket(
    conn: sqlite3.Connection,
    target: Path,
    request: SchedulerCycleRequest,
    tickets: list[TicketRecord],
    nodes: list[DagNode],
    receipts: list[ValidationReceipt],
) -> TicketRecord | None:
    state = _campaign_state_for_target(target)
    if _campaign_mode(state) != "ongoing":
        return None
    if _has_active_runtime_work(tickets, nodes, receipts):
        return None

    now = datetime.now(timezone.utc)
    ticket = TicketRecord(
        ticket_id=_ongoing_ticket_id(tickets),
        title=_ongoing_ticket_title(state),
        ownership_paths=_ongoing_ticket_paths(target),
        payload={
            "source": "ongoing_campaign_draft",
            "run_id": request.run_id,
            "campaign_mode": "ongoing",
            "created_at": now.isoformat(),
            "project_name": _short_text(state.get("project_name") or target.name, limit=80),
            "product_goal": _short_text(state.get("product_goal"), limit=240),
            "desired_first_demo": _short_text(state.get("desired_first_demo"), limit=240),
            "instructions": [
                "Choose the smallest reversible project improvement from the current intake and runtime state.",
                "Create or update local verification for the change whenever practical.",
                "Record evidence before moving the ticket to done.",
            ],
        },
        updated_at=now,
    )
    upsert_ticket(conn, ticket)
    conn.execute(
        """
        INSERT INTO runtime_events(event_type, actor, payload_json, created_at)
        VALUES('campaign.ticket_drafted', 'orchestration.local', ?, ?)
        """,
        (
            json.dumps(
                {
                    "run_id": request.run_id,
                    "ticket_id": ticket.ticket_id,
                    "title": ticket.title,
                    "ownership_paths": ticket.ownership_paths,
                    "source": "ongoing_campaign_draft",
                },
                sort_keys=True,
            ),
            now.isoformat(),
        ),
    )
    return ticket


def _candidate_paths(target: Path, tickets: list[TicketRecord], nodes: list[DagNode]) -> list[Path]:
    raw_paths: list[str] = []
    for node in nodes:
        if node.status == "ready":
            raw_paths.extend(node.paths)
    for ticket in tickets:
        if ticket.status in {"ready", "blocked", "waiting"}:
            raw_paths.extend(ticket.ownership_paths)
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_paths:
        value = str(raw or "").strip()
        if not value:
            continue
        path = Path(value)
        resolved = path if path.is_absolute() else target / path
        try:
            resolved = resolved.resolve()
        except OSError:
            continue
        if resolved not in seen and resolved.exists():
            seen.add(resolved)
            paths.append(resolved)
    return paths[:128]


def _refresh_code_facts(conn: sqlite3.Connection, target: Path, paths: list[Path]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for path in paths:
        if path.is_file():
            facts.extend(code_fact_extractor.facts_for_file(path))
        elif path.is_dir():
            facts.extend(code_fact_extractor.facts_for_tree(path, limit=500))
    for fact in facts:
        upsert_code_fact(conn, fact)
    return facts


def _acquire_group_leases(conn: sqlite3.Connection, decision, request: SchedulerCycleRequest) -> None:
    selected = decision.selected
    group = decision.execution_group
    if group is None or selected.execution_mode not in {"write", "read_only_scope", "integrate", "validate"}:
        return
    target = Path(request.target_path).expanduser().resolve()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    mode = (
        "integrate"
        if selected.execution_mode == "integrate"
        else "validate"
        if selected.execution_mode == "validate"
        else "read"
        if selected.execution_mode == "read_only_scope"
        else "write"
    )
    selected_payload = selected.model_dump(mode="json") if hasattr(selected, "model_dump") else json_ready(selected)
    worker_items = _worker_items_for_selected(target, selected_payload)
    if not worker_items:
        worker_items = [{"node_id": "", "ticket_id": "", "paths": selected.paths or ["."]}]
    for item_index, item in enumerate(worker_items):
        node_id = str(item.get("node_id") or "")
        ticket_id = str(item.get("ticket_id") or "")
        item_paths = _text_list(item.get("paths")) or selected.paths or ["."]
        for path in item_paths:
            lease_id = _stable_runtime_id("lease", request.run_id, group.group_id, node_id or ticket_id or item_index, path)
            upsert_ownership_lease(
                conn,
                OwnershipLease(
                    lease_id=lease_id,
                    owner=selected.owner_role,
                    run_id=request.run_id,
                    group_id=group.group_id,
                    node_id=node_id,
                    paths=[path],
                    mode=mode,  # type: ignore[arg-type]
                    acquired_at=now,
                    expires_at=expires,
                    payload={
                        "candidate_id": selected.candidate_id,
                        "action_kind": selected.action_kind,
                        "source": "scheduler_cycle",
                        "ticket_id": ticket_id,
                        "item_index": item_index,
                    },
                ),
            )


def _mark_selected_items_started(conn: sqlite3.Connection, decision, request: SchedulerCycleRequest) -> None:
    selected = decision.selected
    group = decision.execution_group
    if group is None or selected.action_kind not in {"launch_work", "launch_scope_work"}:
        return
    now = datetime.now(timezone.utc)
    nodes_by_id = {node.node_id: node for node in _payload_models(conn, "execution_dag_nodes", "node_id", DagNode)}
    tickets_by_id = {ticket.ticket_id: ticket for ticket in _payload_models(conn, "tickets", "ticket_id", TicketRecord)}
    for node_id in selected.node_ids:
        node = nodes_by_id.get(node_id)
        if node is None:
            continue
        payload = dict(node.payload)
        payload["active_execution_group_id"] = group.group_id
        payload["active_action_kind"] = selected.action_kind
        payload["active_started_at"] = now.isoformat()
        upsert_dag_node(conn, node.model_copy(update={"status": "running", "payload": payload, "updated_at": now}))
        if node.ticket_id and selected.action_kind == "launch_work":
            ticket = tickets_by_id.get(node.ticket_id)
            if ticket is not None and ticket.status != "done":
                ticket_payload = dict(ticket.payload)
                ticket_payload["active_execution_group_id"] = group.group_id
                ticket_payload["active_action_kind"] = selected.action_kind
                ticket_payload["active_started_at"] = now.isoformat()
                upsert_ticket(conn, ticket.model_copy(update={"status": "running", "payload": ticket_payload, "updated_at": now}))
    if selected.action_kind == "launch_scope_work":
        for ticket_id in selected.ticket_ids:
            ticket = tickets_by_id.get(ticket_id)
            if ticket is None or ticket.status == "done":
                continue
            payload = dict(ticket.payload)
            payload["active_execution_group_id"] = group.group_id
            payload["active_action_kind"] = selected.action_kind
            payload["active_started_at"] = now.isoformat()
            upsert_ticket(conn, ticket.model_copy(update={"payload": payload, "updated_at": now}))


def _release_group_leases(conn: sqlite3.Connection, group_id: str, now: datetime) -> list[str]:
    if not group_id:
        return []
    released: list[str] = []
    rows = conn.execute(
        """
        SELECT lease_id, payload_json
        FROM ownership_leases
        WHERE group_id = ? AND status = 'active'
        """,
        (group_id,),
    ).fetchall()
    for row in rows:
        payload = _json_cell(row["payload_json"], {})
        payload = payload if isinstance(payload, dict) else {}
        nested = payload.get("payload")
        if not isinstance(nested, dict):
            nested = {}
        nested["released_at"] = now.isoformat()
        nested["release_reason"] = "execution_group_terminal"
        payload["payload"] = nested
        payload["status"] = "released"
        conn.execute(
            """
            UPDATE ownership_leases
            SET status = 'released', payload_json = ?, updated_at = datetime('now')
            WHERE lease_id = ? AND status = 'active'
            """,
            (json.dumps(payload, sort_keys=True, default=str), str(row["lease_id"] or "")),
        )
        released.append(str(row["lease_id"] or ""))
    return released


def _release_item_leases(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    node_id: str,
    ticket_id: str,
    now: datetime,
) -> list[str]:
    if not group_id:
        return []
    released: list[str] = []
    rows = conn.execute(
        """
        SELECT lease_id, node_id, payload_json
        FROM ownership_leases
        WHERE group_id = ? AND status = 'active'
        """,
        (group_id,),
    ).fetchall()
    for row in rows:
        row_node_id = str(row["node_id"] or "")
        payload = _json_cell(row["payload_json"], {})
        payload = payload if isinstance(payload, dict) else {}
        nested = payload.get("payload")
        if not isinstance(nested, dict):
            nested = {}
        row_ticket_id = str(nested.get("ticket_id") or "").strip()
        if node_id:
            if row_node_id != node_id:
                continue
        elif ticket_id:
            if row_ticket_id != ticket_id:
                continue
        else:
            continue
        nested["released_at"] = now.isoformat()
        nested["release_reason"] = "worker_item_terminal"
        payload["payload"] = nested
        payload["status"] = "released"
        conn.execute(
            """
            UPDATE ownership_leases
            SET status = 'released', payload_json = ?, updated_at = datetime('now')
            WHERE lease_id = ? AND status = 'active'
            """,
            (json.dumps(payload, sort_keys=True, default=str), str(row["lease_id"] or "")),
        )
        released.append(str(row["lease_id"] or ""))
    return released


def _worker_identity_from_result(worker_result: dict[str, Any]) -> tuple[str, str]:
    output = worker_result.get("output") if isinstance(worker_result.get("output"), dict) else {}
    payload = output.get("payload") if isinstance(output.get("payload"), dict) else {}
    input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    node_id = str(output.get("node_id") or input_payload.get("node_id") or "").strip()
    ticket_id = str(input_payload.get("ticket_id") or payload.get("ticket_id") or "").strip()
    return node_id, ticket_id


def _is_material_changed_path(value: Any) -> bool:
    path = str(value or "").strip().replace("\\", "/")
    if not path or path in {".", "./"}:
        return False
    return not (
        path == ".DS_Store"
        or path.startswith(".git/")
        or path.startswith(".diffmogger/")
        or path.startswith("target/")
    )


def _git_changed_paths(target: Path) -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=target,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        raw = line[3:] if len(line) > 3 else line
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        raw = raw.strip()
        if raw:
            paths.add(raw)
    return paths


def _tail_text(path: Path, *, limit: int = 4000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _target_rel_path(target: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(target.resolve()).as_posix()
    except ValueError:
        return str(path)


OWNERSHIP_PATHS_PREFIX = "OWNERSHIP_PATHS_JSON:"


def _parse_owned_paths_from_text(text: str) -> tuple[list[str], str, str]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(OWNERSHIP_PATHS_PREFIX):
            continue
        raw_value = stripped[len(OWNERSHIP_PATHS_PREFIX) :].strip()
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            return [], "invalid", f"invalid JSON: {exc.msg}"
        if not isinstance(parsed, list):
            return [], "invalid", "ownership paths JSON must be a list"
        paths = _text_list(parsed)
        if not paths:
            return [], "invalid", "ownership paths JSON list is empty"
        return paths, "parsed", ""
    return [], "missing", f"scope report did not include {OWNERSHIP_PATHS_PREFIX}"


def _parse_owned_paths_from_report(path: Path) -> tuple[list[str], str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], "missing_report", f"{exc.__class__.__name__}: {exc}"
    return _parse_owned_paths_from_text(text)


def _load_ticket(conn: sqlite3.Connection, ticket_id: str) -> TicketRecord | None:
    row = conn.execute("SELECT payload_json FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if row is None:
        return None
    try:
        return TicketRecord.model_validate(json.loads(row["payload_json"] or "{}"))
    except Exception:
        return None


def _load_dag_node(conn: sqlite3.Connection, node_id: str) -> DagNode | None:
    row = conn.execute("SELECT payload_json FROM execution_dag_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if row is None:
        return None
    try:
        return DagNode.model_validate(json.loads(row["payload_json"] or "{}"))
    except Exception:
        return None


def _selected_ticket_and_node(
    conn: sqlite3.Connection,
    *,
    ticket_id: str,
    node_id: str,
) -> tuple[TicketRecord | None, DagNode | None]:
    ticket = None
    node = None
    if ticket_id:
        ticket = _load_ticket(conn, ticket_id)
    if node_id:
        node = _load_dag_node(conn, node_id)
    return ticket, node


def _worker_items_for_selected(target: Path, selected: dict[str, Any]) -> list[dict[str, Any]]:
    node_ids = _text_list(selected.get("node_ids"))
    ticket_ids = _text_list(selected.get("ticket_ids"))
    selected_paths = _text_list(selected.get("paths"))
    items: list[dict[str, Any]] = []
    with connect(target) as conn:
        if node_ids:
            for index, node_id in enumerate(node_ids):
                node = _load_dag_node(conn, node_id)
                ticket_id = node.ticket_id if node is not None and node.ticket_id else (ticket_ids[index] if index < len(ticket_ids) else "")
                paths = list(node.paths) if node is not None and node.paths else ([selected_paths[index]] if index < len(selected_paths) else selected_paths)
                items.append({"node_id": node_id, "ticket_id": ticket_id, "paths": paths})
            return items
        if ticket_ids:
            for ticket_id in ticket_ids:
                ticket = _load_ticket(conn, ticket_id)
                paths = list(ticket.ownership_paths) if ticket is not None and ticket.ownership_paths else selected_paths
                items.append({"node_id": "", "ticket_id": ticket_id, "paths": paths})
            return items
    return [{"node_id": "", "ticket_id": "", "paths": selected_paths}]


def _worker_assignment_prompt(
    *,
    target: Path,
    run_id: str,
    ticket: TicketRecord | None,
    node: DagNode | None,
    paths: list[str],
    mode: str,
    report_path: Path,
) -> str:
    ticket_payload = ticket.payload if ticket is not None else {}
    ticket_item = ticket_payload.get("ticket_item") if isinstance(ticket_payload.get("ticket_item"), dict) else {}
    criteria = ticket_item.get("acceptance_criteria") if isinstance(ticket_item.get("acceptance_criteria"), list) else []
    verification = ticket_item.get("verification_commands") if isinstance(ticket_item.get("verification_commands"), list) else []
    lines = [
        f"Target project: {target}",
        f"Run id: {run_id}",
        f"Ticket id: {ticket.ticket_id if ticket else ''}",
        f"Ticket title: {ticket.title if ticket else node.summary if node else 'Automation work item'}",
        f"Node id: {node.node_id if node else ''}",
        f"Node summary: {node.summary if node else ''}",
        f"Owned paths: {', '.join(paths or ['.'])}",
        f"Report path: {report_path}",
        "",
    ]
    if criteria:
        lines.append("Acceptance criteria:")
        lines.extend(f"- {item}" for item in criteria if str(item).strip())
        lines.append("")
    if verification:
        lines.append("Suggested verification:")
        lines.extend(f"- {item}" for item in verification if str(item).strip())
        lines.append("")
    if mode == "write":
        lines.extend(
            [
                "Implement this ticket by creating or updating actual target project files.",
                "Do not count a report-only change as implementation.",
                "Keep the change minimal, reusable, and within the owned paths unless the existing project layout requires a nearby config/test file.",
                "Run lightweight local checks when practical and include the commands/results in the report.",
            ]
        )
    else:
        lines.extend(
            [
                "Inspect the target and write a concise scoping report for the implementation worker.",
                "Do not modify product/source files during this scoping pass.",
                "Name concrete files or directories the implementation worker should own.",
                f'Include exactly one machine-readable ownership line: {OWNERSHIP_PATHS_PREFIX} ["path/or/dir", "..."]',
            ]
        )
    return "\n".join(lines).strip()


def _stub_worker_result(
    *,
    target: Path | None,
    run_id: str,
    group_id: str,
    node_id: str,
    ticket_id: str = "",
    paths: list[str],
    mode: str,
) -> dict[str, Any]:
    success_stub = os.environ.get("DIFFMOGGER_WORKER_EXECUTION", "").strip().lower() in {
        "stub-success",
        "stub_success",
        "test-success",
    }
    is_write = mode == "write"
    ok = bool(success_stub or not is_write)
    status = "completed" if ok else "failed"
    changed_paths = ["stub-output.txt"] if ok and is_write else [".diffmogger/runtime"]
    output = WorkerOutput(
        output_id=f"worker-output:{run_id}:{group_id or 'group'}:{node_id or ticket_id or 'node'}",
        run_id=run_id,
        group_id=group_id,
        node_id=node_id,
        worker_id="temporal-local-stub",
        status=status,  # type: ignore[arg-type]
        changed_paths=changed_paths,
        summary=(
            "Test stub recorded material worker output."
            if success_stub
            else "No real Codex worker was enabled; implementation was not completed."
            if is_write
            else "Local stub recorded read-only scope output."
        ),
        payload={
            "mode": "test_stub_success" if success_stub else "stub_no_material_work",
            "input": {"paths": paths, "target_path": str(target or ""), "ticket_id": ticket_id},
            "ticket_id": ticket_id,
            "owned_paths": paths if not is_write else [],
            "owned_paths_status": "parsed" if paths and not is_write else ("missing" if not is_write else "not_applicable"),
            "owned_paths_detail": "",
        },
    )
    if target is not None:
        with connect(target) as conn:
            with conn:
                upsert_worker_output(conn, output)
    return {
        "ok": ok,
        "activity": "execute_role_work",
        "output": json_ready(output),
        "mode": output.payload["mode"],
        "failure_reason": "" if ok else "real worker execution is not enabled and the stub produced no material file changes",
    }


async def _run_worker_command(
    command: list[str],
    *,
    cwd: Path,
    activity_log_path: Path,
    timeout: int,
) -> tuple[int, str]:
    try:
        with activity_log_path.open("ab") as activity_log:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                stdout=activity_log,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                return_code = await asyncio.wait_for(process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return 124, f"worker helper timed out after {timeout} seconds"
            return int(return_code), ""
    except Exception as exc:
        return 1, f"{exc.__class__.__name__}: {exc}"


@activity.defn
async def run_scheduler_cycle(payload: dict[str, Any]) -> dict[str, Any]:
    request = SchedulerCycleRequest.model_validate(payload)
    target = Path(request.target_path).expanduser().resolve()
    evidence: list[str] = []
    with connect(target) as conn:
        with conn:
            _sync_ticket_run_items(conn, request)
            _seed_default_ticket(conn, request)
            tickets = _payload_models(conn, "tickets", "ticket_id", TicketRecord)
            nodes = _payload_models(conn, "execution_dag_nodes", "node_id", DagNode)
            edges = _payload_models(conn, "execution_dag_edges", "edge_id", DagEdge)
            receipts = _payload_models(conn, "validation_receipts", "recorded_at", ValidationReceipt)
            leases = _payload_models(conn, "ownership_leases", "lease_id", OwnershipLease)
            drafted_ticket = _maybe_draft_ongoing_ticket(conn, target, request, tickets, nodes, receipts)
            if drafted_ticket is not None:
                tickets = [*tickets, drafted_ticket]
            follow_up_nodes = _ensure_scoped_running_ticket_followups(conn, tickets, nodes, request)
            if follow_up_nodes:
                nodes = [*nodes, *follow_up_nodes]
            refreshed_facts = _refresh_code_facts(conn, target, _candidate_paths(target, tickets, nodes))
            persisted_facts = _payload_models(conn, "code_facts", "file_path, fact_id", CodeFact)
            facts = persisted_facts or refreshed_facts
            decision = choose_scheduler_record(
                target_path=target,
                run_id=request.run_id,
                tickets=tickets,
                dag_nodes=nodes,
                dag_edges=edges,
                validation_receipts=receipts,
                ownership_leases=leases,
                code_facts=facts,
                max_fanout=request.max_fanout,
            )
            persist_scheduler_record(conn, decision)
            if not request.dry_run and decision.execution_group is not None:
                upsert_execution_group(
                    conn,
                    decision.execution_group.model_copy(update={"status": "running", "updated_at": datetime.now(timezone.utc)}),
                )
            if not request.dry_run:
                _acquire_group_leases(conn, decision, request)
                _mark_selected_items_started(conn, decision, request)
            evidence.append(f"sqlite:{database_path_for_target(target)}")
            evidence.append(f"scheduler_decision:{decision.decision_id}")
            if decision.execution_group is not None:
                evidence.append(f"execution_group:{decision.execution_group.group_id}")
    return json_ready(SchedulerCycleResult(run_id=request.run_id, decision=decision, evidence=evidence))


def _follow_up_ok(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("ok") is False:
            return False
        return all(_follow_up_ok(item) for item in value.values())
    if isinstance(value, list):
        return all(_follow_up_ok(item) for item in value)
    return True


def _follow_up_evidence(value: Any) -> list[str]:
    evidence: list[str] = []
    if isinstance(value, dict):
        output = value.get("output")
        if isinstance(output, dict) and output.get("output_id"):
            evidence.append(f"worker_output:{output['output_id']}")
        validation = value.get("validation_group")
        if isinstance(validation, dict) and validation.get("validation_group_id"):
            evidence.append(f"validation_group:{validation['validation_group_id']}")
        for item in value.values():
            evidence.extend(_follow_up_evidence(item))
    elif isinstance(value, list):
        for item in value:
            evidence.extend(_follow_up_evidence(item))
    seen: set[str] = set()
    deduped: list[str] = []
    for item in evidence:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _follow_up_failure_reason(value: Any) -> str:
    if isinstance(value, dict):
        reason = str(value.get("failure_reason") or value.get("reason") or "").strip()
        if reason:
            return reason
        output = value.get("output")
        if isinstance(output, dict):
            payload = output.get("payload") if isinstance(output.get("payload"), dict) else {}
            reason = str(payload.get("failure_reason") or output.get("summary") or "").strip()
            if reason:
                return reason
        for item in value.values():
            reason = _follow_up_failure_reason(item)
            if reason:
                return reason
    elif isinstance(value, list):
        for item in value:
            reason = _follow_up_failure_reason(item)
            if reason:
                return reason
    return ""


def _mark_follow_up_recorded(target: Path, cycle: dict[str, Any], follow_up: dict[str, Any]) -> None:
    result = SchedulerCycleResult.model_validate(cycle)
    selected = result.decision.selected
    group = result.decision.execution_group
    now = datetime.now(timezone.utc)
    ok = _follow_up_ok(follow_up)
    evidence = _follow_up_evidence(follow_up)
    status = "completed" if ok else "failed"
    owned_paths_by_ticket = _owned_paths_from_scope_outputs(follow_up)
    with connect(target) as conn:
        with conn:
            released_lease_ids: list[str] = []
            nodes_by_id = {node.node_id: node for node in _payload_models(conn, "execution_dag_nodes", "node_id", DagNode)}
            selected_node_by_ticket: dict[str, str] = {}
            for index, node_id in enumerate(selected.node_ids):
                node = nodes_by_id.get(node_id)
                ticket_id = node.ticket_id if node is not None and node.ticket_id else (selected.ticket_ids[index] if index < len(selected.ticket_ids) else "")
                if ticket_id:
                    selected_node_by_ticket[ticket_id] = node_id
            if group is not None:
                updated_group = group.model_copy(update={"status": status, "updated_at": now})
                upsert_execution_group(conn, updated_group)
                if status in {"completed", "failed"}:
                    released_lease_ids = _release_group_leases(conn, group.group_id, now)
            if ok and selected.node_ids:
                for index, node_id in enumerate(selected.node_ids):
                    node_paths = [selected.paths[index]] if index < len(selected.paths) else selected.paths
                    node = nodes_by_id.get(node_id) or DagNode(
                        node_id=node_id,
                        ticket_id=selected.ticket_ids[index] if index < len(selected.ticket_ids) else "",
                        action_type="build",
                        owner_role=selected.owner_role,
                        paths=node_paths,
                    )
                    upsert_dag_node(conn, node.model_copy(update={"status": "done", "updated_at": now}))
            if ok and selected.ticket_ids:
                tickets_by_id = {ticket.ticket_id: ticket for ticket in _payload_models(conn, "tickets", "ticket_id", TicketRecord)}
                for ticket_id in selected.ticket_ids:
                    ticket = tickets_by_id.get(ticket_id)
                    if ticket is None:
                        continue
                    payload = dict(ticket.payload)
                    payload["last_execution_group_id"] = group.group_id if group else ""
                    payload["last_action_kind"] = selected.action_kind
                    payload["last_completed_at"] = now.isoformat()
                    if released_lease_ids:
                        payload["released_lease_ids"] = released_lease_ids
                    new_evidence = [*ticket.evidence, *evidence]
                    ticket_status = "done"
                    if ticket.payload.get("source") != "temporal_activity_seed" and selected.action_kind in {
                        "launch_scope_work",
                        "create_setup_work",
                        "create_repair_work",
                        "run_validation",
                    }:
                        ticket_status = "running"
                    if ok and ticket_status == "running" and selected.action_kind == "launch_scope_work":
                        owned = owned_paths_by_ticket.get(ticket_id, {})
                        owned_paths = _text_list(owned.get("paths"))
                        owned_status = str(owned.get("status") or "missing").strip()
                        owned_detail = str(owned.get("detail") or "").strip()
                        follow_up_paths = owned_paths or ticket.ownership_paths or selected.paths or ["."]
                        follow_up_node = _ensure_scope_follow_up_node(
                            conn,
                            ticket=ticket,
                            paths=follow_up_paths,
                            owner_role=selected.owner_role,
                            group_id=group.group_id if group else "",
                            run_id=result.run_id,
                            now=now,
                        )
                        payload["follow_up_node_id"] = follow_up_node.node_id
                        payload["scope_owned_paths"] = follow_up_paths
                        payload["scope_owned_paths_status"] = owned_status
                        if owned_detail:
                            payload["scope_owned_paths_detail"] = owned_detail
                    if ok and selected.action_kind == "launch_work" and selected.node_ids:
                        build_node_id = selected_node_by_ticket.get(ticket_id, selected.node_ids[0])
                        payload["follow_up_node_id"] = build_node_id
                        payload["last_build_node_id"] = build_node_id
                    upsert_ticket(
                        conn,
                        ticket.model_copy(
                            update={
                                "status": ticket_status,
                                "evidence": list(dict.fromkeys(new_evidence)),
                                "payload": payload,
                                "updated_at": now,
                            }
                        ),
                    )
            elif not ok and selected.ticket_ids:
                reason = _follow_up_failure_reason(follow_up) or "worker follow-up failed or produced no material implementation evidence"
                tickets_by_id = {ticket.ticket_id: ticket for ticket in _payload_models(conn, "tickets", "ticket_id", TicketRecord)}
                for ticket_id in selected.ticket_ids:
                    ticket = tickets_by_id.get(ticket_id)
                    if ticket is None:
                        continue
                    payload = dict(ticket.payload)
                    payload["last_execution_group_id"] = group.group_id if group else ""
                    payload["last_action_kind"] = selected.action_kind
                    payload["last_failed_at"] = now.isoformat()
                    payload["failure_reason"] = reason
                    if released_lease_ids:
                        payload["released_lease_ids"] = released_lease_ids
                    upsert_ticket(
                        conn,
                        ticket.model_copy(
                            update={
                                "status": "blocked",
                                "evidence": list(dict.fromkeys([*ticket.evidence, *evidence])),
                                "payload": payload,
                                "updated_at": now,
                            }
                        ),
                    )
            conn.execute(
                """
                INSERT INTO runtime_events(event_type, actor, payload_json, created_at)
                VALUES('campaign.follow_up_recorded', 'orchestration.local', ?, ?)
                """,
                (
                    json.dumps(
                        {
                            "run_id": result.run_id,
                            "decision_id": result.decision.decision_id,
                            "group_id": group.group_id if group else "",
                            "selected_action_kind": selected.action_kind,
                            "status": status,
                            "evidence": evidence,
                            "released_lease_ids": released_lease_ids,
                            "failure_reason": "" if ok else _follow_up_failure_reason(follow_up),
                        },
                        sort_keys=True,
                    ),
                    now.isoformat(),
                ),
            )


def _mark_worker_follow_up_recorded(target: Path, cycle: dict[str, Any], worker_result: dict[str, Any]) -> None:
    result = SchedulerCycleResult.model_validate(cycle)
    selected = result.decision.selected
    group = result.decision.execution_group
    now = datetime.now(timezone.utc)
    ok = _follow_up_ok(worker_result)
    evidence = _follow_up_evidence(worker_result)
    node_id, ticket_id = _worker_identity_from_result(worker_result)
    owned_paths_by_ticket = _owned_paths_from_scope_outputs(worker_result)
    with connect(target) as conn:
        with conn:
            released_lease_ids = _release_item_leases(
                conn,
                group_id=group.group_id if group else "",
                node_id=node_id,
                ticket_id=ticket_id,
                now=now,
            )
            nodes_by_id = {node.node_id: node for node in _payload_models(conn, "execution_dag_nodes", "node_id", DagNode)}
            if node_id:
                node = nodes_by_id.get(node_id)
                if node is not None:
                    payload = dict(node.payload)
                    payload["last_execution_group_id"] = group.group_id if group else ""
                    payload["last_action_kind"] = selected.action_kind
                    if ok:
                        payload["last_completed_at"] = now.isoformat()
                        node_status = "done"
                    else:
                        payload["last_failed_at"] = now.isoformat()
                        payload["failure_reason"] = _follow_up_failure_reason(worker_result)
                        node_status = "failed"
                    upsert_dag_node(conn, node.model_copy(update={"status": node_status, "payload": payload, "updated_at": now}))
                    if not ticket_id:
                        ticket_id = node.ticket_id

            if ticket_id:
                ticket = _load_ticket(conn, ticket_id)
                if ticket is not None:
                    payload = dict(ticket.payload)
                    payload["last_execution_group_id"] = group.group_id if group else ""
                    payload["last_action_kind"] = selected.action_kind
                    if released_lease_ids:
                        existing_released = _text_list(payload.get("released_lease_ids"))
                        payload["released_lease_ids"] = list(dict.fromkeys([*existing_released, *released_lease_ids]))
                    new_evidence = list(dict.fromkeys([*ticket.evidence, *evidence]))
                    if ok:
                        payload["last_completed_at"] = now.isoformat()
                        ticket_status = "done"
                        if ticket.payload.get("source") != "temporal_activity_seed" and selected.action_kind in {
                            "launch_scope_work",
                            "create_setup_work",
                            "create_repair_work",
                            "run_validation",
                        }:
                            ticket_status = "running"
                        if ticket_status == "running" and selected.action_kind == "launch_scope_work":
                            owned = owned_paths_by_ticket.get(ticket_id, {})
                            owned_paths = _text_list(owned.get("paths"))
                            owned_status = str(owned.get("status") or "missing").strip()
                            owned_detail = str(owned.get("detail") or "").strip()
                            follow_up_paths = owned_paths or ticket.ownership_paths or selected.paths or ["."]
                            follow_up_node = _ensure_scope_follow_up_node(
                                conn,
                                ticket=ticket,
                                paths=follow_up_paths,
                                owner_role=selected.owner_role,
                                group_id=group.group_id if group else "",
                                run_id=result.run_id,
                                now=now,
                            )
                            payload["follow_up_node_id"] = follow_up_node.node_id
                            payload["scope_owned_paths"] = follow_up_paths
                            payload["scope_owned_paths_status"] = owned_status
                            if owned_detail:
                                payload["scope_owned_paths_detail"] = owned_detail
                        if selected.action_kind == "launch_work" and node_id:
                            payload["follow_up_node_id"] = node_id
                            payload["last_build_node_id"] = node_id
                    else:
                        ticket_status = "blocked"
                        payload["last_failed_at"] = now.isoformat()
                        payload["failure_reason"] = (
                            _follow_up_failure_reason(worker_result)
                            or "worker follow-up failed or produced no material implementation evidence"
                        )
                    upsert_ticket(
                        conn,
                        ticket.model_copy(
                            update={
                                "status": ticket_status,  # type: ignore[arg-type]
                                "evidence": new_evidence,
                                "payload": payload,
                                "updated_at": now,
                            }
                        ),
                    )
            conn.execute(
                """
                INSERT INTO runtime_events(event_type, actor, payload_json, created_at)
                VALUES('campaign.worker_item_recorded', 'orchestration.local', ?, ?)
                """,
                (
                    json.dumps(
                        {
                            "run_id": result.run_id,
                            "decision_id": result.decision.decision_id,
                            "group_id": group.group_id if group else "",
                            "node_id": node_id,
                            "ticket_id": ticket_id,
                            "selected_action_kind": selected.action_kind,
                            "status": "completed" if ok else "failed",
                            "evidence": evidence,
                            "released_lease_ids": released_lease_ids,
                            "failure_reason": "" if ok else _follow_up_failure_reason(worker_result),
                        },
                        sort_keys=True,
                    ),
                    now.isoformat(),
                ),
            )


def _mark_execution_group_terminal(target: Path, cycle: dict[str, Any], follow_up: dict[str, Any]) -> None:
    result = SchedulerCycleResult.model_validate(cycle)
    group = result.decision.execution_group
    if group is None:
        return
    now = datetime.now(timezone.utc)
    ok = _follow_up_ok(follow_up)
    status = "completed" if ok else "failed"
    with connect(target) as conn:
        with conn:
            released_lease_ids = _release_group_leases(conn, group.group_id, now)
            upsert_execution_group(conn, group.model_copy(update={"status": status, "updated_at": now}))
            conn.execute(
                """
                INSERT INTO runtime_events(event_type, actor, payload_json, created_at)
                VALUES('campaign.execution_group_terminal', 'orchestration.local', ?, ?)
                """,
                (
                    json.dumps(
                        {
                            "run_id": result.run_id,
                            "decision_id": result.decision.decision_id,
                            "group_id": group.group_id,
                            "selected_action_kind": result.decision.selected.action_kind,
                            "status": status,
                            "released_lease_ids": released_lease_ids,
                            "failure_reason": "" if ok else _follow_up_failure_reason(follow_up),
                        },
                        sort_keys=True,
                    ),
                    now.isoformat(),
                ),
            )


def _has_backfill_ready_work(target: Path) -> bool:
    with connect(target) as conn:
        tickets = _payload_models(conn, "tickets", "ticket_id", TicketRecord)
        nodes = _payload_models(conn, "execution_dag_nodes", "node_id", DagNode)
    done_ticket_ids = {ticket.ticket_id for ticket in tickets if ticket.status == "done"}
    if any(
        ticket.status in {"ready", "blocked", "waiting"} and all(dependency in done_ticket_ids for dependency in ticket.depends_on)
        for ticket in tickets
    ):
        return True
    return any(node.status == "ready" for node in nodes)


async def run_campaign_cycle(payload: dict[str, Any]) -> dict[str, Any]:
    request = SchedulerCycleRequest.model_validate(payload).model_copy(update={"dry_run": False})
    target = Path(request.target_path).expanduser().resolve()
    active_tasks: dict[asyncio.Task[dict[str, Any]], dict[str, Any]] = {}
    group_states: dict[str, dict[str, Any]] = {}
    cycles: list[dict[str, Any]] = []
    worker_results: list[dict[str, Any]] = []
    validation_results: list[dict[str, Any]] = []
    integration_results: list[dict[str, Any]] = []

    async def launch_cycle() -> bool:
        cycle = await run_scheduler_cycle(request.model_dump(mode="json"))
        cycles.append(cycle)
        selected = cycle.get("decision", {}).get("selected", {}) if isinstance(cycle.get("decision"), dict) else {}
        decision = cycle.get("decision", {}) if isinstance(cycle.get("decision"), dict) else {}
        group = decision.get("execution_group", {}) if isinstance(decision.get("execution_group"), dict) else {}
        validation_group = decision.get("validation_group", {}) if isinstance(decision.get("validation_group"), dict) else {}
        action_kind = selected.get("action_kind")
        follow_payload = {
            **request.model_dump(mode="json"),
            "group_id": group.get("group_id", ""),
            "validation_group_id": validation_group.get("validation_group_id", ""),
        }
        if action_kind in {"launch_work", "launch_scope_work"}:
            worker_items = _worker_items_for_selected(target, selected)
            group_id = str(group.get("group_id") or "")
            group_states[group_id] = {
                "cycle": cycle,
                "selected": selected,
                "follow_payload": follow_payload,
                "pending": len(worker_items),
                "workers": [],
                "ok": True,
            }
            for item in worker_items:
                task = asyncio.create_task(
                    execute_role_work(
                        {
                            **follow_payload,
                            "node_id": item["node_id"],
                            "ticket_id": item["ticket_id"],
                            "paths": item["paths"],
                        }
                    )
                )
                active_tasks[task] = {"cycle": cycle, "group_id": group_id}
            return bool(worker_items)
        if action_kind in {"create_repair_work", "create_setup_work"}:
            follow_up = await create_repair_or_unblocker_work(
                {**follow_payload, "repair_work": decision.get("repair_work", [])}
            )
        elif action_kind == "integrate":
            follow_up = await integrate_ready_work({**follow_payload, "paths": selected.get("paths", [])})
        elif action_kind == "run_validation":
            follow_up = await run_validation_group({**follow_payload, "paths": selected.get("paths", [])})
        elif action_kind == "idle_complete":
            follow_up = {"ok": True, "activity": "idle_complete", "status": "idle"}
        else:
            follow_up = {"ok": True, "activity": "unknown", "status": "noop"}
        _mark_follow_up_recorded(target, cycle, follow_up)
        return action_kind != "idle_complete"

    await launch_cycle()
    while active_tasks:
        done, _pending = await asyncio.wait(active_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            meta = active_tasks.pop(task)
            try:
                worker_result = task.result()
            except Exception as exc:
                worker_result = {
                    "ok": False,
                    "activity": "execute_role_work",
                    "status": "failed",
                    "failure_reason": f"{exc.__class__.__name__}: {exc}",
                }
            worker_results.append(worker_result)
            _mark_worker_follow_up_recorded(target, meta["cycle"], worker_result)
            group_state = group_states.get(str(meta.get("group_id") or ""))
            if group_state is None:
                continue
            group_state["workers"].append(worker_result)
            group_state["pending"] = max(0, int(group_state["pending"]) - 1)
            group_state["ok"] = bool(group_state["ok"]) and _follow_up_ok(worker_result)
            if group_state["pending"] == 0:
                selected = group_state["selected"]
                follow_payload = group_state["follow_payload"]
                group_follow_payload = {**follow_payload, "paths": selected.get("paths", [])}
                validation_result = await run_validation_group(group_follow_payload)
                validation_results.append(validation_result)
                group_follow_up: dict[str, Any] = {
                    "workers": group_state["workers"],
                    "validation": validation_result,
                }
                if selected.get("action_kind") == "launch_work":
                    integration_result = await integrate_ready_work(group_follow_payload)
                    integration_results.append(integration_result)
                    group_follow_up["integration"] = integration_result
                _mark_execution_group_terminal(target, group_state["cycle"], group_follow_up)
        if active_tasks and _has_backfill_ready_work(target):
            await launch_cycle()

    follow_up: dict[str, Any] = {"workers": worker_results}
    if validation_results:
        follow_up["validation"] = validation_results[0] if len(validation_results) == 1 else validation_results
    if integration_results:
        follow_up["integration"] = integration_results[0] if len(integration_results) == 1 else integration_results
    if len(cycles) > 1:
        follow_up["backfill_cycles"] = cycles[1:]
    first_cycle = cycles[0] if cycles else {"run_id": request.run_id}
    return {"ok": True, "cycle": first_cycle, "follow_up": follow_up}


@activity.defn
async def record_follow_up_completion(payload: dict[str, Any]) -> dict[str, Any]:
    target_value = payload.get("target_path") or payload.get("target")
    cycle = payload.get("cycle") if isinstance(payload.get("cycle"), dict) else {}
    follow_up = payload.get("follow_up") if isinstance(payload.get("follow_up"), dict) else {}
    if not target_value:
        return {"ok": False, "activity": "record_follow_up_completion", "status": "missing_target"}
    _mark_follow_up_recorded(Path(str(target_value)).expanduser().resolve(), cycle, follow_up)
    return {"ok": True, "activity": "record_follow_up_completion", "status": "recorded"}


@activity.defn
async def execute_role_work(payload: dict[str, Any]) -> dict[str, Any]:
    target_value = payload.get("target_path") or payload.get("target")
    run_id = str(payload.get("run_id") or "local-run")
    group_id = str(payload.get("group_id") or "")
    node_id = str(payload.get("node_id") or "")
    ticket_id = str(payload.get("ticket_id") or "").strip()
    paths = [str(item) for item in payload.get("paths", []) if str(item).strip()]
    target = Path(str(target_value)).expanduser().resolve() if target_value else None
    mode = "write" if node_id else "read-only"
    execution_mode = os.environ.get("DIFFMOGGER_WORKER_EXECUTION", "").strip().lower()
    if execution_mode not in {"codex", "codex-cli", "codex_cli"}:
        return _stub_worker_result(
            target=target,
            run_id=run_id,
            group_id=group_id,
            node_id=node_id,
            ticket_id=ticket_id,
            paths=paths,
            mode=mode,
        )
    if target is None:
        return {"ok": False, "activity": "execute_role_work", "status": "missing_target", "failure_reason": "target_path is required"}

    report_dir = target / ".diffmogger" / "runtime" / "agent_runs" / _slug(run_id, fallback="run")
    role_slug = _slug(f"{'builder' if mode == 'write' else 'planner'}-{node_id or ticket_id or group_id}", fallback=mode)
    report_path = report_dir / f"{role_slug}.md"
    activity_log_path = report_dir / f"{role_slug}.activity.log"
    helper_path = existing_or_target_path(target, "scripts/spawn_worker_agent.sh")
    with connect(target) as conn:
        if node_id and not ticket_id:
            node_row = conn.execute("SELECT ticket_id FROM execution_dag_nodes WHERE node_id = ?", (node_id,)).fetchone()
            ticket_id = str(node_row["ticket_id"] or "") if node_row is not None else ""
        if not ticket_id:
            group_row = conn.execute("SELECT ticket_ids_json FROM execution_groups WHERE group_id = ?", (group_id,)).fetchone()
            if group_row is not None:
                ticket_ids = _json_cell(group_row["ticket_ids_json"], [])
                if isinstance(ticket_ids, list) and ticket_ids:
                    ticket_id = str(ticket_ids[0] or "")
        ticket, node = _selected_ticket_and_node(conn, ticket_id=ticket_id, node_id=node_id)

    before_paths = _git_changed_paths(target)
    assignment = _worker_assignment_prompt(
        target=target,
        run_id=run_id,
        ticket=ticket,
        node=node,
        paths=paths or (node.paths if node is not None else ticket.ownership_paths if ticket is not None else ["."]),
        mode=mode,
        report_path=report_path,
    )
    command = [
        "bash",
        str(helper_path),
        "--target",
        str(target),
        "--run-id",
        run_id,
        "--role",
        role_slug,
        "--report-path",
        str(report_path),
        "--prompt",
        assignment,
    ]
    if mode == "write":
        command.extend(["--write", "--ownership", ", ".join(paths or ["."])])
    else:
        command.append("--read-only")
    timeout = int(os.environ.get("DIFFMOGGER_CODEX_WORKER_TIMEOUT_SECONDS") or "7200")
    report_dir.mkdir(parents=True, exist_ok=True)
    return_code, failure_reason = await _run_worker_command(
        command,
        cwd=target,
        activity_log_path=activity_log_path,
        timeout=timeout,
    )
    after_paths = _git_changed_paths(target)
    new_or_changed = sorted(path for path in (after_paths - before_paths) if _is_material_changed_path(path))
    current_material = sorted(path for path in after_paths if _is_material_changed_path(path))
    material_paths = new_or_changed or current_material
    report_exists = report_path.exists()
    if return_code == 127:
        status = "failed"
        failure_reason = "Codex CLI worker unavailable"
    elif return_code != 0:
        status = "failed"
        failure_reason = failure_reason or f"worker helper exited with code {return_code}"
    elif mode == "write" and not material_paths:
        status = "failed"
        failure_reason = "write worker completed without material project file changes"
    elif mode != "write" and not report_exists:
        status = "failed"
        failure_reason = "read-only worker completed without writing a report"
    else:
        status = "completed"
    changed_paths = material_paths if mode == "write" else [_target_rel_path(target, report_path)]
    owned_paths: list[str] = []
    owned_status = "not_applicable"
    owned_detail = ""
    if mode != "write":
        owned_paths, owned_status, owned_detail = _parse_owned_paths_from_report(report_path)
    output = WorkerOutput(
        output_id=f"worker-output:{run_id}:{group_id or 'group'}:{node_id or ticket_id or 'node'}",
        run_id=run_id,
        group_id=group_id,
        node_id=node_id,
        worker_id=str(payload.get("worker_id") or "codex-cli-worker"),
        status=status,  # type: ignore[arg-type]
        changed_paths=changed_paths,
        summary="Codex worker completed material project changes." if status == "completed" and mode == "write" else "Codex worker completed scope report." if status == "completed" else failure_reason,
        payload={
            "mode": "codex_cli_worker",
            "worker_mode": mode,
            "ticket_id": ticket_id,
            "input": dict(payload),
            "command": command,
            "report_path": _target_rel_path(target, report_path),
            "activity_log_path": _target_rel_path(target, activity_log_path),
            "return_code": return_code,
            "stdout_tail": _tail_text(activity_log_path),
            "stderr_tail": "",
            "material_changed_paths": material_paths,
            "failure_reason": failure_reason,
            "owned_paths": owned_paths,
            "owned_paths_status": owned_status,
            "owned_paths_detail": owned_detail,
        },
    )
    with connect(target) as conn:
        with conn:
            upsert_worker_output(conn, output)
    return {
        "ok": status == "completed",
        "activity": "execute_role_work",
        "output": json_ready(output),
        "mode": "codex_cli_worker",
        "failure_reason": failure_reason,
    }


@activity.defn
async def run_validation_group(payload: dict[str, Any]) -> dict[str, Any]:
    target_value = payload.get("target_path") or payload.get("target")
    run_id = str(payload.get("run_id") or "local-run")
    group = ValidationGroup(
        validation_group_id=str(payload.get("validation_group_id") or f"validation-group:{run_id}:local"),
        run_id=run_id,
        group_id=str(payload.get("group_id") or ""),
        status="deferred",
        paths=[str(item) for item in payload.get("paths", []) if str(item).strip()],
        payload={"status": "deferred_until_command", "input": dict(payload)},
    )
    if target_value:
        with connect(Path(str(target_value)).expanduser().resolve()) as conn:
            with conn:
                upsert_validation_group(conn, group)
    return {"ok": True, "activity": "run_validation_group", "validation_group": json_ready(group), "status": "deferred_until_command"}


@activity.defn
async def integrate_ready_work(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "activity": "integrate_ready_work", "payload": dict(payload), "serialized": True}


@activity.defn
async def create_repair_or_unblocker_work(payload: dict[str, Any]) -> dict[str, Any]:
    target_value = payload.get("target_path") or payload.get("target")
    run_id = str(payload.get("run_id") or "local-run")
    raw_items = payload.get("repair_work")
    items = raw_items if isinstance(raw_items, list) else [raw_items] if isinstance(raw_items, dict) else []
    created: list[RepairUnblockerWork] = []
    for index, item in enumerate(items or [{}], start=1):
        if isinstance(item, RepairUnblockerWork):
            work = item
        elif isinstance(item, dict) and item:
            work = RepairUnblockerWork.model_validate(item)
        else:
            work = RepairUnblockerWork(
                work_id=f"repair:{run_id}:{index}",
                run_id=run_id,
                source_kind="scheduler",
                action_type="repair",
                title="Create scheduler unblocker work",
                reason="Scheduler requested repair/unblocker generation.",
                payload={"input": dict(payload)},
            )
        created.append(work)
    if target_value:
        with connect(Path(str(target_value)).expanduser().resolve()) as conn:
            with conn:
                for work in created:
                    upsert_repair_unblocker_work(conn, work)
    return {"ok": True, "activity": "create_repair_or_unblocker_work", "created": [json_ready(item) for item in created]}


ACTIVITIES = [
    run_scheduler_cycle,
    execute_role_work,
    run_validation_group,
    integrate_ready_work,
    create_repair_or_unblocker_work,
    record_follow_up_completion,
]
