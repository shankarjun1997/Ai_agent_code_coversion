# routers/catalogs.py
"""Catalog discovery API — upload source, refresh target, list both.

Endpoints:
  POST /api/catalogs/source              upload a Databricks INFORMATION_SCHEMA dump
  GET  /api/catalogs/source              list active source catalogs
  GET  /api/catalogs/source/{id}         load one source catalog with tables+columns
  POST /api/catalogs/target/refresh      pull live BQ INFORMATION_SCHEMA
  GET  /api/catalogs/target              list active target catalogs
  GET  /api/catalogs/target/{id}         load one target catalog with tables+columns

Multi-tenant: tenant_id is read from request.state.tenant_id when the
TenantMiddleware runs; defaults to "default" for unauthenticated dev calls.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from core.catalog.bq_refresh import refresh_target_catalog
from core.catalog.parser import ParserError
from core.catalog.persistence import (
    list_source_catalogs, list_target_catalogs,
    load_source_catalog, load_target_catalog,
)
from core.catalog.uploader import upload_source_catalog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/catalogs", tags=["catalogs"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class TargetRefreshIn(BaseModel):
    project: str
    dataset: str


# ── Helpers ─────────────────────────────────────────────────────────────────

def _tenant_id(request: Request) -> str:
    return getattr(request.state, "tenant_id", None) or "default"


# ── Source endpoints ────────────────────────────────────────────────────────

@router.post("/source", status_code=201)
async def upload_source(
    request: Request,
    file: UploadFile = File(...),
    catalog_name: str = Form(...),
    description: Optional[str] = Form(None),
) -> dict:
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".xlsx", ".xls", ".xlsm"):
        raise HTTPException(400, f"Unsupported file type {suffix} — only xlsx for v1")

    # Write to a temp file (parser is sync + uses openpyxl from disk).
    body = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)
    try:
        result = await upload_source_catalog(
            tenant_id=_tenant_id(request),
            catalog_name=catalog_name,
            raw_filename=file.filename,
            file_path=tmp_path,
            description=description,
        )
    except ParserError as exc:
        raise HTTPException(422, f"Parse failed: {exc}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return result


@router.get("/source")
async def list_sources(request: Request, include_archived: bool = False) -> dict:
    rows = await list_source_catalogs(tenant_id=_tenant_id(request), include_archived=include_archived)
    return {"catalogs": rows}


@router.get("/source/{catalog_id}")
async def get_source(catalog_id: str) -> dict:
    try:
        return await load_source_catalog(catalog_id)
    except KeyError:
        raise HTTPException(404, f"Catalog {catalog_id} not found")


# ── Target endpoints ────────────────────────────────────────────────────────

@router.post("/target/refresh", status_code=201)
async def refresh_target(request: Request, body: TargetRefreshIn) -> dict:
    try:
        return await refresh_target_catalog(
            tenant_id=_tenant_id(request),
            project=body.project,
            dataset=body.dataset,
        )
    except RuntimeError as exc:
        raise HTTPException(422, str(exc))


@router.get("/target")
async def list_targets(request: Request, include_archived: bool = False) -> dict:
    rows = await list_target_catalogs(tenant_id=_tenant_id(request), include_archived=include_archived)
    return {"catalogs": rows}


@router.get("/target/{catalog_id}")
async def get_target(catalog_id: str) -> dict:
    try:
        return await load_target_catalog(catalog_id)
    except KeyError:
        raise HTTPException(404, f"Catalog {catalog_id} not found")
