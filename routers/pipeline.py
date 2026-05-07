"""FastAPI pipeline router — start runs, check status."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.middleware import TokenPayload, get_current_user, require_role
from core.db.platform import get_platform_session
from core.db.tenant import get_tenant_session_factory
from core.models.platform import Tenant
from core.models.tenant import AgentOutput, GeneratedArtifact, PipelineRun
from core.pipeline.orchestrator import PipelineDefinition, PipelineOrchestrator
from core.engine.registry import list_agents

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class StartRunRequest(BaseModel):
    pipeline_name: str
    steps: list[str]
    gates: dict[str, str] = {}
    input_data: dict[str, Any] = {}


class RunResponse(BaseModel):
    run_id: str
    status: str
    pipeline_name: str


async def _get_tenant_session(tenant_id: str, platform_session: AsyncSession):
    tenant_row = await platform_session.get(Tenant, uuid.UUID(tenant_id))
    if not tenant_row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    factory = get_tenant_session_factory(tenant_row.slug, tenant_row.db_url_encrypted)
    return factory


@router.post("/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def start_run(
    body: StartRunRequest,
    user: TokenPayload = Depends(require_role("admin", "member")),
    platform_session: AsyncSession = Depends(get_platform_session),
):
    tenant_row = await platform_session.get(Tenant, uuid.UUID(user.tenant_id))
    if not tenant_row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    factory = get_tenant_session_factory(tenant_row.slug, tenant_row.db_url_encrypted)
    async with factory() as tenant_session:
        pipeline = PipelineDefinition(
            name=body.pipeline_name,
            steps=body.steps,
            gates=body.gates,
        )
        orch = PipelineOrchestrator(session=tenant_session)
        run = await orch.start_run(
            tenant_id=user.tenant_id,
            pipeline=pipeline,
            input_data=body.input_data,
        )
        run = await orch.execute(run, pipeline, body.input_data)
        await tenant_session.commit()

    return RunResponse(
        run_id=str(run.id),
        status=run.status,
        pipeline_name=run.pipeline_name,
    )


@router.get("/runs/{run_id}", response_model=dict)
async def get_run(
    run_id: uuid.UUID,
    user: TokenPayload = Depends(get_current_user),
    platform_session: AsyncSession = Depends(get_platform_session),
):
    tenant_row = await platform_session.get(Tenant, uuid.UUID(user.tenant_id))
    if not tenant_row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    factory = get_tenant_session_factory(tenant_row.slug, tenant_row.db_url_encrypted)
    async with factory() as tenant_session:
        run = await tenant_session.get(PipelineRun, run_id)
        if not run or run.tenant_id != uuid.UUID(user.tenant_id):
            raise HTTPException(status_code=404, detail="Run not found")

        outputs = (
            await tenant_session.execute(
                select(AgentOutput).where(AgentOutput.run_id == run_id)
            )
        ).scalars().all()

        artifacts = (
            await tenant_session.execute(
                select(GeneratedArtifact).where(GeneratedArtifact.run_id == run_id)
            )
        ).scalars().all()

    return {
        "run_id": str(run.id),
        "status": run.status,
        "pipeline_name": run.pipeline_name,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "agent_outputs": [
            {
                "agent_id": o.agent_id,
                "output": o.output,
                "error": o.error,
                "duration_ms": o.duration_ms,
            }
            for o in outputs
        ],
        "artifacts": [
            {
                "id": str(a.id),
                "type": a.artifact_type,
                "content": a.content,
            }
            for a in artifacts
        ],
    }


@router.get("/agents", response_model=list[str])
async def get_registered_agents(
    _: TokenPayload = Depends(get_current_user),
):
    return list_agents()
