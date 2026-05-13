"""Tests for core/stm/agents/transformation_agent.py — L4 TransformationAgent."""
import json

import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.transformation_agent import (
    TransformationAgent, _deterministic_floor, _parse_llm_transformations,
)
from core.stm.blackboard import (
    CandidateMapping, CandidateMappings, GateDecision, IntentArtifact,
    MetadataGraph, StmBlackboard, StageStatus, Transformations, ValidationReport,
)
from tests.stm.fake_llm import FakeLLMClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bb(scd_hint=None, mappings=None) -> StmBlackboard:
    cm = CandidateMappings(target_table="dim_customer", target_dataset="wh")
    if mappings:
        cm.rows = mappings
    else:
        cm.rows = [
            CandidateMapping(target_field="customer_id", target_type="INT64",
                             source_expression="id"),
            CandidateMapping(target_field="email_address", target_type="STRING",
                             source_expression="email"),
            CandidateMapping(target_field="created_at", target_type="TIMESTAMP",
                             source_expression="created_at"),
        ]
    return StmBlackboard(
        session_id="s1",
        target_table="dim_customer",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(
            source="freetext",
            raw_input="load customer dimension with history",
            entity="customer",
            scd_hint=scd_hint,
            is_dimension=True,
            status=StageStatus.ready,
        ),
        metadata_graph=MetadataGraph(),
        candidate_mappings=cm,
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


def _llm_response(scd="type2", derived=None, audit=None,
                  idempotency_key="customer_id", partition_field="created_at"):
    return json.dumps({
        "derived_columns": derived or [],
        "scd_strategy": scd,
        "audit_fields": audit or ["_inserted_at", "_updated_at", "_source_system"],
        "idempotency_key": idempotency_key,
        "partition_field": partition_field,
    })


# ── Deterministic floor ───────────────────────────────────────────────────────

def test_floor_scd_from_intent():
    bb = _bb(scd_hint="type2")
    floor = _deterministic_floor(bb.intent, bb.candidate_mappings)
    assert floor["scd_strategy"] == "type2"


def test_floor_scd_defaults_to_type1():
    bb = _bb(scd_hint=None)
    floor = _deterministic_floor(bb.intent, bb.candidate_mappings)
    assert floor["scd_strategy"] == "type1"


def test_floor_idempotency_key_from_id():
    bb = _bb()
    floor = _deterministic_floor(bb.intent, bb.candidate_mappings)
    assert floor["idempotency_key"] == "customer_id"


def test_floor_partition_field_timestamp():
    bb = _bb()
    floor = _deterministic_floor(bb.intent, bb.candidate_mappings)
    assert floor["partition_field"] == "created_at"


def test_floor_audit_fields():
    bb = _bb()
    floor = _deterministic_floor(bb.intent, bb.candidate_mappings)
    assert "_inserted_at" in floor["audit_fields"]


# ── JSON parsing ──────────────────────────────────────────────────────────────

def test_parse_llm_transformations():
    data = {"derived_columns": [], "scd_strategy": "type2",
            "audit_fields": ["_inserted_at"], "idempotency_key": "id", "partition_field": None}
    result = _parse_llm_transformations(json.dumps(data))
    assert result["scd_strategy"] == "type2"


# ── Agent run ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_transformation_agent_advances_to_l5():
    bb = _bb()
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[_llm_response()]))
    delta = await TransformationAgent().run(ctx)
    assert delta.error is None
    assert delta.updates["current_stage"] == "L5"


@pytest.mark.asyncio
async def test_transformation_agent_sets_ready():
    bb = _bb()
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[_llm_response()]))
    delta = await TransformationAgent().run(ctx)
    assert delta.updates["transformations"].status == StageStatus.ready


@pytest.mark.asyncio
async def test_transformation_agent_scd_strategy():
    bb = _bb(scd_hint="type2")
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[_llm_response(scd="type2")]))
    delta = await TransformationAgent().run(ctx)
    assert delta.updates["transformations"].scd_strategy == "type2"


@pytest.mark.asyncio
async def test_transformation_agent_audit_fields_present():
    bb = _bb()
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[_llm_response()]))
    delta = await TransformationAgent().run(ctx)
    tx: Transformations = delta.updates["transformations"]
    assert "_inserted_at" in tx.audit_fields
    assert any(t.kind == "audit" for t in tx.rows)


@pytest.mark.asyncio
async def test_transformation_agent_derived_columns_from_llm():
    bb = _bb()
    derived = [{"target_field": "full_name", "kind": "derived",
                "logic": "CONCAT(first_name, ' ', last_name)",
                "inputs": ["first_name", "last_name"], "rationale": "concatenated name"}]
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[_llm_response(derived=derived)]))
    delta = await TransformationAgent().run(ctx)
    tx = delta.updates["transformations"]
    derived_fields = [t.target_field for t in tx.rows if t.kind == "derived"]
    assert "full_name" in derived_fields


@pytest.mark.asyncio
async def test_transformation_agent_llm_failure_graceful():
    bb = _bb()

    class _BrokenLLM:
        def complete(self, *a, **kw):
            raise RuntimeError("API down")

    ctx = AgentContext(blackboard=bb, llm=_BrokenLLM())
    delta = await TransformationAgent().run(ctx)
    assert delta.error is None
    tx = delta.updates["transformations"]
    # Floor audit fields still present
    assert "_inserted_at" in tx.audit_fields
    assert tx.status == StageStatus.ready


@pytest.mark.asyncio
async def test_transformation_agent_invalid_scd_from_llm_uses_floor():
    """Invalid LLM scd_strategy falls back to floor value."""
    bb = _bb(scd_hint="type2")
    bad_resp = json.dumps({
        "derived_columns": [],
        "scd_strategy": "garbage",
        "audit_fields": ["_inserted_at"],
        "idempotency_key": "customer_id",
        "partition_field": None,
    })
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(responses=[bad_resp]))
    delta = await TransformationAgent().run(ctx)
    # Floor was "type2" (from intent), LLM said "garbage" → fallback to floor
    assert delta.updates["transformations"].scd_strategy == "type2"
