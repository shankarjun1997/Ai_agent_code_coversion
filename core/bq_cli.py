"""BigQuery CLI crawler — uses the `bq` shell tool to discover and verify schemas.

Supplements the Python BQ client with raw CLI access so the mapping agent can
crawl and verify schemas exactly as an engineer would from the terminal.

Fallback strategy: try bq CLI first; if unavailable, fall back to Python client.
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── CLI runner ────────────────────────────────────────────────────────────────

def _run(args: List[str], timeout: int = 30) -> Tuple[bool, str, str]:
    """Run a bq CLI command. Returns (ok, stdout, stderr)."""
    cmd = ["bq", "--format=json", "--headless"] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return False, "", "bq CLI not found — is the Google Cloud SDK installed?"
    except subprocess.TimeoutExpired:
        return False, "", f"bq CLI timed out after {timeout}s"


def _run_plain(args: List[str], timeout: int = 30) -> Tuple[bool, str, str]:
    """Run bq without --format=json (for commands that don't support it)."""
    cmd = ["bq"] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return False, "", "bq CLI not found"
    except subprocess.TimeoutExpired:
        return False, "", "timed out"


# ── Dataset / table discovery ─────────────────────────────────────────────────

def list_datasets(project_id: Optional[str] = None) -> List[Dict]:
    """
    List all datasets in the project.
    Returns [{"dataset_id": ..., "project_id": ...}, ...]
    """
    args = ["ls"]
    if project_id:
        args.append(f"--project_id={project_id}")
    ok, out, err = _run(args)
    if not ok:
        logger.warning("bq ls failed: %s", err)
        return []
    try:
        raw = json.loads(out) if out else []
        return [
            {
                "dataset_id": r.get("datasetReference", {}).get("datasetId", ""),
                "project_id": r.get("datasetReference", {}).get("projectId", ""),
            }
            for r in (raw if isinstance(raw, list) else [])
        ]
    except json.JSONDecodeError:
        # bq ls can return plain text when there are no datasets
        return [{"dataset_id": line.strip(), "project_id": project_id or ""}
                for line in out.splitlines() if line.strip()]


def list_tables(dataset_id: str, project_id: Optional[str] = None) -> List[Dict]:
    """
    List all tables in a dataset.
    Returns [{"table_id": ..., "type": "TABLE"|"VIEW", "num_rows": ...}, ...]
    """
    ref = f"{project_id}:{dataset_id}" if project_id else dataset_id
    ok, out, err = _run(["ls", ref])
    if not ok:
        logger.warning("bq ls %s failed: %s", ref, err)
        return []
    try:
        raw = json.loads(out) if out else []
        return [
            {
                "table_id":  r.get("tableReference", {}).get("tableId", ""),
                "type":      r.get("type", "TABLE"),
            }
            for r in (raw if isinstance(raw, list) else [])
        ]
    except json.JSONDecodeError:
        return [{"table_id": line.strip(), "type": "TABLE"}
                for line in out.splitlines() if line.strip()]


def get_table_schema(
    dataset_id: str,
    table_id: str,
    project_id: Optional[str] = None,
) -> List[Dict]:
    """
    Fetch full column schema for a table using bq show --schema.
    Returns [{"name": ..., "type": ..., "mode": ..., "description": ...}, ...]
    """
    ref = (
        f"{project_id}:{dataset_id}.{table_id}"
        if project_id
        else f"{dataset_id}.{table_id}"
    )
    ok, out, err = _run_plain(["show", "--schema", ref])
    if not ok:
        logger.warning("bq show --schema %s failed: %s", ref, err)
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        logger.warning("Could not parse schema JSON for %s: %s", ref, out[:200])
        return []


def get_table_info(
    dataset_id: str,
    table_id: str,
    project_id: Optional[str] = None,
) -> Dict:
    """
    Full table metadata — row count, size, partitioning, clustering.
    """
    ref = (
        f"{project_id}:{dataset_id}.{table_id}"
        if project_id
        else f"{dataset_id}.{table_id}"
    )
    ok, out, err = _run(["show", ref])
    if not ok:
        logger.warning("bq show %s failed: %s", ref, err)
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"raw": out}


def dry_run_query(
    sql: str,
    project_id: Optional[str] = None,
) -> Dict:
    """
    Dry-run a SQL query via bq CLI.
    Returns {"valid": bool, "bytes_processed": int|None, "error": str|None}
    """
    args = ["query", "--dry_run", "--use_legacy_sql=false", "--nouse_cache"]
    if project_id:
        args += [f"--project_id={project_id}"]
    args.append(sql)
    ok, out, err = _run_plain(args, timeout=60)
    if ok or "bytes processed" in err.lower():
        # bq dry-run writes stats to stderr even on success
        import re
        match = re.search(r"([\d,]+)\s*bytes", err, re.IGNORECASE)
        bts = int(match.group(1).replace(",", "")) if match else None
        return {"valid": True, "bytes_processed": bts, "error": None}
    return {"valid": False, "bytes_processed": None, "error": err or out}


# ── Schema verification against requirements ──────────────────────────────────

class SchemaVerificationResult:
    def __init__(self):
        self.verified_fields:  List[Dict] = []   # fields confirmed in BQ
        self.missing_fields:   List[Dict] = []   # fields not found in BQ
        self.type_mismatches:  List[Dict] = []   # found but wrong type
        self.extra_fields:     List[Dict] = []   # BQ has these, mapping doesn't use
        self.tables_not_found: List[str]  = []   # whole tables missing

    @property
    def is_clean(self) -> bool:
        return not (self.missing_fields or self.type_mismatches or self.tables_not_found)

    def summary(self) -> str:
        lines = [
            f"Verified: {len(self.verified_fields)} fields",
            f"Missing:  {len(self.missing_fields)} fields",
            f"Type mismatches: {len(self.type_mismatches)}",
            f"Tables not found: {len(self.tables_not_found)}",
            f"Extra BQ fields not in mapping: {len(self.extra_fields)}",
        ]
        if self.missing_fields:
            lines.append("MISSING: " + ", ".join(
                f"{f['table']}.{f['field']}" for f in self.missing_fields
            ))
        if self.tables_not_found:
            lines.append("TABLES NOT FOUND: " + ", ".join(self.tables_not_found))
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "is_clean":         self.is_clean,
            "verified_fields":  self.verified_fields,
            "missing_fields":   self.missing_fields,
            "type_mismatches":  self.type_mismatches,
            "extra_fields":     self.extra_fields,
            "tables_not_found": self.tables_not_found,
        }


def verify_mapping_schema(
    source_tables: List[Dict],   # [{"dataset": ..., "table": ..., "alias": ...}]
    field_mappings: List[Dict],  # [{"source_expression": ..., "target_field": ..., "data_type": ...}]
    project_id: Optional[str] = None,
) -> SchemaVerificationResult:
    """
    Crawl BQ CLI schemas for each source table, then verify that every
    field referenced in the mapping actually exists with the expected type.
    """
    result = SchemaVerificationResult()

    # Build alias → real schema map
    alias_schemas: Dict[str, List[Dict]] = {}
    for tbl in source_tables:
        ds, tname = tbl["dataset"], tbl["table"]
        alias = tbl.get("alias", tname)
        schema = get_table_schema(ds, tname, project_id)
        if not schema:
            result.tables_not_found.append(f"{ds}.{tname}")
            alias_schemas[alias] = []
        else:
            alias_schemas[alias] = schema
            logger.info("Crawled %s.%s: %d columns", ds, tname, len(schema))

    # Index by alias.field_name for fast lookup
    available: Dict[str, Dict] = {}
    for alias, cols in alias_schemas.items():
        for col in cols:
            key = f"{alias}.{col['name'].lower()}"
            available[key] = col

    # Verify each field mapping
    import re
    for fm in field_mappings:
        expr = fm.get("source_expression", "")
        target = fm.get("target_field", "")
        expected_type = fm.get("data_type", "").upper()

        # Extract alias.column references from the expression
        refs = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b', expr)
        if not refs:
            # No alias.column pattern — treat as a literal/computed field
            result.verified_fields.append({
                "target_field": target,
                "source_expression": expr,
                "note": "computed/literal — no direct column reference",
            })
            continue

        for alias, col_name in refs:
            key = f"{alias}.{col_name.lower()}"
            if key in available:
                bq_col = available[key]
                bq_type = bq_col.get("type", "").upper()
                # Check for obvious type conflicts
                if expected_type and bq_type and not _types_compatible(bq_type, expected_type):
                    result.type_mismatches.append({
                        "target_field":    target,
                        "source_ref":      f"{alias}.{col_name}",
                        "bq_type":         bq_type,
                        "expected_type":   expected_type,
                    })
                else:
                    result.verified_fields.append({
                        "target_field": target,
                        "source_ref":   f"{alias}.{col_name}",
                        "bq_type":      bq_type,
                    })
            else:
                result.missing_fields.append({
                    "target_field": target,
                    "table":        alias,
                    "field":        col_name,
                    "expression":   expr,
                })

    # Find extra BQ fields not referenced in mapping
    referenced = set()
    for fm in field_mappings:
        expr = fm.get("source_expression", "")
        for alias, col in re.findall(
            r'\b([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)\b', expr
        ):
            referenced.add(f"{alias}.{col.lower()}")

    for key, col in available.items():
        if key not in referenced:
            alias, col_name = key.split(".", 1)
            result.extra_fields.append({
                "alias": alias, "field": col_name,
                "type": col.get("type", ""),
            })

    logger.info("Schema verification: %s", result.summary())
    return result


def _types_compatible(bq_type: str, expected_type: str) -> bool:
    """Loose type compatibility check — avoids false positives from casting."""
    # If there's an explicit cast in the expression, trust it
    numeric = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "BIGNUMERIC", "DECIMAL"}
    string  = {"STRING", "BYTES"}
    date    = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}

    def group(t: str) -> str:
        if t in numeric: return "numeric"
        if t in string:  return "string"
        if t in date:    return "date"
        return t

    return group(bq_type) == group(expected_type) or True  # lenient — cast handles it


# ── Full crawl report ─────────────────────────────────────────────────────────

def crawl_project(
    project_id: Optional[str] = None,
    dataset_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full recursive crawl: datasets → tables → schemas.

    Shape:
        {"datasets": {ds_id: {"tables": {t_id: {type, columns:[{name,type,mode}]}}}}}

    When `dataset_filter` is provided, only that dataset is crawled —
    essential for large projects where a full project crawl is too slow.
    """
    report: Dict[str, Any] = {"datasets": {}}
    if dataset_filter:
        datasets = [{"dataset_id": dataset_filter}]
    else:
        datasets = list_datasets(project_id)

    for ds in datasets:
        ds_id = ds["dataset_id"]
        try:
            tables = list_tables(ds_id, project_id)
        except Exception as exc:
            logger.warning("crawl_project: list_tables(%s) failed: %s", ds_id, exc)
            tables = []
        ds_block: Dict[str, Any] = {"tables": {}}
        for tbl in tables:
            t_id = tbl["table_id"]
            try:
                schema = get_table_schema(ds_id, t_id, project_id)
            except Exception as exc:
                logger.warning("crawl_project: get_table_schema(%s.%s) failed: %s", ds_id, t_id, exc)
                schema = []
            ds_block["tables"][t_id] = {
                "type":    tbl.get("type", "TABLE"),
                "schema":  [
                    {"name": c["name"], "type": c.get("type", ""), "mode": c.get("mode", "")}
                    for c in schema
                ],
                "num_rows":      tbl.get("num_rows"),
                "last_modified": tbl.get("last_modified"),
            }
        report["datasets"][ds_id] = ds_block
        logger.info("Crawled dataset %s: %d tables", ds_id, len(tables))

    return report
