"""Tenant DB models — PipelineRun, GateEvent, AgentOutput, GeneratedArtifact."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class TenantBase(DeclarativeBase):
    pass


class PipelineRun(TenantBase):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    pipeline_name: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PENDING"
    )
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    gate_events: Mapped[list["GateEvent"]] = relationship("GateEvent", back_populates="run")
    agent_outputs: Mapped[list["AgentOutput"]] = relationship("AgentOutput", back_populates="run")
    artifacts: Mapped[list["GeneratedArtifact"]] = relationship(
        "GeneratedArtifact", back_populates="run"
    )

    def __repr__(self) -> str:
        return f"<PipelineRun {self.id} status={self.status}>"


class GateEvent(TenantBase):
    __tablename__ = "gate_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    gate_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    decision: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    reviewer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="gate_events")

    def __repr__(self) -> str:
        return f"<GateEvent {self.gate_name} decision={self.decision}>"


class AgentOutput(TenantBase):
    __tablename__ = "agent_outputs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="agent_outputs")

    def __repr__(self) -> str:
        return f"<AgentOutput agent={self.agent_id} run={self.run_id}>"


class GeneratedArtifact(TenantBase):
    __tablename__ = "generated_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="artifacts")

    def __repr__(self) -> str:
        return f"<GeneratedArtifact type={self.artifact_type} run={self.run_id}>"
