"""let legacy dashboard state and typed orchestration coexist

Revision ID: 0004_coexist_legacy_and_typed_tables
Revises: 0003_restore_dashboard_projection_schema
Create Date: 2026-05-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_coexist_legacy_and_typed_tables"
down_revision = "0003_restore_dashboard_projection_schema"
branch_labels = None
depends_on = None


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(name: str) -> set[str]:
    if not _table_exists(name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(name)}


def _archive_table(name: str, base: str) -> str:
    archive = base
    index = 2
    while _table_exists(archive):
        archive = f"{base}_{index}"
        index += 1
    op.rename_table(name, archive)
    return archive


def _copy_rows(target: str, source: str) -> None:
    if not _table_exists(source):
        return
    copy_columns = sorted(_columns(target).intersection(_columns(source)))
    if not copy_columns:
        return
    columns_sql = ", ".join(_quote(column) for column in copy_columns)
    op.execute(f"INSERT OR IGNORE INTO {_quote(target)} ({columns_sql}) SELECT {columns_sql} FROM {_quote(source)}")


def _ensure_table(name: str, required_columns: set[str], create_sql: str, index_sql: list[str], sources: list[str]) -> None:
    if _table_exists(name) and required_columns.issubset(_columns(name)):
        for statement in index_sql:
            op.execute(statement)
        return
    archived_current = ""
    if _table_exists(name):
        archived_current = _archive_table(name, f"typed_{name}_pre_0004")
    op.execute(create_sql)
    for source in [*sources, archived_current]:
        if source:
            _copy_rows(name, source)
    for statement in index_sql:
        op.execute(statement)


def upgrade() -> None:
    _ensure_table(
        "execution_dag_nodes",
        {
            "node_id",
            "task_id",
            "ticket_id",
            "action_type",
            "status",
            "owner_role",
            "paths_json",
            "summary",
            "payload_json",
            "metadata_json",
            "validation_receipt_refs_json",
        },
        """
        CREATE TABLE execution_dag_nodes (
            node_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL DEFAULT '',
            ticket_id TEXT NOT NULL DEFAULT '',
            action_type TEXT NOT NULL DEFAULT 'work',
            status TEXT NOT NULL DEFAULT 'planned',
            owner_role TEXT NOT NULL DEFAULT 'builder',
            worktree_id TEXT NOT NULL DEFAULT '',
            worktree_path TEXT NOT NULL DEFAULT '',
            patch_id TEXT NOT NULL DEFAULT '',
            patch_path TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.75,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            blocker_reason TEXT NOT NULL DEFAULT '',
            validation_receipt_refs_json TEXT NOT NULL DEFAULT '[]',
            paths_json TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            payload_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        [
            "CREATE INDEX IF NOT EXISTS idx_execution_dag_nodes_task ON execution_dag_nodes(task_id, action_type, status)",
            "CREATE INDEX IF NOT EXISTS idx_execution_dag_nodes_status ON execution_dag_nodes(status, owner_role, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_execution_dag_nodes_action ON execution_dag_nodes(action_type, owner_role, status)",
        ],
        ["legacy_execution_dag_nodes_pre_0002"],
    )
    _ensure_table(
        "execution_dag_edges",
        {
            "edge_id",
            "source_node_id",
            "target_node_id",
            "dependency_kind",
            "from_node_id",
            "to_node_id",
            "edge_type",
            "payload_json",
        },
        """
        CREATE TABLE execution_dag_edges (
            edge_id TEXT PRIMARY KEY,
            source_node_id TEXT NOT NULL DEFAULT '',
            target_node_id TEXT NOT NULL DEFAULT '',
            dependency_kind TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0,
            dependency_mode TEXT NOT NULL DEFAULT 'hard',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            from_node_id TEXT NOT NULL DEFAULT '',
            to_node_id TEXT NOT NULL DEFAULT '',
            edge_type TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            payload_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_dag_edges_unique ON execution_dag_edges(source_node_id, target_node_id, dependency_kind, dependency_mode)",
            "CREATE INDEX IF NOT EXISTS idx_execution_dag_edges_source ON execution_dag_edges(source_node_id, dependency_mode)",
            "CREATE INDEX IF NOT EXISTS idx_execution_dag_edges_target ON execution_dag_edges(target_node_id, dependency_mode)",
        ],
        ["legacy_execution_dag_edges_pre_0002"],
    )
    _ensure_table(
        "validation_receipts",
        {
            "receipt_id",
            "work_item_id",
            "node_id",
            "run_id",
            "stage",
            "kind",
            "command",
            "status",
            "required",
            "payload_json",
            "recorded_at",
        },
        """
        CREATE TABLE validation_receipts (
            receipt_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL DEFAULT '',
            node_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT '',
            command TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            required INTEGER NOT NULL DEFAULT 1,
            exit_code INTEGER,
            evidence_path TEXT NOT NULL DEFAULT '',
            lease_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            log_artifact_id TEXT NOT NULL DEFAULT '',
            event_id INTEGER,
            payload_json TEXT NOT NULL DEFAULT '{}',
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        [
            "CREATE INDEX IF NOT EXISTS idx_validation_receipts_work ON validation_receipts(work_item_id, status, finished_at)",
        ],
        ["legacy_validation_receipts_pre_0002"],
    )


def downgrade() -> None:
    pass
