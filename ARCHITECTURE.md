# SQL-Gen Agentic Pipeline — Architecture

## Overview

A fully agentic, human-in-the-loop data engineering pipeline that transforms stakeholder conversations into production-ready BigQuery assets, governed by explicit approval gates at every stage.

```
Unstructured Input (transcript / email / Jira issue)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  Agent 1 — Requirement & Prototyping                    │
│                                         │
│  Output: RequirementsDoc + Jira story draft             │
│  → LLM: Claude parses free-form text into structured    │
│    tasks, ACs, clarifying questions, prototype table    │
└─────────────────────────┬───────────────────────────────┘
                          │ REVIEW GATE ← Mohan approves
                          │ (Pipeline pauses, UI shows review prompt)
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Jira Story pushed  (new issue created or existing key) │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Agent 2 — Mapping / Design Document                    │
│                                      │
│  Output: DataMapping config (source of truth)           │
│  → Multi-turn tool-use: Claude discovers BQ schemas,    │
│    maps every field, documents business rules, PII
   ┌──────────┐  ┌──────────────────────────┐            │.  - end goal - stm.excel
│  │ 2a Connect  │  │ 2b Metadata              │  (parallel) │
│  │ Teradata │  │ Lineage · Dataplex · PII │            │
│  │ → BQ SQL │  │ BQ column descriptions   │            │
│  └──────────┘  └──────────────────────────┘   │
└─────────────────────────┬───────────────────────────────┘
                          │ REVIEW GATE ← Shankar approves
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Agent 3 — Engineering Orchestrator                     │
│           │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ 3a SQL   │  │ 3c DQ    │  │ 3d Obs   │  (parallel) │
│  │ DDL/View │  │ Dataform │  │ Alerts   │             │
│  │ dbt/SQLX │  │ dbt tests│  │ Logging  │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│             │
│                                                         │
│  Output: EngineeringPackage + GitHub PR                 │
└─────────────────────────┬───────────────────────────────┘
                          │ REVIEW GATE ← Engineer approves PR
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Agent 4 — QA                                           │
│                           │
│  Output: QAReport with executed test results            │
│  → Generates + runs: row counts, null checks,           │
│    dedup, referential integrity, reconciliation,        │
│    restartability, transformation correctness           │
└─────────────────────────┬───────────────────────────────┘
                          │ REVIEW GATE ← QA lead sign-off
                          │
                          ▼
                    COMPLETED ✓
```

## Services

| Service | Technology       | Port | Description                                       |
| ------- | ---------------- | ---- | ------------------------------------------------- |
| `api`   | Python / FastAPI | 8000 | Pipeline orchestration, agent execution, REST API |
| `ui`    | PHP 8.2 / Nginx  | 8080 | Dashboard, review gates, real-time monitoring     |

## Human-in-the-Loop Gates

| Stage         | Gate Owner           | Action Required                           |
| ------------- | -------------------- | ----------------------------------------- |
| After Agent 1 | Paramjit             | Validate requirements, approve Jira push  |
| After Agent 2 | Shankar              | Validate mapping document, approve design |
| After Agent 3 | Engineer             | Review PR, validate SQL/DQ/metadata       |
| After Agent 4 | Sandeep / Saikrishna | QA sign-off, approve release              |

## Data Flow

```
Jira Story
    ↓ JiraClient.get_issue()
JiraStory (Pydantic)
    ↓ RequirementsAgent.run()
RequirementsDoc (Pydantic)
    ↓ [APPROVED] → Jira issue created
    ↓ MappingAgent.run()  ← multi-turn BQ tool-use
DataMapping (Pydantic) — single source of truth
    ↓ [APPROVED] → RovoConnector.comment() + Confluence page
    ↓ EngineeringOrchestrator.run() — parallel sub-agents
EngineeringPackage (Pydantic)
  ├── List[GeneratedArtifact]  (SQL, dbt, Python, YAML)
  ├── DQReport                 (Dataform, dbt tests, BQ proc)
  ├── ObservabilityConfig      (alerts, audit cols, dashboards)
  └── MetadataEntry            (Dataplex, BQ descriptions, lineage)
    ↓ GitHubClient.publish_artifacts() → PR URL
    ↓ [APPROVED] → QAAgent.run()
QAReport (Pydantic)
    ↓ [SIGNED OFF]
Pipeline COMPLETED
```

## State Persistence

SQLite (`output/state.db`) stores:

- `pipeline_runs` — full run state, stage, all JSON payloads
- `generated_artifacts` — individual files with content
- `data_mappings` — versioned mapping documents

All agent outputs are serialised as Pydantic JSON and stored at each stage,
so the pipeline can be resumed after approval gates without re-running completed work.

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 2. Start with Docker
docker-compose up --build

# Access:
#   UI Dashboard:  http://localhost:8080
#   API Docs:      http://localhost:8000/docs

# 3. Trigger a pipeline (CLI)
python pipeline.py trigger --issue-key DATA-1042

# Or with raw text:
python pipeline.py trigger --input "We need a daily sales summary table..."

# 4. Approve a gate
python pipeline.py approve <run_id> --reviewer "Paramjit" --notes "LGTM"

# 5. Check status
python pipeline.py status
```

## Directory Structure

```
sql-gen/
├── agents/
│   ├── agent_1_requirements.py   # Req & Prototyping (Paramjit)
│   ├── agent_2_mapping.py        # Mapping/Design (Shankar)
│   ├── agent_3_orchestrator.py   # Engineering coordinator
│   ├── agent_3a_sql_gen.py       # SQL/DDL/Views/dbt/SQLX
│   ├── agent_3b_code_conv.py     # Legacy SQL conversion
│   ├── agent_3c_dq.py            # DQ rules
│   ├── agent_3d_observability.py # Monitoring/Alerts
│   ├── agent_3e_metadata.py      # Catalog/Lineage/PII
│   ├── agent_4_qa.py             # QA (Sandeep)
│   └── shared/
│       ├── jira_client.py        # Jira REST API v3
│       ├── github_client.py      # GitHub PR creation
│       └── rovo_connector.py     # Atlassian Rovo + Confluence
├── core/
│   ├── schemas.py                # All Pydantic data models
│   ├── bq_client.py              # BigQuery wrapper
│   ├── state_db.py               # SQLite state management
│   ├── llm_client.py             # Claude API wrapper (tool-use)
│   └── orchestrator.py           # Pipeline with human gates
├── ui/                           # PHP dashboard (Nginx + PHP-FPM)
├── docker/                       # Docker build files
├── output/                       # State DB + generated files
├── app.py                        # FastAPI REST service
├── pipeline.py                   # CLI
├── docker-compose.yml
└── requirements.txt
```
