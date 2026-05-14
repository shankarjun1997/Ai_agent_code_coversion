"""L1 — Schemas agent.

Resolves both sides of the mapping:

* SOURCE side: a single source table. Two routes:
    - Databricks Unity Catalog (live, via DatabricksUnityProvider)
    - File upload (xlsx / csv / json) — parser owns the upload model.
  Provenance is preserved on `SourceTable.origin`.

* TARGET side: the BigQuery dataset's INFORMATION_SCHEMA — many tables.
  Two routes:
    - Live BQ query via `core.bq_client.BQClient.get_table_schema()` per table
    - File upload (xlsx INFORMATION_SCHEMA dump)

If both halves are already populated on the blackboard (because the API
endpoint set them from uploads), this agent is a no-op pass-through. The
config dict may carry `databricks_profile_id`, `databricks_table` (FQN),
`bq_project`, `bq_dataset` to drive live fetches when uploads aren't used.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import ColumnRef, SourceTable, TargetSchema

logger = logging.getLogger(__name__)


class SchemasAgent(StmAgent):
    stage = "L1"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        updates: Dict[str, Any] = {}

        source_table = bb.source_table
        if source_table is None:
            source_table = await self._resolve_source(ctx)

        target_schema = bb.target_schema
        if target_schema is None:
            target_schema = await self._resolve_target(ctx)

        if source_table is None and target_schema is None:
            return BlackboardDelta.failure(
                "No source or target provided — upload files or set databricks/bq config"
            )
        if source_table is None:
            return BlackboardDelta.failure("Source table not provided")
        if target_schema is None:
            return BlackboardDelta.failure("Target schema not provided")

        updates["source_table"] = source_table
        updates["target_schema"] = target_schema
        return BlackboardDelta(updates=updates)

    # ── source side ─────────────────────────────────────────────────────────

    async def _resolve_source(self, ctx: AgentContext) -> Optional[SourceTable]:
        profile_id = ctx.get("databricks_profile_id")
        table_fqn = ctx.get("databricks_table")
        if not profile_id or not table_fqn:
            return None
        from core.discovery import get_provider
        from core.discovery.profiles import load_profile
        try:
            provider = get_provider("databricks")
        except KeyError:
            logger.warning("Databricks provider not registered; cannot resolve live source")
            return None
        profile = await load_profile(profile_id)
        if profile is None:
            return None
        cols = await provider.list_columns(profile, table_fqn)  # type: ignore[attr-defined]
        catalog, schema, name = _split_fqn(table_fqn)
        return SourceTable(
            name=name,
            columns=[ColumnRef(name=c["name"], type=c.get("type"), description=c.get("comment")) for c in cols],
            origin="databricks_unity",
            catalog=catalog,
            schema_name=schema,
        )

    # ── target side ─────────────────────────────────────────────────────────

    async def _resolve_target(self, ctx: AgentContext) -> Optional[TargetSchema]:
        project = ctx.get("bq_project") or ctx.blackboard.target_project
        dataset = ctx.get("bq_dataset") or ctx.blackboard.target_dataset
        if not project or not dataset:
            return None
        try:
            from core.bq_client import BQClient
        except Exception as exc:
            logger.warning("BQClient unavailable: %s", exc)
            return None
        try:
            client = BQClient(project_id=project)
        except Exception as exc:
            logger.warning("BQ client init failed: %s", exc)
            return None
        try:
            rows = await _to_thread(client.list_columns_in_dataset, dataset)
        except Exception as exc:
            logger.exception("BQ INFORMATION_SCHEMA fetch failed for %s.%s", project, dataset)
            raise RuntimeError(
                f"Failed to fetch INFORMATION_SCHEMA for {project}.{dataset}: {exc}"
            ) from exc
        if not rows:
            raise RuntimeError(
                f"INFORMATION_SCHEMA returned no rows for {project}.{dataset} — "
                f"dataset is empty or service account lacks access"
            )
        tables_map: Dict[str, List[ColumnRef]] = {}
        for r in rows:
            tables_map.setdefault(r["table_name"], []).append(
                ColumnRef(name=r["column_name"], type=r.get("data_type"),
                          description=r.get("description"))
            )
        tables = [
            SourceTable(name=name, columns=cols, origin="upload")  # type: ignore[arg-type]
            for name, cols in tables_map.items()
        ]
        return TargetSchema(
            project=project, dataset=dataset, tables=tables,
            fetched_at=datetime.now(timezone.utc), origin="bigquery_live",
        )


def _split_fqn(fqn: str) -> tuple[Optional[str], Optional[str], str]:
    parts = fqn.split(".")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    return None, None, parts[-1]


async def _to_thread(func, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(func, *args, **kwargs)
