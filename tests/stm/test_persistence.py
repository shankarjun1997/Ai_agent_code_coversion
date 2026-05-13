import asyncio
from datetime import datetime

import pytest

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import (
    create_session, load_blackboard, save_blackboard, append_event,
    list_events, record_gate_decision,
)


def _bb(sid="s1"):
    return StmBlackboard(
        session_id=sid, target_table="cust", target_dataset="wh",
        dialect_target="bigquery", selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="x"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="cust", target_dataset="wh"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_create_and_load(tmp_db):
    bb = _bb()
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    loaded = await load_blackboard("s1")
    assert loaded.session_id == "s1"
    assert loaded.target_table == "cust"


@pytest.mark.asyncio
async def test_save_overwrites_snapshot(tmp_db):
    bb = _bb("s2")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    bb.intent.entity = "customer_dim"
    bb.intent.status = StageStatus.ready
    await save_blackboard(bb)
    loaded = await load_blackboard("s2")
    assert loaded.intent.entity == "customer_dim"
    assert loaded.intent.status == StageStatus.ready


@pytest.mark.asyncio
async def test_event_log(tmp_db):
    bb = _bb("s3")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    await append_event("s3", stage="L1", event_kind="started", message="x")
    await append_event("s3", stage="L1", event_kind="ready", artifact_kind="intent", artifact_json='{"x":1}')
    events = await list_events("s3")
    assert [e["event_kind"] for e in events] == ["started", "ready"]


@pytest.mark.asyncio
async def test_gate_decision_row(tmp_db):
    bb = _bb("s4")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    await record_gate_decision("s4", gate_name="gate1_metadata", decision="approved", reviewer="alice", notes=None, refine_target=None, refine_feedback=None)
    events = await list_events("s4")
    assert any(e["event_kind"] == "gate_decided" for e in events)
