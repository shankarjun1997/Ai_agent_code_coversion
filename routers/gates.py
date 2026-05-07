"""FastAPI gate router — submit gate decisions for awaiting pipeline runs."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.middleware import TokenPayload, require_role
from core.db.platform import get_platform_session
from core.db.tenant import get_tenant_session_factory
from core.models.platform import Tenant
from core.models.tenant import PipelineRun
from core.pipeline.orchestrator import PipelineDefinition, PipelineOrchestrator

router = APIRouter(prefix="/gates", tags=["gates"])


class GateDecisionRequest(BaseModel):
    run_id: uuid.UUID
    gate_name: str
    decision: str  # "approved" | "rejected"
    notes: str = ""
    # Caller must re-supply pipeline definition for resume
    pipeline_name: str
    steps: list[str]
    gates: dict[str, str] = {}
    input_data: dict = {}


class GateDecisionResponse(BaseModel):
    run_id: str
    status: str
    gate_name: str
    decision: str


@router.post("/decide", response_model=GateDecisionResponse)
async def decide_gate(
    body: GateDecisionRequest,
    user: TokenPayload = Depends(require_role("admin")),
    platform_session: AsyncSession = Depends(get_platform_session),
):
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="decision must be 'approved' or 'rejected'",
        )

    tenant_row = await platform_session.get(Tenant, uuid.UUID(user.tenant_id))
    if not tenant_row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    factory = get_tenant_session_factory(tenant_row.slug, tenant_row.db_url_encrypted)
    async with factory() as tenant_session:
        run = await tenant_session.get(PipelineRun, body.run_id)
        if not run or run.tenant_id != uuid.UUID(user.tenant_id):
            raise HTTPException(status_code=404, detail="Run not found")

        if run.status != "awaiting_gate":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run is not awaiting a gate (status={run.status})",
            )

        pipeline = PipelineDefinition(
            name=body.pipeline_name,
            steps=body.steps,
            gates=body.gates,
        )
        orch = PipelineOrchestrator(session=tenant_session)
        run = await orch.resume_after_gate(
            run=run,
            pipeline=pipeline,
            gate_name=body.gate_name,
            decision=body.decision,
            reviewer_id=uuid.UUID(user.sub) if user.sub else None,
            notes=body.notes or None,
            input_data=body.input_data,
        )
        await tenant_session.commit()

    return GateDecisionResponse(
        run_id=str(run.id),
        status=run.status,
        gate_name=body.gate_name,
        decision=body.decision,
    )
