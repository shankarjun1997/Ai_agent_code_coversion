"""
Agent 4 — Fix Agent
=====================
Automatically corrects issues identified by the Debug Agent.

Capabilities:
  - Add missing config exports to deploy cfg files
  - Replace hardcoded values with ${config_var} in SQL
  - Fix query_label blocks (ordering, missing fields)
  - Rename dag_ids to follow convention
  - Sync config keys across environments
  - Generate missing query_label blocks
"""
import os
import re
import shutil
from typing import Optional
from datetime import datetime

from . import BaseAgent, AgentResult


class FixAgent(BaseAgent):
    """
    Agent 4: Auto-fix issues found by the Debug Agent.
    
    Takes debug diagnoses as input and applies fixes.
    Can operate in dry-run or apply mode.
    """

    AGENT_NAME = "fix_agent"

    # Map fix action types to handler methods
    FIX_HANDLERS = {
        "add_exports": "_fix_add_exports",
        "replace_value": "_fix_replace_value",
        "replace_hardcoded": "_fix_replace_hardcoded",
        "replace_in_query_label": "_fix_replace_in_query_label",
        "add_query_label_block": "_fix_add_query_label",
        "reorder_table_ids": "_fix_reorder_table_ids",
        "rename_dag_id": "_fix_rename_dag_id",
        "sync_config_keys": "_fix_sync_config_keys",
    }

    def __init__(self, config: dict, module_name: str, dry_run: bool = True):
        super().__init__(config, module_name)
        self.dry_run = dry_run
        self.fixes_applied = []

    def execute(self, input_data: AgentResult = None) -> AgentResult:
        result = AgentResult(self.AGENT_NAME, self.module_name)
        mode = "DRY RUN" if self.dry_run else "APPLY"
        self.logger.info(f"=== Fix Agent ({mode}): {self.module_name} ===")

        if not input_data:
            result.set_failure("No input data from debug agent")
            self.save_result(result)
            return result

        try:
            fixable = input_data.data.get("fixable", [])
            if not fixable:
                # Try to get from diagnoses
                fixable = [
                    d for d in input_data.data.get("diagnoses", [])
                    if d.get("auto_fixable")
                ]

            self.logger.info(f"Found {len(fixable)} auto-fixable issues")

            applied = []
            skipped = []
            failed = []

            for diagnosis in fixable:
                fix_action = diagnosis.get("fix_action")
                if not fix_action:
                    skipped.append({"diagnosis": diagnosis, "reason": "No fix_action"})
                    continue

                try:
                    fix_result = self._apply_fix(fix_action, diagnosis)
                    if fix_result:
                        applied.append(fix_result)
                    else:
                        skipped.append({"diagnosis": diagnosis, "reason": "Handler returned None"})
                except Exception as e:
                    failed.append({
                        "diagnosis": diagnosis,
                        "error": str(e),
                    })
                    self.logger.error(f"Fix failed: {e}")

            result.data = {
                "mode": mode,
                "applied": applied,
                "skipped": skipped,
                "failed": failed,
            }
            result.metrics = {
                "total_fixable": len(fixable),
                "applied": len(applied),
                "skipped": len(skipped),
                "failed": len(failed),
            }

            if failed:
                result.set_failure(f"{len(failed)} fixes failed")
            else:
                result.set_success()

            self.logger.info(
                f"Fix complete: {len(applied)} applied, {len(skipped)} skipped, {len(failed)} failed"
            )

        except Exception as e:
            self.logger.error(f"Fix agent failed: {e}", exc_info=True)
            result.set_failure(str(e))

        self.save_result(result)
        return result

    def _apply_fix(self, fix_action: dict, diagnosis: dict) -> Optional[dict]:
        """Route fix to the appropriate handler."""
        action_type = fix_action.get("type", "")
        handler_name = self.FIX_HANDLERS.get(action_type)

        if not handler_name:
            self.logger.warning(f"No handler for fix type: {action_type}")
            return None

        handler = getattr(self, handler_name, None)
        if not handler:
            self.logger.warning(f"Handler method not found: {handler_name}")
            return None

        return handler(fix_action, diagnosis)

    # ---- Fix Handlers ----

    def _fix_add_exports(self, action: dict, diagnosis: dict) -> dict:
        """Add missing export statements to a config file."""
        cfg_file = action.get("target_file", "")
        variables = action.get("variables", [])

        cfg_path = None
        for path in self.list_config_files():
            if os.path.basename(path) == cfg_file:
                cfg_path = path
                break

        if not cfg_path:
            return {"status": "skipped", "reason": f"Config file not found: {cfg_file}"}

        content = self.read_file(cfg_path)
        lines_to_add = []
        for var in variables:
            if f"export {var}=" not in content:
                lines_to_add.append(f"export {var}=TODO_SET_VALUE")

        if not lines_to_add:
            return {"status": "skipped", "reason": "All exports already exist"}

        new_content = content.rstrip() + "\n" + "\n".join(lines_to_add) + "\n"

        if not self.dry_run:
            self._backup_and_write(cfg_path, new_content)

        return {
            "status": "applied" if not self.dry_run else "dry_run",
            "file": cfg_file,
            "action": "add_exports",
            "added": lines_to_add,
        }

    def _fix_replace_value(self, action: dict, diagnosis: dict) -> dict:
        """Replace a specific value in a config file."""
        field = action.get("field", "")
        old_value = action.get("old_value", "")
        new_value = action.get("new_value", "")

        results = []
        for cfg_path in self.list_config_files():
            content = self.read_file(cfg_path)
            filename = os.path.basename(cfg_path)

            old_str = f"export {field}={old_value}"
            new_str = f"export {field}={new_value}"

            if old_str in content:
                new_content = content.replace(old_str, new_str, 1)
                if not self.dry_run:
                    self._backup_and_write(cfg_path, new_content)
                results.append({
                    "file": filename,
                    "replaced": f"{old_str} -> {new_str}",
                })

        return {
            "status": "applied" if not self.dry_run else "dry_run",
            "action": "replace_value",
            "changes": results,
        }

    def _fix_replace_hardcoded(self, action: dict, diagnosis: dict) -> dict:
        """Replace hardcoded project/dataset IDs with config vars."""
        value = action.get("value", "")

        # Try to find matching config var
        config_var = self._find_config_var_for_value(value)

        results = []
        if config_var:
            for sql_path in self.list_sql_files():
                content = self.read_file(sql_path)
                filename = os.path.basename(sql_path)

                if value in content:
                    new_content = content.replace(value, f"${{{config_var}}}")
                    if not self.dry_run:
                        self._backup_and_write(sql_path, new_content)
                    results.append({
                        "file": filename,
                        "replaced": f"{value} -> ${{{config_var}}}",
                    })

        return {
            "status": "applied" if not self.dry_run else "dry_run",
            "action": "replace_hardcoded",
            "config_var": config_var,
            "changes": results,
        }

    def _fix_replace_in_query_label(self, action: dict, diagnosis: dict) -> dict:
        """Replace a hardcoded value in a query_label block with ${config_var}."""
        field = action.get("field", "")
        old_value = action.get("old_value", "")
        new_value = action.get("new_value", f"${{{field}}}")

        results = []
        for sql_path in self.list_sql_files():
            content = self.read_file(sql_path)
            filename = os.path.basename(sql_path)

            pattern = rf'({field}\s*:\s*){re.escape(old_value)}'
            if re.search(pattern, content):
                new_content = re.sub(pattern, rf'\g<1>{new_value}', content, count=1)
                if not self.dry_run:
                    self._backup_and_write(sql_path, new_content)
                results.append({
                    "file": filename,
                    "replaced": f"{field}: {old_value} -> {new_value}",
                })

        return {
            "status": "applied" if not self.dry_run else "dry_run",
            "action": "replace_in_query_label",
            "changes": results,
        }

    def _fix_add_query_label(self, action: dict, diagnosis: dict) -> dict:
        """Add a query_label block to a SQL file that's missing one."""
        # Template for query_label block
        ql_template = '''    SET @@query_label = FORMAT(
        """etl_type: ${{etl_type}},
        application:${{application}},
        environment: ${{environment}},
        vsad: ${{vsad}},
        dataset_id: ${{target_dataset_name}},
        table_id: TODO_SET_TABLE,
        frequency: ${frequency}
        run_time: %s""",
        run_time
    );'''

        results = []
        for sql_path in self.list_sql_files():
            content = self.read_file(sql_path)
            filename = os.path.basename(sql_path)

            if "@@query_label" in content:
                continue

            # Find insertion point: after DECLARE block, before first SELECT/INSERT/SET
            # Look for 'BEGIN' keyword as anchor
            begin_match = re.search(r'\bBEGIN\b', content, re.IGNORECASE)
            if begin_match:
                # Insert after the first BEGIN + run_time declaration
                insert_pos = begin_match.end()
                new_content = (
                    content[:insert_pos] +
                    "\n\n    -- Query Label\n" + ql_template + "\n" +
                    content[insert_pos:]
                )
                if not self.dry_run:
                    self._backup_and_write(sql_path, new_content)
                results.append({
                    "file": filename,
                    "action": "added_query_label_block",
                })

        return {
            "status": "applied" if not self.dry_run else "dry_run",
            "action": "add_query_label",
            "changes": results,
        }

    def _fix_reorder_table_ids(self, action: dict, diagnosis: dict) -> dict:
        """Fix table_id ordering in query_label blocks."""
        results = []
        for sql_path in self.list_sql_files():
            content = self.read_file(sql_path)
            filename = os.path.basename(sql_path)

            # Find all table_id entries with their values
            entries = re.findall(r'(table_id(?:_\d+)?)\s*:\s*(\S+)', content)
            if not entries or entries[0][0] == "table_id":
                continue  # Already correct or no entries

            # Renumber: first = table_id, rest = table_id_1, table_id_2...
            new_content = content
            for i, (old_key, value) in enumerate(entries):
                new_key = "table_id" if i == 0 else f"table_id_{i}"
                if old_key != new_key:
                    new_content = new_content.replace(
                        f"{old_key}: {value}",
                        f"{new_key}: {value}",
                        1
                    )

            if new_content != content:
                if not self.dry_run:
                    self._backup_and_write(sql_path, new_content)
                results.append({
                    "file": filename,
                    "old_order": [e[0] for e in entries],
                    "new_order": ["table_id"] + [f"table_id_{i}" for i in range(1, len(entries))],
                })

        return {
            "status": "applied" if not self.dry_run else "dry_run",
            "action": "reorder_table_ids",
            "changes": results,
        }

    def _fix_rename_dag_id(self, action: dict, diagnosis: dict) -> dict:
        """Fix dag_id to follow naming convention."""
        module = action.get("module", self.module_name)
        correct_dag_id = f"gudv_nar_onef_{module}"

        results = []
        import yaml as yaml_lib

        for yml_path in self.list_dag_config_files():
            content = self.read_file(yml_path)
            filename = os.path.basename(yml_path)

            try:
                data = yaml_lib.safe_load(content)
                modified = False
                if isinstance(data, dict):
                    for project_id, entries in data.items():
                        if isinstance(entries, list):
                            for entry in entries:
                                if "dag_id" in entry and not entry["dag_id"].startswith("gudv_nar_onef_"):
                                    old_id = entry["dag_id"]
                                    entry["dag_id"] = correct_dag_id
                                    modified = True
                                    results.append({
                                        "file": filename,
                                        "old_dag_id": old_id,
                                        "new_dag_id": correct_dag_id,
                                    })

                if modified and not self.dry_run:
                    new_content = yaml_lib.dump(data, default_flow_style=False)
                    self._backup_and_write(yml_path, new_content)

            except Exception as e:
                self.logger.error(f"Failed to fix dag_id in {filename}: {e}")

        return {
            "status": "applied" if not self.dry_run else "dry_run",
            "action": "rename_dag_id",
            "changes": results,
        }

    def _fix_sync_config_keys(self, action: dict, diagnosis: dict) -> dict:
        """Sync export keys across all environment config files."""
        # Collect all exports from all configs
        all_exports = {}
        for cfg_path in self.list_config_files():
            filename = os.path.basename(cfg_path)
            content = self.read_file(cfg_path)
            all_exports[cfg_path] = self._parse_exports(content)

        # Union of all keys
        all_keys = set()
        for exports in all_exports.values():
            all_keys.update(exports.keys())

        results = []
        for cfg_path, exports in all_exports.items():
            filename = os.path.basename(cfg_path)
            missing_keys = all_keys - set(exports.keys())
            if missing_keys:
                content = self.read_file(cfg_path)
                lines_to_add = []
                for key in sorted(missing_keys):
                    # Try to get default from another config
                    default = "TODO_SET_VALUE"
                    for other_exports in all_exports.values():
                        if key in other_exports:
                            default = other_exports[key]
                            break
                    # Special handling for environment
                    if key == "environment":
                        if "prd" in filename:
                            default = "prod"
                        elif "uat" in filename:
                            default = "uat"
                        elif "dev" in filename:
                            default = "dev"
                    lines_to_add.append(f"export {key}={default}")

                if lines_to_add:
                    new_content = content.rstrip() + "\n" + "\n".join(lines_to_add) + "\n"
                    if not self.dry_run:
                        self._backup_and_write(cfg_path, new_content)
                    results.append({
                        "file": filename,
                        "added_keys": sorted(missing_keys),
                    })

        return {
            "status": "applied" if not self.dry_run else "dry_run",
            "action": "sync_config_keys",
            "changes": results,
        }

    # ---- Helpers ----

    def _backup_and_write(self, filepath: str, content: str):
        """Create backup and write new content."""
        agent_config = self.config.get("agents", {}).get("fix", {})
        if agent_config.get("create_backup", True):
            suffix = agent_config.get("backup_suffix", ".bak")
            backup_path = filepath + suffix
            shutil.copy2(filepath, backup_path)
        self.write_file(filepath, content)

    def _find_config_var_for_value(self, value: str) -> Optional[str]:
        """Find which config variable maps to a given value."""
        for cfg_path in self.list_config_files():
            content = self.read_file(cfg_path)
            for line in content.splitlines():
                if line.strip().startswith("export ") and f"={value}" in line:
                    kv = line.strip()[7:]
                    key = kv.split("=")[0].strip()
                    return key
        return None

    def _parse_exports(self, content: str) -> dict:
        exports = {}
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("export ") and "=" in line:
                kv = line[7:]
                key, _, value = kv.partition("=")
                exports[key.strip()] = value.strip()
        return exports
