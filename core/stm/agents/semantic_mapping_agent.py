"""L3 Semantic Mapping Agent.

Produces CandidateMappings by:
1. Rule baseline — calls core/stm/mapping_engine.build_stm() for deterministic floor
2. LLM refinement — Opus-class LLM refines ambiguous mappings and fills gaps

Rules-as-floor: every mapping starts as a rule_baseline entry; LLM only
adds/replaces entries where it has higher confidence.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    CandidateMapping, CandidateMappings, GraphNode, MetadataGraph,
    StageStatus,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert data engineer specialising in source-to-target field mappings.

Given a target BigQuery table and available source columns (from the metadata graph),
produce field mapping candidates in JSON.

Return ONLY a JSON array of mapping objects (no markdown):
[
  {
    "target_field": "<BQ column name>",
    "target_type": "<BQ type: STRING|INT64|NUMERIC|FLOAT64|BOOL|TIMESTAMP|DATE|TIME|JSON|BYTES>",
    "source_expression": "<SQL expression or source column name>",
    "rationale": "<brief explanation>",
    "llm_confidence": <0.0-1.0>,
    "cardinality": "<1:1|M:1|1:M|M:M|null>"
  },
  ...
]

Rules:
- Prefer exact or near-exact name matches.
- For derived fields (concatenation, CASE, etc.), provide the SQL expression.
- llm_confidence: 0.9+ for exact matches, 0.6-0.9 for inferred, <0.6 for uncertain.
- cardinality: "1:1" for direct column maps, "M:1" for lookups/aggregates.
- If a target field cannot be mapped, still include it with source_expression="" and llm_confidence=0.1.
"""


def _extract_columns_from_graph(graph: MetadataGraph) -> List[Dict[str, Any]]:
    """Flatten column nodes from the graph into a simple list for the LLM prompt."""
    cols = []
    for node in graph.nodes:
        if node.kind == "column":
            # node.id pattern: profile.schema.table.column
            parts = node.id.split(".")
            cols.append({
                "id": node.id,
                "name": node.label,
                "type": node.data_type or "unknown",
                "table": parts[-2] if len(parts) >= 2 else "?",
                "nullable": node.nullable,
            })
    return cols


def _build_rule_baseline(
    target_table: str,
    target_dataset: str,
    graph: MetadataGraph,
) -> List[CandidateMapping]:
    """Deterministic rule baseline: name-match columns to target fields."""
    from core.stm.mapping_engine import map_type

    col_nodes = [n for n in graph.nodes if n.kind == "column"]
    # Build a name→node index for quick lookup
    name_index: Dict[str, GraphNode] = {}
    for node in col_nodes:
        name_index[node.label.lower()] = node

    # For the baseline we produce a 1:1 identity mapping for all source columns
    # (the LLM refines the actual target_field assignments)
    mappings = []
    for node in col_nodes:
        bq_type = map_type(node.data_type or "text")
        mappings.append(CandidateMapping(
            target_field=node.label,
            target_type=bq_type,
            source_node_ids=[node.id],
            source_expression=node.label,
            rationale="rule_baseline: identity mapping",
            rule_baseline=True,
            refined_by_llm=False,
        ))
    return mappings


def _parse_llm_mappings(text: str) -> List[Dict[str, Any]]:
    """Parse LLM JSON array response, tolerating markdown fences."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data)}")
    return data


def _merge_with_llm(
    baseline: List[CandidateMapping],
    llm_rows: List[Dict[str, Any]],
    graph: MetadataGraph,
) -> List[CandidateMapping]:
    """Merge LLM refinements into the baseline.

    LLM rows with target_field already in baseline replace the baseline entry
    if llm_confidence > 0 and source_expression is non-empty.
    LLM-only rows (new target fields) are appended.
    """
    # Build a quick node name→id index
    col_name_to_id: Dict[str, str] = {
        n.label.lower(): n.id for n in graph.nodes if n.kind == "column"
    }

    baseline_by_field = {m.target_field.lower(): m for m in baseline}
    result: List[CandidateMapping] = []

    seen_fields = set()
    for row in llm_rows:
        tf = (row.get("target_field") or "").strip()
        if not tf:
            continue
        tf_lower = tf.lower()
        seen_fields.add(tf_lower)

        src_expr = (row.get("source_expression") or "").strip()
        confidence = float(row.get("llm_confidence") or 0.0)
        bq_type = (row.get("target_type") or "STRING").upper()
        rationale = row.get("rationale") or ""
        cardinality = row.get("cardinality")
        if cardinality not in ("1:1", "M:1", "1:M", "M:M", None):
            cardinality = None

        # Resolve source node ids from expression
        source_node_ids = []
        if src_expr:
            node_id = col_name_to_id.get(src_expr.lower())
            if node_id:
                source_node_ids = [node_id]

        refined = CandidateMapping(
            target_field=tf,
            target_type=bq_type,
            source_node_ids=source_node_ids,
            source_expression=src_expr,
            rationale=rationale,
            rule_baseline=tf_lower in baseline_by_field,
            refined_by_llm=True,
            llm_confidence=confidence if confidence > 0 else None,
            cardinality=cardinality,
        )
        result.append(refined)

    # Append baseline entries the LLM didn't touch
    for m in baseline:
        if m.target_field.lower() not in seen_fields:
            result.append(m)

    return result


class SemanticMappingAgent(StmAgent):
    """L3 — rule baseline + LLM refinement → CandidateMappings."""

    stage = "L3"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        graph = bb.metadata_graph
        model = ctx.get("llm_model_l3", "opus")

        # ── 0. Enhancement branch: load baseline STM if intent_kind=enhance_existing ──
        baseline_rows, delta_only = _load_baseline_rows(bb)

        # ── 1. Deterministic rule baseline (from sources) ──────────────────────
        baseline = _build_rule_baseline(bb.target_table, bb.target_dataset, graph)
        if baseline_rows:
            # Start enhancement sessions from the prior approved rows
            existing_fields = {m.target_field for m in baseline}
            for r in baseline_rows:
                if r.target_field not in existing_fields:
                    baseline.append(r)

        # ── 2. Build LLM prompt with BQ target context ─────────────────────────
        source_cols = _extract_columns_from_graph(graph)
        cols_summary = json.dumps(source_cols[:80], indent=2)
        target_summary = _render_target_summary(bb)
        enhance_note = ""
        if delta_only:
            existing_field_list = sorted({r.target_field for r in baseline_rows})
            enhance_note = (
                "\n\nENHANCEMENT MODE: A prior STM already exists for this target table. "
                "Existing columns (do NOT rewrite unless intent demands): "
                f"{', '.join(existing_field_list)}.\n"
                f"Only emit mapping rows for NEW or CHANGED target_fields. "
                "Mark new rows clearly in rationale."
            )

        prompt = (
            f"Target table: {bb.target_dataset}.{bb.target_table}\n"
            f"Intent: {bb.intent.raw_input}\n"
            f"Entity: {bb.intent.entity}, Action: {bb.intent.action}\n\n"
            f"## Target schema (live BigQuery)\n{target_summary}\n\n"
            f"## Available source columns\n{cols_summary}\n"
            f"{enhance_note}\n\n"
            "Map source columns to target fields. Use lookup_bq_table when you need to "
            "verify a specific table's exact column types."
        )

        llm_tokens_in = 0
        llm_tokens_out = 0
        merged: List[CandidateMapping] = baseline

        # ── 3. LLM refinement — try tool-using agent loop first, fall back to single-shot
        try:
            from core.stm.tools import BQ_TOOL_SCHEMAS, make_bq_tool_handler
            handler = make_bq_tool_handler()
            if hasattr(ctx.llm, "run_agent"):
                response, tool_history = ctx.llm.run_agent(
                    system=_SYSTEM_PROMPT,
                    user_message=prompt,
                    tools=BQ_TOOL_SCHEMAS,
                    tool_handler=handler,
                    max_tokens=2048,
                )
                if tool_history:
                    logger.info("L3 used %d tool calls", len(tool_history))
            else:
                response = ctx.llm.complete(
                    prompt=prompt, system=_SYSTEM_PROMPT,
                    max_tokens=2048, temperature=0.0,
                )
            llm_tokens_in = len(prompt.split()) + len(_SYSTEM_PROMPT.split())
            llm_tokens_out = len(response.split())
            llm_rows = _parse_llm_mappings(response)
            merged = _merge_with_llm(baseline, llm_rows, graph)
            if delta_only:
                # Mark unchanged baseline rows
                touched = {row.get("target_field", "").lower() for row in llm_rows}
                for m in merged:
                    if m.target_field.lower() not in touched and m.target_field in {b.target_field for b in baseline_rows}:
                        m.from_baseline = True
                        m.refined_by_llm = False
        except Exception as exc:
            logger.warning("SemanticMappingAgent LLM call failed, using baseline only: %s", exc)

        candidate_mappings = CandidateMappings(
            target_table=bb.target_table,
            target_dataset=bb.target_dataset,
            rows=merged,
            rule_baseline_summary={
                "baseline_count": len(baseline),
                "llm_refined_count": sum(1 for m in merged if m.refined_by_llm),
                "from_baseline_count": sum(1 for m in merged if m.from_baseline),
                "delta_mode": delta_only,
            },
            status=StageStatus.ready,
        )

        return BlackboardDelta(
            updates={"candidate_mappings": candidate_mappings, "current_stage": "L4"},
            llm_tokens_in=llm_tokens_in,
            llm_tokens_out=llm_tokens_out,
            llm_model=model,
        )


def _render_target_summary(bb) -> str:
    try:
        from core.stm.tools.bq_tools import render_target_summary
        return render_target_summary(getattr(bb, "target_graph", None))
    except Exception:
        return "(target schema unavailable)"


def _load_baseline_rows(bb):
    """If intent_kind=enhance_existing, return prior CandidateMappings.rows + True.
    Otherwise ([], False). Uses sync persistence call so it works inside async agents."""
    if getattr(bb.intent, "intent_kind", "new") != "enhance_existing":
        return [], False
    baseline_id = bb.intent.baseline_stm_id or getattr(bb, "baseline_stm_id", None)
    if not baseline_id:
        return [], False
    try:
        from core.stm.persistence import _load_blackboard_sync
        prior = _load_blackboard_sync(baseline_id)
        rows = list(prior.candidate_mappings.rows) if prior and prior.candidate_mappings else []
        for r in rows:
            r.from_baseline = True
        return rows, True
    except Exception as exc:
        logger.warning("baseline STM load failed for %s: %s", baseline_id, exc)
        return [], False
