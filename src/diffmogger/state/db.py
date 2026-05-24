"""SQLite read-model helpers with Alembic-owned schema migration."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from alembic import command
from alembic.config import Config

from diffmogger.contracts import (
    CodeFact,
    ConflictTelemetry,
    DagEdge,
    DagNode,
    ExecutionGroup,
    IntegrationDecision,
    OwnershipLease,
    RepairUnblockerWork,
    SchedulerRecord,
    SchedulerTelemetry,
    TicketRecord,
    ValidationGroup,
    ValidationReceipt,
    WorkerOutput,
    json_ready,
)
from diffmogger.runtime.paths import target_path


MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"


def database_path_for_target(target: Path) -> Path:
    path = target_path(target.expanduser().resolve(), "target/orchestration.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def sqlite_url(path: Path) -> str:
    return "sqlite:///" + str(path.expanduser().resolve())


def alembic_config(path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATION_DIR))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(path))
    return cfg


def migrate(path_or_target: Path) -> Path:
    path = path_or_target
    if path.suffix != ".sqlite3":
        path = database_path_for_target(path_or_target)
    path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(path), "head")
    return path


@contextmanager
def connect(target: Path) -> Iterator[sqlite3.Connection]:
    path = migrate(target)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _upsert_json(conn: sqlite3.Connection, table: str, key_column: str, key: str, payload: dict[str, Any]) -> None:
    conn.execute(
        f"""
        INSERT INTO {table}({key_column}, payload_json, updated_at)
        VALUES(?, ?, datetime('now'))
        ON CONFLICT({key_column}) DO UPDATE SET
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (key, stable_json(payload)),
    )


def upsert_ticket(conn: sqlite3.Connection, ticket: TicketRecord) -> None:
    payload = json_ready(ticket)
    conn.execute(
        """
        INSERT INTO tickets(ticket_id, title, status, depends_on_json, ownership_paths_json, payload_json, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticket_id) DO UPDATE SET
          title=excluded.title,
          status=excluded.status,
          depends_on_json=excluded.depends_on_json,
          ownership_paths_json=excluded.ownership_paths_json,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            ticket.ticket_id,
            ticket.title,
            ticket.status,
            stable_json(ticket.depends_on),
            stable_json(ticket.ownership_paths),
            stable_json(payload),
            ticket.updated_at.isoformat(),
        ),
    )


def upsert_dag_node(conn: sqlite3.Connection, node: DagNode) -> None:
    payload = json_ready(node)
    conn.execute(
        """
        INSERT INTO execution_dag_nodes(
          node_id, ticket_id, action_type, status, owner_role, paths_json, summary,
          confidence, payload_json, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
          ticket_id=excluded.ticket_id,
          action_type=excluded.action_type,
          status=excluded.status,
          owner_role=excluded.owner_role,
          paths_json=excluded.paths_json,
          summary=excluded.summary,
          confidence=excluded.confidence,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            node.node_id,
            node.ticket_id,
            node.action_type,
            node.status,
            node.owner_role,
            stable_json(node.paths),
            node.summary,
            node.confidence,
            stable_json(payload),
            node.updated_at.isoformat(),
        ),
    )


def upsert_dag_edge(conn: sqlite3.Connection, edge: DagEdge) -> None:
    conn.execute(
        """
        INSERT INTO execution_dag_edges(edge_id, from_node_id, to_node_id, edge_type, payload_json)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(edge_id) DO UPDATE SET
          from_node_id=excluded.from_node_id,
          to_node_id=excluded.to_node_id,
          edge_type=excluded.edge_type,
          payload_json=excluded.payload_json
        """,
        (edge.edge_id, edge.from_node_id, edge.to_node_id, edge.edge_type, stable_json(json_ready(edge))),
    )


def upsert_ownership_lease(conn: sqlite3.Connection, lease: OwnershipLease) -> None:
    payload = json_ready(lease)
    conn.execute(
        """
        INSERT INTO ownership_leases(
          lease_id, owner, run_id, group_id, node_id, paths_json, mode, status,
          acquired_at, expires_at, payload_json, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(lease_id) DO UPDATE SET
          owner=excluded.owner,
          run_id=excluded.run_id,
          group_id=excluded.group_id,
          node_id=excluded.node_id,
          paths_json=excluded.paths_json,
          mode=excluded.mode,
          status=excluded.status,
          acquired_at=excluded.acquired_at,
          expires_at=excluded.expires_at,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            lease.lease_id,
            lease.owner,
            lease.run_id,
            lease.group_id,
            lease.node_id,
            stable_json(lease.paths),
            lease.mode,
            lease.status,
            lease.acquired_at.isoformat(),
            lease.expires_at.isoformat() if lease.expires_at else None,
            stable_json(payload),
        ),
    )


def upsert_code_fact(conn: sqlite3.Connection, fact: CodeFact) -> None:
    payload = json_ready(fact)
    conn.execute(
        """
        INSERT INTO code_facts(
          fact_id, file_path, language, kind, name, target, source, line, column,
          payload_json, extracted_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(fact_id) DO UPDATE SET
          file_path=excluded.file_path,
          language=excluded.language,
          kind=excluded.kind,
          name=excluded.name,
          target=excluded.target,
          source=excluded.source,
          line=excluded.line,
          column=excluded.column,
          payload_json=excluded.payload_json,
          extracted_at=excluded.extracted_at,
          updated_at=excluded.updated_at
        """,
        (
            fact.fact_id,
            fact.file_path,
            fact.language,
            fact.kind,
            fact.name,
            fact.target,
            fact.source,
            fact.line,
            fact.column,
            stable_json(payload),
            fact.extracted_at.isoformat(),
        ),
    )


def insert_validation_receipt(conn: sqlite3.Connection, receipt: ValidationReceipt) -> None:
    conn.execute(
        """
        INSERT INTO validation_receipts(
          receipt_id, node_id, command, status, required, exit_code, evidence_path,
          payload_json, recorded_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(receipt_id) DO UPDATE SET
          node_id=excluded.node_id,
          command=excluded.command,
          status=excluded.status,
          required=excluded.required,
          exit_code=excluded.exit_code,
          evidence_path=excluded.evidence_path,
          payload_json=excluded.payload_json,
          recorded_at=excluded.recorded_at
        """,
        (
            receipt.receipt_id,
            receipt.node_id,
            receipt.command,
            receipt.status,
            int(receipt.required),
            receipt.exit_code,
            receipt.evidence_path,
            stable_json(json_ready(receipt)),
            receipt.recorded_at.isoformat(),
        ),
    )


def upsert_execution_group(conn: sqlite3.Connection, group: ExecutionGroup) -> None:
    payload = json_ready(group)
    conn.execute(
        """
        INSERT INTO execution_groups(
          group_id, run_id, action_kind, status, execution_mode, owner_role,
          node_ids_json, ticket_ids_json, paths_json, payload_json, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(group_id) DO UPDATE SET
          run_id=excluded.run_id,
          action_kind=excluded.action_kind,
          status=excluded.status,
          execution_mode=excluded.execution_mode,
          owner_role=excluded.owner_role,
          node_ids_json=excluded.node_ids_json,
          ticket_ids_json=excluded.ticket_ids_json,
          paths_json=excluded.paths_json,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            group.group_id,
            group.run_id,
            group.action_kind,
            group.status,
            group.execution_mode,
            group.owner_role,
            stable_json(group.node_ids),
            stable_json(group.ticket_ids),
            stable_json(group.paths),
            stable_json(payload),
            group.created_at.isoformat(),
            group.updated_at.isoformat(),
        ),
    )


def insert_conflict_telemetry(conn: sqlite3.Connection, conflict: ConflictTelemetry) -> None:
    payload = json_ready(conflict)
    conn.execute(
        """
        INSERT INTO conflict_telemetry(
          conflict_id, run_id, group_id, conflict_type, severity, paths_json,
          payload_json, created_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conflict_id) DO UPDATE SET
          run_id=excluded.run_id,
          group_id=excluded.group_id,
          conflict_type=excluded.conflict_type,
          severity=excluded.severity,
          paths_json=excluded.paths_json,
          payload_json=excluded.payload_json,
          created_at=excluded.created_at
        """,
        (
            conflict.conflict_id,
            conflict.run_id,
            conflict.group_id,
            conflict.conflict_type,
            conflict.severity,
            stable_json(conflict.paths),
            stable_json(payload),
            conflict.created_at.isoformat(),
        ),
    )


def upsert_worker_output(conn: sqlite3.Connection, output: WorkerOutput) -> None:
    payload = json_ready(output)
    conn.execute(
        """
        INSERT INTO worker_runs(
          output_id, run_id, group_id, node_id, worker_id, status,
          changed_paths_json, payload_json, recorded_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(output_id) DO UPDATE SET
          run_id=excluded.run_id,
          group_id=excluded.group_id,
          node_id=excluded.node_id,
          worker_id=excluded.worker_id,
          status=excluded.status,
          changed_paths_json=excluded.changed_paths_json,
          payload_json=excluded.payload_json,
          recorded_at=excluded.recorded_at
        """,
        (
            output.output_id,
            output.run_id,
            output.group_id,
            output.node_id,
            output.worker_id,
            output.status,
            stable_json(output.changed_paths),
            stable_json(payload),
            output.recorded_at.isoformat(),
        ),
    )


def upsert_validation_group(conn: sqlite3.Connection, group: ValidationGroup) -> None:
    payload = json_ready(group)
    conn.execute(
        """
        INSERT INTO validation_groups(
          validation_group_id, run_id, group_id, status, paths_json,
          payload_json, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(validation_group_id) DO UPDATE SET
          run_id=excluded.run_id,
          group_id=excluded.group_id,
          status=excluded.status,
          paths_json=excluded.paths_json,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            group.validation_group_id,
            group.run_id,
            group.group_id,
            group.status,
            stable_json(group.paths),
            stable_json(payload),
            group.created_at.isoformat(),
            group.updated_at.isoformat(),
        ),
    )


def upsert_integration_decision(conn: sqlite3.Connection, decision: IntegrationDecision) -> None:
    payload = json_ready(decision)
    conn.execute(
        """
        INSERT INTO integration_queue(
          decision_id, run_id, group_id, status, paths_json,
          payload_json, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(decision_id) DO UPDATE SET
          run_id=excluded.run_id,
          group_id=excluded.group_id,
          status=excluded.status,
          paths_json=excluded.paths_json,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            decision.decision_id,
            decision.run_id,
            decision.group_id,
            decision.status,
            stable_json(decision.paths),
            stable_json(payload),
            decision.created_at.isoformat(),
            decision.updated_at.isoformat(),
        ),
    )


def upsert_repair_unblocker_work(conn: sqlite3.Connection, work: RepairUnblockerWork) -> None:
    payload = json_ready(work)
    conn.execute(
        """
        INSERT INTO repair_unblocker_work(
          work_id, run_id, source_kind, source_id, action_type, status,
          paths_json, payload_json, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(work_id) DO UPDATE SET
          run_id=excluded.run_id,
          source_kind=excluded.source_kind,
          source_id=excluded.source_id,
          action_type=excluded.action_type,
          status=excluded.status,
          paths_json=excluded.paths_json,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            work.work_id,
            work.run_id,
            work.source_kind,
            work.source_id,
            work.action_type,
            work.status,
            stable_json(work.paths),
            stable_json(payload),
            work.created_at.isoformat(),
            work.updated_at.isoformat(),
        ),
    )


def upsert_scheduler_telemetry(conn: sqlite3.Connection, telemetry: SchedulerTelemetry) -> None:
    payload = json_ready(telemetry)
    conn.execute(
        """
        INSERT INTO scheduler_telemetry(
          telemetry_id, run_id, selected_group_id, candidate_count,
          selected_count, max_fanout, payload_json, created_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telemetry_id) DO UPDATE SET
          run_id=excluded.run_id,
          selected_group_id=excluded.selected_group_id,
          candidate_count=excluded.candidate_count,
          selected_count=excluded.selected_count,
          max_fanout=excluded.max_fanout,
          payload_json=excluded.payload_json,
          created_at=excluded.created_at
        """,
        (
            telemetry.telemetry_id,
            telemetry.run_id,
            telemetry.selected_group_id,
            telemetry.candidate_count,
            telemetry.selected_count,
            telemetry.max_fanout,
            stable_json(payload),
            telemetry.created_at.isoformat(),
        ),
    )


def persist_scheduler_record(conn: sqlite3.Connection, record: SchedulerRecord) -> None:
    payload = json_ready(record)
    conn.execute(
        """
        INSERT INTO scheduler_decisions(decision_id, run_id, selected_json, payload_json, created_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(decision_id) DO UPDATE SET
          selected_json=excluded.selected_json,
          payload_json=excluded.payload_json,
          created_at=excluded.created_at
        """,
        (
            record.decision_id,
            record.run_id,
            stable_json(payload["selected"]),
            stable_json(payload),
            record.created_at.isoformat(),
        ),
    )
    if record.execution_group is not None:
        upsert_execution_group(conn, record.execution_group)
    if record.validation_group is not None:
        upsert_validation_group(conn, record.validation_group)
    if record.integration_decision is not None:
        upsert_integration_decision(conn, record.integration_decision)
    for conflict in record.conflicts:
        insert_conflict_telemetry(conn, conflict)
    for work in record.repair_work:
        upsert_repair_unblocker_work(conn, work)
    if record.scheduler_telemetry is not None:
        upsert_scheduler_telemetry(conn, record.scheduler_telemetry)
    conn.execute(
        """
        INSERT INTO runtime_events(event_type, actor, payload_json, created_at)
        VALUES('scheduler.decision', 'temporal.activity', ?, ?)
        """,
        (stable_json(payload), record.created_at.isoformat()),
    )


def rows_as_payloads(conn: sqlite3.Connection, table: str, order_by: str) -> list[dict[str, Any]]:
    rows = conn.execute(f"SELECT payload_json FROM {table} ORDER BY {order_by}").fetchall()
    values: list[dict[str, Any]] = []
    for row in rows:
        try:
            data = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            values.append(data)
    return values


def read_control_plane_snapshot(target: Path) -> dict[str, Any]:
    with connect(target) as conn:
        counts = {
            name: int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            for name in [
                "runtime_events",
                "tickets",
                "execution_dag_nodes",
                "execution_dag_edges",
                "validation_receipts",
                "scheduler_decisions",
                "ownership_leases",
                "code_facts",
                "execution_groups",
                "conflict_telemetry",
                "worker_runs",
                "validation_groups",
                "integration_queue",
                "repair_unblocker_work",
                "scheduler_telemetry",
                "human_inputs",
                "notification_messages",
            ]
        }
        latest = conn.execute(
            "SELECT payload_json FROM scheduler_decisions ORDER BY created_at DESC, decision_id DESC LIMIT 1"
        ).fetchone()
    latest_decision: dict[str, Any] = {}
    if latest:
        try:
            parsed = json.loads(latest["payload_json"] or "{}")
            latest_decision = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            latest_decision = {}
    return {
        "authority": "sqlite_read_model",
        "database_path": str(database_path_for_target(target)),
        "counts": counts,
        "latest_scheduler_decision": latest_decision,
    }
