"""create typed local control-plane read model

Revision ID: 0001_control_plane
Revises:
Create Date: 2026-05-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_control_plane"
down_revision = None
branch_labels = None
depends_on = None


def _create_table_if_missing(name: str, *columns: sa.Column) -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(name):
        return
    op.create_table(name, *columns)


def upgrade() -> None:
    _create_table_if_missing(
        "runtime_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False, server_default="system"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_table_if_missing(
        "tickets",
        sa.Column("ticket_id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("depends_on_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("ownership_paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
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
    _create_table_if_missing(
        "execution_dag_edges",
        sa.Column("edge_id", sa.Text(), primary_key=True),
        sa.Column("from_node_id", sa.Text(), nullable=False),
        sa.Column("to_node_id", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
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
    _create_table_if_missing(
        "ownership_leases",
        sa.Column("lease_id", sa.Text(), primary_key=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_table_if_missing(
        "human_inputs",
        sa.Column("input_id", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_table_if_missing(
        "notification_messages",
        sa.Column("message_id", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_table_if_missing(
        "scheduler_decisions",
        sa.Column("decision_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("selected_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_table_if_missing(
        "projections",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("payload_sha256", sa.Text(), nullable=False, server_default=""),
        sa.Column("event_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    for table in [
        "projections",
        "scheduler_decisions",
        "notification_messages",
        "human_inputs",
        "ownership_leases",
        "validation_receipts",
        "execution_dag_edges",
        "execution_dag_nodes",
        "tickets",
        "runtime_events",
    ]:
        op.drop_table(table)
