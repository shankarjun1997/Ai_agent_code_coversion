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
        "last_ping": p.last_ping.isoformat() if getattr(p, "last_ping", None) else None,
        "last_ping_status": getattr(p, "last_ping_status", None),
        "extra":     getattr(p, "extra", {}) or {},
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
async def ping_get(profile_id: str) -> Dict[str, Any]:
    return await _ping_profile(profile_id)


@router.post("/profiles/{profile_id}/ping")
async def ping_post(profile_id: str) -> Dict[str, Any]:
    return await _ping_profile(profile_id)


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str) -> Dict[str, Any]:
    reg = get_registry()
    if not reg.get(profile_id):
        raise HTTPException(status_code=404, detail="profile not found")
    ok = reg.remove(profile_id)
    return {"deleted": ok, "id": profile_id}


async def _ping_profile(profile_id: str) -> Dict[str, Any]:
    """Dispatch ping to the right provider by dialect, update last_ping fields."""
    from datetime import datetime as _dt
    from core.discovery.registry import get_provider as _get_provider
    reg = get_registry()
    p = reg.get(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="profile not found")
    provider = None
    try:
        provider = _get_provider(p.dialect)
    except Exception:
        provider = None
    try:
        if p.dialect == "postgres":
            info = await PostgresProvider(p.dsn).ping()
            ok = True
            payload = {"ok": True, **info}
        elif provider is not None:
            result = await provider.ping(p)
            ok = bool(getattr(result, "ok", False))
            payload = {
                "ok": ok,
                "latency_ms": getattr(result, "latency_ms", None),
                "message": getattr(result, "message", None),
            }
        else:
            raise HTTPException(status_code=400, detail=f"no provider for dialect {p.dialect}")
    except HTTPException:
        raise
    except Exception as e:
        p.last_ping = _dt.utcnow()
        p.last_ping_status = "error"
        raise HTTPException(status_code=502, detail=f"ping failed: {e}")
    p.last_ping = _dt.utcnow()
    p.last_ping_status = "ok" if ok else "error"
    return payload


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


# ---------------------------------------------------------------------------
# Per-dialect profile registration endpoints
# ---------------------------------------------------------------------------

import uuid as _uuid
from core.discovery.credentials import encrypt as _encrypt
from core.discovery.profiles import ConnectionProfile as _ConnectionProfile


class _OracleIn(BaseModel):
    label: str
    dsn: str
    user: str | None = None
    password: str | None = None


class _MySQLIn(BaseModel):
    label: str
    host: str
    port: int = 3306
    db: str
    user: str
    password: str


class _MSSQLIn(BaseModel):
    label: str
    host: str
    port: int = 1433
    db: str
    user: str
    password: str


class _BQIn(BaseModel):
    label: str
    project_id: str
    credentials_json: str | None = None


def _register_profile(dialect: str, label: str, dsn: str, host: str, creds: dict | None) -> dict:
    reg = get_registry()
    pid = f"{dialect[:2]}-{_uuid.uuid4().hex[:8]}"
    p = _ConnectionProfile(
        id=pid, label=label, dialect=dialect, dsn=dsn, host=host,
        encrypted_credentials=_encrypt(creds) if creds else None,
    )
    reg.register(p)
    return {"id": p.id, "label": p.label, "dialect": p.dialect, "host": p.host}


@router.post("/profiles/oracle")
async def post_oracle(body: _OracleIn) -> dict:
    creds = {"user": body.user, "password": body.password} if body.user else None
    return _register_profile("oracle", body.label, body.dsn, body.dsn, creds)


@router.post("/profiles/mysql")
async def post_mysql(body: _MySQLIn) -> dict:
    dsn = f"mysql://{body.user}:{body.password}@{body.host}:{body.port}/{body.db}"
    return _register_profile("mysql", body.label, dsn, f"{body.host}:{body.port}", {"user": body.user, "password": body.password})


@router.post("/profiles/mssql")
async def post_mssql(body: _MSSQLIn) -> dict:
    dsn = f"mssql://{body.user}:{body.password}@{body.host}:{body.port}/{body.db}"
    return _register_profile("mssql", body.label, dsn, f"{body.host}:{body.port}", {"user": body.user, "password": body.password})


@router.post("/profiles/bigquery")
async def post_bigquery(body: _BQIn) -> dict:
    creds = {"credentials_json": body.credentials_json} if body.credentials_json else None
    return _register_profile("bigquery", body.label, body.project_id, "bigquery", creds)


class _JiraIn(BaseModel):
    label: str
    base_url: str
    email: str
    api_token: str
    project_key: str | None = None


@router.post("/profiles/jira")
async def post_jira(body: _JiraIn) -> dict:
    """Register a Jira workspace as a connection profile."""
    base = body.base_url.rstrip("/")
    pid = f"jr-{_uuid.uuid4().hex[:8]}"
    creds = {"email": body.email, "api_token": body.api_token}
    extra = {"email": body.email, "project_key": body.project_key} if body.project_key else {"email": body.email}
    try:
        blob = _encrypt(creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"credential encryption failed: {e}")
    reg = get_registry()
    p = _ConnectionProfile(
        id=pid, label=body.label, dialect="jira",
        dsn=base, host=base.replace("https://", "").replace("http://", ""),
        icon="JR", encrypted_credentials=blob, extra=extra,
    )
    reg.register(p)
    return {"id": p.id, "label": p.label, "dialect": p.dialect, "host": p.host}


@router.get("/jira/{profile_id}/issue/{issue_key}")
async def jira_get_issue(profile_id: str, issue_key: str) -> dict:
    from core.discovery.registry import get_provider as _gp
    reg = get_registry()
    p = reg.get(profile_id)
    if not p or p.dialect != "jira":
        raise HTTPException(status_code=404, detail="jira profile not found")
    provider = _gp("jira")
    data = await provider.get_issue(p, issue_key)
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=data.get("message") or "jira fetch failed")
    return data
