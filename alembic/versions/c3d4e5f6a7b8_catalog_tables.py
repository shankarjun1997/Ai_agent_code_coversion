"""catalog_tables

Phase 1 of the enterprise mapping refactor — adds 4 tables:
  catalogs_source        — header row per uploaded Databricks dump
  catalog_source_tables  — one row per source table (with columns_json blob)
  catalogs_target        — header row per BigQuery dataset snapshot
  catalog_target_tables  — one row per target table (with columns_json blob)

Catalog data is stored normalized at the table level but JSONB at the column
level — L2/L3 always read the whole catalog at once, so column-level rows
would add joins without query benefit. Phase 3 will add an embeddings table
that FKs to catalog_target_tables.id.

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalogs_source",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("catalog_name", sa.String(255), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),  # "databricks_upload"
        sa.Column("raw_filename", sa.String(512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("table_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_catalogs_source_tenant_status", "catalogs_source", ["tenant_id", "status"])

    op.create_table(
        "catalog_source_tables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("catalog_id", sa.String(36), sa.ForeignKey("catalogs_source.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(255), nullable=True),
        sa.Column("unity_catalog", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("columns_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_source_tables_catalog", "catalog_source_tables", ["catalog_id"])
    op.create_index("idx_source_tables_lookup", "catalog_source_tables", ["catalog_id", "schema_name", "table_name"])

    op.create_table(
        "catalogs_target",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("project", sa.String(128), nullable=False),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("target_kind", sa.String(32), nullable=False, server_default="bigquery_live"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("table_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_catalogs_target_tenant", "catalogs_target", ["tenant_id", "status"])
    op.create_index("idx_catalogs_target_lookup", "catalogs_target", ["tenant_id", "project", "dataset", "status"])

    op.create_table(
        "catalog_target_tables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("catalog_id", sa.String(36), sa.ForeignKey("catalogs_target.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("columns_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_target_tables_catalog", "catalog_target_tables", ["catalog_id"])
    op.create_index("idx_target_tables_lookup", "catalog_target_tables", ["catalog_id", "table_name"])


def downgrade() -> None:
    op.drop_index("idx_target_tables_lookup", table_name="catalog_target_tables")
    op.drop_index("idx_target_tables_catalog", table_name="catalog_target_tables")
    op.drop_table("catalog_target_tables")

    op.drop_index("idx_catalogs_target_lookup", table_name="catalogs_target")
    op.drop_index("idx_catalogs_target_tenant", table_name="catalogs_target")
    op.drop_table("catalogs_target")

    op.drop_index("idx_source_tables_lookup", table_name="catalog_source_tables")
    op.drop_index("idx_source_tables_catalog", table_name="catalog_source_tables")
    op.drop_table("catalog_source_tables")

    op.drop_index("idx_catalogs_source_tenant_status", table_name="catalogs_source")
    op.drop_table("catalogs_source")
