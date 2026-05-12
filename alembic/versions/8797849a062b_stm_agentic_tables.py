"""stm_agentic_tables

Revision ID: 8797849a062b
Revises:
Create Date: 2026-05-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8797849a062b"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Platform tables (tenants / tenant_users / refresh_tokens)
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("db_url_encrypted", sa.Text(), nullable=False),
        sa.Column("plan", sa.String(50), nullable=False, server_default="starter"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    op.create_table(
        "tenant_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenant_users_tenant_id", "tenant_users", ["tenant_id"])
    op.create_index("ix_tenant_users_email", "tenant_users", ["email"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("tenant_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    # Profiles — source connection registry
    op.create_table(
        "profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("dialect", sa.String(16), nullable=False),
        sa.Column("dsn", sa.Text(), nullable=False),
        sa.Column("host", sa.String(256), nullable=False),
        sa.Column("icon", sa.String(8), nullable=False, server_default="DB"),
        sa.Column("status", sa.String(32), nullable=False, server_default="connected"),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=True),
        sa.Column("last_ping", sa.DateTime(), nullable=True),
        sa.Column("last_ping_status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # STM agentic session tables
    op.create_table(
        "stm_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_stage", sa.String(16), nullable=False),
        sa.Column("target_table", sa.String(128), nullable=False),
        sa.Column("target_dataset", sa.String(128), nullable=False),
        sa.Column("source_profiles", sa.Text(), nullable=False),
        sa.Column("intent_source", sa.String(16), nullable=False),
        sa.Column("jira_issue_key", sa.String(64), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("blackboard_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=True),
    )

    op.create_table(
        "stm_stage_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("stm_sessions.session_id"), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("event_kind", sa.String(32), nullable=False),
        sa.Column("artifact_kind", sa.String(32), nullable=True),
        sa.Column("artifact_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("llm_model", sa.String(64), nullable=True),
        sa.Column("llm_tokens_in", sa.Integer(), nullable=True),
        sa.Column("llm_tokens_out", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_stm_stage_events_session",
        "stm_stage_events",
        ["session_id", "created_at"],
    )

    op.create_table(
        "stm_gate_decisions",
        sa.Column("decision_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("stm_sessions.session_id"), nullable=False),
        sa.Column("gate_name", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer", sa.String(128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("refine_target", sa.String(16), nullable=True),
        sa.Column("refine_feedback", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stm_gate_decisions")
    op.drop_index("idx_stm_stage_events_session", table_name="stm_stage_events")
    op.drop_table("stm_stage_events")
    op.drop_table("stm_sessions")
    op.drop_table("profiles")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_tenant_users_email", table_name="tenant_users")
    op.drop_index("ix_tenant_users_tenant_id", table_name="tenant_users")
    op.drop_table("tenant_users")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
