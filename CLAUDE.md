# CLAUDE.md

Guidance for Claude when working in this repo.

## Project identity

**SQL-Gen V2** — multi-tenant SaaS platform that turns Jira stories + source-system schemas into governed Source-to-Target Mappings (STMs) for data engineering teams. Currently FastAPI backend + React-in-HTML + PHP front, SQLite/Postgres state, Docker compose for local.

## Mental model — read before designing

The system is **not** an LLM-wrapper that turns prompts into Excel. It is a **progressive certainty engine**: each stage receives incomplete information, enriches it, reduces ambiguity, increases confidence, and hands a more structured artifact to the next stage.

Internalize the six layers (live in `core/stm/` after the agentic evolution lands):

1. **Intent Extraction** — business intent from Jira / free-text
2. **Metadata Intelligence** — knowledge graph across all source dialects + BQ target
3. **Semantic Mapping** — candidate field mappings, rules-grounded then LLM-refined
4. **Transformation Synthesis** — derived columns, SCD, audit, filters, idempotency
5. **Validation & Governance** — deterministic confidence + rule-based findings
6. **STM Generation** — composed `MappingResult` rendered to xlsx/csv

Two human-governance checkpoints: **Gate 1** after L2, **Gate 2** after L5. Reviewer can Approve / Reject / Refine-with-feedback (which marks downstream stale and reruns).

The xlsx output is a **rendered view** of the reasoning. The blackboard (shared session state) IS the product.

## Code map

```
agents/                  # original 4-agent pipeline (requirements → mapping → engineering → QA)
  agent_1_requirements.py
  agent_2_mapping.py     # legacy single-shot LLM mapping (separate track from core/stm)
  agent_3*_*.py          # engineering sub-agents (sql gen, code conv, DQ, observability, metadata)
  agent_4_qa.py
  shared/                # jira_client, github_client, rovo_connector
  svg_generator.py

core/
  stm/                   # mapping intelligence (deterministic today, agentic after evolution)
    mapping_engine.py    # rule-based build_stm() — keep as L3 deterministic floor
    exporter.py          # xlsx/csv rendering — L6 uses this
  discovery/             # source-system providers (Postgres real; Oracle/MySQL/MSSQL/BQ to add)
    postgres_provider.py
    profiles.py          # connection profile registry
  bq_client.py / bq_cli.py # BigQuery wrapper
  orchestrator.py        # legacy pipeline orchestrator
  pipeline/orchestrator.py # multi-tenant platform PipelineOrchestrator
  gates/engine.py        # human-in-loop gate engine (asyncio.Event pattern)
  artifacts/postgres.py  # ArtifactStore for the platform pipeline
  engine/                # ExecutionEngine + AsyncioEngine + agent registry
  models/                # SQLAlchemy models (platform + tenant)
  auth/, tenant/         # multi-tenant infra (JWT, middleware, provisioner)
  schemas.py             # Pydantic data contracts shared across agents
  llm_client.py          # Claude API wrapper (uses anthropic SDK)

routers/                 # FastAPI routers — auth, gates, discovery, stm, pipelines
app.py                   # FastAPI factory
main.py / pipeline.py    # CLI entry points
ui/
  mapping_compose_react.html  # React-in-HTML mapping composer (gains ?mode=agentic stepper)
  sse.php                # SSE proxy (reused for STM session events)
  pages/                 # PHP page shells: requirements, mappings, qa, engineering, pipelines
  index.php / config.php / api.php

alembic/                 # migrations
docker-compose.yml       # local stack
docs/superpowers/specs/  # design specs (start here for in-flight initiatives)
```

## In-flight evolution

**STM Agentic Evolution** — full 6-layer reasoning pipeline inside `core/stm/` with stage-as-agent + shared blackboard, multi-dialect source providers (Postgres, Oracle, MySQL, MSSQL, BQ → BigQuery), ensemble confidence scoring, two governance gates, SSE live progress, refinement-with-rerun.

Spec: `docs/superpowers/specs/2026-05-11-stm-agentic-evolution-design.md`. Implementation plan to follow.

Until implemented, treat `core/stm/mapping_engine.py` as the live mapping engine and `agents/agent_2_mapping.py` as a parallel legacy track.

## Conventions

- **Schemas** — all cross-module data contracts in `core/schemas.py` (Pydantic). New STM blackboard models will live in `core/stm/blackboard.py`.
- **LLM** — single client at `core/llm_client.py`. Per-stage model selection via env (`STM_LLM_MODEL_L1..L4`). Default model family: Claude 4.X.
- **State** — STM uses dedicated tables (`stm_sessions`, `stm_stage_events`, `stm_gate_decisions`); platform pipeline uses `pipeline_runs` + `artifacts`. Don't conflate.
- **Async** — FastAPI + asyncio.Task for coordinator loops. Sync DB drivers wrapped with `asyncio.to_thread`.
- **Gates** — `core/gates/engine.py` uses `asyncio.Event` for human approval. STM coordinator follows the same pattern.
- **Locking** — `SessionLock` abstraction (asyncio.Lock for v1). Single-worker uvicorn assumed; multi-worker requires DB advisory locks (deferred).
- **Rules-as-floor** — when adding LLM reasoning, run the deterministic rule engine first and let the LLM refine; never let LLM-only output ship without a rule baseline.

## What to do when the user asks for STM changes

1. Check the spec first: `docs/superpowers/specs/2026-05-11-stm-agentic-evolution-design.md`.
2. Existing path (`POST /api/stm/generate`, rule-based) stays untouched; new agentic flow lives at `POST /api/stm/sessions`.
3. Don't reach into `agents/agent_2_mapping.py` for STM work — it's a separate track.
4. Mapping intelligence lives in `core/stm/`. UI changes go in `ui/mapping_compose_react.html` (agentic stepper) gated by `?mode=agentic`.

## Don't

- Don't write new docs/READMEs unless explicitly asked.
- Don't add emojis to code or commits.
- Don't break the existing `POST /api/stm/generate` rule-based path — many demos depend on it.
- Don't introduce a graph database, Redis, or a secrets manager in this iteration — explicit non-goals in the spec.
- Don't run `agents/agent_2_mapping.py` from STM code paths — separate track.

## Running locally

```bash
docker compose up                # FastAPI + Postgres demo + PHP front
alembic upgrade head             # apply migrations
python main.py status            # list recent pipeline runs (legacy)
```

For STM agentic sessions (after evolution lands): create a session via the agentic-mode UI or `POST /api/stm/sessions`, then watch progress in the stepper. SSE stream at `/api/stm/sessions/{id}/events`.

## Environment

Standard `.env` carries Anthropic key, Jira creds, BigQuery project. STM additions:
```
STM_PROFILE_ENCRYPTION_KEY=<fernet>
STM_POOL_SIZE=4
STM_JIRA_WRITEBACK_ENABLED=false
STM_LLM_MODEL_L1..L4=<claude model id>
```

See spec §12 for the full list.

## Memory

Auto-memory lives in `/Users/apple/.claude/projects/-Users-apple-Desktop-sql-gen/memory/`. Existing entry: `project_sql_gen.md` — 8-agent pipeline architecture. Update it when STM agentic evolution ships.
