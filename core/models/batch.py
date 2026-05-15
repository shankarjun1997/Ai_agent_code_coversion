"""SQLAlchemy model for Batch — multi-source to target mapping sessions."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.platform import PlatformBase


class Batch(PlatformBase):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="default")
    catalog_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    catalog_target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_context: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    session_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    done_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )
