"""Pydantic shared-blackboard for an STM agentic session."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    idle = "idle"
    running = "running"
    ready = "ready"
    stale = "stale"
    awaiting_review = "awaiting_review"
    rejected = "rejected"
    failed = "failed"


class IntentArtifact(BaseModel):
    source: Literal["jira", "freetext"]
    raw_input: str
    jira_issue_key: Optional[str] = None
    entity: str = ""
    action: str = ""
    is_dimension: bool = False
    is_fact: bool = False
    scd_hint: Optional[Literal["type1", "type2", "type3", "none"]] = None
    filters: List[str] = Field(default_factory=list)
    grain_hint: Optional[str] = None
    extracted_keywords: List[str] = Field(default_factory=list)
    status: StageStatus = StageStatus.idle


class GraphNode(BaseModel):
    id: str
    kind: Literal["dialect", "schema", "table", "column", "concept"]
    label: str
    dialect: Optional[str] = None
    data_type: Optional[str] = None
    nullable: Optional[bool] = None
    is_pii: Optional[bool] = None
    profile: Optional[Dict[str, Any]] = None


class GraphEdge(BaseModel):
    src: str
    dst: str
    kind: Literal["contains", "fk", "semantic_match", "join_candidate", "concept_link"]
    confidence: Optional[float] = None
    evidence: Optional[str] = None


class MetadataGraph(BaseModel):
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    sources_probed: List[str] = Field(default_factory=list)
    coverage_notes: List[str] = Field(default_factory=list)
    status: StageStatus = StageStatus.idle

    def find_by_concept(self, concept: str) -> List[GraphNode]:
        ids = {e.dst for e in self.edges if e.kind == "concept_link" and concept.lower() in (e.evidence or "").lower()}
        return [n for n in self.nodes if n.id in ids]

    def join_candidates(self, table_id: str) -> List[GraphEdge]:
        return [e for e in self.edges if e.kind == "join_candidate" and (e.src.startswith(table_id) or e.dst.startswith(table_id))]

    def columns_of(self, table_id: str) -> List[GraphNode]:
        col_ids = {e.dst for e in self.edges if e.kind == "contains" and e.src == table_id}
        return [n for n in self.nodes if n.id in col_ids and n.kind == "column"]

    def by_dialect(self, dialect: str) -> List[GraphNode]:
        return [n for n in self.nodes if n.dialect == dialect and n.kind == "table"]


class CandidateMapping(BaseModel):
    target_field: str
    target_type: str
    source_node_ids: List[str] = Field(default_factory=list)
    source_expression: str = ""
    rationale: str = ""
    grain: List[str] = Field(default_factory=list)
    cardinality: Optional[Literal["1:1", "M:1", "1:M", "M:M"]] = None
    rule_baseline: bool = False
    refined_by_llm: bool = False
    llm_confidence: Optional[float] = None


class CandidateMappings(BaseModel):
    target_table: str
    target_dataset: str
    rows: List[CandidateMapping] = Field(default_factory=list)
    rule_baseline_summary: Dict[str, Any] = Field(default_factory=dict)
    status: StageStatus = StageStatus.idle


class Transformation(BaseModel):
    target_field: str
    kind: Literal["derived", "scd2", "audit", "surrogate_key", "computed", "filter"]
    logic: str
    inputs: List[str] = Field(default_factory=list)
    rationale: str = ""


class Transformations(BaseModel):
    rows: List[Transformation] = Field(default_factory=list)
    scd_strategy: Optional[Literal["type1", "type2", "type3", "none"]] = None
    audit_fields: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    partition_field: Optional[str] = None
    status: StageStatus = StageStatus.idle


class ValidationFinding(BaseModel):
    severity: Literal["info", "warn", "block"]
    target_field: Optional[str] = None
    rule: str
    message: str


class ConfidenceScore(BaseModel):
    target_field: str
    llm_score: float = 0.0
    name_sim_score: float = 0.0
    type_compat_score: float = 0.0
    profile_overlap_score: Optional[float] = None
    fk_evidence_score: float = 0.0
    final: float = 0.0
    band: Literal["high", "medium", "low"] = "low"


class ValidationReport(BaseModel):
    scores: List[ConfidenceScore] = Field(default_factory=list)
    findings: List[ValidationFinding] = Field(default_factory=list)
    low_confidence_count: int = 0
    block_count: int = 0
    overall_band: Literal["high", "medium", "low"] = "high"
    status: StageStatus = StageStatus.idle


class GateDecision(BaseModel):
    name: Literal["gate1_metadata", "gate2_validation"]
    decision: Literal["pending", "approved", "rejected", "refine"] = "pending"
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    refine_target_stage: Optional[Literal["L1", "L2", "L3", "L4", "L5"]] = None
    refine_feedback: Optional[str] = None
    decided_at: Optional[datetime] = None


class StmBlackboard(BaseModel):
    session_id: str
    target_table: str
    target_dataset: str
    dialect_target: Literal["bigquery"]
    selected_source_profiles: List[str] = Field(default_factory=list)
    intent: IntentArtifact
    metadata_graph: MetadataGraph
    candidate_mappings: CandidateMappings
    transformations: Transformations
    validation: ValidationReport
    stm_result: Optional[Dict[str, Any]] = None
    gates: Dict[str, GateDecision] = Field(default_factory=dict)
    current_stage: Literal["L1", "L2", "L3", "L4", "L5", "L6", "done", "failed"] = "L1"
    refine_feedback_pending: Dict[str, str] = Field(default_factory=dict)
