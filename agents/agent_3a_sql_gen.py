"""Agent 3a — SQL Generation Agent.

Generates optimised BigQuery DDL and DML from an approved DataMapping.
Outputs: CREATE OR REPLACE VIEW, incremental DML, stored procedure shell,
         dbt model SQL, Dataform SQLX — based on mapping.output_types.
"""
from __future__ import annotations

import logging
from typing import List

from core.bq_client import BQClient
from core.llm_client import LLMClient
from core.schemas import DataMapping, GeneratedArtifact, OutputType

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a BigQuery expert generating production-quality SQL.

Rules:
- Use BigQuery Standard SQL only.
- Use CTEs (WITH clauses) for readability.
- Apply partitioning and clustering as specified.
- Implement DELETE+INSERT or MERGE for idempotency as specified.
- Include inline comments only for non-obvious logic.
- Use QUALIFY for deduplication when needed.
- Prefer window functions over subqueries where appropriate.
- Never use SELECT * in production code — list columns explicitly.
"""


class SQLGeneratorAgent:
    def __init__(self, llm: LLMClient, bq: BQClient):
        self.llm = llm
        self.bq  = bq

    def run(self, mapping: DataMapping) -> List[GeneratedArtifact]:
        artifacts: List[GeneratedArtifact] = []

        for output_type in mapping.output_types:
            if output_type == OutputType.SQL_DDL:
                artifacts.append(self._gen_ddl(mapping))
            elif output_type == OutputType.SQL_VIEW:
                artifacts.append(self._gen_view(mapping))
            elif output_type in (OutputType.SQL_QUERY, OutputType.STORED_PROCEDURE):
                artifacts.append(self._gen_dml(mapping, output_type))
            elif output_type == OutputType.DBT_MODEL:
                artifacts.append(self._gen_dbt(mapping))
            elif output_type == OutputType.DATAFORM_SQLX:
                artifacts.append(self._gen_sqlx(mapping))

        # Dry-run all SQL artifacts
        for art in artifacts:
            if art.filename.endswith(".sql") or art.filename.endswith(".sqlx"):
                ok, bts, err = self.bq.dry_run(art.content)
                art.dry_run_valid = ok
                art.dry_run_bytes = bts
                if not ok:
                    logger.warning("Dry-run failed for %s: %s", art.filename, err)

        logger.info("Agent 3a: generated %d SQL artifacts for %s",
                    len(artifacts), mapping.jira_issue)
        return artifacts

    # ── Generators ────────────────────────────────────────────────────────────

    def _gen_ddl(self, m: DataMapping) -> GeneratedArtifact:
        prompt = self._prompt(m, "CREATE TABLE DDL",
            "Generate a BigQuery CREATE OR REPLACE TABLE DDL statement.\n"
            "Include partitioning, clustering, column descriptions, and table description.\n"
            "Return ONLY the SQL, no explanation.")
        sql = self.llm.complete(prompt, system=SYSTEM_PROMPT)
        return GeneratedArtifact(
            artifact_type=OutputType.SQL_DDL,
            filename=f"{m.target_table}.ddl.sql",
            content=sql,
            explanation=f"DDL for {m.target_dataset}.{m.target_table}",
        )

    def _gen_view(self, m: DataMapping) -> GeneratedArtifact:
        prompt = self._prompt(m, "BigQuery View",
            "Generate a CREATE OR REPLACE VIEW statement.\n"
            "The view should encapsulate all joins, filters, and transformations.\n"
            "Return ONLY the SQL.")
        sql = self.llm.complete(prompt, system=SYSTEM_PROMPT)
        return GeneratedArtifact(
            artifact_type=OutputType.SQL_VIEW,
            filename=f"vw_{m.target_table}.sql",
            content=sql,
            explanation=f"View over {', '.join(t.table for t in m.source_tables)}",
        )

    def _gen_dml(self, m: DataMapping, output_type: OutputType) -> GeneratedArtifact:
        strat_desc = (
            "DELETE rows matching the idempotency key, then INSERT the new rows"
            if m.idempotency_strategy.value == "delete_insert"
            else "MERGE using the idempotency key as the match condition"
        )
        prompt = self._prompt(m, "Incremental DML",
            f"Generate a {m.idempotency_strategy.value.upper()} DML script.\n"
            f"Strategy: {strat_desc}.\n"
            "Wrap in a BEGIN...EXCEPTION...END block for atomicity.\n"
            "Return ONLY the SQL.")
        sql = self.llm.complete(prompt, system=SYSTEM_PROMPT)
        fname = (
            f"sp_{m.target_table}.sql"
            if output_type == OutputType.STORED_PROCEDURE
            else f"dml_{m.target_table}.sql"
        )
        return GeneratedArtifact(
            artifact_type=output_type,
            filename=fname,
            content=sql,
            explanation=f"Idempotent DML ({m.idempotency_strategy.value}) for {m.target_table}",
        )

    def _gen_dbt(self, m: DataMapping) -> GeneratedArtifact:
        prompt = self._prompt(m, "dbt Model SQL",
            "Generate the SQL body for a dbt model (no CREATE statement — dbt handles materialisation).\n"
            "Use dbt ref() and source() macros for table references.\n"
            "Add {{ config(materialized='incremental', ...) }} at the top.\n"
            "Return ONLY the SQL with the config block.")
        sql = self.llm.complete(prompt, system=SYSTEM_PROMPT)
        return GeneratedArtifact(
            artifact_type=OutputType.DBT_MODEL,
            filename=f"{m.target_table}.sql",
            content=sql,
            explanation=f"dbt incremental model for {m.target_table}",
        )

    def _gen_sqlx(self, m: DataMapping) -> GeneratedArtifact:
        prompt = self._prompt(m, "Dataform SQLX",
            "Generate a Dataform SQLX file with a config block and the SELECT statement.\n"
            "Include assertions for NOT NULL and primary key uniqueness.\n"
            "Return ONLY the SQLX content.")
        sqlx = self.llm.complete(prompt, system=SYSTEM_PROMPT)
        return GeneratedArtifact(
            artifact_type=OutputType.DATAFORM_SQLX,
            filename=f"{m.target_table}.sqlx",
            content=sqlx,
            explanation=f"Dataform SQLX definition for {m.target_table}",
        )

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _prompt(self, m: DataMapping, task: str, instructions: str) -> str:
        sources = "\n".join(
            f"  - {t.dataset}.{t.table} AS {t.alias}"
            + (f" ({t.join_type} JOIN ON {t.join_condition})" if t.join_type else "")
            for t in m.source_tables
        )
        fields = "\n".join(
            f"  {f.target_field} {f.data_type} = {f.source_expression}"
            + (f"  -- {f.description}" if f.description else "")
            for f in m.field_mappings
        )
        return f"""Task: {task}
Jira Issue: {m.jira_issue}

Source tables:
{sources}

Target: {m.target_dataset}.{m.target_table}
Partition: {m.partition_field or 'none'}
Cluster: {', '.join(m.cluster_fields) or 'none'}
Idempotency: {m.idempotency_strategy.value} on {m.idempotency_key or 'N/A'}

Field mappings:
{fields}

Filters: {'; '.join(m.filters) or 'none'}
Grain: {', '.join(m.grain) or 'not specified'}

Business rules:
{chr(10).join('- ' + r for r in m.business_rules) or 'none'}

{instructions}
"""
