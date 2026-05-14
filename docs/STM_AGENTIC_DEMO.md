# STM Agentic Evolution — Team Demo Guide

A 15-minute walkthrough of the new 6-layer agentic STM pipeline. Story: *we turned the rule-based STM generator into a progressive certainty engine with human governance.*

---

## TL;DR for the room

> "Until last week, STM was: prompt → Excel. Now it's a six-stage reasoning pipeline where each stage hands a richer, more confident artifact to the next, with two human checkpoints. The blackboard IS the product. The Excel is just the rendered view."

The six layers:

| # | Stage | What it does |
|---|-------|--------------|
| L1 | Intent Extraction | Jira/free-text → structured business intent |
| L2 | Metadata Intelligence | Parallel probe across all source DBs, build knowledge graph |
| L3 | Semantic Mapping | Rule-baseline + LLM refinement → candidate field mappings |
| L4 | Transformation Synthesis | SCD, audit, derived columns, idempotency |
| L5 | Validation & Governance | Deterministic confidence scoring + rule findings |
| L6 | STM Generation | Compose MappingResult → render xlsx/csv |

Two governance checkpoints:
- **Gate 1** after L2 — review metadata graph before the LLM reasons about it
- **Gate 2** after L5 — review confidence band & findings before shipping

Reviewer can **Approve / Reject / Refine**. Refine targets a stage, marks downstream stale, reruns.

---

## Pre-demo setup (5 min before)

```bash
# 1. Bring up the stack
cd "/Users/apple/Desktop/sql gen"
docker compose up -d
alembic upgrade head

# 2. Confirm the live Postgres profile responds
curl -s http://localhost:8000/api/discovery/profiles | jq '.profiles[] | {id, status}'

# 3. Open two browser tabs side-by-side.
#    The UI is served by nginx on port 8080 (FastAPI on 8000 is API-only).
#
#    Tab A — rule-based composer (existing, untouched)
#    http://localhost:8080/mapping_compose_react.html
#
#    Tab B — agentic mode (new)
#    http://localhost:8080/mapping_compose_react.html?mode=agentic
#
#    Dashboard (if you want to set the scene first):
#    http://localhost:8080/
```

If demoing Jira write-back, set in `.env`:
```
STM_JIRA_WRITEBACK_ENABLED=true
JIRA_URL=...
JIRA_EMAIL=...
JIRA_API_TOKEN=...
```
…and restart the API container.

---

## Demo script

### Act 1 — "What we had" (1 min)

1. Show **Tab A** (`http://localhost:8080/mapping_compose_react.html`).
2. Click a profile → pick a schema → tick columns → hit **Generate STM**.
3. Excel downloads. Point at it: *"This still works. Every demo, every customer trial, this path is untouched."*

> Message: **no regressions, additive only.**

### Act 2 — "What we built" (8 min)

#### 2a. Start an agentic session (1 min)

1. Switch to **Tab B** (`?mode=agentic`).
2. Modal opens. Fill in:
   - Target table: `fact_customer_360`
   - Target dataset: `analytics_warehouse`
   - Sources: tick the live Postgres profile (chip turns amber)
   - Intent source: **Free text** (or Jira if you want to show write-back)
   - Describe: *"Load customer 360 dimension from CRM into BigQuery, daily refresh, mask PII"*
3. Click **Start session**.

> Message: **one intent, many sources, governed pipeline.**

#### 2b. Watch the stepper (2 min)

The L1→L6 rows update live via SSE:
- L1 flips `running → ready` in ~1s (Haiku, cheap)
- L2 fans out to all source profiles, flips ready in 2-4s (Sonnet)
- Stepper highlights the active row in blue; latency + model badge appear

Click L2 to expand → show the JSON artifact (metadata graph). Talk over it:
> *"This is the blackboard. Every stage reads and writes here. The xlsx at the end is just a render of this state."*

#### 2c. Gate 1 review (1.5 min)

After L2 ready, status flips to **awaiting_review** and a gate panel slides in.

1. Show reviewer field, notes, three buttons: Reject / Refine / Approve.
2. Click **Refine** to demo the loop — pick `L2`, write *"only the public schema is in scope"*, send.
3. Watch L2 rerun. Then approve on the second pass.

> Message: **gates aren't blockers — they're the steering wheel.**

#### 2d. L3 → L5 (1.5 min)

Stages flow through. Each shows duration + model. Open L3 — point at the `confidence` score per row, the rule-baseline + LLM-refined columns.

Then Gate 2 (after L5):
- Open the validation panel → show `overall_band` (green/amber/red)
- Show rule-based findings (PII coverage, type coercions, FK chain depth)

Approve.

#### 2e. L6 + download (1 min)

L6 builds in < 1s. Status: **done**. Click **Download STM xlsx**.
- Open the xlsx → it's the same shape as the rule-based path
- Point out: same exporter, same columns — *"we never replaced the floor, we built reasoning on top of it"*

### Act 3 — "What's underneath" (3 min)

Show one slide or just talk through:

- **Blackboard is persisted** → `stm_sessions.blackboard_json`. Crash the API mid-run → restart → sessions resume via `_recover_stm_sessions()` in `app.py`.
- **SSE replay** → reload the page mid-session, the stream replays from DB then tails live.
- **Clone & retry** → take a rejected/failed session, click **Clone & retry**, get a fresh session re-using sources + target + intent. Demo this with a previous session URL.
- **Jira write-back** (if enabled): show that on `session_done` the Jira issue gets a comment with target, band, field count, sources.

### Act 4 — "Why this matters" (2 min)

Three lines:

1. **No regressions.** Rule-based STM is still one endpoint. Demos still work.
2. **Progressive certainty.** Each stage hands a more structured artifact forward. You can pause the pipeline and inspect at any seam.
3. **Governance built-in.** Gates aren't an afterthought — they're how refinement loops back in.

Optional close: *"Excel is the rendered view. The blackboard is the product."*

---

## API cheat sheet (for engineers in the room)

```bash
# Create a session
curl -X POST http://localhost:8000/api/stm/sessions \
  -H 'content-type: application/json' \
  -d '{
    "target_table": "fact_customer_360",
    "target_dataset": "analytics_warehouse",
    "source_profiles": ["pg-demo"],
    "raw_input": "Load customer 360 dimension",
    "intent_source": "freetext"
  }'

# Watch events
curl -N http://localhost:8000/api/stm/sessions/$SID/events

# Status
curl http://localhost:8000/api/stm/sessions/$SID | jq

# Approve Gate 1
curl -X POST http://localhost:8000/api/stm/sessions/$SID/gates/gate1_metadata \
  -H 'content-type: application/json' \
  -d '{"decision":"approved","reviewer":"shankar@example.com"}'

# Refine Gate 2 back to L3
curl -X POST http://localhost:8000/api/stm/sessions/$SID/gates/gate2_validation \
  -H 'content-type: application/json' \
  -d '{"decision":"refine","refine_target":"L3","refine_feedback":"Tighten PII masking on email fields"}'

# Clone after rejection
curl -X POST http://localhost:8000/api/stm/sessions/$SID/clone

# Download xlsx
curl -O -J http://localhost:8000/api/stm/sessions/$SID/export
```

---

## Anticipated questions

**Q: Why two gates and not three?**
A: L2 is when ambiguity is highest (raw metadata). L5 is when stakes are highest (about to ship). L1, L3, L4 are reversible by refine, so no need.

**Q: Can a reviewer edit fields inline at the gate?**
A: Not in this iteration — explicit non-goal. Refine-with-feedback is the supported edit path. Inline edits land in a follow-up.

**Q: What runs the LLM?**
A: OpenRouter today. Per-stage model: L1 Haiku, L2 Sonnet, L3 + L4 Opus, L5/L6 deterministic (no LLM).

**Q: What if two reviewers click Approve simultaneously?**
A: `asyncio.Event.set()` is idempotent — second decision overwrites the gate row but the pipeline already left the stall.

**Q: Single-worker uvicorn?**
A: Yes, intentional for v1. Multi-worker needs DB advisory locks — deferred.

**Q: Is the rule-based path going away?**
A: No. It's the deterministic floor inside L3, and it's still served at `POST /api/stm/generate`.

---

## If something breaks live

| Symptom | Likely cause | Fast fix |
|---------|--------------|----------|
| L2 stuck on `running` | Source DB unreachable | Check profile status; switch to illustrative profile and start a new session |
| SSE stream silent | Page reloaded mid-stage | Refresh — replay covers it |
| Gate panel doesn't appear | Coordinator didn't reach `awaiting_review` | `curl /api/stm/sessions/$SID` and check `status` field |
| xlsx download 409 | Session not done | Wait for terminal stage, or show the stepper to prove it's still running |
| Jira comment missing | `STM_JIRA_WRITEBACK_ENABLED` not `true` | Skip that act; it's env-gated and silent on failure |

---

## Files to point at if anyone wants the code tour

- `core/stm/coordinator.py` — pipeline loop, gates, recovery hook
- `core/stm/agents/` — one file per layer (L1…L6)
- `core/stm/blackboard.py` — the shared state Pydantic models
- `core/stm/events.py` — SSE broker
- `routers/stm_sessions.py` — REST surface
- `ui/mapping_compose_react.html` — `AgenticApp` component starts ~line 1343
- `docs/superpowers/specs/2026-05-11-stm-agentic-evolution-design.md` — the design doc this was built from
