# core/catalog/persistence.py
"""Async DB read/write helpers for catalogs.

Source catalog write replaces any existing 'active' catalog with the same
(tenant_id, catalog_name) — old rows are marked 'archived' but kept for audit.
Target catalog write replaces any existing 'active' catalog for the same
(tenant_id, project, dataset).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from core.catalog.parser import ParsedSchema
from core.db.platform import get_platform_session_factory
from core.models.catalog import (
    CatalogSource, CatalogSourceTable, CatalogTarget, CatalogTargetTable,
)


# ── Source catalog writes ───────────────────────────────────────────────────

async def save_source_catalog(
    *,
    tenant_id: str,
    catalog_name: str,
    source_kind: str,
    raw_filename: Optional[str],
    description: Optional[str],
    schema: ParsedSchema,
) -> str:
    """Persist a parsed source schema. Archives any prior active catalog with
    the same (tenant_id, catalog_name). Returns new catalog_id (uuid).
    """
    factory = get_platform_session_factory()
    now = datetime.utcnow()
    catalog_id = str(uuid.uuid4())
    table_count = len(schema.tables)
    column_count = sum(len(t.columns) for t in schema.tables)

    async with factory() as session:
        # Archive prior actives with the same name.
        await session.execute(
            update(CatalogSource)
            .where(
                CatalogSource.tenant_id == tenant_id,
                CatalogSource.catalog_name == catalog_name,
                CatalogSource.status == "active",
            )
            .values(status="archived", updated_at=now)
        )

        cat = CatalogSource(
            id=catalog_id,
            tenant_id=tenant_id,
            catalog_name=catalog_name,
            source_kind=source_kind,
            raw_filename=raw_filename,
            description=description,
            status="active",
            table_count=table_count,
            column_count=column_count,
            created_at=now,
            updated_at=now,
        )
        session.add(cat)

        for t in schema.tables:
            session.add(CatalogSourceTable(
                id=str(uuid.uuid4()),
                catalog_id=catalog_id,
                table_name=t.table_name,
                schema_name=t.schema_name,
                unity_catalog=t.catalog,
                description=t.description,
                column_count=len(t.columns),
                columns_json=json.dumps(t.columns),
                created_at=now,
            ))

        await session.commit()

    return catalog_id


# ── Source catalog reads ────────────────────────────────────────────────────

async def list_source_catalogs(*, tenant_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
    factory = get_platform_session_factory()
    async with factory() as session:
        stmt = select(CatalogSource).where(CatalogSource.tenant_id == tenant_id)
        if not include_archived:
            stmt = stmt.where(CatalogSource.status == "active")
        stmt = stmt.order_by(CatalogSource.created_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "catalog_name": r.catalog_name,
            "source_kind": r.source_kind,
            "raw_filename": r.raw_filename,
            "description": r.description,
            "status": r.status,
            "table_count": r.table_count,
            "column_count": r.column_count,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


async def load_source_catalog(catalog_id: str) -> Dict[str, Any]:
    """Return the full catalog with tables + columns (columns parsed from JSON)."""
    factory = get_platform_session_factory()
    async with factory() as session:
        cat = (await session.execute(
            select(CatalogSource).where(CatalogSource.id == catalog_id)
        )).scalar_one_or_none()
        if cat is None:
            raise KeyError(f"Source catalog {catalog_id} not found")

        tbls = (await session.execute(
            select(CatalogSourceTable).where(CatalogSourceTable.catalog_id == catalog_id)
        )).scalars().all()

    return {
        "id": cat.id,
        "tenant_id": cat.tenant_id,
        "catalog_name": cat.catalog_name,
        "source_kind": cat.source_kind,
        "raw_filename": cat.raw_filename,
        "description": cat.description,
        "status": cat.status,
        "table_count": cat.table_count,
        "column_count": cat.column_count,
        "created_at": cat.created_at.isoformat(),
        "updated_at": cat.updated_at.isoformat(),
        "tables": [
            {
                "id": t.id,
                "table_name": t.table_name,
                "schema_name": t.schema_name,
                "unity_catalog": t.unity_catalog,
                "description": t.description,
                "column_count": t.column_count,
                "columns": json.loads(t.columns_json),
            }
            for t in tbls
        ],
    }


# ── Target catalog writes ───────────────────────────────────────────────────

async def save_target_catalog(
    *,
    tenant_id: str,
    project: str,
    dataset: str,
    tables: List[Dict[str, Any]],  # [{table_name, description, columns:[{name,type,...}]}]
) -> str:
    """Persist a target catalog snapshot. Archives prior active catalog for
    the same (tenant_id, project, dataset). Returns new catalog_id.
    """
    factory = get_platform_session_factory()
    now = datetime.utcnow()
    catalog_id = str(uuid.uuid4())
    table_count = len(tables)
    column_count = sum(len(t.get("columns", [])) for t in tables)

    async with factory() as session:
        await session.execute(
            update(CatalogTarget)
            .where(
                CatalogTarget.tenant_id == tenant_id,
                CatalogTarget.project == project,
                CatalogTarget.dataset == dataset,
                CatalogTarget.status == "active",
            )
            .values(status="archived", updated_at=now)
        )

        cat = CatalogTarget(
            id=catalog_id,
            tenant_id=tenant_id,
            project=project,
            dataset=dataset,
            target_kind="bigquery_live",
            status="active",
            table_count=table_count,
            column_count=column_count,
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(cat)

        for t in tables:
            cols = t.get("columns", [])
            session.add(CatalogTargetTable(
                id=str(uuid.uuid4()),
                catalog_id=catalog_id,
                table_name=t["table_name"],
                description=t.get("description"),
                column_count=len(cols),
                columns_json=json.dumps(cols),
                created_at=now,
            ))

        await session.commit()
    return catalog_id


async def list_target_catalogs(*, tenant_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
    factory = get_platform_session_factory()
    async with factory() as session:
        stmt = select(CatalogTarget).where(CatalogTarget.tenant_id == tenant_id)
        if not include_archived:
            stmt = stmt.where(CatalogTarget.status == "active")
        stmt = stmt.order_by(CatalogTarget.fetched_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "project": r.project,
            "dataset": r.dataset,
            "target_kind": r.target_kind,
            "status": r.status,
            "table_count": r.table_count,
            "column_count": r.column_count,
            "fetched_at": r.fetched_at.isoformat(),
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


async def load_target_catalog(catalog_id: str) -> Dict[str, Any]:
    factory = get_platform_session_factory()
    async with factory() as session:
        cat = (await session.execute(
            select(CatalogTarget).where(CatalogTarget.id == catalog_id)
        )).scalar_one_or_none()
        if cat is None:
            raise KeyError(f"Target catalog {catalog_id} not found")
        tbls = (await session.execute(
            select(CatalogTargetTable).where(CatalogTargetTable.catalog_id == catalog_id)
        )).scalars().all()

    return {
        "id": cat.id,
        "tenant_id": cat.tenant_id,
        "project": cat.project,
        "dataset": cat.dataset,
        "target_kind": cat.target_kind,
        "status": cat.status,
        "table_count": cat.table_count,
        "column_count": cat.column_count,
        "fetched_at": cat.fetched_at.isoformat(),
        "created_at": cat.created_at.isoformat(),
        "updated_at": cat.updated_at.isoformat(),
        "tables": [
            {
                "id": t.id,
                "table_name": t.table_name,
                "description": t.description,
                "column_count": t.column_count,
                "columns": json.loads(t.columns_json),
            }
            for t in tbls
        ],
    }
