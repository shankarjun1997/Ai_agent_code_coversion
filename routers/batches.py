# routers/batches.py
"""Batch submission and status API."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.batch.orchestrator import run_batch
from core.batch.persistence import create_batch, get_batch, list_batches
from core.catalog.persistence import load_source_catalog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stm/batches", tags=["batches"])


def _tenant_id(request: Request) -> str:
    return getattr(request.state, "tenant_id", None) or "default"


class BatchIn(BaseModel):
    catalog_source_id: str
    catalog_target_id: str
    business_context: Optional[str] = None


@router.post("", status_code=201)
async def submit_batch(req: Request, body: BatchIn) -> dict:
    try:
        source = await load_source_catalog(body.catalog_source_id)
    except KeyError:
        raise HTTPException(404, f"Source catalog {body.catalog_source_id} not found")

    tables = source.get("tables", [])
    if not tables:
        raise HTTPException(422, "Source catalog has no tables")

    batch_id = await create_batch(
        tenant_id=_tenant_id(req),
        catalog_source_id=body.catalog_source_id,
        catalog_target_id=body.catalog_target_id,
        business_context=body.business_context,
        session_count=len(tables),
    )

    asyncio.create_task(run_batch(batch_id))

    return {"batch_id": batch_id, "session_count": len(tables), "status": "pending"}


@router.get("")
async def list_batches_endpoint(req: Request) -> dict:
    rows = await list_batches(tenant_id=_tenant_id(req))
    return {"batches": rows}


@router.get("/{batch_id}")
async def get_batch_endpoint(batch_id: str) -> dict:
    try:
        return await get_batch(batch_id)
    except KeyError:
        raise HTTPException(404, f"Batch {batch_id} not found")


@router.get("/{batch_id}/events")
async def batch_events(batch_id: str, req: Request):
    """SSE: poll events from all sessions in this batch."""
    from core.db.platform import get_platform_session_factory
    from sqlalchemy import text

    async def generate():
        factory = get_platform_session_factory()
        seen: set = set()
        while True:
            if await req.is_disconnected():
                break
            try:
                async with factory() as db:
                    rows = await db.execute(
                        text("""
                            SELECT e.event_id, e.session_id, e.event_kind, e.artifact_json, e.message, e.created_at
                            FROM stm_stage_events e
                            JOIN stm_sessions s ON s.session_id = e.session_id
                            WHERE s.batch_id = :bid
                            ORDER BY e.created_at ASC
                        """),
                        {"bid": batch_id},
                    )
                    for row in rows:
                        eid = row[0]
                        if eid not in seen:
                            seen.add(eid)
                            payload = json.loads(row[3]) if row[3] else {}
                            if row[4]:
                                payload["message"] = row[4]
                            data = json.dumps({
                                "session_id": row[1],
                                "kind": row[2],
                                "payload": payload,
                            })
                            yield f"data: {data}\n\n"
            except Exception as exc:
                logger.warning("Batch SSE error: %s", exc)
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
