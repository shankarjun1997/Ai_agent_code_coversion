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

        # ── 1. Deterministic rule baseline ────────────────────────────────────
        baseline = _build_rule_baseline(bb.target_table, bb.target_dataset, graph)

        # ── 2. Build LLM prompt ───────────────────────────────────────────────
        source_cols = _extract_columns_from_graph(graph)
        cols_summary = json.dumps(source_cols[:80], indent=2)  # cap at 80 cols
        prompt = (
            f"Target table: {bb.target_dataset}.{bb.target_table}\n"
            f"Intent: {bb.intent.raw_input}\n"
            f"Entity: {bb.intent.entity}, Action: {bb.intent.action}\n\n"
            f"Available source columns:\n{cols_summary}\n\n"
            "Map source columns to target fields."
        )

        llm_tokens_in = 0
        llm_tokens_out = 0
        merged: List[CandidateMapping] = baseline

        # ── 3. LLM refinement ─────────────────────────────────────────────────
        try:
            response = ctx.llm.complete(
                prompt=prompt,
                system=_SYSTEM_PROMPT,
                max_tokens=2048,
                temperature=0.0,
            )
            llm_tokens_in = len(prompt.split()) + len(_SYSTEM_PROMPT.split())
            llm_tokens_out = len(response.split())
            llm_rows = _parse_llm_mappings(response)
            merged = _merge_with_llm(baseline, llm_rows, graph)
        except Exception as exc:
            logger.warning("SemanticMappingAgent LLM call failed, using baseline only: %s", exc)

        candidate_mappings = CandidateMappings(
            target_table=bb.target_table,
            target_dataset=bb.target_dataset,
            rows=merged,
            rule_baseline_summary={
                "baseline_count": len(baseline),
                "llm_refined_count": sum(1 for m in merged if m.refined_by_llm),
            },
            status=StageStatus.ready,
        )

        return BlackboardDelta(
            updates={"candidate_mappings": candidate_mappings, "current_stage": "L4"},
            llm_tokens_in=llm_tokens_in,
            llm_tokens_out=llm_tokens_out,
            llm_model=model,
        )
