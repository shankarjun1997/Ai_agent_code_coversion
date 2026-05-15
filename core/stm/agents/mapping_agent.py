"""L3 — Mapping agent (source-first, batched + mapping_memory few-shot).

Changes from original:
- Batch size / concurrency driven by env (STM_L3_BATCH_SIZE, STM_L3_CONCURRENCY).
- Each batch recalls top-10 mapping_memory rows for its column names (ILIKE).
- Few-shot examples injected into the prompt before the LLM call.
- LLMClient.complete() is sync — wrapped with asyncio.to_thread.
- SSE events emitted via ctx.emit (sync callback) when available.
- mapping_memory table absence or DB error → graceful [] fallback.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.agents.shortlist_agent import _extract_json
from core.stm.blackboard import MappingRow, StageStatus

logger = logging.getLogger(__name__)

# ── Env-driven config ────────────────────────────────────────────────────────

_BATCH_SIZE  = int(os.getenv("STM_L3_BATCH_SIZE",  "12"))
_CONCURRENCY = int(os.getenv("STM_L3_CONCURRENCY", "2"))
_MODEL       = os.getenv("STM_LLM_MODEL_L3", os.getenv("LLM_MODEL", "claude-sonnet-4-6"))

# ── Prompt constants ─────────────────────────────────────────────────────────

SYSTEM = (
    "You are a data architect mapping a source table's columns into a "
    "destination warehouse. For each source column you pick the single best "
    "target column across the candidate tables. Never fabricate matches; emit "
    "'unused' when no sensible target exists."
)

_VALID_TYPES = {"1:1", "1:many", "derived", "constant", "unused"}


# ── mapping_memory recall ────────────────────────────────────────────────────

async def _recall_memory(
    db_url: Optional[str],
    col_names: List[str],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return up to *limit* mapping_memory rows whose source_column ILIKE
    any of the given column names.  Returns [] on any error (table absent,
    no DB URL, etc.).
    """
    if not db_url or not col_names:
        return []
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        # Build ILIKE pattern list
        patterns = [f"%{n}%" for n in col_names]
        clauses = " OR ".join(
            f"source_column ILIKE :p{i}" for i in range(len(patterns))
        )
        query = text(
            f"SELECT source_column, target_table, target_column, "
            f"       mapping_type, business_logic, rationale "
            f"FROM mapping_memory "
            f"WHERE {clauses} "
            f"ORDER BY created_at DESC LIMIT :lim"
        )
        params = {f"p{i}": p for i, p in enumerate(patterns)}
        params["lim"] = limit

        engine = create_async_engine(db_url, echo=False)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(query, params)
                rows = result.fetchall()
        finally:
            await engine.dispose()

        return [
            {
                "source_column": r[0],
                "target_table":  r[1],
                "target_column": r[2],
                "mapping_type":  r[3],
                "business_logic": r[4],
                "rationale":     r[5],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("mapping_memory recall skipped: %s", exc)
        return []


def _format_few_shot(examples: List[Dict[str, Any]]) -> str:
    if not examples:
        return ""
    lines = ["HISTORICAL MAPPINGS (few-shot examples from approved sessions):"]
    for ex in examples:
        lines.append(
            f"  {ex.get('source_column')} -> {ex.get('target_table')}.{ex.get('target_column')}"
            f"  [{ex.get('mapping_type')}] {ex.get('business_logic') or ''}"
        )
    return "\n".join(lines) + "\n\n"


# ── Agent ────────────────────────────────────────────────────────────────────

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
        batches = [
            source_cols[i: i + _BATCH_SIZE]
            for i in range(0, len(source_cols), _BATCH_SIZE)
        ]
        if not batches:
            return BlackboardDelta(updates={"mappings": [], "mapping_status": StageStatus.ready})

        db_url: Optional[str] = os.getenv("DATABASE_URL")
        sem = asyncio.Semaphore(_CONCURRENCY)
        all_rows: List[MappingRow] = []

        async def map_batch(batch_idx: int, batch) -> List[MappingRow]:
            async with sem:
                col_names = [c.name for c in batch]
                memory    = await _recall_memory(db_url, col_names)
                rows      = await self._map_one_batch(ctx, batch, target_compact, memory)
                if ctx.emit:
                    try:
                        ctx.emit("mapping_batch_done", {
                            "batch":      batch_idx + 1,
                            "total":      len(batches),
                            "rows_added": len(rows),
                            "memory_hits": len(memory),
                        })
                    except Exception:
                        pass
                return rows

        results = await asyncio.gather(*[map_batch(i, b) for i, b in enumerate(batches)])
        for chunk in results:
            all_rows.extend(chunk)

        return BlackboardDelta(updates={
            "mappings":       all_rows,
            "mapping_status": StageStatus.awaiting_review,
        })

    async def _map_one_batch(
        self,
        ctx: AgentContext,
        batch,
        target_compact: List[Dict],
        memory: List[Dict[str, Any]],
    ) -> List[MappingRow]:
        bb       = ctx.blackboard
        src_name = bb.source_table.name  # type: ignore[union-attr]
        batch_compact = [
            {k: v for k, v in {"n": c.name, "t": c.type, "d": c.description}.items() if v}
            for c in batch
        ]
        few_shot = _format_few_shot(memory)

        prompt = (
            "For each SOURCE column below, decide the single best mapping to a "
            "TARGET column. One row per source column — no duplicates, no fan-out.\n\n"
            f"SOURCE TABLE: {src_name}\n"
            f"SOURCE COLUMNS ({len(batch)}):\n"
            f"{json.dumps(batch_compact, separators=(',', ':'))}\n\n"
            f"CANDIDATE TARGET TABLES:\n"
            f"{json.dumps(target_compact, separators=(',', ':'))}\n\n"
        )
        if bb.business_context:
            prompt += f"CONTEXT: {bb.business_context}\n\n"
        if few_shot:
            prompt += few_shot
        prompt += (
            "Decision rubric for each source column:\n"
            "1. Check the historical mappings above first — prefer approved patterns.\n"
            "2. Look at the source column's name, type, and description.\n"
            "3. Scan all target tables. Find the target column whose name/type/purpose best matches.\n"
            "4. If multiple targets fit, pick where this column is MOST CENTRAL (natural grain), not an FK.\n"
            "5. If there is NO sensible target, emit 'unused' — do not force a match.\n\n"
            "Output one row per source column with these fields:\n"
            "- s: source column name (exactly as given)\n"
            "- tt: target table (or '' if unused)\n"
            "- tc: target column (or '' if unused)\n"
            "- t: mapping type — '1:1', '1:many', 'derived', 'constant', or 'unused'\n"
            "- l: business logic <=25 words (cast, lookup, hash, aggregate, etc.). Empty if unused.\n"
            "- r: one-sentence rationale for the choice. Empty if unused.\n\n"
            'Return ONLY: {"m":[{"s":"...","tt":"...","tc":"...","t":"...","l":"...","r":"..."}]}\n'
            f"Exactly {len(batch)} rows."
        )

        # LLMClient.complete() is sync — run in thread to stay async-safe
        try:
            raw = await asyncio.to_thread(
                ctx.llm.complete,
                prompt,
                system=SYSTEM,
                max_tokens=4000,
                temperature=0.0,
            )
            parsed   = _extract_json(raw)
            returned = parsed.get("m") or []
        except Exception as exc:
            logger.warning("L3 batch failed (%s cols): %s", len(batch), exc)
            return [
                MappingRow(
                    source_table=src_name,
                    source_column=c.name,
                    target_table="",
                    target_column="",
                    mapping_type="unused",
                    business_logic=f"(batch failed: {str(exc)[:80]})",
                    failed=True,
                )
                for c in batch
            ]

        by_name = {str(r.get("s") or "").strip(): r for r in returned}
        rows: List[MappingRow] = []
        for c in batch:
            r  = by_name.get(c.name, {})
            tt = (r.get("tt") or "").strip()
            tc = (r.get("tc") or "").strip()
            t  = (r.get("t")  or "").strip().lower()
            unused = (t == "unused") or not tt or not tc
            mapping_type = (
                "unused" if unused
                else (t if t in _VALID_TYPES else "derived")
            )
            rows.append(MappingRow(
                source_table=src_name,
                source_column=c.name,
                target_table=""  if unused else tt,
                target_column="" if unused else tc,
                mapping_type=mapping_type,  # type: ignore[arg-type]
                business_logic=(
                    "(no target column receives this source)"
                    if unused else (r.get("l") or "")
                ),
                rationale=(None if unused else (r.get("r") or None)),
            ))
        return rows
