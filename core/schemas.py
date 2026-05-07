"""Pydantic data contracts shared by every agent in the pipeline."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Enumerations ─────────────────────────────────────────────────────────────

class PipelineStage(str, Enum):
    REQUIREMENTS        = "requirements"
    REQUIREMENTS_REVIEW = "requirements_review"
    MAPPING             = "mapping"
    MAPPING_REVIEW      = "mapping_review"
    ENGINEERING         = "engineering"
    ENGINEERING_REVIEW  = "engineering_review"
    QA                  = "qa"
    QA_REVIEW           = "qa_review"
    COMPLETED           = "completed"
    FAILED              = "failed"


class OutputType(str, Enum):
    SQL_QUERY          = "sql_query"
    SQL_VIEW           = "sql_view"
    SQL_DDL            = "sql_ddl"
    STORED_PROCEDURE   = "stored_procedure"
    DBT_MODEL          = "dbt_model"
    DATAFORM_SQLX      = "dataform_sqlx"
    PYTHON_DAG         = "python_dag"
    PYTHON_SCRIPT      = "python_script"
    CLOUD_FUNCTION     = "cloud_function"


class IdempotencyStrategy(str, Enum):
    DELETE_INSERT = "delete_insert"
    MERGE         = "merge"
    APPEND        = "append"
    TRUNCATE_LOAD = "truncate_load"


class DQSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"


class ApprovalStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ── Jira / Requirements ───────────────────────────────────────────────────────

class JiraStory(BaseModel):
    issue_key:            str
    summary:              str
    description:          str
    acceptance_criteria:  str
    labels:               List[str] = []
    priority:             Optional[str] = None
    assignee:             Optional[str] = None
    components:           List[str] = []
    status:               Optional[str] = None
    story_type:           Optional[str] = None
    attachments:          List[str] = []


class ClarifyingQuestion(BaseModel):
    question:   str
    context:    str
    category:   Literal["data_source", "transformation", "business_rule",
                         "scope", "governance", "performance", "other"]
    priority:   Literal["high", "medium", "low"] = "medium"


class PrototypeSpec(BaseModel):
    """Sample output rows + schema to show business users what they'll get."""
    target_table:   str
    columns:        List[Dict[str, str]]   # [{"name": ..., "type": ..., "description": ...}]
    sample_rows:    List[Dict[str, Any]]   # up to 5 illustrative rows
    notes:          Optional[str] = None


class RequirementsDoc(BaseModel):
    doc_id:               str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at:           datetime = Field(default_factory=datetime.utcnow)
    summary:              str = ""
    acceptance_criteria:  str = ""
    raw_input_summary:    str = ""
    jira_story_draft:     Optional[JiraStory] = None
    task_breakdown:       List[str] = []     # ingestion / curation / audit / DQ / observability tasks
    clarifying_questions: List[ClarifyingQuestion] = []
    contradictions:       List[str] = []     # detected contradictions + suggestions
    prototype:            Optional[PrototypeSpec] = None
    approval_status:      ApprovalStatus = ApprovalStatus.PENDING
    reviewer_notes:       Optional[str] = None


# ── Data Mapping (Agent 2 — single source of truth) ──────────────────────────

class FieldMapping(BaseModel):
    source_expression:     str              # e.g. "CAST(o.amount AS FLOAT64)"
    target_field:          str
    data_type:             str
    nullable:              bool = True
    description:           Optional[str] = None
    transformation_logic:  Optional[str] = None
    is_pii:                bool = False
    sensitivity:           Optional[str] = None   # "public" | "internal" | "confidential" | "restricted"


class SourceTable(BaseModel):
    project:        Optional[str] = None
    dataset:        str
    table:          str
    alias:          str
    join_type:      Optional[str] = None   # INNER | LEFT | RIGHT | CROSS
    join_condition: Optional[str] = None


class DataMapping(BaseModel):
    mapping_id:           str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    jira_issue:           str
    version:              int = 1
    created_at:           datetime = Field(default_factory=datetime.utcnow)
    # Source
    source_tables:        List[SourceTable]
    # Target
    target_project:       Optional[str] = None
    target_dataset:       str
    target_table:         str
    field_mappings:       List[FieldMapping]
    # Query logic
    filters:              List[str] = []
    grain:                List[str] = []
    business_rules:       List[str] = []
    # Output requested
    output_types:         List[OutputType]
    # Partitioning / clustering
    partition_field:      Optional[str] = None
    cluster_fields:       List[str] = []
    # Incremental strategy
    idempotency_strategy: IdempotencyStrategy = IdempotencyStrategy.DELETE_INSERT
    idempotency_key:      Optional[str] = None
    # Scheduling
    schedule:             Optional[str] = None   # cron expression
    sla_hours:            Optional[float] = None
    # Governance
    data_owner:           Optional[str] = None
    data_steward:         Optional[str] = None
    tags:                 List[str] = []
    notes:                Optional[str] = None
    # Schema verification (populated by Agent 2 via BQ CLI)
    schema_verify:        Optional[Dict[str, Any]] = None
    svg_path:             Optional[str] = None
    # Approval
    approval_status:      ApprovalStatus = ApprovalStatus.PENDING
    reviewer_notes:       Optional[str] = None


# ── Engineering Sub-agent Outputs ─────────────────────────────────────────────

class GeneratedArtifact(BaseModel):
    artifact_id:    str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    artifact_type:  OutputType
    filename:       str
    content:        str
    explanation:    str
    dry_run_valid:  Optional[bool] = None
    dry_run_bytes:  Optional[int] = None
    created_at:     datetime = Field(default_factory=datetime.utcnow)


class DQRule(BaseModel):
    rule_id:          str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    rule_name:        str
    rule_type:        Literal["uniqueness", "completeness", "validity",
                               "referential_integrity", "freshness", "custom"]
    target_table:     str
    target_column:    Optional[str] = None
    expression:       str          # SQL assertion / dbt test definition
    severity:         DQSeverity = DQSeverity.CRITICAL
    threshold:        Optional[float] = None    # e.g. 0.01 = 1% null tolerance
    description:      str
    remediation:      Optional[str] = None


class DQReport(BaseModel):
    rules:            List[DQRule]
    dataform_yaml:    Optional[str] = None   # Dataform assertions YAML
    dbt_tests_yaml:   Optional[str] = None   # dbt schema.yml tests
    bq_procedure:     Optional[str] = None   # BQ stored proc for DQ checks


class ObservabilityConfig(BaseModel):
    audit_columns:     List[Dict[str, str]] = []   # columns to add: name, type, default_expr
    logging_hooks:     List[str] = []              # SQL/Python snippets for logging
    alert_configs:     List[Dict[str, Any]] = []   # Cloud Monitoring / Datadog alert specs
    dashboard_queries: List[Dict[str, str]] = []   # {name, sql} for monitoring dashboards
    cost_guard_sql:    Optional[str] = None        # Query to estimate / cap slot usage


class MetadataEntry(BaseModel):
    table_fqn:            str     # project.dataset.table
    description:          str
    data_owner:           Optional[str] = None
    data_steward:         Optional[str] = None
    column_descriptions:  Dict[str, str] = {}     # column_name → description
    pii_columns:          List[str] = []
    sensitivity_labels:   Dict[str, str] = {}     # column_name → sensitivity level
    lineage_upstream:     List[str] = []           # upstream table FQNs
    lineage_downstream:   List[str] = []
    dataplex_tags:        Dict[str, Any] = {}
    bq_labels:            Dict[str, str] = {}


class EngineeringPackage(BaseModel):
    """Consolidated output from Agent 3 and all sub-agents."""
    package_id:       str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    jira_issue:       str
    created_at:       datetime = Field(default_factory=datetime.utcnow)
    artifacts:        List[GeneratedArtifact] = []   # 3a + 3b outputs
    dq_report:        Optional[DQReport] = None       # 3c
    observability:    Optional[ObservabilityConfig] = None  # 3d
    metadata:         Optional[MetadataEntry] = None  # 3e
    github_pr_url:    Optional[str] = None
    approval_status:  ApprovalStatus = ApprovalStatus.PENDING
    reviewer_notes:   Optional[str] = None


# ── QA ───────────────────────────────────────────────────────────────────────

class TestCase(BaseModel):
    test_id:      str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    test_name:    str
    test_type:    Literal["row_count", "schema_check", "null_check", "duplicate_check",
                           "referential_integrity", "transformation", "reconciliation",
                           "restartability", "freshness"]
    sql:          str
    expected:     Optional[Any] = None
    description:  str


class QAReport(BaseModel):
    report_id:        str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    jira_issue:       str
    created_at:       datetime = Field(default_factory=datetime.utcnow)
    test_cases:       List[TestCase]
    execution_results: List[Dict[str, Any]] = []
    defects:          List[str] = []
    sign_off_ready:   bool = False
    approval_status:  ApprovalStatus = ApprovalStatus.PENDING
    reviewer_notes:   Optional[str] = None


# ── Top-level Pipeline Run ────────────────────────────────────────────────────

class HumanApproval(BaseModel):
    stage:      PipelineStage
    status:     ApprovalStatus
    reviewer:   Optional[str] = None
    notes:      Optional[str] = None
    timestamp:  datetime = Field(default_factory=datetime.utcnow)


class PipelineRun(BaseModel):
    run_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    jira_issue:   str
    started_at:   datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    stage:        PipelineStage = PipelineStage.REQUIREMENTS
    status:       Literal["running", "waiting_review", "completed", "failed"] = "running"
    # Stage outputs
    requirements: Optional[RequirementsDoc] = None
    mapping:      Optional[DataMapping] = None
    engineering:  Optional[EngineeringPackage] = None
    qa_report:    Optional[QAReport] = None
    # Approval history
    approvals:    List[HumanApproval] = []
    errors:       List[str] = []
    log_entries:  List[str] = []
