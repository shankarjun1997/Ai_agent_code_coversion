"""
YAML Parser — Parses Airflow DAG YAML config files (config.yml / base_config.yaml).
Extracts: dag_id, stored_procs, task configs, schedule_interval.
"""
import yaml
from typing import Optional


class YAMLConfigParser:
    """Parse OneFiber Airflow YAML config files."""

    def __init__(self, content: str, filename: str = ""):
        self.content = content
        self.filename = filename
        self._data = None

    @property
    def data(self) -> dict:
        if self._data is None:
            self._data = yaml.safe_load(self.content) or {}
        return self._data

    def parse(self) -> dict:
        """Full parse of a YAML config file."""
        return {
            "filename": self.filename,
            "dag_id": self.get_dag_id(),
            "schedule_interval": self.get_schedule_interval(),
            "stored_procs": self.get_stored_procs(),
            "tasks": self.get_tasks(),
            "gcp_project_overrides": self.get_gcp_project_overrides(),
            "google_cloud_conn_id_overrides": self.get_google_cloud_conn_id_overrides(),
        }

    def get_dag_id(self) -> Optional[str]:
        """Get dag_id from YAML config."""
        return self.data.get("dag_id")

    def get_schedule_interval(self) -> Optional[str]:
        """Get schedule_interval."""
        return self.data.get("schedule_interval")

    def get_stored_procs(self) -> list:
        """Extract stored procedure names from task definitions."""
        procs = []
        tasks = self.data.get("tasks", [])
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict):
                    sp = task.get("stored_proc") or task.get("stored_procedure")
                    if sp:
                        procs.append(sp)
        elif isinstance(tasks, dict):
            for name, cfg in tasks.items():
                if isinstance(cfg, dict):
                    sp = cfg.get("stored_proc") or cfg.get("stored_procedure")
                    if sp:
                        procs.append(sp)
        return procs

    def get_tasks(self) -> list:
        """Get all task definitions."""
        tasks = self.data.get("tasks", [])
        result = []
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict):
                    result.append(task)
        elif isinstance(tasks, dict):
            for name, cfg in tasks.items():
                if isinstance(cfg, dict):
                    cfg["_task_name"] = name
                    result.append(cfg)
        return result

    def get_gcp_project_overrides(self) -> list:
        """Find gcp_project overrides that should NOT be in YAML (should come from base_config)."""
        overrides = []
        self._walk(self.data, "gcp_project", overrides)
        return overrides

    def get_google_cloud_conn_id_overrides(self) -> list:
        """Find google_cloud_conn_id overrides that should NOT be in YAML."""
        overrides = []
        self._walk(self.data, "google_cloud_conn_id", overrides)
        return overrides

    def validate_dag_id(self, expected_prefix: str = "gudv_nar_onef_") -> dict:
        """Validate dag_id naming convention."""
        dag_id = self.get_dag_id()
        issues = []
        if dag_id is None:
            issues.append("No dag_id found in YAML config")
        else:
            if not dag_id.startswith(expected_prefix):
                issues.append(f"dag_id '{dag_id}' missing expected prefix '{expected_prefix}'")
            if "_nar_" not in dag_id:
                issues.append(f"dag_id '{dag_id}' missing required '_nar_' segment")
        return {
            "is_valid": len(issues) == 0,
            "dag_id": dag_id,
            "issues": issues,
        }

    def validate_stored_procs_against_sql(self, sql_filenames: list) -> dict:
        """
        Check that stored procs in YAML match actual SQL files.
        
        Args:
            sql_filenames: list of SQL file basenames (without .sql extension)
            
        Returns:
            dict with matched, missing_sql, extra_sql
        """
        procs = set(self.get_stored_procs())
        sql_names = set(sql_filenames)

        return {
            "matched": sorted(procs & sql_names),
            "in_yaml_not_in_sql": sorted(procs - sql_names),
            "in_sql_not_in_yaml": sorted(sql_names - procs),
        }

    def _walk(self, obj, key: str, results: list, path: str = ""):
        """Walk the YAML tree looking for a specific key."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                current_path = f"{path}.{k}" if path else k
                if k == key:
                    results.append({"path": current_path, "value": v})
                self._walk(v, key, results, current_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._walk(item, key, results, f"{path}[{i}]")
