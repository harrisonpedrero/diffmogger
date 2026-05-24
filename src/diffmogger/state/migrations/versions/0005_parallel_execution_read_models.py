"""add parallel execution read-model tables

Revision ID: 0005_parallel_execution_read_models
Revises: 0004_coexist_legacy_and_typed_tables
Create Date: 2026-05-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_parallel_execution_read_models"
down_revision = "0004_coexist_legacy_and_typed_tables"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(name: str) -> set[str]:
    if not _table_exists(name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(name)}


def _create_table_if_missing(name: str, *columns: sa.Column) -> None:
    if not _table_exists(name):
        op.create_table(name, *columns)


def _archive_table(name: str, base: str) -> str:
    archive = base
    index = 2
    while _table_exists(archive):
        archive = f"{base}_{index}"
        index += 1
    op.rename_table(name, archive)
    return archive


def _archive_if_incompatible(name: str, required_columns: set[str]) -> None:
    if _table_exists(name) and not required_columns.issubset(_columns(name)):
        _archive_table(name, f"typed_{name}_pre_0005")


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if _table_exists(table) and column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing("ownership_leases", sa.Column("run_id", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("ownership_leases", sa.Column("group_id", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("ownership_leases", sa.Column("node_id", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("ownership_leases", sa.Column("acquired_at", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("ownership_leases", sa.Column("expires_at", sa.Text(), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS idx_ownership_leases_active ON ownership_leases(status, mode, expires_at)")

    _archive_if_incompatible(
        "code_facts",
        {"fact_id", "file_path", "language", "kind", "name", "target", "source", "payload_json", "extracted_at"},
    )
    _create_table_if_missing(
        "code_facts",
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("target", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("extracted_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_code_facts_file ON code_facts(file_path, kind)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_code_facts_symbol ON code_facts(kind, name, target)")

    _archive_if_incompatible(
        "execution_groups",
        {"group_id", "run_id", "action_kind", "status", "execution_mode", "node_ids_json", "paths_json", "payload_json"},
    )
    _create_table_if_missing(
        "execution_groups",
        sa.Column("group_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("action_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("execution_mode", sa.Text(), nullable=False),
        sa.Column("owner_role", sa.Text(), nullable=False, server_default="builder"),
        sa.Column("node_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("ticket_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_execution_groups_run ON execution_groups(run_id, status, action_kind)")

    _archive_if_incompatible(
        "conflict_telemetry",
        {"conflict_id", "run_id", "group_id", "conflict_type", "severity", "paths_json", "payload_json"},
    )
    _create_table_if_missing(
        "conflict_telemetry",
        sa.Column("conflict_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("conflict_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_conflict_telemetry_run ON conflict_telemetry(run_id, group_id, conflict_type)")

    _archive_if_incompatible(
        "worker_runs",
        {"output_id", "run_id", "group_id", "node_id", "worker_id", "status", "changed_paths_json", "payload_json"},
    )
    _create_table_if_missing(
        "worker_runs",
        sa.Column("output_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("node_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("worker_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("changed_paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("recorded_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_worker_runs_group ON worker_runs(group_id, status, recorded_at)")

    _archive_if_incompatible(
        "validation_groups",
        {"validation_group_id", "run_id", "group_id", "status", "paths_json", "payload_json"},
    )
    _create_table_if_missing(
        "validation_groups",
        sa.Column("validation_group_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_validation_groups_run ON validation_groups(run_id, group_id, status)")

    _archive_if_incompatible(
        "integration_queue",
        {"decision_id", "run_id", "group_id", "status", "paths_json", "payload_json"},
    )
    _create_table_if_missing(
        "integration_queue",
        sa.Column("decision_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_integration_queue_run ON integration_queue(run_id, status, group_id)")

    _archive_if_incompatible(
        "repair_unblocker_work",
        {"work_id", "run_id", "source_kind", "source_id", "action_type", "status", "paths_json", "payload_json"},
    )
    _create_table_if_missing(
        "repair_unblocker_work",
        sa.Column("work_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_repair_unblocker_run ON repair_unblocker_work(run_id, status, action_type)")

    _archive_if_incompatible(
        "scheduler_telemetry",
        {"telemetry_id", "run_id", "selected_group_id", "candidate_count", "selected_count", "max_fanout", "payload_json"},
    )
    _create_table_if_missing(
        "scheduler_telemetry",
        sa.Column("telemetry_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("selected_group_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_fanout", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_scheduler_telemetry_run ON scheduler_telemetry(run_id, created_at)")


def downgrade() -> None:
    pass
