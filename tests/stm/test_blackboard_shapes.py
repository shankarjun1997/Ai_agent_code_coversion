from datetime import datetime

from core.stm.blackboard import (
    StageStatus, IntentArtifact, MetadataGraph, GraphNode, GraphEdge,
    CandidateMapping, CandidateMappings, Transformation, Transformations,
    ConfidenceScore, ValidationReport, ValidationFinding, GateDecision,
    StmBlackboard,
)


def test_stage_status_values():
    assert StageStatus.idle.value == "idle"
    assert StageStatus.ready.value == "ready"
    assert StageStatus.stale.value == "stale"


def test_intent_artifact_minimal():
    i = IntentArtifact(
        source="freetext", raw_input="Build customer dim",
        jira_issue_key=None, entity="customer_dim", action="create",
        is_dimension=True, is_fact=False, scd_hint="type2",
        filters=["active users only"], grain_hint="customer_id",
        extracted_keywords=["customer","active"], status=StageStatus.ready,
    )
    assert i.entity == "customer_dim"
    assert i.is_dimension is True


def test_metadata_graph_query_helpers():
    g = MetadataGraph(
        nodes=[
            GraphNode(id="pg.public.customers", kind="table", label="customers", dialect="postgres"),
            GraphNode(id="pg.public.customers.customer_id", kind="column", label="customer_id", dialect="postgres", data_type="bigint"),
        ],
        edges=[GraphEdge(src="pg.public.customers", dst="pg.public.customers.customer_id", kind="contains")],
        sources_probed=["pg-demo"], coverage_notes=[], status=StageStatus.ready,
    )
    assert len(g.columns_of("pg.public.customers")) == 1
    assert g.by_dialect("postgres")[0].label == "customers"


def test_blackboard_assembles():
    bb = StmBlackboard(
        session_id="abc", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(
            source="freetext", raw_input="x", jira_issue_key=None,
            entity="x", action="create", is_dimension=False, is_fact=False,
            scd_hint=None, filters=[], grain_hint=None, extracted_keywords=[],
            status=StageStatus.idle,
        ),
        metadata_graph=MetadataGraph(nodes=[], edges=[], sources_probed=[], coverage_notes=[], status=StageStatus.idle),
        candidate_mappings=CandidateMappings(target_table="x", target_dataset="x", rows=[], rule_baseline_summary={}, status=StageStatus.idle),
        transformations=Transformations(rows=[], scd_strategy=None, audit_fields=[], idempotency_key=None, partition_field=None, status=StageStatus.idle),
        validation=ValidationReport(scores=[], findings=[], low_confidence_count=0, block_count=0, overall_band="high", status=StageStatus.idle),
        stm_result=None,
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="pending"),
            "gate2_validation": GateDecision(name="gate2_validation", decision="pending"),
        },
        current_stage="L1",
    )
    s = bb.model_dump_json()
    bb2 = StmBlackboard.model_validate_json(s)
    assert bb2.session_id == "abc"
