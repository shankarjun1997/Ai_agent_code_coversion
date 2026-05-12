"""HTTP endpoints to generate and download Source-to-Target Mapping (STM) files."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from core.discovery import PostgresProvider, get_registry
from core.stm import build_stm, to_csv, to_xlsx
from core.stm.mapping_engine import MappingResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stm", tags=["stm"])

# In-memory store for the demo. Resets on restart.
_STM_STORE: Dict[str, MappingResult] = {}


class SelectionIn(BaseModel):
    table:  str = Field(..., min_length=1)
    column: str = Field(..., min_length=1)


class GenerateSTMIn(BaseModel):
    profile_id:     str
    schema:         str
    selections:     List[SelectionIn] = Field(..., min_length=1)
    target_dataset: str = Field(default="analytics_warehouse")
    target_table:   str = Field(default="fact_customer_360")
    business_rules: Optional[List[str]] = None


@router.post("/generate")
async def generate(payload: GenerateSTMIn) -> Dict[str, Any]:
    reg = get_registry()
    profile = reg.get(payload.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="profile not found")
    if profile.dialect != "postgres":
        raise HTTPException(status_code=400,
            detail=f"STM generation currently supports postgres; '{profile.dialect}' is illustrative-only")

    # Pull live column metadata for every distinct table touched in the selection
    provider = PostgresProvider(profile.dsn)
    tables = sorted({s.table for s in payload.selections})
    cols_by_table: Dict[str, List[Dict[str, Any]]] = {}
    for t in tables:
        try:
            cols_by_table[t] = await provider.get_columns(payload.schema, t)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"discovery failed for {payload.schema}.{t}: {e}")

    result = build_stm(
        profile_id=payload.profile_id,
        source_system=profile.label,
        schema=payload.schema,
        selections=[s.model_dump() for s in payload.selections],
        columns_by_table=cols_by_table,
        target_dataset=payload.target_dataset,
        target_table=payload.target_table,
        business_rules=payload.business_rules,
    )
    _STM_STORE[result.stm_id] = result
    return result.summary()


@router.get("/{stm_id}/summary")
async def get_summary(stm_id: str) -> Dict[str, Any]:
    r = _STM_STORE.get(stm_id)
    if not r:
        raise HTTPException(status_code=404, detail="stm not found")
    return r.summary()


@router.get("/{stm_id}/export.xlsx")
async def export_xlsx(stm_id: str):
    r = _STM_STORE.get(stm_id)
    if not r:
        raise HTTPException(status_code=404, detail="stm not found")
    body = to_xlsx(r)
    fname = f"stm-{r.target_table}-{r.stm_id}.xlsx"
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{stm_id}/export.csv")
async def export_csv(stm_id: str):
    r = _STM_STORE.get(stm_id)
    if not r:
        raise HTTPException(status_code=404, detail="stm not found")
    body = to_csv(r)
    fname = f"stm-{r.target_table}-{r.stm_id}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
