from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from core.auth.middleware import require_role
from core.gates.engine import GateEngine

router = APIRouter(tags=["gates"])
_gate_engine = None

def get_gate_engine() -> GateEngine:
    global _gate_engine
    if _gate_engine is None:
        _gate_engine = GateEngine()
    return _gate_engine

class GateActionRequest(BaseModel):
    stage: str
    reviewer: str
    notes: str = ""

@router.post("/{run_id}/approve")
async def approve_gate(run_id: str, req: GateActionRequest, request: Request, user: dict = Depends(require_role("engineer"))):
    await get_gate_engine().approve(run_id, req.stage, reviewer=req.reviewer, notes=req.notes, db=request.state.tenant_db)
    return {"ok": True, "run_id": run_id, "stage": req.stage, "action": "approved"}

@router.post("/{run_id}/reject")
async def reject_gate(run_id: str, req: GateActionRequest, request: Request, user: dict = Depends(require_role("engineer"))):
    await get_gate_engine().reject(run_id, req.stage, reviewer=req.reviewer, notes=req.notes, db=request.state.tenant_db)
    return {"ok": True, "run_id": run_id, "stage": req.stage, "action": "rejected"}
