"""STM agentic session HTTP API — source-first pipeline.

Endpoints:
  POST   /api/stm/sessions                        create + start a session
  GET    /api/stm/sessions                        list recent sessions
  GET    /api/stm/sessions/{id}                   summary
  GET    /api/stm/sessions/{id}/blackboard        full blackboard JSON
  GET    /api/stm/sessions/{id}/events            SSE stream
  POST   /api/stm/sessions/{id}/gates/{gate}      gate decision
  GET    /api/stm/sessions/{id}/export.xlsx       STM workbook download
  GET    /api/stm/sessions/{id}/export.zip        per-target SQL bundle
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from core.stm.blackboard import (
    ColumnRef, MappingType, SourceTable, StmBlackboard, TargetSchema,
)
from core.stm.coordinator import decide_gate, is_running, signal_start, start_session
from core.stm.events import EventKind, SseEvent, get_broker
from core.stm.exporter import build_sql_zip, build_stm_xlsx
from core.stm.persistence import (
    get_session_status, list_events, list_sessions, load_blackboard, save_blackboard,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stm/sessions", tags=["stm-sessions"])


# ── Request / response schemas ──────────────────────────────────────────────

class ColumnIn(BaseModel):
    name: str
    type: Optional[str] = None
    description: Optional[str] = None


class TargetTableIn(BaseModel):
    name: str
    columns: List[ColumnIn] = Field(default_factory=list)


class CreateSessionIn(BaseModel):
    business_context: str = ""
    # Source — exactly one of the two routes
    source_table: Optional[Dict[str, Any]] = None
    databricks_profile_id: Optional[str] = None
    databricks_table: Optional[str] = None
    # Target — exactly one of the two routes
    target_schema: Optional[Dict[str, Any]] = None
    bq_project: Optional[str] = None
    bq_dataset: Optional[str] = None


class GateDecisionIn(BaseModel):
    decision: str  # approved | rejected | refine
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    refine_target: Optional[str] = None
    refine_feedback: Optional[str] = None


class MappingRowEdit(BaseModel):
    """Reviewer-edited mapping row pushed back into the blackboard at Gate 2."""
    source_table: str
    source_column: str
    target_table: str = ""
    target_column: str = ""
    mapping_type: MappingType
    business_logic: str = ""
    rationale: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _coerce_source_table(payload: Dict[str, Any]) -> SourceTable:
    cols = [ColumnRef(**c) for c in payload.get("columns", [])]
    return SourceTable(
        name=payload["name"],
        columns=cols,
        origin=payload.get("origin", "upload"),  # type: ignore[arg-type]
        catalog=payload.get("catalog"),
        schema_name=payload.get("schema_name"),
        comment=payload.get("comment"),
    )


def _coerce_target_schema(payload: Dict[str, Any]) -> TargetSchema:
    tables = []
    for t in payload.get("tables", []):
        cols = [ColumnRef(**c) for c in t.get("columns", [])]
        tables.append(SourceTable(name=t["name"], columns=cols, origin="upload"))
    return TargetSchema(
        project=payload.get("project", ""),
        dataset=payload.get("dataset", ""),
        tables=tables,
        origin=payload.get("origin", "upload"),  # type: ignore[arg-type]
    )


def _summary(bb: StmBlackboard, status: Optional[str]) -> Dict[str, Any]:
    return {
        "session_id": bb.session_id,
        "status": status or "unknown",
        "current_stage": bb.current_stage,
        "source_table": bb.source_table_name,
        "target_project": bb.target_project,
        "target_dataset": bb.target_dataset,
        "shortlist_count": len(bb.shortlist.rows) if bb.shortlist else 0,
        "mappings_count": len(bb.mappings),
        "has_sql": bb.sql_bundle is not None,
        "gates": {k: g.decision for k, g in bb.gates.items()},
        "created_at": bb.created_at.isoformat() if bb.created_at else None,
        "updated_at": bb.updated_at.isoformat() if bb.updated_at else None,
    }


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_session(body: CreateSessionIn) -> Dict[str, Any]:
    if not body.source_table and not (body.databricks_profile_id and body.databricks_table):
        raise HTTPException(400, "Provide source_table or databricks_profile_id+databricks_table")
    if not body.target_schema and not (body.bq_project and body.bq_dataset):
        raise HTTPException(400, "Provide target_schema or bq_project+bq_dataset")

    bb = StmBlackboard(
        session_id=str(uuid.uuid4()),
        business_context=body.business_context or "",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    if body.source_table:
        bb.source_table = _coerce_source_table(body.source_table)
    if body.target_schema:
        bb.target_schema = _coerce_target_schema(body.target_schema)

    config: Dict[str, Any] = {}
    if body.databricks_profile_id and body.databricks_table:
        config["databricks_profile_id"] = body.databricks_profile_id
        config["databricks_table"] = body.databricks_table
    if body.bq_project and body.bq_dataset:
        config["bq_project"] = body.bq_project
        config["bq_dataset"] = body.bq_dataset

    await start_session(bb, business_context=bb.business_context, config=config)
    return {"session_id": bb.session_id, "status": "running"}


@router.get("")
async def list_recent(limit: int = 50) -> Dict[str, Any]:
    rows = await list_sessions(limit=limit)
    return {"sessions": rows}


@router.get("/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")
    status = await get_session_status(session_id)
    return _summary(bb, status)


@router.get("/{session_id}/blackboard")
async def get_blackboard(session_id: str) -> Dict[str, Any]:
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")
    return json.loads(bb.model_dump_json())


@router.get("/{session_id}/events")
async def stream_events(session_id: str) -> StreamingResponse:
    broker = get_broker()

    async def gen():
        # Send a hello with current status so reconnecting clients catch up
        try:
            bb = await load_blackboard(session_id)
            status = await get_session_status(session_id)
            yield f"data: {json.dumps({'event': 'snapshot', 'stage': bb.current_stage, 'status': status, 'mappings': len(bb.mappings)})}\n\n"
        except Exception:
            pass

        async for ev in broker.subscribe(session_id):
            payload = {
                "event": ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
                "stage": ev.stage,
                "data": ev.data or {},
                "session_id": ev.session_id,
            }
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/{session_id}/gates/{gate_name}")
async def gate_decision(session_id: str, gate_name: str, body: GateDecisionIn) -> Dict[str, Any]:
    if gate_name not in ("gate1_shortlist", "gate2_mapping"):
        raise HTTPException(400, f"Unknown gate {gate_name}")
    # If user is approving Gate 1 with edits to the picked tables, persist first
    try:
        await decide_gate(
            session_id,
            gate_name=gate_name,
            decision=body.decision,
            reviewer=body.reviewer,
            notes=body.notes,
            refine_target=body.refine_target,
            refine_feedback=body.refine_feedback,
        )
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.put("/{session_id}/shortlist")
async def update_shortlist(session_id: str, picks: List[str]) -> Dict[str, Any]:
    """Reviewer-edited shortlist picks before approving Gate 1."""
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")
    if bb.shortlist is None:
        raise HTTPException(400, "Shortlist not yet produced")
    picked = set(picks)
    for e in bb.shortlist.rows:
        e.picked = e.table in picked
    await save_blackboard(bb)
    return {"ok": True, "picked": [e.table for e in bb.shortlist.rows if e.picked]}


@router.put("/{session_id}/mappings")
async def update_mappings(session_id: str, rows: List[MappingRowEdit]) -> Dict[str, Any]:
    """Reviewer-edited mapping rows before approving Gate 2."""
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")
    from core.stm.blackboard import MappingRow
    bb.mappings = [
        MappingRow(
            source_table=r.source_table, source_column=r.source_column,
            target_table=r.target_table, target_column=r.target_column,
            mapping_type=r.mapping_type, business_logic=r.business_logic,
            rationale=r.rationale, edited_by_reviewer=True,
        )
        for r in rows
    ]
    await save_blackboard(bb)
    return {"ok": True, "count": len(bb.mappings)}


@router.get("/{session_id}/export.xlsx")
async def export_xlsx(session_id: str) -> Response:
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")
    data = await asyncio.to_thread(build_stm_xlsx, bb)
    fname = f"STM_{bb.source_table_name or 'session'}_{datetime.utcnow():%Y%m%d}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{session_id}/export.zip")
async def export_zip(session_id: str) -> Response:
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")
    if bb.sql_bundle is None:
        raise HTTPException(400, "SQL not generated yet — wait for L4")
    data = await asyncio.to_thread(build_sql_zip, bb.sql_bundle, bb.source_table_name)
    fname = f"STM_{bb.source_table_name or 'session'}_{datetime.utcnow():%Y%m%d}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{session_id}/audit")
async def get_audit_log(session_id: str, limit: int = 200) -> Dict[str, Any]:
    rows = await list_events(session_id, limit=limit)
    return {"events": rows}
