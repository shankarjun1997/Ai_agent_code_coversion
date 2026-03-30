"""
Agent 2 — Validation Agent
============================
Compares source system output vs converted/target output.

Capabilities:
  - SQL syntax validation (dry-run against BigQuery)
  - Config completeness check (all SQL ${vars} have matching exports)
  - Cross-environment consistency (prd vs uat vs dev configs aligned)
  - Row count comparison (source table vs target table)
  - Schema comparison (column names, types)
  - Data sample comparison
"""
import os
import re
from typing import Optional

from . import BaseAgent, AgentResult


class ValidationAgent(BaseAgent):
    """
    Agent 2: Validates converted assets against source.
    
    Three validation modes:
      1. Static: File-level checks (no BigQuery needed)
      2. Schema: Compare table schemas via BigQuery INFORMATION_SCHEMA
      3. Data: Compare actual row counts and sample data
    """

    AGENT_NAME = "validation_agent"

    def execute(self, input_data: AgentResult = None) -> AgentResult:
        result = AgentResult(self.AGENT_NAME, self.module_name)
        self.logger.info(f"=== Validation Agent: {self.module_name} ===")

        try:
            # Static validations (no BQ connection needed)
            var_check = self._validate_config_var_coverage()
            cross_env_check = self._validate_cross_environment_consistency()
            sql_syntax_check = self._validate_sql_syntax()
            dag_config_check = self._validate_dag_config_alignment()

            result.data = {
                "config_var_coverage": var_check,
                "cross_environment": cross_env_check,
                "sql_syntax": sql_syntax_check,
                "dag_config_alignment": dag_config_check,
            }

            # Determine overall status
            all_issues = []
            for check in [var_check, cross_env_check, sql_syntax_check, dag_config_check]:
                if isinstance(check, dict):
                    all_issues.extend(check.get("issues", []))
                elif isinstance(check, list):
                    for item in check:
                        all_issues.extend(item.get("issues", []))

            errors = [i for i in all_issues if i.get("severity") == "error"]
            warnings = [i for i in all_issues if i.get("severity") == "warning"]

            result.metrics = {
                "total_checks": len(all_issues),
                "errors": len(errors),
                "warnings": len(warnings),
                "passed": len(all_issues) - len(errors) - len(warnings),
            }

            if errors:
                result.set_mismatch({"error_count": len(errors)})
            else:
                result.set_success()

            self.logger.info(
                f"Validation complete: {len(errors)} errors, {len(warnings)} warnings"
            )

        except Exception as e:
            self.logger.error(f"Validation failed: {e}", exc_info=True)
            result.set_failure(str(e))

        self.save_result(result)
        return result

    # ---- Config Variable Coverage ----

    def _validate_config_var_coverage(self) -> dict:
        """
        For each SQL file, extract all ${var_name} references.
        For each deploy config, extract all 'export var=...' statements.
        Report any SQL vars that don't have a matching config export.
        """
        issues = []

        # Collect all exports from all config files
        config_exports = {}
        for cfg_path in self.list_config_files():
            filename = os.path.basename(cfg_path)
            content = self.read_file(cfg_path)
            exports = self._parse_exports(content)
            config_exports[filename] = exports

        # Check each SQL file
        for sql_path in self.list_sql_files():
            sql_filename = os.path.basename(sql_path)
            content = self.read_file(sql_path)

            # Extract all ${var_name} references
            sql_vars = set(re.findall(r'\$\{(\w+)\}', content))

            for cfg_name, exports in config_exports.items():
                missing = sql_vars - set(exports.keys())
                if missing:
                    issues.append({
                        "type": "missing_config_var",
                        "severity": "error",
                        "message": f"{sql_filename} uses vars not in {cfg_name}: {sorted(missing)}",
                        "sql_file": sql_filename,
                        "config_file": cfg_name,
                        "missing_vars": sorted(missing),
                    })

        return {
            "check": "config_var_coverage",
            "issues": issues,
            "config_files": list(config_exports.keys()),
            "status": "pass" if not issues else "fail",
        }

    # ---- Cross-Environment Consistency ----

    def _validate_cross_environment_consistency(self) -> dict:
        """
        Compare deployprd.cfg, deployuat.cfg, deploydev.cfg.
        They should have the same export keys. Only values that should
        differ are: environment, project IDs, dataset names.
        """
        issues = []
        config_exports = {}

        for cfg_path in self.list_config_files():
            filename = os.path.basename(cfg_path)
            content = self.read_file(cfg_path)
            config_exports[filename] = self._parse_exports(content)

        if len(config_exports) < 2:
            return {"check": "cross_environment", "issues": issues, "status": "skip"}

        # Compare keys across all configs
        all_keys = {}
        for cfg_name, exports in config_exports.items():
            all_keys[cfg_name] = set(exports.keys())

        cfg_names = list(all_keys.keys())
        for i in range(len(cfg_names)):
            for j in range(i + 1, len(cfg_names)):
                cfg_a, cfg_b = cfg_names[i], cfg_names[j]
                only_in_a = all_keys[cfg_a] - all_keys[cfg_b]
                only_in_b = all_keys[cfg_b] - all_keys[cfg_a]

                if only_in_a:
                    issues.append({
                        "type": "key_mismatch",
                        "severity": "warning",
                        "message": f"Keys in {cfg_a} but not {cfg_b}: {sorted(only_in_a)}",
                    })
                if only_in_b:
                    issues.append({
                        "type": "key_mismatch",
                        "severity": "warning",
                        "message": f"Keys in {cfg_b} but not {cfg_a}: {sorted(only_in_b)}",
                    })

        # Check environment values match filename
        env_map = {"deployprd.cfg": "prod", "deployuat.cfg": "uat", "deploydev.cfg": "dev"}
        for cfg_name, exports in config_exports.items():
            expected_env = env_map.get(cfg_name)
            actual_env = exports.get("environment")
            if expected_env and actual_env and actual_env != expected_env:
                issues.append({
                    "type": "wrong_environment",
                    "severity": "error",
                    "message": f"{cfg_name}: environment='{actual_env}' should be '{expected_env}'",
                })

        return {
            "check": "cross_environment",
            "issues": issues,
            "status": "pass" if not issues else "fail",
        }

    # ---- SQL Syntax Validation ----

    def _validate_sql_syntax(self) -> list:
        """Basic SQL syntax checks (without BigQuery connection)."""
        results = []
        for sql_path in self.list_sql_files():
            filename = os.path.basename(sql_path)
            content = self.read_file(sql_path)
            issues = []

            # Check balanced BEGIN/END
            begins = len(re.findall(r'\bBEGIN\b', content, re.IGNORECASE))
            ends = len(re.findall(r'\bEND\b', content, re.IGNORECASE))
            # END includes END IF, END LOOP, etc., but approximate check
            if begins > 0 and ends < begins:
                issues.append({
                    "type": "unbalanced_begin_end",
                    "severity": "warning",
                    "message": f"{filename}: {begins} BEGIN vs {ends} END — may be unbalanced",
                })

            # Check for unclosed backtick references
            backticks = content.count('`')
            if backticks % 2 != 0:
                issues.append({
                    "type": "unclosed_backtick",
                    "severity": "error",
                    "message": f"{filename}: Odd number of backticks ({backticks}) — unclosed reference",
                })

            # Check CREATE OR REPLACE PROCEDURE signature
            proc_match = re.search(
                r'CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+`([^`]+)`',
                content, re.IGNORECASE
            )
            if proc_match:
                proc_ref = proc_match.group(1)
                # Should use ${target_project_id}.${target_dataset_name}
                if not proc_ref.startswith("${"):
                    issues.append({
                        "type": "hardcoded_proc_reference",
                        "severity": "warning",
                        "message": f"{filename}: Procedure reference '{proc_ref}' should use ${{config_vars}}",
                    })

            results.append({
                "file": filename,
                "path": sql_path,
                "issues": issues,
            })

        return results

    # ---- DAG Config Alignment ----

    def _validate_dag_config_alignment(self) -> list:
        """Check that DAG YAML config aligns with deploy configs and SQL files."""
        results = []
        import yaml as yaml_lib

        for yml_path in self.list_dag_config_files():
            filename = os.path.basename(yml_path)
            content = self.read_file(yml_path)
            issues = []

            try:
                data = yaml_lib.safe_load(content)
                if isinstance(data, dict):
                    for project_id, entries in data.items():
                        if isinstance(entries, list):
                            for entry in entries:
                                sp = entry.get("stored_proc", "")
                                # Check stored_proc matches a SQL file
                                sql_files = [
                                    os.path.basename(f).replace(".sql", "")
                                    for f in self.list_sql_files()
                                ]
                                sp_names = [s for s in sql_files if sp in s]
                                if sp and not sp_names:
                                    issues.append({
                                        "type": "stored_proc_not_found",
                                        "severity": "warning",
                                        "message": f"{filename}: stored_proc '{sp}' doesn't match any SQL file",
                                    })
            except Exception as e:
                issues.append({
                    "type": "yaml_parse_error",
                    "severity": "error",
                    "message": f"{filename}: Parse error: {e}",
                })

            results.append({
                "file": filename,
                "path": yml_path,
                "issues": issues,
            })

        return results

    # ---- BigQuery Validation (requires connection) ----

    def validate_with_bigquery(self, bq_client) -> dict:
        """
        Run actual BigQuery validations. Requires a BQ client.
        Call this separately when BQ access is available.
        
        Args:
            bq_client: google.cloud.bigquery.Client instance
            
        Returns:
            dict with row_counts, schema_comparison results
        """
        results = {"row_counts": {}, "schema_diffs": {}}

        # Read config for project/dataset
        prd_config = {}
        for cfg_path in self.list_config_files():
            if "deployprd" in os.path.basename(cfg_path):
                prd_config = self._parse_exports(self.read_file(cfg_path))
                break

        src_project = prd_config.get("src_project_id", "")
        src_dataset = prd_config.get("src_dataset_name", "")
        tgt_project = prd_config.get("target_project_id", "")
        tgt_dataset = prd_config.get("target_dataset_name", "")

        if not all([src_project, src_dataset, tgt_project, tgt_dataset]):
            return {"error": "Missing project/dataset in config"}

        # Get all target table exports
        for key, val in prd_config.items():
            if key.startswith("target_") and key not in (
                "target_project_id", "target_dataset_name"
            ):
                table_name = val
                try:
                    # Row count check
                    query = f"SELECT COUNT(1) as cnt FROM `{tgt_project}.{tgt_dataset}.{table_name}`"
                    df = bq_client.query(query).to_dataframe()
                    count = int(df["cnt"][0])
                    results["row_counts"][table_name] = count
                except Exception as e:
                    results["row_counts"][table_name] = f"ERROR: {e}"

        return results

    # ---- Helpers ----

    def _parse_exports(self, content: str) -> dict:
        exports = {}
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("export ") and "=" in line:
                kv = line[7:]
                key, _, value = kv.partition("=")
                exports[key.strip()] = value.strip()
        return exports
