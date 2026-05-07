"""Agent 3d — Observability Agent.

Instruments pipelines for monitoring, alerting, and cost governance.
Generates: audit column DDL patches, Cloud Monitoring alert configs,
run-time logging hooks, and cost/performance dashboard queries.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from core.llm_client import LLMClient
from core.schemas import DataMapping, ObservabilityConfig

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a GCP platform engineer specialising in BigQuery observability.

Generate practical, deployable observability configuration for data pipelines.
Focus on:
  - Audit columns to add to target tables (created_at, updated_at, pipeline_run_id, source_system)
  - Structured logging hooks (Python/SQL snippets using google-cloud-logging)
  - Cloud Monitoring alert policies (YAML for gcloud or Terraform)
  - BigQuery INFORMATION_SCHEMA queries for cost and performance dashboards
  - Cost guard queries to detect and cap slot over-usage

Return strict JSON.
"""


class ObservabilityAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, mapping: DataMapping) -> ObservabilityConfig:
        target = f"{mapping.target_dataset}.{mapping.target_table}"
        prompt = f"""Generate observability config for this BigQuery pipeline:

Target table: {target}
Schedule: {mapping.schedule or 'on-demand'}
SLA hours: {mapping.sla_hours or 'not set'}
Partition field: {mapping.partition_field or 'none'}
Idempotency key: {mapping.idempotency_key or 'n/a'}

Return JSON with this structure:
{{
  "audit_columns": [
    {{"name": "pipeline_run_id", "type": "STRING", "default_expr": "GENERATE_UUID()"}},
    {{"name": "loaded_at", "type": "TIMESTAMP", "default_expr": "CURRENT_TIMESTAMP()"}}
  ],
  "logging_hooks": [
    "Python/SQL logging snippet as a string"
  ],
  "alert_configs": [
    {{
      "name": "alert name",
      "type": "Cloud Monitoring|Datadog|PagerDuty",
      "condition": "what triggers the alert",
      "threshold": "numeric threshold",
      "severity": "critical|warning|info",
      "yaml": "gcloud-compatible alert YAML"
    }}
  ],
  "dashboard_queries": [
    {{
      "name": "query display name",
      "sql": "SELECT ... FROM INFORMATION_SCHEMA.JOBS_BY_PROJECT WHERE ..."
    }}
  ],
  "cost_guard_sql": "SQL query that estimates cost and raises an error if over budget"
}}
"""
        payload = self.llm.complete_json(prompt, system=SYSTEM_PROMPT)

        config = ObservabilityConfig(
            audit_columns=payload.get("audit_columns", []),
            logging_hooks=payload.get("logging_hooks", []),
            alert_configs=payload.get("alert_configs", []),
            dashboard_queries=payload.get("dashboard_queries", []),
            cost_guard_sql=payload.get("cost_guard_sql"),
        )

        logger.info(
            "Agent 3d: observability config for %s — %d audit cols, %d alerts, %d dashboard queries",
            target,
            len(config.audit_columns),
            len(config.alert_configs),
            len(config.dashboard_queries),
        )
        return config

    def generate_audit_ddl_patch(self, mapping: DataMapping, config: ObservabilityConfig) -> str:
        """Generate ALTER TABLE statements to add audit columns."""
        target = f"`{mapping.target_dataset}.{mapping.target_table}`"
        stmts = [
            f"ALTER TABLE {target} ADD COLUMN IF NOT EXISTS "
            f"{col['name']} {col['type']} OPTIONS(description='auto-added audit column');"
            for col in config.audit_columns
        ]
        return "\n".join(stmts)

    def generate_python_logging_hook(self, mapping: DataMapping) -> str:
        return f'''"""Auto-generated structured logging hook for {mapping.target_table}."""
import uuid
import google.cloud.logging
from datetime import datetime

_logging_client = google.cloud.logging.Client()
_logging_client.setup_logging()

import logging
_logger = logging.getLogger("{mapping.target_table}_pipeline")


def log_pipeline_start(run_id: str) -> None:
    _logger.info("pipeline_started", extra={{
        "json_fields": {{
            "run_id":     run_id,
            "table":      "{mapping.target_dataset}.{mapping.target_table}",
            "jira_issue": "{mapping.jira_issue}",
            "started_at": datetime.utcnow().isoformat(),
        }}
    }})


def log_pipeline_complete(run_id: str, rows_written: int, bytes_processed: int) -> None:
    _logger.info("pipeline_completed", extra={{
        "json_fields": {{
            "run_id":          run_id,
            "table":           "{mapping.target_dataset}.{mapping.target_table}",
            "rows_written":    rows_written,
            "bytes_processed": bytes_processed,
            "completed_at":    datetime.utcnow().isoformat(),
        }}
    }})


def log_pipeline_error(run_id: str, error: str) -> None:
    _logger.error("pipeline_failed", extra={{
        "json_fields": {{
            "run_id":   run_id,
            "table":    "{mapping.target_dataset}.{mapping.target_table}",
            "error":    error,
            "failed_at": datetime.utcnow().isoformat(),
        }}
    }})
'''
