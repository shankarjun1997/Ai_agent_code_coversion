"""Agent 4 — QA Agent.

Validates generated pipelines against functional requirements and data quality
expectations. Generates test cases, executes them in BigQuery, and produces
a sign-off-ready QA report.

Human-in-the-loop gate: QA lead (Sandeep / Saikrishna) approves before release.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from core.bq_client import BQClient
from core.llm_client import LLMClient
from core.schemas import (
    DataMapping,
    EngineeringPackage,
    QAReport,
    RequirementsDoc,
    TestCase,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior data quality assurance engineer.

Generate comprehensive, executable test cases for BigQuery pipelines covering:
  - Row count validation (target vs source)
  - Schema checks (expected columns exist with correct types)
  - Null checks on required fields
  - Duplicate checks on grain / primary key
  - Referential integrity checks
  - Transformation correctness (spot-check computed fields)
  - Reconciliation (aggregate totals source vs target)
  - Restartability (re-running pipeline produces same result)
  - Freshness checks (data is not stale)

Each test must include a runnable BigQuery SQL query.
If a test cannot be expressed as SQL, provide a Python assertion.

Return strict JSON — an array of test case objects.
"""


class QAAgent:
    def __init__(self, llm: LLMClient, bq: BQClient):
        self.llm = llm
        self.bq  = bq

    def run(
        self,
        mapping:      DataMapping,
        requirements: RequirementsDoc,
        pkg:          EngineeringPackage,
    ) -> QAReport:
        """Generate test cases, execute them, return QA report."""

        test_cases = self._generate_test_cases(mapping, requirements, pkg)
        execution_results, defects = self._execute_tests(test_cases)

        sign_off_ready = len([d for d in defects if "CRITICAL" in d.upper()]) == 0

        report = QAReport(
            jira_issue=mapping.jira_issue,
            test_cases=test_cases,
            execution_results=execution_results,
            defects=defects,
            sign_off_ready=sign_off_ready,
        )

        logger.info(
            "Agent 4: %d tests, %d defects, sign_off_ready=%s",
            len(test_cases), len(defects), sign_off_ready,
        )
        return report

    # ── Test generation ───────────────────────────────────────────────────────

    def _generate_test_cases(
        self,
        mapping:      DataMapping,
        requirements: RequirementsDoc,
        pkg:          EngineeringPackage,
    ) -> List[TestCase]:
        target = f"{mapping.target_dataset}.{mapping.target_table}"
        sources = ", ".join(f"{t.dataset}.{t.table}" for t in mapping.source_tables)

        sql_artifacts = [a for a in pkg.artifacts if a.filename.endswith(".sql")]
        artifact_summary = "\n".join(
            f"  - {a.filename} (dry_run_valid={a.dry_run_valid})"
            for a in sql_artifacts
        )

        ac_text = requirements.jira_story_draft.acceptance_criteria

        prompt = f"""Generate QA test cases for this BigQuery pipeline:

Jira issue: {mapping.jira_issue}
Source tables: {sources}
Target table: {target}
Grain: {', '.join(mapping.grain) or 'not specified'}
Idempotency key: {mapping.idempotency_key or 'n/a'}
Partition field: {mapping.partition_field or 'none'}
SLA hours: {mapping.sla_hours or 'not set'}

Acceptance criteria from Jira:
{ac_text}

Business rules:
{chr(10).join('- ' + r for r in mapping.business_rules) or 'none'}

Generated artifacts:
{artifact_summary}

Return a JSON array of test cases:
[
  {{
    "test_name": "snake_case_test_name",
    "test_type": "row_count|schema_check|null_check|duplicate_check|referential_integrity|transformation|reconciliation|restartability|freshness",
    "sql": "SELECT ... FROM `{target}` WHERE ... -- returns rows on failure",
    "expected": null,
    "description": "what this test validates"
  }}
]

Include at minimum:
- 1 row count test
- 1 duplicate check on grain columns
- 1 null check per required field
- 1 reconciliation test (source vs target aggregate)
- 1 restartability test (idempotency verification)
- Tests for each acceptance criterion

Return only the JSON array.
"""
        raw = self.llm.complete_json(prompt, system=SYSTEM_PROMPT)
        if not isinstance(raw, list):
            raw = raw.get("test_cases", [])

        tests = []
        for t in raw:
            try:
                tests.append(TestCase(
                    test_name=t["test_name"],
                    test_type=t["test_type"],
                    sql=t["sql"],
                    expected=t.get("expected"),
                    description=t["description"],
                ))
            except Exception as exc:
                logger.warning("Skipping malformed test case: %s — %s", t, exc)

        return tests

    # ── Test execution ────────────────────────────────────────────────────────

    def _execute_tests(
        self, test_cases: List[TestCase]
    ) -> tuple[List[Dict[str, Any]], List[str]]:
        results = []
        defects = []

        for tc in test_cases:
            try:
                rows = self.bq.run_query(tc.sql)
                failure = len(rows) > 0   # test returns rows on failure

                result: Dict[str, Any] = {
                    "test_id":   tc.test_id,
                    "test_name": tc.test_name,
                    "status":    "FAIL" if failure else "PASS",
                    "rows":      rows[:5],   # sample of violation rows
                }

                if failure:
                    severity = "CRITICAL" if tc.test_type in (
                        "row_count", "null_check", "referential_integrity"
                    ) else "WARNING"
                    defects.append(
                        f"[{severity}] {tc.test_name}: {len(rows)} violation(s) — {tc.description}"
                    )

                results.append(result)
                logger.info("QA test %s: %s", tc.test_name, result["status"])

            except Exception as exc:
                results.append({
                    "test_id":   tc.test_id,
                    "test_name": tc.test_name,
                    "status":    "ERROR",
                    "error":     str(exc),
                })
                defects.append(f"[WARNING] {tc.test_name}: execution error — {exc}")
                logger.warning("QA test %s errored: %s", tc.test_name, exc)

        return results, defects

    def generate_test_report_markdown(self, report: QAReport) -> str:
        pass_count = sum(1 for r in report.execution_results if r.get("status") == "PASS")
        fail_count = sum(1 for r in report.execution_results if r.get("status") == "FAIL")
        err_count  = sum(1 for r in report.execution_results if r.get("status") == "ERROR")

        rows = "\n".join(
            f"| {r['test_name']} | {r['status']} |"
            for r in report.execution_results
        )
        defect_list = "\n".join(f"- {d}" for d in report.defects) or "_None_"

        return f"""# QA Report — {report.jira_issue}

**Report ID:** {report.report_id}
**Generated:** {report.created_at.isoformat()}
**Sign-off ready:** {'✓ YES' if report.sign_off_ready else '✗ NO — defects must be resolved'}

## Test Summary
| Metric | Count |
|--------|-------|
| Total  | {len(report.test_cases)} |
| PASS   | {pass_count} |
| FAIL   | {fail_count} |
| ERROR  | {err_count} |

## Test Results
| Test Name | Status |
|-----------|--------|
{rows}

## Defects
{defect_list}

---
*Generated by SQL-Gen QA Agent (Agent 4)*
"""
