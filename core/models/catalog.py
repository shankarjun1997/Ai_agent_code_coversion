"""SQLAlchemy models for the catalog package — mirrors the c3d4e5f6a7b8 migration."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from core.models.platform import PlatformBase


class CatalogSource(PlatformBase):
    __tablename__ = "catalogs_source"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="default")
    catalog_name = Column(String(255), nullable=False)
    source_kind = Column(String(32), nullable=False)
    raw_filename = Column(String(512), nullable=True)
    description = Column(Text(), nullable=True)
    status = Column(String(16), nullable=False, default="active")
    table_count = Column(Integer(), nullable=False, default=0)
    column_count = Column(Integer(), nullable=False, default=0)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(), nullable=False, default=datetime.utcnow)

    tables = relationship("CatalogSourceTable", back_populates="catalog", cascade="all, delete-orphan")


class CatalogSourceTable(PlatformBase):
    __tablename__ = "catalog_source_tables"

    id = Column(String(36), primary_key=True)
    catalog_id = Column(String(36), ForeignKey("catalogs_source.id", ondelete="CASCADE"), nullable=False)
    table_name = Column(String(255), nullable=False)
    schema_name = Column(String(255), nullable=True)
    unity_catalog = Column(String(255), nullable=True)
    description = Column(Text(), nullable=True)
    column_count = Column(Integer(), nullable=False, default=0)
    columns_json = Column(Text(), nullable=False)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)

    catalog = relationship("CatalogSource", back_populates="tables")


class CatalogTarget(PlatformBase):
    __tablename__ = "catalogs_target"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="default")
    project = Column(String(128), nullable=False)
    dataset = Column(String(128), nullable=False)
    target_kind = Column(String(32), nullable=False, default="bigquery_live")
    status = Column(String(16), nullable=False, default="active")
    table_count = Column(Integer(), nullable=False, default=0)
    column_count = Column(Integer(), nullable=False, default=0)
    fetched_at = Column(DateTime(), nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(), nullable=False, default=datetime.utcnow)

    tables = relationship("CatalogTargetTable", back_populates="catalog", cascade="all, delete-orphan")


class CatalogTargetTable(PlatformBase):
    __tablename__ = "catalog_target_tables"

    id = Column(String(36), primary_key=True)
    catalog_id = Column(String(36), ForeignKey("catalogs_target.id", ondelete="CASCADE"), nullable=False)
    table_name = Column(String(255), nullable=False)
    description = Column(Text(), nullable=True)
    column_count = Column(Integer(), nullable=False, default=0)
    columns_json = Column(Text(), nullable=False)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)

    catalog = relationship("CatalogTarget", back_populates="tables")
