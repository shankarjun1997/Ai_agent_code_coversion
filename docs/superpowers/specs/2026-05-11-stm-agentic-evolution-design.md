# STM Agentic Evolution — Design Spec

**Date:** 2026-05-11
**Status:** Approved — ready for plan
**Author:** Shankar (with Claude)
**Scope home:** `core/stm/` + `core/discovery/` + `routers/stm.py` + `ui/mapping_compose_react.html`

---

## 1. Vision & Mental Model

Today `core/stm/` is a **deterministic rule-based** Source-to-Target Mapping engine: pick Postgres columns → `build_stm()` produces a `MappingResult` → render to xlsx/csv. One in-memory dict, one LLM-less path.

This iteration evolves STM into a **multi-agent reasoning pipeline** that mirrors enterprise data-engineering review: progressive certainty, layered enrichment, two human-governance checkpoints, full auditability.

**Guiding principle: "A progressive certainty engine."** Each stage receives incomplete information, enriches it, reduces ambiguity, increases confidence, and hands a more structured artifact to the next stage.

The pipeline has six layers:

1. **L1 — Intent Extraction** — parse Jira story or free-text into structured business intent (entity, action, dimension/fact, SCD hint, filters, grain).
2. **L2 — Metadata Intelligence** — build a knowledge graph from all selected source profiles (Postgres / Oracle / MySQL / MSSQL / BigQuery) and the BQ target; infer cross-source join candidates and concept links.
3. **L3 — Semantic Mapping** — produce candidate field mappings. The rule-based `mapping_engine.build_stm()` runs first as a deterministic floor; an LLM reasoner refines and adds rows the rules cannot infer (joins, derived, lookups).
4. **L4 — Transformation Synthesis** — synthesize derived columns, SCD2 logic, audit fields, surrogate keys, filters from `intent.filters`, idempotency key and partition field.
5. **L5 — Validation & Governance** — deterministic confidence scoring (ensemble of LLM self-score + heuristics) and rule-based finding generation (block / warn / info).
6. **L6 — STM Generation** — compose the final `MappingResult` from approved blackboard contents; render to xlsx/csv via existing `core/stm/exporter.py`; optional Jira write-back.

Two human-governance checkpoints:
- **Gate 1** after L2 — confirm scope, lineage, source coverage before semantic work begins.
- **Gate 2** after L5 — approve mappings, transforms, and confidence assessment before STM generation.

Reviewer actions at each gate: **Approve / Reject / Refine-with-feedback**. Refinement names a target stage (Lk) and a free-text feedback message; that stage and everything downstream are marked stale and rerun in dependency order.

---

## 2. Locked Constraints

These were decided during brainstorm and bound the spec:

| # | Decision | Why |
|---|---|---|
| 1 | Full 6-layer big bang, inside `core/stm/` | User wants the full evolution, not incremental |
| 2 | L1 intent fed by Jira issue key **or** free-text (user picks per session) | Supports both governed and ad-hoc paths |
| 3 | Knowledge graph = Pydantic nested model + query helpers | No new deps; serializes cleanly for LLM/UI/persistence |
| 4 | State = new `stm_sessions` + `stm_stage_events` + `stm_gate_decisions` tables | Live timeline for UI, easy resume, clean audit |
| 5 | Confidence = ensemble (LLM self-score + heuristics, weighted) | "AI confidence != enterprise trust" — single signal is unsafe |
| 6 | Sources = Postgres, Oracle, MySQL, MSSQL, BQ → BigQuery (all real) | Multi-dialect is part of the evolution, not deferred |
| 7 | Agentic wraps rules — `build_stm()` always runs as baseline inside L3 | Deterministic floor that LLM refinement cannot drop below |
| 8 | SSE progress via existing `ui/sse.php` | Push-based, zero new infra |
| 9 | Gate UX = Approve / Reject / Refine; stages idempotent + rerunnable | Matches "progressive certainty" |
| 10 | Orchestrator shape = **Stage-as-agent + shared blackboard** | Most pure agentic; enables future intra-stage parallelism |
| 11 | LLM model split: Haiku (L1), Sonnet (L2), Opus (L3, L4), none (L5, L6) | Cost/quality tradeoff |
| 12 | L5 deterministic (no LLM second-opinion in v1) | Reproducibility; LLM "explain-finding" behind config flag |
| 13 | Reject is terminal; retry via `POST /sessions/{id}/clone` | Clean audit trail |
| 14 | Single-worker uvicorn assumed; `SessionLock` abstraction wraps `asyncio.Lock` for later DB advisory | Defer multi-worker complexity |
| 15 | MSSQL via pure-Python `pytds` (no ODBC dep) | Keep Dockerfile clean |
| 16 | Credentials via Fernet, key in env (`STM_PROFILE_ENCRYPTION_KEY`) | Simple v1; secrets-manager migration deferred |
| 17 | UI = single-page React stepper in existing `mapping_compose_react.html` with `?mode=agentic` toggle | No new page file in v1 |
| 18 | Jira write-back default **OFF**; per-env opt-in via `STM_JIRA_WRITEBACK_ENABLED` | Safety |

---

## 3. Architecture & Blackboard Topology

```
                ┌────────────────────────────────────────────────────────────┐
                │                  STM SESSION BLACKBOARD                    │
                │  (single shared Pydantic state per session, persisted)     │
                │                                                            │
                │  intent           ← L1 writes                              │
                │  metadata_graph   ← L2 writes (entities, columns, rels)    │
                │  candidate_maps   ← L3 writes                              │
                │  transformations  ← L4 writes                              │
                │  validation       ← L5 writes (confidence, flags)          │
                │  stm_result       ← L6 writes                              │
                │  gates            ← coordinator writes (gate1, gate2)      │
                │  stage_status     ← per-stage status enum                  │
                └─────────────────▲──────────────────────────────────────────┘
                                  │ read / write
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
   ┌────┴────┐  ┌────────┐  ┌─────┴────┐  ┌────────┐  ┌─────┴────┐  ┌────────┐
   │ L1      │  │ L2     │  │ L3       │  │ L4     │  │ L5       │  │ L6 STM │
   │ Intent  │  │ Meta   │  │ Semantic │  │ Xform  │  │ Validate │  │ Build  │
   └─────────┘  └────────┘  └──────────┘  └────────┘  └──────────┘  └────────┘
       (Haiku)    (Sonnet)     (Opus)      (Opus)     (no LLM)      (no LLM)

       ┌───────────────────────────────────────────────────────────┐
       │  COORDINATOR (core/stm/coordinator.py)                    │
       │  - per-session asyncio.Task ticking every 200ms           │
       │  - dispatches eligible agent when readiness rule holds    │
       │  - persists every write as stm_stage_events row           │
       │  - emits SSE events on every transition                   │
       │  - stalls on gates until decision arrives                 │
       │  - on refinement: invalidates downstream, redispatches    │
       └───────────────────────────────────────────────────────────┘
```

### Module layout

```
core/stm/
├── __init__.py                       # exports unchanged build_stm, MappingResult, to_xlsx, to_csv
├── mapping_engine.py                 # EXISTING — deterministic rule engine (L3 baseline)
├── exporter.py                       # EXISTING — xlsx/csv rendering (L6)
├── blackboard.py                     # NEW — Pydantic StmBlackboard + sub-models
├── coordinator.py                    # NEW — per-session dispatch loop, gate stalls, SSE emit
├── locks.py                          # NEW — SessionLock abstraction (asyncio.Lock for now)
├── events.py                         # NEW — SSE event types + emit helpers
├── persistence.py                    # NEW — stm_sessions / stm_stage_events / gates CRUD
└── agents/
    ├── __init__.py
    ├── base.py                       # StmAgent ABC, AgentContext, BlackboardDelta
    ├── intent.py                     # L1 — Haiku
    ├── metadata.py                   # L2 — Sonnet, parallel source probing
    ├── semantic.py                   # L3 — Opus, wraps build_stm
    ├── transform.py                  # L4 — Opus
    ├── validation.py                 # L5 — deterministic ensemble scoring
    └── builder.py                    # L6 — composes MappingResult

core/discovery/
├── base.py                           # NEW — SourceProvider ABC
├── registry.py                       # NEW — dialect → provider
├── cache.py                          # NEW — 15min TTL cache (in-memory)
├── postgres_provider.py              # REFACTOR — wrap sync code in async interface
├── oracle_provider.py                # NEW — oracledb thin mode
├── mysql_provider.py                 # NEW — pymysql
├── mssql_provider.py                 # NEW — python-tds
├── bigquery_provider.py              # NEW — wraps core/bq_client.py
└── profiles.py                       # EXTEND — encrypted creds, ping status

routers/stm.py                        # EXTEND — session lifecycle, SSE, gate decisions
routers/discovery.py                  # EXTEND — per-dialect profile POST endpoints

ui/mapping_compose_react.html         # EXTEND — agentic-mode stepper view
ui/sse.php                            # REUSED — proxy SSE to STM events
```

---

## 4. Data Model

### Blackboard Pydantic shapes (`core/stm/blackboard.py`)

```python
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
    jira_issue_key: Optional[str]
    entity: str
    action: str                      # create|refresh|backfill|migrate
    is_dimension: bool
    is_fact: bool
    scd_hint: Optional[Literal["type1","type2","type3","none"]]
    filters: List[str]
    grain_hint: Optional[str]
    extracted_keywords: List[str]
    status: StageStatus

class GraphNode(BaseModel):
    id: str                          # e.g. "pg.public.customers.customer_id"
    kind: Literal["dialect","schema","table","column","concept"]
    label: str
    dialect: Optional[str]
    data_type: Optional[str]
    nullable: Optional[bool]
    is_pii: Optional[bool]
    profile: Optional[Dict[str, Any]]

class GraphEdge(BaseModel):
    src: str
    dst: str
    kind: Literal["contains","fk","semantic_match","join_candidate","concept_link"]
    confidence: Optional[float]
    evidence: Optional[str]

class MetadataGraph(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    sources_probed: List[str]
    coverage_notes: List[str]
    status: StageStatus

    def find_by_concept(self, concept: str) -> List[GraphNode]: ...
    def join_candidates(self, table_id: str) -> List[GraphEdge]: ...
    def columns_of(self, table_id: str) -> List[GraphNode]: ...
    def by_dialect(self, dialect: str) -> List[GraphNode]: ...

class CandidateMapping(BaseModel):
    target_field: str
    target_type: str
    source_node_ids: List[str]
    source_expression: str
    rationale: str
    grain: List[str]
    cardinality: Optional[Literal["1:1","M:1","1:M","M:M"]]
    rule_baseline: bool
    refined_by_llm: bool

class CandidateMappings(BaseModel):
    target_table: str
    target_dataset: str
    rows: List[CandidateMapping]
    rule_baseline_summary: Dict[str, Any]
    status: StageStatus

class Transformation(BaseModel):
    target_field: str
    kind: Literal["derived","scd2","audit","surrogate_key","computed","filter"]
    logic: str
    inputs: List[str]
    rationale: str

class Transformations(BaseModel):
    rows: List[Transformation]
    scd_strategy: Optional[Literal["type1","type2","type3","none"]]
    audit_fields: List[str]
    idempotency_key: Optional[str]
    partition_field: Optional[str]
    status: StageStatus

class ValidationFinding(BaseModel):
    severity: Literal["info","warn","block"]
    target_field: Optional[str]
    rule: str
    message: str

class ConfidenceScore(BaseModel):
    target_field: str
    llm_score: float
    name_sim_score: float
    type_compat_score: float
    profile_overlap_score: Optional[float]
    fk_evidence_score: float
    final: float
    band: Literal["high","medium","low"]

class ValidationReport(BaseModel):
    scores: List[ConfidenceScore]
    findings: List[ValidationFinding]
    low_confidence_count: int
    block_count: int
    overall_band: Literal["high","medium","low"]
    status: StageStatus

class GateDecision(BaseModel):
    name: Literal["gate1_metadata","gate2_validation"]
    decision: Literal["pending","approved","rejected","refine"]
    reviewer: Optional[str]
    notes: Optional[str]
    refine_target_stage: Optional[Literal["L1","L2","L3","L4","L5"]]
    refine_feedback: Optional[str]
    decided_at: Optional[datetime]

class StmBlackboard(BaseModel):
    session_id: str
    target_table: str
    target_dataset: str
    dialect_target: Literal["bigquery"]
    selected_source_profiles: List[str]
    intent: IntentArtifact
    metadata_graph: MetadataGraph
    candidate_mappings: CandidateMappings
    transformations: Transformations
    validation: ValidationReport
    stm_result: Optional[Dict[str, Any]]
    gates: Dict[str, GateDecision]
    current_stage: Literal["L1","L2","L3","L4","L5","L6","done","failed"]
    refine_feedback_pending: Dict[str, str] = {}    # stage -> feedback text
```

### Persistence tables (alembic migration)

```sql
CREATE TABLE stm_sessions (
  session_id        TEXT PRIMARY KEY,
  status            TEXT NOT NULL,
  current_stage     TEXT NOT NULL,
  target_table      TEXT NOT NULL,
  target_dataset    TEXT NOT NULL,
  source_profiles   TEXT NOT NULL,
  intent_source     TEXT NOT NULL,
  jira_issue_key    TEXT,
  raw_input         TEXT NOT NULL,
  blackboard_json   TEXT NOT NULL,
  created_at        TIMESTAMP NOT NULL,
  updated_at        TIMESTAMP NOT NULL,
  created_by        TEXT
);

CREATE TABLE stm_stage_events (
  event_id          TEXT PRIMARY KEY,
  session_id        TEXT NOT NULL REFERENCES stm_sessions(session_id),
  stage             TEXT NOT NULL,
  event_kind        TEXT NOT NULL,
  artifact_kind     TEXT,
  artifact_json     TEXT,
  confidence        REAL,
  llm_model         TEXT,
  llm_tokens_in     INTEGER,
  llm_tokens_out    INTEGER,
  duration_ms       INTEGER,
  message           TEXT,
  created_at        TIMESTAMP NOT NULL
);
CREATE INDEX idx_stm_stage_events_session ON stm_stage_events(session_id, created_at);

CREATE TABLE stm_gate_decisions (
  decision_id       TEXT PRIMARY KEY,
  session_id        TEXT NOT NULL REFERENCES stm_sessions(session_id),
  gate_name         TEXT NOT NULL,
  decision          TEXT NOT NULL,
  reviewer          TEXT,
  notes             TEXT,
  refine_target     TEXT,
  refine_feedback   TEXT,
  decided_at        TIMESTAMP NOT NULL
);
```

`profiles` (existing) gains `encrypted_credentials BYTEA`, `last_ping TIMESTAMP`, `last_ping_status TEXT`.

**Write rules:**
- Blackboard snapshot written to `stm_sessions.blackboard_json` on every stage terminal event (cheap: full doc, atomic).
- `stm_stage_events.artifact_json` holds **deltas only** for audit history.
- All writes within a session serialized through `SessionLock`.

---

## 5. Agent Contracts

### Common interface (`core/stm/agents/base.py`)

```python
class StmAgent(ABC):
    stage: Literal["L1","L2","L3","L4","L5","L6"]
    name: str

    @abstractmethod
    def applicable(self, bb: StmBlackboard) -> bool: ...

    @abstractmethod
    async def run(self, bb: StmBlackboard, ctx: AgentContext) -> BlackboardDelta: ...

class AgentContext(BaseModel):
    llm: LLMClient
    discovery_registry: Any
    bq: BQClient
    jira: JiraClient
    logger: Any
    model_overrides: Dict[str, str] = {}

class BlackboardDelta(BaseModel):
    artifact_kind: str
    artifact_payload: Any
    events_to_emit: List[Dict]
    confidence: Optional[float]
```

### L1 — IntentAgent

- Reads `bb.intent.raw_input`, `bb.intent.source`, `bb.intent.jira_issue_key`, `bb.refine_feedback_pending.get("L1")`.
- Writes full `IntentArtifact`.
- Applicable when `bb.intent.status in {idle, stale}`.
- Flow: Jira fetch (if source=jira) → single LLM JSON extraction call → parse into IntentArtifact.
- Model: `claude-haiku-4-5`.
- Failure: Jira 404 → status=failed; LLM JSON parse failure → retry once stricter, then failed.

### L2 — MetadataAgent

- Reads `bb.intent`, `bb.selected_source_profiles`, `bb.refine_feedback_pending.get("L2")`.
- Writes `MetadataGraph`.
- Applicable when intent ready and metadata_graph in {idle, stale}.
- Flow:
  1. Parallel source probing via `asyncio.gather` over each `selected_source_profile`. Per-source timeout 30s. Failures recorded as `coverage_notes`, do not abort.
  2. Build deterministic skeleton: `dialect → schema → table → column` nodes + `contains` edges + FKs as `fk` edges.
  3. LLM concept-linking call (single): given intent + flat column list across sources, emit `concept_link` edges with per-edge confidence.
  4. LLM cross-source join inference (same call or follow-up): emit `join_candidate` edges with confidence.
- Model: `claude-sonnet-4-6`.
- Failure: all sources unreachable → status=failed; any subset → continue, log coverage notes.

### Gate 1 — between L2 and L3

Coordinator stalls. Emits `gate_requested` SSE. UI renders graph + intent + coverage notes. Reviewer Approve / Reject / Refine(target=L1|L2, feedback).

### L3 — SemanticMappingAgent

- Reads everything previous + `bb.refine_feedback_pending.get("L3")` + gate1 notes.
- Writes `CandidateMappings`.
- Applicable when gate1 approved and candidate_mappings in {idle, stale}.
- Flow:
  1. Rule baseline: call `mapping_engine.build_stm(...)` over selected columns from the graph (target table inferred from intent.entity + bb.target_table). Each baseline row marked `rule_baseline=True`.
  2. LLM refinement (single Opus call): given intent, graph-as-JSON, baseline rows, optional gate1 feedback — confirm/correct each baseline row, add missing rows (joins, derived, lookups), mark grain + cardinality, provide rationale.
  3. Merge: shared rows → LLM wins on rationale/expression, baseline wins on type. Baseline-only → keep. LLM-only → mark `rule_baseline=False, refined_by_llm=True`.
- Model: `claude-opus-4-7`.

### L4 — TransformationAgent

- Reads candidate_mappings + intent + graph + `bb.refine_feedback_pending.get("L4")`.
- Writes `Transformations`.
- Flow:
  1. Rule baseline: `mapping_engine.infer_transform()` produces PII masking, type casts, timestamp normalization.
  2. LLM synthesis (Opus): derived columns, SCD2 logic (if dimension), audit fields, surrogate key strategy, filter logic from `intent.filters`, idempotency key, partition field.
- Model: `claude-opus-4-7`.

### L5 — ValidationAgent

- Reads everything previous.
- Writes `ValidationReport`.
- Flow (no LLM):
  1. Per candidate mapping compute heuristics: name similarity (embedding cosine or Levenshtein), type compatibility (rule lookup), profile overlap (if sample data available, else None), FK evidence (graph lookup).
  2. Combine with LLM-reported scores from L3/L4: `final = 0.4*llm + 0.25*name_sim + 0.2*type_compat + 0.1*fk + 0.05*profile` (weights in config).
  3. Run deterministic rule checks → findings: type incompat→block, nullable→non-null without default→warn, PII unclassified→warn, missing idempotency on dim→warn, SCD2 declared without effective_from/to→block.
  4. Bands: `>=0.85→high`, `0.65–0.85→medium`, `<0.65→low`. Overall = low if any block; else lowest band present.

### Gate 2 — between L5 and L6

Same shape as gate 1. UI shows score table + findings. Reviewer Approve / Reject / Refine(target=L1..L5, feedback).

### L6 — StmBuilderAgent

- Reads everything (gates approved).
- Writes `stm_result` (dict form of MappingResult).
- Flow: compose MappingResult from approved blackboard, register in existing `_STM_STORE` for compat, render xlsx/csv. Optional Jira write-back (if `intent.source=jira` and `STM_JIRA_WRITEBACK_ENABLED=true`).

### Coordinator dispatch loop

```python
async def coordinator_loop(session_id):
    while True:
        async with SessionLock(session_id):
            bb = await load_blackboard(session_id)
            if bb.current_stage in {"done","failed"}: return
            agent = next_applicable_agent(bb)   # respects gate stalls
            if agent is None:
                if needs_gate(bb):
                    await emit_gate_request(bb); await wait_for_gate_decision(bb)
                    continue
                await asyncio.sleep(0.2); continue
        try:
            delta = await agent.run(bb, ctx)
            async with SessionLock(session_id):
                merge_delta(bb, delta); await persist_blackboard(bb); await emit_events(delta)
        except Exception as exc:
            await mark_failed(session_id, agent.stage, exc); return
```

---

## 6. Refinement, Gates, SSE

### Gate lifecycle

1. Coordinator detects need for gate → writes GateDecision(pending), inserts `stm_gate_decisions` row (pending), emits `gate_requested` SSE, parks task on `asyncio.Event`.
2. UI calls `POST /api/stm/sessions/{id}/gates/{gate}/decide` with decision payload.
3. Endpoint validates state (409 if gate not actually awaiting), updates DB + blackboard, sets the asyncio.Event, emits `gate_decided` SSE.
4. Coordinator resumes.

### Refinement invalidation

When decision = refine with `refine_target_stage = Lk`:
- Mark `Lk` and all downstream artifacts as `stale`.
- Clear gate decisions for any gate sitting between Lk and end (set back to pending).
- Stash `refine_feedback` into `bb.refine_feedback_pending[Lk]`.
- Set `bb.current_stage = Lk`.

Agent at Lk reads `refine_feedback_pending[Lk]` on next run, incorporates into prompt/logic, clears on completion.

Gate1 can target L1 or L2 only. Gate2 can target L1 through L5.

### Concurrency safety

Single coordinator task per session. `SessionLock` (asyncio.Lock per session_id) serializes all blackboard writes between coordinator and gate API. 10s lock acquire timeout → 503 to caller, coordinator retries next tick.

### Rejection

Reject = terminal: `status=rejected`, coordinator exits. Retry via `POST /sessions/{id}/clone` which creates a fresh session seeded from this one.

### SSE event types

```
stage_started      {session_id, stage, ts}
llm_call           {session_id, stage, model, tokens_in, tokens_out}
profile_probe      {session_id, profile_id, ok, table_count, duration_ms}
stage_ready        {session_id, stage, confidence_summary}
stage_failed       {session_id, stage, error}
gate_requested     {session_id, gate, payload_summary}
gate_decided       {session_id, gate, decision, refine_target?, refine_feedback?}
stage_stale        {session_id, stage}
session_completed  {session_id, stm_id}
session_rejected   {session_id, by_gate}
session_failed     {session_id, error}
```

UI subscribes via `GET /api/stm/sessions/{id}/events`.

---

## 7. Multi-Dialect Source Providers

### Interface (`core/discovery/base.py`)

```python
class SourceProvider(ABC):
    dialect: Literal["postgres","oracle","mysql","mssql","bigquery"]

    @abstractmethod
    async def ping(self, profile) -> PingResult: ...
    @abstractmethod
    async def list_schemas(self, profile) -> List[str]: ...
    @abstractmethod
    async def list_tables(self, profile, schema) -> List[TableInfo]: ...
    @abstractmethod
    async def get_columns(self, profile, schema, table) -> List[ColumnInfo]: ...
    @abstractmethod
    async def get_foreign_keys(self, profile, schema, table) -> List[FKInfo]: ...
    @abstractmethod
    async def profile_column(self, profile, schema, table, column, sample_rows=0) -> ColumnProfile: ...
    @abstractmethod
    async def search_by_keywords(self, profile, keywords, limit=50) -> List[ColumnHit]: ...
```

Sync drivers wrapped with `asyncio.to_thread`. Per-profile connection pool size from `STM_POOL_SIZE` env (default 4).

### Provider modules

| Dialect | Module | Driver | Notes |
|---|---|---|---|
| postgres | `postgres_provider.py` | psycopg2 (existing) | refactor sync to async wrapper |
| oracle | `oracle_provider.py` | `oracledb` thin mode | ALL_TABLES / ALL_TAB_COLUMNS / ALL_CONSTRAINTS |
| mysql | `mysql_provider.py` | `pymysql` | INFORMATION_SCHEMA |
| mssql | `mssql_provider.py` | `python-tds` (pure Python) | INFORMATION_SCHEMA + sys.foreign_keys |
| bigquery | `bigquery_provider.py` | google-cloud-bigquery (existing) | wraps `core/bq_client.py` |

### Profile management

New POST endpoints under `routers/discovery.py`:

```
POST /api/discovery/profiles/oracle    {label, dsn, user, pass}
POST /api/discovery/profiles/mysql     {label, host, port, db, user, pass}
POST /api/discovery/profiles/mssql     {label, host, port, db, user, pass}
POST /api/discovery/profiles/bigquery  {label, project_id, credentials_json?}
```

Credentials encrypted with Fernet using `STM_PROFILE_ENCRYPTION_KEY` env. Stored in new `encrypted_credentials BYTEA` column. **TODO: migrate to secrets manager before public-cloud production deploy.**

### Caching

`core/discovery/cache.py` — 15-minute in-memory TTL on `(profile_id, method, args_hash)`. Refinement at L2 can pass `bypass_cache=True`. Process-local; future Redis migration.

### New dependencies (`requirements.txt`)

```
oracledb>=2.0
pymysql>=1.1
python-tds>=1.13
cryptography>=42
```

### Test infrastructure

`docker-compose.test-sources.yml` spins Oracle XE, MySQL, MSSQL with seeded CRM schemas mirroring Postgres demo. Used by integration tests; optional in local dev. Skip integration tests in CI if containers absent.

---

## 8. UI Flow

### Single-page stepper in `ui/mapping_compose_react.html`

Loaded with `?mode=agentic&session=<id>`. Existing rules-mode UI untouched (no `?mode=` param).

```
┌────────────────────────────────────────────────────────────────────────────┐
│  STM Session  ●─●─●─◌─◌─◌    Sess: 9f2a   Target: warehouse.customer_dim  │
│   Confidence: medium   Status: awaiting_review (gate 1)                    │
├──────┬─────────────────────────────────────────────────────────────────────┤
│ L1●  │  ▼ L1 Intent              [ready]  haiku 1.2s                       │
│ L2●  │     entity: customer_dim, action: create, dimension: yes            │
│ G1◌  │  ▼ L2 Metadata            [ready]  sonnet 4.7s                      │
│ L3◌  │     5 sources probed (4 ok, 1 timeout)                              │
│ L4◌  │     27 nodes, 41 edges, 8 join candidates                           │
│ L5◌  │     [ View knowledge graph ▸ ]                                      │
│ G2◌  │  ▼ Gate 1 — Approve metadata scope    [AWAITING REVIEW]             │
│ L6◌  │     [ Approve ]  [ Refine ▾ ]  [ Reject ]                           │
└──────┴─────────────────────────────────────────────────────────────────────┘
```

**Stepper rail**: per-stage dot (●=ready, ◌=pending, ◐=running, ◇=stale, ✕=failed).

**Per-stage expander**: status + duration + model + tokens + headline artifact + "Why?" drawer with rationale.

**Knowledge graph view**: extend `agents/svg_generator.py` pattern to render `MetadataGraph` as `dialect → schema → table → column` clusters; edges color-coded by kind.

**Validation view**: per-row table with final score (banded color), expandable subscore breakdown, findings list below severity-colored.

**Refinement panel**: target stage dropdown + feedback textarea + submit.

**Final-actions bar (after L6)**: Download xlsx / csv / Post to Jira / Clone session.

### Session creation flow

1. `/ui/pages/mappings.php` → "New agentic session" → modal.
2. Modal: source profile multi-select + target dataset/table + intent tab (Jira / free-text).
3. Submit → `POST /api/stm/sessions` → response `{session_id}`.
4. Redirect to `?mode=agentic&session=<id>`.
5. UI opens SSE, renders.
6. Page reload hydrates via `GET /api/stm/sessions/<id>`.

### REST endpoints

```
POST   /api/stm/sessions
GET    /api/stm/sessions
GET    /api/stm/sessions/{id}
GET    /api/stm/sessions/{id}/events           (SSE)
POST   /api/stm/sessions/{id}/gates/{gate}/decide
POST   /api/stm/sessions/{id}/clone
GET    /api/stm/sessions/{id}/graph.svg
GET    /api/stm/sessions/{id}/export.xlsx
GET    /api/stm/sessions/{id}/export.csv
GET    /api/stm/sessions/{id}/timeline         (debug — list events)
GET    /api/stm/sessions/{id}/cost_summary     (LLM token rollup)

POST   /api/discovery/profiles/oracle
POST   /api/discovery/profiles/mysql
POST   /api/discovery/profiles/mssql
POST   /api/discovery/profiles/bigquery
```

Existing `POST /api/stm/generate` (rule-based one-shot) **unchanged**.

---

## 9. Error Handling & Resume

### Error taxonomy

| Class | Stages | Handling |
|---|---|---|
| External API failure (Jira/BQ/source DB) | L1, L2, L6 | Retry 3× backoff 1/3/9s. Then stage_failed, coordinator stops. |
| LLM provider failure | L1–L4 | Retry once. On JSON parse error, retry once with stricter prompt. Then stage_failed. |
| Validation block | L5 | Not an error — `findings[severity=block]`. Stage ready. Gate 2 decides. |
| Bad input | session create | 400 at API boundary before insert. |
| Coordinator crash mid-stage | any | Recovery on app startup (below). |
| Gate decision against wrong state | gate API | 409 conflict. |
| Refinement target invalid | gate API | 400. |
| Lock contention | any | 10s lock timeout → 503. Coordinator retries. |

### Recovery on startup (`recover_sessions`)

```python
async def recover_sessions(db):
    for row in await db.execute("SELECT session_id, current_stage FROM stm_sessions WHERE status='running'"):
        if has_orphaned_started_event(row.session_id):
            mark_stage_failed(row.session_id, row.current_stage, "Worker crashed mid-stage")
            # Do NOT auto-restart — user can clone-to-retry or refine.
        else:
            asyncio.create_task(coordinator_loop(row.session_id))
```

Awaiting-review sessions need no restart — the asyncio.Event is recreated lazily when the decision arrives.

### Observability

- `stm_stage_events` IS the audit log.
- Structured JSON logging to stdout with agent / stage / session_id.
- `GET /api/stm/sessions/{id}/timeline` — events list.
- `GET /api/stm/sessions/{id}/cost_summary` — LLM token rollup with USD estimate.

---

## 10. Testing Strategy

### Unit tests (`tests/stm/unit/`)

- `test_intent_agent.py` — fixture Jira story + fixture free-text, mocked LLM
- `test_metadata_agent.py` — mocked providers, graph assembly, "Oracle timeout + others succeed" path
- `test_semantic_agent.py` — fixture graph, mocked LLM refinement, baseline merge
- `test_transform_agent.py` — SCD2 dimension, audit fields, filter translation
- `test_validation_agent.py` — purely deterministic, no mocks
- `test_builder_agent.py` — MappingResult composition + xlsx render

### Coordinator integration (`tests/stm/integration/`)

- `test_coordinator_happy_path.py` — L1→L6 with both gates auto-approved
- `test_refinement_loop.py` — gate1 refine(L2), assert downstream stale + rerun in order
- `test_rejection.py` — terminal status, blackboard preserved
- `test_recovery.py` — orphaned event → marked failed
- `test_gate_race.py` — concurrent gate decision + coordinator tick → lock serializes

### Provider contract (`tests/discovery/`)

- `test_provider_contract.py` — abstract test class run against each provider, ensures interface parity.
- Per-dialect tests skip in CI if docker-compose containers absent.

### E2E (`tests/e2e/`)

- `test_stm_session_full.py` — recorded LLM cassettes via vcrpy; one Jira-source scenario + one free-text-source scenario.

### Test doubles

- `tests/fixtures/llm_cassettes/` — recorded JSON per stage per scenario.
- `tests/fixtures/source_schemas/` — JSON dumps of probe responses per dialect.
- `FakeLLMClient` plays cassettes.

---

## 11. Rollout Plan

Ship incrementally (purely additive — existing `POST /api/stm/generate` undisturbed throughout):

1. **Migration**: alembic adds the 3 STM tables + `profiles` columns.
2. **Source providers**: Postgres + BigQuery first (mostly refactor), then Oracle / MySQL / MSSQL. Profile ping UI exposes per-dialect status.
3. **Coordinator skeleton**: L1 + L6 pass-through (empty middle), so session lifecycle + SSE + persistence work end-to-end.
4. **L2 Metadata + Gate 1**: enables first real reasoning + first checkpoint.
5. **L3 Semantic + L4 Transform**: full mapping reasoning.
6. **L5 Validation + Gate 2**: confidence scoring + second checkpoint.
7. **Refinement loop**: gate1 first, then gate2.
8. **Jira write-back**: flag-gated, opt-in.

Each step is shippable to demo independently.

---

## 12. Environment Variables (new)

```
STM_PROFILE_ENCRYPTION_KEY=<fernet-key>         # required for any non-postgres profile
STM_POOL_SIZE=4                                  # per-profile connection pool size
STM_JIRA_WRITEBACK_ENABLED=false                 # opt-in Jira comment + transition at L6
STM_LLM_MODEL_L1=claude-haiku-4-5                # overridable per stage
STM_LLM_MODEL_L2=claude-sonnet-4-6
STM_LLM_MODEL_L3=claude-opus-4-7
STM_LLM_MODEL_L4=claude-opus-4-7
STM_VALIDATION_WEIGHTS=0.4,0.25,0.2,0.1,0.05     # llm,name,type,fk,profile
STM_VALIDATION_LLM_EXPLAIN=false                 # optional LLM finding explainer
STM_PROBE_TIMEOUT_SEC=30
STM_METADATA_CACHE_TTL_SEC=900
```

---

## 13. Out of Scope (Explicit Non-Goals)

- Edit-inline at gates (only Approve / Reject / Refine-with-feedback in v1)
- LLM second-opinion confidence pass in L5
- Multi-tenant isolation for STM sessions (single namespace for now)
- Redis-backed cache (in-memory only)
- Secrets manager integration (Fernet+env-key for now)
- Multi-worker uvicorn (single-worker assumed; SessionLock abstraction in place)
- WebSocket bi-directional control (SSE one-way only)
- Dedicated `ui/pages/stm_session.php` page (stepper in `mapping_compose_react.html` for v1)
- Auto-restart on coordinator crash (user re-runs via clone/refine)

---

## 14. Why This Architecture

The mental model articulated upfront — "progressive certainty engine," "state transition architecture," "Human + AI Co-pilot" — maps directly onto the chosen shape:

- **Progressive certainty** = each stage writes to the blackboard with a defined contract; downstream stages consume more-structured artifacts than they would have from raw input. L3 sees a knowledge graph, not free-text Jira.
- **State transition architecture** = `current_stage` + `StageStatus` per artifact is the state machine. Every transition is an event row. Resume is "read state, dispatch eligible agent."
- **Human + AI co-pilot** = two explicit gates, refinement with feedback, deterministic floor (`build_stm`) under every LLM call. Reviewer is always in the driver's seat for irrevocable decisions.
- **Multi-agent collaborative reasoning** = each layer owns one cognitive responsibility; no single mega-prompt.
- **Excel is a rendered view, not the intelligence** = `MappingResult` is composed from the blackboard at the very end. The blackboard IS the product; xlsx is one renderer.
