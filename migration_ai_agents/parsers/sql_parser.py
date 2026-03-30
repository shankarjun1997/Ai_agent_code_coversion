"""
SQL Parser — Parses BigQuery stored procedure SQL files.
Extracts: procedure name, query_label fields, table references,
          variable declarations, DML operations.
"""
import re
from typing import Optional


class SQLParser:
    """Parse BigQuery SQL stored procedures."""

    def __init__(self, content: str, filename: str = ""):
        self.content = content
        self.filename = filename

    def parse(self) -> dict:
        """Full parse of the SQL file."""
        return {
            "filename": self.filename,
            "procedure_name": self.get_procedure_name(),
            "query_label": self.get_query_label_fields(),
            "variables": self.get_variable_declarations(),
            "table_references": self.get_table_references(),
            "config_vars": self.get_config_vars(),
            "dml_operations": self.get_dml_operations(),
            "has_error_handling": self.has_error_handling(),
            "has_query_label": "@@query_label" in self.content,
        }

    def get_procedure_name(self) -> Optional[str]:
        """Extract the procedure name from CREATE OR REPLACE PROCEDURE."""
        m = re.search(
            r'CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+`?([^`(]+)`?\s*\(',
            self.content, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()
        return None

    def get_query_label_fields(self) -> dict:
        """Extract all fields from the @@query_label block."""
        fields = {}
        if "@@query_label" not in self.content:
            return fields

        # Extract the query_label assignment block
        ql_match = re.search(
            r'SET\s+@@query_label\s*=\s*FORMAT\s*\((.*?)\)',
            self.content, re.DOTALL | re.IGNORECASE
        )
        if not ql_match:
            return fields

        ql_block = ql_match.group(1)

        # Parse each field
        field_patterns = [
            ("etl_type", r'etl_type\s*:\s*(\$\{[^}]+\}|[^\s,}]+)'),
            ("application", r'application\s*:\s*(\$\{[^}]+\}|[^\s,}]+)'),
            ("environment", r'environment\s*:\s*(\$\{[^}]+\}|[^\s,}]+)'),
            ("vsad", r'vsad\s*:\s*(\$\{[^}]+\}|[^\s,}]+)'),
            ("dataset_id", r'dataset_id\s*:\s*(\$\{[^}]+\}|[^\s,}]+)'),
            ("frequency", r'frequency\s*:\s*(\w+)'),
        ]

        for field_name, pattern in field_patterns:
            m = re.search(pattern, ql_block)
            if m:
                fields[field_name] = m.group(1)

        # Extract table_id entries
        table_ids = re.findall(r'(table_id(?:_\d+)?)\s*:\s*(\$\{[^}]+\}|[^\s,}]+)', ql_block)
        for tid_key, tid_val in table_ids:
            fields[tid_key] = tid_val

        return fields

    def get_variable_declarations(self) -> list:
        """Extract DECLARE statements."""
        declares = []
        for m in re.finditer(
            r'DECLARE\s+(\w+)\s+(\w+(?:\s*\([^)]*\))?)\s*(?:DEFAULT\s+(.+?))?;',
            self.content, re.IGNORECASE
        ):
            declares.append({
                "name": m.group(1),
                "type": m.group(2),
                "default": m.group(3).strip() if m.group(3) else None,
            })
        return declares

    def get_table_references(self) -> list:
        """Extract all backtick-enclosed table references."""
        refs = set()
        for m in re.finditer(r'`([^`]+\.[^`]+\.[^`]+)`', self.content):
            refs.add(m.group(1))
        return sorted(refs)

    def get_config_vars(self) -> list:
        """Extract all ${config_var} references."""
        return sorted(set(re.findall(r'\$\{(\w+)\}', self.content)))

    def get_dml_operations(self) -> list:
        """Identify INSERT, UPDATE, DELETE, MERGE operations."""
        ops = []
        patterns = [
            (r'INSERT\s+INTO\s+`([^`]+)`', "INSERT"),
            (r'UPDATE\s+`([^`]+)`', "UPDATE"),
            (r'DELETE\s+FROM\s+`([^`]+)`', "DELETE"),
            (r'MERGE\s+INTO\s+`([^`]+)`', "MERGE"),
            (r'CREATE\s+OR\s+REPLACE\s+(?:TABLE|VIEW)\s+`([^`]+)`', "CREATE"),
            (r'TRUNCATE\s+TABLE\s+`([^`]+)`', "TRUNCATE"),
        ]
        for pattern, op_type in patterns:
            for m in re.finditer(pattern, self.content, re.IGNORECASE):
                ops.append({"type": op_type, "target": m.group(1)})
        return ops

    def has_error_handling(self) -> bool:
        """Check if the procedure has EXCEPTION/error handling."""
        return bool(re.search(r'\bEXCEPTION\b|\bWHEN\s+ERROR\b', self.content, re.IGNORECASE))
