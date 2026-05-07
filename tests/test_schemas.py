"""Basic schema round-trip and validation tests."""
import pytest
from datetime import datetime
from core.schemas import (
    DataMapping, FieldMapping, SourceTable, OutputType,
    IdempotencyStrategy, PipelineRun, PipelineStage,
    RequirementsDoc, JiraStory, ClarifyingQuestion,
)


def test_data_mapping_round_trip():
    m = DataMapping(
        jira_issue="DATA-1",
        source_tables=[SourceTable(dataset="raw", table="orders", alias="o")],
        target_dataset="analytics",
        target_table="daily_orders",
        field_mappings=[
            FieldMapping(
                source_expression="o.order_id",
                target_field="order_id",
                data_type="STRING",
            )
        ],
        output_types=[OutputType.SQL_VIEW, OutputType.DBT_MODEL],
        idempotency_strategy=IdempotencyStrategy.DELETE_INSERT,
        idempotency_key="snapshot_date",
        partition_field="snapshot_date",
    )
    json_str = m.model_dump_json()
    recovered = DataMapping.model_validate_json(json_str)
    assert recovered.jira_issue == "DATA-1"
    assert recovered.target_table == "daily_orders"
    assert len(recovered.field_mappings) == 1
    assert OutputType.DBT_MODEL in recovered.output_types


def test_pipeline_run_stages():
    run = PipelineRun(jira_issue="DATA-42")
    assert run.stage == PipelineStage.REQUIREMENTS
    assert run.status == "running"


def test_requirements_doc_with_questions():
    story = JiraStory(
        issue_key="DATA-5",
        summary="Build daily revenue report",
        description="As a finance analyst I want daily revenue by region",
        acceptance_criteria="1. Table updated daily\n2. Revenue correct to 2dp",
    )
    doc = RequirementsDoc(
        raw_input_summary="finance wants daily revenue",
        jira_story_draft=story,
        task_breakdown=["Ingestion: pull from orders", "DQ: revenue not null"],
        clarifying_questions=[
            ClarifyingQuestion(
                question="Which timezone for daily cutoff?",
                context="Revenue aggregation depends on this",
                category="business_rule",
                priority="high",
            )
        ],
    )
    assert len(doc.task_breakdown) == 2
    assert doc.clarifying_questions[0].priority == "high"
    j = doc.model_dump_json()
    rec = RequirementsDoc.model_validate_json(j)
    assert rec.doc_id == doc.doc_id
