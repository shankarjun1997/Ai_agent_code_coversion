"""L3 — Mapping agent (source-first, batched).

For each source column in the source table, find the single best target
column across the shortlisted target tables. Batched 12 columns per LLM call,
2 concurrent. Each row: source_table, source_column, target_table,
target_column, mapping_type, business_logic (<= 25 words), rationale.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.agents.shortlist_agent import _extract_json
from core.stm.blackboard import MappingRow, StageStatus

logger = logging.getLogger(__name__)


SYSTEM = (
    "You are a data architect mapping a source table's columns into a "
    "destination warehouse. For each source column you pick the single best "
    "target column across the candidate tables. Never fabricate matches; emit "
    "'unused' when no sensible target exists."
)


BATCH_SIZE = 12
CONCURRENCY = 2


class MappingAgent(StmAgent):
    stage = "L3"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        if bb.source_table is None or bb.target_schema is None or bb.shortlist is None:
            return BlackboardDelta.failure("Mapping requires schemas + shortlist")

        picked_tables = {e.table for e in bb.shortlist.rows if e.picked}
        target_compact = [
            {
                "table": t.name,
                "cols": [
                    {k: v for k, v in {"n": c.name, "t": c.type, "d": c.description}.items() if v}
                    for c in t.columns
                ],
            }
            for t in bb.target_schema.tables if t.name in picked_tables
        ]
        if not target_compact:
            return BlackboardDelta.failure("No target tables picked at Gate 1")

        source_cols = bb.source_table.columns
        batches = [source_cols[i:i + BATCH_SIZE] for i in range(0, len(source_cols), BATCH_SIZE)]
        if not batches:
            return BlackboardDelta(updates={"mappings": [], "mapping_status": StageStatus.ready})

        sem = asyncio.Semaphore(CONCURRENCY)
        all_rows: List[MappingRow] = []

        async def map_batch(batch_idx: int, batch) -> List[MappingRow]:
            async with sem:
                rows = await self._map_one_batch(ctx, batch, target_compact)
                if ctx.emit:
                    ctx.emit("mapping_batch_done", {
                        "batch": batch_idx + 1, "total": len(batches),
                        "rows_added": len(rows),
                    })
                return rows

        results = await asyncio.gather(*[map_batch(i, b) for i, b in enumerate(batches)])
        for chunk in results:
            all_rows.extend(chunk)

        return BlackboardDelta(updates={
            "mappings": all_rows,
            "mapping_status": StageStatus.awaiting_review,
        })

    async def _map_one_batch(self, ctx: AgentContext, batch, target_compact) -> List[MappingRow]:
        bb = ctx.blackboard
        src_name = bb.source_table.name  # type: ignore[union-attr]
        batch_compact = [
            {k: v for k, v in {"n": c.name, "t": c.type, "d": c.description}.items() if v}
            for c in batch
        ]
        prompt = (
            "For each SOURCE column below, decide the single best mapping to a "
            "TARGET column. One row per source column — no duplicates, no fan-out.\n\n"
            f"SOURCE TABLE: {src_name}\n"
            f"SOURCE COLUMNS ({len(batch)}):\n{json.dumps(batch_compact, separators=(',', ':'))}\n\n"
            f"CANDIDATE TARGET TABLES:\n{json.dumps(target_compact, separators=(',', ':'))}\n\n"
        )
        if bb.business_context:
            prompt += f"CONTEXT: {bb.business_context}\n\n"
        prompt += (
            "Decision rubric for each source column:\n"
            "1. Look at the source column's name, type, and description.\n"
            "2. Scan all target tables. Find the target column whose name/type/purpose best matches.\n"
            "3. If multiple targets fit, pick the one where this column is MOST CENTRAL (the natural grain), not where it's an FK.\n"
            "4. If there is NO sensible target, emit 'unused' — do not force a match.\n\n"
            "Output one row per source column with these fields:\n"
            "- s: source column name (exactly as given)\n"
            "- tt: target table (or '' if unused)\n"
            "- tc: target column (or '' if unused)\n"
            "- t: mapping type — '1:1', '1:many', 'derived', 'constant', or 'unused'\n"
            "- l: business logic <= 25 words, what the engineer must do (cast, lookup, hash, aggregate, etc.). Empty if unused.\n\n"
            'Return ONLY: {"m":[{"s":"...","tt":"...","tc":"...","t":"...","l":"..."}]}\n'
            f"Exactly {len(batch)} rows."
        )
        try:
            raw = ctx.llm.complete(prompt, system=SYSTEM, max_tokens=4000, temperature=0.0)
            parsed = _extract_json(raw)
            returned = parsed.get("m") or []
        except Exception as exc:
            logger.warning("mapping batch failed: %s", exc)
            return [
                MappingRow(
                    source_table=src_name, source_column=c.name,
                    target_table="", target_column="",
                    mapping_type="unused",
                    business_logic=f"(failed to map: {str(exc)[:80]})",
                    failed=True,
                )
                for c in batch
            ]

        by_name = {str(r.get("s") or "").strip(): r for r in returned}
        rows: List[MappingRow] = []
        for c in batch:
            r = by_name.get(c.name, {})
            tt = (r.get("tt") or "").strip()
            tc = (r.get("tc") or "").strip()
            t = (r.get("t") or "").strip().lower()
            unused = (t == "unused") or not tt or not tc
            mapping_type = "unused" if unused else (t if t in {"1:1", "1:many", "derived", "constant"} else "derived")
            rows.append(MappingRow(
                source_table=src_name,
                source_column=c.name,
                target_table="" if unused else tt,
                target_column="" if unused else tc,
                mapping_type=mapping_type,  # type: ignore[arg-type]
                business_logic=("(no target column receives this source)" if unused else (r.get("l") or "")),
            ))
        return rows
