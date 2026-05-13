"""Tests for core/stm/agents/builder_agent.py — L6 BuilderAgent stub."""
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.builder_agent import BuilderAgent
from core.stm.blackboard import (
    CandidateMapping, CandidateMappings, GateDecision, IntentArtifact,
    MetadataGraph, StmBlackboard, StageStatus, Transformation, Transformations,
    ValidationReport,
)
from tests.stm.fake_llm import FakeLLMClient


def _bb(mappings=0, transformations=0) -> StmBlackboard:
    cm = CandidateMappings(target_table="orders", target_dataset="wh")
    for i in range(mappings):
        cm.rows.append(CandidateMapping(target_field=f"field_{i}", target_type="STRING"))
    tx = Transformations()
    for i in range(transformations):
        tx.rows.append(Transformation(target_field=f"field_{i}", kind="derived", logic="x"))
    return StmBlackboard(
        session_id="s1",
        target_table="orders",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="load orders"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=cm,
        transformations=tx,
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


def _ctx(bb):
    return AgentContext(blackboard=bb, llm=FakeLLMClient())


@pytest.mark.asyncio
async def test_builder_agent_advances_to_done():
    bb = _bb()
    delta = await BuilderAgent().run(_ctx(bb))
    assert delta.error is None
    assert delta.updates["current_stage"] == "done"


@pytest.mark.asyncio
async def test_builder_agent_produces_stm_result():
    bb = _bb(mappings=3, transformations=2)
    delta = await BuilderAgent().run(_ctx(bb))
    result = delta.updates["stm_result"]
    assert result is not None
    assert result["session_id"] == "s1"
    assert result["mapping_count"] == 3
    assert result["transformation_count"] == 2


@pytest.mark.asyncio
async def test_builder_agent_stub_status():
    bb = _bb()
    delta = await BuilderAgent().run(_ctx(bb))
    assert delta.updates["stm_result"]["status"] == "stub"


@pytest.mark.asyncio
async def test_builder_agent_stage_label():
    assert BuilderAgent.stage == "L6"


@pytest.mark.asyncio
async def test_builder_agent_no_llm_calls():
    llm = FakeLLMClient()
    bb = _bb()
    ctx = AgentContext(blackboard=bb, llm=llm)
    await BuilderAgent().run(ctx)
    assert llm.call_count == 0
