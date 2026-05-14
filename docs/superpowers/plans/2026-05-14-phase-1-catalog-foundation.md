# Phase 1 — Catalog Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the catalog discovery layer — uploaded Databricks INFORMATION_SCHEMA xlsx becomes structured source catalogs in Postgres; live BigQuery INFORMATION_SCHEMA pulls become target catalogs; both are queryable via REST.

**Architecture:** Add a `core/catalog/` package with a format-agnostic parser (ported from the reference artifact's JS parser), a BQ refresh helper that reuses the existing `BQClient.list_columns_in_dataset` method, and a thin FastAPI router. Catalog data lives in the platform DB in 4 new tables (2 catalog headers + 2 per-table detail tables) using a normalized header with denormalized JSONB column lists. No L1/L2 wiring yet — that's Phase 2.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, openpyxl, pytest, pytest-asyncio. Existing `core/db/platform.py` async engine. Existing `BQClient` (`core/bq_client.py`).

**Non-goals for Phase 1:**
- `batches` table (Phase 2)
- `target_table_embeddings` table + pgvector extension (Phase 3)
- L1/L2 agents reading from catalog cache (Phase 2)
- AI fallback parser (heuristic-only for v1)
- Catalog versioning history (each refresh replaces the previous active catalog for a project/dataset)
- UI (Phase 4)

---

## File Structure

**Create:**
- `alembic/versions/c3d4e5f6a7b8_catalog_tables.py` — migration adding 4 catalog tables
- `core/models/catalog.py` — SQLAlchemy models for catalog tables (uses `PlatformBase`)
- `core/catalog/__init__.py` — public API surface
- `core/catalog/parser.py` — format-agnostic xlsx/csv parser (ported from mapping-agent.jsx)
- `core/catalog/persistence.py` — async DB read/write helpers
- `core/catalog/uploader.py` — orchestrates parse → persist for source uploads
- `core/catalog/bq_refresh.py` — pulls live BQ INFORMATION_SCHEMA → target catalog rows
- `routers/catalogs.py` — FastAPI router with upload + refresh + list endpoints
- `tests/test_catalog_parser.py` — parser unit tests (3 strategies + edge cases)
- `tests/test_catalog_persistence.py` — DB round-trip test
- `tests/test_catalog_bq_refresh.py` — BQ refresh test (mocked BQClient)
- `tests/test_catalogs_router.py` — router integration test with TestClient
- `tests/fixtures/catalog/device_activation_event_source.xlsx` — copy of user-provided source fixture
- `tests/fixtures/catalog/target_information_schema.xlsx` — copy of user-provided target fixture

**Modify:**
- `app.py` — register new `routers/catalogs.py`
- `requirements.txt` — add `openpyxl` (if not already pinned)

**Reference (do not modify):**
- `~/Downloads/Mapping Agent Mock Up/mapping-agent.jsx` lines 74-310 — JS parser logic to port
- `core/bq_client.py` — already has `list_columns_in_dataset(dataset)`
- `alembic/versions/b1c2d3e4f5a6_mapping_memory.py` — migration style reference
- `routers/stm_memory.py` — router style reference

---

## Task 1: Copy test fixtures into the repo

**Files:**
- Create: `tests/fixtures/catalog/device_activation_event_source.xlsx`
- Create: `tests/fixtures/catalog/target_information_schema.xlsx`

- [ ] **Step 1: Create the fixtures directory and copy the user-provided xlsx files**

```bash
mkdir -p tests/fixtures/catalog
cp "$HOME/Downloads/Mapping Agent Mock Up/device_activation_event_source.xlsx" \
   tests/fixtures/catalog/device_activation_event_source.xlsx
cp "$HOME/Downloads/Mapping Agent Mock Up/Target Information Schema.xlsx" \
   tests/fixtures/catalog/target_information_schema.xlsx
```

- [ ] **Step 2: Verify both fixtures exist and are non-empty**

Run: `ls -la tests/fixtures/catalog/`
Expected: Two files listed, both with non-zero size (typically 10–60 KB each).

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/catalog/
git commit -m "test: add user-provided xlsx fixtures for catalog parser tests"
```

---

## Task 2: Alembic migration for catalog tables

**Files:**
- Create: `alembic/versions/c3d4e5f6a7b8_catalog_tables.py`

- [ ] **Step 1: Write the migration file**

```python
"""catalog_tables

Phase 1 of the enterprise mapping refactor — adds 4 tables:
  catalogs_source        — header row per uploaded Databricks dump
  catalog_source_tables  — one row per source table (with columns_json blob)
  catalogs_target        — header row per BigQuery dataset snapshot
  catalog_target_tables  — one row per target table (with columns_json blob)

Catalog data is stored normalized at the table level but JSONB at the column
level — L2/L3 always read the whole catalog at once, so column-level rows
would add joins without query benefit. Phase 3 will add an embeddings table
that FKs to catalog_target_tables.id.

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalogs_source",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("catalog_name", sa.String(255), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),  # "databricks_upload"
        sa.Column("raw_filename", sa.String(512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),  # active|archived
        sa.Column("table_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_catalogs_source_tenant_status", "catalogs_source", ["tenant_id", "status"])

    op.create_table(
        "catalog_source_tables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("catalog_id", sa.String(36), sa.ForeignKey("catalogs_source.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(255), nullable=True),
        sa.Column("catalog", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("columns_json", sa.Text(), nullable=False),  # JSON array of {name,type,description,is_nullable,ordinal}
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_source_tables_catalog", "catalog_source_tables", ["catalog_id"])
    op.create_index("idx_source_tables_lookup", "catalog_source_tables", ["catalog_id", "schema_name", "table_name"])

    op.create_table(
        "catalogs_target",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("project", sa.String(128), nullable=False),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("target_kind", sa.String(32), nullable=False, server_default="bigquery_live"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),  # active|archived
        sa.Column("table_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_catalogs_target_tenant", "catalogs_target", ["tenant_id", "status"])
    op.create_index("idx_catalogs_target_lookup", "catalogs_target", ["tenant_id", "project", "dataset", "status"])

    op.create_table(
        "catalog_target_tables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("catalog_id", sa.String(36), sa.ForeignKey("catalogs_target.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("columns_json", sa.Text(), nullable=False),  # JSON array of {name,type,description,is_nullable,ordinal}
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_target_tables_catalog", "catalog_target_tables", ["catalog_id"])
    op.create_index("idx_target_tables_lookup", "catalog_target_tables", ["catalog_id", "table_name"])


def downgrade() -> None:
    op.drop_index("idx_target_tables_lookup", table_name="catalog_target_tables")
    op.drop_index("idx_target_tables_catalog", table_name="catalog_target_tables")
    op.drop_table("catalog_target_tables")

    op.drop_index("idx_catalogs_target_lookup", table_name="catalogs_target")
    op.drop_index("idx_catalogs_target_tenant", table_name="catalogs_target")
    op.drop_table("catalogs_target")

    op.drop_index("idx_source_tables_lookup", table_name="catalog_source_tables")
    op.drop_index("idx_source_tables_catalog", table_name="catalog_source_tables")
    op.drop_table("catalog_source_tables")

    op.drop_index("idx_catalogs_source_tenant_status", table_name="catalogs_source")
    op.drop_table("catalogs_source")
```

- [ ] **Step 2: Run the migration**

Run: `docker compose exec api alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade b1c2d3e4f5a6 -> c3d4e5f6a7b8, catalog_tables`

- [ ] **Step 3: Verify tables exist**

Run:
```bash
docker compose exec api python3 -c "
import asyncio
from sqlalchemy import text
from core.db.platform import get_engine
async def go():
    eng = get_engine()
    async with eng.connect() as conn:
        for t in ['catalogs_source','catalog_source_tables','catalogs_target','catalog_target_tables']:
            r = await conn.execute(text(f'SELECT COUNT(*) FROM {t}'))
            print(t, '=', r.scalar())
asyncio.run(go())
"
```
Expected: each line prints `<table> = 0`.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/c3d4e5f6a7b8_catalog_tables.py
git commit -m "feat(catalog): alembic migration for 4 catalog tables"
```

---

## Task 3: SQLAlchemy models

**Files:**
- Create: `core/models/catalog.py`

- [ ] **Step 1: Write the models**

Note: the Unity-Catalog "catalog" namespace stored on a Databricks table is held in a column named `unity_catalog` (not `catalog`) to avoid collision with the SQLAlchemy `relationship()` attribute. The migration in Task 2 uses `sa.Column("catalog", sa.String(255), ...)` — update it now to match by renaming that column to `unity_catalog` before continuing.

Edit `alembic/versions/c3d4e5f6a7b8_catalog_tables.py`: replace `sa.Column("catalog", sa.String(255), nullable=True)` with `sa.Column("unity_catalog", sa.String(255), nullable=True)`. Then drop and recreate the schema:

```bash
docker compose exec api alembic downgrade b1c2d3e4f5a6
docker compose exec api alembic upgrade head
```

Now write the models:

```python
"""SQLAlchemy models for the catalog package — mirrors the c3d4e5f6a7b8 migration."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from core.models.platform import PlatformBase


class CatalogSource(PlatformBase):
    __tablename__ = "catalogs_source"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="default")
    catalog_name = Column(String(255), nullable=False)
    source_kind = Column(String(32), nullable=False)
    raw_filename = Column(String(512), nullable=True)
    description = Column(Text(), nullable=True)
    status = Column(String(16), nullable=False, default="active")
    table_count = Column(Integer(), nullable=False, default=0)
    column_count = Column(Integer(), nullable=False, default=0)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(), nullable=False, default=datetime.utcnow)

    tables = relationship("CatalogSourceTable", back_populates="catalog", cascade="all, delete-orphan")


class CatalogSourceTable(PlatformBase):
    __tablename__ = "catalog_source_tables"

    id = Column(String(36), primary_key=True)
    catalog_id = Column(String(36), ForeignKey("catalogs_source.id", ondelete="CASCADE"), nullable=False)
    table_name = Column(String(255), nullable=False)
    schema_name = Column(String(255), nullable=True)
    unity_catalog = Column(String(255), nullable=True)
    description = Column(Text(), nullable=True)
    column_count = Column(Integer(), nullable=False, default=0)
    columns_json = Column(Text(), nullable=False)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)

    catalog = relationship("CatalogSource", back_populates="tables")


class CatalogTarget(PlatformBase):
    __tablename__ = "catalogs_target"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="default")
    project = Column(String(128), nullable=False)
    dataset = Column(String(128), nullable=False)
    target_kind = Column(String(32), nullable=False, default="bigquery_live")
    status = Column(String(16), nullable=False, default="active")
    table_count = Column(Integer(), nullable=False, default=0)
    column_count = Column(Integer(), nullable=False, default=0)
    fetched_at = Column(DateTime(), nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(), nullable=False, default=datetime.utcnow)

    tables = relationship("CatalogTargetTable", back_populates="catalog", cascade="all, delete-orphan")


class CatalogTargetTable(PlatformBase):
    __tablename__ = "catalog_target_tables"

    id = Column(String(36), primary_key=True)
    catalog_id = Column(String(36), ForeignKey("catalogs_target.id", ondelete="CASCADE"), nullable=False)
    table_name = Column(String(255), nullable=False)
    description = Column(Text(), nullable=True)
    column_count = Column(Integer(), nullable=False, default=0)
    columns_json = Column(Text(), nullable=False)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)

    catalog = relationship("CatalogTarget", back_populates="tables")
```

- [ ] **Step 2: Verify models import cleanly**

Run: `docker compose exec api python3 -c "from core.models.catalog import CatalogSource, CatalogSourceTable, CatalogTarget, CatalogTargetTable; print('OK', [c.__tablename__ for c in [CatalogSource, CatalogSourceTable, CatalogTarget, CatalogTargetTable]])"`
Expected: `OK ['catalogs_source', 'catalog_source_tables', 'catalogs_target', 'catalog_target_tables']`

- [ ] **Step 3: Commit**

```bash
git add core/models/catalog.py
git commit -m "feat(catalog): SQLAlchemy models for catalog tables"
```

---

## Task 4: Parser — data structures and strategy 0 (data-sample detection)

The reference parser at `~/Downloads/Mapping Agent Mock Up/mapping-agent.jsx` lines 144–310 has three strategies. We port them one at a time, TDD-style.

**Strategy 0:** File looks like an actual data sample — header row + many data rows, no table_name column. The headers ARE the column names. Example: `device_activation_event_source.xlsx` has 44 columns in the header row, then sample rows below.

**Files:**
- Create: `core/catalog/__init__.py`
- Create: `core/catalog/parser.py`
- Create: `tests/test_catalog_parser.py`

- [ ] **Step 1: Write the failing test (data-sample detection)**

```python
# tests/test_catalog_parser.py
"""Parser tests — ported from mapping-agent.jsx tryFastParse strategies."""
from pathlib import Path

import pytest

from core.catalog.parser import ParsedTable, parse_schema_file


FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


def test_strategy_0_data_sample_uses_headers_as_columns():
    """device_activation_event_source.xlsx: 1 sheet with 44 column headers + data rows.
    Strategy 0 should detect data-sample mode and treat headers as the column list.
    """
    result = parse_schema_file(FIXTURES / "device_activation_event_source.xlsx")
    assert len(result.tables) == 1
    t = result.tables[0]
    assert t.table_name == "device_activation_event"
    assert t.column_count == 44
    assert len(t.columns) == 44
    # First column should be one of the canonical names from the sample
    assert any(c["name"] for c in t.columns)
    # Types should have been inferred from data rows (not all 'string')
    types = {c.get("type") for c in t.columns}
    assert len(types) > 1, f"All columns inferred as same type — type inference failing: {types}"
```

- [ ] **Step 2: Run test — should fail because parser doesn't exist yet**

Run: `docker compose exec api pytest tests/test_catalog_parser.py::test_strategy_0_data_sample_uses_headers_as_columns -v`
Expected: `ImportError: cannot import name 'parse_schema_file' from 'core.catalog.parser'`

- [ ] **Step 3: Write the parser module — strategy 0 only**

```python
# core/catalog/__init__.py
"""Catalog package — schema discovery, parsing, persistence."""
from core.catalog.parser import ParsedColumn, ParsedTable, ParsedSchema, parse_schema_file

__all__ = ["ParsedColumn", "ParsedTable", "ParsedSchema", "parse_schema_file"]
```

```python
# core/catalog/parser.py
"""Format-agnostic schema file parser.

Ported from the reference artifact's JS parser
(~/Downloads/Mapping Agent Mock Up/mapping-agent.jsx, lines 74-310).
Three detection strategies, run in priority order:

  Strategy 0  Data sample: header row + many data rows, no table_name column.
              Headers ARE the columns. Types inferred from first ~20 rows.
  Strategy 1  Schema dump: explicit table_name + column_name columns
              (one row per column).
  Strategy 2  Workbook: one sheet per table.

If all three fail, raises ParserError. No AI fallback in this phase.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import openpyxl


# ── Type inference constants ────────────────────────────────────────────────

_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


# ── Public data structures ──────────────────────────────────────────────────

ParsedColumn = Dict[str, Any]  # {"name": str, "type": str, "description": Optional[str], "ordinal": int}


@dataclass
class ParsedTable:
    table_name: str
    schema_name: Optional[str] = None
    catalog: Optional[str] = None
    description: Optional[str] = None
    columns: List[ParsedColumn] = field(default_factory=list)

    @property
    def column_count(self) -> int:
        return len(self.columns)


@dataclass
class ParsedSchema:
    tables: List[ParsedTable]
    strategy: str  # which strategy succeeded


class ParserError(ValueError):
    """Raised when no strategy can parse the file."""


# ── Header normalization (matches JS norm() at line 80) ─────────────────────

def _norm(s: Any) -> str:
    return re.sub(r"[\s_\-]+", "", str(s or "").lower().strip())


TABLE_KEYS = ["table", "tablename", "table_name", "tbl", "entity", "entity_name",
              "source_table", "target_table", "object_name"]
COLUMN_KEYS = ["column", "columnname", "column_name", "col", "col_name", "field",
               "field_name", "attribute", "columns", "fields"]
TYPE_KEYS = ["type", "datatype", "data_type", "column_type", "field_type",
             "sql_type", "bq_type"]
DESC_KEYS = ["description", "desc", "comment", "comments", "notes", "definition",
             "remarks", "doc"]


def _match_key(headers: List[Any], candidates: List[str]) -> int:
    """Return index of first matching header, or -1 if none. Exact first, then substring."""
    n = [_norm(h) for h in headers]
    c = [_norm(x) for x in candidates]
    for x in c:
        if x in n:
            return n.index(x)
    for x in c:
        for i, h in enumerate(n):
            if x in h:
                return i
    return -1


# ── Type inference (matches JS inferType() at ~line 200) ────────────────────

def _infer_column_type(values: List[Any]) -> str:
    """Inspect up to 20 values, return a single canonical type string."""
    sample = [v for v in values[:20] if v not in (None, "", "NaN")]
    if not sample:
        return "string"

    all_int = True
    all_float = True
    all_date = True
    all_datetime = True
    all_bool = True

    for v in sample:
        s = str(v).strip()
        if isinstance(v, (int,)) and not isinstance(v, bool):
            all_float = False  # int doesn't imply float
            all_date = all_datetime = all_bool = False
            continue
        if isinstance(v, float):
            all_int = False
            all_date = all_datetime = all_bool = False
            continue
        if isinstance(v, bool):
            all_int = all_float = all_date = all_datetime = False
            continue
        if isinstance(v, datetime):
            all_int = all_float = all_date = all_bool = False
            continue
        if isinstance(v, date):
            all_int = all_float = all_datetime = all_bool = False
            continue
        # string fallback — try regexes
        if not _INT_RE.match(s):
            all_int = False
        if not _FLOAT_RE.match(s):
            all_float = False
        if not _DATETIME_RE.match(s):
            all_datetime = False
        if not _DATE_RE.match(s):
            all_date = False
        if s.lower() not in ("true", "false", "0", "1"):
            all_bool = False

    if all_datetime:
        return "timestamp"
    if all_date:
        return "date"
    if all_int:
        return "integer"
    if all_float:
        return "float"
    if all_bool:
        return "boolean"
    return "string"


# ── File reading ─────────────────────────────────────────────────────────────

def _read_xlsx(path: Path) -> List[Dict[str, List[List[Any]]]]:
    """Return list of {name, rows2D}, one per sheet."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for name in wb.sheetnames:
        ws = wb[name]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        out.append({"name": name, "rows2D": rows})
    wb.close()
    return out


# ── Strategy 0: data sample ─────────────────────────────────────────────────

def _try_strategy_0(sheets: List[Dict[str, Any]]) -> Optional[List[ParsedTable]]:
    """Headers ARE column names; rows below are data records.

    Detection criteria (mirrors JS lines 168-195):
      1. NO `table_name`-style header column, AND
      2. ≥ 5 data rows, AND
      3. First column's values are mostly distinct (not table-name grouping),
         AND
      4. Header values look like column identifiers (snake_case-ish, ≥2 headers).
    """
    tables: List[ParsedTable] = []
    for sheet in sheets:
        rows = sheet["rows2D"]
        if len(rows) < 6:  # header + 5 data rows minimum
            continue
        headers = rows[0]
        if len(headers) < 2:
            continue

        # Reject if a table_name-style header exists — that's a schema file (strategy 1).
        if _match_key(list(headers), TABLE_KEYS) != -1:
            return None

        # Check distinctness of first column (mostly distinct → data sample).
        first_col_vals = [r[0] for r in rows[1:] if len(r) > 0]
        if not first_col_vals:
            continue
        non_null = [v for v in first_col_vals if v not in (None, "")]
        if not non_null:
            continue
        distinct_ratio = len(set(non_null)) / max(len(non_null), 1)
        if distinct_ratio < 0.7:
            # Probably (table_name, column_name) grouping — strategy 1.
            return None

        # Header sanity — at least 2 identifier-looking headers.
        ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        ident_headers = [str(h).strip() for h in headers if h and ident_re.match(str(h).strip())]
        if len(ident_headers) < 2:
            continue

        # Build columns with inferred types.
        cols: List[ParsedColumn] = []
        for idx, h in enumerate(headers):
            if not h:
                continue
            col_vals = [r[idx] if idx < len(r) else None for r in rows[1:]]
            cols.append({
                "name": str(h).strip(),
                "type": _infer_column_type(col_vals),
                "description": None,
                "ordinal": idx,
            })

        # Table name: prefer the sheet name unless generic.
        name = sheet["name"]
        if name.lower() in ("sheet1", "sheet", "(csv)"):
            # Fall back to first identifier in the file name (handled by uploader).
            name = "unknown_table"
        tables.append(ParsedTable(table_name=name, columns=cols))

    return tables or None


# ── Main entrypoint ─────────────────────────────────────────────────────────

def parse_schema_file(path: Path) -> ParsedSchema:
    """Parse an xlsx/csv schema or sample file. Raises ParserError on failure."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls", ".xlsm"):
        sheets = _read_xlsx(path)
    else:
        raise ParserError(f"Unsupported extension {suffix} — only .xlsx for v1")

    # Strategy 0
    s0 = _try_strategy_0(sheets)
    if s0:
        # Replace 'unknown_table' with the file stem if needed.
        for t in s0:
            if t.table_name == "unknown_table":
                t.table_name = path.stem.replace("_source", "").replace("_sample", "")
        return ParsedSchema(tables=s0, strategy="data_sample")

    # Strategies 1 & 2 — added in subsequent tasks.
    raise ParserError(
        f"No strategy matched {path.name}. Strategies 1 (schema dump) and 2 "
        f"(workbook-per-table) are added in later tasks."
    )
```

- [ ] **Step 4: Run test — should pass**

Run: `docker compose exec api pytest tests/test_catalog_parser.py::test_strategy_0_data_sample_uses_headers_as_columns -v`
Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add core/catalog/__init__.py core/catalog/parser.py tests/test_catalog_parser.py
git commit -m "feat(catalog): parser strategy 0 — data sample detection with type inference"
```

---

## Task 5: Parser — strategy 1 (table_name + column_name schema dump)

**Strategy 1:** File has `table_name` + `column_name` columns (plus optional `data_type`, `description`). One row per column. This matches the user-provided `Target Information Schema.xlsx`, which is the output of:

```sql
SELECT table_name, STRING_AGG(column_name, ', ' ORDER BY ordinal_position) AS columns,
       COUNT(*) AS column_count
FROM `vz-agentic-198889.buildemo.INFORMATION_SCHEMA.COLUMNS`
GROUP BY table_name
ORDER BY table_name;
```

Each row carries `table_name + comma-separated column list`. Strategy 1 must handle BOTH shapes:
- **1a — flat schema:** one row per column with `column_name` column
- **1b — comma-aggregated:** one row per table with a `columns` column containing CSV column names

**Files:**
- Modify: `core/catalog/parser.py`
- Modify: `tests/test_catalog_parser.py`

- [ ] **Step 1: Write the failing tests for both 1a and 1b shapes**

```python
# Append to tests/test_catalog_parser.py


def test_strategy_1b_string_agg_schema_dump():
    """Target Information Schema.xlsx: one row per table, with column_name CSV-aggregated.
    Header has table_name + columns (or column_name) + column_count.
    """
    result = parse_schema_file(FIXTURES / "target_information_schema.xlsx")
    # Per the artifact screenshot, this file has 11 tables, 255 columns total.
    assert len(result.tables) == 11
    total_cols = sum(t.column_count for t in result.tables)
    assert total_cols == 255

    # Spot-check known tables from the screenshot.
    names = {t.table_name for t in result.tables}
    assert "billing_invoice" in names
    assert "customer_account_profile" in names
    assert "network_outage_event" in names

    # Verify column counts on a few from the screenshot.
    by_name = {t.table_name: t for t in result.tables}
    assert by_name["billing_invoice"].column_count == 24
    assert by_name["customer_account_profile"].column_count == 24
    assert by_name["network_outage_event"].column_count == 23
```

- [ ] **Step 2: Run test — should fail with ParserError**

Run: `docker compose exec api pytest tests/test_catalog_parser.py::test_strategy_1b_string_agg_schema_dump -v`
Expected: FAIL with `ParserError: No strategy matched...`

- [ ] **Step 3: Add `_try_strategy_1` and `_split_column_list` to parser.py**

Add after the strategy 0 function:

```python
# ── Column-list splitting (matches JS splitColumnList at ~line 90) ──────────

def _split_column_list(raw: Any) -> List[str]:
    """Split a comma/newline/pipe/semicolon-delimited column list into parts."""
    s = str(raw or "").strip()
    if not s:
        return []
    # JSON array?
    if s.startswith("["):
        try:
            import json
            arr = json.loads(s)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except ValueError:
            pass
    # Try newline first, then comma/semicolon/pipe. Best split = most parts.
    best = [s]
    for sep_re in (re.compile(r"\r?\n"), re.compile(r"\s*[,;|]\s*")):
        parts = [p.strip() for p in sep_re.split(s) if p.strip()]
        if len(parts) > len(best):
            best = parts
    return best


# ── Strategy 1: explicit schema dump ────────────────────────────────────────

def _try_strategy_1(sheets: List[Dict[str, Any]]) -> Optional[List[ParsedTable]]:
    """Schema-dump file with table_name + column information.

    1a — one row per column: header has table_name AND column_name.
    1b — one row per table: header has table_name AND a list column (`columns`,
         `column_name`, `fields`...). The list column carries CSV-aggregated names.
    """
    for sheet in sheets:
        rows = sheet["rows2D"]
        if not rows:
            continue
        headers = list(rows[0])
        ti = _match_key(headers, TABLE_KEYS)
        ci = _match_key(headers, COLUMN_KEYS)
        if ti == -1 or ci == -1:
            continue
        ty = _match_key(headers, TYPE_KEYS)
        ds = _match_key(headers, DESC_KEYS)

        # Decide 1a vs 1b: peek at the column-name cell of the first data row.
        # If it contains a delimiter (comma/newline) and there's only one row
        # per (table_name) value, it's 1b.
        body = rows[1:]
        if not body:
            continue

        # Group by table.
        per_table: Dict[str, List[Dict[str, Any]]] = {}
        for r in body:
            if ti >= len(r):
                continue
            tname = r[ti]
            if not tname:
                continue
            tname = str(tname).strip()
            col_cell = r[ci] if ci < len(r) else ""
            type_cell = r[ty] if ty != -1 and ty < len(r) else None
            desc_cell = r[ds] if ds != -1 and ds < len(r) else None

            # Detect 1b: cell contains a delimiter and >1 token after split.
            parts = _split_column_list(col_cell)
            if len(parts) > 1:
                # 1b — explode the CSV into one entry per column.
                for ord_i, p in enumerate(parts):
                    per_table.setdefault(tname, []).append({
                        "name": p, "type": None, "description": None, "ordinal": ord_i,
                    })
            else:
                per_table.setdefault(tname, []).append({
                    "name": str(col_cell).strip(),
                    "type": str(type_cell).strip() if type_cell else None,
                    "description": str(desc_cell).strip() if desc_cell else None,
                    "ordinal": len(per_table.get(tname, [])),
                })

        if not per_table:
            continue
        return [ParsedTable(table_name=tname, columns=cols) for tname, cols in per_table.items()]
    return None
```

Then in `parse_schema_file`, add strategy 1 between strategy 0 and the fallback:

```python
    # Strategy 1
    s1 = _try_strategy_1(sheets)
    if s1:
        return ParsedSchema(tables=s1, strategy="schema_dump")
```

- [ ] **Step 4: Run both parser tests — should pass**

Run: `docker compose exec api pytest tests/test_catalog_parser.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/catalog/parser.py tests/test_catalog_parser.py
git commit -m "feat(catalog): parser strategy 1 — schema dump (flat + CSV-aggregated)"
```

---

## Task 6: Parser — strategy 2 (workbook with one sheet per table) + final fallback

**Strategy 2:** workbook where each sheet is one table. Each sheet's first row is column headers; we use _strategy 1_-style header detection inside each sheet, OR fall back to "first column = column name" if the sheet has only column-level data (no table_name).

**Files:**
- Modify: `core/catalog/parser.py`
- Modify: `tests/test_catalog_parser.py`

- [ ] **Step 1: Write a failing test for strategy 2 using a synthetic xlsx**

```python
# Append to tests/test_catalog_parser.py


def test_strategy_2_workbook_per_table(tmp_path):
    """Synthetic workbook: 2 sheets, each a table with column rows."""
    import openpyxl
    wb = openpyxl.Workbook()
    s1 = wb.active
    s1.title = "orders"
    s1.append(["column_name", "data_type", "description"])
    s1.append(["order_id", "STRING", "PK"])
    s1.append(["amount", "FLOAT64", "USD"])
    s2 = wb.create_sheet("customers")
    s2.append(["column_name", "data_type", "description"])
    s2.append(["customer_id", "STRING", "PK"])
    s2.append(["email", "STRING", None])
    s2.append(["created_at", "TIMESTAMP", None])

    path = tmp_path / "workbook.xlsx"
    wb.save(path)

    result = parse_schema_file(path)
    assert result.strategy == "workbook_per_table"
    by_name = {t.table_name: t for t in result.tables}
    assert set(by_name.keys()) == {"orders", "customers"}
    assert by_name["orders"].column_count == 2
    assert by_name["customers"].column_count == 3
    assert by_name["orders"].columns[0]["name"] == "order_id"
    assert by_name["orders"].columns[0]["type"] == "STRING"
```

- [ ] **Step 2: Run test — should fail**

Run: `docker compose exec api pytest tests/test_catalog_parser.py::test_strategy_2_workbook_per_table -v`
Expected: FAIL with `ParserError`.

- [ ] **Step 3: Add `_try_strategy_2` to parser.py**

```python
# Add after _try_strategy_1

# ── Strategy 2: workbook, one sheet per table ───────────────────────────────

def _try_strategy_2(sheets: List[Dict[str, Any]]) -> Optional[List[ParsedTable]]:
    """Each sheet is a table; the sheet's first row is the column-level header.

    Inside a sheet, header must include a column_name-style header
    (no table_name header — that would belong to strategy 1).
    """
    tables: List[ParsedTable] = []
    for sheet in sheets:
        rows = sheet["rows2D"]
        if len(rows) < 2:
            continue
        headers = list(rows[0])
        # If table_name header is present, this is strategy 1 territory; skip.
        if _match_key(headers, TABLE_KEYS) != -1:
            continue
        ci = _match_key(headers, COLUMN_KEYS)
        if ci == -1:
            continue
        ty = _match_key(headers, TYPE_KEYS)
        ds = _match_key(headers, DESC_KEYS)

        cols: List[ParsedColumn] = []
        for ord_i, r in enumerate(rows[1:]):
            if ci >= len(r):
                continue
            name = r[ci]
            if not name:
                continue
            cols.append({
                "name": str(name).strip(),
                "type": str(r[ty]).strip() if ty != -1 and ty < len(r) and r[ty] else None,
                "description": str(r[ds]).strip() if ds != -1 and ds < len(r) and r[ds] else None,
                "ordinal": ord_i,
            })
        if cols:
            tables.append(ParsedTable(table_name=sheet["name"], columns=cols))
    return tables or None
```

In `parse_schema_file`, add strategy 2 before the fallback:

```python
    # Strategy 2
    s2 = _try_strategy_2(sheets)
    if s2:
        return ParsedSchema(tables=s2, strategy="workbook_per_table")
```

Update the final ParserError message:

```python
    raise ParserError(
        f"No strategy matched {path.name}. Tried: data_sample, schema_dump, workbook_per_table."
    )
```

- [ ] **Step 4: Run all parser tests**

Run: `docker compose exec api pytest tests/test_catalog_parser.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/catalog/parser.py tests/test_catalog_parser.py
git commit -m "feat(catalog): parser strategy 2 — workbook with one sheet per table"
```

---

## Task 7: Catalog persistence — save uploaded source catalog to DB

**Files:**
- Create: `core/catalog/persistence.py`
- Create: `tests/test_catalog_persistence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_persistence.py
"""Persistence round-trip tests for catalogs."""
import json
import uuid
from datetime import datetime

import pytest

from core.catalog.parser import ParsedColumn, ParsedSchema, ParsedTable
from core.catalog.persistence import (
    save_source_catalog, list_source_catalogs, load_source_catalog,
)


@pytest.mark.asyncio
async def test_save_and_list_source_catalog():
    schema = ParsedSchema(
        tables=[
            ParsedTable(
                table_name="orders",
                columns=[
                    {"name": "order_id", "type": "string", "description": None, "ordinal": 0},
                    {"name": "amount", "type": "float", "description": None, "ordinal": 1},
                ],
            ),
            ParsedTable(
                table_name="customers",
                columns=[
                    {"name": "customer_id", "type": "string", "description": None, "ordinal": 0},
                ],
            ),
        ],
        strategy="schema_dump",
    )

    catalog_id = await save_source_catalog(
        tenant_id="default",
        catalog_name="frontier_test_" + uuid.uuid4().hex[:8],
        source_kind="databricks_upload",
        raw_filename="test.xlsx",
        description="round-trip test",
        schema=schema,
    )

    rows = await list_source_catalogs(tenant_id="default")
    assert any(r["id"] == catalog_id for r in rows)

    loaded = await load_source_catalog(catalog_id)
    assert loaded["table_count"] == 2
    assert loaded["column_count"] == 3
    names = {t["table_name"] for t in loaded["tables"]}
    assert names == {"orders", "customers"}
    orders = next(t for t in loaded["tables"] if t["table_name"] == "orders")
    assert orders["columns"][0]["name"] == "order_id"
    assert orders["columns"][0]["type"] == "string"
```

- [ ] **Step 2: Run test — should fail with import error**

Run: `docker compose exec api pytest tests/test_catalog_persistence.py -v`
Expected: `ImportError: cannot import name 'save_source_catalog' from 'core.catalog.persistence'`

- [ ] **Step 3: Write persistence.py**

```python
# core/catalog/persistence.py
"""Async DB read/write helpers for catalogs.

Source catalog write replaces any existing 'active' catalog with the same
(tenant_id, catalog_name) — old rows are marked 'archived' but kept for audit.
Target catalog write replaces any existing 'active' catalog for the same
(tenant_id, project, dataset).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from core.catalog.parser import ParsedSchema
from core.db.platform import get_platform_session_factory
from core.models.catalog import (
    CatalogSource, CatalogSourceTable, CatalogTarget, CatalogTargetTable,
)


# ── Source catalog writes ───────────────────────────────────────────────────

async def save_source_catalog(
    *,
    tenant_id: str,
    catalog_name: str,
    source_kind: str,
    raw_filename: Optional[str],
    description: Optional[str],
    schema: ParsedSchema,
) -> str:
    """Persist a parsed source schema. Archives any prior active catalog with
    the same (tenant_id, catalog_name). Returns new catalog_id (uuid).
    """
    factory = get_platform_session_factory()
    now = datetime.utcnow()
    catalog_id = str(uuid.uuid4())
    table_count = len(schema.tables)
    column_count = sum(len(t.columns) for t in schema.tables)

    async with factory() as session:
        # Archive prior actives with the same name.
        await session.execute(
            update(CatalogSource)
            .where(
                CatalogSource.tenant_id == tenant_id,
                CatalogSource.catalog_name == catalog_name,
                CatalogSource.status == "active",
            )
            .values(status="archived", updated_at=now)
        )

        cat = CatalogSource(
            id=catalog_id,
            tenant_id=tenant_id,
            catalog_name=catalog_name,
            source_kind=source_kind,
            raw_filename=raw_filename,
            description=description,
            status="active",
            table_count=table_count,
            column_count=column_count,
            created_at=now,
            updated_at=now,
        )
        session.add(cat)

        for t in schema.tables:
            session.add(CatalogSourceTable(
                id=str(uuid.uuid4()),
                catalog_id=catalog_id,
                table_name=t.table_name,
                schema_name=t.schema_name,
                unity_catalog=t.catalog,
                description=t.description,
                column_count=len(t.columns),
                columns_json=json.dumps(t.columns),
                created_at=now,
            ))

        await session.commit()

    return catalog_id


# ── Source catalog reads ────────────────────────────────────────────────────

async def list_source_catalogs(*, tenant_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
    factory = get_platform_session_factory()
    async with factory() as session:
        stmt = select(CatalogSource).where(CatalogSource.tenant_id == tenant_id)
        if not include_archived:
            stmt = stmt.where(CatalogSource.status == "active")
        stmt = stmt.order_by(CatalogSource.created_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "catalog_name": r.catalog_name,
            "source_kind": r.source_kind,
            "raw_filename": r.raw_filename,
            "description": r.description,
            "status": r.status,
            "table_count": r.table_count,
            "column_count": r.column_count,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


async def load_source_catalog(catalog_id: str) -> Dict[str, Any]:
    """Return the full catalog with tables + columns (columns parsed from JSON)."""
    factory = get_platform_session_factory()
    async with factory() as session:
        cat = (await session.execute(
            select(CatalogSource).where(CatalogSource.id == catalog_id)
        )).scalar_one_or_none()
        if cat is None:
            raise KeyError(f"Source catalog {catalog_id} not found")

        tbls = (await session.execute(
            select(CatalogSourceTable).where(CatalogSourceTable.catalog_id == catalog_id)
        )).scalars().all()

    return {
        "id": cat.id,
        "tenant_id": cat.tenant_id,
        "catalog_name": cat.catalog_name,
        "source_kind": cat.source_kind,
        "raw_filename": cat.raw_filename,
        "description": cat.description,
        "status": cat.status,
        "table_count": cat.table_count,
        "column_count": cat.column_count,
        "created_at": cat.created_at.isoformat(),
        "updated_at": cat.updated_at.isoformat(),
        "tables": [
            {
                "id": t.id,
                "table_name": t.table_name,
                "schema_name": t.schema_name,
                "unity_catalog": t.unity_catalog,
                "description": t.description,
                "column_count": t.column_count,
                "columns": json.loads(t.columns_json),
            }
            for t in tbls
        ],
    }


# ── Target catalog writes ───────────────────────────────────────────────────

async def save_target_catalog(
    *,
    tenant_id: str,
    project: str,
    dataset: str,
    tables: List[Dict[str, Any]],  # [{table_name, description, columns:[{name,type,...}]}]
) -> str:
    """Persist a target catalog snapshot. Archives prior active catalog for
    the same (tenant_id, project, dataset). Returns new catalog_id.
    """
    factory = get_platform_session_factory()
    now = datetime.utcnow()
    catalog_id = str(uuid.uuid4())
    table_count = len(tables)
    column_count = sum(len(t.get("columns", [])) for t in tables)

    async with factory() as session:
        await session.execute(
            update(CatalogTarget)
            .where(
                CatalogTarget.tenant_id == tenant_id,
                CatalogTarget.project == project,
                CatalogTarget.dataset == dataset,
                CatalogTarget.status == "active",
            )
            .values(status="archived", updated_at=now)
        )

        cat = CatalogTarget(
            id=catalog_id,
            tenant_id=tenant_id,
            project=project,
            dataset=dataset,
            target_kind="bigquery_live",
            status="active",
            table_count=table_count,
            column_count=column_count,
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(cat)

        for t in tables:
            cols = t.get("columns", [])
            session.add(CatalogTargetTable(
                id=str(uuid.uuid4()),
                catalog_id=catalog_id,
                table_name=t["table_name"],
                description=t.get("description"),
                column_count=len(cols),
                columns_json=json.dumps(cols),
                created_at=now,
            ))

        await session.commit()
    return catalog_id


async def list_target_catalogs(*, tenant_id: str, include_archived: bool = False) -> List[Dict[str, Any]]:
    factory = get_platform_session_factory()
    async with factory() as session:
        stmt = select(CatalogTarget).where(CatalogTarget.tenant_id == tenant_id)
        if not include_archived:
            stmt = stmt.where(CatalogTarget.status == "active")
        stmt = stmt.order_by(CatalogTarget.fetched_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "project": r.project,
            "dataset": r.dataset,
            "target_kind": r.target_kind,
            "status": r.status,
            "table_count": r.table_count,
            "column_count": r.column_count,
            "fetched_at": r.fetched_at.isoformat(),
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


async def load_target_catalog(catalog_id: str) -> Dict[str, Any]:
    factory = get_platform_session_factory()
    async with factory() as session:
        cat = (await session.execute(
            select(CatalogTarget).where(CatalogTarget.id == catalog_id)
        )).scalar_one_or_none()
        if cat is None:
            raise KeyError(f"Target catalog {catalog_id} not found")
        tbls = (await session.execute(
            select(CatalogTargetTable).where(CatalogTargetTable.catalog_id == catalog_id)
        )).scalars().all()

    return {
        "id": cat.id,
        "tenant_id": cat.tenant_id,
        "project": cat.project,
        "dataset": cat.dataset,
        "target_kind": cat.target_kind,
        "status": cat.status,
        "table_count": cat.table_count,
        "column_count": cat.column_count,
        "fetched_at": cat.fetched_at.isoformat(),
        "created_at": cat.created_at.isoformat(),
        "updated_at": cat.updated_at.isoformat(),
        "tables": [
            {
                "id": t.id,
                "table_name": t.table_name,
                "description": t.description,
                "column_count": t.column_count,
                "columns": json.loads(t.columns_json),
            }
            for t in tbls
        ],
    }
```

- [ ] **Step 4: Run test — should pass**

Run: `docker compose exec api pytest tests/test_catalog_persistence.py -v`
Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add core/catalog/persistence.py tests/test_catalog_persistence.py
git commit -m "feat(catalog): persistence — save/load source + target catalogs"
```

---

## Task 8: Uploader — orchestrate parse → persist

**Files:**
- Create: `core/catalog/uploader.py`

- [ ] **Step 1: Write the uploader**

```python
# core/catalog/uploader.py
"""Glue: parse an uploaded file and persist as a source catalog."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.catalog.parser import parse_schema_file
from core.catalog.persistence import save_source_catalog


async def upload_source_catalog(
    *,
    tenant_id: str,
    catalog_name: str,
    raw_filename: str,
    file_path: Path,
    description: Optional[str] = None,
    source_kind: str = "databricks_upload",
) -> dict:
    """Parse the file at `file_path`, persist as a source catalog, return summary."""
    schema = parse_schema_file(file_path)
    catalog_id = await save_source_catalog(
        tenant_id=tenant_id,
        catalog_name=catalog_name,
        source_kind=source_kind,
        raw_filename=raw_filename,
        description=description,
        schema=schema,
    )
    return {
        "catalog_id": catalog_id,
        "strategy": schema.strategy,
        "table_count": len(schema.tables),
        "column_count": sum(len(t.columns) for t in schema.tables),
    }
```

- [ ] **Step 2: Quick smoke import**

Run: `docker compose exec api python3 -c "from core.catalog.uploader import upload_source_catalog; print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add core/catalog/uploader.py
git commit -m "feat(catalog): uploader — parse + persist source catalogs"
```

---

## Task 9: BQ refresh — pull live INFORMATION_SCHEMA → target catalog

**Files:**
- Create: `core/catalog/bq_refresh.py`
- Create: `tests/test_catalog_bq_refresh.py`

- [ ] **Step 1: Write the failing test (mocked BQClient)**

```python
# tests/test_catalog_bq_refresh.py
"""Test BQ refresh with a mocked BQClient."""
from unittest.mock import MagicMock, patch

import pytest

from core.catalog.bq_refresh import refresh_target_catalog


@pytest.mark.asyncio
async def test_refresh_target_catalog_persists_grouped_rows():
    fake_rows = [
        {"table_name": "orders",    "column_name": "order_id",   "data_type": "STRING",    "is_nullable": "NO",  "description": "PK"},
        {"table_name": "orders",    "column_name": "amount",     "data_type": "FLOAT64",   "is_nullable": "YES", "description": None},
        {"table_name": "customers", "column_name": "customer_id","data_type": "STRING",    "is_nullable": "NO",  "description": None},
        {"table_name": "customers", "column_name": "email",      "data_type": "STRING",    "is_nullable": "YES", "description": "user email"},
    ]

    fake_client = MagicMock()
    fake_client.list_columns_in_dataset.return_value = fake_rows

    with patch("core.catalog.bq_refresh.BQClient", return_value=fake_client):
        out = await refresh_target_catalog(
            tenant_id="default",
            project="test-proj",
            dataset="test_ds",
        )

    assert out["table_count"] == 2
    assert out["column_count"] == 4
    assert out["catalog_id"]
    fake_client.list_columns_in_dataset.assert_called_once_with("test_ds")
```

- [ ] **Step 2: Run test — should fail**

Run: `docker compose exec api pytest tests/test_catalog_bq_refresh.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write bq_refresh.py**

```python
# core/catalog/bq_refresh.py
"""Pull live BQ INFORMATION_SCHEMA → target catalog rows.

Uses BQClient.list_columns_in_dataset (added in commit e52a3c3) which runs
one INFORMATION_SCHEMA.COLUMNS query against the dataset.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from core.bq_client import BQClient
from core.catalog.persistence import save_target_catalog


def _group_rows_by_table(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{table_name, column_name, data_type, ...}] → [{table_name, columns:[{name, type, ...}]}]."""
    by_table: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        tn = r.get("table_name")
        if not tn:
            continue
        col = {
            "name": r.get("column_name"),
            "type": r.get("data_type"),
            "description": r.get("description"),
            "is_nullable": (r.get("is_nullable") == "YES") if r.get("is_nullable") is not None else None,
            "ordinal": len(by_table.get(tn, [])),
        }
        by_table.setdefault(tn, []).append(col)
    return [
        {"table_name": tn, "description": None, "columns": cols}
        for tn, cols in by_table.items()
    ]


async def refresh_target_catalog(
    *,
    tenant_id: str,
    project: str,
    dataset: str,
) -> Dict[str, Any]:
    """Live-fetch BQ INFORMATION_SCHEMA, persist as target catalog, return summary."""
    client = BQClient(project_id=project)
    rows = await asyncio.to_thread(client.list_columns_in_dataset, dataset)
    if not rows:
        raise RuntimeError(
            f"INFORMATION_SCHEMA returned no rows for {project}.{dataset} — "
            f"dataset is empty or service account lacks access"
        )
    tables = _group_rows_by_table(rows)
    catalog_id = await save_target_catalog(
        tenant_id=tenant_id,
        project=project,
        dataset=dataset,
        tables=tables,
    )
    return {
        "catalog_id": catalog_id,
        "project": project,
        "dataset": dataset,
        "table_count": len(tables),
        "column_count": sum(len(t["columns"]) for t in tables),
    }
```

- [ ] **Step 4: Run test — should pass**

Run: `docker compose exec api pytest tests/test_catalog_bq_refresh.py -v`
Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add core/catalog/bq_refresh.py tests/test_catalog_bq_refresh.py
git commit -m "feat(catalog): BQ refresh — live INFORMATION_SCHEMA into target catalog"
```

---

## Task 10: FastAPI router — upload + refresh + list endpoints

**Files:**
- Create: `routers/catalogs.py`
- Create: `tests/test_catalogs_router.py`
- Modify: `app.py`

- [ ] **Step 1: Write the failing router integration test**

```python
# tests/test_catalogs_router.py
"""Router integration: upload + list + refresh-mocked."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app import app

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


@pytest.mark.asyncio
async def test_upload_source_then_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with open(FIXTURES / "target_information_schema.xlsx", "rb") as f:
            resp = await client.post(
                "/api/catalogs/source",
                files={"file": ("target_information_schema.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"catalog_name": "router_test_catalog", "description": "router test"},
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["table_count"] == 11
        assert body["column_count"] == 255
        cid = body["catalog_id"]

        resp = await client.get("/api/catalogs/source")
        assert resp.status_code == 200
        items = resp.json()["catalogs"]
        assert any(c["id"] == cid for c in items)


@pytest.mark.asyncio
async def test_refresh_target_mocked():
    transport = ASGITransport(app=app)
    fake_client = MagicMock()
    fake_client.list_columns_in_dataset.return_value = [
        {"table_name": "t1", "column_name": "c1", "data_type": "STRING", "is_nullable": "NO", "description": None},
        {"table_name": "t1", "column_name": "c2", "data_type": "INT64",  "is_nullable": "YES", "description": None},
        {"table_name": "t2", "column_name": "c1", "data_type": "STRING", "is_nullable": "NO", "description": None},
    ]
    with patch("core.catalog.bq_refresh.BQClient", return_value=fake_client):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/catalogs/target/refresh",
                json={"project": "test-proj", "dataset": "rtest_ds"},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["table_count"] == 2
            assert body["column_count"] == 3
```

- [ ] **Step 2: Run test — should fail**

Run: `docker compose exec api pytest tests/test_catalogs_router.py -v`
Expected: 404s or import error.

- [ ] **Step 3: Write routers/catalogs.py**

```python
# routers/catalogs.py
"""Catalog discovery API — upload source, refresh target, list both.

Endpoints:
  POST /api/catalogs/source              upload a Databricks INFORMATION_SCHEMA dump
  GET  /api/catalogs/source              list active source catalogs
  GET  /api/catalogs/source/{id}         load one source catalog with tables+columns
  POST /api/catalogs/target/refresh      pull live BQ INFORMATION_SCHEMA
  GET  /api/catalogs/target              list active target catalogs
  GET  /api/catalogs/target/{id}         load one target catalog with tables+columns

Multi-tenant: tenant_id is read from request.state.tenant_id when the
TenantMiddleware runs; defaults to "default" for unauthenticated dev calls.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from core.catalog.bq_refresh import refresh_target_catalog
from core.catalog.parser import ParserError
from core.catalog.persistence import (
    list_source_catalogs, list_target_catalogs,
    load_source_catalog, load_target_catalog,
)
from core.catalog.uploader import upload_source_catalog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/catalogs", tags=["catalogs"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class TargetRefreshIn(BaseModel):
    project: str
    dataset: str


# ── Helpers ─────────────────────────────────────────────────────────────────

def _tenant_id(request: Request) -> str:
    return getattr(request.state, "tenant_id", None) or "default"


# ── Source endpoints ────────────────────────────────────────────────────────

@router.post("/source", status_code=201)
async def upload_source(
    request: Request,
    file: UploadFile = File(...),
    catalog_name: str = Form(...),
    description: Optional[str] = Form(None),
) -> dict:
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".xlsx", ".xls", ".xlsm"):
        raise HTTPException(400, f"Unsupported file type {suffix} — only xlsx for v1")

    # Write to a temp file (parser is sync + uses openpyxl from disk).
    body = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)
    try:
        result = await upload_source_catalog(
            tenant_id=_tenant_id(request),
            catalog_name=catalog_name,
            raw_filename=file.filename,
            file_path=tmp_path,
            description=description,
        )
    except ParserError as exc:
        raise HTTPException(422, f"Parse failed: {exc}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return result


@router.get("/source")
async def list_sources(request: Request, include_archived: bool = False) -> dict:
    rows = await list_source_catalogs(tenant_id=_tenant_id(request), include_archived=include_archived)
    return {"catalogs": rows}


@router.get("/source/{catalog_id}")
async def get_source(catalog_id: str) -> dict:
    try:
        return await load_source_catalog(catalog_id)
    except KeyError:
        raise HTTPException(404, f"Catalog {catalog_id} not found")


# ── Target endpoints ────────────────────────────────────────────────────────

@router.post("/target/refresh", status_code=201)
async def refresh_target(request: Request, body: TargetRefreshIn) -> dict:
    try:
        return await refresh_target_catalog(
            tenant_id=_tenant_id(request),
            project=body.project,
            dataset=body.dataset,
        )
    except RuntimeError as exc:
        raise HTTPException(422, str(exc))


@router.get("/target")
async def list_targets(request: Request, include_archived: bool = False) -> dict:
    rows = await list_target_catalogs(tenant_id=_tenant_id(request), include_archived=include_archived)
    return {"catalogs": rows}


@router.get("/target/{catalog_id}")
async def get_target(catalog_id: str) -> dict:
    try:
        return await load_target_catalog(catalog_id)
    except KeyError:
        raise HTTPException(404, f"Catalog {catalog_id} not found")
```

- [ ] **Step 4: Register the router in app.py**

Open `app.py`. After the line `from routers.stm_memory import router as stm_memory_router`, add:

```python
from routers.catalogs import router as catalogs_router
```

After the line `app.include_router(stm_memory_router)`, add:

```python
app.include_router(catalogs_router)
```

- [ ] **Step 5: Verify python-multipart is installed (FastAPI UploadFile requirement)**

Run: `docker compose exec api python3 -c "import multipart; print(multipart.__version__)"`
Expected: prints a version number (≥0.0.5). If `ModuleNotFoundError`, add `python-multipart` to `requirements.txt` and rebuild the image:

```bash
echo "python-multipart>=0.0.6" >> requirements.txt
docker compose up --build api -d
```

- [ ] **Step 6: Run router tests**

Run: `docker compose exec api pytest tests/test_catalogs_router.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add routers/catalogs.py tests/test_catalogs_router.py app.py requirements.txt
git commit -m "feat(catalog): FastAPI router — upload, refresh, list endpoints"
```

---

## Task 11: End-to-end smoke against live BQ

This task uses the real BigQuery service account already mounted in the api container (`gcpproject-438715`, dataset `vz_raw_dev`). Verifies the whole Phase 1 stack from curl to live BQ.

- [ ] **Step 1: Rebuild and start**

Run: `docker compose up --build api -d`
Wait for healthy: `until curl -fs http://localhost:8000/api/health >/dev/null; do sleep 1; done`

- [ ] **Step 2: Upload a source catalog via curl**

Run:
```bash
curl -s -X POST http://localhost:8000/api/catalogs/source \
  -F "file=@tests/fixtures/catalog/target_information_schema.xlsx" \
  -F "catalog_name=phase1_smoke" \
  -F "description=phase 1 smoke test" | python3 -m json.tool
```
Expected output contains `"table_count": 11`, `"column_count": 255`, `"strategy": "schema_dump"`, and a `catalog_id` uuid.

- [ ] **Step 3: List source catalogs**

Run: `curl -s http://localhost:8000/api/catalogs/source | python3 -m json.tool`
Expected: an array `catalogs` containing the just-uploaded entry with `status: "active"`.

- [ ] **Step 4: Refresh a target catalog from live BQ**

Run:
```bash
curl -s -X POST http://localhost:8000/api/catalogs/target/refresh \
  -H 'Content-Type: application/json' \
  -d '{"project": "gcpproject-438715", "dataset": "vz_raw_dev"}' | python3 -m json.tool
```
Expected: `"table_count": 12`, `"column_count": 111`, and a `catalog_id` uuid.

- [ ] **Step 5: List target catalogs**

Run: `curl -s http://localhost:8000/api/catalogs/target | python3 -m json.tool`
Expected: an entry with `project: "gcpproject-438715"`, `dataset: "vz_raw_dev"`, `table_count: 12`.

- [ ] **Step 6: Load full target catalog detail**

Run:
```bash
TARGET_ID=$(curl -s http://localhost:8000/api/catalogs/target | python3 -c "import sys,json; print(json.load(sys.stdin)['catalogs'][0]['id'])")
curl -s "http://localhost:8000/api/catalogs/target/$TARGET_ID" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('tables:', d['table_count'])
for t in d['tables'][:3]:
    print(f\" - {t['table_name']} ({t['column_count']} cols) — first col: {t['columns'][0]}\")
"
```
Expected: lists `account`, `billing`, `cust_master` etc. with column metadata.

- [ ] **Step 7: Re-upload same source catalog (archive prior active)**

Run:
```bash
curl -s -X POST http://localhost:8000/api/catalogs/source \
  -F "file=@tests/fixtures/catalog/target_information_schema.xlsx" \
  -F "catalog_name=phase1_smoke" \
  -F "description=second upload" | python3 -m json.tool
```
Then: `curl -s "http://localhost:8000/api/catalogs/source?include_archived=true" | python3 -m json.tool`
Expected: at least one row with `status: "archived"` and one with `status: "active"`, both with the same `catalog_name`.

- [ ] **Step 8: Final commit**

If anything was tweaked during smoke (e.g., requirements.txt), commit it:

```bash
git status
git add -u
git diff --cached
git commit -m "test: Phase 1 end-to-end smoke validated against vz_raw_dev"
```

If nothing changed, skip this step (no empty commits).

---

## Self-review checklist (run before marking the plan done)

- [ ] **Spec coverage:** Every "Phase 1 — Foundation" deliverable in `docs/superpowers/specs/2026-05-14-enterprise-mapping-refactor-design.md` is addressed: alembic for catalogs (Task 2), uploader (Task 8), BQ refresh (Task 9), router (Task 10). Note: `batches` table deferred to Phase 2 plan; `target_table_embeddings` + pgvector deferred to Phase 3 plan — see plan header non-goals.
- [ ] **Placeholder scan:** No "TBD", "TODO", "implement later", or empty steps.
- [ ] **Type consistency:** `ParsedSchema.strategy` strings `"data_sample"`, `"schema_dump"`, `"workbook_per_table"` match across parser, persistence, and tests.
- [ ] **Method signatures consistent:** `BQClient.list_columns_in_dataset(dataset)` (singular `dataset` positional arg) matches the call in `bq_refresh.py` and the test mock.

## Done criteria for Phase 1

1. `pytest tests/test_catalog_parser.py tests/test_catalog_persistence.py tests/test_catalog_bq_refresh.py tests/test_catalogs_router.py -v` — all green.
2. Curl smoke test (Task 11) returns expected counts (11/255 source, 12/111 target).
3. Re-uploading the same `catalog_name` archives the prior active catalog without errors.
4. No regressions: existing test suite (`pytest tests/ -v` from project root) still passes.
5. Git log shows ~10 atomic commits, one per task, each green at commit time.

## Hand-off for Phase 2

Phase 2 (Batch + L3 rework) needs:
- `batches` table migration (new).
- `stm_sessions` migration adding `catalog_source_id` and `catalog_target_id` columns + nullable `source_table_id` (references `catalog_source_tables.id`).
- `core/stm/agents/schemas_agent.py` updated to load from catalog cache when those IDs are present, falling back to inline source/target.
- `core/batch/orchestrator.py` (new).
- `routers/batches.py` (new).
- `core/stm/agents/mapping_agent.py` rewrite (batched per-column, concurrency-bounded, mapping_memory few-shot).

Write that plan after Phase 1 lands.
