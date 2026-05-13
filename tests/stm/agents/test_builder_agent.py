"""Tests for core/stm/agents/builder_agent.py — L6 BuilderAgent (full)."""
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.builder_agent import BuilderAgent, _build_mapping_rows
from core.stm.blackboard import (
    CandidateMapping, CandidateMappings, ConfidenceScore, GateDecision,
    IntentArtifact, MetadataGraph, StmBlackboard, StageStatus,
    Transformation, Transformations, ValidationReport,
)
from tests.stm.fake_llm import FakeLLMClient


def _bb(mappings=None, transformations=None, overall_band="high") -> StmBlackboard:
    cm = CandidateMappings(target_table="dim_customer", target_dataset="wh")
    if mappings is not None:
        cm.rows = mappings
    else:
        cm.rows = [
            CandidateMapping(
                target_field="customer_id", target_type="INT64",
                source_node_ids=["pg.public.customers.id"],
                source_expression="id", rationale="pk",
            ),
            CandidateMapping(
                target_field="email", target_type="STRING",
                source_node_ids=["pg.public.customers.email"],
                source_expression="email", rationale="direct",
            ),
        ]

    tx = Transformations(audit_fields=["_inserted_at"])
    if transformations is not None:
        tx.rows = transformations

    vr = ValidationReport(overall_band=overall_band)

    return StmBlackboard(
        session_id="s1",
        target_table="dim_customer",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="load customers",
                              entity="customer", status=StageStatus.ready),
        metadata_graph=MetadataGraph(),
        candidate_mappings=cm,
        transformations=tx,
        validation=vr,
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


def _ctx(bb):
    return AgentContext(blackboard=bb, llm=FakeLLMClient())


# ── _build_mapping_rows unit tests ────────────────────────────────────────────

def test_build_mapping_rows_basic():
    bb = _bb()
    rows = _build_mapping_rows(bb)
    assert len(rows) == 2
    fields = {r.target_column for r in rows}
    assert fields == {"customer_id", "email"}


def test_build_mapping_rows_source_info_from_node_id():
    bb = _bb()
    rows = _build_mapping_rows(bb)
    id_row = next(r for r in rows if r.target_column == "customer_id")
    assert id_row.source_schema == "public"
    assert id_row.source_table == "customers"
    assert id_row.source_column == "id"


def test_build_mapping_rows_pii_detection():
    bb = _bb()
    rows = _build_mapping_rows(bb)
    email_row = next(r for r in rows if r.target_column == "email")
    assert email_row.is_pii is True


def test_build_mapping_rows_includes_derived_audit():
    tx = [Transformation(target_field="_inserted_at", kind="audit",
                         logic="CURRENT_TIMESTAMP()", rationale="audit")]
    bb = _bb(transformations=tx)
    rows = _build_mapping_rows(bb)
    audit_row = next((r for r in rows if r.target_column == "_inserted_at"), None)
    assert audit_row is not None
    assert "CURRENT_TIMESTAMP" in audit_row.transformation


# ── Agent run ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_builder_agent_advances_to_done():
    delta = await BuilderAgent().run(_ctx(_bb()))
    assert delta.error is None
    assert delta.updates["current_stage"] == "done"


@pytest.mark.asyncio
async def test_builder_agent_stm_result_populated():
    delta = await BuilderAgent().run(_ctx(_bb()))
    result = delta.updates["stm_result"]
    assert result["target_table"] == "dim_customer"
    assert result["status"] == "done"
    assert result["field_count"] >= 2


@pytest.mark.asyncio
async def test_builder_agent_xlsx_bytes_produced():
    delta = await BuilderAgent().run(_ctx(_bb()))
    result = delta.updates["stm_result"]
    assert result["xlsx_bytes"] is not None
    assert isinstance(result["xlsx_bytes"], bytes)
    # xlsx magic bytes: PK zip header
    assert result["xlsx_bytes"][:2] == b"PK"


@pytest.mark.asyncio
async def test_builder_agent_overall_band_in_result():
    delta = await BuilderAgent().run(_ctx(_bb(overall_band="medium")))
    assert delta.updates["stm_result"]["overall_band"] == "medium"


@pytest.mark.asyncio
async def test_builder_agent_pii_count():
    delta = await BuilderAgent().run(_ctx(_bb()))
    result = delta.updates["stm_result"]
    assert result["pii_count"] >= 1  # email is PII


@pytest.mark.asyncio
async def test_builder_agent_no_llm_calls():
    llm = FakeLLMClient()
    bb = _bb()
    await BuilderAgent().run(AgentContext(blackboard=bb, llm=llm))
    assert llm.call_count == 0


@pytest.mark.asyncio
async def test_builder_agent_stage_label():
    assert BuilderAgent.stage == "L6"
