"""Agent 2 — Mapping / Design Document Agent.

Produces source-to-target mapping specifications grounded in the approved
Jira story, BQ schemas, data dictionaries, and lineage metadata.

Uses multi-turn tool-use with Claude to discover schemas before finalising.
Human-in-the-loop gate: Shankar must approve before engineering starts.

After finalize_mapping the agent:
  1. Crawls BQ CLI to verify every source column reference exists.
  2. Generates a SVG workflow diagram of the mapping.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
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
Your task is to produce a precise, complete source-to-target data mapping
specification from a Jira story and BigQuery schemas.

Workflow:
1. Call bq_cli_list_datasets to see all available BQ datasets via the CLI.
2. Call list_datasets (Python client) as a fallback if CLI returns nothing.
3. Call search_schema with relevant keywords from the story.
4. Call bq_cli_show_schema for each identified source table to get the
   authoritative CLI-verified schema.
5. Call get_table_schema (Python client) as a fallback or for sample rows.
6. Design the target table (name, fields, grain, partition, cluster).
7. Map every required field with exact BigQuery SQL expressions.
8. Call finalize_mapping with the complete specification.

Rules:
- Prefer bq_cli_show_schema over get_table_schema — it matches what a DBA sees.
- Use only confirmed tables/columns discovered via tools.
- Every source expression must be valid BigQuery SQL.
- Include partition_field and idempotency_key for incremental pipelines.
- List ALL business rules explicitly.
- Classify PII fields (is_pii: true) and set sensitivity labels.
"""

TOOLS = [
    {
        "name": "bq_cli_list_datasets",
        "description": "List all BigQuery datasets via the bq CLI (authoritative).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "bq_cli_show_schema",
        "description": "Get the full column schema for a table via bq show --schema (authoritative).",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string"},
                "table":   {"type": "string"},
            },
            "required": ["dataset", "table"],
        },
    },
    {
        "name": "bq_cli_list_tables",
        "description": "List all tables in a dataset via the bq CLI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string"},
            },
            "required": ["dataset"],
        },
    },
    {
        "name": "list_datasets",
        "description": "List all BigQuery datasets in the project (Python client fallback).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_schema",
        "description": "Search INFORMATION_SCHEMA for tables/columns matching keywords.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset":  {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["dataset", "keywords"],
        },
    },
    {
        "name": "get_table_schema",
        "description": "Get the full column schema for a specific table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string"},
                "table":   {"type": "string"},
            },
            "required": ["dataset", "table"],
        },
    },
    {
        "name": "get_sample_rows",
        "description": "Get a few sample rows to understand data shape.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string"},
                "table":   {"type": "string"},
                "n":       {"type": "integer", "default": 3},
            },
            "required": ["dataset", "table"],
        },
    },
    {
        "name": "finalize_mapping",
        "description": "Finalise and save the complete data mapping specification.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_tables": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dataset":        {"type": "string"},
                            "table":          {"type": "string"},
                            "alias":          {"type": "string"},
                            "join_type":      {"type": "string"},
                            "join_condition": {"type": "string"},
                        },
                        "required": ["dataset", "table", "alias"],
                    },
                },
                "target_dataset":       {"type": "string"},
                "target_table":         {"type": "string"},
                "field_mappings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_expression":    {"type": "string"},
                            "target_field":         {"type": "string"},
                            "data_type":            {"type": "string"},
                            "nullable":             {"type": "boolean"},
                            "description":          {"type": "string"},
                            "transformation_logic": {"type": "string"},
                            "is_pii":               {"type": "boolean"},
                            "sensitivity":          {"type": "string"},
                        },
                        "required": ["source_expression", "target_field", "data_type"],
                    },
                },
                "filters":              {"type": "array", "items": {"type": "string"}},
                "grain":                {"type": "array", "items": {"type": "string"}},
                "business_rules":       {"type": "array", "items": {"type": "string"}},
                "output_types":         {"type": "array", "items": {"type": "string"}},
                "partition_field":      {"type": "string"},
                "cluster_fields":       {"type": "array", "items": {"type": "string"}},
                "idempotency_strategy": {"type": "string"},
                "idempotency_key":      {"type": "string"},
                "schedule":             {"type": "string"},
                "sla_hours":            {"type": "number"},
                "data_owner":           {"type": "string"},
                "data_steward":         {"type": "string"},
                "tags":                 {"type": "array", "items": {"type": "string"}},
                "notes":                {"type": "string"},
            },
            "required": [
                "source_tables", "target_dataset", "target_table",
                "field_mappings", "output_types",
            ],
        },
    },
]


class MappingAgent:
    def __init__(self, llm: LLMClient, bq: BQClient):
        self.llm = llm
        self.bq  = bq
        self._pending_mapping: Optional[Dict] = None

    def _handle_tool(self, tool_name: str, tool_input: Dict) -> str:
        # ── BQ CLI tools (authoritative) ──────────────────────────────────────
        if tool_name == "bq_cli_list_datasets":
            datasets = bq_cli.list_datasets()
            return json.dumps({"datasets": datasets})

        if tool_name == "bq_cli_list_tables":
            tables = bq_cli.list_tables(tool_input["dataset"])
            return json.dumps({"tables": tables})

        if tool_name == "bq_cli_show_schema":
            schema = bq_cli.get_table_schema(
                tool_input["dataset"], tool_input["table"]
            )
            return json.dumps({"schema": schema, "count": len(schema)})

        # ── Python BQ client tools (fallback / supplement) ────────────────────
        if tool_name == "list_datasets":
            return json.dumps({"datasets": self.bq.get_all_datasets()})

        if tool_name == "search_schema":
            result = self.bq.search_schema(
                tool_input["dataset"], tool_input.get("keywords", [])
            )
            return json.dumps(result[:200])   # cap to avoid context overflow

        if tool_name == "get_table_schema":
            result = self.bq.get_table_schema(
                tool_input["dataset"], tool_input["table"]
            )
            return json.dumps(result)

        if tool_name == "get_sample_rows":
            result = self.bq.get_sample_rows(
                tool_input["dataset"], tool_input["table"], tool_input.get("n", 3)
            )
            return json.dumps(result, default=str)

        if tool_name == "finalize_mapping":
            self._pending_mapping = tool_input
            return json.dumps({"status": "mapping_finalised"})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def run(self, story: JiraStory, extra_context: str = "") -> DataMapping:
        """Discover schema and produce a DataMapping for the given story."""
        self._pending_mapping = None

        user_msg = f"""Create a complete data mapping for this Jira story:

Issue:   {story.issue_key}
Summary: {story.summary}

Description:
{story.description}

Acceptance Criteria:
{story.acceptance_criteria}

Labels: {', '.join(story.labels)}
{f'Additional context:{extra_context}' if extra_context else ''}

Steps:
1. List available datasets.
2. Search for source tables relevant to the requirements.
3. Fetch full schemas for identified tables.
4. Design the target table and field mappings.
5. Call finalize_mapping with the complete specification.
"""
        _, tool_history = self.llm.run_agent(
            system=SYSTEM_PROMPT,
            user_message=user_msg,
            tools=TOOLS,
            tool_handler=self._handle_tool,
        )

        if not self._pending_mapping:
            raise ValueError("Agent 2 did not call finalize_mapping — mapping incomplete.")

        raw = self._pending_mapping
        mapping = DataMapping(
            jira_issue=story.issue_key,
            source_tables=[SourceTable(**t) for t in raw["source_tables"]],
            target_dataset=raw["target_dataset"],
            target_table=raw["target_table"],
            field_mappings=[FieldMapping(**f) for f in raw["field_mappings"]],
            filters=raw.get("filters", []),
            grain=raw.get("grain", []),
            business_rules=raw.get("business_rules", []),
            output_types=[OutputType(o) for o in raw.get("output_types", ["sql_view"])],
            partition_field=raw.get("partition_field"),
            cluster_fields=raw.get("cluster_fields", []),
            idempotency_strategy=IdempotencyStrategy(
                raw.get("idempotency_strategy", "delete_insert")
            ),
            idempotency_key=raw.get("idempotency_key"),
            schedule=raw.get("schedule"),
            sla_hours=raw.get("sla_hours"),
            data_owner=raw.get("data_owner"),
            data_steward=raw.get("data_steward"),
            tags=raw.get("tags", []),
            notes=raw.get("notes"),
        )

        # ── BQ CLI schema verification ────────────────────────────────────────
        mapping = self._verify_schema(mapping)

        # ── SVG workflow diagram ──────────────────────────────────────────────
        mapping = self._generate_svg(mapping)

        logger.info(
            "Agent 2: mapping %s created — %d sources, %d fields, outputs: %s, svg: %s",
            mapping.mapping_id,
            len(mapping.source_tables),
            len(mapping.field_mappings),
            [o.value for o in mapping.output_types],
            mapping.svg_path or "none",
        )
        return mapping

    def _verify_schema(self, mapping: DataMapping) -> DataMapping:
        """Crawl BQ CLI and verify every source column reference in the mapping."""
        source_tables = [
            {
                "dataset": st.dataset,
                "table":   st.table,
                "alias":   st.alias,
            }
            for st in mapping.source_tables
        ]
        field_mappings = [
            {
                "source_expression": fm.source_expression,
                "target_field":      fm.target_field,
                "data_type":         fm.data_type,
            }
            for fm in mapping.field_mappings
        ]
        try:
            result = bq_cli.verify_mapping_schema(source_tables, field_mappings)
            mapping.schema_verify = result.to_dict()
            if result.is_clean:
                logger.info("Agent 2: BQ CLI schema verification PASSED for %s", mapping.mapping_id)
            else:
                logger.warning(
                    "Agent 2: BQ CLI schema verification has issues for %s:\n%s",
                    mapping.mapping_id, result.summary()
                )
        except Exception as exc:
            logger.warning("Agent 2: BQ CLI schema verification skipped: %s", exc)
            mapping.schema_verify = {"error": str(exc)}
        return mapping

    def _generate_svg(self, mapping: DataMapping) -> DataMapping:
        """Generate SVG workflow diagram and store path on the mapping."""
        try:
            from agents.svg_generator import generate_mapping_svg

            verify_result = None
            if mapping.schema_verify and not mapping.schema_verify.get("error"):
                # Reconstruct a light proxy so svg_generator can read its fields
                verify_result = _VerifyProxy(mapping.schema_verify)

            svg_path = generate_mapping_svg(mapping, verify_result=verify_result)
            mapping.svg_path = svg_path
            logger.info("Agent 2: SVG diagram written to %s", svg_path)
        except Exception as exc:
            logger.warning("Agent 2: SVG generation skipped: %s", exc)
        return mapping


class _VerifyProxy:
    """Minimal duck-type proxy so svg_generator can read SchemaVerificationResult fields
    from a plain dict (what gets stored in DataMapping.schema_verify)."""

    def __init__(self, d: Dict):
        self.verified_fields  = d.get("verified_fields", [])
        self.missing_fields   = d.get("missing_fields", [])
        self.type_mismatches  = d.get("type_mismatches", [])
        self.extra_fields     = d.get("extra_fields", [])
        self.tables_not_found = d.get("tables_not_found", [])

    @property
    def is_clean(self) -> bool:
        return not (self.missing_fields or self.type_mismatches or self.tables_not_found)
