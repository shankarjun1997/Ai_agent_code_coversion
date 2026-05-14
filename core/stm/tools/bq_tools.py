"""BigQuery agent tools — give L3/L4 LLM calls hand-reach into the live target.

Three tools, all read-only:
  - lookup_bq_table(dataset, table)   → returns column schema + row count
  - sample_bq_query(sql, limit)       → executes SELECT with hard LIMIT clamp
  - dry_run_sql(sql)                  → validates SQL without executing

Used by the SemanticMappingAgent (L3) and TransformationAgent (L4) via
LLMClient.run_agent. Tools are JSON-callable; results are JSON strings.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


BQ_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "lookup_bq_table",
        "description": (
            "Look up the schema and row count of a BigQuery table. Use when you "
            "need to confirm exact column names/types before writing a mapping or "
            "transformation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "BQ dataset name."},
                "table":   {"type": "string", "description": "BQ table name."},
            },
            "required": ["dataset", "table"],
        },
    },
    {
        "name": "sample_bq_query",
        "description": (
            "Run a read-only SELECT against BigQuery. Always include a LIMIT (max 100). "
            "Use sparingly — only when sampling is necessary to confirm a transformation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql":   {"type": "string", "description": "SELECT query."},
                "limit": {"type": "integer", "description": "Row cap (1-100, default 25)."},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "dry_run_sql",
        "description": (
            "Validate a BigQuery SQL statement without executing it. Returns ok/error + "
            "estimated bytes scanned. Use to verify a derived transformation expression."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "BQ Standard SQL to validate."},
            },
            "required": ["sql"],
        },
    },
]


def _project_id() -> str:
    return os.environ.get("BQ_PROJECT_ID", "")


def lookup_bq_table(dataset: str, table: str) -> Dict[str, Any]:
    try:
        from core import bq_cli
        schema = bq_cli.get_table_schema(dataset, table, _project_id() or None)
        info = bq_cli.get_table_info(dataset, table, _project_id() or None)
        return {
            "ok": True,
            "dataset": dataset, "table": table,
            "columns": [
                {"name": c.get("name"), "type": c.get("type"), "mode": c.get("mode")}
                for c in (schema or [])
            ],
            "num_rows": info.get("num_rows") if isinstance(info, dict) else None,
        }
    except Exception as exc:
        return {"ok": False, "dataset": dataset, "table": table, "error": str(exc)}


_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(r"\b(insert|update|delete|merge|drop|alter|create)\b", re.IGNORECASE)


def sample_bq_query(sql: str, limit: int = 25) -> Dict[str, Any]:
    if not sql or not sql.strip():
        return {"ok": False, "error": "empty sql"}
    if _FORBIDDEN_RE.search(sql):
        return {"ok": False, "error": "DDL/DML not allowed in sample_bq_query"}
    n = max(1, min(int(limit or 25), 100))
    safe = sql.rstrip(" ;\n\t")
    if not _LIMIT_RE.search(safe):
        safe = f"{safe} LIMIT {n}"
    try:
        from core.bq_client import BQClient
        client = BQClient(project_id=_project_id() or None)
        rows = client.run_query(safe) if hasattr(client, "run_query") else []
        return {"ok": True, "rows": rows[:n], "row_count": len(rows[:n])}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "sql": safe}


def dry_run_sql(sql: str) -> Dict[str, Any]:
    if not sql or not sql.strip():
        return {"ok": False, "error": "empty sql"}
    try:
        from core.bq_client import BQClient
        client = BQClient(project_id=_project_id() or None)
        result = client.dry_run(sql)
        if isinstance(result, tuple):
            ok, bytes_scanned, msg = (result + (None, None))[:3]
            return {"ok": bool(ok), "bytes_scanned": bytes_scanned, "message": msg}
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def make_bq_tool_handler() -> Callable[[str, Dict[str, Any]], str]:
    """Build a tool dispatcher compatible with LLMClient.run_agent."""
    def _handle(name: str, args: Dict[str, Any]) -> str:
        try:
            if name == "lookup_bq_table":
                out = lookup_bq_table(args.get("dataset", ""), args.get("table", ""))
            elif name == "sample_bq_query":
                out = sample_bq_query(args.get("sql", ""), int(args.get("limit") or 25))
            elif name == "dry_run_sql":
                out = dry_run_sql(args.get("sql", ""))
            else:
                out = {"ok": False, "error": f"unknown tool {name!r}"}
        except Exception as exc:
            out = {"ok": False, "error": str(exc)}
        try:
            return json.dumps(out)
        except Exception:
            return json.dumps({"ok": False, "error": "result_not_serialisable"})
    return _handle


def render_target_summary(target_graph) -> str:
    """Render BqTargetGraph to a short string for prompt injection."""
    if not target_graph or not getattr(target_graph, "tables", None):
        return "(target dataset not crawled or empty)"
    lines: List[str] = [
        f"BigQuery target: project={target_graph.project_id}, dataset={target_graph.dataset}",
        f"Tables in dataset ({len(target_graph.tables)}):",
    ]
    for tbl in target_graph.tables[:20]:
        cols_str = ", ".join(
            f"{c.get('name')}:{c.get('type')}" for c in (tbl.columns or [])[:24]
        )
        lines.append(f"  - {tbl.name} ({tbl.row_count or '?'} rows): {cols_str}")
    if len(target_graph.tables) > 20:
        lines.append(f"  ... +{len(target_graph.tables) - 20} more")
    return "\n".join(lines)
