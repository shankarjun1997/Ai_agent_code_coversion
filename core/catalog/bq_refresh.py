"""Pull live BQ INFORMATION_SCHEMA into a target catalog snapshot."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from core.bq_client import BQClient
from core.catalog.persistence import save_target_catalog


def _group_rows_by_table(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_table: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        tn = r.get("table_name")
        if not tn:
            continue
        col = {
            "name": r.get("column_name"),
            "type": r.get("data_type"),
            "description": r.get("description"),
            "is_nullable": (r.get("is_nullable") == "YES") if r.get("is_nullable") is not None else None,
            "ordinal": len(by_table.get(tn, [])),
        }
        by_table.setdefault(tn, []).append(col)
    return [
        {"table_name": tn, "description": None, "columns": cols}
        for tn, cols in by_table.items()
    ]


async def refresh_target_catalog(
    *,
    tenant_id: str,
    project: str,
    dataset: str,
) -> Dict[str, Any]:
    """Live-fetch BQ INFORMATION_SCHEMA, persist as target catalog, return summary."""
    client = BQClient(project_id=project)
    rows = await asyncio.to_thread(client.list_columns_in_dataset, dataset)
    if not rows:
        raise RuntimeError(
            f"INFORMATION_SCHEMA returned no rows for {project}.{dataset} — "
            f"dataset is empty or service account lacks access"
        )
    tables = _group_rows_by_table(rows)
    catalog_id = await save_target_catalog(
        tenant_id=tenant_id,
        project=project,
        dataset=dataset,
        tables=tables,
    )
    return {
        "catalog_id": catalog_id,
        "project": project,
        "dataset": dataset,
        "table_count": len(tables),
        "column_count": sum(len(t["columns"]) for t in tables),
    }
