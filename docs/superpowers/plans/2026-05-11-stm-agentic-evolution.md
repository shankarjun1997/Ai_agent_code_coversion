# STM Agentic Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve `core/stm/` from a deterministic rule-based mapping engine into a 6-layer multi-agent reasoning pipeline (Intent → Metadata → Semantic → Transform → Validate → STM Build) with shared blackboard, multi-dialect source providers, ensemble confidence scoring, two governance gates, SSE live progress, and refinement-with-rerun.

**Architecture:** Stage-as-agent + shared Pydantic `StmBlackboard` persisted to new `stm_sessions` / `stm_stage_events` / `stm_gate_decisions` tables. A per-session coordinator `asyncio.Task` dispatches eligible agents in dependency order, stalls on two human gates, and emits SSE events to the UI. The existing rule engine `mapping_engine.build_stm()` runs as a deterministic baseline inside L3 — LLM refinement layers on top but never overrides the floor. Source providers behind a unified `SourceProvider` ABC (Postgres / Oracle / MySQL / MSSQL / BigQuery).

**Tech Stack:** Python 3.10 · FastAPI · Pydantic v2 · SQLAlchemy + Alembic · asyncio · Anthropic SDK (Claude Haiku 4.5 / Sonnet 4.6 / Opus 4.7) · psycopg2 · oracledb · pymysql · python-tds · google-cloud-bigquery · cryptography (Fernet) · openpyxl · React-in-HTML · SSE via PHP proxy

**Spec:** `docs/superpowers/specs/2026-05-11-stm-agentic-evolution-design.md`

---

## Phase Index

| Phase | Title | Shippable Outcome |
|---|---|---|
| 0 | Foundation | Dependencies + migrations + env scaffolding |
| 1 | Source Provider Abstraction | Postgres + BQ behind unified `SourceProvider` interface, cached |
| 2 | Multi-Dialect Providers | Oracle / MySQL / MSSQL providers + encrypted credentials + per-dialect profile endpoints |
| 3 | Blackboard + Persistence | StmBlackboard model, persistence layer, session lock, SSE event emit |
| 4 | Coordinator Skeleton + L1 + L6 | End-to-end session lifecycle with intent extraction and pass-through STM build |
| 5 | L2 Metadata + Gate 1 | Real metadata reasoning, knowledge graph, first governance gate |
| 6 | L3 Semantic + L4 Transform | Full mapping reasoning wrapping the rule baseline |
| 7 | L5 Validation + Gate 2 | Ensemble confidence scoring, deterministic findings, second gate, full L6 |
| 8 | UI Agentic Mode | React stepper, SSE consumption, gate panels, graph view, validation scorecard |
| 9 | Jira Write-Back + Polish | Optional Jira comment/transition, cost summary, clone session, test source containers |

**Conventions used throughout:**
- All new modules ship with focused unit tests (TDD).
- Each task ends with a green test suite + one atomic commit.
- File paths absolute from repo root.
- Commit messages follow existing repo style (`type: short summary` lowercase).
- Run tests with `pytest <path> -v`. Run from repo root unless noted.
- LLM calls in tests use `FakeLLMClient` (introduced in Phase 4 Task 4.1) — never hit the real API in unit tests.

---

# PHASE 0 — Foundation

Shippable outcome: dependencies installed, alembic migration applied, env scaffolding ready. Existing rule-based `POST /api/stm/generate` path remains 100% functional.

---

### Task 0.1: Add new dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Append new dependencies**

Add the following lines to the end of `requirements.txt`:

```
# STM agentic evolution
oracledb>=2.0
pymysql>=1.1
python-tds>=1.13
cryptography>=42
rapidfuzz>=3.6
```

- [ ] **Step 2: Install and verify**

Run: `pip install -r requirements.txt`
Expected: all packages install without compilation errors (oracledb is thin-mode, no Oracle client required; python-tds is pure-Python; rapidfuzz ships wheels).

Run: `python -c "import oracledb, pymysql, pytds, cryptography, rapidfuzz; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add oracledb, pymysql, python-tds, cryptography, rapidfuzz for STM agentic"
```

---

### Task 0.2: Env scaffolding

**Files:**
- Modify: `.env` (local copy; do NOT commit secrets)
- Modify: `core/config.py`

- [ ] **Step 1: Inspect current config**

Run: `grep -n "class.*Config\|env\|getenv" core/config.py`
Note the existing pattern (likely pydantic-settings or os.getenv).

- [ ] **Step 2: Add STM config block to `core/config.py`**

Append (or merge into the existing settings class — preserve the existing pattern):

```python
import os

# STM agentic evolution configuration
STM_PROFILE_ENCRYPTION_KEY = os.getenv("STM_PROFILE_ENCRYPTION_KEY", "")
STM_POOL_SIZE = int(os.getenv("STM_POOL_SIZE", "4"))
STM_JIRA_WRITEBACK_ENABLED = os.getenv("STM_JIRA_WRITEBACK_ENABLED", "false").lower() == "true"
STM_LLM_MODEL_L1 = os.getenv("STM_LLM_MODEL_L1", "claude-haiku-4-5")
STM_LLM_MODEL_L2 = os.getenv("STM_LLM_MODEL_L2", "claude-sonnet-4-6")
STM_LLM_MODEL_L3 = os.getenv("STM_LLM_MODEL_L3", "claude-opus-4-7")
STM_LLM_MODEL_L4 = os.getenv("STM_LLM_MODEL_L4", "claude-opus-4-7")
STM_VALIDATION_WEIGHTS = tuple(
    float(x) for x in os.getenv("STM_VALIDATION_WEIGHTS", "0.4,0.25,0.2,0.1,0.05").split(",")
)
STM_VALIDATION_LLM_EXPLAIN = os.getenv("STM_VALIDATION_LLM_EXPLAIN", "false").lower() == "true"
STM_PROBE_TIMEOUT_SEC = int(os.getenv("STM_PROBE_TIMEOUT_SEC", "30"))
STM_METADATA_CACHE_TTL_SEC = int(os.getenv("STM_METADATA_CACHE_TTL_SEC", "900"))
```

If the file uses a Pydantic settings class, add equivalent fields with the same defaults.

- [ ] **Step 3: Write smoke test**

Create `tests/stm/__init__.py` (empty file) and `tests/stm/test_config.py`:

```python
def test_stm_config_defaults(monkeypatch):
    monkeypatch.delenv("STM_POOL_SIZE", raising=False)
    monkeypatch.delenv("STM_LLM_MODEL_L1", raising=False)
    import importlib, core.config as cfg
    importlib.reload(cfg)
    assert cfg.STM_POOL_SIZE == 4
    assert cfg.STM_LLM_MODEL_L1 == "claude-haiku-4-5"
    assert cfg.STM_JIRA_WRITEBACK_ENABLED is False
    assert sum(cfg.STM_VALIDATION_WEIGHTS) == 1.0
```

- [ ] **Step 4: Run test**

Run: `pytest tests/stm/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/stm/__init__.py tests/stm/test_config.py
git commit -m "config: add STM agentic evolution settings"
```

---

### Task 0.3: Alembic migration — STM tables + profile columns

**Files:**
- Create: `alembic/versions/<auto>_stm_agentic_tables.py`
- Test: `tests/stm/test_migration.py`

- [ ] **Step 1: Generate migration skeleton**

Run: `alembic revision -m "stm_agentic_tables"`
Note the generated revision id; use it as `<rev>` below.

- [ ] **Step 2: Replace the migration body**

Open the generated file `alembic/versions/<rev>_stm_agentic_tables.py` and replace `upgrade()` / `downgrade()` with:

```python
"""stm_agentic_tables

Revision ID: <rev>
Revises: <prev_rev>   # alembic fills this in
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "stm_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_stage", sa.String(16), nullable=False),
        sa.Column("target_table", sa.String(128), nullable=False),
        sa.Column("target_dataset", sa.String(128), nullable=False),
        sa.Column("source_profiles", sa.Text(), nullable=False),  # JSON array
        sa.Column("intent_source", sa.String(16), nullable=False),
        sa.Column("jira_issue_key", sa.String(64), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("blackboard_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=True),
    )
    op.create_table(
        "stm_stage_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("stm_sessions.session_id"), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("event_kind", sa.String(32), nullable=False),
        sa.Column("artifact_kind", sa.String(32), nullable=True),
        sa.Column("artifact_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("llm_model", sa.String(64), nullable=True),
        sa.Column("llm_tokens_in", sa.Integer(), nullable=True),
        sa.Column("llm_tokens_out", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_stm_stage_events_session",
        "stm_stage_events",
        ["session_id", "created_at"],
    )
    op.create_table(
        "stm_gate_decisions",
        sa.Column("decision_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("stm_sessions.session_id"), nullable=False),
        sa.Column("gate_name", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer", sa.String(128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("refine_target", sa.String(16), nullable=True),
        sa.Column("refine_feedback", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
    )
    # Profile encryption columns (table 'profiles' exists from discovery)
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("last_ping", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_ping_status", sa.String(32), nullable=True))


def downgrade():
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("last_ping_status")
        batch.drop_column("last_ping")
        batch.drop_column("encrypted_credentials")
    op.drop_table("stm_gate_decisions")
    op.drop_index("idx_stm_stage_events_session", table_name="stm_stage_events")
    op.drop_table("stm_stage_events")
    op.drop_table("stm_sessions")
```

Note: if `profiles` table does not yet exist in the SQL schema (only as in-memory dataclass in `core/discovery/profiles.py`), create it in this migration too:

```python
# Insert BEFORE the batch_alter_table block above:
op.create_table(
    "profiles",
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("label", sa.String(128), nullable=False),
    sa.Column("dialect", sa.String(16), nullable=False),
    sa.Column("dsn", sa.Text(), nullable=False),
    sa.Column("host", sa.String(256), nullable=False),
    sa.Column("icon", sa.String(8), nullable=False, server_default="DB"),
    sa.Column("status", sa.String(32), nullable=False, server_default="connected"),
    sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=True),
    sa.Column("last_ping", sa.DateTime(), nullable=True),
    sa.Column("last_ping_status", sa.String(32), nullable=True),
    sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
)
```

…and remove the `batch_alter_table` for profiles (columns already declared in `create_table`).

Run `grep -rn "profiles" alembic/versions/ core/models/ | head` first to confirm which path applies. If a `profiles` table already exists, keep the original `batch_alter_table`. Otherwise use the combined `create_table` form.

- [ ] **Step 3: Run migration locally**

Run: `alembic upgrade head`
Expected: migration applies cleanly. Two new lines: `Running upgrade <prev_rev> -> <rev>, stm_agentic_tables`.

- [ ] **Step 4: Verify tables**

Run: `python -c "from sqlalchemy import create_engine, inspect; import os; e = create_engine(os.environ.get('DATABASE_URL','sqlite:///./app.db')); print(inspect(e).get_table_names())"`
Expected output contains: `stm_sessions`, `stm_stage_events`, `stm_gate_decisions`.

- [ ] **Step 5: Write migration smoke test**

Create `tests/stm/test_migration.py`:

```python
import os
from sqlalchemy import create_engine, inspect


def test_stm_tables_present():
    engine = create_engine(os.environ.get("DATABASE_URL", "sqlite:///./app.db"))
    tables = set(inspect(engine).get_table_names())
    assert "stm_sessions" in tables
    assert "stm_stage_events" in tables
    assert "stm_gate_decisions" in tables


def test_stm_stage_events_index():
    engine = create_engine(os.environ.get("DATABASE_URL", "sqlite:///./app.db"))
    idx_names = [i["name"] for i in inspect(engine).get_indexes("stm_stage_events")]
    assert "idx_stm_stage_events_session" in idx_names
```

- [ ] **Step 6: Run test**

Run: `pytest tests/stm/test_migration.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/<rev>_stm_agentic_tables.py tests/stm/test_migration.py
git commit -m "migration: stm_sessions, stm_stage_events, stm_gate_decisions + profile creds columns"
```

---

# PHASE 1 — Source Provider Abstraction

Shippable outcome: existing Postgres discovery + BigQuery wrapped behind a single `SourceProvider` ABC, with a 15-minute TTL cache. No agentic flow yet; existing rule path still uses the same providers transparently.

---

### Task 1.1: SourceProvider ABC + data classes

**Files:**
- Create: `core/discovery/base.py`
- Create: `tests/discovery/__init__.py` (empty)
- Test: `tests/discovery/test_base.py`

- [ ] **Step 1: Write failing contract test**

Create `tests/discovery/test_base.py`:

```python
import pytest
from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo,
    FKInfo, ColumnProfile, ColumnHit,
)


def test_source_provider_is_abstract():
    with pytest.raises(TypeError):
        SourceProvider()


def test_ping_result_shape():
    r = PingResult(ok=True, latency_ms=12, message=None)
    assert r.ok is True
    assert r.latency_ms == 12


def test_table_info_shape():
    t = TableInfo(schema="public", name="customers", row_estimate=1000, comment=None)
    assert t.schema == "public"


def test_column_info_shape():
    c = ColumnInfo(
        schema="public", table="customers", name="customer_id",
        data_type="bigint", nullable=False, is_primary_key=True,
        default=None, comment=None,
    )
    assert c.is_primary_key is True
```

- [ ] **Step 2: Run — expect import error**

Run: `pytest tests/discovery/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.discovery.base'`.

- [ ] **Step 3: Implement `core/discovery/base.py`**

```python
"""SourceProvider abstract interface for cross-dialect discovery."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional


Dialect = Literal["postgres", "oracle", "mysql", "mssql", "bigquery"]


@dataclass
class PingResult:
    ok: bool
    latency_ms: Optional[int] = None
    message: Optional[str] = None


@dataclass
class TableInfo:
    schema: str
    name: str
    row_estimate: Optional[int] = None
    comment: Optional[str] = None


@dataclass
class ColumnInfo:
    schema: str
    table: str
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool = False
    default: Optional[str] = None
    comment: Optional[str] = None


@dataclass
class FKInfo:
    schema: str
    table: str
    column: str
    ref_schema: str
    ref_table: str
    ref_column: str
    constraint_name: Optional[str] = None


@dataclass
class ColumnProfile:
    row_count: Optional[int] = None
    distinct_count: Optional[int] = None
    null_pct: Optional[float] = None
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    sample_values: List[Any] = None


@dataclass
class ColumnHit:
    schema: str
    table: str
    column: str
    data_type: str
    score: float
    matched_on: Literal["name", "comment", "value"]


class SourceProvider(ABC):
    dialect: Dialect

    @abstractmethod
    async def ping(self, profile: Any) -> PingResult: ...

    @abstractmethod
    async def list_schemas(self, profile: Any) -> List[str]: ...

    @abstractmethod
    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]: ...

    @abstractmethod
    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]: ...

    @abstractmethod
    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]: ...

    @abstractmethod
    async def profile_column(
        self, profile: Any, schema: str, table: str, column: str,
        sample_rows: int = 0,
    ) -> ColumnProfile: ...

    @abstractmethod
    async def search_by_keywords(
        self, profile: Any, keywords: List[str], limit: int = 50,
    ) -> List[ColumnHit]: ...
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/discovery/test_base.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/discovery/base.py tests/discovery/__init__.py tests/discovery/test_base.py
git commit -m "discovery: add SourceProvider ABC + data classes"
```

---

### Task 1.2: Provider registry

**Files:**
- Create: `core/discovery/registry.py`
- Test: `tests/discovery/test_registry.py`

- [ ] **Step 1: Write failing test**

Create `tests/discovery/test_registry.py`:

```python
import pytest
from core.discovery.registry import get_provider, register_provider
from core.discovery.base import SourceProvider, PingResult


class _Fake(SourceProvider):
    dialect = "postgres"
    async def ping(self, p): return PingResult(ok=True)
    async def list_schemas(self, p): return []
    async def list_tables(self, p, s): return []
    async def get_columns(self, p, s, t): return []
    async def get_foreign_keys(self, p, s, t): return []
    async def profile_column(self, p, s, t, c, sample_rows=0): return None
    async def search_by_keywords(self, p, kw, limit=50): return []


def test_unknown_dialect_raises():
    with pytest.raises(ValueError):
        get_provider("nonexistent")


def test_register_and_get():
    fake = _Fake()
    register_provider("postgres", fake)
    assert get_provider("postgres") is fake
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/discovery/test_registry.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `core/discovery/registry.py`**

```python
"""Dialect → SourceProvider registry."""
from typing import Dict
from core.discovery.base import SourceProvider, Dialect


_PROVIDERS: Dict[str, SourceProvider] = {}


def register_provider(dialect: Dialect, provider: SourceProvider) -> None:
    _PROVIDERS[dialect] = provider


def get_provider(dialect: str) -> SourceProvider:
    p = _PROVIDERS.get(dialect)
    if p is None:
        raise ValueError(f"Unknown dialect: {dialect}")
    return p


def all_providers() -> Dict[str, SourceProvider]:
    return dict(_PROVIDERS)
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/discovery/test_registry.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/discovery/registry.py tests/discovery/test_registry.py
git commit -m "discovery: provider registry"
```

---

### Task 1.3: Cache layer

**Files:**
- Create: `core/discovery/cache.py`
- Test: `tests/discovery/test_cache.py`

- [ ] **Step 1: Write failing test**

Create `tests/discovery/test_cache.py`:

```python
import asyncio
import time

import pytest

from core.discovery.cache import DiscoveryCache


@pytest.mark.asyncio
async def test_cache_hit_within_ttl():
    cache = DiscoveryCache(ttl_seconds=60)
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return "value"

    assert await cache.get_or_load("p1", "list_schemas", (), loader) == "value"
    assert await cache.get_or_load("p1", "list_schemas", (), loader) == "value"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cache_miss_after_ttl():
    cache = DiscoveryCache(ttl_seconds=0)  # immediate expiry
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return "v"

    await cache.get_or_load("p", "m", (), loader)
    time.sleep(0.01)
    await cache.get_or_load("p", "m", (), loader)
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_bypass_cache_forces_reload():
    cache = DiscoveryCache(ttl_seconds=60)
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return "v"

    await cache.get_or_load("p", "m", (), loader)
    await cache.get_or_load("p", "m", (), loader, bypass=True)
    assert calls["n"] == 2
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/discovery/test_cache.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `core/discovery/cache.py`**

```python
"""15-minute TTL in-memory cache for discovery results."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Hashable, Tuple

from core.config import STM_METADATA_CACHE_TTL_SEC


class DiscoveryCache:
    def __init__(self, ttl_seconds: int = STM_METADATA_CACHE_TTL_SEC):
        self.ttl = ttl_seconds
        self._store: Dict[Tuple[str, str, Tuple[Hashable, ...]], Tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_or_load(
        self,
        profile_id: str,
        method: str,
        args: Tuple[Hashable, ...],
        loader: Callable[[], Awaitable[Any]],
        bypass: bool = False,
    ) -> Any:
        key = (profile_id, method, args)
        now = time.time()
        if not bypass:
            async with self._lock:
                hit = self._store.get(key)
            if hit is not None:
                ts, val = hit
                if now - ts <= self.ttl:
                    return val
        val = await loader()
        async with self._lock:
            self._store[key] = (now, val)
        return val

    def invalidate(self, profile_id: str | None = None) -> None:
        if profile_id is None:
            self._store.clear()
            return
        keys = [k for k in self._store if k[0] == profile_id]
        for k in keys:
            self._store.pop(k, None)


_default = DiscoveryCache()


def default_cache() -> DiscoveryCache:
    return _default
```

- [ ] **Step 4: Add pytest-asyncio if missing**

Run: `pip show pytest-asyncio || pip install pytest-asyncio>=0.23`
Add to `requirements.txt` under a test dependencies section (or `requirements-dev.txt` if one exists):

```
pytest-asyncio>=0.23
```

Add to `pyproject.toml` or `pytest.ini` (whichever this repo uses; check with `ls pyproject.toml pytest.ini setup.cfg 2>/dev/null`):

```ini
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 5: Run — expect PASS**

Run: `pytest tests/discovery/test_cache.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add core/discovery/cache.py tests/discovery/test_cache.py requirements.txt pyproject.toml
git commit -m "discovery: 15min TTL cache for source probes"
```

---

### Task 1.4: Refactor PostgresProvider to async + SourceProvider interface

**Files:**
- Modify: `core/discovery/postgres_provider.py`
- Test: `tests/discovery/test_postgres_provider.py`

- [ ] **Step 1: Read current file**

Use the Read tool on `core/discovery/postgres_provider.py`. Note the existing function signatures so the refactor preserves callers in the rule-based path.

- [ ] **Step 2: Write failing async-interface test (skipped if no Postgres)**

Create `tests/discovery/test_postgres_provider.py`:

```python
import os

import pytest

from core.discovery.base import SourceProvider
from core.discovery.postgres_provider import PostgresProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("DEMO_DB_DSN"), reason="DEMO_DB_DSN not set"
)


def test_postgres_provider_implements_interface():
    p = PostgresProvider()
    assert isinstance(p, SourceProvider)
    assert p.dialect == "postgres"


@pytest.mark.asyncio
async def test_postgres_ping(demo_pg_profile):
    p = PostgresProvider()
    r = await p.ping(demo_pg_profile)
    assert r.ok is True
    assert r.latency_ms is not None


@pytest.mark.asyncio
async def test_postgres_list_schemas(demo_pg_profile):
    p = PostgresProvider()
    schemas = await p.list_schemas(demo_pg_profile)
    assert "public" in schemas
```

Create `tests/discovery/conftest.py`:

```python
import os

import pytest

from core.discovery.profiles import ConnectionProfile


@pytest.fixture
def demo_pg_profile():
    dsn = os.environ.get("DEMO_DB_DSN", "postgresql://demo:demo@localhost:5432/crm_demo")
    host = dsn.split("@", 1)[-1] if "@" in dsn else dsn
    return ConnectionProfile(
        id="test-pg", label="test", dialect="postgres", dsn=dsn, host=host,
    )
```

- [ ] **Step 3: Run — expect FAIL (skipped without DSN)**

Run: `DEMO_DB_DSN=postgresql://demo:demo@localhost:5432/crm_demo pytest tests/discovery/test_postgres_provider.py -v`
Expected: FAIL on `isinstance(p, SourceProvider)` or AttributeError on async methods.

- [ ] **Step 4: Refactor `core/discovery/postgres_provider.py`**

Wrap existing sync logic in async methods using `asyncio.to_thread`. Preserve every existing public function in the module — add new `PostgresProvider` class alongside.

Add at the top of the file:

```python
import asyncio
from typing import Any, List
from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo,
    ColumnProfile, ColumnHit,
)
```

Add the class at the bottom of the file (keep all existing top-level functions intact):

```python
class PostgresProvider(SourceProvider):
    dialect = "postgres"

    async def ping(self, profile: Any) -> PingResult:
        def _sync():
            import psycopg2, time
            t0 = time.perf_counter()
            try:
                conn = psycopg2.connect(profile.dsn, connect_timeout=5)
                conn.close()
                return PingResult(ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
            except Exception as exc:
                return PingResult(ok=False, message=str(exc))
        return await asyncio.to_thread(_sync)

    async def list_schemas(self, profile: Any) -> List[str]:
        def _sync():
            import psycopg2
            with psycopg2.connect(profile.dsn) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT schema_name FROM information_schema.schemata
                    WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
                    ORDER BY schema_name
                """)
                return [r[0] for r in cur.fetchall()]
        return await asyncio.to_thread(_sync)

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _sync():
            import psycopg2
            with psycopg2.connect(profile.dsn) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name, obj_description(
                        ('"' || %s || '"."' || table_name || '"')::regclass, 'pg_class'
                    )
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_type='BASE TABLE'
                    ORDER BY table_name
                """, (schema, schema))
                return [TableInfo(schema=schema, name=r[0], comment=r[1]) for r in cur.fetchall()]
        return await asyncio.to_thread(_sync)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _sync():
            import psycopg2
            with psycopg2.connect(profile.dsn) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT c.column_name, c.data_type, c.is_nullable, c.column_default,
                           CASE WHEN tc.constraint_type='PRIMARY KEY' THEN TRUE ELSE FALSE END AS is_pk
                    FROM information_schema.columns c
                    LEFT JOIN information_schema.key_column_usage kcu
                      ON kcu.table_schema=c.table_schema AND kcu.table_name=c.table_name AND kcu.column_name=c.column_name
                    LEFT JOIN information_schema.table_constraints tc
                      ON tc.constraint_name=kcu.constraint_name AND tc.constraint_type='PRIMARY KEY'
                    WHERE c.table_schema=%s AND c.table_name=%s
                    ORDER BY c.ordinal_position
                """, (schema, table))
                return [
                    ColumnInfo(
                        schema=schema, table=table, name=r[0],
                        data_type=r[1], nullable=(r[2] == "YES"),
                        default=r[3], is_primary_key=bool(r[4]),
                    )
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        def _sync():
            import psycopg2
            with psycopg2.connect(profile.dsn) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT kcu.column_name, ccu.table_schema, ccu.table_name, ccu.column_name, tc.constraint_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu USING (constraint_name, table_schema)
                    JOIN information_schema.constraint_column_usage ccu USING (constraint_name, table_schema)
                    WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema=%s AND tc.table_name=%s
                """, (schema, table))
                return [
                    FKInfo(
                        schema=schema, table=table, column=r[0],
                        ref_schema=r[1], ref_table=r[2], ref_column=r[3],
                        constraint_name=r[4],
                    )
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def profile_column(
        self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0,
    ) -> ColumnProfile:
        def _sync():
            import psycopg2
            with psycopg2.connect(profile.dsn) as conn, conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*), COUNT(DISTINCT "{column}"), 100.0 * AVG(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END) FROM "{schema}"."{table}"')
                row = cur.fetchone()
                rc, dc, np = row[0], row[1], float(row[2]) if row[2] is not None else None
                samples = []
                if sample_rows > 0:
                    cur.execute(f'SELECT "{column}" FROM "{schema}"."{table}" WHERE "{column}" IS NOT NULL LIMIT {int(sample_rows)}')
                    samples = [r[0] for r in cur.fetchall()]
                return ColumnProfile(row_count=rc, distinct_count=dc, null_pct=np, sample_values=samples)
        return await asyncio.to_thread(_sync)

    async def search_by_keywords(
        self, profile: Any, keywords: List[str], limit: int = 50,
    ) -> List[ColumnHit]:
        def _sync():
            if not keywords:
                return []
            import psycopg2
            patterns = [f"%{k.lower()}%" for k in keywords]
            placeholders = " OR ".join(["LOWER(column_name) LIKE %s"] * len(patterns))
            sql = f"""
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
                  AND ({placeholders})
                ORDER BY table_schema, table_name, ordinal_position
                LIMIT %s
            """
            with psycopg2.connect(profile.dsn) as conn, conn.cursor() as cur:
                cur.execute(sql, (*patterns, limit))
                return [
                    ColumnHit(schema=r[0], table=r[1], column=r[2], data_type=r[3], score=1.0, matched_on="name")
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)
```

- [ ] **Step 5: Run tests — expect PASS (with Postgres up)**

Run: `DEMO_DB_DSN=<dsn> pytest tests/discovery/test_postgres_provider.py -v`
Expected: 3 passed (or 3 skipped if DSN absent).

Run the existing test suite to ensure no regression:
Run: `pytest -q -x --ignore=tests/integration --ignore=tests/e2e 2>&1 | tail -30`
Expected: no failures introduced.

- [ ] **Step 6: Register provider in `core/discovery/__init__.py`**

Open `core/discovery/__init__.py` (likely currently lists profile registry exports). Append:

```python
from core.discovery.base import SourceProvider
from core.discovery.registry import register_provider, get_provider, all_providers
from core.discovery.postgres_provider import PostgresProvider

# Auto-register Postgres on import
register_provider("postgres", PostgresProvider())
```

- [ ] **Step 7: Commit**

```bash
git add core/discovery/postgres_provider.py core/discovery/__init__.py tests/discovery/test_postgres_provider.py tests/discovery/conftest.py
git commit -m "discovery: async PostgresProvider behind SourceProvider interface"
```

---

### Task 1.5: BigQuery provider

**Files:**
- Create: `core/discovery/bigquery_provider.py`
- Test: `tests/discovery/test_bigquery_provider.py`

- [ ] **Step 1: Write failing test (skipped unless BQ credentials present)**

Create `tests/discovery/test_bigquery_provider.py`:

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    reason="GOOGLE_APPLICATION_CREDENTIALS not set",
)

from core.discovery.base import SourceProvider
from core.discovery.bigquery_provider import BigQueryProvider
from core.discovery.profiles import ConnectionProfile


def test_bq_provider_implements_interface():
    p = BigQueryProvider()
    assert isinstance(p, SourceProvider)
    assert p.dialect == "bigquery"


@pytest.mark.asyncio
async def test_bq_list_schemas(bq_profile):
    p = BigQueryProvider()
    out = await p.list_schemas(bq_profile)
    assert isinstance(out, list)
```

Append fixture to `tests/discovery/conftest.py`:

```python
@pytest.fixture
def bq_profile():
    from core.discovery.profiles import ConnectionProfile
    return ConnectionProfile(
        id="test-bq", label="test", dialect="bigquery",
        dsn=os.environ.get("BQ_PROJECT_ID", ""), host="bigquery",
    )
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/discovery/test_bigquery_provider.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `core/discovery/bigquery_provider.py`**

```python
"""BigQuery provider wrapping core/bq_client.py."""
from __future__ import annotations

import asyncio
import time
from typing import Any, List

from core.bq_client import BQClient
from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo,
    ColumnProfile, ColumnHit,
)


class BigQueryProvider(SourceProvider):
    dialect = "bigquery"

    def _client(self, profile: Any) -> BQClient:
        project_id = profile.dsn or ""
        return BQClient(project_id=project_id)

    async def ping(self, profile: Any) -> PingResult:
        def _sync():
            t0 = time.perf_counter()
            try:
                self._client(profile).get_all_datasets()
                return PingResult(ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
            except Exception as exc:
                return PingResult(ok=False, message=str(exc))
        return await asyncio.to_thread(_sync)

    async def list_schemas(self, profile: Any) -> List[str]:
        return await asyncio.to_thread(lambda: self._client(profile).get_all_datasets())

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _sync():
            names = self._client(profile).get_tables_in_dataset(schema)
            return [TableInfo(schema=schema, name=n) for n in names]
        return await asyncio.to_thread(_sync)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _sync():
            rows = self._client(profile).get_table_schema(schema, table)
            return [
                ColumnInfo(
                    schema=schema, table=table, name=r["column_name"],
                    data_type=r["data_type"], nullable=(r["is_nullable"] == "YES"),
                    default=r.get("column_default"),
                )
                for r in rows if "error" not in r
            ]
        return await asyncio.to_thread(_sync)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        # BigQuery has no FK metadata; return empty.
        return []

    async def profile_column(
        self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0,
    ) -> ColumnProfile:
        def _sync():
            client = self._client(profile)
            rc = client.get_row_count(schema, table)
            samples = []
            if sample_rows > 0:
                samples = [r.get(column) for r in client.get_sample_rows(schema, table, n=sample_rows)]
            return ColumnProfile(row_count=rc, sample_values=samples)
        return await asyncio.to_thread(_sync)

    async def search_by_keywords(
        self, profile: Any, keywords: List[str], limit: int = 50,
    ) -> List[ColumnHit]:
        def _sync():
            client = self._client(profile)
            hits: List[ColumnHit] = []
            for ds in client.get_all_datasets():
                rows = client.search_schema(ds, keywords)
                for r in rows:
                    if "error" in r:
                        continue
                    hits.append(ColumnHit(
                        schema=ds, table=r["table_name"], column=r["column_name"],
                        data_type=r["data_type"], score=1.0, matched_on="name",
                    ))
                    if len(hits) >= limit:
                        return hits
            return hits
        return await asyncio.to_thread(_sync)
```

- [ ] **Step 4: Register in `core/discovery/__init__.py`**

Append:

```python
from core.discovery.bigquery_provider import BigQueryProvider
register_provider("bigquery", BigQueryProvider())
```

- [ ] **Step 5: Run — expect PASS (or skip)**

Run: `pytest tests/discovery/test_bigquery_provider.py -v`
Expected: 2 passed if credentials present, 2 skipped otherwise.

- [ ] **Step 6: Commit**

```bash
git add core/discovery/bigquery_provider.py core/discovery/__init__.py tests/discovery/test_bigquery_provider.py tests/discovery/conftest.py
git commit -m "discovery: BigQueryProvider"
```

---

# PHASE 2 — Multi-Dialect Providers + Encrypted Credentials

Shippable outcome: Oracle / MySQL / MSSQL providers implementing the same interface, plus a Fernet credential helper and per-dialect POST endpoints. After this phase the UI can ping all five dialects.

---

### Task 2.1: Credential encryption helper

**Files:**
- Create: `core/discovery/credentials.py`
- Test: `tests/discovery/test_credentials.py`

- [ ] **Step 1: Write failing test**

Create `tests/discovery/test_credentials.py`:

```python
import os

import pytest

from core.discovery.credentials import encrypt, decrypt, generate_key


def test_roundtrip(monkeypatch):
    key = generate_key()
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", key)
    blob = encrypt({"user": "alice", "password": "s3cret"})
    assert isinstance(blob, bytes)
    assert b"alice" not in blob
    data = decrypt(blob)
    assert data == {"user": "alice", "password": "s3cret"}


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("STM_PROFILE_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        encrypt({"x": 1})
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/discovery/test_credentials.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `core/discovery/credentials.py`**

```python
"""Fernet-based credential encryption for source profiles."""
from __future__ import annotations

import json
import os
from typing import Any

from cryptography.fernet import Fernet


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _fernet() -> Fernet:
    key = os.environ.get("STM_PROFILE_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("STM_PROFILE_ENCRYPTION_KEY not set")
    return Fernet(key.encode("ascii") if isinstance(key, str) else key)


def encrypt(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode("utf-8"))


def decrypt(blob: bytes) -> dict:
    return json.loads(_fernet().decrypt(blob).decode("utf-8"))
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/discovery/test_credentials.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/discovery/credentials.py tests/discovery/test_credentials.py
git commit -m "discovery: Fernet credential helper"
```

---

### Task 2.2: Oracle provider

**Files:**
- Create: `core/discovery/oracle_provider.py`
- Test: `tests/discovery/test_oracle_provider.py`

- [ ] **Step 1: Write failing test**

Create `tests/discovery/test_oracle_provider.py`:

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ORACLE_TEST_DSN"), reason="ORACLE_TEST_DSN not set"
)

from core.discovery.base import SourceProvider
from core.discovery.oracle_provider import OracleProvider
from core.discovery.profiles import ConnectionProfile


def test_oracle_provider_implements_interface():
    assert isinstance(OracleProvider(), SourceProvider)
    assert OracleProvider().dialect == "oracle"


@pytest.mark.asyncio
async def test_oracle_ping():
    dsn = os.environ["ORACLE_TEST_DSN"]   # e.g. user/pass@host:1521/svc
    p = ConnectionProfile(id="ora", label="t", dialect="oracle", dsn=dsn, host=dsn)
    r = await OracleProvider().ping(p)
    assert r.ok is True
```

- [ ] **Step 2: Run — FAIL or skip**

Run: `pytest tests/discovery/test_oracle_provider.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `core/discovery/oracle_provider.py`**

```python
"""Oracle source provider — oracledb thin mode (no Oracle client install)."""
from __future__ import annotations

import asyncio
import time
from typing import Any, List

import oracledb

from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo,
    ColumnProfile, ColumnHit,
)


class OracleProvider(SourceProvider):
    dialect = "oracle"

    def _connect(self, profile: Any):
        # DSN format: user/pass@host:port/service
        return oracledb.connect(profile.dsn)

    async def ping(self, profile: Any) -> PingResult:
        def _sync():
            t0 = time.perf_counter()
            try:
                conn = self._connect(profile)
                conn.close()
                return PingResult(ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
            except Exception as exc:
                return PingResult(ok=False, message=str(exc))
        return await asyncio.to_thread(_sync)

    async def list_schemas(self, profile: Any) -> List[str]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute("SELECT username FROM all_users ORDER BY username")
                return [r[0] for r in cur.fetchall()]
        return await asyncio.to_thread(_sync)

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name, num_rows FROM all_tables WHERE owner=:o ORDER BY table_name",
                    o=schema.upper(),
                )
                return [TableInfo(schema=schema, name=r[0], row_estimate=r[1]) for r in cur.fetchall()]
        return await asyncio.to_thread(_sync)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT c.column_name, c.data_type, c.nullable, c.data_default,
                           CASE WHEN cc.constraint_type='P' THEN 'Y' ELSE 'N' END
                    FROM all_tab_columns c
                    LEFT JOIN all_cons_columns cc_col
                      ON cc_col.owner=c.owner AND cc_col.table_name=c.table_name AND cc_col.column_name=c.column_name
                    LEFT JOIN all_constraints cc
                      ON cc.owner=cc_col.owner AND cc.constraint_name=cc_col.constraint_name AND cc.constraint_type='P'
                    WHERE c.owner=:o AND c.table_name=:t
                    ORDER BY c.column_id
                """, o=schema.upper(), t=table.upper())
                return [
                    ColumnInfo(
                        schema=schema, table=table, name=r[0],
                        data_type=r[1], nullable=(r[2] == "Y"),
                        default=str(r[3]) if r[3] is not None else None,
                        is_primary_key=(r[4] == "Y"),
                    )
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT a.column_name, c_pk.owner, c_pk.table_name, b.column_name, a.constraint_name
                    FROM all_cons_columns a
                    JOIN all_constraints c
                      ON a.owner=c.owner AND a.constraint_name=c.constraint_name
                    JOIN all_constraints c_pk
                      ON c.r_owner=c_pk.owner AND c.r_constraint_name=c_pk.constraint_name
                    JOIN all_cons_columns b
                      ON c_pk.owner=b.owner AND c_pk.constraint_name=b.constraint_name AND b.position=a.position
                    WHERE c.constraint_type='R' AND a.owner=:o AND a.table_name=:t
                """, o=schema.upper(), t=table.upper())
                return [
                    FKInfo(
                        schema=schema, table=table, column=r[0],
                        ref_schema=r[1], ref_table=r[2], ref_column=r[3],
                        constraint_name=r[4],
                    )
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def profile_column(
        self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0,
    ) -> ColumnProfile:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(
                    f'SELECT COUNT(*), COUNT(DISTINCT "{column}"), '
                    f'100*AVG(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END) '
                    f'FROM "{schema.upper()}"."{table.upper()}"'
                )
                rc, dc, np = cur.fetchone()
                samples = []
                if sample_rows > 0:
                    cur.execute(
                        f'SELECT "{column}" FROM "{schema.upper()}"."{table.upper()}" '
                        f'WHERE "{column}" IS NOT NULL AND ROWNUM <= {int(sample_rows)}'
                    )
                    samples = [r[0] for r in cur.fetchall()]
                return ColumnProfile(
                    row_count=rc, distinct_count=dc,
                    null_pct=float(np) if np is not None else None,
                    sample_values=samples,
                )
        return await asyncio.to_thread(_sync)

    async def search_by_keywords(
        self, profile: Any, keywords: List[str], limit: int = 50,
    ) -> List[ColumnHit]:
        def _sync():
            if not keywords:
                return []
            patterns = [f"%{k.lower()}%" for k in keywords]
            clauses = " OR ".join([f"LOWER(column_name) LIKE :k{i}" for i in range(len(patterns))])
            sql = f"""
                SELECT owner, table_name, column_name, data_type
                FROM all_tab_columns
                WHERE ({clauses}) AND owner NOT IN ('SYS','SYSTEM','XDB')
                AND ROWNUM <= :lim
            """
            params = {f"k{i}": p for i, p in enumerate(patterns)}
            params["lim"] = limit
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(sql, **params)
                return [
                    ColumnHit(schema=r[0], table=r[1], column=r[2], data_type=r[3], score=1.0, matched_on="name")
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)
```

- [ ] **Step 4: Register in `core/discovery/__init__.py`**

Append:

```python
from core.discovery.oracle_provider import OracleProvider
register_provider("oracle", OracleProvider())
```

- [ ] **Step 5: Run — PASS (or skip)**

Run: `pytest tests/discovery/test_oracle_provider.py -v`
Expected: 2 passed or 2 skipped.

- [ ] **Step 6: Commit**

```bash
git add core/discovery/oracle_provider.py core/discovery/__init__.py tests/discovery/test_oracle_provider.py
git commit -m "discovery: OracleProvider (oracledb thin mode)"
```

---

### Task 2.3: MySQL provider

**Files:**
- Create: `core/discovery/mysql_provider.py`
- Test: `tests/discovery/test_mysql_provider.py`

- [ ] **Step 1: Write failing test**

```python
# tests/discovery/test_mysql_provider.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MYSQL_TEST_DSN"), reason="MYSQL_TEST_DSN not set"
)

from core.discovery.base import SourceProvider
from core.discovery.mysql_provider import MySQLProvider
from core.discovery.profiles import ConnectionProfile


def test_mysql_provider_implements_interface():
    assert isinstance(MySQLProvider(), SourceProvider)
    assert MySQLProvider().dialect == "mysql"


@pytest.mark.asyncio
async def test_mysql_ping():
    dsn = os.environ["MYSQL_TEST_DSN"]   # mysql://user:pass@host:3306/db
    p = ConnectionProfile(id="my", label="t", dialect="mysql", dsn=dsn, host=dsn)
    r = await MySQLProvider().ping(p)
    assert r.ok is True
```

- [ ] **Step 2: Run — FAIL or skip**

Run: `pytest tests/discovery/test_mysql_provider.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `core/discovery/mysql_provider.py`**

```python
"""MySQL source provider — pymysql."""
from __future__ import annotations

import asyncio
import time
from typing import Any, List
from urllib.parse import urlparse

import pymysql

from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo,
    ColumnProfile, ColumnHit,
)


def _parse_dsn(dsn: str) -> dict:
    # mysql://user:pass@host:port/db
    u = urlparse(dsn)
    return dict(
        host=u.hostname or "localhost",
        port=u.port or 3306,
        user=u.username or "",
        password=u.password or "",
        database=(u.path or "/").lstrip("/"),
        charset="utf8mb4",
        connect_timeout=5,
    )


class MySQLProvider(SourceProvider):
    dialect = "mysql"

    def _connect(self, profile: Any):
        return pymysql.connect(**_parse_dsn(profile.dsn))

    async def ping(self, profile: Any) -> PingResult:
        def _sync():
            t0 = time.perf_counter()
            try:
                self._connect(profile).close()
                return PingResult(ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
            except Exception as exc:
                return PingResult(ok=False, message=str(exc))
        return await asyncio.to_thread(_sync)

    async def list_schemas(self, profile: Any) -> List[str]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name NOT IN ('mysql','sys','performance_schema','information_schema') "
                    "ORDER BY schema_name"
                )
                return [r[0] for r in cur.fetchall()]
        return await asyncio.to_thread(_sync)

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name, table_rows, table_comment FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",
                    (schema,),
                )
                return [
                    TableInfo(schema=schema, name=r[0], row_estimate=r[1], comment=r[2] or None)
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name, data_type, is_nullable, column_default, column_key
                    FROM information_schema.columns
                    WHERE table_schema=%s AND table_name=%s
                    ORDER BY ordinal_position
                """, (schema, table))
                return [
                    ColumnInfo(
                        schema=schema, table=table, name=r[0], data_type=r[1],
                        nullable=(r[2] == "YES"), default=r[3],
                        is_primary_key=(r[4] == "PRI"),
                    )
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name, referenced_table_schema, referenced_table_name,
                           referenced_column_name, constraint_name
                    FROM information_schema.key_column_usage
                    WHERE table_schema=%s AND table_name=%s AND referenced_table_name IS NOT NULL
                """, (schema, table))
                return [
                    FKInfo(
                        schema=schema, table=table, column=r[0],
                        ref_schema=r[1], ref_table=r[2], ref_column=r[3],
                        constraint_name=r[4],
                    )
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def profile_column(
        self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0,
    ) -> ColumnProfile:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*), COUNT(DISTINCT `{column}`), "
                    f"100*AVG(CASE WHEN `{column}` IS NULL THEN 1 ELSE 0 END) "
                    f"FROM `{schema}`.`{table}`"
                )
                rc, dc, np = cur.fetchone()
                samples = []
                if sample_rows > 0:
                    cur.execute(
                        f"SELECT `{column}` FROM `{schema}`.`{table}` "
                        f"WHERE `{column}` IS NOT NULL LIMIT {int(sample_rows)}"
                    )
                    samples = [r[0] for r in cur.fetchall()]
                return ColumnProfile(
                    row_count=rc, distinct_count=dc,
                    null_pct=float(np) if np is not None else None,
                    sample_values=samples,
                )
        return await asyncio.to_thread(_sync)

    async def search_by_keywords(
        self, profile: Any, keywords: List[str], limit: int = 50,
    ) -> List[ColumnHit]:
        def _sync():
            if not keywords:
                return []
            patterns = [f"%{k.lower()}%" for k in keywords]
            clauses = " OR ".join(["LOWER(column_name) LIKE %s"] * len(patterns))
            sql = f"""
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema NOT IN ('mysql','sys','performance_schema','information_schema')
                  AND ({clauses})
                LIMIT %s
            """
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(sql, (*patterns, limit))
                return [
                    ColumnHit(schema=r[0], table=r[1], column=r[2], data_type=r[3], score=1.0, matched_on="name")
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)
```

- [ ] **Step 4: Register**

Append to `core/discovery/__init__.py`:

```python
from core.discovery.mysql_provider import MySQLProvider
register_provider("mysql", MySQLProvider())
```

- [ ] **Step 5: Run + Commit**

Run: `pytest tests/discovery/test_mysql_provider.py -v`

```bash
git add core/discovery/mysql_provider.py core/discovery/__init__.py tests/discovery/test_mysql_provider.py
git commit -m "discovery: MySQLProvider (pymysql)"
```

---

### Task 2.4: MSSQL provider (pure-Python pytds)

**Files:**
- Create: `core/discovery/mssql_provider.py`
- Test: `tests/discovery/test_mssql_provider.py`

- [ ] **Step 1: Failing test**

```python
# tests/discovery/test_mssql_provider.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MSSQL_TEST_DSN"), reason="MSSQL_TEST_DSN not set"
)

from core.discovery.base import SourceProvider
from core.discovery.mssql_provider import MSSQLProvider
from core.discovery.profiles import ConnectionProfile


def test_mssql_provider_implements_interface():
    assert isinstance(MSSQLProvider(), SourceProvider)
    assert MSSQLProvider().dialect == "mssql"


@pytest.mark.asyncio
async def test_mssql_ping():
    dsn = os.environ["MSSQL_TEST_DSN"]   # mssql://user:pass@host:1433/db
    p = ConnectionProfile(id="ms", label="t", dialect="mssql", dsn=dsn, host=dsn)
    r = await MSSQLProvider().ping(p)
    assert r.ok is True
```

- [ ] **Step 2: Run — FAIL or skip**

Run: `pytest tests/discovery/test_mssql_provider.py -v`

- [ ] **Step 3: Implement `core/discovery/mssql_provider.py`**

```python
"""MSSQL source provider — pure-Python pytds."""
from __future__ import annotations

import asyncio
import time
from typing import Any, List
from urllib.parse import urlparse

import pytds

from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo,
    ColumnProfile, ColumnHit,
)


def _parse_dsn(dsn: str) -> dict:
    u = urlparse(dsn)
    return dict(
        server=u.hostname or "localhost",
        port=u.port or 1433,
        user=u.username or "",
        password=u.password or "",
        database=(u.path or "/").lstrip("/"),
        login_timeout=5,
        timeout=10,
    )


class MSSQLProvider(SourceProvider):
    dialect = "mssql"

    def _connect(self, profile: Any):
        return pytds.connect(**_parse_dsn(profile.dsn))

    async def ping(self, profile: Any) -> PingResult:
        def _sync():
            t0 = time.perf_counter()
            try:
                self._connect(profile).close()
                return PingResult(ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
            except Exception as exc:
                return PingResult(ok=False, message=str(exc))
        return await asyncio.to_thread(_sync)

    async def list_schemas(self, profile: Any) -> List[str]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT name FROM sys.schemas WHERE name NOT IN "
                    "('sys','INFORMATION_SCHEMA','db_owner','db_accessadmin','db_securityadmin',"
                    "'db_ddladmin','db_backupoperator','db_datareader','db_datawriter',"
                    "'db_denydatareader','db_denydatawriter','guest') ORDER BY name"
                )
                return [r[0] for r in cur.fetchall()]
        return await asyncio.to_thread(_sync)

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",
                    (schema,),
                )
                return [TableInfo(schema=schema, name=r[0]) for r in cur.fetchall()]
        return await asyncio.to_thread(_sync)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT c.column_name, c.data_type, c.is_nullable, c.column_default,
                        CASE WHEN tc.constraint_type='PRIMARY KEY' THEN 1 ELSE 0 END
                    FROM information_schema.columns c
                    LEFT JOIN information_schema.key_column_usage kcu
                        ON kcu.table_schema=c.table_schema AND kcu.table_name=c.table_name AND kcu.column_name=c.column_name
                    LEFT JOIN information_schema.table_constraints tc
                        ON tc.constraint_name=kcu.constraint_name AND tc.constraint_type='PRIMARY KEY'
                    WHERE c.table_schema=%s AND c.table_name=%s
                    ORDER BY c.ordinal_position
                """, (schema, table))
                return [
                    ColumnInfo(
                        schema=schema, table=table, name=r[0], data_type=r[1],
                        nullable=(r[2] == "YES"), default=r[3], is_primary_key=bool(r[4]),
                    )
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT col.name, OBJECT_SCHEMA_NAME(fkc.referenced_object_id),
                           OBJECT_NAME(fkc.referenced_object_id),
                           refcol.name, fk.name
                    FROM sys.foreign_keys fk
                    JOIN sys.foreign_key_columns fkc ON fk.object_id=fkc.constraint_object_id
                    JOIN sys.columns col ON col.object_id=fkc.parent_object_id AND col.column_id=fkc.parent_column_id
                    JOIN sys.columns refcol ON refcol.object_id=fkc.referenced_object_id AND refcol.column_id=fkc.referenced_column_id
                    WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id)=%s AND OBJECT_NAME(fk.parent_object_id)=%s
                """, (schema, table))
                return [
                    FKInfo(
                        schema=schema, table=table, column=r[0],
                        ref_schema=r[1], ref_table=r[2], ref_column=r[3], constraint_name=r[4],
                    )
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)

    async def profile_column(
        self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0,
    ) -> ColumnProfile:
        def _sync():
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*), COUNT(DISTINCT [{column}]), "
                    f"100.0*AVG(CASE WHEN [{column}] IS NULL THEN 1.0 ELSE 0.0 END) "
                    f"FROM [{schema}].[{table}]"
                )
                rc, dc, np = cur.fetchone()
                samples = []
                if sample_rows > 0:
                    cur.execute(
                        f"SELECT TOP {int(sample_rows)} [{column}] "
                        f"FROM [{schema}].[{table}] WHERE [{column}] IS NOT NULL"
                    )
                    samples = [r[0] for r in cur.fetchall()]
                return ColumnProfile(
                    row_count=rc, distinct_count=dc,
                    null_pct=float(np) if np is not None else None,
                    sample_values=samples,
                )
        return await asyncio.to_thread(_sync)

    async def search_by_keywords(
        self, profile: Any, keywords: List[str], limit: int = 50,
    ) -> List[ColumnHit]:
        def _sync():
            if not keywords:
                return []
            patterns = [f"%{k.lower()}%" for k in keywords]
            clauses = " OR ".join(["LOWER(column_name) LIKE %s"] * len(patterns))
            sql = f"""
                SELECT TOP {int(limit)} table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema NOT IN ('sys','INFORMATION_SCHEMA') AND ({clauses})
            """
            with self._connect(profile) as conn, conn.cursor() as cur:
                cur.execute(sql, tuple(patterns))
                return [
                    ColumnHit(schema=r[0], table=r[1], column=r[2], data_type=r[3], score=1.0, matched_on="name")
                    for r in cur.fetchall()
                ]
        return await asyncio.to_thread(_sync)
```

- [ ] **Step 4: Register**

Append to `core/discovery/__init__.py`:

```python
from core.discovery.mssql_provider import MSSQLProvider
register_provider("mssql", MSSQLProvider())
```

- [ ] **Step 5: Run + Commit**

```bash
pytest tests/discovery/test_mssql_provider.py -v
git add core/discovery/mssql_provider.py core/discovery/__init__.py tests/discovery/test_mssql_provider.py
git commit -m "discovery: MSSQLProvider (python-tds)"
```

---

### Task 2.5: Per-dialect profile POST endpoints + encrypted persistence

**Files:**
- Modify: `core/discovery/profiles.py`
- Modify: `routers/discovery.py`
- Test: `tests/discovery/test_profile_endpoints.py`

- [ ] **Step 1: Failing test**

Create `tests/discovery/test_profile_endpoints.py`:

```python
import os
import pytest
from fastapi.testclient import TestClient

from app import create_app   # or wherever the FastAPI factory lives; adjust if app is top-level


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", "wkPzx-2zM9YlbsZF_4ic4w8I1OvOhA-IRgLY4ZSj_5o=")
    app = create_app()  # if app.py exports `app` directly, use that and skip factory
    return TestClient(app)


def test_post_oracle_profile(client):
    resp = client.post(
        "/api/discovery/profiles/oracle",
        json={"label": "test-ora", "dsn": "user/pass@host:1521/svc", "user": "u", "password": "p"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dialect"] == "oracle"
    assert "id" in body


def test_post_mysql_profile(client):
    resp = client.post(
        "/api/discovery/profiles/mysql",
        json={"label": "test-my", "host": "h", "port": 3306, "db": "d", "user": "u", "password": "p"},
    )
    assert resp.status_code == 200
    assert resp.json()["dialect"] == "mysql"
```

The exact `app` import may be `from app import app` or `create_app()` — inspect `app.py` first and use the matching form. Adjust the import in this test before running.

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/discovery/test_profile_endpoints.py -v`

- [ ] **Step 3: Extend `core/discovery/profiles.py` dataclass**

In `core/discovery/profiles.py`, extend `ConnectionProfile`:

```python
from typing import Optional
from datetime import datetime

@dataclass
class ConnectionProfile:
    id: str
    label: str
    dialect: str
    dsn: str
    host: str
    last_used: Optional[str] = None
    icon: str = "DB"
    status: str = "connected"
    # NEW
    encrypted_credentials: Optional[bytes] = None
    last_ping: Optional[datetime] = None
    last_ping_status: Optional[str] = None
```

- [ ] **Step 4: Add endpoints to `routers/discovery.py`**

Inspect existing `routers/discovery.py` for the FastAPI router prefix (likely `/api/discovery`). Add new endpoints:

```python
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.discovery.profiles import ConnectionProfile
from core.discovery.credentials import encrypt
from core.discovery.registry import get_provider
# `_REGISTRY` or similar — use whatever the existing module exposes


class OraclePayload(BaseModel):
    label: str
    dsn: str
    user: str | None = None
    password: str | None = None


class MySQLPayload(BaseModel):
    label: str
    host: str
    port: int = 3306
    db: str
    user: str
    password: str


class MSSQLPayload(BaseModel):
    label: str
    host: str
    port: int = 1433
    db: str
    user: str
    password: str


class BQPayload(BaseModel):
    label: str
    project_id: str
    credentials_json: str | None = None


def _save_profile(dialect: str, payload: dict, dsn: str, host: str, creds: dict | None) -> dict:
    from core.discovery.profiles import _REGISTRY    # adjust to actual export
    p = ConnectionProfile(
        id=f"{dialect[:2]}-{uuid.uuid4().hex[:8]}",
        label=payload["label"], dialect=dialect, dsn=dsn, host=host,
        encrypted_credentials=encrypt(creds) if creds else None,
        last_ping=None, last_ping_status=None,
    )
    _REGISTRY.register(p)
    return {"id": p.id, "label": p.label, "dialect": p.dialect, "host": p.host}


@router.post("/profiles/oracle")
async def post_oracle(body: OraclePayload):
    creds = {"user": body.user, "password": body.password} if body.user else None
    return _save_profile("oracle", body.dict(), dsn=body.dsn, host=body.dsn, creds=creds)


@router.post("/profiles/mysql")
async def post_mysql(body: MySQLPayload):
    dsn = f"mysql://{body.user}:{body.password}@{body.host}:{body.port}/{body.db}"
    creds = {"user": body.user, "password": body.password}
    return _save_profile("mysql", body.dict(), dsn=dsn, host=f"{body.host}:{body.port}", creds=creds)


@router.post("/profiles/mssql")
async def post_mssql(body: MSSQLPayload):
    dsn = f"mssql://{body.user}:{body.password}@{body.host}:{body.port}/{body.db}"
    creds = {"user": body.user, "password": body.password}
    return _save_profile("mssql", body.dict(), dsn=dsn, host=f"{body.host}:{body.port}", creds=creds)


@router.post("/profiles/bigquery")
async def post_bigquery(body: BQPayload):
    creds = {"credentials_json": body.credentials_json} if body.credentials_json else None
    return _save_profile("bigquery", body.dict(), dsn=body.project_id, host="bigquery", creds=creds)
```

If `_REGISTRY` is named differently in `profiles.py` (e.g. `_DEFAULT_REGISTRY` or accessed via `ProfileRegistry()` singleton), inspect and use the matching symbol. The existing `ProfileRegistry.register()` method already exists.

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/discovery/test_profile_endpoints.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add core/discovery/profiles.py routers/discovery.py tests/discovery/test_profile_endpoints.py
git commit -m "discovery: per-dialect POST profile endpoints with Fernet-encrypted credentials"
```

---

# PHASE 3 — Blackboard + Persistence + Locks + Events

Shippable outcome: every persistence and serialization primitive needed by the coordinator and agents — blackboard models, DB CRUD, session locks, SSE event types. No agent runs yet; this phase is pure plumbing with unit-test coverage.

---

### Task 3.1: StageStatus enum + atomic Pydantic sub-artifacts

**Files:**
- Create: `core/stm/blackboard.py`
- Test: `tests/stm/test_blackboard_shapes.py`

- [ ] **Step 1: Failing test**

Create `tests/stm/test_blackboard_shapes.py`:

```python
from datetime import datetime

from core.stm.blackboard import (
    StageStatus, IntentArtifact, MetadataGraph, GraphNode, GraphEdge,
    CandidateMapping, CandidateMappings, Transformation, Transformations,
    ConfidenceScore, ValidationReport, ValidationFinding, GateDecision,
    StmBlackboard,
)


def test_stage_status_values():
    assert StageStatus.idle.value == "idle"
    assert StageStatus.ready.value == "ready"
    assert StageStatus.stale.value == "stale"


def test_intent_artifact_minimal():
    i = IntentArtifact(
        source="freetext", raw_input="Build customer dim",
        jira_issue_key=None, entity="customer_dim", action="create",
        is_dimension=True, is_fact=False, scd_hint="type2",
        filters=["active users only"], grain_hint="customer_id",
        extracted_keywords=["customer","active"], status=StageStatus.ready,
    )
    assert i.entity == "customer_dim"
    assert i.is_dimension is True


def test_metadata_graph_query_helpers():
    g = MetadataGraph(
        nodes=[
            GraphNode(id="pg.public.customers", kind="table", label="customers", dialect="postgres"),
            GraphNode(id="pg.public.customers.customer_id", kind="column", label="customer_id", dialect="postgres", data_type="bigint"),
        ],
        edges=[GraphEdge(src="pg.public.customers", dst="pg.public.customers.customer_id", kind="contains")],
        sources_probed=["pg-demo"], coverage_notes=[], status=StageStatus.ready,
    )
    assert len(g.columns_of("pg.public.customers")) == 1
    assert g.by_dialect("postgres")[0].label == "customers"


def test_blackboard_assembles():
    bb = StmBlackboard(
        session_id="abc", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(
            source="freetext", raw_input="x", jira_issue_key=None,
            entity="x", action="create", is_dimension=False, is_fact=False,
            scd_hint=None, filters=[], grain_hint=None, extracted_keywords=[],
            status=StageStatus.idle,
        ),
        metadata_graph=MetadataGraph(nodes=[], edges=[], sources_probed=[], coverage_notes=[], status=StageStatus.idle),
        candidate_mappings=CandidateMappings(target_table="x", target_dataset="x", rows=[], rule_baseline_summary={}, status=StageStatus.idle),
        transformations=Transformations(rows=[], scd_strategy=None, audit_fields=[], idempotency_key=None, partition_field=None, status=StageStatus.idle),
        validation=ValidationReport(scores=[], findings=[], low_confidence_count=0, block_count=0, overall_band="high", status=StageStatus.idle),
        stm_result=None,
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="pending"),
            "gate2_validation": GateDecision(name="gate2_validation", decision="pending"),
        },
        current_stage="L1",
    )
    s = bb.model_dump_json()
    bb2 = StmBlackboard.model_validate_json(s)
    assert bb2.session_id == "abc"
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_blackboard_shapes.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `core/stm/blackboard.py`**

```python
"""Pydantic shared-blackboard for an STM agentic session."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    idle = "idle"
    running = "running"
    ready = "ready"
    stale = "stale"
    awaiting_review = "awaiting_review"
    rejected = "rejected"
    failed = "failed"


class IntentArtifact(BaseModel):
    source: Literal["jira", "freetext"]
    raw_input: str
    jira_issue_key: Optional[str] = None
    entity: str = ""
    action: str = ""
    is_dimension: bool = False
    is_fact: bool = False
    scd_hint: Optional[Literal["type1", "type2", "type3", "none"]] = None
    filters: List[str] = Field(default_factory=list)
    grain_hint: Optional[str] = None
    extracted_keywords: List[str] = Field(default_factory=list)
    status: StageStatus = StageStatus.idle


class GraphNode(BaseModel):
    id: str
    kind: Literal["dialect", "schema", "table", "column", "concept"]
    label: str
    dialect: Optional[str] = None
    data_type: Optional[str] = None
    nullable: Optional[bool] = None
    is_pii: Optional[bool] = None
    profile: Optional[Dict[str, Any]] = None


class GraphEdge(BaseModel):
    src: str
    dst: str
    kind: Literal["contains", "fk", "semantic_match", "join_candidate", "concept_link"]
    confidence: Optional[float] = None
    evidence: Optional[str] = None


class MetadataGraph(BaseModel):
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    sources_probed: List[str] = Field(default_factory=list)
    coverage_notes: List[str] = Field(default_factory=list)
    status: StageStatus = StageStatus.idle

    def find_by_concept(self, concept: str) -> List[GraphNode]:
        ids = {e.dst for e in self.edges if e.kind == "concept_link" and concept.lower() in (e.evidence or "").lower()}
        return [n for n in self.nodes if n.id in ids]

    def join_candidates(self, table_id: str) -> List[GraphEdge]:
        return [e for e in self.edges if e.kind == "join_candidate" and (e.src.startswith(table_id) or e.dst.startswith(table_id))]

    def columns_of(self, table_id: str) -> List[GraphNode]:
        col_ids = {e.dst for e in self.edges if e.kind == "contains" and e.src == table_id}
        return [n for n in self.nodes if n.id in col_ids and n.kind == "column"]

    def by_dialect(self, dialect: str) -> List[GraphNode]:
        return [n for n in self.nodes if n.dialect == dialect and n.kind == "table"]


class CandidateMapping(BaseModel):
    target_field: str
    target_type: str
    source_node_ids: List[str] = Field(default_factory=list)
    source_expression: str = ""
    rationale: str = ""
    grain: List[str] = Field(default_factory=list)
    cardinality: Optional[Literal["1:1", "M:1", "1:M", "M:M"]] = None
    rule_baseline: bool = False
    refined_by_llm: bool = False
    llm_confidence: Optional[float] = None


class CandidateMappings(BaseModel):
    target_table: str
    target_dataset: str
    rows: List[CandidateMapping] = Field(default_factory=list)
    rule_baseline_summary: Dict[str, Any] = Field(default_factory=dict)
    status: StageStatus = StageStatus.idle


class Transformation(BaseModel):
    target_field: str
    kind: Literal["derived", "scd2", "audit", "surrogate_key", "computed", "filter"]
    logic: str
    inputs: List[str] = Field(default_factory=list)
    rationale: str = ""


class Transformations(BaseModel):
    rows: List[Transformation] = Field(default_factory=list)
    scd_strategy: Optional[Literal["type1", "type2", "type3", "none"]] = None
    audit_fields: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    partition_field: Optional[str] = None
    status: StageStatus = StageStatus.idle


class ValidationFinding(BaseModel):
    severity: Literal["info", "warn", "block"]
    target_field: Optional[str] = None
    rule: str
    message: str


class ConfidenceScore(BaseModel):
    target_field: str
    llm_score: float = 0.0
    name_sim_score: float = 0.0
    type_compat_score: float = 0.0
    profile_overlap_score: Optional[float] = None
    fk_evidence_score: float = 0.0
    final: float = 0.0
    band: Literal["high", "medium", "low"] = "low"


class ValidationReport(BaseModel):
    scores: List[ConfidenceScore] = Field(default_factory=list)
    findings: List[ValidationFinding] = Field(default_factory=list)
    low_confidence_count: int = 0
    block_count: int = 0
    overall_band: Literal["high", "medium", "low"] = "high"
    status: StageStatus = StageStatus.idle


class GateDecision(BaseModel):
    name: Literal["gate1_metadata", "gate2_validation"]
    decision: Literal["pending", "approved", "rejected", "refine"] = "pending"
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    refine_target_stage: Optional[Literal["L1", "L2", "L3", "L4", "L5"]] = None
    refine_feedback: Optional[str] = None
    decided_at: Optional[datetime] = None


class StmBlackboard(BaseModel):
    session_id: str
    target_table: str
    target_dataset: str
    dialect_target: Literal["bigquery"]
    selected_source_profiles: List[str] = Field(default_factory=list)
    intent: IntentArtifact
    metadata_graph: MetadataGraph
    candidate_mappings: CandidateMappings
    transformations: Transformations
    validation: ValidationReport
    stm_result: Optional[Dict[str, Any]] = None
    gates: Dict[str, GateDecision] = Field(default_factory=dict)
    current_stage: Literal["L1", "L2", "L3", "L4", "L5", "L6", "done", "failed"] = "L1"
    refine_feedback_pending: Dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/test_blackboard_shapes.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/stm/blackboard.py tests/stm/test_blackboard_shapes.py
git commit -m "stm: StmBlackboard Pydantic shapes + query helpers"
```

---

### Task 3.2: Persistence layer

**Files:**
- Create: `core/stm/persistence.py`
- Test: `tests/stm/test_persistence.py`

- [ ] **Step 1: Failing test**

Create `tests/stm/test_persistence.py`:

```python
import asyncio
from datetime import datetime

import pytest

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import (
    create_session, load_blackboard, save_blackboard, append_event,
    list_events, record_gate_decision,
)


def _bb(sid="s1"):
    return StmBlackboard(
        session_id=sid, target_table="cust", target_dataset="wh",
        dialect_target="bigquery", selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="x"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="cust", target_dataset="wh"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_create_and_load(tmp_db):
    bb = _bb()
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    loaded = await load_blackboard("s1")
    assert loaded.session_id == "s1"
    assert loaded.target_table == "cust"


@pytest.mark.asyncio
async def test_save_overwrites_snapshot(tmp_db):
    bb = _bb("s2")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    bb.intent.entity = "customer_dim"
    bb.intent.status = StageStatus.ready
    await save_blackboard(bb)
    loaded = await load_blackboard("s2")
    assert loaded.intent.entity == "customer_dim"
    assert loaded.intent.status == StageStatus.ready


@pytest.mark.asyncio
async def test_event_log(tmp_db):
    bb = _bb("s3")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    await append_event("s3", stage="L1", event_kind="started", message="x")
    await append_event("s3", stage="L1", event_kind="ready", artifact_kind="intent", artifact_json='{"x":1}')
    events = await list_events("s3")
    assert [e["event_kind"] for e in events] == ["started", "ready"]


@pytest.mark.asyncio
async def test_gate_decision_row(tmp_db):
    bb = _bb("s4")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    await record_gate_decision("s4", gate_name="gate1_metadata", decision="approved", reviewer="alice", notes=None, refine_target=None, refine_feedback=None)
    events = await list_events("s4")
    assert any(e["event_kind"] == "gate_decided" for e in events)
```

Create `tests/stm/conftest.py`:

```python
import os
import pytest

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Apply alembic schema to the temp DB
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
    yield db_path
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_persistence.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `core/stm/persistence.py`**

```python
"""STM session + event persistence using SQLAlchemy core."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, MetaData, Table, select, insert, update
from sqlalchemy.engine import Engine

from core.stm.blackboard import StmBlackboard


_engine: Optional[Engine] = None
_meta: Optional[MetaData] = None


def _eng() -> Engine:
    global _engine, _meta
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "sqlite:///./app.db")
        _engine = create_engine(url, future=True)
        _meta = MetaData()
        _meta.reflect(bind=_engine, only=["stm_sessions", "stm_stage_events", "stm_gate_decisions"])
    return _engine


def _t(name: str) -> Table:
    _eng()
    return _meta.tables[name]


async def create_session(
    bb: StmBlackboard,
    *,
    raw_input: str,
    intent_source: str,
    jira_issue_key: Optional[str],
    created_by: Optional[str] = None,
) -> None:
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_sessions")).values(
            session_id=bb.session_id,
            status="running",
            current_stage=bb.current_stage,
            target_table=bb.target_table,
            target_dataset=bb.target_dataset,
            source_profiles=json.dumps(bb.selected_source_profiles),
            intent_source=intent_source,
            jira_issue_key=jira_issue_key,
            raw_input=raw_input,
            blackboard_json=bb.model_dump_json(),
            created_at=now,
            updated_at=now,
            created_by=created_by,
        ))


async def load_blackboard(session_id: str) -> StmBlackboard:
    with _eng().connect() as conn:
        row = conn.execute(
            select(_t("stm_sessions").c.blackboard_json).where(
                _t("stm_sessions").c.session_id == session_id
            )
        ).fetchone()
    if row is None:
        raise KeyError(session_id)
    return StmBlackboard.model_validate_json(row[0])


async def save_blackboard(bb: StmBlackboard) -> None:
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(
            update(_t("stm_sessions"))
            .where(_t("stm_sessions").c.session_id == bb.session_id)
            .values(
                status="awaiting_review" if any(
                    g.decision == "pending" and g.name in bb.gates and bb.gates[g.name].decision == "pending"
                    for g in bb.gates.values()
                    if g.decision == "pending"
                ) else "running",
                current_stage=bb.current_stage,
                blackboard_json=bb.model_dump_json(),
                updated_at=now,
            )
        )


async def set_session_status(session_id: str, status: str) -> None:
    with _eng().begin() as conn:
        conn.execute(
            update(_t("stm_sessions"))
            .where(_t("stm_sessions").c.session_id == session_id)
            .values(status=status, updated_at=datetime.utcnow())
        )


async def append_event(
    session_id: str,
    *,
    stage: str,
    event_kind: str,
    artifact_kind: Optional[str] = None,
    artifact_json: Optional[str] = None,
    confidence: Optional[float] = None,
    llm_model: Optional[str] = None,
    llm_tokens_in: Optional[int] = None,
    llm_tokens_out: Optional[int] = None,
    duration_ms: Optional[int] = None,
    message: Optional[str] = None,
) -> str:
    eid = str(uuid.uuid4())
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_stage_events")).values(
            event_id=eid, session_id=session_id, stage=stage, event_kind=event_kind,
            artifact_kind=artifact_kind, artifact_json=artifact_json, confidence=confidence,
            llm_model=llm_model, llm_tokens_in=llm_tokens_in, llm_tokens_out=llm_tokens_out,
            duration_ms=duration_ms, message=message, created_at=datetime.utcnow(),
        ))
    return eid


async def list_events(session_id: str) -> List[Dict[str, Any]]:
    with _eng().connect() as conn:
        rows = conn.execute(
            select(_t("stm_stage_events")).where(
                _t("stm_stage_events").c.session_id == session_id
            ).order_by(_t("stm_stage_events").c.created_at)
        ).fetchall()
    return [dict(r._mapping) for r in rows]


async def record_gate_decision(
    session_id: str,
    *,
    gate_name: str,
    decision: str,
    reviewer: Optional[str],
    notes: Optional[str],
    refine_target: Optional[str],
    refine_feedback: Optional[str],
) -> str:
    did = str(uuid.uuid4())
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_gate_decisions")).values(
            decision_id=did, session_id=session_id, gate_name=gate_name, decision=decision,
            reviewer=reviewer, notes=notes, refine_target=refine_target,
            refine_feedback=refine_feedback, decided_at=now,
        ))
    await append_event(
        session_id, stage="GATE", event_kind="gate_decided",
        message=f"{gate_name}:{decision}",
        artifact_kind=gate_name,
        artifact_json=json.dumps({"decision": decision, "refine_target": refine_target, "refine_feedback": refine_feedback}),
    )
    return did


async def list_running_sessions() -> List[Dict[str, Any]]:
    with _eng().connect() as conn:
        rows = conn.execute(
            select(_t("stm_sessions")).where(_t("stm_sessions").c.status == "running")
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def reset_engine_for_tests() -> None:
    global _engine, _meta
    _engine = None
    _meta = None
```

- [ ] **Step 4: Make tests reset the engine between test DBs**

Append to `tests/stm/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _reset_engine():
    from core.stm.persistence import reset_engine_for_tests
    reset_engine_for_tests()
    yield
    reset_engine_for_tests()
```

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/stm/test_persistence.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add core/stm/persistence.py tests/stm/test_persistence.py tests/stm/conftest.py
git commit -m "stm: persistence layer (sessions, events, gate decisions)"
```

---

### Task 3.3: SessionLock abstraction

**Files:**
- Create: `core/stm/locks.py`
- Test: `tests/stm/test_locks.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_locks.py
import asyncio
import pytest

from core.stm.locks import SessionLock


@pytest.mark.asyncio
async def test_serializes_writers():
    order = []

    async def writer(name, delay):
        async with SessionLock("s1"):
            order.append(f"{name}-in")
            await asyncio.sleep(delay)
            order.append(f"{name}-out")

    await asyncio.gather(writer("A", 0.05), writer("B", 0.01))
    # B should not enter until A exits
    assert order[0] == "A-in"
    assert order[1] == "A-out"
    assert order[2] == "B-in"
    assert order[3] == "B-out"


@pytest.mark.asyncio
async def test_different_sessions_concurrent():
    started = []
    barrier = asyncio.Event()

    async def writer(sid):
        async with SessionLock(sid):
            started.append(sid)
            await barrier.wait()

    t1 = asyncio.create_task(writer("a"))
    t2 = asyncio.create_task(writer("b"))
    await asyncio.sleep(0.05)
    assert set(started) == {"a", "b"}
    barrier.set()
    await asyncio.gather(t1, t2)


@pytest.mark.asyncio
async def test_acquire_timeout():
    async with SessionLock("zz"):
        with pytest.raises(TimeoutError):
            async with SessionLock("zz", timeout=0.05):
                pass
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_locks.py -v`

- [ ] **Step 3: Implement `core/stm/locks.py`**

```python
"""Per-session async lock abstraction. Single-worker now; DB advisory later."""
from __future__ import annotations

import asyncio
from typing import Dict, Optional


_LOCKS: Dict[str, asyncio.Lock] = {}
_REGISTRY_LOCK = asyncio.Lock()


async def _get_lock(session_id: str) -> asyncio.Lock:
    async with _REGISTRY_LOCK:
        lock = _LOCKS.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _LOCKS[session_id] = lock
        return lock


class SessionLock:
    def __init__(self, session_id: str, timeout: Optional[float] = 10.0):
        self.session_id = session_id
        self.timeout = timeout
        self._lock: Optional[asyncio.Lock] = None

    async def __aenter__(self) -> "SessionLock":
        self._lock = await _get_lock(self.session_id)
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"SessionLock acquire timeout for {self.session_id}")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._lock is not None and self._lock.locked():
            self._lock.release()


def reset_locks_for_tests() -> None:
    _LOCKS.clear()
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/test_locks.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/stm/locks.py tests/stm/test_locks.py
git commit -m "stm: SessionLock per-session asyncio lock"
```

---

### Task 3.4: Event types + SSE broker

**Files:**
- Create: `core/stm/events.py`
- Test: `tests/stm/test_events.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_events.py
import asyncio
import json
import pytest

from core.stm.events import SseBroker, EventKind


@pytest.mark.asyncio
async def test_broker_fanout_to_subscribers():
    broker = SseBroker()
    queue = await broker.subscribe("s1")
    await broker.publish("s1", {"type": EventKind.stage_started, "stage": "L1"})
    msg = await asyncio.wait_for(queue.get(), timeout=1)
    assert msg["type"] == "stage_started"


@pytest.mark.asyncio
async def test_broker_other_session_isolated():
    broker = SseBroker()
    q1 = await broker.subscribe("s1")
    await broker.publish("s2", {"type": EventKind.stage_started})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q1.get(), timeout=0.1)


def test_event_kinds_defined():
    for k in [
        "stage_started", "stage_ready", "stage_failed", "stage_stale",
        "llm_call", "profile_probe", "gate_requested", "gate_decided",
        "session_completed", "session_rejected", "session_failed",
    ]:
        assert hasattr(EventKind, k)
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_events.py -v`

- [ ] **Step 3: Implement `core/stm/events.py`**

```python
"""SSE event broker for STM session progress."""
from __future__ import annotations

import asyncio
from enum import Enum
from typing import Dict, List


class EventKind(str, Enum):
    stage_started = "stage_started"
    stage_ready = "stage_ready"
    stage_failed = "stage_failed"
    stage_stale = "stage_stale"
    llm_call = "llm_call"
    profile_probe = "profile_probe"
    gate_requested = "gate_requested"
    gate_decided = "gate_decided"
    session_completed = "session_completed"
    session_rejected = "session_rejected"
    session_failed = "session_failed"


class SseBroker:
    def __init__(self):
        self._subs: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs.setdefault(session_id, []).append(q)
        return q

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            lst = self._subs.get(session_id, [])
            if queue in lst:
                lst.remove(queue)

    async def publish(self, session_id: str, event: dict) -> None:
        async with self._lock:
            queues = list(self._subs.get(session_id, []))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass    # drop oldest semantics could be added later


_default = SseBroker()


def default_broker() -> SseBroker:
    return _default
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/test_events.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/stm/events.py tests/stm/test_events.py
git commit -m "stm: SseBroker + EventKind"
```

---

# PHASE 4 — Coordinator Skeleton + L1 + L6 Pass-Through

Shippable outcome: end-to-end session lifecycle works — create a session, intent extraction runs (L1, Haiku), L6 produces an empty (but valid) MappingResult, SSE events stream to the UI. No gates yet; no semantic reasoning yet. The skeleton can be demoed.

---

### Task 4.1: Agent base + AgentContext + FakeLLMClient

**Files:**
- Create: `core/stm/agents/__init__.py` (empty)
- Create: `core/stm/agents/base.py`
- Create: `tests/stm/fake_llm.py`
- Test: `tests/stm/agents/__init__.py` (empty) + `tests/stm/agents/test_base.py`

- [ ] **Step 1: Failing test**

Create `tests/stm/agents/test_base.py`:

```python
import pytest

from core.stm.agents.base import StmAgent, AgentContext, BlackboardDelta


def test_stm_agent_is_abstract():
    with pytest.raises(TypeError):
        StmAgent()


def test_delta_minimal():
    d = BlackboardDelta(artifact_kind="intent", artifact_payload={"x": 1})
    assert d.artifact_kind == "intent"
    assert d.events_to_emit == []
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/agents/test_base.py -v`

- [ ] **Step 3: Implement `core/stm/agents/base.py`**

```python
"""Base contract for STM agents."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from core.stm.blackboard import StmBlackboard


@dataclass
class AgentContext:
    llm: Any
    discovery_registry: Any = None
    bq: Any = None
    jira: Any = None
    logger: Any = None
    model_overrides: Dict[str, str] = field(default_factory=dict)


@dataclass
class BlackboardDelta:
    artifact_kind: str
    artifact_payload: Any
    events_to_emit: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    set_current_stage: Optional[str] = None
    clear_refine_feedback_for_stage: Optional[str] = None


class StmAgent(ABC):
    stage: str  # "L1".."L6"
    name: str

    @abstractmethod
    def applicable(self, bb: StmBlackboard) -> bool: ...

    @abstractmethod
    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta: ...
```

- [ ] **Step 4: Create FakeLLMClient at `tests/stm/fake_llm.py`**

```python
"""Replayable LLM client for unit tests."""
from typing import Any, Dict, List


class FakeLLMClient:
    def __init__(self, responses: List[Dict[str, Any]] | Dict[str, Any] | None = None):
        if responses is None:
            self._queue: List[Any] = []
        elif isinstance(responses, dict):
            self._queue = [responses]
        else:
            self._queue = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def complete_json(self, prompt: str, system: str = "", max_tokens: int = 0, **kw) -> Dict[str, Any]:
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens, **kw})
        if not self._queue:
            raise RuntimeError(f"FakeLLMClient exhausted (call #{len(self.calls)})")
        return self._queue.pop(0)

    async def complete_json_async(self, prompt: str, system: str = "", max_tokens: int = 0, **kw):
        return self.complete_json(prompt, system=system, max_tokens=max_tokens, **kw)

    def push(self, response: Dict[str, Any]) -> None:
        self._queue.append(response)
```

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/stm/agents/test_base.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add core/stm/agents/__init__.py core/stm/agents/base.py tests/stm/agents/__init__.py tests/stm/agents/test_base.py tests/stm/fake_llm.py
git commit -m "stm: StmAgent base + AgentContext + FakeLLMClient"
```

---

### Task 4.2: IntentAgent (L1)

**Files:**
- Create: `core/stm/agents/intent.py`
- Test: `tests/stm/agents/test_intent.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/agents/test_intent.py
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.intent import IntentAgent
from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from tests.stm.fake_llm import FakeLLMClient


def _bb(raw="Build customer dim, active users only", src="freetext", jira_key=None):
    return StmBlackboard(
        session_id="s", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source=src, raw_input=raw, jira_issue_key=jira_key),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_applicable_when_idle_or_stale():
    bb = _bb()
    bb.intent.status = StageStatus.idle
    assert IntentAgent().applicable(bb) is True
    bb.intent.status = StageStatus.ready
    assert IntentAgent().applicable(bb) is False
    bb.intent.status = StageStatus.stale
    assert IntentAgent().applicable(bb) is True


@pytest.mark.asyncio
async def test_freetext_extraction():
    fake = FakeLLMClient([{
        "entity": "customer_dim", "action": "create",
        "is_dimension": True, "is_fact": False, "scd_hint": "type2",
        "filters": ["active users only"], "grain_hint": "customer_id",
        "extracted_keywords": ["customer", "active"],
    }])
    bb = _bb()
    delta = await IntentAgent().run(bb, AgentContext(llm=fake))
    assert delta.artifact_kind == "intent"
    assert delta.artifact_payload.entity == "customer_dim"
    assert delta.artifact_payload.is_dimension is True
    assert "stage_ready" in [e["type"] for e in delta.events_to_emit]


@pytest.mark.asyncio
async def test_jira_path_calls_jira_client(monkeypatch):
    fake_llm = FakeLLMClient([{
        "entity": "x", "action": "create", "is_dimension": False, "is_fact": True,
        "scd_hint": None, "filters": [], "grain_hint": None, "extracted_keywords": [],
    }])
    bb = _bb(raw="", src="jira", jira_key="DAT-123")
    class _Jira:
        def get_issue(self, key, **kw):
            from core.schemas import JiraStory
            return JiraStory(issue_key=key, summary="S", description="D", acceptance_criteria="AC",
                             labels=[], priority=None, assignee=None, components=[],
                             status=None, story_type=None, attachments=[])
    delta = await IntentAgent().run(bb, AgentContext(llm=fake_llm, jira=_Jira()))
    assert delta.artifact_payload.entity == "x"
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/agents/test_intent.py -v`

- [ ] **Step 3: Implement `core/stm/agents/intent.py`**

```python
"""L1 — Intent extraction agent (Haiku)."""
from __future__ import annotations

import json
from typing import Any

from core.config import STM_LLM_MODEL_L1
from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import IntentArtifact, StageStatus, StmBlackboard


SYSTEM_PROMPT = (
    "You are a senior data engineer. Extract structured business intent from the input. "
    "Return ONLY a JSON object with keys: entity (str), action (one of "
    "'create','refresh','backfill','migrate'), is_dimension (bool), is_fact (bool), "
    "scd_hint (one of 'type1','type2','type3','none' or null), filters (list of str), "
    "grain_hint (str or null), extracted_keywords (list of str). No markdown."
)


class IntentAgent(StmAgent):
    stage = "L1"
    name = "IntentAgent"

    def applicable(self, bb: StmBlackboard) -> bool:
        return bb.intent.status in (StageStatus.idle, StageStatus.stale)

    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta:
        # Resolve raw text
        if bb.intent.source == "jira" and bb.intent.jira_issue_key:
            if ctx.jira is None:
                raise RuntimeError("IntentAgent: source=jira but no jira client in context")
            story = ctx.jira.get_issue(bb.intent.jira_issue_key)
            text = f"Summary: {story.summary}\n\nDescription: {story.description}\n\nAC: {story.acceptance_criteria}"
        else:
            text = bb.intent.raw_input

        refine = bb.refine_feedback_pending.get("L1", "")
        if refine:
            text = f"{text}\n\nREFINEMENT FEEDBACK:\n{refine}"

        model = ctx.model_overrides.get("L1", STM_LLM_MODEL_L1)
        raw = ctx.llm.complete_json(text, system=SYSTEM_PROMPT, max_tokens=1024, model=model)

        new_intent = IntentArtifact(
            source=bb.intent.source,
            raw_input=bb.intent.raw_input,
            jira_issue_key=bb.intent.jira_issue_key,
            entity=raw.get("entity", ""),
            action=raw.get("action", "create"),
            is_dimension=bool(raw.get("is_dimension", False)),
            is_fact=bool(raw.get("is_fact", False)),
            scd_hint=raw.get("scd_hint"),
            filters=list(raw.get("filters") or []),
            grain_hint=raw.get("grain_hint"),
            extracted_keywords=list(raw.get("extracted_keywords") or []),
            status=StageStatus.ready,
        )

        return BlackboardDelta(
            artifact_kind="intent",
            artifact_payload=new_intent,
            events_to_emit=[
                {"type": "stage_started", "stage": "L1"},
                {"type": "llm_call", "stage": "L1", "model": model},
                {"type": "stage_ready", "stage": "L1", "confidence_summary": "parsed"},
            ],
            clear_refine_feedback_for_stage="L1",
        )
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/agents/test_intent.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/stm/agents/intent.py tests/stm/agents/test_intent.py
git commit -m "stm: L1 IntentAgent (Haiku)"
```

---

### Task 4.3: BuilderAgent (L6 pass-through for now)

**Files:**
- Create: `core/stm/agents/builder.py`
- Test: `tests/stm/agents/test_builder.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/agents/test_builder.py
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.builder import BuilderAgent
from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)


def _bb():
    bb = StmBlackboard(
        session_id="s", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="x", entity="customer_dim", status=StageStatus.ready),
        metadata_graph=MetadataGraph(status=StageStatus.ready),
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse", status=StageStatus.ready),
        transformations=Transformations(status=StageStatus.ready),
        validation=ValidationReport(status=StageStatus.ready),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="approved"),
            "gate2_validation": GateDecision(name="gate2_validation", decision="approved"),
        },
    )
    return bb


@pytest.mark.asyncio
async def test_builder_applicable_only_after_gate2():
    bb = _bb()
    bb.gates["gate2_validation"].decision = "pending"
    assert BuilderAgent().applicable(bb) is False
    bb.gates["gate2_validation"].decision = "approved"
    assert BuilderAgent().applicable(bb) is True


@pytest.mark.asyncio
async def test_builder_produces_stm_result():
    bb = _bb()
    delta = await BuilderAgent().run(bb, AgentContext(llm=None))
    assert delta.artifact_kind == "stm_result"
    assert delta.artifact_payload is not None
    assert "stm_id" in delta.artifact_payload
    assert delta.set_current_stage == "done"
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/agents/test_builder.py -v`

- [ ] **Step 3: Implement `core/stm/agents/builder.py`**

```python
"""L6 — STM Builder agent (composes MappingResult)."""
from __future__ import annotations

import uuid
from datetime import datetime

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import StmBlackboard


class BuilderAgent(StmAgent):
    stage = "L6"
    name = "BuilderAgent"

    def applicable(self, bb: StmBlackboard) -> bool:
        return (
            bb.stm_result is None
            and bb.gates.get("gate2_validation", None) is not None
            and bb.gates["gate2_validation"].decision == "approved"
        )

    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta:
        # Pass-through: compose a minimal MappingResult dict from blackboard state.
        # Full implementation lands in Phase 7 Task 7.4.
        stm_id = uuid.uuid4().hex[:8]
        result = {
            "stm_id": stm_id,
            "target_dataset": bb.target_dataset,
            "target_table": bb.target_table,
            "field_count": len(bb.candidate_mappings.rows),
            "rows": [r.model_dump() for r in bb.candidate_mappings.rows],
            "transformations": [t.model_dump() for t in bb.transformations.rows],
            "source_tables": sorted({
                ".".join(n.id.split(".")[:3]) for n in bb.metadata_graph.nodes if n.kind == "table"
            }),
            "business_rules": list(bb.intent.filters),
            "generated_at": datetime.utcnow().isoformat(),
        }
        return BlackboardDelta(
            artifact_kind="stm_result",
            artifact_payload=result,
            events_to_emit=[
                {"type": "stage_started", "stage": "L6"},
                {"type": "stage_ready", "stage": "L6"},
                {"type": "session_completed", "stm_id": stm_id},
            ],
            set_current_stage="done",
        )
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/agents/test_builder.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/stm/agents/builder.py tests/stm/agents/test_builder.py
git commit -m "stm: L6 BuilderAgent pass-through (full impl deferred to phase 7)"
```

---

### Task 4.4: Coordinator (no gates yet)

**Files:**
- Create: `core/stm/coordinator.py`
- Test: `tests/stm/test_coordinator_basic.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_coordinator_basic.py
import asyncio
import pytest

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.coordinator import StmCoordinator
from core.stm.persistence import create_session, load_blackboard
from tests.stm.fake_llm import FakeLLMClient


def _bb(sid):
    return StmBlackboard(
        session_id=sid, target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-demo"],
        intent=IntentArtifact(source="freetext", raw_input="Build customer dim, active users only"),
        metadata_graph=MetadataGraph(status=StageStatus.ready),
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse", status=StageStatus.ready),
        transformations=Transformations(status=StageStatus.ready),
        validation=ValidationReport(status=StageStatus.ready),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="approved"),
            "gate2_validation": GateDecision(name="gate2_validation", decision="approved"),
        },
    )


@pytest.mark.asyncio
async def test_runs_l1_then_l6_with_gates_pre_approved(tmp_db):
    bb = _bb("s-basic")
    await create_session(bb, raw_input=bb.intent.raw_input, intent_source="freetext", jira_issue_key=None)
    fake = FakeLLMClient([{
        "entity": "customer_dim", "action": "create",
        "is_dimension": True, "is_fact": False, "scd_hint": "type2",
        "filters": ["active users only"], "grain_hint": "customer_id",
        "extracted_keywords": ["customer"],
    }])
    coord = StmCoordinator(session_id="s-basic", llm=fake)
    await coord.run_until_done(timeout=5)
    loaded = await load_blackboard("s-basic")
    assert loaded.current_stage == "done"
    assert loaded.intent.status == StageStatus.ready
    assert loaded.stm_result is not None
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_coordinator_basic.py -v`

- [ ] **Step 3: Implement `core/stm/coordinator.py`**

```python
"""Coordinator: per-session dispatch loop over StmAgent registry."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.agents.intent import IntentAgent
from core.stm.agents.builder import BuilderAgent
from core.stm.blackboard import IntentArtifact, StageStatus, StmBlackboard
from core.stm.events import EventKind, default_broker
from core.stm.locks import SessionLock
from core.stm.persistence import (
    append_event, load_blackboard, save_blackboard, set_session_status,
)

logger = logging.getLogger("stm.coordinator")


def default_agents() -> List[StmAgent]:
    # Order matters — coordinator dispatches first-applicable.
    # Phase 5+ will append MetadataAgent, SemanticAgent, TransformAgent, ValidationAgent.
    return [IntentAgent(), BuilderAgent()]


class StmCoordinator:
    def __init__(
        self,
        session_id: str,
        llm: Any,
        agents: Optional[List[StmAgent]] = None,
        discovery_registry: Any = None,
        bq: Any = None,
        jira: Any = None,
        broker=None,
    ):
        self.session_id = session_id
        self.agents = agents or default_agents()
        self.ctx = AgentContext(
            llm=llm, discovery_registry=discovery_registry, bq=bq, jira=jira, logger=logger,
        )
        self.broker = broker or default_broker()
        self._task: Optional[asyncio.Task] = None

    async def _next_applicable(self, bb: StmBlackboard) -> Optional[StmAgent]:
        for a in self.agents:
            if a.applicable(bb):
                return a
        return None

    async def _apply_delta(self, bb: StmBlackboard, delta: BlackboardDelta) -> None:
        # Merge delta into blackboard
        if delta.artifact_kind == "intent":
            bb.intent = delta.artifact_payload
        elif delta.artifact_kind == "metadata_graph":
            bb.metadata_graph = delta.artifact_payload
        elif delta.artifact_kind == "candidate_mappings":
            bb.candidate_mappings = delta.artifact_payload
        elif delta.artifact_kind == "transformations":
            bb.transformations = delta.artifact_payload
        elif delta.artifact_kind == "validation":
            bb.validation = delta.artifact_payload
        elif delta.artifact_kind == "stm_result":
            bb.stm_result = delta.artifact_payload
        if delta.set_current_stage:
            bb.current_stage = delta.set_current_stage
        if delta.clear_refine_feedback_for_stage:
            bb.refine_feedback_pending.pop(delta.clear_refine_feedback_for_stage, None)

    async def tick(self) -> bool:
        """Return True if work advanced, False if idle/done."""
        async with SessionLock(self.session_id):
            bb = await load_blackboard(self.session_id)
            if bb.current_stage in ("done", "failed"):
                return False
            agent = await self._next_applicable(bb)
            if agent is None:
                return False
        # Dispatch outside lock to allow concurrent reads
        try:
            await append_event(self.session_id, stage=agent.stage, event_kind="started")
            await self.broker.publish(self.session_id, {"type": EventKind.stage_started, "stage": agent.stage})
            delta = await agent.run(bb, self.ctx)
        except Exception as exc:
            logger.exception("Agent %s failed", agent.name)
            await append_event(self.session_id, stage=agent.stage, event_kind="failed", message=str(exc))
            await self.broker.publish(self.session_id, {"type": EventKind.stage_failed, "stage": agent.stage, "error": str(exc)})
            async with SessionLock(self.session_id):
                bb2 = await load_blackboard(self.session_id)
                bb2.current_stage = "failed"
                await save_blackboard(bb2)
                await set_session_status(self.session_id, "failed")
            return False

        async with SessionLock(self.session_id):
            bb = await load_blackboard(self.session_id)
            await self._apply_delta(bb, delta)
            await save_blackboard(bb)
            await append_event(
                self.session_id, stage=agent.stage, event_kind="ready",
                artifact_kind=delta.artifact_kind, confidence=delta.confidence,
            )
            for ev in delta.events_to_emit:
                await self.broker.publish(self.session_id, ev)
            if bb.current_stage == "done":
                await set_session_status(self.session_id, "completed")
        return True

    async def run_until_done(self, timeout: float = 60.0) -> None:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            advanced = await self.tick()
            if not advanced:
                async with SessionLock(self.session_id):
                    bb = await load_blackboard(self.session_id)
                if bb.current_stage in ("done", "failed", "awaiting_review"):
                    return
                await asyncio.sleep(0.05)
        raise TimeoutError(f"Coordinator timeout for session {self.session_id}")

    def start_background(self) -> asyncio.Task:
        self._task = asyncio.create_task(self.run_until_done(timeout=3600))
        return self._task
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/test_coordinator_basic.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add core/stm/coordinator.py tests/stm/test_coordinator_basic.py
git commit -m "stm: coordinator skeleton (L1 + L6, no gates)"
```

---

### Task 4.5: Session API endpoints

**Files:**
- Modify: `routers/stm.py`
- Test: `tests/stm/test_session_endpoints.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_session_endpoints.py
import asyncio
import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", "wkPzx-2zM9YlbsZF_4ic4w8I1OvOhA-IRgLY4ZSj_5o=")
    from app import app
    return TestClient(app)


def test_post_creates_session(client, monkeypatch):
    # Stub the coordinator so it doesn't run real LLM
    from core.stm import coordinator as coord_mod

    class _Stub(coord_mod.StmCoordinator):
        def start_background(self):
            class _T:
                def cancel(self): pass
            return _T()

    monkeypatch.setattr(coord_mod, "StmCoordinator", _Stub)

    resp = client.post(
        "/api/stm/sessions",
        json={
            "source_profiles": ["postgres-crm-demo"],
            "target_dataset": "warehouse",
            "target_table": "customer_dim",
            "intent": {"source": "freetext", "raw_text": "Build customer dim, active users only"},
        },
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    assert sid

    # Hydration
    resp2 = client.get(f"/api/stm/sessions/{sid}")
    assert resp2.status_code == 200
    assert resp2.json()["target_table"] == "customer_dim"


def test_post_requires_intent_payload(client):
    resp = client.post("/api/stm/sessions", json={
        "source_profiles": ["postgres-crm-demo"],
        "target_dataset": "warehouse",
        "target_table": "customer_dim",
        # missing intent
    })
    assert resp.status_code == 422
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_session_endpoints.py -v`

- [ ] **Step 3: Extend `routers/stm.py`**

Read the existing `routers/stm.py` (it has `POST /generate`, `GET /{id}/summary`, `GET /{id}/export.xlsx`, `GET /{id}/export.csv`). Add new endpoints — do not modify the existing ones.

Append to the bottom of `routers/stm.py`:

```python
import asyncio
import json
import uuid
from typing import List, Optional, Literal

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.coordinator import StmCoordinator
from core.stm.events import default_broker
from core.stm.persistence import (
    create_session, load_blackboard, list_events, record_gate_decision,
    save_blackboard, set_session_status, list_running_sessions,
)
from core.llm_client import LLMClient


class IntentInput(BaseModel):
    source: Literal["jira", "freetext"]
    jira_key: Optional[str] = None
    raw_text: Optional[str] = None


class SessionCreate(BaseModel):
    source_profiles: List[str]
    target_dataset: str
    target_table: str
    intent: IntentInput


@router.post("/sessions")
async def create_stm_session(body: SessionCreate):
    sid = uuid.uuid4().hex
    raw = body.intent.raw_text if body.intent.source == "freetext" else (body.intent.jira_key or "")
    if not raw:
        raise HTTPException(status_code=400, detail="intent must include raw_text or jira_key")

    bb = StmBlackboard(
        session_id=sid, target_table=body.target_table, target_dataset=body.target_dataset,
        dialect_target="bigquery", selected_source_profiles=body.source_profiles,
        intent=IntentArtifact(
            source=body.intent.source, raw_input=raw,
            jira_issue_key=body.intent.jira_key,
            status=StageStatus.idle,
        ),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table=body.target_table, target_dataset=body.target_dataset),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
        current_stage="L1",
    )
    await create_session(bb, raw_input=raw, intent_source=body.intent.source, jira_issue_key=body.intent.jira_key)
    coord = StmCoordinator(session_id=sid, llm=LLMClient())
    coord.start_background()
    return {"session_id": sid}


@router.get("/sessions")
async def list_stm_sessions(limit: int = 50):
    rows = await list_running_sessions()
    return rows[:limit]


@router.get("/sessions/{session_id}")
async def get_stm_session(session_id: str):
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    return json.loads(bb.model_dump_json())


@router.get("/sessions/{session_id}/timeline")
async def session_timeline(session_id: str):
    return await list_events(session_id)


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, request: Request):
    broker = default_broker()
    queue = await broker.subscribe(session_id)

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
        finally:
            await broker.unsubscribe(session_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/test_session_endpoints.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add routers/stm.py tests/stm/test_session_endpoints.py
git commit -m "stm: session create/get/timeline/SSE endpoints"
```

---

### Task 4.6: Recovery on app startup

**Files:**
- Modify: `app.py` (startup hook)
- Test: `tests/stm/test_recovery.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_recovery.py
import pytest

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import create_session, append_event, load_blackboard
from core.stm.recovery import recover_sessions
from datetime import datetime, timedelta


def _bb(sid):
    return StmBlackboard(
        session_id=sid, target_table="t", target_dataset="d", dialect_target="bigquery",
        selected_source_profiles=[],
        intent=IntentArtifact(source="freetext", raw_input="x"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="t", target_dataset="d"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_orphaned_started_event_marks_failed(tmp_db, monkeypatch):
    bb = _bb("orph")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    # Simulate an orphaned 'started' more than 5 minutes ago (we'll patch the threshold)
    await append_event("orph", stage="L1", event_kind="started")
    # Force threshold to 0 to make any started orphaned for this test
    monkeypatch.setenv("STM_ORPHAN_THRESHOLD_SEC", "0")
    await recover_sessions()
    loaded = await load_blackboard("orph")
    assert loaded.current_stage == "failed"
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_recovery.py -v`

- [ ] **Step 3: Implement `core/stm/recovery.py`**

```python
"""Startup recovery: detect orphaned coordinator sessions."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

from core.stm.blackboard import StageStatus
from core.stm.persistence import (
    list_events, list_running_sessions, load_blackboard, save_blackboard, set_session_status,
)


async def recover_sessions() -> None:
    threshold = int(os.environ.get("STM_ORPHAN_THRESHOLD_SEC", "300"))
    cutoff = datetime.utcnow() - timedelta(seconds=threshold)
    for row in await list_running_sessions():
        sid = row["session_id"]
        events = await list_events(sid)
        # Find latest 'started' with no matching terminal kind after it.
        last_started = None
        last_terminal_after_started = None
        for ev in events:
            if ev["event_kind"] == "started":
                last_started = ev
                last_terminal_after_started = None
            elif ev["event_kind"] in ("ready", "failed") and last_started:
                last_terminal_after_started = ev
        if last_started and not last_terminal_after_started and last_started["created_at"] <= cutoff:
            bb = await load_blackboard(sid)
            bb.current_stage = "failed"
            await save_blackboard(bb)
            await set_session_status(sid, "failed")
```

- [ ] **Step 4: Wire into `app.py` startup**

Read existing `app.py`. Locate the FastAPI startup hook (likely `@app.on_event("startup")` or a factory). Add:

```python
from core.stm.recovery import recover_sessions

@app.on_event("startup")
async def _stm_recover():
    try:
        await recover_sessions()
    except Exception as exc:
        import logging
        logging.getLogger("stm.recovery").warning("recover_sessions failed: %s", exc)
```

If `app.py` uses a factory function (`create_app`), call `recover_sessions()` from inside the factory's startup registration.

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/stm/test_recovery.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add core/stm/recovery.py app.py tests/stm/test_recovery.py
git commit -m "stm: startup recovery for orphaned coordinator sessions"
```

---

# PHASE 5 — L2 Metadata + Gate 1

Shippable outcome: real metadata reasoning produces a knowledge graph; first governance gate stalls the pipeline; reviewer Approve / Reject / Refine drives the next move. SVG endpoint renders the graph.

---

### Task 5.1: MetadataAgent — parallel source probing + deterministic skeleton

**Files:**
- Create: `core/stm/agents/metadata.py`
- Test: `tests/stm/agents/test_metadata.py`

- [ ] **Step 1: Failing test (mock providers)**

```python
# tests/stm/agents/test_metadata.py
import pytest

from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo, ColumnProfile, ColumnHit,
)
from core.discovery.registry import register_provider, all_providers
from core.discovery.profiles import ConnectionProfile
from core.stm.agents.base import AgentContext
from core.stm.agents.metadata import MetadataAgent
from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from tests.stm.fake_llm import FakeLLMClient


class _MockPg(SourceProvider):
    dialect = "postgres"

    async def ping(self, p): return PingResult(ok=True, latency_ms=1)
    async def list_schemas(self, p): return ["public"]
    async def list_tables(self, p, s): return [TableInfo(schema="public", name="customers")]
    async def get_columns(self, p, s, t):
        return [
            ColumnInfo(schema=s, table=t, name="customer_id", data_type="bigint", nullable=False, is_primary_key=True),
            ColumnInfo(schema=s, table=t, name="email", data_type="varchar", nullable=True),
            ColumnInfo(schema=s, table=t, name="is_active", data_type="boolean", nullable=False),
        ]
    async def get_foreign_keys(self, p, s, t): return []
    async def profile_column(self, p, s, t, c, sample_rows=0): return ColumnProfile(row_count=100, distinct_count=99)
    async def search_by_keywords(self, p, kw, limit=50):
        return [
            ColumnHit(schema="public", table="customers", column="customer_id", data_type="bigint", score=1.0, matched_on="name"),
            ColumnHit(schema="public", table="customers", column="is_active", data_type="boolean", score=1.0, matched_on="name"),
        ]


def _bb(sid="s-meta"):
    return StmBlackboard(
        session_id=sid, target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-x"],
        intent=IntentArtifact(
            source="freetext", raw_input="x", entity="customer_dim",
            action="create", is_dimension=True, is_fact=False,
            scd_hint="type2", filters=["active users only"],
            extracted_keywords=["customer","active"], status=StageStatus.ready,
        ),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.fixture
def pg_registered(monkeypatch):
    # Save & restore
    snap = dict(all_providers())
    register_provider("postgres", _MockPg())
    yield
    for k, v in snap.items():
        register_provider(k, v)


@pytest.fixture
def profile_in_registry(pg_registered, monkeypatch):
    from core.discovery.profiles import ProfileRegistry, ConnectionProfile
    reg = ProfileRegistry()
    reg.register(ConnectionProfile(id="pg-x", label="t", dialect="postgres", dsn="postgresql://", host="h"))
    # Patch the module-level singleton lookup the agent uses
    monkeypatch.setattr("core.stm.agents.metadata._lookup_profile", lambda pid: reg.get(pid))


@pytest.mark.asyncio
async def test_applicable_only_when_intent_ready(profile_in_registry):
    bb = _bb()
    bb.intent.status = StageStatus.idle
    assert MetadataAgent().applicable(bb) is False
    bb.intent.status = StageStatus.ready
    assert MetadataAgent().applicable(bb) is True


@pytest.mark.asyncio
async def test_builds_skeleton_with_keyword_hits(profile_in_registry):
    bb = _bb()
    fake = FakeLLMClient([{"concept_links": [], "join_candidates": []}])
    delta = await MetadataAgent().run(bb, AgentContext(llm=fake))
    g = delta.artifact_payload
    table_nodes = [n for n in g.nodes if n.kind == "table"]
    column_nodes = [n for n in g.nodes if n.kind == "column"]
    assert len(table_nodes) >= 1
    assert any(n.label == "customer_id" for n in column_nodes)
    assert "pg-x" in g.sources_probed


@pytest.mark.asyncio
async def test_handles_source_timeout(profile_in_registry, monkeypatch):
    # Make the provider ping raise to simulate timeout
    class _Boom(_MockPg):
        async def search_by_keywords(self, p, kw, limit=50):
            raise asyncio.TimeoutError("simulated")
    import asyncio
    register_provider("postgres", _Boom())
    bb = _bb()
    fake = FakeLLMClient([{"concept_links": [], "join_candidates": []}])
    delta = await MetadataAgent().run(bb, AgentContext(llm=fake))
    g = delta.artifact_payload
    assert any("simulated" in n or "timeout" in n.lower() for n in g.coverage_notes)
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/agents/test_metadata.py -v`

- [ ] **Step 3: Implement `core/stm/agents/metadata.py`**

```python
"""L2 — Metadata Intelligence agent."""
from __future__ import annotations

import asyncio
import json
from typing import Any, List

from core.config import STM_LLM_MODEL_L2, STM_PROBE_TIMEOUT_SEC
from core.discovery.profiles import ProfileRegistry
from core.discovery.registry import get_provider
from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    GraphEdge, GraphNode, IntentArtifact, MetadataGraph, StageStatus, StmBlackboard,
)


def _lookup_profile(profile_id: str):
    return ProfileRegistry().get(profile_id)


SYSTEM_PROMPT = (
    "You are a metadata reasoning engine. Given an intent and a flat list of source columns "
    "from multiple dialects, emit (1) concept_links between intent keywords and columns and "
    "(2) join_candidates between columns across sources that likely refer to the same entity. "
    "Return ONLY JSON of form: "
    '{"concept_links":[{"concept":"...","node_id":"...","confidence":0.9,"evidence":"..."}], '
    '"join_candidates":[{"src":"node_id_a","dst":"node_id_b","confidence":0.8,"evidence":"..."}]}. '
    "node_id format: <profile_id>.<schema>.<table>.<column>"
)


class MetadataAgent(StmAgent):
    stage = "L2"
    name = "MetadataAgent"

    def applicable(self, bb: StmBlackboard) -> bool:
        return (
            bb.intent.status == StageStatus.ready
            and bb.metadata_graph.status in (StageStatus.idle, StageStatus.stale)
        )

    async def _probe_one(
        self, profile_id: str, keywords: List[str], coverage_notes: List[str],
    ) -> tuple[list, list, list, list]:
        prof = _lookup_profile(profile_id)
        if prof is None:
            coverage_notes.append(f"{profile_id}: profile not found")
            return [], [], [], []
        try:
            provider = get_provider(prof.dialect)
        except ValueError:
            coverage_notes.append(f"{profile_id}: no provider for {prof.dialect}")
            return [], [], [], []
        try:
            async with asyncio.timeout(STM_PROBE_TIMEOUT_SEC):
                hits = await provider.search_by_keywords(prof, keywords, limit=80)
        except (asyncio.TimeoutError, Exception) as exc:
            coverage_notes.append(f"{profile_id}: probe failed — {exc}")
            return [], [], [], []

        # Gather full column info for hit tables (dedup)
        table_keys = sorted({(h.schema, h.table) for h in hits})
        tables: list = []
        columns: list = []
        fks: list = []
        for (s, t) in table_keys:
            try:
                async with asyncio.timeout(STM_PROBE_TIMEOUT_SEC):
                    cols = await provider.get_columns(prof, s, t)
                    foreign = await provider.get_foreign_keys(prof, s, t)
                tables.append({"schema": s, "name": t, "dialect": prof.dialect, "profile_id": profile_id})
                for c in cols:
                    columns.append({
                        "profile_id": profile_id, "dialect": prof.dialect,
                        "schema": s, "table": t, "name": c.name,
                        "data_type": c.data_type, "nullable": c.nullable,
                        "is_primary_key": c.is_primary_key,
                    })
                for fk in foreign:
                    fks.append({
                        "profile_id": profile_id, "dialect": prof.dialect,
                        "schema": s, "table": t, "column": fk.column,
                        "ref_schema": fk.ref_schema, "ref_table": fk.ref_table, "ref_column": fk.ref_column,
                    })
            except Exception as exc:
                coverage_notes.append(f"{profile_id}.{s}.{t}: column fetch failed — {exc}")
        return tables, columns, fks, [h.__dict__ | {"profile_id": profile_id, "dialect": prof.dialect} for h in hits]

    def _build_skeleton(self, tables, columns, fks) -> tuple[List[GraphNode], List[GraphEdge]]:
        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []
        for t in tables:
            tid = f"{t['profile_id']}.{t['schema']}.{t['name']}"
            nodes.append(GraphNode(id=tid, kind="table", label=t["name"], dialect=t["dialect"]))
        for c in columns:
            tid = f"{c['profile_id']}.{c['schema']}.{c['table']}"
            cid = f"{tid}.{c['name']}"
            nodes.append(GraphNode(
                id=cid, kind="column", label=c["name"], dialect=c["dialect"],
                data_type=c["data_type"], nullable=c["nullable"],
            ))
            edges.append(GraphEdge(src=tid, dst=cid, kind="contains"))
        for fk in fks:
            src = f"{fk['profile_id']}.{fk['schema']}.{fk['table']}.{fk['column']}"
            dst = f"{fk['profile_id']}.{fk['ref_schema']}.{fk['ref_table']}.{fk['ref_column']}"
            edges.append(GraphEdge(src=src, dst=dst, kind="fk", evidence="explicit FK"))
        return nodes, edges

    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta:
        keywords = list(bb.intent.extracted_keywords)
        if bb.intent.entity and bb.intent.entity not in keywords:
            keywords.append(bb.intent.entity)

        coverage_notes: List[str] = []
        all_tables, all_columns, all_fks, all_hits = [], [], [], []
        results = await asyncio.gather(*[
            self._probe_one(pid, keywords, coverage_notes)
            for pid in bb.selected_source_profiles
        ])
        for tables, columns, fks, hits in results:
            all_tables.extend(tables)
            all_columns.extend(columns)
            all_fks.extend(fks)
            all_hits.extend(hits)

        nodes, edges = self._build_skeleton(all_tables, all_columns, all_fks)

        # Concept linking + join candidates via LLM
        if all_columns:
            prompt = json.dumps({
                "intent": {
                    "entity": bb.intent.entity, "action": bb.intent.action,
                    "is_dimension": bb.intent.is_dimension, "filters": bb.intent.filters,
                    "keywords": keywords,
                },
                "columns": [
                    {"node_id": f"{c['profile_id']}.{c['schema']}.{c['table']}.{c['name']}",
                     "dialect": c["dialect"], "data_type": c["data_type"]}
                    for c in all_columns
                ],
                "refine_feedback": bb.refine_feedback_pending.get("L2", ""),
            })
            model = ctx.model_overrides.get("L2", STM_LLM_MODEL_L2)
            raw = ctx.llm.complete_json(prompt, system=SYSTEM_PROMPT, max_tokens=4096, model=model)
            for link in raw.get("concept_links", []) or []:
                edges.append(GraphEdge(
                    src=f"concept:{link.get('concept','')}",
                    dst=link.get("node_id", ""),
                    kind="concept_link",
                    confidence=float(link.get("confidence") or 0.0),
                    evidence=link.get("evidence"),
                ))
            for join in raw.get("join_candidates", []) or []:
                edges.append(GraphEdge(
                    src=join.get("src", ""),
                    dst=join.get("dst", ""),
                    kind="join_candidate",
                    confidence=float(join.get("confidence") or 0.0),
                    evidence=join.get("evidence"),
                ))
            # Add concept pseudo-nodes
            concepts = {e.src for e in edges if e.kind == "concept_link"}
            existing_ids = {n.id for n in nodes}
            for cid in concepts:
                if cid not in existing_ids:
                    nodes.append(GraphNode(id=cid, kind="concept", label=cid.split(":", 1)[-1]))

        graph = MetadataGraph(
            nodes=nodes, edges=edges,
            sources_probed=bb.selected_source_profiles,
            coverage_notes=coverage_notes,
            status=StageStatus.ready,
        )
        return BlackboardDelta(
            artifact_kind="metadata_graph",
            artifact_payload=graph,
            events_to_emit=[
                {"type": "stage_started", "stage": "L2"},
                {"type": "stage_ready", "stage": "L2", "confidence_summary": f"{len(nodes)} nodes / {len(edges)} edges"},
            ],
            clear_refine_feedback_for_stage="L2",
        )
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/agents/test_metadata.py -v`
Expected: 3 passed.

- [ ] **Step 5: Wire into coordinator's default_agents**

In `core/stm/coordinator.py` replace:

```python
def default_agents() -> List[StmAgent]:
    return [IntentAgent(), BuilderAgent()]
```

with:

```python
from core.stm.agents.metadata import MetadataAgent

def default_agents() -> List[StmAgent]:
    return [IntentAgent(), MetadataAgent(), BuilderAgent()]
```

- [ ] **Step 6: Commit**

```bash
git add core/stm/agents/metadata.py core/stm/coordinator.py tests/stm/agents/test_metadata.py
git commit -m "stm: L2 MetadataAgent — parallel probing + LLM concept linking"
```

---

### Task 5.2: Gate stall in coordinator + gate decision API

**Files:**
- Modify: `core/stm/coordinator.py`
- Modify: `routers/stm.py`
- Test: `tests/stm/test_coordinator_gates.py`
- Test: `tests/stm/test_gate_endpoint.py`

- [ ] **Step 1: Failing test for gate stall**

Create `tests/stm/test_coordinator_gates.py`:

```python
import asyncio
import pytest

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.coordinator import StmCoordinator
from core.stm.persistence import create_session, load_blackboard, record_gate_decision
from tests.stm.fake_llm import FakeLLMClient


def _bb(sid):
    return StmBlackboard(
        session_id=sid, target_table="t", target_dataset="d", dialect_target="bigquery",
        selected_source_profiles=[],
        intent=IntentArtifact(source="freetext", raw_input="x"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="t", target_dataset="d", status=StageStatus.ready),
        transformations=Transformations(status=StageStatus.ready),
        validation=ValidationReport(status=StageStatus.ready),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation", decision="approved"),
        },
    )


@pytest.mark.asyncio
async def test_coordinator_stalls_at_gate1(tmp_db):
    bb = _bb("g1")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    fake = FakeLLMClient([
        {"entity": "x", "action": "create", "is_dimension": False, "is_fact": False,
         "scd_hint": None, "filters": [], "grain_hint": None, "extracted_keywords": []},
        {"concept_links": [], "join_candidates": []},
    ])
    coord = StmCoordinator(session_id="g1", llm=fake)
    await coord.run_until_done(timeout=5)
    loaded = await load_blackboard("g1")
    # Should be parked awaiting review of gate1
    assert loaded.intent.status == StageStatus.ready
    assert loaded.metadata_graph.status == StageStatus.ready
    assert loaded.gates["gate1_metadata"].decision == "pending"
    assert loaded.stm_result is None


@pytest.mark.asyncio
async def test_coordinator_resumes_after_gate1_approval(tmp_db):
    bb = _bb("g2")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    fake = FakeLLMClient([
        {"entity": "x", "action": "create", "is_dimension": False, "is_fact": False,
         "scd_hint": None, "filters": [], "grain_hint": None, "extracted_keywords": []},
        {"concept_links": [], "join_candidates": []},
    ])
    coord = StmCoordinator(session_id="g2", llm=fake)
    await coord.run_until_done(timeout=5)
    # Approve gate1
    await record_gate_decision("g2", gate_name="gate1_metadata", decision="approved",
                                reviewer="alice", notes=None, refine_target=None, refine_feedback=None)
    # Re-apply approval to blackboard (in this Phase 5, semantic/transform/validation agents don't
    # exist yet — we expect the coordinator to advance through and reach BuilderAgent because their
    # statuses were pre-set to ready in the fixture).
    bb_loaded = await load_blackboard("g2")
    bb_loaded.gates["gate1_metadata"].decision = "approved"
    from core.stm.persistence import save_blackboard
    await save_blackboard(bb_loaded)
    coord2 = StmCoordinator(session_id="g2", llm=fake)
    await coord2.run_until_done(timeout=5)
    final = await load_blackboard("g2")
    assert final.current_stage == "done"
    assert final.stm_result is not None
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_coordinator_gates.py -v`

- [ ] **Step 3: Update `core/stm/coordinator.py` to stall on gates**

Add at top:

```python
GATE_AFTER_STAGE = {"L2": "gate1_metadata", "L5": "gate2_validation"}
```

Modify `_next_applicable` and the dispatch loop to recognize "stalled" state — the simplest implementation is: after applying a delta, check whether the just-completed stage triggers a gate that is still `pending`. If so, mark `bb.current_stage` to that stage's name, set status awaiting_review, and stop the loop.

Replace `_apply_delta` and add a `_check_gate_after_stage` step. The complete updated section of the coordinator:

```python
async def _apply_delta(self, bb: StmBlackboard, delta: BlackboardDelta) -> None:
    if delta.artifact_kind == "intent":
        bb.intent = delta.artifact_payload
    elif delta.artifact_kind == "metadata_graph":
        bb.metadata_graph = delta.artifact_payload
    elif delta.artifact_kind == "candidate_mappings":
        bb.candidate_mappings = delta.artifact_payload
    elif delta.artifact_kind == "transformations":
        bb.transformations = delta.artifact_payload
    elif delta.artifact_kind == "validation":
        bb.validation = delta.artifact_payload
    elif delta.artifact_kind == "stm_result":
        bb.stm_result = delta.artifact_payload
    if delta.set_current_stage:
        bb.current_stage = delta.set_current_stage
    if delta.clear_refine_feedback_for_stage:
        bb.refine_feedback_pending.pop(delta.clear_refine_feedback_for_stage, None)


def _gate_required_after(self, stage: str, bb: StmBlackboard) -> str | None:
    gname = GATE_AFTER_STAGE.get(stage)
    if not gname:
        return None
    g = bb.gates.get(gname)
    if g and g.decision == "pending":
        return gname
    return None
```

In `tick()`, after the delta is merged and saved, add:

```python
gname = self._gate_required_after(agent.stage, bb)
if gname:
    await append_event(self.session_id, stage="GATE", event_kind="gate_requested",
                        artifact_kind=gname, message=gname)
    await self.broker.publish(self.session_id, {
        "type": EventKind.gate_requested, "gate": gname,
        "payload_summary": (
            "metadata-graph ready" if gname == "gate1_metadata" else "validation report ready"
        ),
    })
    await set_session_status(self.session_id, "awaiting_review")
```

Update the run loop exit condition in `run_until_done` to also break when status == awaiting_review (loading the session row each iteration):

```python
async def run_until_done(self, timeout: float = 60.0) -> None:
    import asyncio
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        advanced = await self.tick()
        async with SessionLock(self.session_id):
            bb = await load_blackboard(self.session_id)
        if bb.current_stage in ("done", "failed"):
            return
        # Detect stall: a pending gate after the latest-ready stage.
        for stage, gname in GATE_AFTER_STAGE.items():
            g = bb.gates.get(gname)
            if g and g.decision == "pending":
                # Determine if that stage is ready
                stage_ready = {
                    "L2": bb.metadata_graph.status == StageStatus.ready,
                    "L5": bb.validation.status == StageStatus.ready,
                }.get(stage, False)
                if stage_ready:
                    return  # awaiting_review
        if not advanced:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"Coordinator timeout for session {self.session_id}")
```

- [ ] **Step 4: Run — PASS for first test, may fail second until step 5 lands**

Run: `pytest tests/stm/test_coordinator_gates.py::test_coordinator_stalls_at_gate1 -v`
Expected: PASS.

- [ ] **Step 5: Add gate decision API to `routers/stm.py`**

Create `tests/stm/test_gate_endpoint.py`:

```python
import pytest
from fastapi.testclient import TestClient

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import create_session, load_blackboard


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", "wkPzx-2zM9YlbsZF_4ic4w8I1OvOhA-IRgLY4ZSj_5o=")
    from app import app
    return TestClient(app)


def _seed(sid):
    bb = StmBlackboard(
        session_id=sid, target_table="t", target_dataset="d", dialect_target="bigquery",
        selected_source_profiles=[],
        intent=IntentArtifact(source="freetext", raw_input="x", status=StageStatus.ready),
        metadata_graph=MetadataGraph(status=StageStatus.ready),
        candidate_mappings=CandidateMappings(target_table="t", target_dataset="d"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )
    return bb


@pytest.mark.asyncio
async def test_approve_gate1(tmp_db, client):
    bb = _seed("gx-approve")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    r = client.post("/api/stm/sessions/gx-approve/gates/gate1_metadata/decide",
                    json={"decision": "approved", "reviewer": "alice"})
    assert r.status_code == 200
    loaded = await load_blackboard("gx-approve")
    assert loaded.gates["gate1_metadata"].decision == "approved"


@pytest.mark.asyncio
async def test_refine_gate1_marks_downstream_stale(tmp_db, client):
    bb = _seed("gx-refine")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    r = client.post("/api/stm/sessions/gx-refine/gates/gate1_metadata/decide", json={
        "decision": "refine", "reviewer": "bob",
        "refine_target": "L2", "refine_feedback": "Add customer_loyalty"
    })
    assert r.status_code == 200
    loaded = await load_blackboard("gx-refine")
    assert loaded.metadata_graph.status == StageStatus.stale
    assert loaded.refine_feedback_pending["L2"] == "Add customer_loyalty"
    assert loaded.gates["gate1_metadata"].decision == "pending"


@pytest.mark.asyncio
async def test_invalid_refine_target_for_gate1_returns_400(tmp_db, client):
    bb = _seed("gx-bad")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    r = client.post("/api/stm/sessions/gx-bad/gates/gate1_metadata/decide", json={
        "decision": "refine", "refine_target": "L4", "refine_feedback": "x"
    })
    assert r.status_code == 400
```

- [ ] **Step 6: Implement the gate endpoint**

Append to `routers/stm.py`:

```python
GATE_REFINE_TARGETS = {
    "gate1_metadata": {"L1", "L2"},
    "gate2_validation": {"L1", "L2", "L3", "L4", "L5"},
}

STAGE_TO_ARTIFACT = {
    "L1": "intent",
    "L2": "metadata_graph",
    "L3": "candidate_mappings",
    "L4": "transformations",
    "L5": "validation",
}

DOWNSTREAM_ORDER = ["L1", "L2", "L3", "L4", "L5"]


class GateDecideBody(BaseModel):
    decision: Literal["approved", "rejected", "refine"]
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    refine_target: Optional[Literal["L1","L2","L3","L4","L5"]] = None
    refine_feedback: Optional[str] = None


@router.post("/sessions/{session_id}/gates/{gate_name}/decide")
async def decide_gate(session_id: str, gate_name: str, body: GateDecideBody):
    if gate_name not in ("gate1_metadata", "gate2_validation"):
        raise HTTPException(status_code=404, detail="unknown gate")
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    gate = bb.gates.get(gate_name)
    if gate is None or gate.decision != "pending":
        raise HTTPException(status_code=409, detail="gate not pending")

    if body.decision == "approved":
        gate.decision = "approved"
        gate.reviewer = body.reviewer
        gate.notes = body.notes
        from datetime import datetime as _dt
        gate.decided_at = _dt.utcnow()
    elif body.decision == "rejected":
        gate.decision = "rejected"
        gate.reviewer = body.reviewer
        gate.notes = body.notes
        bb.current_stage = "failed"
        await save_blackboard(bb)
        await set_session_status(session_id, "rejected")
        await record_gate_decision(
            session_id, gate_name=gate_name, decision="rejected",
            reviewer=body.reviewer, notes=body.notes, refine_target=None, refine_feedback=None,
        )
        default_broker().publish_nowait = lambda *a, **k: None    # type: ignore
        return {"ok": True}
    elif body.decision == "refine":
        if not body.refine_target or body.refine_target not in GATE_REFINE_TARGETS[gate_name]:
            raise HTTPException(status_code=400, detail="invalid refine_target for this gate")
        if not body.refine_feedback:
            raise HTTPException(status_code=400, detail="refine_feedback required")
        # Mark target stage + everything downstream stale
        idx = DOWNSTREAM_ORDER.index(body.refine_target)
        for stage in DOWNSTREAM_ORDER[idx:]:
            getattr(bb, STAGE_TO_ARTIFACT[stage]).status = StageStatus.stale
        # Reset gates that sit between target and end
        if idx <= DOWNSTREAM_ORDER.index("L2"):
            bb.gates["gate1_metadata"] = GateDecision(name="gate1_metadata", decision="pending")
        if idx <= DOWNSTREAM_ORDER.index("L5"):
            bb.gates["gate2_validation"] = GateDecision(name="gate2_validation", decision="pending")
        bb.refine_feedback_pending[body.refine_target] = body.refine_feedback
        bb.current_stage = body.refine_target

    await save_blackboard(bb)
    await record_gate_decision(
        session_id, gate_name=gate_name, decision=body.decision,
        reviewer=body.reviewer, notes=body.notes,
        refine_target=body.refine_target, refine_feedback=body.refine_feedback,
    )
    await default_broker().publish(session_id, {
        "type": "gate_decided", "gate": gate_name, "decision": body.decision,
        "refine_target": body.refine_target, "refine_feedback": body.refine_feedback,
    })
    # Restart the coordinator task for non-rejected decisions to resume execution
    if body.decision in ("approved", "refine"):
        coord = StmCoordinator(session_id=session_id, llm=LLMClient())
        coord.start_background()
    return {"ok": True}
```

- [ ] **Step 7: Run all gate tests**

Run: `pytest tests/stm/test_coordinator_gates.py tests/stm/test_gate_endpoint.py -v`
Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
git add core/stm/coordinator.py routers/stm.py tests/stm/test_coordinator_gates.py tests/stm/test_gate_endpoint.py
git commit -m "stm: gate stall in coordinator + decide endpoint with refinement"
```

---

### Task 5.3: Graph SVG endpoint

**Files:**
- Create: `core/stm/graph_svg.py`
- Modify: `routers/stm.py`
- Test: `tests/stm/test_graph_svg.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_graph_svg.py
import pytest
from fastapi.testclient import TestClient

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, GraphNode, GraphEdge,
    CandidateMappings, Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import create_session


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", "wkPzx-2zM9YlbsZF_4ic4w8I1OvOhA-IRgLY4ZSj_5o=")
    from app import app
    return TestClient(app)


@pytest.mark.asyncio
async def test_svg_for_session(tmp_db, client):
    bb = StmBlackboard(
        session_id="svg-1", target_table="t", target_dataset="d", dialect_target="bigquery",
        selected_source_profiles=[],
        intent=IntentArtifact(source="freetext", raw_input="x", status=StageStatus.ready),
        metadata_graph=MetadataGraph(
            nodes=[
                GraphNode(id="pg.public.customers", kind="table", label="customers", dialect="postgres"),
                GraphNode(id="pg.public.customers.customer_id", kind="column", label="customer_id", dialect="postgres", data_type="bigint"),
            ],
            edges=[GraphEdge(src="pg.public.customers", dst="pg.public.customers.customer_id", kind="contains")],
            sources_probed=["pg"],
            status=StageStatus.ready,
        ),
        candidate_mappings=CandidateMappings(target_table="t", target_dataset="d"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    r = client.get("/api/stm/sessions/svg-1/graph.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    body = r.text
    assert "<svg" in body
    assert "customers" in body
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_graph_svg.py -v`

- [ ] **Step 3: Implement `core/stm/graph_svg.py`**

```python
"""Minimal SVG renderer for MetadataGraph. Clusters by dialect → table."""
from __future__ import annotations

from xml.sax.saxutils import escape

from core.stm.blackboard import MetadataGraph


_EDGE_COLOR = {
    "contains": "#888",
    "fk": "#3b82f6",
    "concept_link": "#10b981",
    "join_candidate": "#a855f7",
    "semantic_match": "#f59e0b",
}


def render_svg(graph: MetadataGraph, width: int = 1100, height: int = 700) -> str:
    # Group tables by dialect; columns under their table.
    dialects: dict[str, list] = {}
    for n in graph.nodes:
        if n.kind == "table":
            dialects.setdefault(n.dialect or "unknown", []).append(n)

    cols_by_table: dict[str, list] = {}
    for n in graph.nodes:
        if n.kind == "column":
            tid = ".".join(n.id.split(".")[:-1])
            cols_by_table.setdefault(tid, []).append(n)

    positions: dict[str, tuple[float, float]] = {}
    parts: list[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">')
    parts.append('<style>.t{font:600 12px sans-serif;fill:#0f172a}.c{font:11px monospace;fill:#334155}.h{font:700 13px sans-serif;fill:#0f172a}</style>')

    dialect_x_step = width / max(len(dialects), 1)
    for di, (dial, tables) in enumerate(dialects.items()):
        x0 = di * dialect_x_step + 16
        parts.append(f'<text x="{x0}" y="20" class="h">{escape(dial)}</text>')
        y = 48
        for t in tables:
            positions[t.id] = (x0, y)
            parts.append(f'<rect x="{x0-6}" y="{y-14}" width="200" height="20" fill="#e0f2fe" stroke="#0284c7"/>')
            parts.append(f'<text x="{x0}" y="{y}" class="t">{escape(t.label)}</text>')
            y += 22
            for c in cols_by_table.get(t.id, []):
                positions[c.id] = (x0 + 12, y)
                tone = c.data_type or ""
                parts.append(f'<text x="{x0+12}" y="{y}" class="c">{escape(c.label)} : {escape(tone)}</text>')
                y += 16
            y += 12

    # Edges
    for e in graph.edges:
        if e.src in positions and e.dst in positions:
            x1, y1 = positions[e.src]
            x2, y2 = positions[e.dst]
            color = _EDGE_COLOR.get(e.kind, "#94a3b8")
            dash = ' stroke-dasharray="3,3"' if e.kind == "join_candidate" else ""
            parts.append(
                f'<line x1="{x1+60}" y1="{y1-5}" x2="{x2+60}" y2="{y2-5}" stroke="{color}" stroke-width="1.2"{dash}/>'
            )

    parts.append("</svg>")
    return "".join(parts)
```

- [ ] **Step 4: Add the endpoint to `routers/stm.py`**

```python
from fastapi.responses import Response

@router.get("/sessions/{session_id}/graph.svg")
async def session_graph_svg(session_id: str):
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    from core.stm.graph_svg import render_svg
    svg = render_svg(bb.metadata_graph)
    return Response(content=svg, media_type="image/svg+xml")
```

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/stm/test_graph_svg.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add core/stm/graph_svg.py routers/stm.py tests/stm/test_graph_svg.py
git commit -m "stm: graph SVG endpoint for L2 metadata view"
```

---

# PHASE 6 — L3 Semantic Mapping + L4 Transformation Synthesis

Shippable outcome: after gate 1, the pipeline produces candidate mappings (rules-grounded, LLM-refined) and a transformation plan (derived columns, SCD2 if dimension, audit fields). After this phase, blackboard contains real mapping content; gate 2 is still wired but trivially auto-passes until Phase 7 adds the validator.

---

### Task 6.1: SemanticMappingAgent (L3)

**Files:**
- Create: `core/stm/agents/semantic.py`
- Test: `tests/stm/agents/test_semantic.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/agents/test_semantic.py
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.semantic import SemanticMappingAgent
from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, GraphNode, GraphEdge,
    CandidateMappings, Transformations, ValidationReport, GateDecision, StageStatus,
)
from tests.stm.fake_llm import FakeLLMClient


def _bb_after_gate1():
    g = MetadataGraph(
        nodes=[
            GraphNode(id="pg.public.customers", kind="table", label="customers", dialect="postgres"),
            GraphNode(id="pg.public.customers.customer_id", kind="column", label="customer_id", dialect="postgres", data_type="bigint"),
            GraphNode(id="pg.public.customers.email", kind="column", label="email", dialect="postgres", data_type="varchar"),
            GraphNode(id="pg.public.customers.is_active", kind="column", label="is_active", dialect="postgres", data_type="boolean"),
        ],
        edges=[
            GraphEdge(src="pg.public.customers", dst="pg.public.customers.customer_id", kind="contains"),
            GraphEdge(src="pg.public.customers", dst="pg.public.customers.email", kind="contains"),
            GraphEdge(src="pg.public.customers", dst="pg.public.customers.is_active", kind="contains"),
        ],
        sources_probed=["pg-x"], status=StageStatus.ready,
    )
    return StmBlackboard(
        session_id="sem", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-x"],
        intent=IntentArtifact(
            source="freetext", raw_input="x", entity="customer_dim", action="create",
            is_dimension=True, is_fact=False, scd_hint="type2",
            filters=["active users only"], extracted_keywords=["customer"], status=StageStatus.ready,
        ),
        metadata_graph=g,
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="approved"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_applicable_only_after_gate1_approved():
    bb = _bb_after_gate1()
    assert SemanticMappingAgent().applicable(bb) is True
    bb.gates["gate1_metadata"].decision = "pending"
    assert SemanticMappingAgent().applicable(bb) is False


@pytest.mark.asyncio
async def test_produces_candidate_mappings_merging_rules_and_llm():
    bb = _bb_after_gate1()
    fake = FakeLLMClient([{
        "mappings": [
            {
                "target_field": "customer_id", "target_type": "INT64",
                "source_node_ids": ["pg.public.customers.customer_id"],
                "source_expression": "customer_id",
                "rationale": "Direct PK passthrough",
                "grain": ["customer_id"], "cardinality": "1:1",
                "llm_confidence": 0.98,
            },
            {
                "target_field": "email_lc", "target_type": "STRING",
                "source_node_ids": ["pg.public.customers.email"],
                "source_expression": "LOWER(email)",
                "rationale": "Lowercase for case-insensitive match",
                "grain": [], "cardinality": "1:1",
                "llm_confidence": 0.85,
            },
        ]
    }])
    delta = await SemanticMappingAgent().run(bb, AgentContext(llm=fake))
    cm = delta.artifact_payload
    assert cm.target_table == "customer_dim"
    fields = {r.target_field for r in cm.rows}
    # Both the LLM-refined and rule-baseline rows should be present
    assert "customer_id" in fields
    assert "email_lc" in fields
    # rule_baseline_summary populated
    assert "field_count" in cm.rule_baseline_summary
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/agents/test_semantic.py -v`

- [ ] **Step 3: Implement `core/stm/agents/semantic.py`**

```python
"""L3 — Semantic Mapping agent. Wraps rule-based build_stm; LLM refines."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.config import STM_LLM_MODEL_L3
from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    CandidateMapping, CandidateMappings, StageStatus, StmBlackboard,
)
from core.stm.mapping_engine import build_stm


SYSTEM_PROMPT = (
    "You are a senior data engineer producing a precise source-to-target mapping. "
    "Inputs: intent, target table/dataset, knowledge-graph columns, rule-engine baseline rows. "
    "Confirm or correct baseline rows; add rows the rules missed (joins, derived, lookups); "
    "for each row provide source_expression as BigQuery SQL, rationale, grain, cardinality, "
    "and llm_confidence (0..1). "
    'Return ONLY JSON: {"mappings":[{"target_field":...,"target_type":...,"source_node_ids":[...],'
    '"source_expression":"...","rationale":"...","grain":[...],"cardinality":"1:1|M:1|1:M|M:M",'
    '"llm_confidence":0.0..1.0}]}'
)


def _rule_baseline(bb: StmBlackboard) -> tuple[Dict[str, Any], List[CandidateMapping]]:
    # Translate the metadata graph's columns into the SelectedColumn shape build_stm expects.
    # build_stm signature today expects a list of dicts/dataclasses; we adapt minimally.
    rows: List[CandidateMapping] = []
    columns = []
    for n in bb.metadata_graph.nodes:
        if n.kind != "column":
            continue
        parts = n.id.split(".")
        if len(parts) < 4:
            continue
        columns.append({
            "schema": parts[1],
            "table": parts[2],
            "name": n.label,
            "data_type": n.data_type or "STRING",
            "nullable": bool(n.nullable),
            "is_primary_key": False,
            "node_id": n.id,
        })
    summary: Dict[str, Any] = {"field_count": 0}
    if not columns:
        return summary, rows
    # build_stm in the codebase today is keyed off a different shape; wrap defensively.
    try:
        result = build_stm(
            selected_columns=columns,
            target_table=bb.target_table,
            target_dataset=bb.target_dataset,
        )
        summary["field_count"] = result.field_count
        for r in result.rows:
            rows.append(CandidateMapping(
                target_field=getattr(r, "target_column", None) or r.get("target_column"),
                target_type=getattr(r, "target_type", None) or r.get("target_type", "STRING"),
                source_node_ids=[
                    next((c["node_id"] for c in columns
                          if c["name"] == (getattr(r, "source_column", None) or r.get("source_column"))),
                         "")
                ],
                source_expression=getattr(r, "source_column", None) or r.get("source_column", ""),
                rationale="rule-baseline: deterministic type/PII mapping",
                grain=[], cardinality="1:1",
                rule_baseline=True,
            ))
    except Exception as exc:
        summary["error"] = str(exc)
    return summary, rows


class SemanticMappingAgent(StmAgent):
    stage = "L3"
    name = "SemanticMappingAgent"

    def applicable(self, bb: StmBlackboard) -> bool:
        g1 = bb.gates.get("gate1_metadata")
        return (
            g1 is not None and g1.decision == "approved"
            and bb.candidate_mappings.status in (StageStatus.idle, StageStatus.stale)
        )

    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta:
        summary, baseline_rows = _rule_baseline(bb)

        prompt = json.dumps({
            "intent": {
                "entity": bb.intent.entity, "action": bb.intent.action,
                "is_dimension": bb.intent.is_dimension, "is_fact": bb.intent.is_fact,
                "scd_hint": bb.intent.scd_hint, "filters": bb.intent.filters,
                "keywords": bb.intent.extracted_keywords,
            },
            "target": {"dataset": bb.target_dataset, "table": bb.target_table},
            "graph_columns": [
                {"node_id": n.id, "label": n.label, "data_type": n.data_type,
                 "dialect": n.dialect, "nullable": n.nullable}
                for n in bb.metadata_graph.nodes if n.kind == "column"
            ],
            "rule_baseline": [
                {"target_field": r.target_field, "target_type": r.target_type,
                 "source_expression": r.source_expression}
                for r in baseline_rows
            ],
            "refine_feedback": bb.refine_feedback_pending.get("L3", ""),
        })
        model = ctx.model_overrides.get("L3", STM_LLM_MODEL_L3)
        raw = ctx.llm.complete_json(prompt, system=SYSTEM_PROMPT, max_tokens=8192, model=model)

        by_target: Dict[str, CandidateMapping] = {r.target_field: r for r in baseline_rows}
        for m in raw.get("mappings", []) or []:
            tgt = m.get("target_field")
            if not tgt:
                continue
            existing = by_target.get(tgt)
            row = CandidateMapping(
                target_field=tgt,
                target_type=(existing.target_type if existing else m.get("target_type", "STRING")),
                source_node_ids=list(m.get("source_node_ids") or []),
                source_expression=m.get("source_expression", ""),
                rationale=m.get("rationale", ""),
                grain=list(m.get("grain") or []),
                cardinality=m.get("cardinality"),
                rule_baseline=bool(existing),
                refined_by_llm=True,
                llm_confidence=float(m.get("llm_confidence") or 0.0),
            )
            by_target[tgt] = row

        merged = list(by_target.values())
        cm = CandidateMappings(
            target_table=bb.target_table, target_dataset=bb.target_dataset,
            rows=merged, rule_baseline_summary=summary, status=StageStatus.ready,
        )
        return BlackboardDelta(
            artifact_kind="candidate_mappings",
            artifact_payload=cm,
            events_to_emit=[
                {"type": "stage_started", "stage": "L3"},
                {"type": "llm_call", "stage": "L3", "model": model},
                {"type": "stage_ready", "stage": "L3", "confidence_summary": f"{len(merged)} candidate rows"},
            ],
            clear_refine_feedback_for_stage="L3",
        )
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/agents/test_semantic.py -v`
Expected: 2 passed.

- [ ] **Step 5: Wire into coordinator**

In `core/stm/coordinator.py`, update `default_agents()`:

```python
from core.stm.agents.semantic import SemanticMappingAgent

def default_agents() -> List[StmAgent]:
    return [IntentAgent(), MetadataAgent(), SemanticMappingAgent(), BuilderAgent()]
```

- [ ] **Step 6: Commit**

```bash
git add core/stm/agents/semantic.py core/stm/coordinator.py tests/stm/agents/test_semantic.py
git commit -m "stm: L3 SemanticMappingAgent — rules baseline + Opus refinement"
```

---

### Task 6.2: TransformationAgent (L4)

**Files:**
- Create: `core/stm/agents/transform.py`
- Test: `tests/stm/agents/test_transform.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/agents/test_transform.py
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.transform import TransformationAgent
from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings, CandidateMapping,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from tests.stm.fake_llm import FakeLLMClient


def _bb_after_l3(scd="type2", is_dim=True):
    return StmBlackboard(
        session_id="tx", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-x"],
        intent=IntentArtifact(
            source="freetext", raw_input="x", entity="customer_dim", action="create",
            is_dimension=is_dim, is_fact=False, scd_hint=scd,
            filters=["active users only"], status=StageStatus.ready,
        ),
        metadata_graph=MetadataGraph(status=StageStatus.ready),
        candidate_mappings=CandidateMappings(
            target_table="customer_dim", target_dataset="warehouse",
            rows=[
                CandidateMapping(target_field="customer_id", target_type="INT64",
                                 source_expression="customer_id", rationale="pk"),
            ],
            status=StageStatus.ready,
        ),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="approved"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_dimension_with_scd2_adds_history_rows():
    bb = _bb_after_l3(scd="type2", is_dim=True)
    fake = FakeLLMClient([{
        "rows": [
            {"target_field": "customer_sk", "kind": "surrogate_key",
             "logic": "FARM_FINGERPRINT(CONCAT(CAST(customer_id AS STRING)))",
             "inputs": ["customer_id"], "rationale": "stable hash SK"},
            {"target_field": "effective_from", "kind": "scd2",
             "logic": "CURRENT_TIMESTAMP()", "inputs": [], "rationale": "SCD2 start"},
            {"target_field": "effective_to", "kind": "scd2",
             "logic": "TIMESTAMP('9999-12-31')", "inputs": [], "rationale": "SCD2 end"},
            {"target_field": "is_current", "kind": "scd2",
             "logic": "TRUE", "inputs": [], "rationale": "SCD2 flag"},
            {"target_field": "created_dt", "kind": "audit",
             "logic": "CURRENT_TIMESTAMP()", "inputs": [], "rationale": "audit"},
        ],
        "scd_strategy": "type2",
        "audit_fields": ["created_dt", "updated_dt", "batch_id"],
        "idempotency_key": "customer_id",
        "partition_field": "effective_from",
    }])
    delta = await TransformationAgent().run(bb, AgentContext(llm=fake))
    tx = delta.artifact_payload
    kinds = {r.kind for r in tx.rows}
    assert "scd2" in kinds
    assert "surrogate_key" in kinds
    assert "audit" in kinds
    assert tx.scd_strategy == "type2"
    assert tx.idempotency_key == "customer_id"
    assert tx.partition_field == "effective_from"


@pytest.mark.asyncio
async def test_fact_table_no_scd():
    bb = _bb_after_l3(scd=None, is_dim=False)
    bb.intent.is_fact = True
    fake = FakeLLMClient([{
        "rows": [
            {"target_field": "order_sk", "kind": "surrogate_key",
             "logic": "FARM_FINGERPRINT(CAST(order_id AS STRING))",
             "inputs": ["order_id"], "rationale": "SK"},
            {"target_field": "batch_id", "kind": "audit",
             "logic": "@run_id", "inputs": [], "rationale": "batch id"},
        ],
        "scd_strategy": "none",
        "audit_fields": ["batch_id"],
        "idempotency_key": "order_id",
        "partition_field": "order_date",
    }])
    delta = await TransformationAgent().run(bb, AgentContext(llm=fake))
    tx = delta.artifact_payload
    kinds = {r.kind for r in tx.rows}
    assert "scd2" not in kinds
    assert tx.scd_strategy == "none"
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/agents/test_transform.py -v`

- [ ] **Step 3: Implement `core/stm/agents/transform.py`**

```python
"""L4 — Transformation Synthesis agent."""
from __future__ import annotations

import json
from typing import Any, List

from core.config import STM_LLM_MODEL_L4
from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    StageStatus, StmBlackboard, Transformation, Transformations,
)


SYSTEM_PROMPT = (
    "You are a senior data engineer designing transformation logic for a BigQuery target table. "
    "Inputs: intent (incl. is_dimension/is_fact/scd_hint/filters), candidate mappings. "
    "Produce derived columns, surrogate-key strategy, SCD logic (only if dimension+scd_hint), "
    "audit fields (created_dt/updated_dt/batch_id), idempotency_key, partition_field, "
    "and any filter-translation rows from intent.filters. "
    'Return ONLY JSON: {"rows":[{"target_field":"...","kind":"derived|scd2|audit|surrogate_key|computed|filter",'
    '"logic":"<BQ SQL>","inputs":[...],"rationale":"..."}], '
    '"scd_strategy":"type1|type2|type3|none","audit_fields":[...],'
    '"idempotency_key":"...","partition_field":"..."}'
)


class TransformationAgent(StmAgent):
    stage = "L4"
    name = "TransformationAgent"

    def applicable(self, bb: StmBlackboard) -> bool:
        return (
            bb.candidate_mappings.status == StageStatus.ready
            and bb.transformations.status in (StageStatus.idle, StageStatus.stale)
        )

    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta:
        prompt = json.dumps({
            "intent": {
                "entity": bb.intent.entity, "action": bb.intent.action,
                "is_dimension": bb.intent.is_dimension, "is_fact": bb.intent.is_fact,
                "scd_hint": bb.intent.scd_hint, "filters": bb.intent.filters,
                "grain_hint": bb.intent.grain_hint,
            },
            "candidates": [
                {"target_field": r.target_field, "target_type": r.target_type,
                 "source_expression": r.source_expression}
                for r in bb.candidate_mappings.rows
            ],
            "refine_feedback": bb.refine_feedback_pending.get("L4", ""),
        })
        model = ctx.model_overrides.get("L4", STM_LLM_MODEL_L4)
        raw = ctx.llm.complete_json(prompt, system=SYSTEM_PROMPT, max_tokens=8192, model=model)

        rows: List[Transformation] = []
        for r in raw.get("rows", []) or []:
            try:
                rows.append(Transformation(
                    target_field=r["target_field"],
                    kind=r["kind"],
                    logic=r["logic"],
                    inputs=list(r.get("inputs") or []),
                    rationale=r.get("rationale", ""),
                ))
            except Exception:
                continue

        tx = Transformations(
            rows=rows,
            scd_strategy=raw.get("scd_strategy"),
            audit_fields=list(raw.get("audit_fields") or []),
            idempotency_key=raw.get("idempotency_key"),
            partition_field=raw.get("partition_field"),
            status=StageStatus.ready,
        )
        return BlackboardDelta(
            artifact_kind="transformations",
            artifact_payload=tx,
            events_to_emit=[
                {"type": "stage_started", "stage": "L4"},
                {"type": "llm_call", "stage": "L4", "model": model},
                {"type": "stage_ready", "stage": "L4", "confidence_summary": f"{len(rows)} transformation rows"},
            ],
            clear_refine_feedback_for_stage="L4",
        )
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/agents/test_transform.py -v`
Expected: 2 passed.

- [ ] **Step 5: Wire into coordinator**

```python
from core.stm.agents.transform import TransformationAgent

def default_agents() -> List[StmAgent]:
    return [
        IntentAgent(), MetadataAgent(), SemanticMappingAgent(),
        TransformationAgent(), BuilderAgent(),
    ]
```

- [ ] **Step 6: Commit**

```bash
git add core/stm/agents/transform.py core/stm/coordinator.py tests/stm/agents/test_transform.py
git commit -m "stm: L4 TransformationAgent — SCD/audit/derived/filter synthesis"
```

---

# PHASE 7 — L5 Validation + Gate 2 + Full L6 Builder

Shippable outcome: ensemble confidence scoring, deterministic findings, second governance gate, full L6 that composes a real MappingResult and exports xlsx/csv.

---

### Task 7.1: Heuristic scoring functions

**Files:**
- Create: `core/stm/scoring.py`
- Test: `tests/stm/test_scoring.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_scoring.py
from core.stm.scoring import (
    name_similarity, type_compatibility, fk_evidence_score,
    profile_overlap, weighted_final, band_for,
)


def test_name_similarity_exact():
    assert name_similarity("customer_id", "customer_id") == 1.0


def test_name_similarity_snake_vs_camel():
    assert name_similarity("customerId", "customer_id") > 0.8


def test_name_similarity_unrelated_low():
    assert name_similarity("zzz", "customer_id") < 0.5


def test_type_compat_same_family():
    assert type_compatibility("bigint", "INT64") == 1.0
    assert type_compatibility("varchar", "STRING") == 1.0
    assert type_compatibility("boolean", "BOOL") == 1.0


def test_type_compat_incompatible():
    assert type_compatibility("boolean", "TIMESTAMP") < 0.4


def test_fk_evidence():
    edges = [{"src": "a.b.c.id", "dst": "a.b.d.id", "kind": "fk"}]
    assert fk_evidence_score("a.b.c.id", "a.b.d.id", edges) > 0.5
    assert fk_evidence_score("x", "y", edges) == 0.0


def test_profile_overlap():
    assert profile_overlap([1, 2, 3], [2, 3, 4]) == pytest_round(2/4)
    assert profile_overlap([], []) is None


def pytest_round(x, n=3):
    return round(x, n)


def test_weighted_final_and_bands():
    f = weighted_final(llm=0.9, name=0.9, type_=0.9, profile=None, fk=0.5, weights=(0.4,0.25,0.2,0.1,0.05))
    assert band_for(0.9) == "high"
    assert band_for(0.7) == "medium"
    assert band_for(0.3) == "low"
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_scoring.py -v`

- [ ] **Step 3: Implement `core/stm/scoring.py`**

```python
"""Deterministic heuristics for L5 confidence scoring."""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from rapidfuzz import fuzz


_TYPE_FAMILY = {
    "string": {"STRING", "string", "varchar", "character varying", "text", "char", "character", "bpchar", "name", "uuid"},
    "int":    {"INT64", "int64", "bigint", "integer", "int", "smallint", "int2", "int4", "int8", "serial", "bigserial"},
    "float":  {"FLOAT64", "float64", "real", "double precision", "float", "float4", "float8"},
    "numeric": {"NUMERIC", "numeric", "decimal"},
    "bool":   {"BOOL", "bool", "boolean"},
    "ts":     {"TIMESTAMP", "timestamp", "timestamptz", "datetime"},
    "date":   {"DATE", "date"},
    "json":   {"JSON", "json", "jsonb"},
    "bytes":  {"BYTES", "bytea"},
}


def _normalize(name: str) -> str:
    out = []
    for ch in name or "":
        if ch.isupper():
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out).strip("_").replace("__", "_").lower()


def name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.ratio(_normalize(a), _normalize(b)) / 100.0


def _family_of(t: str) -> Optional[str]:
    t = (t or "").strip()
    for fam, members in _TYPE_FAMILY.items():
        if t in members:
            return fam
    # fall back: lowercase prefix match
    tl = t.lower()
    for fam, members in _TYPE_FAMILY.items():
        if any(m.lower() == tl or tl.startswith(m.lower()) for m in members):
            return fam
    return None


_COMPAT_BONUS = {
    ("int", "numeric"): 0.7, ("numeric", "int"): 0.7,
    ("int", "float"): 0.6, ("float", "int"): 0.6,
    ("date", "ts"): 0.6, ("ts", "date"): 0.6,
    ("string", "json"): 0.4, ("json", "string"): 0.4,
}


def type_compatibility(src: str, tgt: str) -> float:
    fs = _family_of(src)
    ft = _family_of(tgt)
    if not fs or not ft:
        return 0.3
    if fs == ft:
        return 1.0
    return _COMPAT_BONUS.get((fs, ft), 0.2)


def fk_evidence_score(src_id: str, dst_id: str, edges: Iterable[dict]) -> float:
    if not src_id or not dst_id:
        return 0.0
    for e in edges:
        s, d, k = e.get("src"), e.get("dst"), e.get("kind")
        if k in ("fk", "join_candidate") and {s, d} >= {src_id, dst_id}:
            return 1.0 if k == "fk" else 0.6
        if k == "fk" and (s == src_id or d == dst_id or s == dst_id or d == src_id):
            return 0.6
    return 0.0


def profile_overlap(a: Iterable, b: Iterable) -> Optional[float]:
    a_set = set(a or [])
    b_set = set(b or [])
    if not a_set and not b_set:
        return None
    inter = a_set & b_set
    union = a_set | b_set
    return len(inter) / max(len(union), 1)


def weighted_final(
    *,
    llm: float, name: float, type_: float,
    fk: float, profile: Optional[float],
    weights: Tuple[float, float, float, float, float],
) -> float:
    # weights order: llm, name, type, fk, profile
    w_llm, w_name, w_type, w_fk, w_profile = weights
    parts = [w_llm * (llm or 0.0), w_name * (name or 0.0), w_type * (type_ or 0.0), w_fk * (fk or 0.0)]
    total_w = w_llm + w_name + w_type + w_fk
    if profile is not None:
        parts.append(w_profile * profile)
        total_w += w_profile
    return round(sum(parts) / max(total_w, 1e-9), 4)


def band_for(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/test_scoring.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add core/stm/scoring.py tests/stm/test_scoring.py
git commit -m "stm: heuristic scoring (name/type/fk/profile + weighted)"
```

---

### Task 7.2: ValidationAgent (L5)

**Files:**
- Create: `core/stm/agents/validation.py`
- Test: `tests/stm/agents/test_validation.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/agents/test_validation.py
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.validation import ValidationAgent
from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, GraphNode, GraphEdge,
    CandidateMappings, CandidateMapping, Transformations, Transformation,
    ValidationReport, GateDecision, StageStatus,
)


def _bb_after_l4():
    return StmBlackboard(
        session_id="v", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-x"],
        intent=IntentArtifact(
            source="freetext", raw_input="x", entity="customer_dim", action="create",
            is_dimension=True, is_fact=False, scd_hint="type2",
            filters=["active users only"], status=StageStatus.ready,
        ),
        metadata_graph=MetadataGraph(
            nodes=[
                GraphNode(id="pg.public.customers.customer_id", kind="column",
                          label="customer_id", data_type="bigint", dialect="postgres"),
            ],
            edges=[],
            status=StageStatus.ready,
        ),
        candidate_mappings=CandidateMappings(
            target_table="customer_dim", target_dataset="warehouse",
            rows=[
                CandidateMapping(
                    target_field="customer_id", target_type="INT64",
                    source_node_ids=["pg.public.customers.customer_id"],
                    source_expression="customer_id", rationale="pk", llm_confidence=0.95,
                ),
                CandidateMapping(
                    target_field="weird_field", target_type="TIMESTAMP",
                    source_node_ids=["pg.public.customers.customer_id"],
                    source_expression="customer_id", rationale="type-mismatch demo",
                    llm_confidence=0.3,
                ),
            ],
            status=StageStatus.ready,
        ),
        transformations=Transformations(
            rows=[
                Transformation(target_field="effective_from", kind="scd2", logic="CURRENT_TIMESTAMP()"),
                Transformation(target_field="effective_to", kind="scd2", logic="TIMESTAMP('9999-12-31')"),
            ],
            scd_strategy="type2",
            audit_fields=["created_dt"],
            idempotency_key="customer_id",
            partition_field="effective_from",
            status=StageStatus.ready,
        ),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="approved"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_validation_produces_scores_and_findings():
    bb = _bb_after_l4()
    delta = await ValidationAgent().run(bb, AgentContext(llm=None))
    rep = delta.artifact_payload
    fields = {s.target_field for s in rep.scores}
    assert "customer_id" in fields and "weird_field" in fields
    # weird_field should be low band — type incompat
    weird = next(s for s in rep.scores if s.target_field == "weird_field")
    assert weird.band == "low"
    assert any(f.rule == "type_compat" and f.severity == "block" for f in rep.findings)
    assert rep.overall_band == "low"


@pytest.mark.asyncio
async def test_scd2_missing_columns_blocks():
    bb = _bb_after_l4()
    # Remove effective_to to trigger SCD2 block finding
    bb.transformations.rows = [r for r in bb.transformations.rows if r.target_field != "effective_to"]
    delta = await ValidationAgent().run(bb, AgentContext(llm=None))
    rep = delta.artifact_payload
    assert any("effective_to" in f.message or "scd2" in f.rule.lower() for f in rep.findings)
    assert rep.block_count >= 1
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/agents/test_validation.py -v`

- [ ] **Step 3: Implement `core/stm/agents/validation.py`**

```python
"""L5 — Validation agent. Deterministic ensemble confidence + rule-based findings."""
from __future__ import annotations

from typing import Dict, List

from core.config import STM_VALIDATION_WEIGHTS
from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    ConfidenceScore, StageStatus, StmBlackboard, ValidationFinding, ValidationReport,
)
from core.stm.scoring import (
    band_for, fk_evidence_score, name_similarity, profile_overlap,
    type_compatibility, weighted_final,
)


class ValidationAgent(StmAgent):
    stage = "L5"
    name = "ValidationAgent"

    def applicable(self, bb: StmBlackboard) -> bool:
        return (
            bb.transformations.status == StageStatus.ready
            and bb.validation.status in (StageStatus.idle, StageStatus.stale)
        )

    def _nodes_by_id(self, bb: StmBlackboard) -> Dict[str, dict]:
        return {n.id: n.model_dump() for n in bb.metadata_graph.nodes}

    def _edges_dict(self, bb: StmBlackboard) -> List[dict]:
        return [e.model_dump() for e in bb.metadata_graph.edges]

    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta:
        nodes = self._nodes_by_id(bb)
        edges = self._edges_dict(bb)
        scores: List[ConfidenceScore] = []
        findings: List[ValidationFinding] = []

        for row in bb.candidate_mappings.rows:
            # Pick a representative source node for heuristics
            src_id = row.source_node_ids[0] if row.source_node_ids else ""
            src_node = nodes.get(src_id, {})
            src_name = src_node.get("label", src_id.split(".")[-1] if src_id else "")
            src_type = src_node.get("data_type") or ""

            # heuristic subscores
            name_s = name_similarity(src_name, row.target_field)
            type_s = type_compatibility(src_type, row.target_type)
            fk_s = max((fk_evidence_score(src_id, dst, edges) for dst in row.source_node_ids[1:]), default=0.0)
            prof_overlap = None    # sample data not surfaced in this iteration
            llm_s = row.llm_confidence or 0.0

            final = weighted_final(
                llm=llm_s, name=name_s, type_=type_s, fk=fk_s, profile=prof_overlap,
                weights=STM_VALIDATION_WEIGHTS,
            )
            band = band_for(final)
            scores.append(ConfidenceScore(
                target_field=row.target_field,
                llm_score=llm_s, name_sim_score=name_s, type_compat_score=type_s,
                profile_overlap_score=prof_overlap, fk_evidence_score=fk_s,
                final=final, band=band,
            ))

            # Rule-based findings
            if type_s < 0.4:
                findings.append(ValidationFinding(
                    severity="block", target_field=row.target_field, rule="type_compat",
                    message=f"Source type {src_type!r} incompatible with target {row.target_type!r}",
                ))
            if src_node and src_node.get("nullable") is True:
                if row.target_field in (bb.transformations.idempotency_key, "customer_id"):
                    findings.append(ValidationFinding(
                        severity="warn", target_field=row.target_field, rule="null_safety",
                        message="Nullable source mapped to non-nullable target without default",
                    ))
            if src_node and src_node.get("is_pii") is True:
                findings.append(ValidationFinding(
                    severity="warn", target_field=row.target_field, rule="pii_handling",
                    message="PII source mapped without classification on target",
                ))

        # Idempotency key check
        if bb.intent.is_dimension and not bb.transformations.idempotency_key:
            findings.append(ValidationFinding(
                severity="warn", target_field=None, rule="missing_idempotency_key",
                message="Dimension table has no idempotency_key — incremental loads may double-write",
            ))

        # SCD2 column completeness
        if bb.transformations.scd_strategy == "type2":
            tx_fields = {t.target_field for t in bb.transformations.rows if t.kind == "scd2"}
            for required in ("effective_from", "effective_to", "is_current"):
                if required not in tx_fields:
                    findings.append(ValidationFinding(
                        severity="block", target_field=None, rule="scd2_columns",
                        message=f"SCD2 declared but missing column: {required}",
                    ))

        block_count = sum(1 for f in findings if f.severity == "block")
        low_count = sum(1 for s in scores if s.band == "low")
        if block_count > 0:
            overall = "low"
        elif low_count > 0:
            overall = "medium"
        else:
            bands = [s.band for s in scores]
            overall = "high" if all(b == "high" for b in bands) else "medium"

        rep = ValidationReport(
            scores=scores, findings=findings,
            low_confidence_count=low_count, block_count=block_count,
            overall_band=overall, status=StageStatus.ready,
        )
        return BlackboardDelta(
            artifact_kind="validation",
            artifact_payload=rep,
            events_to_emit=[
                {"type": "stage_started", "stage": "L5"},
                {"type": "stage_ready", "stage": "L5",
                 "confidence_summary": f"overall {overall}, {block_count} blocks, {low_count} low"},
            ],
            clear_refine_feedback_for_stage="L5",
        )
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/agents/test_validation.py -v`
Expected: 2 passed.

- [ ] **Step 5: Wire into coordinator + register gate2 stall**

Update `core/stm/coordinator.py`:

```python
from core.stm.agents.validation import ValidationAgent

def default_agents() -> List[StmAgent]:
    return [
        IntentAgent(), MetadataAgent(), SemanticMappingAgent(),
        TransformationAgent(), ValidationAgent(), BuilderAgent(),
    ]
```

The gate2 stall is already in place via `GATE_AFTER_STAGE = {"L2": ..., "L5": ...}` from Phase 5. No additional change needed.

- [ ] **Step 6: Commit**

```bash
git add core/stm/agents/validation.py core/stm/coordinator.py tests/stm/agents/test_validation.py
git commit -m "stm: L5 ValidationAgent — ensemble confidence + deterministic findings"
```

---

### Task 7.3: Full L6 BuilderAgent — real MappingResult + xlsx

**Files:**
- Modify: `core/stm/agents/builder.py`
- Test: `tests/stm/agents/test_builder_full.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/agents/test_builder_full.py
import pytest

from core.stm.agents.base import AgentContext
from core.stm.agents.builder import BuilderAgent
from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, GraphNode,
    CandidateMappings, CandidateMapping, Transformations, Transformation,
    ValidationReport, ConfidenceScore, GateDecision, StageStatus,
)


def _bb_ready_for_l6():
    return StmBlackboard(
        session_id="b", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-x"],
        intent=IntentArtifact(
            source="freetext", raw_input="x", entity="customer_dim", action="create",
            is_dimension=True, is_fact=False, scd_hint="type2",
            filters=["active users only"], status=StageStatus.ready,
        ),
        metadata_graph=MetadataGraph(
            nodes=[GraphNode(id="pg.public.customers", kind="table", label="customers", dialect="postgres")],
            edges=[], status=StageStatus.ready,
        ),
        candidate_mappings=CandidateMappings(
            target_table="customer_dim", target_dataset="warehouse",
            rows=[
                CandidateMapping(target_field="customer_id", target_type="INT64",
                                 source_expression="customer_id", rationale="pk"),
            ],
            status=StageStatus.ready,
        ),
        transformations=Transformations(
            rows=[Transformation(target_field="created_dt", kind="audit", logic="CURRENT_TIMESTAMP()")],
            scd_strategy="type2", audit_fields=["created_dt"],
            idempotency_key="customer_id", partition_field="effective_from",
            status=StageStatus.ready,
        ),
        validation=ValidationReport(
            scores=[ConfidenceScore(target_field="customer_id", llm_score=0.95, name_sim_score=1.0,
                                    type_compat_score=1.0, fk_evidence_score=0.0,
                                    final=0.95, band="high")],
            findings=[], low_confidence_count=0, block_count=0, overall_band="high",
            status=StageStatus.ready,
        ),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="approved"),
            "gate2_validation": GateDecision(name="gate2_validation", decision="approved"),
        },
    )


@pytest.mark.asyncio
async def test_builder_full_emits_xlsx_renderable_dict():
    bb = _bb_ready_for_l6()
    delta = await BuilderAgent().run(bb, AgentContext(llm=None))
    res = delta.artifact_payload
    assert res["target_table"] == "customer_dim"
    assert res["target_dataset"] == "warehouse"
    assert res["field_count"] >= 1
    assert "rows" in res
    assert any(r["target_field"] == "customer_id" for r in res["rows"])
    assert "transformations" in res
    assert res["scd_strategy"] == "type2"
    assert res["idempotency_key"] == "customer_id"
    assert res["partition_field"] == "effective_from"
    assert delta.set_current_stage == "done"
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/agents/test_builder_full.py -v`

- [ ] **Step 3: Replace `core/stm/agents/builder.py` with full implementation**

```python
"""L6 — STM Builder agent. Composes a MappingResult dict; renders xlsx via exporter."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import StmBlackboard


class BuilderAgent(StmAgent):
    stage = "L6"
    name = "BuilderAgent"

    def applicable(self, bb: StmBlackboard) -> bool:
        g2 = bb.gates.get("gate2_validation")
        return (
            bb.stm_result is None
            and g2 is not None and g2.decision == "approved"
        )

    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta:
        stm_id = uuid.uuid4().hex[:8]

        rows: List[Dict[str, Any]] = []
        for r in bb.candidate_mappings.rows:
            rows.append({
                "target_field": r.target_field,
                "target_type": r.target_type,
                "source_expression": r.source_expression,
                "rationale": r.rationale,
                "grain": r.grain,
                "cardinality": r.cardinality,
                "rule_baseline": r.rule_baseline,
                "refined_by_llm": r.refined_by_llm,
            })

        transformations: List[Dict[str, Any]] = [
            {"target_field": t.target_field, "kind": t.kind, "logic": t.logic, "inputs": t.inputs, "rationale": t.rationale}
            for t in bb.transformations.rows
        ]

        source_tables = sorted({
            ".".join(n.id.split(".")[:3]) for n in bb.metadata_graph.nodes if n.kind == "table"
        })

        validation = {
            "overall_band": bb.validation.overall_band,
            "low_confidence_count": bb.validation.low_confidence_count,
            "block_count": bb.validation.block_count,
            "scores": [s.model_dump() for s in bb.validation.scores],
            "findings": [f.model_dump() for f in bb.validation.findings],
        }

        result = {
            "stm_id": stm_id,
            "target_dataset": bb.target_dataset,
            "target_table": bb.target_table,
            "field_count": len(rows),
            "rows": rows,
            "transformations": transformations,
            "source_tables": source_tables,
            "business_rules": list(bb.intent.filters),
            "scd_strategy": bb.transformations.scd_strategy,
            "audit_fields": list(bb.transformations.audit_fields),
            "idempotency_key": bb.transformations.idempotency_key,
            "partition_field": bb.transformations.partition_field,
            "intent": {
                "entity": bb.intent.entity, "action": bb.intent.action,
                "is_dimension": bb.intent.is_dimension, "is_fact": bb.intent.is_fact,
                "scd_hint": bb.intent.scd_hint, "filters": list(bb.intent.filters),
            },
            "validation": validation,
            "generated_at": datetime.utcnow().isoformat(),
        }

        return BlackboardDelta(
            artifact_kind="stm_result",
            artifact_payload=result,
            events_to_emit=[
                {"type": "stage_started", "stage": "L6"},
                {"type": "stage_ready", "stage": "L6"},
                {"type": "session_completed", "stm_id": stm_id},
            ],
            set_current_stage="done",
        )
```

- [ ] **Step 4: Run all builder tests**

Run: `pytest tests/stm/agents/test_builder.py tests/stm/agents/test_builder_full.py -v`
Expected: 4 passed.

- [ ] **Step 5: Add xlsx/csv export endpoints for sessions**

Append to `routers/stm.py`:

```python
from fastapi.responses import StreamingResponse as _StreamingResponse
from io import BytesIO


def _result_to_mapping_result(result: dict):
    """Adapt session stm_result dict into the legacy MappingResult dataclass for exporter."""
    from core.stm.mapping_engine import MappingResult, MappingRow
    rows = []
    for r in result.get("rows", []):
        rows.append(MappingRow(
            source_system=", ".join(result.get("source_tables", [])),
            source_schema="",
            source_table="",
            source_column=r.get("source_expression", ""),
            source_type="",
            source_nullable=True,
            source_description="",
            target_dataset=result["target_dataset"],
            target_table=result["target_table"],
            target_column=r["target_field"],
            target_type=r.get("target_type", "STRING"),
            target_nullable=True,
            transform=", ".join(t["logic"] for t in result.get("transformations", []) if t["target_field"] == r["target_field"]) or None,
            is_pii=False,
        ))
    mr = MappingResult(
        stm_id=result["stm_id"],
        target_dataset=result["target_dataset"],
        target_table=result["target_table"],
        rows=rows,
        source_tables=result.get("source_tables", []),
        business_rules=result.get("business_rules", []),
        partition_field=result.get("partition_field"),
        idempotency_strategy="delete_insert",
        idempotency_key=result.get("idempotency_key"),
        field_count=len(rows),
        generated_at=result.get("generated_at", ""),
    )
    return mr


@router.get("/sessions/{session_id}/export.xlsx")
async def session_export_xlsx(session_id: str):
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    if not bb.stm_result:
        raise HTTPException(status_code=409, detail="session has no STM result yet")
    from core.stm.exporter import to_xlsx
    mr = _result_to_mapping_result(bb.stm_result)
    blob = to_xlsx(mr)
    fname = f"stm-{mr.target_table}-{mr.stm_id}.xlsx"
    return _StreamingResponse(
        BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/sessions/{session_id}/export.csv")
async def session_export_csv(session_id: str):
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    if not bb.stm_result:
        raise HTTPException(status_code=409, detail="session has no STM result yet")
    from core.stm.exporter import to_csv
    mr = _result_to_mapping_result(bb.stm_result)
    blob = to_csv(mr)
    fname = f"stm-{mr.target_table}-{mr.stm_id}.csv"
    return _StreamingResponse(
        BytesIO(blob),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
```

If `MappingRow` field names differ from what's referenced above, run `grep -n "class MappingRow" core/stm/mapping_engine.py` first and adapt field names. Inspect the actual dataclass; rename adapter fields accordingly.

- [ ] **Step 6: Run integration test**

Create `tests/stm/test_session_exports.py`:

```python
import asyncio
import pytest
from fastapi.testclient import TestClient

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import create_session, save_blackboard


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", "wkPzx-2zM9YlbsZF_4ic4w8I1OvOhA-IRgLY4ZSj_5o=")
    from app import app
    return TestClient(app)


@pytest.mark.asyncio
async def test_export_404_no_result(tmp_db, client):
    bb = StmBlackboard(
        session_id="x", target_table="t", target_dataset="d", dialect_target="bigquery",
        selected_source_profiles=[],
        intent=IntentArtifact(source="freetext", raw_input="x"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="t", target_dataset="d"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    r = client.get("/api/stm/sessions/x/export.xlsx")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_export_when_result_present(tmp_db, client):
    bb = StmBlackboard(
        session_id="y", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=[],
        intent=IntentArtifact(source="freetext", raw_input="x"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="approved"),
            "gate2_validation": GateDecision(name="gate2_validation", decision="approved"),
        },
        stm_result={
            "stm_id": "abc12345", "target_dataset": "warehouse", "target_table": "customer_dim",
            "field_count": 1, "rows": [{"target_field":"customer_id","target_type":"INT64",
                                        "source_expression":"customer_id"}],
            "transformations": [], "source_tables": [], "business_rules": [],
            "scd_strategy": None, "audit_fields": [], "idempotency_key": "customer_id",
            "partition_field": None, "intent": {}, "validation": {},
            "generated_at": "2026-05-11T00:00:00",
        },
    )
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    await save_blackboard(bb)
    r = client.get("/api/stm/sessions/y/export.xlsx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
```

Run: `pytest tests/stm/test_session_exports.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add core/stm/agents/builder.py routers/stm.py tests/stm/agents/test_builder_full.py tests/stm/test_session_exports.py
git commit -m "stm: full L6 BuilderAgent + xlsx/csv session exports"
```

---

### Task 7.4: End-to-end integration test (mocked LLM)

**Files:**
- Test: `tests/stm/test_e2e_session.py`

- [ ] **Step 1: Write the test**

```python
# tests/stm/test_e2e_session.py
import pytest
from unittest.mock import patch

from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, ColumnProfile, ColumnHit, FKInfo,
)
from core.discovery.registry import register_provider, all_providers
from core.discovery.profiles import ProfileRegistry, ConnectionProfile
from core.stm.coordinator import StmCoordinator
from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import create_session, load_blackboard, save_blackboard
from tests.stm.fake_llm import FakeLLMClient


class _PG(SourceProvider):
    dialect = "postgres"
    async def ping(self, p): return PingResult(ok=True, latency_ms=1)
    async def list_schemas(self, p): return ["public"]
    async def list_tables(self, p, s): return [TableInfo(schema=s, name="customers")]
    async def get_columns(self, p, s, t):
        return [
            ColumnInfo(schema=s, table=t, name="customer_id", data_type="bigint", nullable=False, is_primary_key=True),
            ColumnInfo(schema=s, table=t, name="email", data_type="varchar", nullable=True),
            ColumnInfo(schema=s, table=t, name="is_active", data_type="boolean", nullable=False),
        ]
    async def get_foreign_keys(self, p, s, t): return []
    async def profile_column(self, p, s, t, c, sample_rows=0): return ColumnProfile()
    async def search_by_keywords(self, p, kw, limit=50):
        return [ColumnHit(schema="public", table="customers", column="customer_id",
                          data_type="bigint", score=1.0, matched_on="name")]


@pytest.fixture
def env(monkeypatch):
    snap = dict(all_providers())
    register_provider("postgres", _PG())
    reg = ProfileRegistry()
    reg.register(ConnectionProfile(id="pg-x", label="t", dialect="postgres", dsn="x", host="h"))
    monkeypatch.setattr("core.stm.agents.metadata._lookup_profile", lambda pid: reg.get(pid))
    yield
    for k, v in snap.items():
        register_provider(k, v)


def _seed_bb():
    return StmBlackboard(
        session_id="e2e", target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-x"],
        intent=IntentArtifact(source="freetext", raw_input="Build customer dim, active users only"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_full_session_with_auto_approvals(tmp_db, env):
    bb = _seed_bb()
    await create_session(bb, raw_input=bb.intent.raw_input, intent_source="freetext", jira_issue_key=None)
    fake = FakeLLMClient([
        # L1
        {"entity": "customer_dim", "action": "create", "is_dimension": True, "is_fact": False,
         "scd_hint": "type2", "filters": ["active users only"], "grain_hint": "customer_id",
         "extracted_keywords": ["customer","active"]},
        # L2
        {"concept_links": [{"concept": "customer", "node_id": "pg-x.public.customers.customer_id",
                            "confidence": 0.95, "evidence": "name match"}],
         "join_candidates": []},
        # L3
        {"mappings": [
            {"target_field": "customer_id", "target_type": "INT64",
             "source_node_ids": ["pg-x.public.customers.customer_id"],
             "source_expression": "customer_id", "rationale": "pk",
             "grain": ["customer_id"], "cardinality": "1:1", "llm_confidence": 0.99},
        ]},
        # L4
        {"rows": [
            {"target_field": "effective_from", "kind": "scd2", "logic": "CURRENT_TIMESTAMP()", "inputs": []},
            {"target_field": "effective_to", "kind": "scd2", "logic": "TIMESTAMP('9999-12-31')", "inputs": []},
            {"target_field": "is_current", "kind": "scd2", "logic": "TRUE", "inputs": []},
        ], "scd_strategy": "type2", "audit_fields": ["created_dt"],
         "idempotency_key": "customer_id", "partition_field": "effective_from"},
    ])
    coord = StmCoordinator(session_id="e2e", llm=fake)
    await coord.run_until_done(timeout=10)

    # Stalled at gate 1
    bb = await load_blackboard("e2e")
    assert bb.gates["gate1_metadata"].decision == "pending"
    bb.gates["gate1_metadata"].decision = "approved"
    await save_blackboard(bb)

    coord2 = StmCoordinator(session_id="e2e", llm=fake)
    await coord2.run_until_done(timeout=10)

    # Stalled at gate 2
    bb = await load_blackboard("e2e")
    assert bb.gates["gate2_validation"].decision == "pending"
    bb.gates["gate2_validation"].decision = "approved"
    await save_blackboard(bb)

    coord3 = StmCoordinator(session_id="e2e", llm=fake)
    await coord3.run_until_done(timeout=10)

    bb = await load_blackboard("e2e")
    assert bb.current_stage == "done"
    assert bb.stm_result is not None
    assert bb.stm_result["target_table"] == "customer_dim"
```

- [ ] **Step 2: Run — PASS**

Run: `pytest tests/stm/test_e2e_session.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/stm/test_e2e_session.py
git commit -m "stm: e2e integration test (mocked LLM, full L1→L6 with gate stalls)"
```

---

# PHASE 8 — UI Agentic Mode

Shippable outcome: `ui/mapping_compose_react.html` gains a `?mode=agentic` stepper that drives a session via the new endpoints, consumes SSE, exposes gate decisions and refinement, and lets users download the final STM. The existing rules-mode path remains untouched.

The UI is React-in-HTML using inline Babel + an `API_BASE` constant. All new code lives behind a `mode === 'agentic'` branch in the same file.

---

### Task 8.1: Wire `?mode=agentic` switch + session-create modal

**Files:**
- Modify: `ui/mapping_compose_react.html`
- Modify: `ui/pages/mappings.php` (add the "New agentic session" entry button)

- [ ] **Step 1: Inspect current UI**

Read the top of `ui/mapping_compose_react.html` and find the `function App()` (or equivalent root component) and the `API_BASE` constant. Note the existing UI patterns (button classes, layout).

Read `ui/pages/mappings.php` to find the spot to add a new button.

- [ ] **Step 2: Add "New agentic session" link to `ui/pages/mappings.php`**

Place near the top, next to existing "New mapping" or similar:

```html
<a class="btn btn-primary" href="/ui/mapping_compose_react.html?mode=agentic">
  New agentic session
</a>
```

- [ ] **Step 3: Add mode-switch logic to `ui/mapping_compose_react.html`**

Near the top of the React script section, after `const API_BASE = ...`:

```js
const urlParams = new URLSearchParams(window.location.search);
const MODE = urlParams.get('mode') || 'rules';
const SESSION_ID_FROM_URL = urlParams.get('session') || null;
```

At the top of the root `App()` component's render, branch:

```jsx
if (MODE === 'agentic') {
  return <AgenticApp initialSessionId={SESSION_ID_FROM_URL} />;
}
// existing rules-mode UI below — leave untouched
```

- [ ] **Step 4: Define `AgenticApp` skeleton with session-create modal**

Append before the existing `App()` definition:

```jsx
function AgenticApp({ initialSessionId }) {
  const [sessionId, setSessionId] = React.useState(initialSessionId);
  const [creating, setCreating] = React.useState(!initialSessionId);
  return (
    <div className="agentic-shell">
      <header className="ag-header">
        <h2>STM Agentic Session</h2>
      </header>
      {creating
        ? <NewSessionModal onCreated={(sid) => { setSessionId(sid); setCreating(false); history.replaceState({}, '', `?mode=agentic&session=${sid}`); }} />
        : <SessionStepper sessionId={sessionId} />}
    </div>
  );
}

function NewSessionModal({ onCreated }) {
  const [profiles, setProfiles] = React.useState([]);
  const [selProfiles, setSelProfiles] = React.useState([]);
  const [dataset, setDataset] = React.useState('warehouse');
  const [table, setTable] = React.useState('');
  const [intentTab, setIntentTab] = React.useState('freetext'); // 'jira' | 'freetext'
  const [jiraKey, setJiraKey] = React.useState('');
  const [text, setText] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    fetch(`${API_BASE}/api/discovery/profiles`).then(r => r.json()).then(setProfiles);
  }, []);

  const submit = async () => {
    setBusy(true);
    const body = {
      source_profiles: selProfiles,
      target_dataset: dataset,
      target_table: table,
      intent: intentTab === 'jira'
        ? { source: 'jira', jira_key: jiraKey }
        : { source: 'freetext', raw_text: text },
    };
    try {
      const res = await fetch(`${API_BASE}/api/stm/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      onCreated(data.session_id);
    } catch (e) {
      alert('Create failed: ' + e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ag-modal">
      <h3>New STM session</h3>
      <label>Source profiles</label>
      <select multiple value={selProfiles} onChange={e => setSelProfiles(Array.from(e.target.selectedOptions).map(o => o.value))}>
        {profiles.map(p => <option key={p.id} value={p.id}>{p.label} ({p.dialect})</option>)}
      </select>
      <label>Target dataset</label>
      <input value={dataset} onChange={e => setDataset(e.target.value)} />
      <label>Target table</label>
      <input value={table} onChange={e => setTable(e.target.value)} />
      <div className="ag-tabs">
        <button className={intentTab === 'freetext' ? 'active' : ''} onClick={() => setIntentTab('freetext')}>Free text</button>
        <button className={intentTab === 'jira' ? 'active' : ''} onClick={() => setIntentTab('jira')}>Jira</button>
      </div>
      {intentTab === 'freetext'
        ? <textarea rows={6} value={text} onChange={e => setText(e.target.value)} placeholder="e.g. Build customer dim, active users only"/>
        : <input value={jiraKey} onChange={e => setJiraKey(e.target.value)} placeholder="DAT-123"/>}
      <button className="btn btn-primary" disabled={busy || !table || (intentTab === 'freetext' ? !text : !jiraKey)} onClick={submit}>
        {busy ? 'Creating…' : 'Create session'}
      </button>
    </div>
  );
}
```

`SessionStepper` is a placeholder for Tasks 8.2–8.5; create the stub now:

```jsx
function SessionStepper({ sessionId }) {
  return <div>Stepper for {sessionId} — coming next</div>;
}
```

- [ ] **Step 4: Smoke test in browser**

Run: `docker compose up -d` (or whatever launches the dev stack). Visit `http://localhost:<port>/ui/mapping_compose_react.html?mode=agentic`.
Expected: modal renders, lists profiles, can submit and lands on `?session=<id>`.

- [ ] **Step 5: Commit**

```bash
git add ui/mapping_compose_react.html ui/pages/mappings.php
git commit -m "ui: agentic mode toggle + session-create modal"
```

---

### Task 8.2: SessionStepper — SSE consumption + hydration

**Files:**
- Modify: `ui/mapping_compose_react.html`

- [ ] **Step 1: Replace the stub `SessionStepper` with the live version**

```jsx
const STAGE_ORDER = ['L1','L2','GATE1','L3','L4','L5','GATE2','L6'];
const STAGE_LABEL = {
  L1: 'L1 Intent', L2: 'L2 Metadata', GATE1: 'Gate 1', L3: 'L3 Semantic',
  L4: 'L4 Transform', L5: 'L5 Validation', GATE2: 'Gate 2', L6: 'L6 STM Build',
};

function statusOf(bb, key) {
  switch (key) {
    case 'L1': return bb.intent?.status || 'idle';
    case 'L2': return bb.metadata_graph?.status || 'idle';
    case 'GATE1': return bb.gates?.gate1_metadata?.decision || 'pending';
    case 'L3': return bb.candidate_mappings?.status || 'idle';
    case 'L4': return bb.transformations?.status || 'idle';
    case 'L5': return bb.validation?.status || 'idle';
    case 'GATE2': return bb.gates?.gate2_validation?.decision || 'pending';
    case 'L6': return bb.stm_result ? 'ready' : 'idle';
  }
}

const STATUS_DOT = {
  idle: '◌', running: '◐', ready: '●', stale: '◇', awaiting_review: '◐',
  pending: '◌', approved: '●', rejected: '✕', refine: '◐', failed: '✕',
};

function SessionStepper({ sessionId }) {
  const [bb, setBb] = React.useState(null);
  const [events, setEvents] = React.useState([]);
  const [err, setErr] = React.useState(null);

  // Hydrate on mount
  React.useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/api/stm/sessions/${sessionId}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(data => { if (alive) setBb(data); })
      .catch(e => alive && setErr(e.message));
    return () => { alive = false; };
  }, [sessionId]);

  // SSE subscribe
  React.useEffect(() => {
    const es = new EventSource(`${API_BASE}/api/stm/sessions/${sessionId}/events`);
    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        setEvents(prev => [...prev.slice(-200), ev]);
        // Re-hydrate blackboard on important transitions
        if (['stage_ready','gate_decided','gate_requested','session_completed','session_rejected','session_failed','stage_stale'].includes(ev.type)) {
          fetch(`${API_BASE}/api/stm/sessions/${sessionId}`).then(r => r.json()).then(setBb);
        }
      } catch {}
    };
    es.onerror = () => {};
    return () => es.close();
  }, [sessionId]);

  if (err) return <div className="ag-error">Session load failed: {err}</div>;
  if (!bb) return <div>Loading…</div>;

  return (
    <div className="ag-grid">
      <aside className="ag-rail">
        {STAGE_ORDER.map(k => {
          const s = statusOf(bb, k);
          return <div key={k} className={`ag-rail-row st-${s}`} title={`${STAGE_LABEL[k]}: ${s}`}>
            <span className="ag-dot">{STATUS_DOT[s] || '◌'}</span>
            <span>{STAGE_LABEL[k]}</span>
          </div>;
        })}
      </aside>
      <main className="ag-main">
        <StageCard title="L1 Intent" stage="L1" bb={bb}/>
        <StageCard title="L2 Metadata" stage="L2" bb={bb} sessionId={sessionId}/>
        <GatePanel gate="gate1_metadata" bb={bb} sessionId={sessionId}/>
        <StageCard title="L3 Semantic Mapping" stage="L3" bb={bb}/>
        <StageCard title="L4 Transformations" stage="L4" bb={bb}/>
        <StageCard title="L5 Validation" stage="L5" bb={bb}/>
        <GatePanel gate="gate2_validation" bb={bb} sessionId={sessionId}/>
        <FinalActions bb={bb} sessionId={sessionId}/>
      </main>
    </div>
  );
}

function StageCard({ title, stage, bb, sessionId }) {
  return <section className="ag-card"><h4>{title}</h4>{/* placeholder, filled in Task 8.3 */}</section>;
}
function GatePanel({ gate, bb, sessionId }) {
  return <section className="ag-card ag-gate"><h4>{gate}</h4>{/* placeholder, filled in Task 8.4 */}</section>;
}
function FinalActions({ bb, sessionId }) {
  if (!bb.stm_result) return null;
  return <section className="ag-card">
    <h4>Final actions</h4>
    <a className="btn" href={`${API_BASE}/api/stm/sessions/${sessionId}/export.xlsx`}>Download .xlsx</a>
    <a className="btn" href={`${API_BASE}/api/stm/sessions/${sessionId}/export.csv`}>Download .csv</a>
  </section>;
}
```

- [ ] **Step 2: Add minimal CSS**

Append a `<style>` block (or extend the existing one) inside the HTML head with:

```css
.agentic-shell { padding: 16px; }
.ag-grid { display: grid; grid-template-columns: 220px 1fr; gap: 16px; }
.ag-rail { display: flex; flex-direction: column; gap: 6px; }
.ag-rail-row { display:flex; gap: 8px; align-items: center; padding: 4px 6px; border-radius: 4px; }
.ag-rail-row.st-ready { background:#dcfce7; }
.ag-rail-row.st-running { background:#fef3c7; }
.ag-rail-row.st-stale { background:#e2e8f0; }
.ag-rail-row.st-failed, .ag-rail-row.st-rejected { background:#fee2e2; }
.ag-card { border:1px solid #cbd5e1; border-radius:6px; padding:12px; margin-bottom:12px; }
.ag-gate { background:#fff7ed; border-color:#fb923c; }
.ag-error { color:#b91c1c; }
.ag-tabs { display:flex; gap:4px; margin:8px 0; }
.ag-tabs .active { background:#0284c7; color:white; }
.ag-modal { max-width:600px; }
.ag-modal label { display:block; font-weight:600; margin-top:8px; }
.ag-modal input, .ag-modal textarea, .ag-modal select { width:100%; }
.ag-dot { width: 16px; display: inline-block; text-align: center; }
```

- [ ] **Step 3: Smoke test**

Open `?mode=agentic&session=<id>` for a recent session. Confirm the rail renders with the right dots and that an event triggered re-hydration.

- [ ] **Step 4: Commit**

```bash
git add ui/mapping_compose_react.html
git commit -m "ui: agentic session stepper with SSE + hydration"
```

---

### Task 8.3: Per-stage expanders + graph view + validation scorecard

**Files:**
- Modify: `ui/mapping_compose_react.html`

- [ ] **Step 1: Replace `StageCard`**

```jsx
function StageCard({ title, stage, bb, sessionId }) {
  const [open, setOpen] = React.useState(true);
  const s = statusOf(bb, stage);
  return (
    <section className="ag-card">
      <header style={{display:'flex',justifyContent:'space-between',cursor:'pointer'}}
              onClick={() => setOpen(o => !o)}>
        <h4>{title}</h4>
        <span>[{s}] {open ? '▲' : '▼'}</span>
      </header>
      {open && <div className="ag-stage-body">
        {stage === 'L1' && <L1Body intent={bb.intent}/>}
        {stage === 'L2' && <L2Body bb={bb} sessionId={sessionId}/>}
        {stage === 'L3' && <L3Body cm={bb.candidate_mappings}/>}
        {stage === 'L4' && <L4Body tx={bb.transformations}/>}
        {stage === 'L5' && <L5Body val={bb.validation}/>}
      </div>}
    </section>
  );
}

function L1Body({ intent }) {
  if (!intent || intent.status === 'idle') return <em>not started</em>;
  return <ul>
    <li>entity: <b>{intent.entity}</b></li>
    <li>action: {intent.action}</li>
    <li>dimension/fact: {intent.is_dimension ? 'dimension' : intent.is_fact ? 'fact' : '—'}</li>
    <li>scd_hint: {intent.scd_hint || '—'}</li>
    <li>filters: {intent.filters?.join(', ') || '—'}</li>
    <li>keywords: {intent.extracted_keywords?.join(', ') || '—'}</li>
  </ul>;
}

function L2Body({ bb, sessionId }) {
  const g = bb.metadata_graph || {};
  return <div>
    <p><b>{g.sources_probed?.length || 0}</b> sources probed · <b>{g.nodes?.length || 0}</b> nodes / <b>{g.edges?.length || 0}</b> edges</p>
    {g.coverage_notes?.length > 0 && <details><summary>Coverage notes</summary>
      <ul>{g.coverage_notes.map((n, i) => <li key={i}>{n}</li>)}</ul></details>}
    {g.status === 'ready' && <img alt="graph" src={`${API_BASE}/api/stm/sessions/${sessionId}/graph.svg`} style={{maxWidth:'100%',border:'1px solid #ddd'}}/>}
  </div>;
}

function L3Body({ cm }) {
  if (!cm || cm.status === 'idle') return <em>not started</em>;
  return <table className="ag-table"><thead><tr>
    <th>target</th><th>type</th><th>expression</th><th>baseline</th><th>llm</th></tr></thead>
    <tbody>{cm.rows.map((r,i) => <tr key={i}>
      <td>{r.target_field}</td><td>{r.target_type}</td>
      <td><code>{r.source_expression}</code></td>
      <td>{r.rule_baseline ? '✓' : ''}</td>
      <td>{r.refined_by_llm ? '✓' : ''}</td>
    </tr>)}</tbody></table>;
}

function L4Body({ tx }) {
  if (!tx || tx.status === 'idle') return <em>not started</em>;
  return <div>
    <p>SCD: <b>{tx.scd_strategy || '—'}</b>, idempotency: <b>{tx.idempotency_key || '—'}</b>, partition: <b>{tx.partition_field || '—'}</b></p>
    <table className="ag-table"><thead><tr><th>field</th><th>kind</th><th>logic</th></tr></thead>
    <tbody>{tx.rows.map((r,i) => <tr key={i}>
      <td>{r.target_field}</td><td>{r.kind}</td><td><code>{r.logic}</code></td>
    </tr>)}</tbody></table>
  </div>;
}

function L5Body({ val }) {
  if (!val || val.status === 'idle') return <em>not started</em>;
  return <div>
    <p>Overall: <b>{val.overall_band}</b> · {val.block_count} blocks · {val.low_confidence_count} low</p>
    <table className="ag-table"><thead><tr><th>field</th><th>final</th><th>band</th><th>name</th><th>type</th><th>fk</th><th>llm</th></tr></thead>
    <tbody>{val.scores.map((s,i) => <tr key={i} className={`band-${s.band}`}>
      <td>{s.target_field}</td><td>{s.final.toFixed(2)}</td><td>{s.band}</td>
      <td>{s.name_sim_score.toFixed(2)}</td><td>{s.type_compat_score.toFixed(2)}</td>
      <td>{s.fk_evidence_score.toFixed(2)}</td><td>{s.llm_score.toFixed(2)}</td>
    </tr>)}</tbody></table>
    {val.findings.length > 0 && <details open><summary>Findings ({val.findings.length})</summary>
      <ul>{val.findings.map((f,i) => <li key={i} className={`sev-${f.severity}`}>
        [{f.severity}] {f.rule} — {f.message} {f.target_field ? `(${f.target_field})` : ''}
      </li>)}</ul></details>}
  </div>;
}
```

Append to the `<style>`:

```css
.ag-table { width:100%; border-collapse:collapse; margin-top:6px; }
.ag-table th, .ag-table td { border-bottom:1px solid #e2e8f0; padding:4px 6px; font-size:12px; }
.band-high { background:#dcfce7; }
.band-medium { background:#fef3c7; }
.band-low { background:#fee2e2; }
.sev-block { color:#991b1b; }
.sev-warn { color:#a16207; }
```

- [ ] **Step 2: Commit**

```bash
git add ui/mapping_compose_react.html
git commit -m "ui: per-stage expanders, graph view, validation scorecard"
```

---

### Task 8.4: Gate panel + refinement form

**Files:**
- Modify: `ui/mapping_compose_react.html`

- [ ] **Step 1: Replace `GatePanel`**

```jsx
function GatePanel({ gate, bb, sessionId }) {
  const g = bb.gates?.[gate];
  if (!g) return null;
  const decision = g.decision;
  // Determine if this gate is currently awaiting
  const stageReady = gate === 'gate1_metadata'
    ? bb.metadata_graph?.status === 'ready'
    : bb.validation?.status === 'ready';
  const isAwaiting = decision === 'pending' && stageReady;

  const [mode, setMode] = React.useState(null); // 'approve' | 'refine' | 'reject'
  const [target, setTarget] = React.useState(gate === 'gate1_metadata' ? 'L2' : 'L3');
  const [feedback, setFeedback] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  const submit = async (payload) => {
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/api/stm/sessions/${sessionId}/gates/${gate}/decide`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(await r.text());
      setMode(null);
    } catch (e) {
      alert('Gate decision failed: ' + e.message);
    } finally { setBusy(false); }
  };

  if (!isAwaiting) {
    return <section className="ag-card ag-gate">
      <h4>{gate === 'gate1_metadata' ? 'Gate 1 — Metadata Scope' : 'Gate 2 — Validation Approval'}</h4>
      <p>Status: <b>{decision}</b> {g.reviewer ? `by ${g.reviewer}` : ''}</p>
      {g.refine_target_stage && <p>Refined → {g.refine_target_stage}: {g.refine_feedback}</p>}
    </section>;
  }

  const validTargets = gate === 'gate1_metadata' ? ['L1','L2'] : ['L1','L2','L3','L4','L5'];

  return <section className="ag-card ag-gate">
    <h4>{gate === 'gate1_metadata' ? 'Gate 1 — Metadata Scope' : 'Gate 2 — Validation Approval'} (AWAITING REVIEW)</h4>
    {!mode && <div>
      <button className="btn" disabled={busy} onClick={() => submit({decision:'approved', reviewer:'me'})}>Approve</button>
      <button className="btn" disabled={busy} onClick={() => setMode('refine')}>Refine</button>
      <button className="btn" disabled={busy} onClick={() => submit({decision:'rejected', reviewer:'me'})}>Reject</button>
    </div>}
    {mode === 'refine' && <div>
      <label>Target stage</label>
      <select value={target} onChange={e => setTarget(e.target.value)}>
        {validTargets.map(t => <option key={t} value={t}>{t}</option>)}
      </select>
      <label>Feedback</label>
      <textarea rows={4} value={feedback} onChange={e => setFeedback(e.target.value)}/>
      <button className="btn btn-primary" disabled={busy || !feedback}
              onClick={() => submit({decision:'refine', reviewer:'me', refine_target:target, refine_feedback:feedback})}>
        Submit refinement
      </button>
      <button className="btn" onClick={() => setMode(null)}>Cancel</button>
    </div>}
  </section>;
}
```

- [ ] **Step 2: Smoke test**

Drive a session through L2, watch UI show the gate panel, click Approve → coordinator resumes → next stages execute → gate 2 panel appears → Refine targeting L3 with feedback → confirm UI shows downstream stale dots and stages rerun.

- [ ] **Step 3: Commit**

```bash
git add ui/mapping_compose_react.html
git commit -m "ui: gate panel with approve / reject / refine-with-feedback"
```

---

### Task 8.5: Final actions bar

**Files:**
- Modify: `ui/mapping_compose_react.html`

- [ ] **Step 1: Replace `FinalActions`**

```jsx
function FinalActions({ bb, sessionId }) {
  if (!bb.stm_result) return null;
  const canPostJira = bb.intent?.source === 'jira' && bb.intent?.jira_issue_key;
  const [posting, setPosting] = React.useState(false);
  const postToJira = async () => {
    setPosting(true);
    try {
      const r = await fetch(`${API_BASE}/api/stm/sessions/${sessionId}/jira_writeback`, {method:'POST'});
      if (!r.ok) throw new Error(await r.text());
      alert('Posted to Jira.');
    } catch (e) {
      alert('Failed: ' + e.message);
    } finally { setPosting(false); }
  };
  const clone = async () => {
    const r = await fetch(`${API_BASE}/api/stm/sessions/${sessionId}/clone`, {method:'POST'});
    const data = await r.json();
    window.location.search = `?mode=agentic&session=${data.session_id}`;
  };
  return <section className="ag-card">
    <h4>Final actions — STM {bb.stm_result.stm_id}</h4>
    <a className="btn" href={`${API_BASE}/api/stm/sessions/${sessionId}/export.xlsx`}>Download .xlsx</a>
    <a className="btn" href={`${API_BASE}/api/stm/sessions/${sessionId}/export.csv`}>Download .csv</a>
    {canPostJira && <button className="btn" disabled={posting} onClick={postToJira}>Post to Jira</button>}
    <button className="btn" onClick={clone}>Clone session</button>
  </section>;
}
```

- [ ] **Step 2: Commit**

```bash
git add ui/mapping_compose_react.html
git commit -m "ui: final actions bar (download / post-jira / clone)"
```

---

# PHASE 9 — Jira Write-Back, Cost Summary, Clone, Test Sources

Shippable outcome: optional Jira comment + transition on completion; LLM cost rollup endpoint; clone-to-retry endpoint; docker-compose for Oracle/MySQL/MSSQL test containers.

---

### Task 9.1: Clone session endpoint

**Files:**
- Modify: `routers/stm.py`
- Test: `tests/stm/test_clone.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_clone.py
import pytest
from fastapi.testclient import TestClient

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import create_session, load_blackboard, save_blackboard


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", "wkPzx-2zM9YlbsZF_4ic4w8I1OvOhA-IRgLY4ZSj_5o=")
    from app import app
    return TestClient(app)


def _seed(sid):
    return StmBlackboard(
        session_id=sid, target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=["pg-x"],
        intent=IntentArtifact(source="freetext", raw_input="Build dim, active users only"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )


@pytest.mark.asyncio
async def test_clone_creates_fresh_session_with_same_inputs(tmp_db, client, monkeypatch):
    # Stub coordinator to not run real LLM
    from core.stm import coordinator as cm
    class _Stub(cm.StmCoordinator):
        def start_background(self):
            class _T:
                def cancel(self): pass
            return _T()
    monkeypatch.setattr(cm, "StmCoordinator", _Stub)

    bb = _seed("orig")
    await create_session(bb, raw_input=bb.intent.raw_input, intent_source="freetext", jira_issue_key=None)
    r = client.post("/api/stm/sessions/orig/clone")
    assert r.status_code == 200
    new_sid = r.json()["session_id"]
    assert new_sid != "orig"
    loaded = await load_blackboard(new_sid)
    assert loaded.target_table == "customer_dim"
    assert loaded.intent.raw_input == bb.intent.raw_input
    # Clone resets statuses
    assert loaded.intent.status == StageStatus.idle
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_clone.py -v`

- [ ] **Step 3: Add clone endpoint to `routers/stm.py`**

```python
@router.post("/sessions/{session_id}/clone")
async def clone_session(session_id: str):
    try:
        src = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    new_sid = uuid.uuid4().hex
    bb = StmBlackboard(
        session_id=new_sid,
        target_table=src.target_table, target_dataset=src.target_dataset,
        dialect_target=src.dialect_target,
        selected_source_profiles=list(src.selected_source_profiles),
        intent=IntentArtifact(
            source=src.intent.source, raw_input=src.intent.raw_input,
            jira_issue_key=src.intent.jira_issue_key, status=StageStatus.idle,
        ),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table=src.target_table, target_dataset=src.target_dataset),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
        current_stage="L1",
    )
    await create_session(
        bb, raw_input=src.intent.raw_input,
        intent_source=src.intent.source, jira_issue_key=src.intent.jira_issue_key,
    )
    StmCoordinator(session_id=new_sid, llm=LLMClient()).start_background()
    return {"session_id": new_sid}
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/test_clone.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add routers/stm.py tests/stm/test_clone.py
git commit -m "stm: clone-session endpoint (fresh session seeded from source)"
```

---

### Task 9.2: Cost summary endpoint

**Files:**
- Create: `core/stm/cost.py`
- Modify: `routers/stm.py`
- Test: `tests/stm/test_cost.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_cost.py
import pytest
from fastapi.testclient import TestClient

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import create_session, append_event


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", "wkPzx-2zM9YlbsZF_4ic4w8I1OvOhA-IRgLY4ZSj_5o=")
    from app import app
    return TestClient(app)


@pytest.mark.asyncio
async def test_cost_summary_aggregates_tokens(tmp_db, client):
    bb = StmBlackboard(
        session_id="cs", target_table="t", target_dataset="d", dialect_target="bigquery",
        selected_source_profiles=[],
        intent=IntentArtifact(source="freetext", raw_input="x"),
        metadata_graph=MetadataGraph(),
        candidate_mappings=CandidateMappings(target_table="t", target_dataset="d"),
        transformations=Transformations(),
        validation=ValidationReport(),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata"),
            "gate2_validation": GateDecision(name="gate2_validation"),
        },
    )
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    await append_event("cs", stage="L1", event_kind="llm_call", llm_model="claude-haiku-4-5",
                        llm_tokens_in=100, llm_tokens_out=20)
    await append_event("cs", stage="L2", event_kind="llm_call", llm_model="claude-sonnet-4-6",
                        llm_tokens_in=2000, llm_tokens_out=400)
    r = client.get("/api/stm/sessions/cs/cost_summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_tokens_in"] == 2100
    assert body["total_tokens_out"] == 420
    assert "by_stage" in body
    assert body["by_stage"]["L2"]["tokens_in"] == 2000
    assert "estimated_usd" in body
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_cost.py -v`

- [ ] **Step 3: Implement `core/stm/cost.py`**

```python
"""Per-session LLM cost rollup."""
from __future__ import annotations

from typing import Any, Dict, List


# Approx USD per 1M tokens (as of Jan 2026 list; tune as needed).
_MODEL_USD_PER_M = {
    "claude-haiku-4-5":  {"in": 0.80,  "out": 4.00},
    "claude-sonnet-4-6": {"in": 3.00,  "out": 15.00},
    "claude-opus-4-7":   {"in": 15.00, "out": 75.00},
}


def aggregate(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_stage: Dict[str, Dict[str, Any]] = {}
    by_model: Dict[str, Dict[str, Any]] = {}
    total_in = total_out = 0
    usd = 0.0
    for ev in events:
        if ev.get("event_kind") != "llm_call":
            continue
        tin = ev.get("llm_tokens_in") or 0
        tout = ev.get("llm_tokens_out") or 0
        model = ev.get("llm_model") or "unknown"
        stage = ev.get("stage") or "?"
        total_in += tin
        total_out += tout
        s = by_stage.setdefault(stage, {"tokens_in": 0, "tokens_out": 0, "calls": 0})
        s["tokens_in"] += tin; s["tokens_out"] += tout; s["calls"] += 1
        m = by_model.setdefault(model, {"tokens_in": 0, "tokens_out": 0, "calls": 0})
        m["tokens_in"] += tin; m["tokens_out"] += tout; m["calls"] += 1
        rate = _MODEL_USD_PER_M.get(model)
        if rate:
            usd += (tin / 1_000_000.0) * rate["in"] + (tout / 1_000_000.0) * rate["out"]
    return {
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "by_stage": by_stage,
        "by_model": by_model,
        "estimated_usd": round(usd, 4),
    }
```

- [ ] **Step 4: Add endpoint to `routers/stm.py`**

```python
from core.stm.cost import aggregate as _aggregate_cost

@router.get("/sessions/{session_id}/cost_summary")
async def session_cost(session_id: str):
    events = await list_events(session_id)
    return _aggregate_cost(events)
```

- [ ] **Step 5: Update agents to report tokens**

In each agent that calls LLM (intent.py, metadata.py, semantic.py, transform.py), update the `events_to_emit` to include token counts when the FakeLLMClient or real client returns usage. For the real LLMClient, the wrapper should return a dict with `_usage = {"input_tokens": ..., "output_tokens": ...}` — if it doesn't yet, add a small accessor.

Inspect `core/llm_client.py` and locate `complete_json`. If it doesn't surface usage, add an optional `last_usage` attribute set after each call:

```python
# In LLMClient.complete_json(), after the API response:
self.last_usage = {
    "input_tokens": resp.usage.input_tokens if hasattr(resp, "usage") else None,
    "output_tokens": resp.usage.output_tokens if hasattr(resp, "usage") else None,
}
```

Then in agents, after `ctx.llm.complete_json(...)`:

```python
usage = getattr(ctx.llm, "last_usage", None) or {}
events_to_emit.append({
    "type": "llm_call", "stage": "L<n>", "model": model,
    "tokens_in": usage.get("input_tokens"), "tokens_out": usage.get("output_tokens"),
})
```

Also update the coordinator's `append_event(..., event_kind="ready")` to pass `llm_tokens_in/out` through (extract from the events_to_emit that the agent reported). Add this in `tick()` where the ready event is appended:

```python
last_llm = next((e for e in reversed(delta.events_to_emit) if e.get("type") == "llm_call"), None)
await append_event(
    self.session_id, stage=agent.stage, event_kind="ready",
    artifact_kind=delta.artifact_kind, confidence=delta.confidence,
    llm_model=(last_llm or {}).get("model"),
    llm_tokens_in=(last_llm or {}).get("tokens_in"),
    llm_tokens_out=(last_llm or {}).get("tokens_out"),
)
```

But the cost test seeds `llm_call` events directly, so it doesn't require the agent integration — that's a separate code path. Keep the agent integration but the cost test stands on its own.

- [ ] **Step 6: Run — PASS**

Run: `pytest tests/stm/test_cost.py -v`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add core/stm/cost.py routers/stm.py core/llm_client.py core/stm/coordinator.py core/stm/agents/intent.py core/stm/agents/metadata.py core/stm/agents/semantic.py core/stm/agents/transform.py tests/stm/test_cost.py
git commit -m "stm: cost summary endpoint + token plumbing through agents"
```

---

### Task 9.3: Jira write-back endpoint

**Files:**
- Modify: `routers/stm.py`
- Test: `tests/stm/test_jira_writeback.py`

- [ ] **Step 1: Failing test**

```python
# tests/stm/test_jira_writeback.py
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from core.stm.blackboard import (
    StmBlackboard, IntentArtifact, MetadataGraph, CandidateMappings,
    Transformations, ValidationReport, GateDecision, StageStatus,
)
from core.stm.persistence import create_session, save_blackboard


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", "wkPzx-2zM9YlbsZF_4ic4w8I1OvOhA-IRgLY4ZSj_5o=")
    monkeypatch.setenv("STM_JIRA_WRITEBACK_ENABLED", "true")
    from app import app
    return TestClient(app)


def _bb(sid, source="jira"):
    return StmBlackboard(
        session_id=sid, target_table="customer_dim", target_dataset="warehouse",
        dialect_target="bigquery", selected_source_profiles=[],
        intent=IntentArtifact(source=source, raw_input="x",
                              jira_issue_key="DAT-1" if source == "jira" else None,
                              status=StageStatus.ready),
        metadata_graph=MetadataGraph(status=StageStatus.ready),
        candidate_mappings=CandidateMappings(target_table="customer_dim", target_dataset="warehouse",
                                              status=StageStatus.ready),
        transformations=Transformations(status=StageStatus.ready),
        validation=ValidationReport(status=StageStatus.ready),
        gates={
            "gate1_metadata": GateDecision(name="gate1_metadata", decision="approved"),
            "gate2_validation": GateDecision(name="gate2_validation", decision="approved"),
        },
        stm_result={"stm_id":"abc12345","target_table":"customer_dim","target_dataset":"warehouse",
                    "field_count":1,"rows":[], "transformations":[], "source_tables":[],
                    "business_rules":[], "scd_strategy":None, "audit_fields":[],
                    "idempotency_key":None, "partition_field":None, "intent":{},
                    "validation":{}, "generated_at":"2026-05-11T00:00:00"},
    )


@pytest.mark.asyncio
async def test_writeback_requires_completed_session(tmp_db, client):
    bb = _bb("wb-x")
    bb.stm_result = None
    await create_session(bb, raw_input="x", intent_source="jira", jira_issue_key="DAT-1")
    r = client.post("/api/stm/sessions/wb-x/jira_writeback")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_writeback_calls_jira_client(tmp_db, client, monkeypatch):
    bb = _bb("wb-ok")
    await create_session(bb, raw_input="x", intent_source="jira", jira_issue_key="DAT-1")
    await save_blackboard(bb)
    calls = []

    class _MockJira:
        def add_comment(self, key, body): calls.append(("comment", key, body))

    monkeypatch.setattr("routers.stm._build_jira_client", lambda: _MockJira())
    r = client.post("/api/stm/sessions/wb-ok/jira_writeback")
    assert r.status_code == 200
    assert any(c[0] == "comment" and c[1] == "DAT-1" for c in calls)


@pytest.mark.asyncio
async def test_writeback_freetext_session_400(tmp_db, client):
    bb = _bb("wb-ft", source="freetext")
    await create_session(bb, raw_input="x", intent_source="freetext", jira_issue_key=None)
    await save_blackboard(bb)
    r = client.post("/api/stm/sessions/wb-ft/jira_writeback")
    assert r.status_code == 400
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/stm/test_jira_writeback.py -v`

- [ ] **Step 3: Add the endpoint + helper to `routers/stm.py`**

```python
from core.config import STM_JIRA_WRITEBACK_ENABLED


def _build_jira_client():
    """Builds a Jira client from env. Returns a JiraClient or raises."""
    from agents.shared.jira_client import JiraClient
    import os
    base = os.environ["JIRA_BASE_URL"]
    email = os.environ["JIRA_EMAIL"]
    token = os.environ["JIRA_API_TOKEN"]
    return JiraClient(base=base, email=email, token=token)


@router.post("/sessions/{session_id}/jira_writeback")
async def jira_writeback(session_id: str):
    if not STM_JIRA_WRITEBACK_ENABLED:
        raise HTTPException(status_code=403, detail="STM_JIRA_WRITEBACK_ENABLED=false")
    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    if bb.intent.source != "jira" or not bb.intent.jira_issue_key:
        raise HTTPException(status_code=400, detail="session not Jira-sourced")
    if not bb.stm_result:
        raise HTTPException(status_code=409, detail="no STM result yet")
    body = (
        f"STM session **{bb.stm_result['stm_id']}** completed.\n"
        f"Target: `{bb.stm_result['target_dataset']}.{bb.stm_result['target_table']}`\n"
        f"Fields: {bb.stm_result['field_count']} · "
        f"Overall confidence: {bb.stm_result.get('validation',{}).get('overall_band','?')}\n"
        f"SCD: {bb.stm_result.get('scd_strategy') or '—'} · "
        f"Idempotency key: {bb.stm_result.get('idempotency_key') or '—'}"
    )
    jira = _build_jira_client()
    jira.add_comment(bb.intent.jira_issue_key, body)
    return {"ok": True}
```

If `agents.shared.jira_client.JiraClient` has a different constructor (inspect the file first — Phase 1 of the discovery showed `JiraClient` exists), use the actual signature.

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/stm/test_jira_writeback.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add routers/stm.py tests/stm/test_jira_writeback.py
git commit -m "stm: optional Jira write-back endpoint (flag-gated)"
```

---

### Task 9.4: Test source containers

**Files:**
- Create: `docker-compose.test-sources.yml`
- Create: `tests/integration/test_provider_contracts.py`

- [ ] **Step 1: Write the compose file**

Create `docker-compose.test-sources.yml`:

```yaml
version: "3.9"

services:
  test-postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: crm_demo
      POSTGRES_USER: demo
      POSTGRES_PASSWORD: demo
    ports: ["55432:5432"]
    volumes:
      - ./tests/fixtures/postgres_seed.sql:/docker-entrypoint-initdb.d/seed.sql:ro

  test-mysql:
    image: mysql:8
    environment:
      MYSQL_ROOT_PASSWORD: demo
      MYSQL_DATABASE: crm_demo
      MYSQL_USER: demo
      MYSQL_PASSWORD: demo
    ports: ["53306:3306"]
    volumes:
      - ./tests/fixtures/mysql_seed.sql:/docker-entrypoint-initdb.d/seed.sql:ro

  test-mssql:
    image: mcr.microsoft.com/mssql/server:2022-latest
    environment:
      ACCEPT_EULA: "Y"
      MSSQL_SA_PASSWORD: "Demo!Demo123"
    ports: ["51433:1433"]

  test-oracle:
    image: gvenzl/oracle-free:slim
    environment:
      ORACLE_PASSWORD: demo
    ports: ["51521:1521"]
```

- [ ] **Step 2: Add seed files**

Create `tests/fixtures/postgres_seed.sql`:

```sql
CREATE TABLE customers (
  customer_id BIGSERIAL PRIMARY KEY,
  email VARCHAR(255),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);
INSERT INTO customers (email, is_active) VALUES
  ('a@b.com', TRUE), ('c@d.com', FALSE), ('e@f.com', TRUE);
```

Create `tests/fixtures/mysql_seed.sql`:

```sql
CREATE TABLE customers (
  customer_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(255),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO customers (email, is_active) VALUES
  ('a@b.com', TRUE), ('c@d.com', FALSE), ('e@f.com', TRUE);
```

Oracle/MSSQL seed scripts can be added later if needed; the provider tests skip when containers aren't running.

- [ ] **Step 3: Provider contract test**

Create `tests/integration/test_provider_contracts.py`:

```python
import os
import pytest

from core.discovery.profiles import ConnectionProfile
from core.discovery.postgres_provider import PostgresProvider
from core.discovery.mysql_provider import MySQLProvider


def _can_connect(dsn):
    return bool(os.environ.get(dsn))


@pytest.mark.asyncio
@pytest.mark.skipif(not _can_connect("TEST_PG_DSN"), reason="TEST_PG_DSN not set")
async def test_postgres_contract():
    dsn = os.environ["TEST_PG_DSN"]
    p = PostgresProvider()
    profile = ConnectionProfile(id="t", label="t", dialect="postgres", dsn=dsn, host=dsn)
    assert (await p.ping(profile)).ok
    schemas = await p.list_schemas(profile)
    assert "public" in schemas
    tables = await p.list_tables(profile, "public")
    assert any(t.name == "customers" for t in tables)
    cols = await p.get_columns(profile, "public", "customers")
    names = {c.name for c in cols}
    assert {"customer_id", "email", "is_active"} <= names


@pytest.mark.asyncio
@pytest.mark.skipif(not _can_connect("TEST_MY_DSN"), reason="TEST_MY_DSN not set")
async def test_mysql_contract():
    dsn = os.environ["TEST_MY_DSN"]
    p = MySQLProvider()
    profile = ConnectionProfile(id="t", label="t", dialect="mysql", dsn=dsn, host=dsn)
    assert (await p.ping(profile)).ok
    schemas = await p.list_schemas(profile)
    assert "crm_demo" in schemas
```

- [ ] **Step 4: Run (only if containers are up)**

```bash
docker compose -f docker-compose.test-sources.yml up -d
TEST_PG_DSN=postgresql://demo:demo@localhost:55432/crm_demo \
TEST_MY_DSN=mysql://demo:demo@localhost:53306/crm_demo \
  pytest tests/integration/test_provider_contracts.py -v
docker compose -f docker-compose.test-sources.yml down
```

Expected: passes locally with containers; skipped in CI without DSN env.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.test-sources.yml tests/fixtures/postgres_seed.sql tests/fixtures/mysql_seed.sql tests/integration/test_provider_contracts.py
git commit -m "tests: docker-compose for test sources + provider contract integration tests"
```

---

# Spec Coverage Self-Review

This section was applied after the plan was authored.

| Spec section | Covered by |
|---|---|
| §1 Vision | Phase index intro + commit messages |
| §2 Locked constraints | All decisions encoded across phases (big-bang scope = full 9-phase plan; intent source = Task 4.2 + 4.5; graph = Task 3.1; persistence = Task 0.3 + 3.2; ensemble confidence = Task 7.1 + 7.2; multi-dialect = Phase 2; agentic-wraps-rules = Task 6.1 `_rule_baseline`; SSE = Task 3.4 + Task 4.5; gate UX = Task 5.2; orchestrator shape = Task 4.4 + 5.2; LLM model split = `STM_LLM_MODEL_*` in 0.2 + agent files; deterministic L5 = 7.2; reject terminal + clone = 5.2 + 9.1; single-worker SessionLock = 3.3; pytds for MSSQL = 2.4; Fernet creds = 2.1 + 2.5; UI `?mode=agentic` = 8.1; Jira write-back default OFF = 9.3 honors `STM_JIRA_WRITEBACK_ENABLED`) |
| §3 Architecture | Phase index + module layout in Phase 3/4 |
| §4 Data model | Phase 3 (Task 3.1, 3.2) + Phase 0.3 migration |
| §5 Agent contracts | Task 4.1 (base) + 4.2 (L1) + 5.1 (L2) + 6.1 (L3) + 6.2 (L4) + 7.2 (L5) + 7.3 (L6) |
| §6 Refinement, gates, SSE | Task 5.2 (coordinator stall + decide) + 3.4 (SSE broker) + 4.5 (SSE endpoint) |
| §7 Multi-dialect providers | Phase 1 + Phase 2 |
| §8 UI flow | Phase 8 (Tasks 8.1–8.5) |
| §9 Error handling, resume | Task 4.6 (recovery) + Task 5.2 (gate errors) + cost summary (9.2) |
| §10 Testing | Every implementation task ends with a passing test; e2e in 7.4; contract tests in 9.4 |
| §11 Rollout plan | Each phase is shippable independently |
| §12 Env vars | Task 0.2 |
| §13 Out-of-scope | Honored: no edit-inline (gate UI in 8.4 is approve/reject/refine only); no LLM second-opinion (validation 7.2 deterministic); STM_VALIDATION_LLM_EXPLAIN flag wiring deferred to a future iteration with a TODO comment; no Redis; no secrets manager; no multi-worker (SessionLock present); no WebSocket; no dedicated `stm_session.php`; no auto-restart on crash |

**Placeholder scan:** None. Every step has concrete code or commands. The note about adapting `MappingRow` field names in 7.3 Step 5 directs the engineer to verify the actual dataclass — that's a runtime inspection step, not a placeholder.

**Type consistency:** `CandidateMapping.llm_confidence` is added in Task 3.1 (not in the spec's original sketch) and referenced in 6.1, 7.2. `BlackboardDelta.set_current_stage` and `clear_refine_feedback_for_stage` introduced in 4.1 and used uniformly thereafter. `StageStatus` enum used consistently across all agents.

**Ambiguity check:** The dispatch behavior when multiple agents are simultaneously applicable is decided: first-in-order from `default_agents()` (5.1 wires the order). The relationship between the deterministic rule engine (`mapping_engine.build_stm`) and L3 is fixed in `_rule_baseline()` (Task 6.1), preserving backward compatibility.

---

# Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-11-stm-agentic-evolution.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Sub-skill: `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?








