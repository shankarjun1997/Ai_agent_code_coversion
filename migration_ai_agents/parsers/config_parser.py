"""
Config Parser — Parses deploy config files (deployprd.cfg, deployuat.cfg, deploydev.cfg).
Extracts: exports, sections, environment type.
"""
import re
from typing import Optional


class ConfigParser:
    """Parse OneFiber deploy config files."""

    def __init__(self, content: str, filename: str = ""):
        self.content = content
        self.filename = filename

    def parse(self) -> dict:
        """Full parse of the config file."""
        return {
            "filename": self.filename,
            "environment": self.detect_environment(),
            "exports": self.get_exports(),
            "sections": self.get_sections(),
            "metadata": self.get_metadata_exports(),
            "source_tables": self.get_source_tables(),
            "target_tables": self.get_target_tables(),
        }

    def detect_environment(self) -> Optional[str]:
        """Detect environment from filename or export."""
        if "prd" in self.filename.lower():
            return "prod"
        elif "uat" in self.filename.lower():
            return "uat"
        elif "dev" in self.filename.lower():
            return "dev"
        # Fallback: check export environment=
        m = re.search(r'export\s+environment\s*=\s*(\S+)', self.content)
        return m.group(1) if m else None

    def get_exports(self) -> dict:
        """Parse all export key=value pairs."""
        exports = {}
        for line in self.content.splitlines():
            line = line.strip()
            if line.startswith("export ") and "=" in line:
                kv = line[7:]  # strip 'export '
                key, _, value = kv.partition("=")
                exports[key.strip()] = value.strip()
        return exports

    def get_sections(self) -> list:
        """Extract section headers (# ==== SECTION NAME ====)."""
        sections = []
        for m in re.finditer(r'#\s*=+\s*\n#\s*(.+?)\s*\n#\s*=+', self.content):
            sections.append(m.group(1).strip())
        return sections

    def get_metadata_exports(self) -> dict:
        """Extract query label metadata exports."""
        exports = self.get_exports()
        metadata_keys = ["etl_type", "application", "environment", "vsad"]
        return {k: exports.get(k) for k in metadata_keys if k in exports}

    def get_source_tables(self) -> dict:
        """Extract source table exports (src_* keys)."""
        exports = self.get_exports()
        return {k: v for k, v in exports.items() if k.startswith("src_") and k not in ("src_project_id", "src_dataset_name")}

    def get_target_tables(self) -> dict:
        """Extract target table exports (target_* keys, excluding project/dataset)."""
        exports = self.get_exports()
        return {
            k: v for k, v in exports.items()
            if k.startswith("target_") and k not in ("target_project_id", "target_dataset_name")
        }

    def validate_against_sql(self, sql_config_vars: list) -> dict:
        """
        Validate that all config vars used in SQL have matching exports.
        
        Args:
            sql_config_vars: list of variable names from SQL ${var} references
            
        Returns:
            dict with matched, missing, unused
        """
        exports = set(self.get_exports().keys())
        sql_vars = set(sql_config_vars)

        return {
            "matched": sorted(exports & sql_vars),
            "missing_in_config": sorted(sql_vars - exports),
            "unused_in_sql": sorted(exports - sql_vars),
        }
