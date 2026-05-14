# Enterprise Mapping Refactor — Frontier → Verizon

**Date:** 2026-05-14
**Status:** Approved design, ready for implementation planning
**Supersedes:** `2026-05-11-stm-agentic-evolution-design.md` (for everything beyond the per-session 4-stage core)
**Related:** Commit `e52a3c3` — 4-stage source-first pipeline live; this design layers catalog discovery, batching, vector recall, and a ZealPHP UI on top.

## Context

Verizon migration ingests Frontier source schemas into the BigQuery `vz-agentic-198889.buildemo` dataset (and siblings). Real catalog scale: thousands of source tables, hundreds-to-thousands of target tables, full column-level Source-to-Target Mappings (STMs) required with business logic, transformation rules, and per-row confidence. The current 4-stage per-session pipeline is correct for one source table at a time but doesn't address discovery, batching, or thousand-table recall, and the existing PHP UI was never designed for enterprise reviewer throughput.

This refactor is additive on the backend (one rewrite + several new layers) and a complete teardown + rebuild of the UI on ZealPHP (sibidharan/zealphp, ext-openswoole based).

## Mental model

> The 4-stage per-session pipeline (L1 schemas → L2 shortlist → [G1] → L3 mapping → [G2] → L4 sql) becomes the **inner loop**. The outer loop is **catalog-first discovery + user-curated batches**, and the L2/L3 internals are reworked to scale to thousand-table targets via vector recall and per-column batched concurrency.

The reference artifact (`mapping-agent.jsx`, Claude artifact `81a47eb4-…`) supplies two patterns we adopt — *compact target representation* and *batched-per-column mapping with bounded concurrency* — and one pattern we deliberately deviate from: the artifact runs zero gates; we keep both Gate 1 and Gate 2 mandatory per session for enterprise review discipline.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ZealPHP UI                                                      │
│  ┌─────────────┬─────────────┬────────────┬──────────────────┐  │
│  │ Catalog     │ Batch       │ Session    │ Review Queue     │  │
│  │ Browser     │ Composer    │ Stepper    │ (Gate inbox)     │  │
│  └─────────────┴─────────────┴────────────┴──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│  FastAPI                                                         │
│  ┌──────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Discovery    │  │ Batch           │  │ Per-source         │  │
│  │ - Databricks │→ │ Orchestrator    │→ │ Coordinator        │  │
│  │   uploader   │  │ - fan-out       │  │ L1→L2→[G1]→L3→[G2] │  │
│  │ - BQ live    │  │ - quota/         │  │ →L4 (existing,     │  │
│  │ - Catalog    │  │   concurrency    │  │  L3 reworked)      │  │
│  │   cache      │  │ - queue model    │  │                    │  │
│  └──────────────┘  └─────────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
              │
        Postgres + pgvector: catalogs · batches · sessions · blackboards
                            · mapping_memory · target_table_embeddings
```

**New layers (additive):**
- `core/catalog/` — Databricks upload parser, BQ live fetcher, catalog cache, embedding indexer.
- `core/batch/` — batch orchestrator: takes N source tables, fans out to N coordinator runs, bounded concurrency.

**Rewritten:**
- `core/stm/agents/mapping_agent.py` (L3) — batched-per-column, concurrency-bounded, streams rows via SSE.

**Modified (small surgical changes):**
- `core/stm/agents/shortlist_agent.py` (L2) — add vector-recall branch; compact target representation `{table: "col1, col2, ..."}` instead of full column metadata in the LLM prompt.
- `core/stm/agents/schemas_agent.py` (L1) — read source side from catalog cache instead of inline upload; target side unchanged (already uses `BQClient.list_columns_in_dataset` after `e52a3c3`).
- `routers/stm_sessions.py` — accept `catalog_source_id` + `catalog_target_id` in addition to inline source/target.

**Stays untouched:**
- `coordinator.py`, `blackboard.py`, `persistence.py`, `events.py`, the two gates, SSE broker, BQClient, exporter, sql_agent, mapping_memory router, gates router, auth router.

**Deleted entirely:**
- All of `ui/` (`api.php`, `auth.php`, `config.php`, `dashboard.html`, `index.php`, `login.php`, `logout.php`, `mapping_compose_react.html`, `sse.php`, `svg.php`, `pages/`). Rebuilt fresh on ZealPHP.

## Data flow

```
1. DISCOVERY (sticky catalogs, cached by tenant)
   Source: Databricks INFO_SCHEMA xlsx/csv upload
           → core/catalog/uploader.py → catalogs.source rows
   Target: BQ INFO_SCHEMA live pull (existing BQClient.list_columns_in_dataset)
           → catalogs.target rows
   Both cached in Postgres so the user uploads/fetches once per refresh,
   not per session. Target catalog refresh also triggers re-embedding.

2. BATCH COMPOSITION (UI)
   User opens Catalog Browser → ticks N source tables → picks BQ dataset(s)
   → fills batch-level business_context (free-form)
   → optionally per-source override notes → submits.

3. BATCH SUBMIT (POST /api/stm/batches)
   Creates 1 batch row + N stm_sessions rows, each "queued".
   Returns batch_id.

4. FAN-OUT EXECUTION (BatchOrchestrator, asyncio)
   Pulls queued sessions, bounded by STM_MAX_PARALLEL_SESSIONS (default 4).
   Each session runs the existing L1→L2→[G1]→L3→[G2]→L4 in coordinator.py.
   Per-session SSE still works; new batch-level SSE rolls them up.

5. PER-SESSION INTERNALS
   L1  fetch source cols (from catalog cache) + target catalog (one
       BQClient call); already correct after the e52a3c3 fix.
   L2  TWO-STAGE SHORTLIST:
        (a) if target_table_count > STM_L2_RECALL_K (default 50):
            embed source table → pgvector top-K nearest target tables.
        (b) else: pass all target tables.
        Then 1 LLM call with compact target rep
        {table: "col1, col2, ..."} → shortlist 3–10 picks with evidence.
   G1  Gate 1 → review queue.
   L3  REWORKED: source cols in batches of STM_L3_BATCH_SIZE=12,
        per-session concurrency STM_L3_CONCURRENCY=2.
        Each batch call returns one row per source column with:
          target_table, target_column, mapping_type, transformation,
          business_logic, confidence, rationale, dq_rules[].
        Stream rows back via SSE as they land.
        mapping_memory recall: top-10 most-recent approved rows where
        source column name overlaps (Postgres trigram) prepended as
        few-shot context.
   G2  Gate 2 → review queue.
   L4  SQL bundle per shortlisted target (existing, untouched).

6. REVIEW QUEUE (UI)
   All pending gates across all batches in one inbox.
   Per-session approve/reject/refine — no bulk-approve.
   Hotkeys (j/k navigate, a approve, r reject, e edit) for throughput.

7. BATCH COMPLETION
   Batch is "done" when every session is done|rejected.
   Batch export: zip of per-target SQL + master STM xlsx
   (one sheet per source table + a provenance sheet).
```

**Concrete deviations from the artifact:**
1. L2 picks tables, L3 maps columns — kept the same split, but adopted the artifact's compact target representation in L2.
2. mapping_memory few-shot in L3 — artifact has none.
3. Two-stage shortlist (vector recall → LLM rank) for thousand-table scale — artifact assumes one dataset.
4. Both gates mandatory — artifact has none.

## UI surfaces (ZealPHP)

Five screens. Server-rendered via ZealPHP routes; SSE for live updates; tiny vanilla-JS islands for interactivity (no SPA framework). Aesthetic: editorial serif headings, mono body, dot-matrix tables.

### Routes

| Route | Screen | Purpose |
|---|---|---|
| `/catalog` | Catalog Browser | Upload/refresh + tick source/target tables. |
| `/batch/new` | Batch Composer | Review picks, target dataset, business context. |
| `/batch/{id}` | Batch Dashboard | SSE-live per-session progress table; export. |
| `/session/{id}` | Session Stepper | Per-source 4-stage detail; gate review. |
| `/queue` | Review Queue | Cross-batch pending-gate inbox with hotkeys. |

### Top bar (every page)

```
Vol. #1  MAPPING AGENT   | tenant ▾ | ⚑ 12 gates pending | ◐ done
```

### Catalog Browser layout

Split-pane. Left: source catalog (uploaded Databricks). Right: target catalog (live BQ). Filter, search, hover for column metadata, tick to select. Selection state lives in tenant session.

### Batch Composer layout

One-screen form: selected sources list, target dataset picker, batch-level business_context textarea, per-source override notes (collapsible). Submit POSTs to `/api/stm/batches`, redirects to `/batch/{id}`.

### Batch Dashboard layout

SSE-driven table: one row per session showing stage progress, status, gate state, action link. Export-zip button enabled when batch reaches `done`.

### Session Stepper layout

Four collapsible sections (§01 Schemas, §02 Shortlist, §03 Mapping, §04 SQL). L3 streams rows live. Inline refine action at each gate.

### Review Queue layout

Vertical list of pending gates across all batches, newest first. Each row: batch + source + gate name + summary (n picks / n rows / avg confidence). Hotkeys: `j`/`k` navigate, `a` approve, `r` reject, `e` open inline editor, `→` open session.

### API surface added

```
POST   /api/catalogs/source                upload Databricks INFO_SCHEMA dump
GET    /api/catalogs/source                list cached source catalogs
POST   /api/catalogs/target/refresh        live BQ INFO_SCHEMA pull (re-embeds)
GET    /api/catalogs/target                list cached target catalogs
POST   /api/stm/batches                    submit a new batch
GET    /api/stm/batches/{id}               batch summary
GET    /api/stm/batches/{id}/events        batch-level SSE
GET    /api/stm/batches/{id}/export.zip    consolidated export
GET    /api/gates/pending                  cross-batch pending gates
```

Existing `/api/stm/sessions/*` endpoints stay unchanged.

## Scaling

### Context-window budget per LLM call

Hold prompts to ≤15k tokens.

| Stage | Prompt size | Strategy |
|---|---|---|
| L2 shortlist | ~6k tok | Compact target rep (table → CSV column list). Vector recall narrows large catalogs before LLM. |
| L3 mapping batch | ~4k tok | 12 source cols + only the *picked* target tables (3–10) with full column metadata. |
| L4 SQL | ~2k tok | One picked target + its mapping rows. |

### Two-stage shortlist

**Index phase** (on target-catalog refresh):
- For each target table, embed `table_name + " | " + ", ".join(col_name + ":" + col_desc)` as one document.
- Provider: Voyage AI `voyage-3-lite` (1024-dim, $0.02/M tok). Behind a provider abstraction (`core/catalog/embedding_providers/`).
- Persist in `target_table_embeddings(catalog_id, table_name, embedding vector(1024), text_repr text, embedded_at)`.

**Query phase** (every L2 invocation):
- Embed the source table the same way → 1 query vector.
- pgvector `ORDER BY embedding <=> :q LIMIT :k` → top-K candidates (`STM_L2_RECALL_K=50`).
- Feed those 50 to the LLM with compact rep; LLM picks final 3–10 with evidence.

**Fallback:** if `target_table_count <= STM_L2_RECALL_K`, skip recall — send all tables directly to the LLM (preserves the simple path for small catalogs).

### Concurrency knobs

| Knob | Default | Rationale |
|---|---|---|
| `STM_MAX_PARALLEL_SESSIONS` | 4 | Tier-2 RPM headroom: 4 × ~6 calls = 24 inflight/min. |
| `STM_L3_BATCH_SIZE` | 12 | Amortizes target-schema overhead; output stays bounded. |
| `STM_L3_CONCURRENCY` | 2 | Per-session in-flight L3 calls. Max 8 mapping calls inflight. |
| `STM_L2_RECALL_K` | 50 | Top-K candidates from pgvector before LLM ranks. |
| `STM_EMBEDDING_PROVIDER` | voyage | `voyage` \| `openai` \| `local`. |
| LLM retries | 3 | Exponential backoff on 429/529 (existing). |

### Cost back-of-envelope

One source table, 44 columns, 5 picked targets:
- L1: BQ INFO_SCHEMA query only — $0
- L2: 1 call, ~6k in / 1k out — $0.021
- L3: ⌈44/12⌉ = 4 calls, ~4k in / 2k out each — $0.108
- L4: 5 calls, ~2k in / 2k out each — $0.090

**≈ $0.22 per source table.** Batch of 50 ≈ $11. Catalog of 1,000 ≈ $220. Linear.

Embedding costs (one-time per catalog refresh):
- 1,000 tables → $0.001
- 10,000 tables → $0.01
- 100,000 tables → $0.10

### Failure modes

| Failure | Behavior |
|---|---|
| LLM 429 / 529 | Existing retry with exponential backoff, 3 attempts. |
| LLM returns invalid JSON | Stage marked `failed`. Reviewer can refine. |
| BQ INFO_SCHEMA timeout | L1 fails loudly (per `e52a3c3` fix), retryable from L1. |
| Bad upload (missing columns) | Validation at upload time, rejected before batch submit. |
| Catalog staleness | Target cache TTL 1 hr; UI shows age + refresh button. |
| Voyage AI quota | Fallback provider via env switch. |
| 50-table batch hits rate limit | Concurrency knobs conservative; per-tenant middleware if observed. |
| Frontier sources lack descriptions | Uploader supports manual annotation; type-only matching with confidence penalty otherwise. |

### mapping_memory at scale

- Schema already exists (Phase A, 2026-05-14).
- Recall query at L3: top-10 most-recent approved rows where source column name overlaps (Postgres trigram). Adds ~1k tokens to L3 prompt.
- No eviction needed for v1 (50 source tables × 44 cols = ~2,200 rows per batch; 100 batches = 220k rows, well within Postgres).
- Filter by `source_table_name` trigram similarity before passing to L3 prompt to keep noise low.

### Non-goals

- Cross-batch parallel orchestration (batches sequential at orchestrator level for v1).
- Auto-approval by confidence threshold (both gates mandatory per requirement).
- Multi-tenant isolation beyond platform default.
- Auth/JWT changes.
- WebSocket transport (SSE sufficient).
- Backwards-compatibility shim for the deleted PHP UI.

## Rollout

### Delete list

```
ui/                              ALL          ← rebuild on ZealPHP
core/stm/agents/mapping_agent.py REWRITE      ← batched per-column
```

Nothing else is deleted.

### Phase ordering (~9 working days)

```
Phase 1 — Foundation                                        ~2 days
 ├─ alembic: pgvector extension + catalogs/* tables +
 │           target_table_embeddings + batches table
 ├─ core/catalog/uploader.py (Databricks xlsx → catalog rows)
 ├─ core/catalog/bq_refresh.py (live BQ INFO_SCHEMA → catalog rows)
 └─ routers/catalogs.py (upload + refresh + list endpoints)

Phase 2 — Batch + L3 rework                                 ~2 days
 ├─ core/batch/orchestrator.py (fan-out, bounded concurrency)
 ├─ routers/batches.py (submit + dashboard + SSE)
 └─ core/stm/agents/mapping_agent.py REWRITE
       - batched 12 cols, concurrency=2
       - stream rows via SSE
       - mapping_memory few-shot

Phase 3 — Vector recall                                     ~1 day
 ├─ core/catalog/embeddings.py
 ├─ core/catalog/embedding_providers/{voyage,openai,local}.py
 ├─ L2 wiring: skip-or-recall branch, top-K=50
 └─ background reindex on catalog refresh

Phase 4 — ZealPHP UI                                        ~3 days
 ├─ tear down ui/
 ├─ scaffold ZealPHP app: routes for /catalog /batch/new
 │  /batch/{id} /session/{id} /queue
 ├─ SSE consumer for live updates
 ├─ Review Queue with hotkeys
 └─ editorial design language (serif/mono, dot tables)

Phase 5 — Verify + cutover                                  ~1 day
 ├─ smoke: 50-source batch against vz-agentic-198889.buildemo
 ├─ docker compose up — full stack boots clean
 └─ retire any leftover legacy stubs
```

Phases 1–3 are backend-only and smoke-testable with curl before Phase 4 starts.

### Done criteria

A batch of 50 source tables against `vz-agentic-198889.buildemo` runs end-to-end and:

1. Catalog browser shows all uploaded Databricks tables + live BQ targets.
2. Batch composer creates the batch in one click; SSE dashboard updates live.
3. Bounded concurrency holds (≤4 sessions, ≤8 L3 calls, ≤24 LLM calls/min) — observed under load.
4. Both gates trigger per session; Review Queue inbox shows them all; hotkeys work.
5. Vector recall kicks in when `target_table_count > 50`; bypass works below.
6. Master STM xlsx + zip of per-target SQL downloadable when all sessions are `done`.
7. Total batch cost within ±20% of $11 estimate.
8. Total wall-clock under 40 min.
9. mapping_memory grows during the batch; later sessions show few-shot recall context in L3 prompts.
10. `git grep -l 'php' ui/` returns 0 results.

## Environment

New env vars (add to `.env.example`):

```
# Embeddings
VOYAGE_API_KEY=<voyage-ai-key>
STM_EMBEDDING_PROVIDER=voyage           # voyage | openai | local
STM_L2_RECALL_K=50

# Concurrency
STM_MAX_PARALLEL_SESSIONS=4
STM_L3_BATCH_SIZE=12
STM_L3_CONCURRENCY=2

# Catalog
STM_CATALOG_TARGET_TTL_SECONDS=3600
```

## Open decisions

- **Embedding provider default**: voyage-3-lite specified, but if Verizon prohibits non-Google/non-Anthropic vendors, default to `local` (sentence-transformers via Python) with a documented model.
- **ZealPHP version pin**: pin a tagged release in `composer.json` to avoid drift; track via Renovate.
- **Per-tenant rate limit middleware**: deferred to post-launch; add only if 50-table batch trips Anthropic's limit in practice.

## References

- Reference artifact: Claude artifact `81a47eb4-ced4-4333-a2fd-2354f9faeef1` (the React mapping-agent.jsx mockup)
- Working copies: `~/Downloads/Mapping Agent Mock Up/{mapping-agent.jsx, Target Information Schema.xlsx, device_activation_event_source.xlsx, Information schema query.txt}`
- Prior architecture spec: `docs/superpowers/specs/2026-05-11-stm-agentic-evolution-design.md`
- L1 BQ fix: commit `e52a3c3`
- ZealPHP: github.com/sibidharan/zealphp
