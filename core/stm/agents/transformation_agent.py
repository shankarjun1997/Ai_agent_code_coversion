"""L4 Transformation Synthesis Agent.

Produces Transformations (SCD strategy, audit fields, derived columns,
idempotency key, partition field) from the CandidateMappings + IntentArtifact.

Strategy
--------
1. Deterministic floor: infer SCD strategy, audit fields, and idempotency key
   from intent hints and mapping patterns.
2. LLM refinement: Opus-class LLM fills derived columns and complex expressions
   the deterministic pass cannot infer.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    StageStatus, Transformation, Transformations,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert data engineer specialising in BigQuery transformation patterns.

Given a target table, its candidate field mappings, and intent metadata, produce
a JSON object describing required transformations.

Return ONLY valid JSON (no markdown):
{
  "derived_columns": [
    {
      "target_field": "<field name>",
      "kind": "<derived|scd2|audit|surrogate_key|computed|filter>",
      "logic": "<SQL expression or description>",
      "inputs": ["<source fields>"],
      "rationale": "<brief explanation>"
    }
  ],
  "scd_strategy": "<type1|type2|type3|none>",
  "audit_fields": ["<field names>"],
  "idempotency_key": "<field or expression or null>",
  "partition_field": "<field name or null>"
}

Rules:
- scd_strategy: use intent hint if provided; otherwise infer from table name patterns.
- audit_fields: standard BQ audit columns: _inserted_at, _updated_at, _source_system.
- idempotency_key: typically the primary key or surrogate key.
- partition_field: prefer date/timestamp fields for partitioning.
- derived_columns: only include if genuinely needed; avoid duplication.
"""

# Standard audit fields always injected
_AUDIT_FIELDS = ["_inserted_at", "_updated_at", "_source_system"]

# Surrogate key pattern
_SK_PATTERN = re.compile(r"^(sk_|surrogate_key|dim_key|wh_key)", re.IGNORECASE)
_TS_PATTERN = re.compile(r"(timestamp|date|created_at|updated_at|event_time)", re.IGNORECASE)


def _deterministic_floor(bb_intent, candidate_mappings) -> Dict[str, Any]:
    """Build the deterministic transformation floor."""
    scd = bb_intent.scd_hint or "type1"

    # Find a partition field from candidate mappings
    partition_field = None
    for m in candidate_mappings.rows:
        if _TS_PATTERN.search(m.target_field):
            if m.target_type in ("TIMESTAMP", "DATE"):
                partition_field = m.target_field
                break

    # Idempotency key — look for _id, _key, surrogate key patterns
    idempotency_key = None
    for m in candidate_mappings.rows:
        if m.target_field.endswith("_id") or m.target_field.endswith("_key"):
            idempotency_key = m.target_field
            break
    if idempotency_key is None and candidate_mappings.rows:
        idempotency_key = candidate_mappings.rows[0].target_field

    return {
        "scd_strategy": scd,
        "audit_fields": _AUDIT_FIELDS,
        "idempotency_key": idempotency_key,
        "partition_field": partition_field,
    }


def _parse_llm_transformations(text: str) -> Dict[str, Any]:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


class TransformationAgent(StmAgent):
    """L4 — produces Transformations from CandidateMappings + IntentArtifact."""

    stage = "L4"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        model = ctx.get("llm_model_l4", "opus")

        # ── 1. Deterministic floor ────────────────────────────────────────────
        floor = _deterministic_floor(bb.intent, bb.candidate_mappings)

        # ── 2. Build LLM prompt with BQ target context ────────────────────────
        is_enhance = getattr(bb.intent, "intent_kind", "new") == "enhance_existing"
        from_baseline = {m.target_field.lower() for m in bb.candidate_mappings.rows if getattr(m, "from_baseline", False)}
        mappings_summary = [
            {"target_field": m.target_field, "target_type": m.target_type,
             "source_expression": m.source_expression,
             "from_baseline": bool(getattr(m, "from_baseline", False))}
            for m in bb.candidate_mappings.rows[:50]
        ]
        target_summary = ""
        try:
            from core.stm.tools.bq_tools import render_target_summary
            target_summary = render_target_summary(getattr(bb, "target_graph", None))
        except Exception:
            target_summary = "(target schema unavailable)"

        enhance_note = ""
        if is_enhance and from_baseline:
            enhance_note = (
                f"\nENHANCEMENT MODE: rewrite transformations ONLY for fields NOT in baseline: "
                f"{', '.join(sorted({m.target_field for m in bb.candidate_mappings.rows if not getattr(m,'from_baseline', False)}))}\n"
            )
        prompt = (
            f"Target table: {bb.target_dataset}.{bb.target_table}\n"
            f"Intent: {bb.intent.raw_input}\n"
            f"SCD hint: {bb.intent.scd_hint}\n"
            f"Is dimension: {bb.intent.is_dimension}\n"
            f"## Target schema (live BigQuery)\n{target_summary}\n\n"
            f"Candidate mappings:\n{json.dumps(mappings_summary, indent=2)}{enhance_note}\n\n"
            "Produce the transformation specification. Use dry_run_sql to validate any non-trivial SQL expression you propose."
        )

        derived_rows: List[Transformation] = []
        scd_strategy = floor["scd_strategy"]
        audit_fields = floor["audit_fields"]
        idempotency_key = floor["idempotency_key"]
        partition_field = floor["partition_field"]
        llm_tokens_in = 0
        llm_tokens_out = 0

        # ── 3. LLM refinement (tool-using when available) ─────────────────────
        try:
            from core.stm.tools import BQ_TOOL_SCHEMAS, make_bq_tool_handler
            handler = make_bq_tool_handler()
            if hasattr(ctx.llm, "run_agent"):
                response, tool_history = ctx.llm.run_agent(
                    system=_SYSTEM_PROMPT,
                    user_message=prompt,
                    tools=BQ_TOOL_SCHEMAS,
                    tool_handler=handler,
                    max_tokens=1024,
                )
                if tool_history:
                    logger.info("L4 used %d tool calls", len(tool_history))
            else:
                response = ctx.llm.complete(
                    prompt=prompt,
                    system=_SYSTEM_PROMPT,
                    max_tokens=1024,
                    temperature=0.0,
                )
            llm_tokens_in = len(prompt.split()) + len(_SYSTEM_PROMPT.split())
            llm_tokens_out = len(response.split())
            llm_data = _parse_llm_transformations(response)

            # Merge LLM results — LLM overrides floor for known fields
            scd_strategy = llm_data.get("scd_strategy") or scd_strategy
            if scd_strategy not in ("type1", "type2", "type3", "none"):
                scd_strategy = floor["scd_strategy"]

            llm_audit = llm_data.get("audit_fields") or []
            audit_fields = list(set(_AUDIT_FIELDS) | set(llm_audit))

            idempotency_key = llm_data.get("idempotency_key") or idempotency_key
            partition_field = llm_data.get("partition_field") or partition_field

            for row in llm_data.get("derived_columns") or []:
                kind = row.get("kind", "derived")
                if kind not in ("derived", "scd2", "audit", "surrogate_key", "computed", "filter"):
                    kind = "derived"
                derived_rows.append(Transformation(
                    target_field=row.get("target_field", ""),
                    kind=kind,
                    logic=row.get("logic", ""),
                    inputs=row.get("inputs") or [],
                    rationale=row.get("rationale", ""),
                ))

        except Exception as exc:
            logger.warning("TransformationAgent LLM call failed, using floor only: %s", exc)

        # Always add audit transformations from floor
        for af in audit_fields:
            if not any(t.target_field == af for t in derived_rows):
                derived_rows.append(Transformation(
                    target_field=af,
                    kind="audit",
                    logic=f"CURRENT_TIMESTAMP()  -- {af}",
                    inputs=[],
                    rationale="standard audit field",
                ))

        transformations = Transformations(
            rows=derived_rows,
            scd_strategy=scd_strategy if scd_strategy in ("type1", "type2", "type3", "none") else None,
            audit_fields=audit_fields,
            idempotency_key=idempotency_key,
            partition_field=partition_field,
            status=StageStatus.ready,
        )

        return BlackboardDelta(
            updates={"transformations": transformations, "current_stage": "L5"},
            llm_tokens_in=llm_tokens_in,
            llm_tokens_out=llm_tokens_out,
            llm_model=model,
        )
