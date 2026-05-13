"""Tests for core/stm/agents/metadata_agent.py — L2 MetadataAgent."""
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.metadata_agent import MetadataAgent
from core.stm.blackboard import (
    CandidateMappings, GateDecision, IntentArtifact, MetadataGraph,
    StmBlackboard, StageStatus, Transformations, ValidationReport,
)
from core.discovery.base import ColumnInfo, FKInfo, TableInfo
from tests.stm.fake_llm import FakeLLMClient


# ── Mock provider ─────────────────────────────────────────────────────────────

class _MockProvider:
    dialect = "postgres"

    async def list_schemas(self, profile):
        return ["public"]

    async def list_tables(self, profile, schema):
        return [TableInfo(schema=schema, name="customers"), TableInfo(schema=schema, name="orders")]

    async def get_columns(self, profile, schema, table):
        if table == "customers":
            return [
                ColumnInfo(schema=schema, table=table, name="id", data_type="INT64", nullable=False, is_primary_key=True),
                ColumnInfo(schema=schema, table=table, name="email", data_type="STRING", nullable=True),
                ColumnInfo(schema=schema, table=table, name="customer_name", data_type="STRING", nullable=True),
            ]
        if table == "orders":
            return [
                ColumnInfo(schema=schema, table=table, name="order_id", data_type="INT64", nullable=False, is_primary_key=True),
                ColumnInfo(schema=schema, table=table, name="customer_id", data_type="INT64", nullable=False),
                ColumnInfo(schema=schema, table=table, name="total_amount", data_type="NUMERIC", nullable=True),
            ]
        return []

    async def get_foreign_keys(self, profile, schema, table):
        if table == "orders":
            return [FKInfo(
                schema=schema, table=table, column="customer_id",
                ref_schema=schema, ref_table="customers", ref_column="id",
                constraint_name="fk_orders_customer",
            )]
        return []


class _FailingProvider:
    dialect = "postgres"

    async def list_schemas(self, profile):
        raise ConnectionError("DB unreachable")

    async def list_tables(self, profile, schema):
        raise ConnectionError("DB unreachable")

    async def get_columns(self, profile, schema, table):
        raise ConnectionError("DB unreachable")

    async def get_foreign_keys(self, profile, schema, table):
        raise ConnectionError("DB unreachable")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bb(profiles=None, keywords=None) -> StmBlackboard:
    intent = IntentArtifact(
        source="freetext",
        raw_input="load customer dimension",
        entity="customer",
        extracted_keywords=keywords or ["customer", "email"],
        status=StageStatus.ready,
    )
    return StmBlackboard(
        session_id="s1",
        target_table="dim_customer",
        target_dataset="wh",
        dialect_target="bigquery",
        selected_source_profiles=profiles or ["pg-demo"],
        intent=intent,
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="dim_customer", target_dataset="wh"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


def _make_agent(provider=None):
    mock = provider or _MockProvider()
    # provider_factory ignores dialect and returns the mock
    return MetadataAgent(provider_factory=lambda dialect: mock)


def _ctx(bb, provider=None):
    agent = _make_agent(provider)
    return AgentContext(blackboard=bb, llm=FakeLLMClient()), agent


# ── Profile registry mock ─────────────────────────────────────────────────────

class _FakeProfile:
    def __init__(self, id_, dialect="postgres"):
        self.id = id_
        self.dialect = dialect


class _FakeRegistry:
    def __init__(self, profiles):
        self._profiles = {p.id: p for p in profiles}

    def get(self, pid):
        return self._profiles.get(pid)


def _patched_agent(profiles, provider=None):
    """Return MetadataAgent with patched registry + provider_factory."""
    from unittest.mock import patch
    mock_provider = provider or _MockProvider()
    fake_reg = _FakeRegistry(profiles)

    def _factory(dialect):
        return mock_provider

    agent = MetadataAgent(provider_factory=_factory)

    # Patch get_registry inside metadata_agent
    import core.stm.agents.metadata_agent as mod
    mod_get_registry = lambda: fake_reg  # noqa: E731
    return agent, mod_get_registry


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metadata_agent_builds_nodes(monkeypatch):
    import core.stm.agents.metadata_agent as mod
    fake_reg = _FakeRegistry([_FakeProfile("pg-demo", "postgres")])
    monkeypatch.setattr(mod, "get_registry", lambda: fake_reg)

    bb = _bb(["pg-demo"])
    agent = MetadataAgent(provider_factory=lambda d: _MockProvider())
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient())
    delta = await agent.run(ctx)

    graph: MetadataGraph = delta.updates["metadata_graph"]
    assert len(graph.nodes) > 0
    kinds = {n.kind for n in graph.nodes}
    assert "table" in kinds
    assert "column" in kinds


@pytest.mark.asyncio
async def test_metadata_agent_builds_fk_edges(monkeypatch):
    import core.stm.agents.metadata_agent as mod
    fake_reg = _FakeRegistry([_FakeProfile("pg-demo", "postgres")])
    monkeypatch.setattr(mod, "get_registry", lambda: fake_reg)

    bb = _bb(["pg-demo"])
    agent = MetadataAgent(provider_factory=lambda d: _MockProvider())
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient())
    delta = await agent.run(ctx)

    graph: MetadataGraph = delta.updates["metadata_graph"]
    fk_edges = [e for e in graph.edges if e.kind == "fk"]
    assert len(fk_edges) >= 1
    assert fk_edges[0].evidence == "fk_orders_customer"


@pytest.mark.asyncio
async def test_metadata_agent_concept_links(monkeypatch):
    import core.stm.agents.metadata_agent as mod
    fake_reg = _FakeRegistry([_FakeProfile("pg-demo", "postgres")])
    monkeypatch.setattr(mod, "get_registry", lambda: fake_reg)

    bb = _bb(["pg-demo"], keywords=["email"])
    agent = MetadataAgent(provider_factory=lambda d: _MockProvider())
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient())
    delta = await agent.run(ctx)

    graph: MetadataGraph = delta.updates["metadata_graph"]
    concept_edges = [e for e in graph.edges if e.kind == "concept_link"]
    assert len(concept_edges) >= 1


@pytest.mark.asyncio
async def test_metadata_agent_advances_stage(monkeypatch):
    import core.stm.agents.metadata_agent as mod
    fake_reg = _FakeRegistry([_FakeProfile("pg-demo", "postgres")])
    monkeypatch.setattr(mod, "get_registry", lambda: fake_reg)

    bb = _bb(["pg-demo"])
    agent = MetadataAgent(provider_factory=lambda d: _MockProvider())
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient())
    delta = await agent.run(ctx)

    assert delta.updates["current_stage"] == "L3"
    assert delta.updates["metadata_graph"].status == StageStatus.ready


@pytest.mark.asyncio
async def test_metadata_agent_failing_provider_graceful(monkeypatch):
    import core.stm.agents.metadata_agent as mod
    fake_reg = _FakeRegistry([_FakeProfile("pg-demo", "postgres")])
    monkeypatch.setattr(mod, "get_registry", lambda: fake_reg)

    bb = _bb(["pg-demo"])
    agent = MetadataAgent(provider_factory=lambda d: _FailingProvider())
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient())
    delta = await agent.run(ctx)

    assert delta.error is None
    graph = delta.updates["metadata_graph"]
    assert len(graph.coverage_notes) > 0  # error recorded
    assert "pg-demo" not in graph.sources_probed


@pytest.mark.asyncio
async def test_metadata_agent_unknown_profile_graceful(monkeypatch):
    import core.stm.agents.metadata_agent as mod
    fake_reg = _FakeRegistry([])  # empty registry
    monkeypatch.setattr(mod, "get_registry", lambda: fake_reg)

    bb = _bb(["nonexistent-profile"])
    agent = MetadataAgent(provider_factory=lambda d: _MockProvider())
    ctx = AgentContext(blackboard=bb, llm=FakeLLMClient())
    delta = await agent.run(ctx)

    assert delta.error is None
    graph = delta.updates["metadata_graph"]
    assert any("not found" in n for n in graph.coverage_notes)


@pytest.mark.asyncio
async def test_metadata_agent_no_llm_calls(monkeypatch):
    import core.stm.agents.metadata_agent as mod
    fake_reg = _FakeRegistry([_FakeProfile("pg-demo", "postgres")])
    monkeypatch.setattr(mod, "get_registry", lambda: fake_reg)

    llm = FakeLLMClient()
    bb = _bb(["pg-demo"])
    agent = MetadataAgent(provider_factory=lambda d: _MockProvider())
    ctx = AgentContext(blackboard=bb, llm=llm)
    await agent.run(ctx)
    assert llm.call_count == 0
