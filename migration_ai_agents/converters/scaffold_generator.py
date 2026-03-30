"""
Scaffold Generator — Creates the full production folder structure for a new module.

Generates:
  <module_name>/
  ├── pipelines/
  │   └── src/
  │       └── main/
  │           ├── sql/              ← Converted BQ stored procedures
  │           ├── config/           ← deployprd.cfg, deployuat.cfg, deploydev.cfg
  │           ├── scripts/          ← run_bq_ddl_deploy.sh, run_copy_to_gcs.sh
  │           ├── bq_ddl/           ← DDL scripts (CREATE TABLE etc.)
  │           └── ddl_script/       ← Environment-specific DDL runners
  ├── dag/
  │   ├── python/                   ← Airflow DAG Python files + DO_utils.py
  │   ├── config/                   ← base_config.yaml + sp_*.yml
  │   ├── DPF/                      ← DPF dag creation configs
  │   └── uat/                      ← UAT-specific dag overrides
  │       ├── python/
  │       └── config/
  └── assembly/
      └── packages/
  <module_name>.conf                 ← Jenkins packaging config (at repo root)

This follows the EXACT structure used by the Jenkins pipeline (Jenkinsfile)
and the composer_utils deployment tooling.
"""
import os
import shutil
import logging

logger = logging.getLogger(__name__)


class ScaffoldGenerator:
    """Create production-ready folder structure for a new OneFiber module."""

    def __init__(self, repo_root: str):
        """
        Args:
            repo_root: Absolute path to the onefiber repo root
        """
        self.repo_root = repo_root

    def generate(self, module_name: str, conversion_result: dict, do_utils_source: str = None) -> dict:
        """
        Write all converted files into the proper folder structure.

        Args:
            module_name: Module name (e.g. 'new_dashboard')
            conversion_result: Output from OracleToBQConverter.convert()
            do_utils_source: Optional path to copy DO_utils.py from (e.g. from ned_dashboard)

        Returns:
            dict with created files list and status
        """
        module_dir = os.path.join(self.repo_root, module_name)
        created_files = []

        proc_name = conversion_result["report"]["procedure_name"]

        # ── 1. Create directory structure ──
        dirs = [
            os.path.join(module_dir, "pipelines", "src", "main", "sql"),
            os.path.join(module_dir, "pipelines", "src", "main", "config"),
            os.path.join(module_dir, "pipelines", "src", "main", "scripts"),
            os.path.join(module_dir, "pipelines", "src", "main", "bq_ddl"),
            os.path.join(module_dir, "pipelines", "src", "main", "ddl_script"),
            os.path.join(module_dir, "dag", "python"),
            os.path.join(module_dir, "dag", "config"),
            os.path.join(module_dir, "dag", "DPF"),
            os.path.join(module_dir, "dag", "uat", "python"),
            os.path.join(module_dir, "dag", "uat", "config"),
            os.path.join(module_dir, "assembly", "packages"),
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)
            logger.debug(f"Created directory: {d}")

        # ── 2. Write converted BQ SQL ──
        sql_path = os.path.join(module_dir, "pipelines", "src", "main", "sql", f"{proc_name}.sql")
        self._write(sql_path, conversion_result["bq_sql"])
        created_files.append(sql_path)

        # ── 3. Write deploy configs ──
        for filename, content in conversion_result["deploy_configs"].items():
            cfg_path = os.path.join(module_dir, "pipelines", "src", "main", "config", filename)
            self._write(cfg_path, content)
            created_files.append(cfg_path)

        # ── 4. Write deploy scripts ──
        for filename, content in conversion_result["deploy_scripts"].items():
            script_path = os.path.join(module_dir, "pipelines", "src", "main", "scripts", filename)
            self._write(script_path, content)
            # Make executable
            os.chmod(script_path, 0o755)
            created_files.append(script_path)

        # ── 5. Write DAG Python file ──
        dag_py_path = os.path.join(module_dir, "dag", "python", f"{proc_name}.py")
        self._write(dag_py_path, conversion_result["dag_python"])
        created_files.append(dag_py_path)

        # Also copy to UAT
        dag_uat_py_path = os.path.join(module_dir, "dag", "uat", "python", f"{proc_name}.py")
        self._write(dag_uat_py_path, conversion_result["dag_python"])
        created_files.append(dag_uat_py_path)

        # ── 6. Copy DO_utils.py ──
        do_utils_dst = os.path.join(module_dir, "dag", "python", "DO_utils.py")
        if do_utils_source and os.path.exists(do_utils_source):
            shutil.copy2(do_utils_source, do_utils_dst)
            created_files.append(do_utils_dst)
            # Also to UAT
            do_utils_uat = os.path.join(module_dir, "dag", "uat", "python", "DO_utils.py")
            shutil.copy2(do_utils_source, do_utils_uat)
            created_files.append(do_utils_uat)
        else:
            # Try to find DO_utils.py from another module
            for candidate in ("ned_dashboard", "ntp_summary", "onef_bau_dashboard"):
                src = os.path.join(self.repo_root, candidate, "dag", "python", "DO_utils.py")
                if os.path.exists(src):
                    shutil.copy2(src, do_utils_dst)
                    created_files.append(do_utils_dst)
                    do_utils_uat = os.path.join(module_dir, "dag", "uat", "python", "DO_utils.py")
                    shutil.copy2(src, do_utils_uat)
                    created_files.append(do_utils_uat)
                    logger.info(f"Copied DO_utils.py from {candidate}")
                    break

        # ── 7. Write DAG YAML config ──
        dag_yml_path = os.path.join(module_dir, "dag", "config", f"{proc_name}.yml")
        self._write(dag_yml_path, conversion_result["dag_yaml"])
        created_files.append(dag_yml_path)

        # Also to UAT
        dag_uat_yml_path = os.path.join(module_dir, "dag", "uat", "config", f"{proc_name}.yml")
        self._write(dag_uat_yml_path, conversion_result["dag_yaml"])
        created_files.append(dag_uat_yml_path)

        # ── 8. Write base_config.yaml ──
        base_cfg_path = os.path.join(module_dir, "dag", "config", "base_config.yaml")
        self._write(base_cfg_path, conversion_result["base_config_yaml"])
        created_files.append(base_cfg_path)

        base_cfg_uat_path = os.path.join(module_dir, "dag", "uat", "config", "base_config.yaml")
        self._write(base_cfg_uat_path, conversion_result["base_config_yaml"])
        created_files.append(base_cfg_uat_path)

        # ── 9. Write .conf file at repo root ──
        conf_path = os.path.join(self.repo_root, f"{module_name}.conf")
        self._write(conf_path, conversion_result["conf_file"])
        created_files.append(conf_path)

        # ── 10. Write conversion report ──
        report_path = os.path.join(module_dir, "CONVERSION_REPORT.md")
        self._write(report_path, self._format_report_md(conversion_result["report"]))
        created_files.append(report_path)

        logger.info(f"Scaffold complete: {len(created_files)} files created for '{module_name}'")

        return {
            "module_name": module_name,
            "module_dir": module_dir,
            "files_created": created_files,
            "total_files": len(created_files),
            "report": conversion_result["report"],
        }

    def _write(self, filepath: str, content: str):
        """Write content to file, creating directories as needed."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        logger.debug(f"Wrote: {filepath}")

    def _format_report_md(self, report: dict) -> str:
        """Format the conversion report as Markdown."""
        lines = [
            f"# Conversion Report: {report['module_name']}",
            "",
            f"**Procedure:** `{report['procedure_name']}`",
            f"**Complexity:** {report['complexity'].get('difficulty', 'N/A')} "
            f"(score: {report['complexity'].get('score', 'N/A')})",
            f"**BQ SQL Lines:** {report['bq_sql_lines']}",
            "",
            "## Conversion Summary",
            f"- Oracle functions converted: {report['oracle_functions_converted']}",
            f"- DML operations: {report['total_dml_operations']}",
            f"- Tables referenced: {report['total_tables_referenced']}",
            f"- Has cursors: {'Yes' if report['has_cursors'] else 'No'}",
            f"- Has dynamic SQL: {'Yes' if report['has_dynamic_sql'] else 'No'}",
            f"- Has sequences: {'Yes' if report['has_sequences'] else 'No'}",
            f"- Has Oracle (+) joins: {'Yes' if report['has_oracle_joins'] else 'No'}",
            "",
            "## Files Generated",
        ]
        for f in report["files_generated"]:
            lines.append(f"- `{f}`")

        if report.get("functions_needing_manual_review"):
            lines.append("")
            lines.append("## Functions Needing Manual Review")
            for f in report["functions_needing_manual_review"]:
                lines.append(f"- `{f}`")

        lines.append("")
        lines.append("## Review Checklist")
        for item in report.get("review_checklist", []):
            lines.append(f"- {item}")

        lines.append("")
        lines.append("---")
        lines.append("*Generated by OneFiber Migration AI Agent Framework*")
        return "\n".join(lines)
