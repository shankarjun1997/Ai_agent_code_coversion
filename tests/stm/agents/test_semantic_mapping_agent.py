"""Tests for core/stm/agents/semantic_mapping_agent.py — L3 SemanticMappingAgent."""
import json

import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.semantic_mapping_agent import (
    SemanticMappingAgent, _build_rule_baseline, _merge_with_llm,
    _extract_columns_from_graph, _parse_llm_mappings,
)
from core.stm.blackboard import (
    CandidateMappings, GateDecision, GraphEdge, GraphNode,
    IntentArtifact, MetadataGraph, StmBlackboard, StageStatus,
    Transformations, ValidationReport,
)
from tests.stm.fake_llm import FakeLLMClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _graph_with_cols() -> MetadataGraph:
    g = MetadataGraph()
    g.nodes = [
        GraphNode(id="pg.pub.customers.id", kind="column", label="id",
                  data_type="integer", nullable=False, dialect="postgres"),
        GraphNode(id="pg.pub.customers.email", kind="column", label="email",
                  data_type="text", nullable=True, dialect="postgres"),
        GraphNode(id="pg.pub.customers.created_at", kind="column", label="created_at",
                  data_type="timestamp", nullable=True, dialect="postgres"),
        GraphNode(id="pg.pub.customers", kind="table", label="customers", dialect="postgres"),
    ]
    return g


def _bb(graph: MetadataGraph = None) -> StmBlackboard:
    return StmBlackboard(
        session_id="s1",
        target_table="dim_customer",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(
            source="freetext", raw_input="load customer dimension",
            entity="customer", action="load", status=StageStatus.ready,
        ),
        metadata_graph=graph or _graph_with_cols(),
        candidate_mappings=CandidateMappings(target_table="dim_customer", target_dataset="wh"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


def _llm_response(rows):
    return json.dumps(rows)


# ── Unit helpers ──────────────────────────────────────────────────────────────

def test_extract_columns_from_graph():
    graph = _graph_with_cols()
    cols = _extract_columns_from_graph(graph)
    assert len(cols) == 3  # only column nodes
    names = {c["name"] for c in cols}
    assert names == {"id", "email", "created_at"}


def test_build_rule_baseline():
    graph = _graph_with_cols()
    baseline = _build_rule_baseline("dim_customer", "wh", graph)
    assert len(baseline) == 3
    assert all(m.rule_baseline for m in baseline)
    types = {m.target_field: m.target_type for m in baseline}
    assert types["id"] == "INT64"
    assert types["email"] == "STRING"
    assert types["created_at"] == "TIMESTAMP"


def test_parse_llm_mappings_plain():
    rows = _parse_llm_mappings('[{"target_field":"id","target_type":"INT64","source_expression":"id","rationale":"exact","llm_confidence":0.95,"cardinality":"1:1"}]')
    assert rows[0]["target_field"] == "id"


def test_parse_llm_mappings_fenced():
    data = json.dumps([{"target_field": "email", "target_type": "STRING",
                        "source_expression": "email", "rationale": "exact",
                        "llm_confidence": 0.95, "cardinality": "1:1"}])
    rows = _parse_llm_mappings(f"```json\n{data}\n```")
    assert rows[0]["target_field"] == "email"


def test_parse_llm_mappings_invalid_raises():
    with pytest.raises(Exception):
        _parse_llm_mappings("not json")


def test_merge_with_llm_replaces_baseline():
    graph = _graph_with_cols()
    baseline = _build_rule_baseline("dim_customer", "wh", graph)
    llm_rows = [
        {"target_field": "email", "target_type": "STRING",
         "source_expression": "email", "rationale": "llm exact",
         "llm_confidence": 0.95, "cardinality": "1:1"},
    ]
    merged = _merge_with_llm(baseline, llm_rows, graph)
    email_mappings = [m for m in merged if m.target_field == "email"]
    assert len(email_mappings) == 1
    assert email_mappings[0].refined_by_llm is True
    assert email_mappings[0].llm_confidence == 0.95


def test_merge_with_llm_keeps_untouched_baseline():
    graph = _graph_with_cols()
    baseline = _build_rule_baseline("dim_customer", "wh", graph)
    llm_rows = [
        {"target_field": "email", "target_type": "STRING",
         "source_expression": "email", "rationale": "llm", "llm_confidence": 0.9, "cardinality": "1:1"},
    ]
    merged = _merge_with_llm(baseline, llm_rows, graph)
    # id and created_at still present
    fields = {m.target_field for m in merged}
    assert "id" in fields
    assert "created_at" in fields


# ── Agent run ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_mapping_agent_populates_rows():
    bb = _bb()
    llm_resp = _llm_response([
        {"target_field": "customer_id", "target_type": "INT64",
         "source_expression": "id", "rationale": "pk", "llm_confidence": 0.95, "cardinality": "1:1"},
        {"target_field": "email_address", "target_type": "STRING",
         "source_expression": "email", "rationale": "email", "llm_confidence": 0.9, "cardinality": "1:1"},
    ])
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[llm_resp]))
    delta = await SemanticMappingAgent().run(ctx)

    assert delta.error is None
    cm: CandidateMappings = delta.updates["candidate_mappings"]
    assert len(cm.rows) > 0


@pytest.mark.asyncio
async def test_semantic_mapping_agent_sets_ready():
    bb = _bb()
    llm_resp = _llm_response([
        {"target_field": "id", "target_type": "INT64",
         "source_expression": "id", "rationale": "exact", "llm_confidence": 0.95, "cardinality": "1:1"},
    ])
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[llm_resp]))
    delta = await SemanticMappingAgent().run(ctx)
    assert delta.updates["candidate_mappings"].status == StageStatus.ready


@pytest.mark.asyncio
async def test_semantic_mapping_agent_advances_to_l4():
    bb = _bb()
    llm_resp = _llm_response([])
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[llm_resp]))
    delta = await SemanticMappingAgent().run(ctx)
    assert delta.updates["current_stage"] == "L4"


@pytest.mark.asyncio
async def test_semantic_mapping_agent_baseline_fallback_on_llm_failure():
    """When LLM fails, baseline mappings are still returned."""
    bb = _bb()

    class _BrokenLLM:
        def complete(self, *a, **kw):
            raise RuntimeError("API down")

    ctx = AgentContext(blackboard=bb, llm=_BrokenLLM())
    delta = await SemanticMappingAgent().run(ctx)
    assert delta.error is None
    cm = delta.updates["candidate_mappings"]
    assert len(cm.rows) == 3  # baseline has 3 cols
    assert all(m.rule_baseline for m in cm.rows)


@pytest.mark.asyncio
async def test_semantic_mapping_agent_baseline_summary():
    bb = _bb()
    llm_resp = _llm_response([
        {"target_field": "email", "target_type": "STRING",
         "source_expression": "email", "rationale": "x", "llm_confidence": 0.9, "cardinality": "1:1"},
    ])
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[llm_resp]))
    delta = await SemanticMappingAgent().run(ctx)
    summary = delta.updates["candidate_mappings"].rule_baseline_summary
    assert "baseline_count" in summary
    assert summary["baseline_count"] == 3
