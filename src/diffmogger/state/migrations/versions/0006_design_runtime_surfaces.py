"""add design contract and review runtime surfaces

Revision ID: 0006_design_runtime_surfaces
Revises: 0005_parallel_execution_read_models
Create Date: 2026-05-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_design_runtime_surfaces"
down_revision = "0005_parallel_execution_read_models"
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


def _archive_table(name: str, base: str) -> None:
    archive = base
    index = 2
    while _table_exists(archive):
        archive = f"{base}_{index}"
        index += 1
    op.rename_table(name, archive)


def _archive_if_incompatible(name: str, required_columns: set[str]) -> None:
    if _table_exists(name) and not required_columns.issubset(_columns(name)):
        _archive_table(name, f"typed_{name}_pre_0006")


def upgrade() -> None:
    _archive_if_incompatible(
        "design_contracts",
        {
            "contract_id",
            "version",
            "status",
            "source",
            "ui_capability_mode",
            "ui_validation_mode",
            "designer_enabled",
            "payload_json",
            "updated_at",
        },
    )
    _create_table_if_missing(
        "design_contracts",
        sa.Column("contract_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("source", sa.Text(), nullable=False, server_default="generated_contract"),
        sa.Column("ui_capability_mode", sa.Text(), nullable=False, server_default="auto"),
        sa.Column("ui_validation_mode", sa.Text(), nullable=False, server_default="auto"),
        sa.Column("designer_enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_design_contracts_status ON design_contracts(status, updated_at)")

    _archive_if_incompatible(
        "design_reviews",
        {
            "review_id",
            "contract_id",
            "contract_version",
            "node_id",
            "ticket_id",
            "status",
            "severity",
            "findings_json",
            "evidence_paths_json",
            "required_follow_up_json",
            "payload_json",
            "recorded_at",
        },
    )
    _create_table_if_missing(
        "design_reviews",
        sa.Column("review_id", sa.Text(), primary_key=True),
        sa.Column("contract_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("contract_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("node_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("ticket_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="not_required"),
        sa.Column("severity", sa.Text(), nullable=False, server_default="info"),
        sa.Column("findings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("required_follow_up_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("recorded_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_design_reviews_ticket ON design_reviews(ticket_id, status, recorded_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_design_reviews_node ON design_reviews(node_id, status, recorded_at)")


def downgrade() -> None:
    pass
