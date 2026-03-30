"""
Agent 3 — Debug Agent
======================
Identifies root cause of validation failures.

Uses LLM reasoning to analyze:
  - SQL logic differences between source and target
  - Config variable mismatches
  - Join condition changes
  - Aggregation differences
  - Data type conversions
"""
import os
import re
import json
from typing import Optional

from . import BaseAgent, AgentResult


class DebugAgent(BaseAgent):
    """
    Agent 3: Root-cause analysis for validation failures.
    
    Takes validation results as input, analyzes each failure,
    and produces detailed diagnosis with suggested fixes.
    """

    AGENT_NAME = "debug_agent"

    # Issue categories and their analysis strategies
    CATEGORIES = {
        "missing_config_var": "analyze_missing_config_var",
        "wrong_environment": "analyze_wrong_environment",
        "hardcoded_project_id": "analyze_hardcoded_reference",
        "hardcoded_etl_type": "analyze_hardcoded_query_label",
        "hardcoded_environment": "analyze_hardcoded_query_label",
        "hardcoded_vsad": "analyze_hardcoded_query_label",
        "missing_query_label": "analyze_missing_query_label",
        "table_id_ordering": "analyze_table_id_ordering",
        "dag_id_naming": "analyze_dag_id_naming",
        "key_mismatch": "analyze_config_key_mismatch",
        "unclosed_backtick": "analyze_sql_syntax_error",
    }

    def execute(self, input_data: AgentResult = None) -> AgentResult:
        result = AgentResult(self.AGENT_NAME, self.module_name)
        self.logger.info(f"=== Debug Agent: {self.module_name} ===")

        if not input_data:
            result.set_failure("No input data from validation agent")
            self.save_result(result)
            return result

        try:
            diagnoses = []
            all_issues = self._extract_all_issues(input_data)

            self.logger.info(f"Analyzing {len(all_issues)} issues from validation")

            for issue in all_issues:
                diagnosis = self._diagnose_issue(issue)
                if diagnosis:
                    diagnoses.append(diagnosis)

            # Group by severity
            critical = [d for d in diagnoses if d.get("severity") == "error"]
            warnings = [d for d in diagnoses if d.get("severity") == "warning"]
            info = [d for d in diagnoses if d.get("severity") == "info"]

            result.data = {
                "diagnoses": diagnoses,
                "summary": {
                    "critical": len(critical),
                    "warnings": len(warnings),
                    "info": len(info),
                    "total": len(diagnoses),
                },
                "fixable": [d for d in diagnoses if d.get("auto_fixable")],
            }

            result.metrics = {
                "issues_analyzed": len(all_issues),
                "diagnoses_produced": len(diagnoses),
                "auto_fixable": len([d for d in diagnoses if d.get("auto_fixable")]),
            }

            result.set_success() if not critical else result.set_mismatch()
            self.logger.info(
                f"Debug complete: {len(critical)} critical, {len(warnings)} warnings, "
                f"{len([d for d in diagnoses if d.get('auto_fixable')])} auto-fixable"
            )

        except Exception as e:
            self.logger.error(f"Debug failed: {e}", exc_info=True)
            result.set_failure(str(e))

        self.save_result(result)
        return result

    def _extract_all_issues(self, validation_result: AgentResult) -> list:
        """Extract all issues from nested validation result data."""
        issues = []
        data = validation_result.data

        for key, value in data.items():
            if isinstance(value, dict):
                issues.extend(value.get("issues", []))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        issues.extend(item.get("issues", []))

        return issues

    def _diagnose_issue(self, issue: dict) -> Optional[dict]:
        """Produce a diagnosis for a single issue."""
        issue_type = issue.get("type", "unknown")
        handler_name = self.CATEGORIES.get(issue_type, "analyze_generic")
        handler = getattr(self, handler_name, self.analyze_generic)
        return handler(issue)

    # ---- Specific Analyzers ----

    def analyze_missing_config_var(self, issue: dict) -> dict:
        """Diagnose missing config variable."""
        missing_vars = issue.get("missing_vars", [])
        sql_file = issue.get("sql_file", "")
        cfg_file = issue.get("config_file", "")

        # Try to find the value in other config files
        suggestions = []
        for cfg_path in self.list_config_files():
            content = self.read_file(cfg_path)
            for var in missing_vars:
                if f"export {var}=" in content:
                    suggestions.append(f"'{var}' found in {os.path.basename(cfg_path)}")

        return {
            "issue_type": "missing_config_var",
            "severity": issue.get("severity", "error"),
            "message": issue.get("message"),
            "root_cause": f"SQL file '{sql_file}' references config vars {missing_vars} "
                          f"that are not exported in '{cfg_file}'",
            "suggested_fix": f"Add 'export {', export '.join(f'{v}=<value>' for v in missing_vars)}' "
                            f"to {cfg_file}",
            "context": suggestions,
            "auto_fixable": True,
            "fix_action": {
                "type": "add_exports",
                "target_file": cfg_file,
                "variables": missing_vars,
            },
        }

    def analyze_wrong_environment(self, issue: dict) -> dict:
        """Diagnose wrong environment value in config."""
        return {
            "issue_type": "wrong_environment",
            "severity": "error",
            "message": issue.get("message"),
            "root_cause": f"Config file has environment='{issue.get('current')}' "
                          f"but should be '{issue.get('expected')}' based on filename",
            "suggested_fix": f"Change 'export environment={issue.get('current')}' to "
                            f"'export environment={issue.get('expected')}'",
            "auto_fixable": True,
            "fix_action": {
                "type": "replace_value",
                "field": "environment",
                "old_value": issue.get("current"),
                "new_value": issue.get("expected"),
            },
        }

    def analyze_hardcoded_reference(self, issue: dict) -> dict:
        """Diagnose hardcoded GCP project/dataset references."""
        return {
            "issue_type": "hardcoded_reference",
            "severity": "warning",
            "message": issue.get("message"),
            "root_cause": f"Hardcoded value '{issue.get('value')}' should be a config variable "
                          f"for environment portability",
            "suggested_fix": "Replace with ${config_var} and add corresponding export to deploy configs",
            "auto_fixable": True,
            "fix_action": {
                "type": "replace_hardcoded",
                "value": issue.get("value"),
            },
        }

    def analyze_hardcoded_query_label(self, issue: dict) -> dict:
        """Diagnose hardcoded values in query_label block."""
        field = issue.get("type", "").replace("hardcoded_", "")
        return {
            "issue_type": f"hardcoded_{field}",
            "severity": "warning",
            "message": issue.get("message"),
            "root_cause": f"query_label field '{field}' has hardcoded value '{issue.get('current_value')}' "
                          f"instead of config variable",
            "suggested_fix": f"Replace '{issue.get('current_value')}' with '{issue.get('suggested', '${' + field + '}')}'",
            "auto_fixable": True,
            "fix_action": {
                "type": "replace_in_query_label",
                "field": field,
                "old_value": issue.get("current_value"),
                "new_value": issue.get("suggested"),
            },
        }

    def analyze_missing_query_label(self, issue: dict) -> dict:
        """Diagnose missing query_label block."""
        return {
            "issue_type": "missing_query_label",
            "severity": "error",
            "message": issue.get("message"),
            "root_cause": "SQL file is missing the @@query_label block required for all stored procedures",
            "suggested_fix": "Add @@query_label block after variable declarations, before main logic",
            "auto_fixable": True,
            "fix_action": {
                "type": "add_query_label_block",
            },
        }

    def analyze_table_id_ordering(self, issue: dict) -> dict:
        """Diagnose incorrect table_id ordering."""
        return {
            "issue_type": "table_id_ordering",
            "severity": "warning",
            "message": issue.get("message"),
            "root_cause": "table_id entries not following convention: main table=table_id, "
                          "additional=table_id_1, table_id_2, etc.",
            "suggested_fix": "Renumber table_id entries starting from 'table_id' for the main table",
            "auto_fixable": True,
            "fix_action": {
                "type": "reorder_table_ids",
                "current": issue.get("current"),
            },
        }

    def analyze_dag_id_naming(self, issue: dict) -> dict:
        """Diagnose DAG ID naming convention issues."""
        return {
            "issue_type": "dag_id_naming",
            "severity": "error",
            "message": issue.get("message"),
            "root_cause": "dag_id must follow format: gudv_nar_onef_<dashboard_name>",
            "suggested_fix": f"Rename dag_id to follow gudv_nar_onef_<module> convention",
            "auto_fixable": True,
            "fix_action": {
                "type": "rename_dag_id",
                "module": self.module_name,
            },
        }

    def analyze_config_key_mismatch(self, issue: dict) -> dict:
        """Diagnose config key differences between environments."""
        return {
            "issue_type": "config_key_mismatch",
            "severity": "warning",
            "message": issue.get("message"),
            "root_cause": "Deploy config files have different export keys across environments. "
                          "All environments should have the same keys with only values differing.",
            "suggested_fix": "Add missing exports to the config file that's missing them",
            "auto_fixable": True,
            "fix_action": {
                "type": "sync_config_keys",
            },
        }

    def analyze_sql_syntax_error(self, issue: dict) -> dict:
        """Diagnose SQL syntax issues."""
        return {
            "issue_type": "sql_syntax_error",
            "severity": "error",
            "message": issue.get("message"),
            "root_cause": issue.get("message"),
            "suggested_fix": "Review and fix the SQL syntax error",
            "auto_fixable": False,
            "fix_action": None,
        }

    def analyze_generic(self, issue: dict) -> dict:
        """Generic diagnosis for unrecognized issue types."""
        return {
            "issue_type": issue.get("type", "unknown"),
            "severity": issue.get("severity", "info"),
            "message": issue.get("message"),
            "root_cause": issue.get("message"),
            "suggested_fix": "Manual review required",
            "auto_fixable": False,
            "fix_action": None,
        }

    # ---- LLM-Powered Deep Analysis ----

    def deep_analyze_with_llm(self, issue: dict, llm_client) -> dict:
        """
        Use LLM for complex root-cause analysis.
        Call this when simple pattern matching isn't enough.
        
        Args:
            issue: The issue to analyze
            llm_client: LLM client instance from models/llm_client.py
        """
        # Read relevant files for context
        context_files = {}
        for sql_path in self.list_sql_files():
            context_files[os.path.basename(sql_path)] = self.read_file(sql_path)
        for cfg_path in self.list_config_files():
            context_files[os.path.basename(cfg_path)] = self.read_file(cfg_path)

        prompt = self._build_debug_prompt(issue, context_files)
        response = llm_client.generate(prompt)

        return {
            "issue_type": issue.get("type"),
            "severity": issue.get("severity"),
            "message": issue.get("message"),
            "llm_analysis": response,
            "auto_fixable": False,
        }

    def _build_debug_prompt(self, issue: dict, context_files: dict) -> str:
        """Build an LLM prompt for deep analysis."""
        prompt_template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "prompts", "debug_mismatch.txt"
        )

        if os.path.exists(prompt_template_path):
            template = self.read_file(prompt_template_path)
        else:
            template = (
                "Analyze this migration issue and identify the root cause.\n\n"
                "Issue: {issue}\n\n"
                "Relevant files:\n{files}\n\n"
                "Provide: 1) Root cause 2) Suggested fix 3) Impact assessment"
            )

        files_str = ""
        for fname, content in context_files.items():
            files_str += f"\n--- {fname} ---\n{content[:2000]}\n"

        return template.format(issue=json.dumps(issue, indent=2), files=files_str)
