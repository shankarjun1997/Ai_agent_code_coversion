"""Add batches table and batch-related columns to stm_sessions.

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-05-15
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def _col_exists(conn, table: str, col: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": col},
    )
    return result.fetchone() is not None


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:t"
        ),
        {"t": table},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "batches"):
        op.create_table(
            "batches",
            sa.Column("id",                 sa.String(36),  primary_key=True),
            sa.Column("tenant_id",          sa.String(64),  nullable=False, server_default="default"),
            sa.Column("catalog_source_id",  sa.String(36),  nullable=False),
            sa.Column("catalog_target_id",  sa.String(36),  nullable=False),
            sa.Column("business_context",   sa.Text(),      nullable=True),
            sa.Column("status",             sa.String(16),  nullable=False, server_default="pending"),
            sa.Column("session_count",      sa.Integer(),   nullable=False, server_default="0"),
            sa.Column("done_count",         sa.Integer(),   nullable=False, server_default="0"),
            sa.Column("created_at",         sa.DateTime(),  nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at",         sa.DateTime(),  nullable=False, server_default=sa.func.now()),
        )

    for col_name, col_type in [
        ("batch_id",                sa.String(36)),
        ("catalog_source_id",       sa.String(36)),
        ("catalog_target_id",       sa.String(36)),
        ("catalog_source_table_id", sa.String(36)),
        ("source_table_name",       sa.String(255)),
    ]:
        if not _col_exists(conn, "stm_sessions", col_name):
            op.add_column("stm_sessions", sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    for col in ["batch_id", "catalog_source_id", "catalog_target_id", "catalog_source_table_id", "source_table_name"]:
        op.drop_column("stm_sessions", col)
    op.drop_table("batches")
