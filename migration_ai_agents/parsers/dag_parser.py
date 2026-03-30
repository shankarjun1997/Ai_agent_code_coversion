"""
DAG Parser — Parses Airflow DAG Python files.
Extracts: dag_id, operators, task dependencies, gcp_project overrides, execution_timeout, retries, trigger_rule.
"""
import re
import ast
from typing import Optional


class DAGParser:
    """Parse OneFiber Airflow DAG Python files."""

    def __init__(self, content: str, filename: str = ""):
        self.content = content
        self.filename = filename

    def parse(self) -> dict:
        """Full parse of a DAG Python file."""
        return {
            "filename": self.filename,
            "dag_id": self.get_dag_id(),
            "operators": self.get_operators(),
            "task_dependencies": self.get_task_dependencies(),
            "gcp_project_overrides": self.get_gcp_project_overrides(),
            "google_cloud_conn_id_overrides": self.get_google_cloud_conn_id_overrides(),
            "execution_timeout_usage": self.get_execution_timeout_usage(),
            "retries": self.get_retries(),
            "trigger_rules": self.get_trigger_rules(),
            "imports": self.get_imports(),
        }

    def get_dag_id(self) -> Optional[str]:
        """Extract dag_id from the Python source."""
        # Match dag_id = "..." or dag_id="..."
        m = re.search(r'dag_id\s*=\s*["\']([^"\']+)["\']', self.content)
        if m:
            return m.group(1)
        # Match from config dict: config['dag_id'] or config.get('dag_id')
        m = re.search(r'config\s*\[\s*["\']dag_id["\']\s*\]', self.content)
        if m:
            return "from_config"
        return None

    def get_operators(self) -> list:
        """Extract operator instantiations with task_id and type."""
        operators = []
        # Match <VarName> = <OperatorClass>(task_id="...", ...)
        pattern = re.compile(
            r'(\w+)\s*=\s*(\w+Operator|PythonOperator|BranchPythonOperator|'
            r'BashOperator|BigQueryInsertJobOperator|DummyOperator|EmptyOperator)\s*\(',
            re.MULTILINE
        )
        for m in pattern.finditer(self.content):
            var_name = m.group(1)
            op_class = m.group(2)
            # Find task_id in the block after this operator
            block_start = m.end()
            block_end = self._find_matching_paren(block_start - 1)
            block = self.content[block_start:block_end] if block_end else self.content[block_start:block_start+500]
            tid = re.search(r'task_id\s*=\s*["\']([^"\']+)["\']', block)
            operators.append({
                "variable": var_name,
                "operator_class": op_class,
                "task_id": tid.group(1) if tid else None,
            })
        return operators

    def get_task_dependencies(self) -> list:
        """Extract >> / << task dependency chains."""
        deps = []
        for line in self.content.splitlines():
            line = line.strip()
            if ">>" in line or "<<" in line:
                deps.append(line)
        return deps

    def get_gcp_project_overrides(self) -> list:
        """Find any hardcoded gcp_project or project references."""
        overrides = []
        patterns = [
            (r'gcp_project\s*=\s*["\']([^"\']+)["\']', "gcp_project"),
            (r'project\s*=\s*["\']([^"\']+)["\']', "project"),
        ]
        for pat, label in patterns:
            for m in re.finditer(pat, self.content):
                overrides.append({
                    "type": label,
                    "value": m.group(1),
                    "line": self.content[:m.start()].count('\n') + 1,
                })
        return overrides

    def get_google_cloud_conn_id_overrides(self) -> list:
        """Find google_cloud_conn_id overrides that should come from base_config."""
        overrides = []
        for m in re.finditer(r'google_cloud_conn_id\s*=\s*["\']([^"\']+)["\']', self.content):
            overrides.append({
                "value": m.group(1),
                "line": self.content[:m.start()].count('\n') + 1,
            })
        return overrides

    def get_execution_timeout_usage(self) -> list:
        """Find execution_timeout settings."""
        usages = []
        for m in re.finditer(r'execution_timeout\s*=\s*(.+)', self.content):
            usages.append({
                "value": m.group(1).strip().rstrip(','),
                "line": self.content[:m.start()].count('\n') + 1,
            })
        return usages

    def get_retries(self) -> list:
        """Find retries settings."""
        results = []
        for m in re.finditer(r'retries\s*=\s*(\d+)', self.content):
            results.append({
                "value": int(m.group(1)),
                "line": self.content[:m.start()].count('\n') + 1,
            })
        return results

    def get_trigger_rules(self) -> list:
        """Find trigger_rule assignments."""
        rules = []
        for m in re.finditer(r'trigger_rule\s*=\s*["\']?([^"\')\s,]+)["\']?', self.content):
            rules.append({
                "value": m.group(1),
                "line": self.content[:m.start()].count('\n') + 1,
            })
        return rules

    def get_imports(self) -> list:
        """Extract all import statements."""
        imports = []
        for line in self.content.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
        return imports

    def validate_dag_id(self, expected_prefix: str = "gudv_nar_onef_") -> dict:
        """
        Validate dag_id naming convention.
        
        Args:
            expected_prefix: Expected prefix for dag_id (default: gudv_nar_onef_)
            
        Returns:
            dict with is_valid, dag_id, issues
        """
        dag_id = self.get_dag_id()
        issues = []

        if dag_id is None:
            issues.append("No dag_id found in file")
        elif dag_id == "from_config":
            pass  # Cannot statically validate
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

    def _find_matching_paren(self, start: int) -> Optional[int]:
        """Find the closing parenthesis matching the opening one at start."""
        if start >= len(self.content) or self.content[start] != '(':
            return None
        depth = 0
        for i in range(start, len(self.content)):
            if self.content[i] == '(':
                depth += 1
            elif self.content[i] == ')':
                depth -= 1
                if depth == 0:
                    return i
        return None
