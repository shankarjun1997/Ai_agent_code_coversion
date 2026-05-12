"""Agent 2 — Mapping Design Agent.

Flow matches the PDF spec:
  1. Pre-fetch BQ schemas in Python (no LLM tool-use loop)
  2. Prompt builder assembles story + sidebar + governance + schemas
  3. Single LLM request → JSON with 4 sections
  4. Parse sections → DataMapping
  5. BQ CLI schema verification (post-process)
  6. SVG diagram (post-process)
  7. Human review gate: approve or refine (loops back to step 2)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from core.bq_client import BQClient
from core import bq_cli
from core.llm_client import LLMClient
from core.schemas import (
    DataMapping,
    FieldMapping,
    IdempotencyStrategy,
    JiraStory,
    OutputType,
    SourceTable,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior data engineer and solutions architect.
Produce a complete, precise source-to-target data mapping specification.
You will be given: a Jira story, BQ schema context, sidebar configuration, and governance requirements.

Return ONLY a valid JSON object with exactly these four top-level keys:

{
  "field_mapping": [
    {
      "source_expression": "<exact BQ SQL expression>",
      "target_field": "<snake_case column name>",
      "data_type": "<BQ type: STRING|INT64|FLOAT64|BOOL|DATE|TIMESTAMP|BYTES|NUMERIC>",
      "nullable": true,
      "description": "<business meaning>",
      "transformation_logic": "<SQL or rule, empty string if passthrough>",
      "is_pii": false,
      "sensitivity": "<none|low|medium|high>"
    }
  ],
  "design_spec": {
    "source_tables": [
      {
        "dataset": "<dataset>",
        "table": "<table>",
        "alias": "<short alias>",
        "join_type": "<INNER|LEFT|CROSS or empty for primary>",
        "join_condition": "<ON clause or empty>"
      }
    ],
    "target_dataset": "<dataset>",
    "target_table": "<table>",
    "partition_field": "<field or null>",
    "cluster_fields": [],
    "output_types": ["sql_view"],
    "tags": [],
    "notes": "<architecture notes>"
  },
  "transform_logic": {
    "business_rules": ["<rule 1>", "<rule 2>"],
    "filters": ["<WHERE clause fragments>"],
    "grain": ["<field defining uniqueness>"],
    "transformations": [{"field": "<target>", "logic": "<SQL or description>"}],
    "idempotency_strategy": "delete_insert",
    "idempotency_key": "<field>",
    "schedule": "<cron or null>",
    "sla_hours": null
  },
  "metadata_lineage": {
    "data_owner": "<name or team>",
    "data_steward": "<name or team>",
    "pii_fields": [{"field": "<target_field>", "sensitivity": "<medium|high>"}],
    "retention_days": null
  }
}

Rules:
- Use ONLY columns confirmed to exist in the schema context provided.
- Every source_expression must be valid BigQuery SQL.
- Include partition_field and idempotency_key for incremental pipelines.
- Classify all PII fields with is_pii: true and appropriate sensitivity.
- Return ONLY the JSON — no markdown, no explanation.
"""


class MappingAgent:
    def __init__(self, llm: LLMClient, bq: BQClient):
        self.llm = llm
        self.bq  = bq

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        story: JiraStory,
        extra_context: str = "",
        sidebar_inputs: Optional[Dict] = None,
    ) -> DataMapping:
        """Single-request mapping: fetch schemas → build prompt → one LLM call → parse."""
        schema_context = self._prefetch_schemas(story)
        prompt = self._build_prompt(story, schema_context, sidebar_inputs, extra_context)

        logger.info("Agent 2: single LLM request for mapping '%s'", story.issue_key)
        raw = self.llm.complete_json(prompt, system=SYSTEM_PROMPT, max_tokens=8192)

        mapping = self._parse_response(raw, story)
        mapping = self._verify_schema(mapping)
        mapping = self._generate_svg(mapping)

        logger.info(
            "Agent 2: mapping %s — %d sources, %d fields, outputs: %s",
            mapping.mapping_id,
            len(mapping.source_tables),
            len(mapping.field_mappings),
            [o.value for o in mapping.output_types],
        )
        return mapping

    # ── Step 1: Pre-fetch schemas ─────────────────────────────────────────────

    def _prefetch_schemas(self, story: JiraStory) -> str:
        """Gather BQ dataset + table info and return as formatted text for the prompt."""
        lines: List[str] = []

        # List datasets
        try:
            datasets = bq_cli.list_datasets()
            lines.append(f"Available datasets: {', '.join(datasets)}")
        except Exception as exc:
            logger.warning("bq_cli.list_datasets failed: %s", exc)
            try:
                datasets = self.bq.get_all_datasets()
                lines.append(f"Available datasets (python client): {', '.join(datasets)}")
            except Exception:
                datasets = []
                lines.append("Dataset listing unavailable.")

        # Extract likely keywords from story text
        story_text = f"{story.summary} {story.description} {story.acceptance_criteria}".lower()
        keywords = _extract_keywords(story_text)

        # For each dataset, search for matching tables
        for ds in datasets[:5]:  # cap to first 5 datasets
            try:
                tables = bq_cli.list_tables(ds)
                relevant = [t for t in tables if any(k in t.lower() for k in keywords)]
                if not relevant:
                    relevant = tables[:3]  # fallback: first 3
                for table in relevant[:4]:
                    try:
                        schema = bq_cli.get_table_schema(ds, table)
                        col_list = ", ".join(
                            f"{c['name']}:{c['type']}" for c in schema[:40]
                        )
                        lines.append(f"\n`{ds}.{table}` columns: {col_list}")
                    except Exception as exc:
                        logger.debug("Schema fetch failed %s.%s: %s", ds, table, exc)
            except Exception as exc:
                logger.debug("list_tables failed for %s: %s", ds, exc)

        return "\n".join(lines) if lines else "No schema context available."

    # ── Step 2: Prompt builder ────────────────────────────────────────────────

    def _build_prompt(
        self,
        story: JiraStory,
        schema_context: str,
        sidebar_inputs: Optional[Dict],
        extra_context: str,
    ) -> str:
        parts = [
            f"Jira Story: {story.issue_key}",
            f"Summary: {story.summary}",
            f"\nDescription:\n{story.description}",
            f"\nAcceptance Criteria:\n{story.acceptance_criteria}",
            f"\nLabels: {', '.join(story.labels)}",
            f"\n\n--- BigQuery Schema Context ---\n{schema_context}",
        ]

        # Sidebar / governance inputs
        if sidebar_inputs:
            gov: List[str] = []
            if sidebar_inputs.get("source_fields"):
                gov.append(f"Source fields: {', '.join(sidebar_inputs['source_fields'])}")
            if sidebar_inputs.get("target_fields"):
                gov.append(f"Required target fields: {', '.join(sidebar_inputs['target_fields'])}")
            if sidebar_inputs.get("business_rules"):
                rules = sidebar_inputs["business_rules"]
                gov.append("Business rules:\n" + "\n".join(f"  - {r}" for r in rules))
            if sidebar_inputs.get("lineage"):
                gov.append(f"Lineage context: {sidebar_inputs['lineage']}")
            if sidebar_inputs.get("pii_fields"):
                gov.append(f"PII fields (must mark is_pii=true): {', '.join(sidebar_inputs['pii_fields'])}")
            if sidebar_inputs.get("data_owner"):
                gov.append(f"Data owner: {sidebar_inputs['data_owner']}")
            if gov:
                parts.append("\n\n--- Sidebar Configuration ---\n" + "\n".join(gov))

        # Reviewer refinement feedback
        if extra_context:
            parts.append(f"\n\n--- Reviewer Feedback (MUST incorporate) ---\n{extra_context}")

        parts.append("\n\nProduce the JSON mapping specification now.")
        return "\n".join(parts)

    # ── Step 3: Parse JSON response → DataMapping ─────────────────────────────

    def _parse_response(self, raw: Dict, story: JiraStory) -> DataMapping:
        fm_raw  = raw.get("field_mapping", [])
        ds_raw  = raw.get("design_spec", {})
        tl_raw  = raw.get("transform_logic", {})
        ml_raw  = raw.get("metadata_lineage", {})

        source_tables = [
            SourceTable(
                dataset=t["dataset"],
                table=t["table"],
                alias=t.get("alias", t["table"][:3]),
                join_type=t.get("join_type"),
                join_condition=t.get("join_condition"),
            )
            for t in ds_raw.get("source_tables", [])
        ]

        field_mappings = [
            FieldMapping(
                source_expression=f["source_expression"],
                target_field=f["target_field"],
                data_type=f["data_type"],
                nullable=f.get("nullable", True),
                description=f.get("description", ""),
                transformation_logic=f.get("transformation_logic", ""),
                is_pii=f.get("is_pii", False),
                sensitivity=f.get("sensitivity", "none"),
            )
            for f in fm_raw
        ]

        output_types_raw = ds_raw.get("output_types", ["sql_view"])
        try:
            output_types = [OutputType(o) for o in output_types_raw]
        except ValueError:
            output_types = [OutputType.SQL_VIEW]

        idempotency_raw = tl_raw.get("idempotency_strategy", "delete_insert")
        try:
            idempotency_strategy = IdempotencyStrategy(idempotency_raw)
        except ValueError:
            idempotency_strategy = IdempotencyStrategy.DELETE_INSERT

        return DataMapping(
            jira_issue=story.issue_key,
            source_tables=source_tables,
            target_dataset=ds_raw.get("target_dataset", ""),
            target_table=ds_raw.get("target_table", ""),
            field_mappings=field_mappings,
            filters=tl_raw.get("filters", []),
            grain=tl_raw.get("grain", []),
            business_rules=tl_raw.get("business_rules", []),
            output_types=output_types,
            partition_field=ds_raw.get("partition_field"),
            cluster_fields=ds_raw.get("cluster_fields", []),
            idempotency_strategy=idempotency_strategy,
            idempotency_key=tl_raw.get("idempotency_key"),
            schedule=tl_raw.get("schedule"),
            sla_hours=tl_raw.get("sla_hours"),
            data_owner=ml_raw.get("data_owner"),
            data_steward=ml_raw.get("data_steward"),
            tags=ds_raw.get("tags", []),
            notes=ds_raw.get("notes"),
        )

    # ── Post-processing: schema verify + SVG ─────────────────────────────────

    def _verify_schema(self, mapping: DataMapping) -> DataMapping:
        source_tables = [
            {"dataset": st.dataset, "table": st.table, "alias": st.alias}
            for st in mapping.source_tables
        ]
        field_mappings = [
            {"source_expression": fm.source_expression, "target_field": fm.target_field, "data_type": fm.data_type}
            for fm in mapping.field_mappings
        ]
        try:
            result = bq_cli.verify_mapping_schema(source_tables, field_mappings)
            mapping.schema_verify = result.to_dict()
            if result.is_clean:
                logger.info("Agent 2: schema verification PASSED for %s", mapping.mapping_id)
            else:
                logger.warning("Agent 2: schema verification issues for %s:\n%s", mapping.mapping_id, result.summary())
        except Exception as exc:
            logger.warning("Agent 2: schema verification skipped: %s", exc)
            mapping.schema_verify = {"error": str(exc)}
        return mapping

    def _generate_svg(self, mapping: DataMapping) -> DataMapping:
        try:
            from agents.svg_generator import generate_mapping_svg
            verify_result = None
            if mapping.schema_verify and not mapping.schema_verify.get("error"):
                verify_result = _VerifyProxy(mapping.schema_verify)
            svg_path = generate_mapping_svg(mapping, verify_result=verify_result)
            mapping.svg_path = svg_path
            logger.info("Agent 2: SVG written to %s", svg_path)
        except Exception as exc:
            logger.warning("Agent 2: SVG generation skipped: %s", exc)
        return mapping


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_keywords(text: str) -> List[str]:
    """Pull likely table-name keywords from story text."""
    stop = {"the", "a", "an", "and", "or", "for", "to", "in", "of", "with",
            "from", "as", "is", "are", "be", "by", "on", "at", "we", "this",
            "that", "should", "must", "will", "need", "all", "each", "any"}
    words = [w.strip(".,;:()[]\"'") for w in text.split()]
    return list({w for w in words if len(w) > 3 and w not in stop})[:20]


def extract_four_sections(mapping: DataMapping) -> Dict:
    """Split a DataMapping into the 4 reviewer tab sections."""
    return {
        "field_mapping": [
            {
                "source": fm.source_expression,
                "target": fm.target_field,
                "type": fm.data_type,
                "nullable": fm.nullable,
                "description": fm.description or "",
                "transformation_logic": fm.transformation_logic or "",
                "is_pii": fm.is_pii,
                "sensitivity": fm.sensitivity or "none",
            }
            for fm in mapping.field_mappings
        ],
        "transform_logic": {
            "business_rules": mapping.business_rules,
            "filters": mapping.filters,
            "grain": mapping.grain,
            "transformations": [
                {"field": fm.target_field, "logic": fm.transformation_logic}
                for fm in mapping.field_mappings if fm.transformation_logic
            ],
            "idempotency_strategy": mapping.idempotency_strategy.value if mapping.idempotency_strategy else None,
            "idempotency_key": mapping.idempotency_key,
            "schedule": mapping.schedule,
            "sla_hours": mapping.sla_hours,
        },
        "design_spec": {
            "source_tables": [
                {"dataset": st.dataset, "table": st.table, "alias": st.alias, "join_type": st.join_type}
                for st in mapping.source_tables
            ],
            "target_dataset": mapping.target_dataset,
            "target_table": mapping.target_table,
            "partition_field": mapping.partition_field,
            "cluster_fields": mapping.cluster_fields,
            "output_types": [o.value for o in mapping.output_types],
            "tags": mapping.tags,
            "notes": mapping.notes,
        },
        "metadata_lineage": {
            "data_owner": mapping.data_owner,
            "data_steward": mapping.data_steward,
            "pii_fields": [
                {"field": fm.target_field, "sensitivity": fm.sensitivity}
                for fm in mapping.field_mappings if fm.is_pii
            ],
            "schema_verify": mapping.schema_verify or {},
            "mapping_id": mapping.mapping_id,
            "jira_issue": mapping.jira_issue,
            "svg_path": mapping.svg_path,
        },
    }


class _VerifyProxy:
    """Duck-type proxy so svg_generator can read SchemaVerificationResult fields from a dict."""
    def __init__(self, d: Dict):
        self.verified_fields  = d.get("verified_fields", [])
        self.missing_fields   = d.get("missing_fields", [])
        self.type_mismatches  = d.get("type_mismatches", [])
        self.extra_fields     = d.get("extra_fields", [])
        self.tables_not_found = d.get("tables_not_found", [])

    @property
    def is_clean(self) -> bool:
        return not (self.missing_fields or self.type_mismatches or self.tables_not_found)
