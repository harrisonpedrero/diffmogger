"""archive legacy tables that reused new control-plane names

Revision ID: 0002_adopt_legacy_control_plane_names
Revises: 0001_control_plane
Create Date: 2026-05-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_adopt_legacy_control_plane_names"
down_revision = "0001_control_plane"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(name: str) -> set[str]:
    if not _table_exists(name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(name)}


def _archive_table(name: str) -> None:
    base = f"legacy_{name}_pre_0002"
    archive = base
    index = 2
    while _table_exists(archive):
        archive = f"{base}_{index}"
        index += 1
    op.rename_table(name, archive)


def _archive_if_incompatible(name: str, required_columns: set[str]) -> None:
    if _table_exists(name) and not required_columns.issubset(_columns(name)):
        _archive_table(name)


def _create_table_if_missing(name: str, *columns: sa.Column) -> None:
    if not _table_exists(name):
        op.create_table(name, *columns)


def upgrade() -> None:
    _archive_if_incompatible(
        "execution_dag_nodes",
        {
            "node_id",
            "ticket_id",
            "action_type",
            "status",
            "owner_role",
            "paths_json",
            "summary",
            "confidence",
            "payload_json",
            "updated_at",
        },
    )
    _create_table_if_missing(
        "execution_dag_nodes",
        sa.Column("node_id", sa.Text(), primary_key=True),
        sa.Column("ticket_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("owner_role", sa.Text(), nullable=False, server_default="builder"),
        sa.Column("paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    _archive_if_incompatible(
        "execution_dag_edges",
        {"edge_id", "from_node_id", "to_node_id", "edge_type", "payload_json"},
    )
    _create_table_if_missing(
        "execution_dag_edges",
        sa.Column("edge_id", sa.Text(), primary_key=True),
        sa.Column("from_node_id", sa.Text(), nullable=False),
        sa.Column("to_node_id", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
    )

    _archive_if_incompatible(
        "validation_receipts",
        {
            "receipt_id",
            "node_id",
            "command",
            "status",
            "required",
            "exit_code",
            "evidence_path",
            "payload_json",
            "recorded_at",
        },
    )
    _create_table_if_missing(
        "validation_receipts",
        sa.Column("receipt_id", sa.Text(), primary_key=True),
        sa.Column("node_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("required", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("evidence_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("recorded_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    _archive_if_incompatible("projections", {"name", "payload_json", "payload_sha256", "event_id", "updated_at"})
    _create_table_if_missing(
        "projections",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("payload_sha256", sa.Text(), nullable=False, server_default=""),
        sa.Column("event_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    pass
