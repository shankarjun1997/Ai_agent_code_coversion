"""Glue: parse an uploaded file and persist as a source catalog."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.catalog.parser import parse_schema_file
from core.catalog.persistence import save_source_catalog


async def upload_source_catalog(
    *,
    tenant_id: str,
    catalog_name: str,
    raw_filename: str,
    file_path: Path,
    description: Optional[str] = None,
    source_kind: str = "databricks_upload",
) -> dict:
    """Parse the file at `file_path`, persist as a source catalog, return summary."""
    schema = parse_schema_file(file_path)
    catalog_id = await save_source_catalog(
        tenant_id=tenant_id,
        catalog_name=catalog_name,
        source_kind=source_kind,
        raw_filename=raw_filename,
        description=description,
        schema=schema,
    )
    return {
        "catalog_id": catalog_id,
        "strategy": schema.strategy,
        "table_count": len(schema.tables),
        "column_count": sum(len(t.columns) for t in schema.tables),
    }
