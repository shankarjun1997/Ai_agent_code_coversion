"""SQLAlchemy models for the catalog package — mirrors the c3d4e5f6a7b8 migration."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.platform import PlatformBase


class CatalogSource(PlatformBase):
    __tablename__ = "catalogs_source"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="default")
    catalog_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    table_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    column_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    tables: Mapped[list["CatalogSourceTable"]] = relationship(
        "CatalogSourceTable", back_populates="catalog", cascade="all, delete-orphan",
    )


class CatalogSourceTable(PlatformBase):
    __tablename__ = "catalog_source_tables"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("catalogs_source.id", ondelete="CASCADE"), nullable=False,
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    unity_catalog: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    column_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    columns_json: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)

    catalog: Mapped["CatalogSource"] = relationship("CatalogSource", back_populates="tables")


class CatalogTarget(PlatformBase):
    __tablename__ = "catalogs_target"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="default")
    project: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False, server_default="bigquery_live")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    table_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    column_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    tables: Mapped[list["CatalogTargetTable"]] = relationship(
        "CatalogTargetTable", back_populates="catalog", cascade="all, delete-orphan",
    )


class CatalogTargetTable(PlatformBase):
    __tablename__ = "catalog_target_tables"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("catalogs_target.id", ondelete="CASCADE"), nullable=False,
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    column_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    columns_json: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)

    catalog: Mapped["CatalogTarget"] = relationship("CatalogTarget", back_populates="tables")
