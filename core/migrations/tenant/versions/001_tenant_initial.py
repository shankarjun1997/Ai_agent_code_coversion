"""Tenant initial schema
Revision ID: 001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '001'; down_revision = None; branch_labels = None; depends_on = None

def upgrade():
    op.create_table('pipeline_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('current_stage', sa.String(50)),
        sa.Column('input_payload', JSONB(), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table('gate_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_runs.id'), nullable=False),
        sa.Column('stage', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('reviewer_email', sa.String(255)),
        sa.Column('notes', sa.Text()),
        sa.Column('decided_at', sa.DateTime()),
    )
    op.create_table('agent_outputs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_runs.id'), nullable=False),
        sa.Column('agent_id', sa.String(50), nullable=False),
        sa.Column('output_json', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table('generated_artifacts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_runs.id'), nullable=False),
        sa.Column('agent_id', sa.String(50), nullable=False),
        sa.Column('artifact_type', sa.String(50), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table('generated_artifacts'); op.drop_table('agent_outputs'); op.drop_table('gate_events'); op.drop_table('pipeline_runs')
