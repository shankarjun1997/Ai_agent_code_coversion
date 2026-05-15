"""Fan-out one STM session per source table in a batch."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import update as sa_update

from core.batch.persistence import get_batch, update_batch_status
from core.catalog.persistence import load_source_catalog
from core.db.platform import get_platform_session_factory
from core.models.batch import Batch

logger = logging.getLogger(__name__)

_MAX_PARALLEL = int(os.getenv("STM_MAX_PARALLEL_SESSIONS", "4"))


async def _create_and_run_session(
    batch_id: str,
    tenant_id: str,
    catalog_source_id: str,
    catalog_target_id: str,
    business_context: str,
    table: Dict[str, Any],
) -> str:
    """Build a StmBlackboard for one table and kick off the pipeline."""
    from core.stm.blackboard import StmBlackboard  # local import — avoids circular
    from core.stm.coordinator import start_session  # local import — avoids circular

    session_id = str(uuid.uuid4())
    now = datetime.utcnow()
    bb = StmBlackboard(
        session_id=session_id,
        created_at=now,
        business_context=business_context,
        batch_id=batch_id,
        catalog_source_id=catalog_source_id,
        catalog_target_id=catalog_target_id,
        catalog_source_table_id=table["id"],
        source_table_name_hint=table["table_name"],
    )

    try:
        await start_session(bb, business_context=business_context)
    except Exception as exc:
        logger.error("Session %s (table=%s) failed to start: %s", session_id, table.get("table_name"), exc)

    return session_id


async def run_batch(batch_id: str) -> None:
    """Fan out + run all sessions for a batch, with bounded concurrency."""
    batch = await get_batch(batch_id)
    tenant_id         = batch["tenant_id"]
    catalog_source_id = batch["catalog_source_id"]
    catalog_target_id = batch["catalog_target_id"]
    business_context  = batch.get("business_context") or ""

    source = await load_source_catalog(catalog_source_id)
    tables = source.get("tables", [])

    if not tables:
        logger.warning("Batch %s: source catalog %s has no tables — marking failed", batch_id, catalog_source_id)
        await update_batch_status(batch_id, status="failed", done_count=0)
        return

    # Update session_count now that we know the real table count
    factory = get_platform_session_factory()
    async with factory() as db:
        await db.execute(
            sa_update(Batch).where(Batch.id == batch_id).values(
                session_count=len(tables), updated_at=datetime.utcnow()
            )
        )
        await db.commit()

    await update_batch_status(batch_id, status="running", done_count=0)

    sem = asyncio.Semaphore(_MAX_PARALLEL)
    done = 0

    async def _bounded(table: Dict[str, Any]) -> None:
        nonlocal done
        async with sem:
            await _create_and_run_session(
                batch_id, tenant_id, catalog_source_id, catalog_target_id,
                business_context, table,
            )
            done += 1
            await update_batch_status(batch_id, status="running", done_count=done)

    await asyncio.gather(*[_bounded(t) for t in tables])
    await update_batch_status(batch_id, status="done", done_count=done)
