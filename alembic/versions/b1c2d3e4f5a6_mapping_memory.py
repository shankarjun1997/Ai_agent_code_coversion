"""mapping_memory

Adds the mapping_memory table — Phase A of the enterprise-blueprint memory
layer. Every gate2_validation decision (approved / refine / rejected) writes
one row per target field. Becomes the dataset for Phase B RAG retrieval.

Revision ID: b1c2d3e4f5a6
Revises: 8797849a062b
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "8797849a062b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mapping_memory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("gate_name", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer", sa.String(128), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),

        sa.Column("intent_kind", sa.String(32), nullable=True),
        sa.Column("intent_action", sa.String(32), nullable=True),
        sa.Column("intent_entity", sa.String(128), nullable=True),
        sa.Column("intent_keywords_json", sa.Text(), nullable=True),
        sa.Column("jira_issue_key", sa.String(64), nullable=True),

        sa.Column("target_dataset", sa.String(128), nullable=False),
        sa.Column("target_table", sa.String(128), nullable=False),
        sa.Column("target_field", sa.String(128), nullable=True),
        sa.Column("target_type", sa.String(64), nullable=True),

        sa.Column("source_node_ids_json", sa.Text(), nullable=True),
        sa.Column("source_expression", sa.Text(), nullable=True),
        sa.Column("cardinality", sa.String(16), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),

        sa.Column("transformation_kind", sa.String(32), nullable=True),
        sa.Column("transformation_logic", sa.Text(), nullable=True),

        sa.Column("confidence_band", sa.String(16), nullable=True),
        sa.Column("confidence_final", sa.Float(), nullable=True),
        sa.Column("score_llm", sa.Float(), nullable=True),
        sa.Column("score_name_sim", sa.Float(), nullable=True),
        sa.Column("score_type_compat", sa.Float(), nullable=True),
        sa.Column("score_profile_overlap", sa.Float(), nullable=True),
        sa.Column("score_fk_evidence", sa.Float(), nullable=True),

        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("refine_feedback", sa.Text(), nullable=True),

        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_mapping_memory_target",
        "mapping_memory",
        ["target_dataset", "target_table", "target_field"],
    )
    op.create_index("idx_mapping_memory_decision", "mapping_memory", ["decision"])
    op.create_index("idx_mapping_memory_created", "mapping_memory", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_mapping_memory_created", table_name="mapping_memory")
    op.drop_index("idx_mapping_memory_decision", table_name="mapping_memory")
    op.drop_index("idx_mapping_memory_target", table_name="mapping_memory")
    op.drop_table("mapping_memory")
