"""FastAPI application — multi-tenant SaaS data migration platform.

Source-first STM agentic pipeline: Databricks Unity Catalog → BigQuery.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from core.db.platform import close_engine, get_engine, get_platform_session_factory
from core.db.tenant import get_tenant_session_factory
from core.models.platform import PlatformBase
from core.tenant.middleware import TenantMiddleware

from routers.auth import router as auth_router
from routers.gates import router as gates_router
from routers.discovery import router as discovery_router
from routers.stm_sessions import router as stm_sessions_router
from routers.stm_memory import router as stm_memory_router


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

    try:
        await _recover_stm_sessions()
    except Exception as exc:
        logger.warning("STM session recovery skipped: %s", exc)

    yield

    await close_engine()
    logger.info("Platform DB engine closed")


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

app.include_router(auth_router)
app.include_router(gates_router)
app.include_router(discovery_router)
app.include_router(stm_sessions_router)
app.include_router(stm_memory_router)


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
