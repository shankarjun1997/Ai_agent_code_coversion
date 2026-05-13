"""Tests for core/stm/agents/base.py — StmAgent, AgentContext, BlackboardDelta."""
import asyncio

import pytest

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    CandidateMappings, GateDecision, IntentArtifact, MetadataGraph,
    StmBlackboard, StageStatus, Transformations, ValidationReport,
)
from tests.stm.fake_llm import FakeLLMClient


def _bb(sid: str = "s1") -> StmBlackboard:
    return StmBlackboard(
        session_id=sid,
        target_table="orders",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="load orders"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="orders", target_dataset="wh"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


def _ctx(bb: StmBlackboard, responses=None) -> AgentContext:
    return AgentContext(blackboard=bb, llm=FakeLLMClient(responses=responses or []))


# ── BlackboardDelta ───────────────────────────────────────────────────────────

def test_delta_apply_known_attr():
    bb = _bb()
    delta = BlackboardDelta(updates={"current_stage": "L2"})
    delta.apply(bb)
    assert bb.current_stage == "L2"


def test_delta_apply_unknown_attr_does_not_raise():
    bb = _bb()
    delta = BlackboardDelta(updates={"nonexistent_field": "value"})
    delta.apply(bb)  # should not raise


def test_delta_failure_factory():
    d = BlackboardDelta.failure("something broke", duration_ms=100)
    assert d.error == "something broke"
    assert d.duration_ms == 100
    assert d.updates == {}


# ── StmAgent ─────────────────────────────────────────────────────────────────

class _SuccessAgent(StmAgent):
    stage = "L1"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        return BlackboardDelta(updates={"current_stage": "L2"}, llm_model="fake")


class _FailingAgent(StmAgent):
    stage = "L1"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        raise ValueError("deliberate failure")


@pytest.mark.asyncio
async def test_agent_run_success():
    bb = _bb()
    ctx = _ctx(bb)
    delta = await _SuccessAgent().run(ctx)
    assert delta.error is None
    assert delta.updates["current_stage"] == "L2"
    assert delta.llm_model == "fake"
    assert delta.duration_ms >= 0


@pytest.mark.asyncio
async def test_agent_run_failure_returns_delta_not_raise():
    bb = _bb()
    ctx = _ctx(bb)
    delta = await _FailingAgent().run(ctx)
    assert delta.error == "deliberate failure"
    assert delta.updates == {}


@pytest.mark.asyncio
async def test_agent_run_populates_duration():
    bb = _bb()
    ctx = _ctx(bb)
    delta = await _SuccessAgent().run(ctx)
    assert isinstance(delta.duration_ms, int)


# ── AgentContext ──────────────────────────────────────────────────────────────

def test_agent_context_get_default():
    ctx = _ctx(_bb())
    assert ctx.get("missing_key", 42) == 42


def test_agent_context_get_value():
    bb = _bb()
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient(), config={"model": "claude-opus-4-5"})
    assert ctx.get("model") == "claude-opus-4-5"


def test_agent_context_emit_optional():
    ctx = _ctx(_bb())
    assert ctx.emit is None


def test_fake_llm_records_calls():
    llm = FakeLLMClient(responses=["hello"])
    result = llm.complete("test prompt")
    assert result == "hello"
    assert llm.call_count == 1
    assert llm.calls[0]["prompt"] == "test prompt"


def test_fake_llm_repeats_last():
    llm = FakeLLMClient(responses=["only"])
    llm.complete("a")
    llm.complete("b")
    assert llm.call_count == 2
    assert llm.calls[1]["prompt"] == "b"
