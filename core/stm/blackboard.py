"""Pydantic shared-blackboard for an STM agentic session.

Source-first model: one source table (Databricks Unity Catalog table OR uploaded
data sample) → many candidate target tables in a BigQuery dataset
(INFORMATION_SCHEMA). The pipeline shortlists relevant target tables, then
maps each source column to its single best target column with business logic,
then generates BigQuery MERGE SQL.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Stage status / gate decision ─────────────────────────────────────────────

class StageStatus(str, Enum):
    idle = "idle"
    running = "running"
    ready = "ready"
    stale = "stale"
    awaiting_review = "awaiting_review"
    rejected = "rejected"
    failed = "failed"


Stage = Literal["L1", "L2", "L3", "L4", "done", "failed"]
GateName = Literal["gate1_shortlist", "gate2_mapping"]


class GateDecision(BaseModel):
    name: GateName
    decision: Literal["pending", "approved", "rejected", "refine"] = "pending"
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    refine_target_stage: Optional[Literal["L1", "L2", "L3"]] = None
    refine_feedback: Optional[str] = None
    decided_at: Optional[datetime] = None


# ── Attachments (file upload provenance) ─────────────────────────────────────

class Attachment(BaseModel):
    """File uploaded at session start (xlsx, csv, json, txt).

    The schemas agent parses the file via `core.stm.schemas.upload_parser` and
    promotes the inferred tables into `source_table` / `target_schema` depending
    on which slot the upload targeted.
    """
    id: str
    filename: str
    kind: Literal["xlsx", "csv", "json", "txt"]
    bytes: int
    stored_at: str
    role: Literal["source", "target"]
    uploaded_at: Optional[datetime] = None
    diag: Optional[Dict[str, Any]] = None  # parser strategy + stats


# ── Schema models (L1 output) ────────────────────────────────────────────────

class ColumnRef(BaseModel):
    name: str
    type: Optional[str] = None          # BQ-style type ideally (STRING, INT64, …) or raw dialect type
    description: Optional[str] = None


class SourceTable(BaseModel):
    """A single source table — name + ordered list of columns with types."""
    name: str
    columns: List[ColumnRef] = Field(default_factory=list)
    # Provenance: where these columns came from
    origin: Literal["databricks_unity", "upload", "manual"] = "upload"
    catalog: Optional[str] = None   # databricks catalog
    schema_name: Optional[str] = None  # databricks schema
    comment: Optional[str] = None


class TargetSchema(BaseModel):
    """The target BigQuery dataset's INFORMATION_SCHEMA dump — many tables."""
    project: str
    dataset: str
    tables: List[SourceTable] = Field(default_factory=list)
    fetched_at: Optional[datetime] = None
    origin: Literal["bigquery_live", "upload"] = "bigquery_live"


# ── Shortlist (L2 output) ────────────────────────────────────────────────────

class ShortlistEntry(BaseModel):
    """One candidate target table — picked by L2 as receiving data from source."""
    table: str
    reason: str                     # one-liner role description
    match_count: int = 0            # number of source columns with a real home here
    evidence: List[str] = Field(default_factory=list)  # ["source.col -> target.col (1:1)", ...]
    picked: bool = True             # reviewer can uncheck at Gate 1


class Shortlist(BaseModel):
    rows: List[ShortlistEntry] = Field(default_factory=list)
    status: StageStatus = StageStatus.idle


# ── Mapping rows (L3 output) ─────────────────────────────────────────────────

MappingType = Literal["1:1", "1:many", "derived", "constant", "unused"]


class MappingRow(BaseModel):
    """One row per source column — its single best landing in the target schema."""
    source_table: str
    source_column: str
    target_table: str = ""           # "" when mapping_type == "unused"
    target_column: str = ""          # "" when mapping_type == "unused"
    mapping_type: MappingType
    business_logic: str = ""         # ≤25 words — what the engineer needs to do
    rationale: Optional[str] = None  # optional extra context
    edited_by_reviewer: bool = False
    failed: bool = False             # set when the LLM batch failed for this column


# ── SQL output (L4 output) ───────────────────────────────────────────────────

class SqlStatement(BaseModel):
    target_table: str
    sql: str
    header_comment: str = ""


class SqlBundle(BaseModel):
    project: str
    dataset: str
    statements: List[SqlStatement] = Field(default_factory=list)
    combined_sql: str = ""
    generated_at: Optional[datetime] = None
    status: StageStatus = StageStatus.idle


# ── Top-level blackboard ─────────────────────────────────────────────────────

class StmBlackboard(BaseModel):
    """Shared session state across the 4-stage source-first pipeline."""
    session_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # User intent (free-form, replaces the old IntentArtifact)
    business_context: str = ""

    # L1 — schemas
    source_table: Optional[SourceTable] = None
    target_schema: Optional[TargetSchema] = None

    # L2 — shortlist
    shortlist: Optional[Shortlist] = None

    # L3 — mappings (source-first; one row per source column)
    mappings: List[MappingRow] = Field(default_factory=list)
    mapping_status: StageStatus = StageStatus.idle

    # L4 — SQL
    sql_bundle: Optional[SqlBundle] = None

    # Gates + attachments + flow control
    gates: Dict[str, GateDecision] = Field(default_factory=dict)
    attachments: List[Attachment] = Field(default_factory=list)
    current_stage: Stage = "L1"
    refine_feedback_pending: Dict[str, str] = Field(default_factory=dict)

    # Convenience accessors — used by exporter / persistence to denormalise
    @property
    def target_project(self) -> str:
        return (self.target_schema.project if self.target_schema else "") or ""

    @property
    def target_dataset(self) -> str:
        return (self.target_schema.dataset if self.target_schema else "") or ""

    @property
    def source_table_name(self) -> str:
        return (self.source_table.name if self.source_table else "") or ""
