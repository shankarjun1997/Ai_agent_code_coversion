# core/batch/persistence.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import select, update

from core.db.platform import get_platform_session_factory
from core.models.batch import Batch

BatchStatus = Literal["pending", "running", "done", "failed"]

_factory = get_platform_session_factory()


async def create_batch(
    *,
    tenant_id: str,
    catalog_source_id: str,
    catalog_target_id: str,
    business_context: Optional[str],
    session_count: int,
) -> str:
    now = datetime.utcnow()
    bid = str(uuid.uuid4())
    async with _factory() as session:
        session.add(Batch(
            id=bid,
            tenant_id=tenant_id,
            catalog_source_id=catalog_source_id,
            catalog_target_id=catalog_target_id,
            business_context=business_context,
            status="pending",
            session_count=session_count,
            done_count=0,
            created_at=now,
            updated_at=now,
        ))
        await session.commit()
    return bid


async def get_batch(batch_id: str) -> Dict[str, Any]:
    async with _factory() as session:
        b = (await session.execute(
            select(Batch).where(Batch.id == batch_id)
        )).scalar_one_or_none()
        if b is None:
            raise KeyError(f"Batch {batch_id} not found")
    return {
        "id": b.id,
        "tenant_id": b.tenant_id,
        "catalog_source_id": b.catalog_source_id,
        "catalog_target_id": b.catalog_target_id,
        "business_context": b.business_context,
        "status": b.status,
        "session_count": b.session_count,
        "done_count": b.done_count,
        "created_at": b.created_at.isoformat(),
        "updated_at": b.updated_at.isoformat(),
    }


async def list_batches(*, tenant_id: str) -> List[Dict[str, Any]]:
    async with _factory() as session:
        rows = (await session.execute(
            select(Batch)
            .where(Batch.tenant_id == tenant_id)
            .order_by(Batch.created_at.desc())
        )).scalars().all()
    return [
        {
            "id": b.id,
            "status": b.status,
            "session_count": b.session_count,
            "done_count": b.done_count,
            "created_at": b.created_at.isoformat(),
        }
        for b in rows
    ]


async def update_batch_status(
    batch_id: str,
    *,
    status: BatchStatus,
    done_count: Optional[int] = None,
) -> None:
    vals: Dict[str, Any] = {"status": status, "updated_at": datetime.utcnow()}
    if done_count is not None:
        vals["done_count"] = done_count
    async with _factory() as session:
        result = await session.execute(
            update(Batch).where(Batch.id == batch_id).values(**vals)
        )
        await session.commit()
    if result.rowcount == 0:
        raise KeyError(f"Batch {batch_id} not found")
