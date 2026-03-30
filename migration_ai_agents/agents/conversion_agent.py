"""
Agent 1 — Conversion Agent
===========================
Converts SQL, DAG, and Config files between environments/formats.

Capabilities:
  - Hardcoded values → ${config_var} substitution
  - query_label standardization
  - table_id ordering (main=table_id, additional=table_id_1,2...)
  - dag_id naming convention enforcement
  - Environment-specific config generation (prod/uat/dev)
  - SQL dialect conversion (if needed)
"""
import os
import re
from typing import Optional

from . import BaseAgent, AgentResult


class ConversionAgent(BaseAgent):
    """
    Agent 1: Converts migration assets to target format.
    
    Handles:
      - SQL stored procedures: config var substitution, query_label standardization
      - Deploy configs: environment-aware generation (deployprd/uat/dev.cfg)
      - DAG Python files: dag_id naming, config structure
      - DAG YAML configs: project/dataset mapping
    """

    AGENT_NAME = "conversion_agent"

    def execute(self, input_data: AgentResult = None) -> AgentResult:
        result = AgentResult(self.AGENT_NAME, self.module_name)
        self.logger.info(f"=== Conversion Agent: {self.module_name} ===")

        try:
            sql_results = self._convert_sql_files()
            config_results = self._convert_config_files()
            dag_results = self._convert_dag_files()
            yaml_results = self._convert_yaml_configs()

            result.data = {
                "sql": sql_results,
                "config": config_results,
                "dag": dag_results,
                "yaml": yaml_results,
            }
            result.metrics = {
                "sql_files_processed": len(sql_results),
                "config_files_processed": len(config_results),
                "dag_files_processed": len(dag_results),
                "yaml_files_processed": len(yaml_results),
                "total_issues_found": sum(
                    len(r.get("issues", [])) for r in sql_results + config_results
                ),
            }
            result.set_success()
            self.logger.info(f"Conversion complete: {result.metrics}")
        except Exception as e:
            self.logger.error(f"Conversion failed: {e}", exc_info=True)
            result.set_failure(str(e))

        self.save_result(result)
        return result

    # ---- SQL Conversion ----

    def _convert_sql_files(self) -> list:
        """Analyze and convert all SQL files in the module."""
        results = []
        for sql_path in self.list_sql_files():
            content = self.read_file(sql_path)
            filename = os.path.basename(sql_path)
            issues = []

            # 1. Check query_label block
            ql_issues = self._check_query_label(content, filename)
            issues.extend(ql_issues)

            # 2. Check for hardcoded project/dataset IDs
            hc_issues = self._check_hardcoded_references(content, filename)
            issues.extend(hc_issues)

            # 3. Check table_id ordering
            tid_issues = self._check_table_id_ordering(content, filename)
            issues.extend(tid_issues)

            results.append({
                "file": filename,
                "path": sql_path,
                "issues": issues,
                "has_query_label": "@@query_label" in content,
            })

        return results

    def _check_query_label(self, content: str, filename: str) -> list:
        """Check query_label block for standardization issues."""
        issues = []
        if "@@query_label" not in content:
            issues.append({
                "type": "missing_query_label",
                "severity": "error",
                "message": f"{filename}: Missing @@query_label block",
            })
            return issues

        # Required fields in query_label
        required_fields = {
            "etl_type": r"etl_type\s*:\s*(\$\{[^}]+\}|[^\s,}]+)",
            "application": r"application\s*:\s*(\$\{[^}]+\}|[^\s,}]+)",
            "environment": r"environment\s*:\s*(\$\{[^}]+\}|[^\s,}]+)",
            "vsad": r"vsad\s*:\s*(\$\{[^}]+\}|[^\s,}]+)",
            "dataset_id": r"dataset_id\s*:\s*(\$\{[^}]+\}|[^\s,}]+)",
            "table_id": r"table_id\s*:\s*(\$\{[^}]+\}|[^\s,}]+)",
        }

        for field, pattern in required_fields.items():
            m = re.search(pattern, content)
            if not m:
                issues.append({
                    "type": f"missing_{field}",
                    "severity": "error",
                    "message": f"{filename}: Missing '{field}' in query_label",
                })
            else:
                val = m.group(1)
                # Check if it should be a config var but isn't
                if not val.startswith("${") and field in ("etl_type", "environment", "vsad", "dataset_id"):
                    issues.append({
                        "type": f"hardcoded_{field}",
                        "severity": "warning",
                        "message": f"{filename}: '{field}' is hardcoded as '{val}', should use ${{config_var}}",
                        "current_value": val,
                        "suggested": f"${{{field}}}",
                    })

        return issues

    def _check_hardcoded_references(self, content: str, filename: str) -> list:
        """Detect hardcoded GCP project IDs or dataset names."""
        issues = []
        # Common hardcoded patterns
        gcp_project_pattern = r'vz-it-(?:pr|np)-\w+-\w+-\d+'
        for m in re.finditer(gcp_project_pattern, content):
            # Skip if inside a comment
            line_start = content.rfind('\n', 0, m.start()) + 1
            line = content[line_start:content.find('\n', m.end())]
            if line.strip().startswith('--') or line.strip().startswith('#'):
                continue
            issues.append({
                "type": "hardcoded_project_id",
                "severity": "warning",
                "message": f"{filename}: Hardcoded GCP project ID '{m.group()}'",
                "value": m.group(),
                "position": m.start(),
            })

        return issues

    def _check_table_id_ordering(self, content: str, filename: str) -> list:
        """Check that table_id ordering follows convention."""
        issues = []
        if "@@query_label" not in content:
            return issues

        # Find all table_id entries
        table_ids = re.findall(r'(table_id(?:_\d+)?)\s*:', content)
        if not table_ids:
            return issues

        # First should be 'table_id' (no number)
        if table_ids[0] != "table_id":
            issues.append({
                "type": "table_id_ordering",
                "severity": "warning",
                "message": f"{filename}: First table should be 'table_id', not '{table_ids[0]}'",
                "current": table_ids,
            })

        # Check sequential numbering
        expected = ["table_id"] + [f"table_id_{i}" for i in range(1, len(table_ids))]
        if table_ids != expected[:len(table_ids)]:
            issues.append({
                "type": "table_id_sequence",
                "severity": "info",
                "message": f"{filename}: table_id sequence {table_ids} should be {expected[:len(table_ids)]}",
            })

        return issues

    # ---- Config Conversion ----

    def _convert_config_files(self) -> list:
        """Analyze deploy config files for each environment."""
        results = []
        for cfg_path in self.list_config_files():
            content = self.read_file(cfg_path)
            filename = os.path.basename(cfg_path)
            issues = []

            # Determine environment from filename
            if "prd" in filename:
                expected_env = "prod"
            elif "uat" in filename:
                expected_env = "uat"
            elif "dev" in filename:
                expected_env = "dev"
            else:
                expected_env = None

            # Parse exports
            exports = self._parse_cfg_exports(content)

            # Check required metadata exports
            required_metadata = ["etl_type", "application", "environment", "vsad"]
            for field in required_metadata:
                if field not in exports:
                    issues.append({
                        "type": f"missing_export_{field}",
                        "severity": "error",
                        "message": f"{filename}: Missing 'export {field}=...'",
                    })
                elif field == "environment" and expected_env and exports[field] != expected_env:
                    issues.append({
                        "type": "wrong_environment",
                        "severity": "error",
                        "message": f"{filename}: environment='{exports[field]}' should be '{expected_env}'",
                        "current": exports[field],
                        "expected": expected_env,
                    })

            results.append({
                "file": filename,
                "path": cfg_path,
                "environment": expected_env,
                "exports": exports,
                "issues": issues,
            })

        return results

    def _parse_cfg_exports(self, content: str) -> dict:
        """Parse export statements from a .cfg file."""
        exports = {}
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("export ") and "=" in line:
                # export key=value
                kv = line[7:]  # strip 'export '
                key, _, value = kv.partition("=")
                exports[key.strip()] = value.strip()
        return exports

    # ---- DAG Conversion ----

    def _convert_dag_files(self) -> list:
        """Analyze DAG Python files."""
        results = []
        for dag_path in self.list_dag_python_files():
            content = self.read_file(dag_path)
            filename = os.path.basename(dag_path)
            issues = []

            # Check for common DAG issues
            if "execution_timeout" in content:
                issues.append({
                    "type": "has_execution_timeout",
                    "severity": "warning",
                    "message": f"{filename}: Has execution_timeout (should not be set unless specifically needed)",
                })

            # Check retries
            retries_match = re.search(r"'retries'\s*:\s*(\d+)", content)
            if retries_match and int(retries_match.group(1)) != 0:
                issues.append({
                    "type": "non_zero_retries",
                    "severity": "warning",
                    "message": f"{filename}: retries={retries_match.group(1)}, should be 0",
                })

            # Check trigger_rule on end task
            if "trigger_rule" in content:
                tr_match = re.search(r"trigger_rule\s*=\s*['\"](\w+)['\"]", content)
                if tr_match and tr_match.group(1) != "all_success":
                    issues.append({
                        "type": "wrong_trigger_rule",
                        "severity": "warning",
                        "message": f"{filename}: trigger_rule='{tr_match.group(1)}', should be 'all_success' on end task",
                    })

            # Check for gcp_project or google_cloud_conn_id override
            for field in ["gcp_project", "google_cloud_conn_id"]:
                if re.search(rf"['\"]?{field}['\"]?\s*[=:]\s*['\"]", content):
                    issues.append({
                        "type": f"overrides_{field}",
                        "severity": "warning",
                        "message": f"{filename}: Overrides '{field}' — should come from base_config",
                    })

            results.append({
                "file": filename,
                "path": dag_path,
                "issues": issues,
            })

        return results

    # ---- YAML Config Conversion ----

    def _convert_yaml_configs(self) -> list:
        """Analyze DAG YAML config files."""
        results = []
        for yml_path in self.list_dag_config_files():
            content = self.read_file(yml_path)
            filename = os.path.basename(yml_path)
            issues = []

            try:
                import yaml
                data = yaml.safe_load(content)
                if isinstance(data, dict):
                    for project_id, entries in data.items():
                        if isinstance(entries, list):
                            for entry in entries:
                                dag_id = entry.get("dag_id", "")
                                # Check dag_id naming convention
                                if not dag_id.startswith("gudv_nar_onef_"):
                                    issues.append({
                                        "type": "dag_id_naming",
                                        "severity": "error",
                                        "message": f"{filename}: dag_id '{dag_id}' should start with 'gudv_nar_onef_'",
                                    })
            except Exception as e:
                issues.append({
                    "type": "yaml_parse_error",
                    "severity": "error",
                    "message": f"{filename}: YAML parse error: {e}",
                })

            results.append({
                "file": filename,
                "path": yml_path,
                "issues": issues,
            })

        return results
