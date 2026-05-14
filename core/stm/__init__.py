"""STM agentic source-first mapping package."""
from core.stm.blackboard import (
    Attachment, ColumnRef, GateDecision, MappingRow, MappingType,
    Shortlist, ShortlistEntry, SourceTable, SqlBundle, SqlStatement,
    StageStatus, StmBlackboard, TargetSchema,
)
from core.stm.exporter import build_sql_zip, build_stm_xlsx

__all__ = [
    "Attachment", "ColumnRef", "GateDecision", "MappingRow", "MappingType",
    "Shortlist", "ShortlistEntry", "SourceTable", "SqlBundle", "SqlStatement",
    "StageStatus", "StmBlackboard", "TargetSchema",
    "build_sql_zip", "build_stm_xlsx",
]
