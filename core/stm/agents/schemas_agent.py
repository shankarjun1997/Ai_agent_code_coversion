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

        # Fast path: batch sessions pre-populate catalog IDs — load both sides
        # from the catalog DB without hitting Databricks/BQ live APIs.
        if (
            bb.source_table is None or bb.target_schema is None
        ) and bb.catalog_source_id and bb.catalog_target_id:
            src, tgt = await self._resolve_from_catalog(bb)
            if src is not None and bb.source_table is None:
                updates["source_table"] = src
            if tgt is not None and bb.target_schema is None:
                updates["target_schema"] = tgt
            # Re-read from updates so the checks below work correctly.
            source_table = updates.get("source_table") or bb.source_table
            target_schema = updates.get("target_schema") or bb.target_schema
        else:
            source_table = bb.source_table
            target_schema = bb.target_schema

        if source_table is None:
            source_table = await self._resolve_source(ctx)
            if source_table is not None:
                updates["source_table"] = source_table

        if target_schema is None:
            target_schema = await self._resolve_target(ctx)
            if target_schema is not None:
                updates["target_schema"] = target_schema

        # Final resolution check — merge updates with existing blackboard state.
        resolved_source = updates.get("source_table") or bb.source_table
        resolved_target = updates.get("target_schema") or bb.target_schema

        if resolved_source is None and resolved_target is None:
            return BlackboardDelta.failure(
                "No source or target provided — upload files or set databricks/bq config"
            )
        if resolved_source is None:
            return BlackboardDelta.failure("Source table not provided")
        if resolved_target is None:
            return BlackboardDelta.failure("Target schema not provided")

        updates["source_table"] = resolved_source
        updates["target_schema"] = resolved_target
        return BlackboardDelta(updates=updates)

    # ── catalog fast path (batch sessions) ──────────────────────────────────

    async def _resolve_from_catalog(
        self, bb
    ) -> tuple[Optional[SourceTable], Optional[TargetSchema]]:
        """Load source + target schemas from the catalog DB.

        Used for batch sessions where the batch orchestrator pre-populates
        catalog_source_id, catalog_target_id, and catalog_source_table_id on
        the blackboard. Falls through (returns None) if a catalog entry is
        missing or the requested table is not found.
        """
        from core.catalog.persistence import load_source_catalog, load_target_catalog

        src_result: Optional[SourceTable] = None
        tgt_result: Optional[TargetSchema] = None

        # --- source side ---
        try:
            src_catalog = await load_source_catalog(bb.catalog_source_id)
            table_id = bb.catalog_source_table_id
            src_row = next(
                (t for t in src_catalog.get("tables", []) if t["id"] == table_id),
                None,
            )
            if src_row is None and bb.source_table_name_hint:
                # Fallback: match by table name if ID lookup misses.
                src_row = next(
                    (
                        t for t in src_catalog.get("tables", [])
                        if t["table_name"] == bb.source_table_name_hint
                    ),
                    None,
                )
            if src_row is not None:
                raw_cols = src_row.get("columns") or []
                columns = [
                    ColumnRef(
                        name=c.get("name") or c.get("column_name", ""),
                        type=c.get("type") or c.get("data_type"),
                        description=c.get("description") or c.get("comment"),
                    )
                    for c in raw_cols
                ]
                src_result = SourceTable(
                    name=src_row["table_name"],
                    columns=columns,
                    origin="upload",
                    schema_name=src_row.get("schema_name"),
                )
                logger.info(
                    "schemas_agent: loaded source %s from catalog (id=%s, %d cols)",
                    src_row["table_name"], bb.catalog_source_id, len(columns),
                )
            else:
                logger.warning(
                    "schemas_agent: catalog_source_table_id=%s not found in catalog %s — "
                    "will fall through to live fetch",
                    table_id, bb.catalog_source_id,
                )
        except KeyError:
            logger.warning(
                "schemas_agent: source catalog %s not found — falling through",
                bb.catalog_source_id,
            )
        except Exception as exc:
            logger.warning(
                "schemas_agent: catalog source load failed (%s) — falling through", exc
            )

        # --- target side ---
        try:
            tgt_catalog = await load_target_catalog(bb.catalog_target_id)
            raw_tables = tgt_catalog.get("tables", [])
            tgt_tables = [
                SourceTable(
                    name=t["table_name"],
                    columns=[
                        ColumnRef(
                            name=c.get("name") or c.get("column_name", ""),
                            type=c.get("type") or c.get("data_type"),
                            description=c.get("description"),
                        )
                        for c in (t.get("columns") or [])
                    ],
                    origin="upload",
                )
                for t in raw_tables
            ]
            tgt_result = TargetSchema(
                project=tgt_catalog.get("project", ""),
                dataset=tgt_catalog.get("dataset", ""),
                tables=tgt_tables,
                fetched_at=datetime.now(timezone.utc),
                origin="upload",
            )
            logger.info(
                "schemas_agent: loaded target catalog %s (%d tables)",
                bb.catalog_target_id, len(tgt_tables),
            )
        except KeyError:
            logger.warning(
                "schemas_agent: target catalog %s not found — falling through",
                bb.catalog_target_id,
            )
        except Exception as exc:
            logger.warning(
                "schemas_agent: catalog target load failed (%s) — falling through", exc
            )

        return src_result, tgt_result

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
