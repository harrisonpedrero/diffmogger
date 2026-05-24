"""restore dashboard-compatible projection table shape

Revision ID: 0003_restore_dashboard_projection_schema
Revises: 0002_adopt_legacy_control_plane_names
Create Date: 2026-05-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_restore_dashboard_projection_schema"
down_revision = "0002_adopt_legacy_control_plane_names"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(name: str) -> set[str]:
    if not _table_exists(name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(name)}


def _archive_table(name: str, base: str) -> None:
    archive = base
    index = 2
    while _table_exists(archive):
        archive = f"{base}_{index}"
        index += 1
    op.rename_table(name, archive)


def _create_projection_table() -> None:
    op.create_table(
        "projections",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("payload_sha256", sa.Text(), nullable=False, server_default=""),
        sa.Column("event_id", sa.Integer(), nullable=True),
    )


def upgrade() -> None:
    required = {"name", "updated_at", "payload_json", "payload_sha256", "event_id"}
    if _table_exists("projections") and required.issubset(_columns("projections")):
        return
    if _table_exists("projections"):
        _archive_table("projections", "typed_projections_pre_0003")
    if _table_exists("legacy_projections_pre_0002") and required.issubset(_columns("legacy_projections_pre_0002")):
        op.rename_table("legacy_projections_pre_0002", "projections")
        return
    _create_projection_table()


def downgrade() -> None:
    pass
