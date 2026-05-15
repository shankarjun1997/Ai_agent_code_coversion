# Phase 2 — Batch Pipeline + Mapping Agent Rewrite

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task.

**Goal:** Wire catalog selection into batch jobs (one STM session per source table), bounded concurrency, SSE progress, and batched-column mapping_agent.

**Architecture:** `POST /api/stm/batches` creates a Batch row + fan-out sessions. Orchestrator runs sessions concurrently (max 4). mapping_agent sends 12 source cols per LLM call and streams result rows. Batch SSE aggregates session events.

**Tech Stack:** Existing FastAPI + asyncio + SQLAlchemy 2.0 + anthropic SDK. Current alembic head: `c3d4e5f6a7b8`.

---

## File layout

```
alembic/versions/d1e2f3a4b5c6_batch_tables.py   NEW migration
core/models/batch.py                             NEW Batch SQLAlchemy model
core/batch/__init__.py                           NEW (empty)
core/batch/persistence.py                        NEW save/load/list batches
core/batch/orchestrator.py                       NEW fan-out + concurrency
routers/batches.py                               NEW 5 endpoints
core/stm/agents/mapping_agent.py                 REWRITE batched + streaming
core/stm/agents/schemas_agent.py                 UPDATE catalog cache load
app.py                                           MODIFY register batches router
```

---

## Task 1: Alembic migration — batches table + stm_sessions new columns

**Files:**
- Create: `alembic/versions/d1e2f3a4b5c6_batch_tables.py`

- [ ] **Step 1: Write the migration**

```python
# alembic/versions/d1e2f3a4b5c6_batch_tables.py
"""Add batches table and batch-related columns to stm_sessions.

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-05-15
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id",                 sa.String(36),  primary_key=True),
        sa.Column("tenant_id",          sa.String(64),  nullable=False, server_default="default"),
        sa.Column("catalog_source_id",  sa.String(36),  nullable=False),
        sa.Column("catalog_target_id",  sa.String(36),  nullable=False),
        sa.Column("business_context",   sa.Text(),      nullable=True),
        sa.Column("status",             sa.String(16),  nullable=False, server_default="pending"),
        sa.Column("session_count",      sa.Integer(),   nullable=False, server_default="0"),
        sa.Column("done_count",         sa.Integer(),   nullable=False, server_default="0"),
        sa.Column("created_at",         sa.DateTime(),  nullable=False),
        sa.Column("updated_at",         sa.DateTime(),  nullable=False),
    )
    op.add_column("stm_sessions", sa.Column("batch_id",               sa.String(36), nullable=True))
    op.add_column("stm_sessions", sa.Column("catalog_source_id",      sa.String(36), nullable=True))
    op.add_column("stm_sessions", sa.Column("catalog_target_id",      sa.String(36), nullable=True))
    op.add_column("stm_sessions", sa.Column("catalog_source_table_id",sa.String(36), nullable=True))
    op.add_column("stm_sessions", sa.Column("source_table_name",      sa.String(255),nullable=True))


def downgrade() -> None:
    for col in ["batch_id","catalog_source_id","catalog_target_id","catalog_source_table_id","source_table_name"]:
        op.drop_column("stm_sessions", col)
    op.drop_table("batches")
```

- [ ] **Step 2: Apply migration**

```bash
docker exec sqlgen-api alembic upgrade head
```

Expected: `Running upgrade c3d4e5f6a7b8 -> d1e2f3a4b5c6, Add batches table ...`

- [ ] **Step 3: Verify**

```bash
docker exec sqlgen-api python3 -c "
from sqlalchemy import create_engine, text
import os
e = create_engine(os.environ['DATABASE_URL'].replace('+asyncpg',''))
with e.connect() as c:
    r = c.execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='batches' ORDER BY ordinal_position\"))
    print([row[0] for row in r])
"
```

Expected: list with `id, tenant_id, catalog_source_id, catalog_target_id, business_context, status, session_count, done_count, created_at, updated_at`.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/d1e2f3a4b5c6_batch_tables.py
git commit -m "feat(batch): migration — batches table + batch columns on stm_sessions"
```

---

## Task 2: SQLAlchemy Batch model

**Files:**
- Create: `core/models/batch.py`

- [ ] **Step 1: Write model**

```python
# core/models/batch.py
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from core.models.platform import PlatformBase


class Batch(PlatformBase):
    __tablename__ = "batches"

    id:                Mapped[str]           = mapped_column(String(36), primary_key=True)
    tenant_id:         Mapped[str]           = mapped_column(String(64), nullable=False, server_default="default")
    catalog_source_id: Mapped[str]           = mapped_column(String(36), nullable=False)
    catalog_target_id: Mapped[str]           = mapped_column(String(36), nullable=False)
    business_context:  Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status:            Mapped[str]           = mapped_column(String(16), nullable=False, server_default="pending")
    session_count:     Mapped[int]           = mapped_column(Integer(), nullable=False, server_default="0")
    done_count:        Mapped[int]           = mapped_column(Integer(), nullable=False, server_default="0")
    created_at:        Mapped[datetime]      = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at:        Mapped[datetime]      = mapped_column(DateTime(), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 2: Smoke import**

```bash
docker compose up --build api -d
until docker exec sqlgen-api curl -fs http://localhost:8000/api/health >/dev/null; do sleep 1; done
docker exec sqlgen-api python3 -c "from core.models.batch import Batch; print('OK', Batch.__tablename__)"
```

Expected: `OK batches`

- [ ] **Step 3: Commit**

```bash
git add core/models/batch.py
git commit -m "feat(batch): SQLAlchemy Batch model"
```

---

## Task 3: Batch persistence helpers

**Files:**
- Create: `core/batch/__init__.py`
- Create: `core/batch/persistence.py`
- Create: `tests/test_batch_persistence.py`

- [ ] **Step 1: Create `core/batch/__init__.py`** (empty)

- [ ] **Step 2: Write failing test**

```python
# tests/test_batch_persistence.py
import uuid
import pytest
from core.batch.persistence import create_batch, get_batch, list_batches, update_batch_status


@pytest.mark.asyncio
async def test_create_and_get_batch():
    bid = await create_batch(
        tenant_id="default",
        catalog_source_id=str(uuid.uuid4()),
        catalog_target_id=str(uuid.uuid4()),
        business_context="test batch",
        session_count=3,
    )
    assert bid

    batch = await get_batch(bid)
    assert batch["id"] == bid
    assert batch["status"] == "pending"
    assert batch["session_count"] == 3
    assert batch["done_count"] == 0


@pytest.mark.asyncio
async def test_update_batch_status():
    bid = await create_batch(
        tenant_id="default",
        catalog_source_id=str(uuid.uuid4()),
        catalog_target_id=str(uuid.uuid4()),
        business_context=None,
        session_count=1,
    )
    await update_batch_status(bid, status="running", done_count=0)
    batch = await get_batch(bid)
    assert batch["status"] == "running"
```

- [ ] **Step 3: Run — expect ImportError**

```bash
docker exec sqlgen-api pytest tests/test_batch_persistence.py -v
```

- [ ] **Step 4: Write `core/batch/persistence.py`**

```python
# core/batch/persistence.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import select, update
from core.db.platform import get_platform_session_factory
from core.models.batch import Batch


async def create_batch(
    *,
    tenant_id: str,
    catalog_source_id: str,
    catalog_target_id: str,
    business_context: Optional[str],
    session_count: int,
) -> str:
    factory = get_platform_session_factory()
    now = datetime.utcnow()
    bid = str(uuid.uuid4())
    async with factory() as session:
        session.add(Batch(
            id=bid,
            tenant_id=tenant_id,
            catalog_source_id=catalog_source_id,
            catalog_target_id=catalog_target_id,
            business_context=business_context,
            status="pending",
            session_count=session_count,
            done_count=0,
            created_at=now,
            updated_at=now,
        ))
        await session.commit()
    return bid


async def get_batch(batch_id: str) -> Dict[str, Any]:
    factory = get_platform_session_factory()
    async with factory() as session:
        b = (await session.execute(select(Batch).where(Batch.id == batch_id))).scalar_one_or_none()
        if b is None:
            raise KeyError(f"Batch {batch_id} not found")
    return {
        "id": b.id, "tenant_id": b.tenant_id,
        "catalog_source_id": b.catalog_source_id,
        "catalog_target_id": b.catalog_target_id,
        "business_context": b.business_context,
        "status": b.status,
        "session_count": b.session_count,
        "done_count": b.done_count,
        "created_at": b.created_at.isoformat(),
        "updated_at": b.updated_at.isoformat(),
    }


async def list_batches(*, tenant_id: str) -> List[Dict[str, Any]]:
    factory = get_platform_session_factory()
    async with factory() as session:
        rows = (await session.execute(
            select(Batch).where(Batch.tenant_id == tenant_id).order_by(Batch.created_at.desc())
        )).scalars().all()
    return [{"id": b.id, "status": b.status, "session_count": b.session_count,
             "done_count": b.done_count, "created_at": b.created_at.isoformat()} for b in rows]


async def update_batch_status(batch_id: str, *, status: str, done_count: Optional[int] = None) -> None:
    factory = get_platform_session_factory()
    vals: Dict[str, Any] = {"status": status, "updated_at": datetime.utcnow()}
    if done_count is not None:
        vals["done_count"] = done_count
    async with factory() as session:
        await session.execute(update(Batch).where(Batch.id == batch_id).values(**vals))
        await session.commit()
```

- [ ] **Step 5: Rebuild + run test**

```bash
docker compose up --build api -d
until docker exec sqlgen-api curl -fs http://localhost:8000/api/health >/dev/null; do sleep 1; done
docker exec sqlgen-api pytest tests/test_batch_persistence.py tests/test_catalog_persistence.py -v 2>&1 | tail -10
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add core/batch/__init__.py core/batch/persistence.py tests/test_batch_persistence.py
git commit -m "feat(batch): persistence helpers — create/get/list/update batch"
```

---

## Task 4: Batch orchestrator

**Files:**
- Create: `core/batch/orchestrator.py`

The orchestrator fans out one STM session per source table. It reads the source catalog tables from the catalog store, creates one `stm_session` per table (with `batch_id` + `catalog_source_table_id` set), then runs sessions with a semaphore (max `STM_MAX_PARALLEL_SESSIONS`, default 4).

- [ ] **Step 1: Write `core/batch/orchestrator.py`**

```python
# core/batch/orchestrator.py
"""Fan-out one STM session per source table in a batch."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import update as sa_update

from core.batch.persistence import get_batch, update_batch_status
from core.catalog.persistence import load_source_catalog, load_target_catalog
from core.db.platform import get_platform_session_factory
from core.models.platform import StmSession  # adjust import to wherever StmSession is defined

logger = logging.getLogger(__name__)

_MAX_PARALLEL = int(os.getenv("STM_MAX_PARALLEL_SESSIONS", "4"))


async def _create_session_row(
    batch_id: str,
    tenant_id: str,
    catalog_source_id: str,
    catalog_target_id: str,
    table: Dict[str, Any],
) -> str:
    """Insert one stm_sessions row linked to this batch + table."""
    factory = get_platform_session_factory()
    session_id = str(uuid.uuid4())
    now = datetime.utcnow()
    async with factory() as db:
        db.add(StmSession(
            id=session_id,
            tenant_id=tenant_id,
            status="pending",
            current_stage=None,
            batch_id=batch_id,
            catalog_source_id=catalog_source_id,
            catalog_target_id=catalog_target_id,
            catalog_source_table_id=table["id"],
            source_table_name=table["table_name"],
            created_at=now,
            updated_at=now,
        ))
        await db.commit()
    return session_id


async def _run_session(session_id: str) -> None:
    """Drive the 4-stage pipeline for one session (imports coordinator)."""
    from core.stm.coordinator import run_session  # local import to avoid circular
    try:
        await run_session(session_id)
    except Exception as exc:
        logger.error("Session %s failed: %s", session_id, exc)


async def run_batch(batch_id: str) -> None:
    """Fan out + run all sessions for a batch."""
    batch = await get_batch(batch_id)
    tenant_id         = batch["tenant_id"]
    catalog_source_id = batch["catalog_source_id"]
    catalog_target_id = batch["catalog_target_id"]

    source = await load_source_catalog(catalog_source_id)
    tables = source.get("tables", [])

    if not tables:
        await update_batch_status(batch_id, status="failed", done_count=0)
        return

    # Update batch with actual session count
    factory = get_platform_session_factory()
    async with factory() as db:
        await db.execute(
            sa_update(type("_", (), {"__table__": None}))  # placeholder
        )

    await update_batch_status(batch_id, status="running", done_count=0)

    sem = asyncio.Semaphore(_MAX_PARALLEL)
    done = 0

    async def _bounded(table: Dict[str, Any]) -> None:
        nonlocal done
        async with sem:
            sid = await _create_session_row(batch_id, tenant_id, catalog_source_id, catalog_target_id, table)
            await _run_session(sid)
            done += 1
            await update_batch_status(batch_id, status="running", done_count=done)

    await asyncio.gather(*[_bounded(t) for t in tables])
    await update_batch_status(batch_id, status="done", done_count=done)
```

**NOTE:** The `StmSession` model import path must match your actual model location. Run `grep -rn "class StmSession\|StmSession" core/models/ core/stm/` to find it. If the model doesn't have the new columns yet (`batch_id`, `catalog_source_id`, etc.), add them to the model class (they exist in the DB from Task 1 migration).

- [ ] **Step 2: Find StmSession model and add new columns**

```bash
docker exec sqlgen-api python3 -c "
import subprocess
r = subprocess.run(['grep','-rn','class StmSession','/app/core/'], capture_output=True, text=True)
print(r.stdout)
"
```

Once found, open that file and add these `Mapped` columns (using SQLAlchemy 2.0 style, matching existing patterns):
```python
batch_id:                Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
catalog_source_id:       Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
catalog_target_id:       Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
catalog_source_table_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
source_table_name:       Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```

- [ ] **Step 3: Fix the update placeholder in orchestrator**

The `sa_update` call in `run_batch` has a placeholder. Replace it with a proper update that sets `session_count`:

```python
from core.models.batch import Batch
async with factory() as db:
    await db.execute(
        sa_update(Batch).where(Batch.id == batch_id).values(session_count=len(tables), updated_at=datetime.utcnow())
    )
    await db.commit()
```

- [ ] **Step 4: Smoke import**

```bash
docker compose up --build api -d
until docker exec sqlgen-api curl -fs http://localhost:8000/api/health >/dev/null; do sleep 1; done
docker exec sqlgen-api python3 -c "from core.batch.orchestrator import run_batch; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add core/batch/orchestrator.py
git commit -m "feat(batch): orchestrator — fan-out sessions with bounded concurrency"
```

---

## Task 5: Batches router

**Files:**
- Create: `routers/batches.py`
- Modify: `app.py`

**Endpoints:**
```
POST   /api/stm/batches              submit batch (returns 201 + batch_id, fires run_batch in background)
GET    /api/stm/batches              list batches for tenant
GET    /api/stm/batches/{id}         get batch summary + session list
GET    /api/stm/batches/{id}/events  SSE: aggregate events from all sessions in batch
```

- [ ] **Step 1: Write `routers/batches.py`**

```python
# routers/batches.py
"""Batch submission and status API."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.batch.orchestrator import run_batch
from core.batch.persistence import create_batch, get_batch, list_batches, update_batch_status
from core.catalog.persistence import load_source_catalog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stm/batches", tags=["batches"])


def _tenant(req: Request) -> str:
    return getattr(req.state, "tenant_id", None) or "default"


class BatchIn(BaseModel):
    catalog_source_id: str
    catalog_target_id: str
    business_context: Optional[str] = None


@router.post("", status_code=201)
async def submit_batch(req: Request, body: BatchIn) -> dict:
    # Count source tables to set session_count
    try:
        source = await load_source_catalog(body.catalog_source_id)
    except KeyError:
        raise HTTPException(404, f"Source catalog {body.catalog_source_id} not found")

    table_count = source.get("table_count", 0)
    if table_count == 0:
        raise HTTPException(422, "Source catalog has no tables")

    batch_id = await create_batch(
        tenant_id=_tenant(req),
        catalog_source_id=body.catalog_source_id,
        catalog_target_id=body.catalog_target_id,
        business_context=body.business_context,
        session_count=table_count,
    )

    # Fire-and-forget orchestrator
    asyncio.create_task(run_batch(batch_id))

    return {"batch_id": batch_id, "session_count": table_count, "status": "pending"}


@router.get("")
async def list_batches_endpoint(req: Request) -> dict:
    rows = await list_batches(tenant_id=_tenant(req))
    return {"batches": rows}


@router.get("/{batch_id}")
async def get_batch_endpoint(batch_id: str) -> dict:
    try:
        return await get_batch(batch_id)
    except KeyError:
        raise HTTPException(404, f"Batch {batch_id} not found")


@router.get("/{batch_id}/events")
async def batch_events(batch_id: str, req: Request):
    """SSE stream: forward events from all sessions in this batch."""
    from sqlalchemy import select, text
    from core.db.platform import get_platform_session_factory
    from core.stm.events import EventBroker  # existing SSE broker

    async def generate():
        # Poll batch sessions and forward their events
        # Simple implementation: poll DB for new events every 2s
        factory = get_platform_session_factory()
        seen: set = set()
        while True:
            if await req.is_disconnected():
                break
            try:
                async with factory() as db:
                    rows = await db.execute(
                        text("""
                            SELECT e.id, e.session_id, e.kind, e.payload, e.created_at
                            FROM stm_stage_events e
                            JOIN stm_sessions s ON s.id = e.session_id
                            WHERE s.batch_id = :bid
                            ORDER BY e.created_at ASC
                        """),
                        {"bid": batch_id}
                    )
                    for row in rows:
                        if row[0] not in seen:
                            seen.add(row[0])
                            data = json.dumps({
                                "session_id": row[1],
                                "kind": row[2],
                                "payload": json.loads(row[3]) if row[3] else {},
                            })
                            yield f"data: {data}\n\n"
            except Exception as exc:
                logger.warning("Batch SSE error: %s", exc)
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 2: Register router in `app.py`**

Add after the other router imports:
```python
from routers.batches import router as batches_router
```

Add after `app.include_router(catalogs_router)`:
```python
app.include_router(batches_router)
```

- [ ] **Step 3: Rebuild + verify endpoints exist**

```bash
docker compose up --build api -d
until docker exec sqlgen-api curl -fs http://localhost:8000/api/health >/dev/null; do sleep 1; done
docker exec sqlgen-api python3 -c "
import urllib.request as u, json
r = u.urlopen('http://localhost:8000/openapi.json')
paths = list(json.loads(r.read())['paths'].keys())
batch_paths = [p for p in paths if 'batches' in p]
print(batch_paths)
"
```

Expected: list containing `/api/stm/batches`, `/api/stm/batches/{batch_id}`, `/api/stm/batches/{batch_id}/events`.

- [ ] **Step 4: Commit**

```bash
git add routers/batches.py app.py
git commit -m "feat(batch): batches router — submit, list, get, SSE"
```

---

## Task 6: mapping_agent.py rewrite — batched columns + mapping_memory

**Files:**
- Rewrite: `core/stm/agents/mapping_agent.py`

Existing `mapping_agent.py` does single-shot LLM mapping. Rewrite to:
1. Split source columns into batches of 12
2. For each batch: recall top-10 mapping_memory rows with overlapping column names (Postgres `LIKE` match)
3. One LLM call per batch: system prompt with only the picked target tables' column metadata
4. Stream result rows back via session SSE events
5. Concurrency: asyncio.Semaphore(2) for in-flight L3 calls within a session

- [ ] **Step 1: Read existing mapping_agent.py** to understand current signature + LLM call pattern before rewriting.

- [ ] **Step 2: Write rewrite**

The new `mapping_agent.py` must expose the same class interface (`MappingAgent` with `run(context)` async method) expected by the coordinator. Key changes:

```python
# core/stm/agents/mapping_agent.py
"""L3 Mapping Agent — batched per-column with mapping_memory few-shot."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from core.llm_client import LLMClient
from core.stm.agents.base import StmAgent, AgentContext

logger = logging.getLogger(__name__)

_BATCH_SIZE  = int(os.getenv("STM_L3_BATCH_SIZE", "12"))
_CONCURRENCY = int(os.getenv("STM_L3_CONCURRENCY", "2"))
_MODEL       = os.getenv("STM_LLM_MODEL_L3", os.getenv("LLM_MODEL", "deepseek-chat"))


class MappingAgent(StmAgent):
    """L3: map source columns to target columns in batches of STM_L3_BATCH_SIZE."""

    async def run(self, ctx: AgentContext) -> Dict[str, Any]:
        bb = ctx.blackboard
        source_cols   = bb.get("source_columns", [])   # [{name, type, description}]
        target_tables = bb.get("shortlisted_tables", [])  # [{table_name, columns:[...]}]

        if not source_cols:
            return {"mappings": [], "error": "no source columns"}
        if not target_tables:
            return {"mappings": [], "error": "no target tables shortlisted"}

        batches = [source_cols[i:i+_BATCH_SIZE] for i in range(0, len(source_cols), _BATCH_SIZE)]
        sem     = asyncio.Semaphore(_CONCURRENCY)
        results: List[Dict[str, Any]] = []

        async def _run_batch(batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            async with sem:
                memory_rows = await _recall_memory(ctx.session_id, batch)
                return await _llm_map_batch(batch, target_tables, memory_rows, ctx)

        batch_results = await asyncio.gather(*[_run_batch(b) for b in batches])
        for br in batch_results:
            results.extend(br)

        return {"mappings": results}


async def _recall_memory(session_id: str, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pull top-10 approved mapping_memory rows for columns in this batch."""
    try:
        from sqlalchemy import text
        from core.db.platform import get_platform_session_factory
        names = [c["name"] for c in batch if c.get("name")]
        if not names:
            return []
        factory = get_platform_session_factory()
        async with factory() as db:
            like_clause = " OR ".join([f"source_column_name ILIKE :n{i}" for i in range(len(names))])
            params = {f"n{i}": f"%{n}%" for i, n in enumerate(names)}
            params["limit"] = 10
            rows = await db.execute(
                text(f"""
                    SELECT source_column_name, target_column_name, transformation_logic
                    FROM mapping_memory
                    WHERE approved = true AND ({like_clause})
                    ORDER BY created_at DESC LIMIT :limit
                """),
                params,
            )
            return [{"src": r[0], "tgt": r[1], "logic": r[2]} for r in rows]
    except Exception:
        return []


async def _llm_map_batch(
    batch: List[Dict[str, Any]],
    target_tables: List[Dict[str, Any]],
    memory_rows: List[Dict[str, Any]],
    ctx: AgentContext,
) -> List[Dict[str, Any]]:
    """One LLM call for a batch of source columns."""
    target_summary = "\n".join(
        f"TABLE {t['table_name']}: " + ", ".join(
            f"{c['name']}({c.get('type','?')})" for c in t.get("columns", [])
        )
        for t in target_tables
    )

    memory_block = ""
    if memory_rows:
        memory_block = "\n\nPrior approved mappings (few-shot):\n" + "\n".join(
            f"  {r['src']} → {r['tgt']}: {r['logic']}" for r in memory_rows
        )

    src_block = "\n".join(
        f"  {c.get('name')} ({c.get('type','?')}): {c.get('description','')}" for c in batch
    )

    prompt = f"""Map these source columns to the best target column.

SOURCE COLUMNS:
{src_block}

TARGET TABLES:
{target_summary}
{memory_block}

Return JSON array. Each element:
{{"source_column": "...", "target_table": "...", "target_column": "...", "transformation": "...", "confidence": 0.0-1.0, "rationale": "..."}}

Return ONLY the JSON array, no other text."""

    client = LLMClient()
    response = await asyncio.to_thread(
        client.complete,
        model=_MODEL,
        prompt=prompt,
        max_tokens=2048,
    )

    try:
        raw = response.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        mappings = json.loads(raw)
        if not isinstance(mappings, list):
            mappings = []
    except Exception:
        mappings = []

    # Emit SSE event per mapped column so UI can stream rows
    try:
        from core.stm.events import EventBroker
        broker = EventBroker.get(ctx.session_id)
        if broker:
            for m in mappings:
                await broker.publish("mapping_row", m)
    except Exception:
        pass

    return mappings
```

**Adapt the LLMClient call** to match the actual `client.complete` / `client.chat` signature in `core/llm_client.py`. Read that file first.

- [ ] **Step 3: Rebuild + smoke**

```bash
docker compose up --build api -d
until docker exec sqlgen-api curl -fs http://localhost:8000/api/health >/dev/null; do sleep 1; done
docker exec sqlgen-api python3 -c "from core.stm.agents.mapping_agent import MappingAgent; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add core/stm/agents/mapping_agent.py
git commit -m "feat(batch): mapping_agent rewrite — batched 12-col LLM calls + mapping_memory few-shot"
```

---

## Task 7: schemas_agent.py — load from catalog cache

**Files:**
- Modify: `core/stm/agents/schemas_agent.py`

When a session has `catalog_source_id` + `catalog_target_id` set (batch-created sessions), load schema from catalog DB instead of hitting BQ directly. Fall back to existing inline BQ fetch if those IDs are absent.

- [ ] **Step 1: Read current `core/stm/agents/schemas_agent.py`** to understand the existing BQ fetch path.

- [ ] **Step 2: Add catalog-cache path**

In the `run(ctx)` method, before the BQ fetch, add:

```python
# If session was created from catalog, load from cache (fast, no BQ round-trip)
session_meta = ctx.blackboard.get("session_meta", {})
catalog_source_id      = session_meta.get("catalog_source_id")
catalog_source_table_id = session_meta.get("catalog_source_table_id")
catalog_target_id      = session_meta.get("catalog_target_id")

if catalog_source_id and catalog_source_table_id and catalog_target_id:
    from core.catalog.persistence import load_source_catalog, load_target_catalog
    src_catalog = await load_source_catalog(catalog_source_id)
    tgt_catalog = await load_target_catalog(catalog_target_id)
    # Find the specific source table
    src_table = next(
        (t for t in src_catalog.get("tables", []) if t["id"] == catalog_source_table_id),
        None
    )
    if src_table:
        return {
            "source_columns": src_table["columns"],
            "source_table_name": src_table["table_name"],
            "target_tables": tgt_catalog.get("tables", []),
        }
    # Fall through to BQ fetch if table not found
```

The coordinator must populate `session_meta` in the blackboard with `catalog_source_id`, `catalog_source_table_id`, `catalog_target_id` from the session row at session start.

- [ ] **Step 3: Update coordinator to populate session_meta**

Read `core/stm/coordinator.py`. At session start (where blackboard is initialized), add:

```python
# Load session row to get catalog IDs for batch sessions
from sqlalchemy import select, text
from core.db.platform import get_platform_session_factory
factory = get_platform_session_factory()
async with factory() as db:
    row = (await db.execute(
        text("SELECT catalog_source_id, catalog_target_id, catalog_source_table_id, source_table_name FROM stm_sessions WHERE id = :id"),
        {"id": session_id}
    )).one_or_none()
if row:
    blackboard["session_meta"] = {
        "catalog_source_id": row[0],
        "catalog_target_id": row[1],
        "catalog_source_table_id": row[2],
        "source_table_name": row[3],
    }
```

- [ ] **Step 4: Rebuild + smoke**

```bash
docker compose up --build api -d
until docker exec sqlgen-api curl -fs http://localhost:8000/api/health >/dev/null; do sleep 1; done
docker exec sqlgen-api pytest tests/ --ignore=tests/stm -q 2>&1 | tail -5
```

All existing tests must still pass.

- [ ] **Step 5: Commit**

```bash
git add core/stm/agents/schemas_agent.py core/stm/coordinator.py
git commit -m "feat(batch): schemas_agent loads from catalog cache for batch sessions"
```

---

## Task 8: End-to-end smoke — submit a batch via API

**No new files.** Verify the full pipeline: POST batch → sessions created → orchestrator runs → status updates.

- [ ] **Step 1: Get a real source + target catalog ID**

```bash
docker exec sqlgen-api python3 -c "
import urllib.request as u, json
src = json.loads(u.urlopen('http://localhost:8000/api/catalogs/source').read())['catalogs']
tgt = json.loads(u.urlopen('http://localhost:8000/api/catalogs/target').read())['catalogs']
print('SOURCE:', src[0]['id'], src[0]['catalog_name'], src[0]['table_count'], 'tables')
print('TARGET:', tgt[0]['id'], tgt[0]['project'] + '.' + tgt[0]['dataset'])
"
```

- [ ] **Step 2: Submit a batch (use a small source to avoid LLM cost)**

```bash
docker exec sqlgen-api python3 -c "
import urllib.request as u, json
# Use whichever source catalog has the fewest tables
src_id = 'REPLACE_WITH_SOURCE_ID'
tgt_id = 'REPLACE_WITH_TARGET_ID'
body = json.dumps({'catalog_source_id': src_id, 'catalog_target_id': tgt_id, 'business_context': 'smoke test'}).encode()
req = u.Request('http://localhost:8000/api/stm/batches', data=body, method='POST', headers={'Content-Type':'application/json'})
r = json.loads(u.urlopen(req).read())
print('BATCH:', json.dumps(r, indent=2))
"
```

Expected: `{"batch_id": "...", "session_count": N, "status": "pending"}`

- [ ] **Step 3: Poll batch status**

```bash
# Poll for 30s
docker exec sqlgen-api python3 -c "
import urllib.request as u, json, time
bid = 'REPLACE_WITH_BATCH_ID'
for _ in range(15):
    r = json.loads(u.urlopen(f'http://localhost:8000/api/stm/batches/{bid}').read())
    print(r.get('status'), r.get('done_count'), '/', r.get('session_count'))
    if r.get('status') in ('done', 'failed'): break
    time.sleep(2)
"
```

Expected: status transitions `pending → running → done`.

- [ ] **Step 4: Commit (if any fixes were needed)**

If no code changes were needed: `echo "no smoke commit needed"`.
If fixes were needed: commit with `fix(batch): smoke — <what was fixed>`.

---

## Done criteria

1. `pytest tests/ --ignore=tests/stm -q` — all green (no regressions)
2. `POST /api/stm/batches` → 201 with `batch_id`
3. Batch status transitions `pending → running → done`
4. `/batch/{id}` in ZealPHP UI shows batch info (once wired — Phase 4 UI shell is already in place)
5. 6 atomic commits

## Hand-off for Phase 3

Phase 3 (Vector recall) needs:
- `target_table_embeddings` table migration
- `core/catalog/embedding_providers/voyage.py`
- L2 shortlist agent updated to: embed source table → pgvector recall top-50 → LLM ranks
- Background reindex job on catalog refresh
