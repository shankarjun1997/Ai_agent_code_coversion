"""L4 — SQL agent.

Generates BigQuery Standard SQL that loads data from one source table into
multiple target tables. One MERGE (or fallback CREATE OR REPLACE … AS SELECT)
per target table that receives data. Idempotent, type-safe, includes a header
comment per statement summarizing what is loaded from which source columns.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import SqlBundle, SqlStatement, StageStatus

logger = logging.getLogger(__name__)


SYSTEM = (
    "You generate production BigQuery Standard SQL. You emit idempotent MERGE "
    "statements grouped by target table. You apply business logic exactly, use "
    "SAFE_CAST / SAFE_DIVIDE, and never mix TIMESTAMP with DATE."
)


class SqlAgent(StmAgent):
    stage = "L4"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        if bb.source_table is None or bb.target_schema is None or not bb.mappings:
            return BlackboardDelta.failure("SQL gen requires source + target + mappings")
        project = bb.target_project
        dataset = bb.target_dataset
        if not project or not dataset:
            return BlackboardDelta.failure("Target project/dataset missing — cannot fully qualify SQL")

        picked = {e.table for e in (bb.shortlist.rows if bb.shortlist else []) if e.picked}
        source_type_ref = {
            "table": bb.source_table.name,
            "cols": [f"{c.name}:{c.type}" if c.type else c.name for c in bb.source_table.columns],
        }
        target_type_ref = [
            {
                "table": t.name,
                "cols": [f"{c.name}:{c.type}" if c.type else c.name for c in t.columns],
            }
            for t in bb.target_schema.tables if t.name in picked
        ]
        slim_mappings = [
            {
                "st": m.source_table, "sc": m.source_column,
                "tt": m.target_table, "tc": m.target_column,
                "type": m.mapping_type, "logic": m.business_logic,
            }
            for m in bb.mappings if m.mapping_type != "unused"
        ]

        prompt = (
            "Generate BigQuery Standard SQL that loads data FROM one source table "
            "INTO multiple target tables. One statement per target table.\n\n"
            f"PROJECT.DATASET: `{project}.{dataset}`\n\n"
            f"SOURCE TABLE (type reference):\n{json.dumps(source_type_ref, separators=(',', ':'))}\n\n"
            f"TARGET TABLES (type reference):\n{json.dumps(target_type_ref, separators=(',', ':'))}\n\n"
            f"MAPPINGS (st=source table, sc=source col, tt=target table, tc=target col, type=mapping type, logic=business logic):\n"
            f"{json.dumps(slim_mappings, separators=(',', ':'))}\n\n"
            "Requirements:\n"
            "1. Group mappings by TARGET TABLE. For each target table that receives data, emit one statement.\n"
            f"2. Use MERGE `{project}.{dataset}.<target>` ... USING (SELECT ... FROM `{project}.{dataset}.<source>`) ... when the target has a clear primary key. Idempotent.\n"
            "3. If no natural key is obvious, fall back to CREATE OR REPLACE TABLE ... AS SELECT (full refresh).\n"
            f"4. Fully-qualify every table reference as `{project}.{dataset}.table_name`.\n"
            "5. Use CTEs for pre-aggregation when target rows are aggregates of source rows.\n"
            "6. Apply business logic exactly — type casts, date math, lookups (CASE for code -> label), hashing (TO_HEX(SHA256(...))), conditional logic.\n"
            "7. BigQuery type safety: SAFE_CAST, SAFE_DIVIDE, no TIMESTAMP/DATE direct comparison.\n"
            "8. Skip 'unused' rows.\n"
            "9. For target columns no mapping covers, omit them from the INSERT/UPDATE list.\n"
            "10. For 'constant' mappings, use the literal value directly.\n"
            "11. Add a header comment per target statement summarizing what's being loaded and from which source columns.\n\n"
            "Return ONLY a single fenced SQL block:\n\n"
            "```sql\n-- complete SQL here, one statement per target table\n```"
        )

        try:
            raw = ctx.llm.complete(prompt, system=SYSTEM, max_tokens=14000, temperature=0.0)
        except Exception as exc:
            return BlackboardDelta.failure(f"SQL LLM call failed: {exc}")

        sql = _extract_sql_block(raw)
        if not sql:
            return BlackboardDelta.failure("LLM returned no SQL")
        statements = _split_into_statements(sql)

        bundle = SqlBundle(
            project=project, dataset=dataset,
            statements=statements, combined_sql=sql,
            generated_at=datetime.now(timezone.utc), status=StageStatus.ready,
        )
        return BlackboardDelta(updates={"sql_bundle": bundle})


def _extract_sql_block(text: str) -> str:
    m = re.search(r"```(?:sql|SQL)?\s*\n([\s\S]*?)\n```", text)
    if m:
        return m.group(1).strip()
    return text.strip()


# Split SQL into individual statements at top-level semicolons.
# Tracks string literals, line comments, block comments, parentheses depth.
def _split_into_statements(sql: str) -> List[SqlStatement]:
    stmts: List[SqlStatement] = []
    i = 0
    start = 0
    depth = 0
    in_single = in_double = in_line = in_block = False
    while i < len(sql):
        c = sql[i]
        n = sql[i + 1] if i + 1 < len(sql) else ""
        if in_line:
            if c == "\n":
                in_line = False
            i += 1; continue
        if in_block:
            if c == "*" and n == "/":
                in_block = False; i += 2; continue
            i += 1; continue
        if in_single:
            if c == "'" and sql[i - 1:i] != "\\":
                in_single = False
            i += 1; continue
        if in_double:
            if c == '"' and sql[i - 1:i] != "\\":
                in_double = False
            i += 1; continue
        if c == "-" and n == "-":
            in_line = True; i += 2; continue
        if c == "/" and n == "*":
            in_block = True; i += 2; continue
        if c == "'":
            in_single = True; i += 1; continue
        if c == '"':
            in_double = True; i += 1; continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == ";" and depth == 0:
            chunk = sql[start:i + 1].strip()
            if chunk:
                stmts.append(_to_statement(chunk))
            start = i + 1
        i += 1
    tail = sql[start:].strip()
    if tail:
        stmts.append(_to_statement(tail))
    return stmts


_TABLE_PATTERNS = [
    re.compile(r"CREATE\s+OR\s+REPLACE\s+TABLE\s+`?[\w.-]+`?\.([\w]+)", re.IGNORECASE),
    re.compile(r"INSERT\s+INTO\s+`?[\w.-]+`?\.([\w]+)", re.IGNORECASE),
    re.compile(r"MERGE\s+(?:INTO\s+)?`?[\w.-]+`?\.([\w]+)", re.IGNORECASE),
    re.compile(r"CREATE\s+TABLE\s+`?[\w.-]+`?\.([\w]+)", re.IGNORECASE),
    re.compile(r"`[\w-]+\.[\w-]+\.([\w]+)`"),
]


def _to_statement(chunk: str) -> SqlStatement:
    table = ""
    for pat in _TABLE_PATTERNS:
        m = pat.search(chunk)
        if m:
            table = m.group(1); break
    header = ""
    for line in chunk.splitlines()[:6]:
        s = line.strip()
        if s.startswith("--"):
            header = s.lstrip("-").strip(); break
    return SqlStatement(target_table=table, sql=chunk, header_comment=header)
