"""Tests for core/stm/scoring.py — heuristic confidence scoring."""
import pytest

from core.stm.blackboard import (
    CandidateMapping, GraphEdge, MetadataGraph,
)
from core.stm.scoring import (
    name_similarity, type_compatibility, fk_evidence,
    profile_overlap, score_mapping,
)


# ── name_similarity ───────────────────────────────────────────────────────────

def test_name_similarity_exact():
    assert name_similarity("customer_id", "customer_id") == 1.0


def test_name_similarity_close():
    score = name_similarity("cust_id", "customer_id")
    assert 0.4 < score < 1.0


def test_name_similarity_unrelated():
    score = name_similarity("account_balance", "event_timestamp")
    assert score < 0.4


def test_name_similarity_empty():
    assert name_similarity("", "customer_id") == 0.0


# ── type_compatibility ────────────────────────────────────────────────────────

def test_type_exact_match():
    assert type_compatibility("STRING", "STRING") == 1.0


def test_type_compatible_pair():
    assert type_compatibility("INT64", "NUMERIC") == 0.7


def test_type_incompatible():
    assert type_compatibility("BYTES", "INT64") == 0.0


def test_type_timestamp_to_string():
    assert type_compatibility("TIMESTAMP", "STRING") == 0.7


# ── fk_evidence ──────────────────────────────────────────────────────────────

def _graph_with_fk():
    graph = MetadataGraph()
    graph.edges.append(GraphEdge(
        src="pg.public.orders.customer_id",
        dst="pg.public.customers.id",
        kind="fk",
    ))
    return graph


def test_fk_evidence_hit():
    graph = _graph_with_fk()
    score = fk_evidence(
        ["pg.public.orders.customer_id"],
        "id",
        graph,
    )
    assert score > 0.0


def test_fk_evidence_no_match():
    graph = _graph_with_fk()
    score = fk_evidence(["pg.public.products.sku"], "email", graph)
    assert score == 0.0


def test_fk_evidence_empty_graph():
    assert fk_evidence(["node1"], "field", MetadataGraph()) == 0.0


# ── profile_overlap ───────────────────────────────────────────────────────────

def test_profile_overlap_full():
    assert profile_overlap({"min": 0, "max": 100}, {"min": 0, "max": 100}) == 1.0


def test_profile_overlap_partial():
    score = profile_overlap({"min": 0, "max": 100}, {"min": 50, "max": 150})
    assert 0.0 < score < 1.0


def test_profile_overlap_no_overlap():
    assert profile_overlap({"min": 0, "max": 10}, {"min": 20, "max": 30}) == 0.0


def test_profile_overlap_none():
    assert profile_overlap(None, {"min": 0, "max": 10}) == 0.0


# ── score_mapping ensemble ────────────────────────────────────────────────────

def _mapping(target_field: str, source_expr: str = "", llm_conf: float = 0.0):
    return CandidateMapping(
        target_field=target_field,
        target_type="STRING",
        source_expression=source_expr,
        llm_confidence=llm_conf if llm_conf else None,
    )


def test_score_mapping_high_band():
    m = _mapping("customer_id", source_expr="customer_id", llm_conf=0.95)
    result = score_mapping(m, MetadataGraph(), source_bq_type="INT64", target_bq_type="INT64")
    assert result.band == "high"
    assert result.final >= 0.70


def test_score_mapping_low_band():
    m = _mapping("some_obscure_field", source_expr="xyz_123")
    result = score_mapping(m, MetadataGraph(), source_bq_type="BYTES", target_bq_type="INT64")
    assert result.band == "low"


def test_score_mapping_returns_confidence_score():
    from core.stm.blackboard import ConfidenceScore
    m = _mapping("email", source_expr="email_address")
    result = score_mapping(m, MetadataGraph(), source_bq_type="STRING", target_bq_type="STRING")
    assert isinstance(result, ConfidenceScore)
    assert result.target_field == "email"
    assert 0.0 <= result.final <= 1.0


def test_score_mapping_band_medium():
    # name_sim("order_date","order_date")=1.0, type_compat TIMESTAMP→DATE=0.7
    # final = 0.4*1.0 + 0.3*0.7 = 0.61 → medium/high
    m = _mapping("order_date", source_expr="order_date")
    result = score_mapping(m, MetadataGraph(), source_bq_type="TIMESTAMP", target_bq_type="DATE")
    assert result.band in ("medium", "high")
