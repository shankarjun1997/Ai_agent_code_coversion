"""STM agentic session API endpoints.

POST   /api/stm/sessions                     — create + start a new session
GET    /api/stm/sessions/{id}                — fetch session status + blackboard summary
GET    /api/stm/sessions/{id}/events         — SSE live progress stream
GET    /api/stm/sessions/{id}/export         — download xlsx (regenerated from stm_result)
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

import os
import shutil

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from core.stm.blackboard import (
    Attachment, GateDecision, IntentArtifact, MetadataGraph,
    CandidateMappings, StmBlackboard, Transformations, ValidationReport,
)
from core.stm.coordinator import decide_gate, is_running, signal_start, start_session
from core.stm.events import get_broker
from core.stm.persistence import (
    get_session_status, list_events, load_blackboard, save_blackboard,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stm/sessions", tags=["stm-sessions"])


# ── Request / Response schemas ────────────────────────────────────────────────

class CreateSessionIn(BaseModel):
    target_table: str = Field(..., min_length=1)
    target_dataset: str = Field(..., min_length=1)
    source_profiles: List[str] = Field(..., min_items=1)
    raw_input: str = Field(..., min_length=1)
    intent_source: str = Field(default="freetext")
    jira_issue_key: Optional[str] = None
    pause_for_attachments: bool = False


class SessionSummary(BaseModel):
    session_id: str
    status: str
    current_stage: str
    target_table: str
    target_dataset: str
    source_profiles: List[str]
    intent_entity: Optional[str]
    intent_status: Optional[str]
    overall_band: Optional[str]
    stm_result_available: bool
    is_running: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _bb_summary(bb: StmBlackboard) -> SessionSummary:
    db_status = await get_session_status(bb.session_id) or "running"
    return SessionSummary(
        session_id=bb.session_id,
        status=db_status,
        current_stage=bb.current_stage,
        target_table=bb.target_table,
        target_dataset=bb.target_dataset,
        source_profiles=bb.selected_source_profiles,
        intent_entity=bb.intent.entity or None,
        intent_status=bb.intent.status.value if bb.intent else None,
        overall_band=bb.validation.overall_band if (bb.validation and bb.validation.scores) else None,
        stm_result_available=bb.stm_result is not None,
        is_running=is_running(bb.session_id),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_session(payload: CreateSessionIn) -> Dict[str, Any]:
    """Create a new STM agentic session and start the L1→L6 pipeline."""
    session_id = str(uuid.uuid4())

    bb = StmBlackboard(
        session_id=session_id,
        target_table=payload.target_table,
        target_dataset=payload.target_dataset,
        dialect_target="bigquery",
        selected_source_profiles=payload.source_profiles,
        intent=IntentArtifact(
            source=payload.intent_source if payload.intent_source in ("jira", "freetext") else "freetext",
            raw_input=payload.raw_input,
            jira_issue_key=payload.jira_issue_key,
        ),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(
            target_table=payload.target_table,
            target_dataset=payload.target_dataset,
        ),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )

    try:
        await start_session(
            bb,
            raw_input=payload.raw_input,
            intent_source=payload.intent_source,
            jira_issue_key=payload.jira_issue_key,
            pause_for_attachments=payload.pause_for_attachments,
        )
    except Exception as exc:
        logger.exception("Failed to start STM session: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to start session: {exc}")

    return {
        "session_id": session_id,
        "status": "awaiting_attachments" if payload.pause_for_attachments else "running",
        "events_url": f"/api/stm/sessions/{session_id}/events",
        "paused": payload.pause_for_attachments,
    }


@router.post("/{session_id}/start")
async def start_paused_session(session_id: str) -> Dict[str, Any]:
    """Signal a session that was created with pause_for_attachments=true to proceed.

    No-op if the session wasn't paused. After this, L1 begins.
    """
    try:
        await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    unblocked = signal_start(session_id)
    return {"session_id": session_id, "unblocked": unblocked}


@router.post("/{session_id}/attachments")
async def upload_attachment(session_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload a CSV/PDF/DOCX/TXT attachment. Stored on disk, parsed, and added
    to the blackboard so L2 can ingest CSV columns as synthetic source nodes
    and L1 can pull document text into raw_input.
    """
    from core.stm.attachments import parse_attachment, storage_dir
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    target_dir = storage_dir(session_id)
    safe_name = os.path.basename(file.filename or "upload.bin")
    dest = os.path.join(target_dir, f"{uuid.uuid4().hex[:8]}_{safe_name}")
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to write upload: {exc}")
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    parsed = parse_attachment(dest, safe_name)
    att = Attachment(
        id=uuid.uuid4().hex,
        filename=safe_name,
        kind=parsed["kind"],
        bytes=parsed["bytes"],
        stored_at=dest,
        text_excerpt=parsed.get("text_excerpt", ""),
        csv_schema=parsed.get("csv_schema"),
    )
    bb.attachments.append(att)
    if parsed.get("text_excerpt"):
        sep = "\n\n---\n\n" if bb.intent.raw_input else ""
        bb.intent.raw_input = f"{bb.intent.raw_input}{sep}{parsed['text_excerpt']}"
    await save_blackboard(bb)

    return {
        "attachment_id": att.id,
        "kind": att.kind,
        "bytes": att.bytes,
        "csv_schema": att.csv_schema,
        "text_excerpt_chars": len(att.text_excerpt or ""),
    }


@router.get("/{session_id}/attachments")
async def list_attachments(session_id: str) -> Dict[str, Any]:
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"attachments": [a.model_dump(mode="json") for a in bb.attachments]}


@router.delete("/{session_id}/attachments/{attachment_id}")
async def delete_attachment(session_id: str, attachment_id: str) -> Dict[str, Any]:
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    before = len(bb.attachments)
    removed = next((a for a in bb.attachments if a.id == attachment_id), None)
    bb.attachments = [a for a in bb.attachments if a.id != attachment_id]
    if removed and removed.stored_at and os.path.exists(removed.stored_at):
        try:
            os.remove(removed.stored_at)
        except OSError:
            pass
    await save_blackboard(bb)
    return {"deleted": before != len(bb.attachments), "id": attachment_id}


@router.get("/{session_id}")
async def get_session(session_id: str) -> SessionSummary:
    """Return current state summary for a session."""
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return await _bb_summary(bb)


@router.get("/{session_id}/blackboard")
async def get_blackboard(session_id: str) -> Dict[str, Any]:
    """Return the full blackboard so the UI can render per-stage artifacts."""
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return bb.model_dump(mode="json")


@router.get("/{session_id}/events")
async def stream_events(session_id: str):
    """SSE stream of live session events.

    Replays DB events first (for reconnects), then tails live broker events.
    """
    # Verify session exists
    try:
        await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    async def _generate():
        # 1. Replay historical events from DB
        try:
            past = await list_events(session_id)
            for ev in past:
                data = {
                    "event": ev.get("event_kind"),
                    "stage": ev.get("stage"),
                    "data": {},
                    "session_id": session_id,
                }
                yield f"data: {json.dumps(data)}\n\n"
        except Exception as exc:
            logger.warning("SSE replay failed for %s: %s", session_id, exc)

        # 2. If session is still running, tail live events
        if is_running(session_id):
            broker = get_broker()
            try:
                async for event in broker.subscribe(session_id):
                    yield event.to_sse()
            except asyncio.CancelledError:
                pass

        # 3. Send terminal event if session already done
        else:
            try:
                bb = await load_blackboard(session_id)
                terminal_event = "session_done" if bb.current_stage == "done" else "session_failed"
                yield f"data: {json.dumps({'event': terminal_event, 'stage': bb.current_stage, 'data': {}, 'session_id': session_id})}\n\n"
            except Exception:
                pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class GateDecisionIn(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected|refine)$")
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    refine_target: Optional[str] = None
    refine_feedback: Optional[str] = None


@router.post("/{session_id}/gates/{gate_name}")
async def post_gate_decision(session_id: str, gate_name: str, payload: GateDecisionIn) -> Dict[str, Any]:
    """Submit an Approve / Reject / Refine decision for a gate."""
    try:
        await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    try:
        await decide_gate(
            session_id,
            gate_name=gate_name,
            decision=payload.decision,
            reviewer=payload.reviewer,
            notes=payload.notes,
            refine_target=payload.refine_target,
            refine_feedback=payload.refine_feedback,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Gate decision failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"session_id": session_id, "gate": gate_name, "decision": payload.decision}


@router.post("/{session_id}/clone", status_code=201)
async def clone_session(session_id: str) -> Dict[str, Any]:
    """Start a fresh session re-using the source profiles + target + raw input
    of an existing session. Useful when reviewers want to try a different intent
    framing or re-run from scratch after a rejection."""
    try:
        src = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    new_id = str(uuid.uuid4())
    bb = StmBlackboard(
        session_id=new_id,
        target_table=src.target_table,
        target_dataset=src.target_dataset,
        dialect_target=src.dialect_target,
        selected_source_profiles=list(src.selected_source_profiles),
        intent=IntentArtifact(
            source=src.intent.source if src.intent else "freetext",
            raw_input=src.intent.raw_input if src.intent else "",
            jira_issue_key=src.intent.jira_issue_key if src.intent else None,
        ),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(
            target_table=src.target_table,
            target_dataset=src.target_dataset,
        ),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )

    try:
        await start_session(
            bb,
            raw_input=bb.intent.raw_input,
            intent_source=bb.intent.source,
            jira_issue_key=bb.intent.jira_issue_key,
        )
    except Exception as exc:
        logger.exception("Clone failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Clone failed: {exc}")

    return {
        "session_id": new_id,
        "cloned_from": session_id,
        "events_url": f"/api/stm/sessions/{new_id}/events",
    }


def _build_ddl(bb: StmBlackboard) -> str:
    """Render CREATE SCHEMA + CREATE TABLE DDL from the blackboard."""
    cols: List[str] = []
    for m in bb.candidate_mappings.rows:
        bq_type = (m.target_type or "STRING").upper()
        cols.append(f"  `{m.target_field}` {bq_type}")
    if bb.transformations and bb.transformations.audit_fields:
        for af in bb.transformations.audit_fields:
            if not any(m.target_field == af for m in bb.candidate_mappings.rows):
                cols.append(f"  `{af}` TIMESTAMP")
    partition_clause = ""
    if bb.transformations and bb.transformations.partition_field:
        partition_clause = f"\nPARTITION BY DATE(`{bb.transformations.partition_field}`)"
    return (
        f"CREATE SCHEMA IF NOT EXISTS `{bb.target_dataset}`;\n"
        f"CREATE TABLE IF NOT EXISTS `{bb.target_dataset}.{bb.target_table}` (\n"
        + ",\n".join(cols)
        + f"\n){partition_clause};\n"
    )


@router.get("/{session_id}/bq/preview-ddl")
async def bq_preview_ddl(session_id: str) -> Dict[str, Any]:
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"sql": _build_ddl(bb), "table": f"{bb.target_dataset}.{bb.target_table}"}


@router.post("/{session_id}/bq/materialize")
async def bq_materialize(session_id: str) -> Dict[str, Any]:
    """Create the target dataset (if missing) and table in BigQuery.

    Guarded by Gate 2 approval. Idempotent — uses CREATE IF NOT EXISTS.
    """
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    gate2 = bb.gates.get("gate2_validation")
    if not gate2 or gate2.decision != "approved":
        raise HTTPException(status_code=409, detail="Gate 2 has not approved this session yet")

    ddl = _build_ddl(bb)
    project_id = os.environ.get("BQ_PROJECT_ID", "")
    try:
        from core.bq_client import BQClient
        client = BQClient(project_id=project_id or None)
        ok, _bytes, msg = client.dry_run(ddl) if hasattr(client, "dry_run") else (True, None, None)
        if not ok:
            raise HTTPException(status_code=400, detail=f"DDL dry-run failed: {msg}")
        if hasattr(client, "run_query"):
            client.run_query(ddl)
        bb.materialized = {
            "ok": True,
            "table_ref": f"{bb.target_dataset}.{bb.target_table}",
            "project_id": project_id,
            "sql": ddl,
        }
        await save_blackboard(bb)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("BQ materialize failed for %s", session_id)
        raise HTTPException(status_code=502, detail=f"BigQuery materialize failed: {exc}")

    return bb.materialized


@router.get("/{session_id}/export")
async def export_xlsx(session_id: str, format: str = "xlsx"):
    """Download the STM xlsx for a completed session."""
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    if bb.current_stage != "done" or not bb.stm_result:
        raise HTTPException(status_code=409, detail="Session not yet complete")

    if format == "changelog":
        md = (bb.stm_result or {}).get("changelog_md", "")
        if not md:
            raise HTTPException(status_code=404, detail="No changelog for this session (not an enhancement run)")
        filename = f"stm_{bb.target_dataset}_{bb.target_table}_changelog.md"
        return Response(
            content=md, media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Regenerate xlsx from current blackboard state
    try:
        from core.stm.agents.builder_agent import _build_mapping_rows
        from core.stm.mapping_engine import MappingResult
        from core.stm.exporter import to_xlsx, to_csv
        import uuid as _uuid
        from datetime import datetime, timezone

        rows = _build_mapping_rows(bb)
        source_tables = list({r.source_table for r in rows if r.source_table})

        result = MappingResult(
            stm_id=bb.stm_result.get("stm_id") or str(_uuid.uuid4()),
            profile_id=bb.selected_source_profiles[0] if bb.selected_source_profiles else "unknown",
            source_system=bb.selected_source_profiles[0] if bb.selected_source_profiles else "unknown",
            source_schema="public",
            source_tables=source_tables,
            target_dataset=bb.target_dataset,
            target_table=bb.target_table,
            partition_field=bb.transformations.partition_field,
            rows=rows,
            pii_count=sum(1 for r in rows if r.is_pii),
            field_count=len(rows),
            idempotency_key=bb.transformations.idempotency_key,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        if format == "csv":
            csv_bytes = to_csv(result)
            filename = f"stm_{bb.target_dataset}_{bb.target_table}.csv"
            return Response(
                content=csv_bytes, media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        xlsx_bytes = to_xlsx(result)
    except Exception as exc:
        logger.exception("xlsx export failed for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")

    filename = f"stm_{bb.target_dataset}_{bb.target_table}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
