# Core Infrastructure Design
**Product:** Enterprise Data Migration Platform (SaaS)
**Date:** 2026-05-07
**Scope:** Core pipeline infrastructure — orchestrator, tenant model, execution engine, auth, gates, error handling, testing

---

## 1. Context

This platform is a multi-tenant SaaS product that automates enterprise data migration to BigQuery using an agentic AI pipeline. The pipeline has 4 main stages (Requirements → Mapping → Engineering → QA), each separated by a human-in-the-loop approval gate.

This spec covers the **core infrastructure** layer only — the machinery that runs agents, manages tenants, handles gates, and provides auth. Individual agent implementations (Agent 1–4) are out of scope here.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        SaaS Platform                        │
│                                                             │
│  ┌──────────┐    ┌──────────────────────────────────────┐  │
│  │  Auth    │    │         FastAPI App                  │  │
│  │  Layer   │───▶│  TenantMiddleware (injects DB conn)  │  │
│  │ JWT+bcrypt│   │  REST API  /pipelines  /gates        │  │
│  └──────────┘    └──────────────┬───────────────────────┘  │
│                                 │                           │
│                  ┌──────────────▼───────────────────────┐  │
│                  │       PipelineOrchestrator            │  │
│                  │  State machine: drives run lifecycle  │  │
│                  └──────────────┬───────────────────────┘  │
│                                 │                           │
│                  ┌──────────────▼───────────────────────┐  │
│                  │        ExecutionEngine (ABC)          │  │
│                  │  AsyncioEngine  (current)             │  │
│                  │  TemporalEngine (future, plug-in)     │  │
│                  └──────────────┬───────────────────────┘  │
│                                 │                           │
│          ┌──────────────────────┼──────────────────────┐   │
│          ▼                      ▼                      ▼   │
│      Agent 1              Agent 2              Agent 3+4   │
│   (Requirements)          (Mapping)          (Eng / QA)    │
│                                                             │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Tenant Postgres DB  (one per tenant)              │    │
│  │  pipeline_runs · gate_events · agent_outputs       │    │
│  │  generated_artifacts                               │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────┐   ┌───────────────┐   ┌──────────────┐   │
│  │  GateEngine │   │ SlackNotifier │   │ UI Dashboard │   │
│  │  pauses run │──▶│ posts to chan  │──▶│ approve/rej  │   │
│  │  awaits sig │   │ with run link  │   │ fires signal │   │
│  └─────────────┘   └───────────────┘   └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Responsibility |
|-----------|---------------|
| `TenantMiddleware` | Decodes JWT, resolves tenant DB connection, injects into request state |
| `PipelineOrchestrator` | Drives state machine, calls `ExecutionEngine`, triggers `GateEngine` |
| `ExecutionEngine` (ABC) | Abstraction over how agents run — `AsyncioEngine` now, `TemporalEngine` later |
| `GateEngine` | Pauses pipeline via `asyncio.Event`, fires Slack notification, resumes on approval |
| `ArtifactStore` (ABC) | Abstraction over artifact storage — `PostgresArtifactStore` now, `GCSArtifactStore` later |
| `agent_registry` | Dict mapping agent IDs to agent instances — swap implementations with one line |

---

## 3. Tenant Model

### Database isolation

- **Platform DB** (one, shared): manages tenant routing only
- **Tenant DB** (one per tenant): all pipeline data — provisioned at signup via Alembic migrations

### Platform DB schema

```sql
tenants (
  id            UUID PRIMARY KEY,
  name          TEXT NOT NULL,
  slug          TEXT UNIQUE NOT NULL,
  db_url_encrypted TEXT NOT NULL,   -- AES-256 encrypted connection string
  plan          TEXT DEFAULT 'starter',
  created_at    TIMESTAMPTZ DEFAULT now()
)

tenant_users (
  id            UUID PRIMARY KEY,
  tenant_id     UUID REFERENCES tenants(id),
  email         TEXT UNIQUE NOT NULL,
  hashed_password TEXT NOT NULL,
  role          TEXT NOT NULL,      -- admin | engineer | viewer
  created_at    TIMESTAMPTZ DEFAULT now()
)
```

`db_url_encrypted` is decrypted at runtime using an application-level key (never stored in the DB). The encryption key lives in environment config / GCP Secret Manager.

### Tenant provisioning (on signup)

1. Create row in `tenants`
2. Provision a new Postgres database
3. Run Alembic migrations against the new DB
4. Store the encrypted connection string in `tenants.db_url_encrypted`

---

## 4. Data Model (Tenant DB)

```sql
pipeline_runs (
  id              UUID PRIMARY KEY,
  status          TEXT NOT NULL,
  -- PENDING | RUNNING | AWAITING_GATE | COMPLETED | FAILED | REVISION_REQUESTED
  current_stage   TEXT,             -- agent_1 | agent_2 | agent_3 | agent_4
  input_payload   JSONB NOT NULL,   -- raw trigger input
  created_by      UUID NOT NULL,    -- tenant_user.id
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
)

gate_events (
  id              UUID PRIMARY KEY,
  run_id          UUID REFERENCES pipeline_runs(id),
  stage           TEXT NOT NULL,
  status          TEXT NOT NULL,    -- PENDING | APPROVED | REJECTED
  reviewer_email  TEXT,
  notes           TEXT,
  decided_at      TIMESTAMPTZ
)

agent_outputs (
  id              UUID PRIMARY KEY,
  run_id          UUID REFERENCES pipeline_runs(id),
  agent_id        TEXT NOT NULL,    -- agent_1 | agent_2 | agent_3a | etc.
  output_json     JSONB NOT NULL,   -- Pydantic model serialised
  created_at      TIMESTAMPTZ DEFAULT now()
)

generated_artifacts (
  id              UUID PRIMARY KEY,
  run_id          UUID REFERENCES pipeline_runs(id),
  agent_id        TEXT NOT NULL,
  artifact_type   TEXT NOT NULL,    -- SQL | DDL | DQ_RULE | YAML | METADATA
  filename        TEXT NOT NULL,
  content         TEXT NOT NULL,    -- stored in Postgres now; GCS later via ArtifactStore
  created_at      TIMESTAMPTZ DEFAULT now()
)
```

### Design decisions

- Agent outputs stored as **JSONB** — flexible, queryable, no migration needed when agent output schema evolves.
- `gate_events` is an **append-only audit log** — full history of who approved what.
- `ArtifactStore` abstraction: agents call `artifact_store.save(artifact)`, never write to DB directly. Today `PostgresArtifactStore` persists to `generated_artifacts`. Later, `GCSArtifactStore` uploads to a bucket and stores only the GCS URI in the DB.

---

## 5. Execution Engine & State Machine

### Pipeline state machine

```
PENDING
   │  trigger()
   ▼
RUNNING ──── agent timeout / exception ──▶ FAILED
   │
   │  agent completes stage
   ▼
AWAITING_GATE ──── rejected ──▶ FAILED
   │             └─ revision needed ──▶ REVISION_REQUESTED
   │  approved
   ▼
RUNNING  (next stage)
   │
   │  all stages complete
   ▼
COMPLETED
```

### ExecutionEngine interface

```python
class ExecutionEngine(ABC):
    async def run_agent(self, agent_id: str, input: BaseModel) -> BaseModel: ...
    async def cancel(self, run_id: str): ...

class AsyncioEngine(ExecutionEngine):
    async def run_agent(self, agent_id: str, input: BaseModel) -> BaseModel:
        agent = agent_registry[agent_id]
        task = asyncio.create_task(agent.run(input))
        return await asyncio.wait_for(task, timeout=settings.agent_timeouts[agent_id])
```

Agent 3 sub-agents (3a–3e) run in parallel inside the `agent_3` orchestrator:

```python
results = await asyncio.gather(
    engine.run_agent("agent_3a", input),
    engine.run_agent("agent_3b", input),
    engine.run_agent("agent_3c", input),
    engine.run_agent("agent_3d", input),
    engine.run_agent("agent_3e", input),
    return_exceptions=True
)
```

Partial failures are surfaced in the consolidated review package; one sub-agent failing does not abort the others.

### GateEngine

```python
class GateEngine:
    _gates: dict[str, asyncio.Event] = {}

    async def wait_for_approval(self, run_id: str, stage: str):
        event = asyncio.Event()
        self._gates[run_id] = event
        db.update_run(run_id, status="AWAITING_GATE")
        slack_notifier.notify(run_id, stage)
        await event.wait()
        result = db.get_gate_decision(run_id, stage)
        if result.status == "REJECTED":
            raise GateRejectedError(result.notes)

    def approve(self, run_id: str, stage: str, reviewer: str, notes: str):
        db.record_gate_event(run_id, stage=stage, status="APPROVED",
                             reviewer=reviewer, notes=notes)
        self._gates[run_id].set()

    def reject(self, run_id: str, stage: str, reviewer: str, notes: str):
        db.record_gate_event(run_id, stage=stage, status="REJECTED",
                             reviewer=reviewer, notes=notes)
        self._gates[run_id].set()
```

`asyncio.Event` maps cleanly to a Temporal `signal` when migrating later — the gate contract stays identical.

---

## 6. Auth & Tenant Middleware

### Request flow

```
Incoming request
  │
  ▼
JWTMiddleware
  ├── decode Bearer token → { user_id, tenant_id, role }
  ├── reject 401 if expired or invalid signature
  └── attach to request.state.user
  │
  ▼
TenantMiddleware
  ├── look up tenant in platform DB by tenant_id
  ├── decrypt db_url
  ├── open pooled Postgres connection to tenant DB
  └── attach to request.state.tenant_db
  │
  ▼
Route handler
  └── reads request.state.tenant_db — no platform DB access
```

### Auth flows

| Flow | Mechanism |
|------|-----------|
| Signup | Hash password (bcrypt, cost 12) → store in platform DB → provision tenant DB → return JWT pair |
| Login | Verify bcrypt hash → return JWT pair |
| Access token | Stateless JWT, 15-minute TTL, signed with HS256 |
| Refresh token | Stateful, 7-day TTL, stored in platform DB, rotated on use (old token invalidated) |
| Password reset | Time-limited signed token (1 hour), delivered via email link |

### Roles

| Role | Permissions |
|------|-------------|
| `admin` | Manage users, view all runs, approve any gate |
| `engineer` | Trigger pipelines, view runs, approve assigned gates |
| `viewer` | Read-only access to runs and artifacts |

Role is encoded in the JWT payload. Route handlers enforce it via a `require_role(role)` FastAPI dependency decorator.

---

## 7. Error Handling & Resilience

### Failure categories

| Category | Detection | Response |
|----------|-----------|----------|
| Agent exception | Uncaught exception in `run_agent` | Mark run `FAILED`, store error + stage, notify Slack |
| Agent timeout | `asyncio.wait_for` raises `TimeoutError` | Same as above |
| Gate rejection | Reviewer clicks Reject | Mark run `FAILED` with reviewer notes; `REVISION_REQUESTED` for rework cases |
| Claude API error | HTTP 5xx / rate limit | Retry with exponential backoff: 3 attempts, 2s / 4s / 8s delays |
| Server restart (RUNNING run) | Startup query | Mark `FAILED` — asyncio task state is lost; operator must re-trigger |
| Server restart (AWAITING_GATE run) | Startup query | Re-create `asyncio.Event` and stay suspended — gate approval is still valid |

### Invariants

- All DB writes use transactions — partial writes never leave a run in inconsistent state.
- Agent 3 sub-agents use `return_exceptions=True` — one sub-agent failure does not abort others.
- Every agent call has a configured timeout (set per-agent in `settings.agent_timeouts`).
- Run state is always persisted to DB before any gate notification fires — restart recovery is always possible.

---

## 8. Testing Strategy

### Unit tests

| Target | Approach |
|--------|----------|
| `PipelineOrchestrator` | Mock `ExecutionEngine` + `GateEngine`, assert state transitions |
| `GateEngine` | Mock DB, verify suspend / resume / rejection / restart recovery |
| `TenantMiddleware` | Mock platform DB, verify tenant resolution and DB injection |
| `ArtifactStore` | Verify save/retrieve contract against `PostgresArtifactStore` |
| Auth flows | Mock DB, verify JWT issue/verify/refresh/rotation |

### Integration tests

| Scenario | What it proves |
|----------|---------------|
| Full pipeline run (stub agents) | Orchestrator drives all stages correctly with no LLM calls |
| Gate approval end-to-end | Pipeline suspends, Slack fires, approval resumes correctly |
| Gate rejection end-to-end | Pipeline halts with correct status and notes |
| Two tenants run simultaneously | Zero data bleed between tenant DBs |
| Restart with `AWAITING_GATE` run | Event restored, approval still works after restart |

### Contract tests

- Each agent has a fixed Pydantic input/output schema registered in `agent_registry`.
- Contract tests assert that schema hasn't broken between code changes.
- Prevents silent interface breakage between agents (e.g., Agent 2 output change silently breaking Agent 3 input).

### Out of scope for now

- Load / performance testing (deferred until multi-tenant traffic exists)
- E2E tests with real Claude API calls (too slow/expensive for CI; covered by manual QA)

### Test infra

- `pytest` + `pytest-asyncio`
- `testcontainers` for real Postgres per test run
- Tenant fixture factory: one helper to provision a fully isolated test tenant

---

## 9. Future Migration Path

| Capability | Now | Later |
|------------|-----|-------|
| Execution engine | `AsyncioEngine` | `TemporalEngine` / `CloudWorkflowsEngine` — swap one class |
| Artifact storage | `PostgresArtifactStore` | `GCSArtifactStore` — swap one class |
| Gate suspension primitive | `asyncio.Event` | Temporal `signal` — same semantic contract |
| Auth | Email + password | Enterprise SSO (SAML/OIDC) — additive, existing auth unchanged |

All future migrations are **seam swaps**, not rewrites. Agent code is never touched.

---

## 10. Open Questions

_None — all design decisions resolved during brainstorming session._
