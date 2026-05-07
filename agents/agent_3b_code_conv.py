"""Agent 3b — Code Conversion Agent.

Migrates legacy SQL/ETL code to BigQuery Standard SQL.
Supported sources: Teradata, Oracle, SQL Server, Informatica, stored procedures.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from core.llm_client import LLMClient
from core.schemas import GeneratedArtifact, OutputType

logger = logging.getLogger(__name__)

SourceDialect = Literal[
    "teradata", "oracle", "sql_server", "mysql", "postgres",
    "informatica", "ssis", "stored_procedure", "spark_sql", "hive"
]

SYSTEM_PROMPT = """You are a BigQuery migration specialist.

Convert legacy SQL/ETL code to idiomatic BigQuery Standard SQL.

Rules:
- Translate dialect-specific functions to BigQuery equivalents.
- Rewrite procedural logic into set-based SQL using CTEs.
- Replace legacy JOIN syntax with ANSI JOIN.
- Convert ROWNUM / TOP / FETCH FIRST to LIMIT.
- Replace DECODE() with CASE WHEN.
- Replace NVL() with COALESCE().
- Replace SYSDATE/GETDATE() with CURRENT_TIMESTAMP().
- Replace TO_DATE/CONVERT with PARSE_DATE / CAST.
- Flag constructs you cannot auto-convert with: -- MANUAL REVIEW REQUIRED: <reason>
- Preserve all business logic — do not simplify what you don't understand.

After the converted SQL, append a CONVERSION NOTES section listing:
- All functions translated
- All constructs flagged for manual review
- Any assumptions made
"""


class CodeConversionAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def convert(
        self,
        legacy_code:  str,
        source_dialect: SourceDialect,
        context:        Optional[str] = None,
        jira_issue:     str = "CONV",
    ) -> GeneratedArtifact:
        """
        Convert legacy code to BigQuery SQL.

        Args:
            legacy_code:    The original SQL/ETL code to convert.
            source_dialect: Source system dialect.
            context:        Optional mapping doc context for better conversion.
            jira_issue:     Jira issue key for traceability.

        Returns:
            GeneratedArtifact with the converted SQL and conversion notes.
        """
        ctx_block = f"\nMapping context for reference:\n{context}" if context else ""
        prompt = f"""Convert the following {source_dialect.upper()} code to BigQuery Standard SQL.
{ctx_block}

=== LEGACY CODE ===
{legacy_code}

=== INSTRUCTIONS ===
{SYSTEM_PROMPT}

Return:
1. The complete converted BigQuery SQL.
2. A CONVERSION NOTES section.
"""
        converted = self.llm.complete(prompt, system=SYSTEM_PROMPT)

        # Detect manual review flags
        manual_items = [
            line.strip()
            for line in converted.splitlines()
            if "MANUAL REVIEW REQUIRED" in line
        ]

        explanation = (
            f"Converted from {source_dialect} to BigQuery. "
            f"{len(manual_items)} construct(s) require manual review."
        )

        logger.info(
            "Agent 3b: converted %d chars from %s — %d manual review items",
            len(legacy_code), source_dialect, len(manual_items),
        )

        return GeneratedArtifact(
            artifact_type=OutputType.SQL_QUERY,
            filename=f"converted_{jira_issue.lower()}_{source_dialect}.sql",
            content=converted,
            explanation=explanation,
        )
