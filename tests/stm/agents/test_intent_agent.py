"""Tests for core/stm/agents/intent_agent.py — L1 Intent Extraction."""
import json

import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.intent_agent import IntentAgent, _keyword_floor, _parse_llm_json
from core.stm.blackboard import (
    CandidateMappings, GateDecision, IntentArtifact, MetadataGraph,
    StmBlackboard, StageStatus, Transformations, ValidationReport,
)
from tests.stm.fake_llm import FakeLLMClient


def _bb(raw_input: str = "load customer dimension", source: str = "freetext") -> StmBlackboard:
    return StmBlackboard(
        session_id="s1",
        target_table="dim_customer",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source=source, raw_input=raw_input),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="dim_customer", target_dataset="wh"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


def _llm_response(entity="customer", action="load", is_dim=True, is_fact=False,
                  scd_hint=None, filters=None, grain_hint=None, keywords=None):
    return json.dumps({
        "entity": entity,
        "action": action,
        "is_dimension": is_dim,
        "is_fact": is_fact,
        "scd_hint": scd_hint,
        "filters": filters or [],
        "grain_hint": grain_hint,
        "extracted_keywords": keywords or [],
    })


def _ctx(bb, responses=None):
    return AgentContext(blackboard=bb, llm=FakeLLMClient(responses=responses or [""]))


# ── Deterministic floor ───────────────────────────────────────────────────────

def test_keyword_floor_scd2():
    floor = _keyword_floor("track history of customer changes over time")
    assert floor["scd_hint"] == "type2"


def test_keyword_floor_dimension():
    floor = _keyword_floor("load customer dimension table")
    assert floor["is_dimension"] is True


def test_keyword_floor_fact():
    floor = _keyword_floor("load order transactions fact table")
    assert floor["is_fact"] is True


def test_keyword_floor_plain():
    floor = _keyword_floor("move some data")
    assert floor["scd_hint"] is None
    assert floor["is_dimension"] is False


# ── JSON parsing ──────────────────────────────────────────────────────────────

def test_parse_llm_json_plain():
    result = _parse_llm_json('{"entity": "order"}')
    assert result["entity"] == "order"


def test_parse_llm_json_fenced():
    result = _parse_llm_json('```json\n{"entity": "product"}\n```')
    assert result["entity"] == "product"


def test_parse_llm_json_invalid_raises():
    with pytest.raises(Exception):
        _parse_llm_json("not json")


# ── Agent run ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intent_agent_populates_entity():
    bb = _bb("load customer dimension")
    ctx = _ctx(bb, responses=[_llm_response(entity="customer", is_dim=True)])
    delta = await IntentAgent().run(ctx)
    assert delta.error is None
    assert delta.updates["intent"].entity == "customer"


@pytest.mark.asyncio
async def test_intent_agent_sets_stage_ready():
    bb = _bb("load orders fact table")
    ctx = _ctx(bb, responses=[_llm_response(entity="order", is_fact=True)])
    delta = await IntentAgent().run(ctx)
    assert delta.updates["intent"].status == StageStatus.ready


@pytest.mark.asyncio
async def test_intent_agent_advances_stage():
    bb = _bb("load customer dimension")
    ctx = _ctx(bb, responses=[_llm_response()])
    delta = await IntentAgent().run(ctx)
    assert delta.updates["current_stage"] == "L2"


@pytest.mark.asyncio
async def test_intent_agent_scd2_floor_wins():
    """Even if LLM says scd_hint=None, floor detects SCD2 keywords."""
    bb = _bb("track history of customer changes over time")
    ctx = _ctx(bb, responses=[_llm_response(scd_hint=None)])
    delta = await IntentAgent().run(ctx)
    assert delta.updates["intent"].scd_hint == "type2"


@pytest.mark.asyncio
async def test_intent_agent_filters_extracted():
    bb = _bb("load active orders where status=active")
    resp = _llm_response(entity="order", filters=["status = 'active'"])
    ctx = _ctx(bb, responses=[resp])
    delta = await IntentAgent().run(ctx)
    assert delta.updates["intent"].filters == ["status = 'active'"]


@pytest.mark.asyncio
async def test_intent_agent_llm_failure_graceful():
    """If LLM throws, agent still returns a delta using keyword floor."""
    bb = _bb("load customer dimension table")

    class _BrokenLLM:
        def complete(self, *a, **kw):
            raise RuntimeError("network error")

    ctx = AgentContext(blackboard=bb, llm=_BrokenLLM())
    delta = await IntentAgent().run(ctx)
    # Should not propagate as error — floor covers the basics
    assert delta.error is None
    assert delta.updates["intent"].status == StageStatus.ready


@pytest.mark.asyncio
async def test_intent_agent_invalid_scd_hint_normalised():
    """Invalid scd_hint values from LLM are normalised to None."""
    bb = _bb("some requirement")
    resp = json.dumps({
        "entity": "thing", "action": "load", "is_dimension": False, "is_fact": False,
        "scd_hint": "garbage", "filters": [], "grain_hint": None, "extracted_keywords": [],
    })
    ctx = _ctx(bb, responses=[resp])
    delta = await IntentAgent().run(ctx)
    assert delta.updates["intent"].scd_hint is None
