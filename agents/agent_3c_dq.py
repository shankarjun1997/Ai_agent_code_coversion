"""Agent 3c — Data Quality Agent.

Generates DQ rules as Dataform assertions, dbt tests, and/or BigQuery
stored procedures based on the approved DataMapping and business rules.
"""
from __future__ import annotations

import json
import logging
from typing import List

from core.llm_client import LLMClient
from core.schemas import DataMapping, DQReport, DQRule, DQSeverity

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a data quality engineer specialising in BigQuery pipelines.

Generate comprehensive DQ rules covering:
  - Uniqueness:           no duplicate primary keys
  - Completeness:         required fields are not NULL / empty
  - Validity:             values within expected ranges / domains
  - Referential integrity: foreign keys resolve in reference tables
  - Freshness:            data is not stale beyond the SLA
  - Custom business rules: derived from the mapping specification

For each rule provide:
  - rule_name:    snake_case identifier
  - rule_type:    uniqueness|completeness|validity|referential_integrity|freshness|custom
  - expression:   exact BigQuery SQL assertion (returns rows on failure)
  - severity:     critical|warning|info
  - description:  plain English explanation
  - remediation:  suggested fix for violations

Return strict JSON — an array of rule objects.
"""


class DQAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, mapping: DataMapping) -> DQReport:
        """Generate DQ rules and output formats for the given mapping."""
        target = f"{mapping.target_dataset}.{mapping.target_table}"
        fields_desc = "\n".join(
            f"  - {f.target_field} ({f.data_type}, nullable={f.nullable},"
            f" pii={f.is_pii}): {f.description or 'n/a'}"
            for f in mapping.field_mappings
        )
        rules_prompt = f"""Generate DQ rules for:

Target table: {target}
Partition: {mapping.partition_field or 'none'}
Grain (unique key): {', '.join(mapping.grain) or 'not specified'}
SLA hours: {mapping.sla_hours or 'not specified'}

Fields:
{fields_desc}

Business rules:
{chr(10).join('- ' + r for r in mapping.business_rules) or 'none'}

Idempotency key: {mapping.idempotency_key or 'n/a'}

Return a JSON array of DQ rule objects matching this schema:
[
  {{
    "rule_name": "...",
    "rule_type": "uniqueness|completeness|validity|referential_integrity|freshness|custom",
    "target_column": "column_name or null",
    "expression": "SELECT ... FROM `{target}` WHERE <violation_condition>",
    "severity": "critical|warning|info",
    "threshold": null,
    "description": "...",
    "remediation": "..."
  }}
]

Return only the JSON array.
"""
        raw_rules = self.llm.complete_json(rules_prompt, system=SYSTEM_PROMPT)
        if not isinstance(raw_rules, list):
            raw_rules = raw_rules.get("rules", [])

        rules: List[DQRule] = []
        for r in raw_rules:
            try:
                rules.append(DQRule(
                    rule_name=r["rule_name"],
                    rule_type=r["rule_type"],
                    target_table=target,
                    target_column=r.get("target_column"),
                    expression=r["expression"],
                    severity=DQSeverity(r.get("severity", "critical")),
                    threshold=r.get("threshold"),
                    description=r["description"],
                    remediation=r.get("remediation"),
                ))
            except Exception as exc:
                logger.warning("Skipping malformed DQ rule: %s — %s", r, exc)

        dataform_yaml = self._to_dataform_yaml(rules, target)
        dbt_yaml      = self._to_dbt_yaml(rules, mapping)
        bq_procedure  = self._to_bq_procedure(rules, target)

        logger.info("Agent 3c: generated %d DQ rules for %s", len(rules), target)
        return DQReport(
            rules=rules,
            dataform_yaml=dataform_yaml,
            dbt_tests_yaml=dbt_yaml,
            bq_procedure=bq_procedure,
        )

    # ── Format converters ─────────────────────────────────────────────────────

    def _to_dataform_yaml(self, rules: List[DQRule], target: str) -> str:
        lines = [f"# Dataform assertions for {target}", "assertions:"]
        for r in rules:
            lines.append(f"  - name: {r.rule_name}")
            lines.append(f"    description: {r.description}")
            lines.append(f"    severity: {r.severity.value}")
            lines.append(f"    query: |")
            for sql_line in r.expression.splitlines():
                lines.append(f"      {sql_line}")
        return "\n".join(lines)

    def _to_dbt_yaml(self, rules: List[DQRule], mapping: DataMapping) -> str:
        target = f"{mapping.target_dataset}.{mapping.target_table}"
        lines = [
            f"# dbt tests for {target}",
            "models:",
            f"  - name: {mapping.target_table}",
            "    columns:",
        ]
        # Group rules by column
        col_rules: dict = {}
        for r in rules:
            col = r.target_column or "_table"
            col_rules.setdefault(col, []).append(r)

        for col, col_r_list in col_rules.items():
            lines.append(f"      - name: {col if col != '_table' else 'id'}")
            lines.append("        tests:")
            for r in col_r_list:
                if r.rule_type == "uniqueness":
                    lines.append("          - unique")
                elif r.rule_type == "completeness":
                    lines.append("          - not_null")
                else:
                    lines.append(f"          - dbt_utils.expression_is_true:")
                    lines.append(f"              expression: \"-- {r.rule_name}: see custom test\"")

        return "\n".join(lines)

    def _to_bq_procedure(self, rules: List[DQRule], target: str) -> str:
        checks = "\n\n".join(
            f"  -- {r.rule_name} ({r.severity.value})\n"
            f"  SET v_violations = (SELECT COUNT(*) FROM ({r.expression}));\n"
            f"  IF v_violations > 0 THEN\n"
            f"    INSERT INTO dq_log VALUES('{r.rule_name}', '{r.severity.value}', "
            f"v_violations, CURRENT_TIMESTAMP(), '{r.description}');\n"
            f"  END IF;"
            for r in rules
        )
        return f"""-- Auto-generated DQ procedure for {target}
CREATE OR REPLACE PROCEDURE `{target.replace('.', '_')}_dq_check`()
BEGIN
  DECLARE v_violations INT64;

{checks}
END;"""
