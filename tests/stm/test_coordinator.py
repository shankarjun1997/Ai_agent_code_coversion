"""Tests for core/stm/coordinator.py — STM pipeline coordinator."""
import asyncio
import uuid

import pytest

from core.stm.blackboard import (
    CandidateMappings, GateDecision, IntentArtifact, MetadataGraph,
    StmBlackboard, Transformations, ValidationReport,
)
from core.stm.coordinator import (
    is_running, resume_session, running_sessions, start_session,
)
from core.stm.events import EventKind, SseEvent, get_broker, reset_broker_for_tests
from core.stm.locks import reset_registry_for_tests
from core.stm.persistence import (
    load_blackboard, list_events, reset_engine_for_tests,
)
from tests.stm.fake_llm import FakeLLMClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    from tests.stm.conftest import _apply_schema
    _apply_schema(db_url)
    yield db_path


@pytest.fixture(autouse=True)
def _reset_all():
    reset_engine_for_tests()
    reset_broker_for_tests()
    reset_registry_for_tests()
    yield
    reset_engine_for_tests()
    reset_broker_for_tests()
    reset_registry_for_tests()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_bb(sid=None) -> StmBlackboard:
    sid = sid or str(uuid.uuid4())
    return StmBlackboard(
        session_id=sid,
        target_table="dim_customer",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="load customers"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="dim_customer", target_dataset="wh"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


def _intent_llm():
    """Fake LLM that returns valid JSON for L1, L3, L4 agents."""
    import json

    responses = [
        # L1 IntentAgent
        json.dumps({
            "entity": "customer", "action": "load", "is_dimension": True, "is_fact": False,
            "scd_hint": None, "filters": [], "grain_hint": None, "extracted_keywords": ["customer"],
        }),
        # L3 SemanticMappingAgent
        json.dumps([
            {"target_field": "customer_id", "target_type": "INT64",
             "source_expression": "id", "rationale": "pk", "llm_confidence": 0.95, "cardinality": "1:1"},
        ]),
        # L4 TransformationAgent
        json.dumps({
            "derived_columns": [],
            "scd_strategy": "type1",
            "audit_fields": ["_inserted_at"],
            "idempotency_key": "customer_id",
            "partition_field": None,
        }),
    ]
    return FakeLLMClient(responses=responses)


async def _wait_for_pipeline(session_id: str, max_wait: float = 10.0):
    """Poll until the pipeline task completes or max_wait expires."""
    elapsed = 0.0
    while is_running(session_id) and elapsed < max_wait:
        await asyncio.sleep(0.1)
        elapsed += 0.1
    if is_running(session_id):
        raise TimeoutError(f"Pipeline for {session_id} did not finish in {max_wait}s")


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_session_creates_db_row(tmp_db):
    bb = _make_bb("sess-create-test")
    await start_session(
        bb, raw_input="load customers",
        intent_source="freetext",
        llm=_intent_llm(),
    )
    await _wait_for_pipeline("sess-create-test")
    loaded = await load_blackboard("sess-create-test")
    assert loaded.session_id == "sess-create-test"


@pytest.mark.asyncio
async def test_pipeline_runs_to_done(tmp_db):
    bb = _make_bb("sess-done-test")
    await start_session(
        bb, raw_input="load customers",
        intent_source="freetext",
        llm=_intent_llm(),
    )
    await _wait_for_pipeline("sess-done-test")

    loaded = await load_blackboard("sess-done-test")
    assert loaded.current_stage == "done"
    assert loaded.stm_result is not None
    assert loaded.stm_result["status"] == "done"


@pytest.mark.asyncio
async def test_pipeline_emits_sse_events(tmp_db):
    bb = _make_bb("sess-sse-test")
    received = []

    broker = get_broker()

    async def reader():
        async for ev in broker.subscribe("sess-sse-test"):
            received.append(ev.kind)

    reader_task = asyncio.create_task(reader())
    # Let reader attach before starting pipeline
    await asyncio.sleep(0)

    await start_session(
        bb, raw_input="load customers",
        intent_source="freetext",
        llm=_intent_llm(),
    )

    # Wait for pipeline to complete (broker.close() signals reader)
    await _wait_for_pipeline("sess-sse-test")
    # Give reader a moment to drain
    try:
        await asyncio.wait_for(reader_task, timeout=2.0)
    except asyncio.TimeoutError:
        reader_task.cancel()

    assert EventKind.stage_started in received
    assert EventKind.stage_ready in received
    assert EventKind.session_done in received


@pytest.mark.asyncio
async def test_pipeline_events_logged_to_db(tmp_db):
    bb = _make_bb("sess-events-test")
    await start_session(
        bb, raw_input="load customers",
        intent_source="freetext",
        llm=_intent_llm(),
    )
    await _wait_for_pipeline("sess-events-test")

    events = await list_events("sess-events-test")
    kinds = [e["event_kind"] for e in events]
    assert "stage_started" in kinds
    assert "stage_ready" in kinds
    assert "session_done" in kinds


@pytest.mark.asyncio
async def test_is_running_clears_after_completion(tmp_db):
    bb = _make_bb("sess-running-test")
    await start_session(
        bb, raw_input="load customers",
        intent_source="freetext",
        llm=_intent_llm(),
    )
    # Should be running immediately after start
    assert is_running("sess-running-test")
    await _wait_for_pipeline("sess-running-test")
    assert not is_running("sess-running-test")
