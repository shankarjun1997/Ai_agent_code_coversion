"""HTTP endpoints for source-system schema discovery."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.discovery import PostgresProvider, get_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/discovery", tags=["discovery"])


def _serialise_profile(p) -> Dict[str, Any]:
    return {
        "id":        p.id,
        "label":     p.label,
        "dialect":   p.dialect,
        "host":      p.host,
        "icon":      p.icon,
        "status":    p.status,
        "last_used": p.last_used,
    }


@router.get("/profiles")
async def list_profiles() -> Dict[str, Any]:
    reg = get_registry()
    return {"profiles": [_serialise_profile(p) for p in reg.list()]}


class RegisterPostgresIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    dsn:   str = Field(..., min_length=10)


@router.post("/profiles/postgres")
async def register_postgres(payload: RegisterPostgresIn) -> Dict[str, Any]:
    reg = get_registry()
    profile = reg.add_postgres(payload.label, payload.dsn)
    # validate by ping
    try:
        info = await PostgresProvider(profile.dsn).ping()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"connection failed: {e}")
    return {"profile": _serialise_profile(profile), "ping": info}


@router.get("/profiles/{profile_id}/ping")
async def ping(profile_id: str) -> Dict[str, Any]:
    reg = get_registry()
    p = reg.get(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="profile not found")
    if p.dialect != "postgres":
        raise HTTPException(status_code=400, detail=f"only postgres ping is implemented; got {p.dialect}")
    try:
        info = await PostgresProvider(p.dsn).ping()
        return {"ok": True, **info}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ping failed: {e}")


@router.get("/profiles/{profile_id}/schemas")
async def list_schemas(profile_id: str) -> Dict[str, Any]:
    reg = get_registry()
    p = reg.get(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="profile not found")
    if p.dialect != "postgres":
        # Stub for non-Postgres demo profiles — return illustrative structure
        return {
            "schemas": [
                {"name": "SALES",     "table_count": 18},
                {"name": "MARKETING", "table_count": 11},
                {"name": "FINANCE",   "table_count": 23},
            ],
            "illustrative": True,
        }
    schemas = await PostgresProvider(p.dsn).list_schemas()
    return {"schemas": schemas, "illustrative": False}


@router.get("/profiles/{profile_id}/schemas/{schema}/tables")
async def list_tables(profile_id: str, schema: str) -> Dict[str, Any]:
    reg = get_registry()
    p = reg.get(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="profile not found")
    if p.dialect != "postgres":
        return {"tables": [], "illustrative": True}
    tables = await PostgresProvider(p.dsn).list_tables(schema)
    return {"tables": tables, "illustrative": False}


@router.get("/profiles/{profile_id}/schemas/{schema}/tables/{table}/columns")
async def list_columns(profile_id: str, schema: str, table: str) -> Dict[str, Any]:
    reg = get_registry()
    p = reg.get(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="profile not found")
    if p.dialect != "postgres":
        return {"columns": [], "illustrative": True}
    cols = await PostgresProvider(p.dsn).get_columns(schema, table)
    return {"columns": cols, "illustrative": False}
