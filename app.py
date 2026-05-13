"""FastAPI application — multi-tenant SaaS data migration platform.

Preserves all original SQL-Gen pipeline endpoints (prefixed /api/pipeline, /api/jira, etc.)
and adds the new multi-tenant auth, pipeline orchestration, and gate routers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import shutil
import tempfile

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, Response
from pydantic import BaseModel

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Original core imports (preserved) ────────────────────────────────────────
from core import state_db
from core.orchestrator import PipelineOrchestrator as LegacyOrchestrator

# ── New multi-tenant imports ──────────────────────────────────────────────────
from core.db.platform import close_engine, get_engine, get_platform_session_factory
from core.db.tenant import get_tenant_session_factory
from core.models.platform import PlatformBase
from core.tenant.middleware import TenantMiddleware
from routers.auth import router as auth_router
from routers.pipelines import router as pipeline_router
from routers.gates import router as gates_router
from routers.discovery import router as discovery_router
from routers.stm import router as stm_router
from routers.stm_sessions import router as stm_sessions_router


def decrypt_db_url(encrypted: str) -> str:
    from core.tenant.provisioner import decrypt_db_url as _decrypt
    return _decrypt(encrypted)





async def recover_awaiting_gates(gate_engine) -> None:
    """On startup, restore gate events for runs still in AWAITING state."""
    try:
        async with get_platform_session_factory()() as platform_db:
            from sqlalchemy import select
            from core.models.platform import Tenant
            result = await platform_db.execute(select(Tenant))
            tenants = result.scalars().all()
        for tenant in tenants:
            try:
                db_url = decrypt_db_url(tenant.db_url_encrypted)
                async with get_tenant_session_factory(db_url)() as tenant_db:
                    from sqlalchemy import select
                    from core.models.tenant import PipelineRun
                    result = await tenant_db.execute(
                        select(PipelineRun).where(PipelineRun.status == "AWAITING")
                    )
                    runs = result.scalars().all()
                for run in runs:
                    gate_engine.restore_gate(str(run.id))
            except Exception as exc:
                logger.warning("Failed to recover gates for tenant %s: %s", tenant.slug, exc)
    except Exception as exc:
        logger.warning("recover_awaiting_gates failed: %s", exc)


# ── Startup / Shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create platform DB tables on startup; dispose engine on shutdown."""
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(PlatformBase.metadata.create_all)
        logger.info("Platform DB tables ready")
    except Exception as exc:
        logger.warning("Could not connect to platform DB on startup: %s", exc)

    # Startup recovery: resume any 'running' runs that were interrupted
    try:
        _recover_stale_runs()
    except Exception as exc:
        logger.warning("Startup recovery skipped: %s", exc)

    # STM agentic session recovery: re-queue sessions stuck in 'running'
    try:
        await _recover_stm_sessions()
    except Exception as exc:
        logger.warning("STM session recovery skipped: %s", exc)

    yield

    await close_engine()
    logger.info("Platform DB engine closed")


def _recover_stale_runs() -> None:
    """Mark any legacy runs stuck in 'running' as 'failed' after restart."""
    try:
        stale = state_db.get_stale_running_runs()
        for run in stale:
            state_db.mark_run_failed(run["run_id"], "Interrupted by server restart")
            logger.warning("Recovered stale run: %s", run["run_id"])
    except AttributeError:
        pass  # state_db may not implement get_stale_running_runs


async def _recover_stm_sessions() -> None:
    """Re-queue any STM agentic sessions stuck in 'running' state after restart."""
    try:
        from core.stm.persistence import list_running_sessions
        from core.stm.coordinator import resume_session
        stale = await list_running_sessions()
        for row in stale:
            sid = row["session_id"]
            logger.warning("STM recovery: re-queuing session %s", sid)
            try:
                await resume_session(sid)
            except Exception as exc:
                logger.warning("STM recovery: failed to resume %s: %s", sid, exc)
    except Exception as exc:
        logger.warning("STM session recovery error: %s", exc)


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="SQL-Gen / Migration Platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(TenantMiddleware)

# ── New routers ───────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(pipeline_router)
app.include_router(gates_router)
app.include_router(discovery_router)
app.include_router(stm_router)
app.include_router(stm_sessions_router)


# ── Legacy orchestrator singleton ─────────────────────────────────────────────

_orchestrator: Optional[LegacyOrchestrator] = None


def get_orchestrator() -> LegacyOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = LegacyOrchestrator()
    return _orchestrator


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


# ── Legacy Request / Response models ──────────────────────────────────────────

class TriggerRequest(BaseModel):
    raw_input:      Optional[str] = None
    jira_issue_key: Optional[str] = None
    legacy_code:    Optional[str] = None
    legacy_dialect: Optional[str] = None


class ApprovalRequest(BaseModel):
    reviewer: str
    notes:    str = ""


# ── Legacy pipeline endpoints (preserved) ─────────────────────────────────────

@app.post("/api/pipeline/trigger")
def trigger_pipeline(req: TriggerRequest):
    if not req.raw_input and not req.jira_issue_key:
        raise HTTPException(400, "Provide raw_input or jira_issue_key")
    orch = get_orchestrator()
    run  = orch.trigger(
        raw_input=req.raw_input or "",
        jira_issue_key=req.jira_issue_key,
        legacy_code=req.legacy_code,
        legacy_dialect=req.legacy_dialect,
    )
    return {"run_id": run.run_id, "jira_issue": run.jira_issue, "status": run.status}


@app.post("/api/pipeline/runs/{run_id}/approve")
def approve_run(run_id: str, req: ApprovalRequest):
    orch = get_orchestrator()
    ok   = orch.approve(run_id, req.reviewer, req.notes)
    if not ok:
        raise HTTPException(404, "Run not found or not in review state")
    return {"ok": True}


@app.post("/api/pipeline/runs/{run_id}/reject")
def reject_run(run_id: str, req: ApprovalRequest):
    orch = get_orchestrator()
    ok   = orch.reject(run_id, req.reviewer, req.notes)
    if not ok:
        raise HTTPException(404, "Run not found or not in review state")
    return {"ok": True}


@app.post("/api/pipeline/runs/{run_id}/refine")
def refine_run(run_id: str, req: ApprovalRequest, sidebar_inputs: Optional[dict] = None):
    orch = get_orchestrator()
    ok   = orch.refine(run_id, req.reviewer, req.notes, sidebar_inputs=sidebar_inputs)
    if not ok:
        raise HTTPException(404, "Run not found or not in mapping review state")
    return {"ok": True, "action": "refining"}


@app.get("/api/pipeline/runs")
def list_runs(limit: int = 30):
    return state_db.get_recent_runs(limit)


@app.get("/api/pipeline/runs/pending")
def pending_reviews():
    return state_db.get_pending_reviews()


@app.get("/api/pipeline/runs/{run_id}")
def get_run(run_id: str):
    row = state_db.get_run(run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return row


@app.get("/api/pipeline/runs/{run_id}/artifacts")
def get_artifacts(run_id: str):
    return state_db.get_run_artifacts(run_id)


@app.get("/api/pipeline/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """Server-Sent Events for real-time pipeline status updates."""
    async def event_generator():
        last_log_count = 0
        for _ in range(300):
            row = state_db.get_run(run_id)
            if not row:
                yield "data: {\"error\": \"run not found\"}\n\n"
                return

            logs: List[str] = json.loads(row.get("log_json") or "[]")
            new_logs = logs[last_log_count:]
            last_log_count = len(logs)

            for log in new_logs:
                yield f"data: {json.dumps({'type': 'log', 'message': log})}\n\n"

            yield f"data: {json.dumps({'type': 'status', 'stage': row['stage'], 'status': row['status']})}\n\n"

            if row["status"] in ("completed", "failed"):
                yield f"data: {json.dumps({'type': 'done', 'status': row['status']})}\n\n"
                return

            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Mappings ──────────────────────────────────────────────────────────────────

@app.get("/api/mappings")
def list_mappings(limit: int = 30):
    return state_db.get_recent_mappings(limit)


@app.get("/api/mappings/{mapping_id}/svg")
def get_mapping_svg(mapping_id: str):
    svg_path = Path("output/diagrams") / f"{mapping_id}.svg"
    if not svg_path.exists():
        raise HTTPException(404, f"SVG not found for mapping {mapping_id}")
    return FileResponse(str(svg_path), media_type="image/svg+xml")


# ── Jira proxy ────────────────────────────────────────────────────────────────

@app.get("/api/jira/issues")
def search_jira(jql: str = "project=DATA ORDER BY created DESC", max_results: int = 50):
    try:
        orch   = get_orchestrator()
        issues = orch.jira.search_issues(jql, max_results)
        return issues
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/jira/issues/{issue_key}")
def get_jira_issue(issue_key: str):
    try:
        orch  = get_orchestrator()
        story = orch.jira.get_issue(issue_key, os.getenv("JIRA_AC_FIELD"))
        return story.model_dump()
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Requirements file upload ──────────────────────────────────────────────────

@app.post("/api/requirements/upload")
async def upload_requirements(file: UploadFile = File(...)):
    """Upload a DOCX/PDF/TXT requirements doc and return extracted text."""
    suffix = Path(file.filename).suffix if file.filename else ".tmp"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        from core.doc_processor import extract_text
        text = extract_text(tmp_path)
        return {"filename": file.filename, "text": text, "chars": len(text)}
    except Exception as exc:
        raise HTTPException(400, f"Could not extract text: {exc}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Artifact download ─────────────────────────────────────────────────────────

@app.get("/api/pipeline/runs/{run_id}/artifacts/{filename}/download")
def download_artifact(run_id: str, filename: str):
    """Download a generated artifact file."""
    art_path = Path("output/artifacts") / run_id / filename
    if art_path.exists():
        return FileResponse(str(art_path), filename=filename)

    # Fallback: serve from state_db content field
    artifacts = state_db.get_run_artifacts(run_id)
    for art in artifacts:
        if art.get("filename") == filename:
            content = art.get("content", "")
            media = "text/plain"
            if filename.endswith(".sql"):
                media = "application/sql"
            elif filename.endswith((".yaml", ".yml")):
                media = "text/yaml"
            return Response(
                content=content,
                media_type=media,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    raise HTTPException(404, f"Artifact '{filename}' not found for run {run_id}")


# ── Jira artifact sync ────────────────────────────────────────────────────────

@app.post("/api/pipeline/runs/{run_id}/jira-sync")
def jira_sync(run_id: str):
    """Push generated artifacts as a Jira comment."""
    row = state_db.get_run(run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    artifacts = state_db.get_run_artifacts(run_id)
    issue_key = row.get("jira_issue", "")
    if not issue_key or issue_key == "DRAFT":
        raise HTTPException(400, "No Jira issue associated with this run")
    try:
        orch = get_orchestrator()
        lines = [f"✅ *Engineering artifacts generated* — {len(artifacts)} file(s):\n"]
        for art in artifacts:
            lines.append(f"  • `{art.get('filename','')}` — {art.get('explanation','')}")
        orch.jira.add_comment(issue_key, "\n".join(lines))
        return {"ok": True, "issue": issue_key, "files": len(artifacts)}
    except Exception as exc:
        raise HTTPException(500, str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
