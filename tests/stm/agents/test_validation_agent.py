"""Tests for core/stm/agents/validation_agent.py — L5 ValidationAgent."""
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.validation_agent import ValidationAgent
from core.stm.blackboard import (
    CandidateMapping, CandidateMappings, GateDecision, IntentArtifact,
    MetadataGraph, StmBlackboard, StageStatus, Transformation,
    Transformations, ValidationReport,
)
from tests.stm.fake_llm import FakeLLMClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bb(mappings=None, scd_strategy=None, partition_field=None) -> StmBlackboard:
    cm = CandidateMappings(target_table="dim_customer", target_dataset="wh")
    if mappings is not None:
        cm.rows = mappings
    else:
        cm.rows = [
            CandidateMapping(target_field="customer_id", target_type="INT64",
                             source_expression="id", llm_confidence=0.95),
            CandidateMapping(target_field="email", target_type="STRING",
                             source_expression="email", llm_confidence=0.9),
        ]
    tx = Transformations(
        scd_strategy=scd_strategy,
        partition_field=partition_field,
        audit_fields=["_inserted_at", "_updated_at"],
    )
    return StmBlackboard(
        session_id="s1",
        target_table="dim_customer",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="load customer",
                              entity="customer", status=StageStatus.ready),
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


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validation_agent_advances_to_l6():
    delta = await ValidationAgent().run(_ctx(_bb()))
    assert delta.error is None
    assert delta.updates["current_stage"] == "L6"


@pytest.mark.asyncio
async def test_validation_agent_sets_ready():
    delta = await ValidationAgent().run(_ctx(_bb()))
    assert delta.updates["validation"].status == StageStatus.ready


@pytest.mark.asyncio
async def test_validation_agent_scores_per_field():
    delta = await ValidationAgent().run(_ctx(_bb()))
    report = delta.updates["validation"]
    assert len(report.scores) == 2
    assert all(s.target_field in ("customer_id", "email") for s in report.scores)


@pytest.mark.asyncio
async def test_validation_agent_no_llm_calls():
    llm = FakeLLMClient()
    await ValidationAgent().run(AgentContext(blackboard=_bb(), llm=llm))
    assert llm.call_count == 0


@pytest.mark.asyncio
async def test_validation_agent_high_band_for_good_mappings():
    """Good mappings (high llm_confidence, exact names) → high band."""
    delta = await ValidationAgent().run(_ctx(_bb()))
    report = delta.updates["validation"]
    # Both fields have llm_confidence=0.9+ → overall high
    assert report.overall_band in ("high", "medium")


@pytest.mark.asyncio
async def test_validation_agent_block_finding_for_no_mappings():
    delta = await ValidationAgent().run(_ctx(_bb(mappings=[])))
    report = delta.updates["validation"]
    assert report.block_count >= 1
    assert report.overall_band == "low"
    rules = [f.rule for f in report.findings]
    assert "no_mappings" in rules


@pytest.mark.asyncio
async def test_validation_agent_missing_source_expression_warn():
    mappings = [
        CandidateMapping(target_field="mystery_field", target_type="STRING",
                         source_expression=""),  # no source
    ]
    delta = await ValidationAgent().run(_ctx(_bb(mappings=mappings)))
    report = delta.updates["validation"]
    warn_rules = [f.rule for f in report.findings if f.severity == "warn"]
    assert "missing_source_expression" in warn_rules


@pytest.mark.asyncio
async def test_validation_agent_scd2_missing_date_warns():
    # SCD2 but no effective_from field
    delta = await ValidationAgent().run(_ctx(_bb(scd_strategy="type2")))
    report = delta.updates["validation"]
    rules = [f.rule for f in report.findings]
    assert "scd2_missing_effective_date" in rules


@pytest.mark.asyncio
async def test_validation_agent_no_partition_info_finding():
    # Many mappings, no partition field
    mappings = [
        CandidateMapping(target_field=f"field_{i}", target_type="STRING",
                         source_expression=f"col_{i}")
        for i in range(6)
    ]
    delta = await ValidationAgent().run(_ctx(_bb(mappings=mappings, partition_field=None)))
    report = delta.updates["validation"]
    info_rules = [f.rule for f in report.findings if f.severity == "info"]
    assert "no_partition_field" in info_rules


@pytest.mark.asyncio
async def test_validation_agent_low_confidence_count():
    # All mappings have no LLM confidence and bad names → low band
    mappings = [
        CandidateMapping(target_field=f"target_{i}", target_type="STRING",
                         source_expression=f"xyz_abc_{i}")  # no name match
        for i in range(5)
    ]
    delta = await ValidationAgent().run(_ctx(_bb(mappings=mappings)))
    report = delta.updates["validation"]
    assert report.low_confidence_count > 0
