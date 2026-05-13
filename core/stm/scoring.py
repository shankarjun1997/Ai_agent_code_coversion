"""Ensemble confidence scoring for STM candidate mappings.

All functions are deterministic — no LLM calls.  The ValidationAgent (L5)
calls these to produce ConfidenceScore per target field.

Scoring components
------------------
name_similarity     rapidfuzz token_sort_ratio on normalised column names
type_compatibility  exact/compatible BigQuery type pairs
fk_evidence         bonus when the MetadataGraph contains an FK/join edge
profile_overlap     data-profile value-range overlap (optional, 0.0 if absent)

Final score
-----------
    final = 0.40 * name_sim + 0.30 * type_compat + 0.20 * fk_ev + 0.10 * prof_overlap

Band thresholds: high >= 0.70, medium >= 0.45, low < 0.45
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from rapidfuzz import fuzz

from core.stm.blackboard import (
    CandidateMapping, ConfidenceScore, GraphEdge, MetadataGraph,
)


# ── Weights ───────────────────────────────────────────────────────────────────
_W_NAME = 0.40
_W_TYPE = 0.30
_W_FK   = 0.20
_W_PROF = 0.10

# ── Band thresholds ───────────────────────────────────────────────────────────
_HIGH   = 0.70
_MEDIUM = 0.45


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise(name: str) -> str:
    """Lower-case, collapse non-alphanum to spaces."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


# Compatible BigQuery type pairs (source → target).
_COMPAT: Dict[str, set[str]] = {
    "STRING":    {"STRING", "JSON"},
    "INT64":     {"INT64", "NUMERIC", "FLOAT64"},
    "NUMERIC":   {"NUMERIC", "FLOAT64", "INT64"},
    "FLOAT64":   {"FLOAT64", "NUMERIC"},
    "BOOL":      {"BOOL", "INT64"},
    "TIMESTAMP": {"TIMESTAMP", "DATE", "TIME", "STRING"},
    "DATE":      {"DATE", "TIMESTAMP", "STRING"},
    "TIME":      {"TIME", "STRING"},
    "JSON":      {"JSON", "STRING"},
    "BYTES":     {"BYTES"},
}


# ── Individual scoring functions ──────────────────────────────────────────────

def name_similarity(source_col: str, target_col: str) -> float:
    """0.0–1.0 name-based similarity using rapidfuzz token_sort_ratio."""
    src = _normalise(source_col)
    tgt = _normalise(target_col)
    if not src or not tgt:
        return 0.0
    return fuzz.token_sort_ratio(src, tgt) / 100.0


def type_compatibility(source_bq_type: str, target_bq_type: str) -> float:
    """1.0 exact match, 0.7 compatible pair, 0.0 incompatible."""
    s = source_bq_type.upper().strip()
    t = target_bq_type.upper().strip()
    if s == t:
        return 1.0
    if t in _COMPAT.get(s, set()):
        return 0.7
    return 0.0


def fk_evidence(
    source_node_ids: List[str],
    target_field: str,
    graph: MetadataGraph,
) -> float:
    """0.8 if any FK/join-candidate edge connects source nodes to target_field."""
    if not source_node_ids or not graph.edges:
        return 0.0
    src_set = set(source_node_ids)
    tgt_lower = target_field.lower()
    for edge in graph.edges:
        if edge.kind in ("fk", "join_candidate"):
            # Check if any source node participates in this edge
            edge_nodes = {edge.src, edge.dst}
            if src_set & edge_nodes:
                # The other end of the edge — check if target_field appears in it
                other_ends = edge_nodes - src_set
                for node_id in other_ends:
                    if tgt_lower in node_id.lower().split("."):
                        return 0.8
                    # also match if target field is a suffix of the node id
                    if node_id.lower().endswith(f".{tgt_lower}") or node_id.lower() == tgt_lower:
                        return 0.8
                # FK chain within source set
                if src_set & {edge.src} and src_set & {edge.dst}:
                    return 0.4
                # Any participation in an FK edge is still weak evidence
                return 0.3
    return 0.0


def profile_overlap(source_profile: Optional[Dict], target_profile: Optional[Dict]) -> float:
    """Numeric range overlap ratio — 0.0 if profiles absent or non-numeric."""
    if not source_profile or not target_profile:
        return 0.0
    try:
        s_min = float(source_profile.get("min", 0))
        s_max = float(source_profile.get("max", 0))
        t_min = float(target_profile.get("min", 0))
        t_max = float(target_profile.get("max", 0))
    except (TypeError, ValueError):
        return 0.0
    if s_max <= s_min or t_max <= t_min:
        return 0.0
    overlap = max(0.0, min(s_max, t_max) - max(s_min, t_min))
    union = max(s_max, t_max) - min(s_min, t_min)
    return overlap / union if union > 0 else 0.0


def _band(score: float) -> str:
    if score >= _HIGH:
        return "high"
    if score >= _MEDIUM:
        return "medium"
    return "low"


# ── Ensemble scorer ───────────────────────────────────────────────────────────

def score_mapping(
    mapping: CandidateMapping,
    graph: MetadataGraph,
    *,
    source_bq_type: str = "STRING",
    target_bq_type: str = "STRING",
    source_profile: Optional[Dict] = None,
    target_profile: Optional[Dict] = None,
) -> ConfidenceScore:
    """Produce a ConfidenceScore for a single CandidateMapping row."""
    # Derive source column name from first node id (e.g. "pg.public.users.email" → "email")
    source_col = mapping.source_expression or (
        mapping.source_node_ids[0].split(".")[-1] if mapping.source_node_ids else ""
    )

    name_sim  = name_similarity(source_col, mapping.target_field)
    type_comp = type_compatibility(source_bq_type, target_bq_type)
    fk_ev     = fk_evidence(mapping.source_node_ids, mapping.target_field, graph)
    prof_ol   = profile_overlap(source_profile, target_profile)

    # Inject LLM confidence if available (replaces name_sim as dominant signal)
    llm = mapping.llm_confidence or 0.0
    if llm > 0.0:
        final = 0.35 * llm + 0.25 * name_sim + 0.25 * type_comp + 0.15 * fk_ev
    else:
        final = _W_NAME * name_sim + _W_TYPE * type_comp + _W_FK * fk_ev + _W_PROF * prof_ol

    final = min(1.0, max(0.0, final))

    return ConfidenceScore(
        target_field=mapping.target_field,
        llm_score=llm,
        name_sim_score=name_sim,
        type_compat_score=type_comp,
        fk_evidence_score=fk_ev,
        profile_overlap_score=prof_ol,
        final=final,
        band=_band(final),
    )
