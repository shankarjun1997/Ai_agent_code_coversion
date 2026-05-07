# Shipping Checklist — Enterprise Data Migration Platform

This document covers everything required to ship the platform to production SaaS.

---

## Phase 1: Prerequisites (Before Any Deployment)

### 1.1 Infrastructure Setup
- [ ] GCP project created and billing enabled
- [ ] Cloud SQL (Postgres 15) instance provisioned — platform DB
- [ ] Cloud SQL IAM user / service account created with least-privilege access
- [ ] GCS bucket created for artifact storage (future `GCSArtifactStore`)
- [ ] Cloud Run or GKE cluster provisioned for API deployment
- [ ] Docker Registry (Artifact Registry) set up for container images

### 1.2 Secrets & Environment
Set all of these in GCP Secret Manager (mount as env vars in Cloud Run):
```
DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>/platform
SECRET_KEY=<64-char random string>          # jwt signing
ENCRYPTION_KEY=<Fernet key base64>          # tenant db_url encryption
ANTHROPIC_API_KEY=<your key>                # Claude API
SLACK_WEBHOOK_URL=<webhook>                 # gate notifications
JIRA_URL=https://your-org.atlassian.net
JIRA_USER=<email>
JIRA_API_TOKEN=<token>
GITHUB_TOKEN=<PAT with repo scope>
BQ_PROJECT=<gcp-project-id>
```

Generate ENCRYPTION_KEY:
```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

### 1.3 Database Bootstrap
```bash
# Run platform DB migration (once, on fresh deployment)
DATABASE_URL=postgresql://... alembic -c core/migrations/platform/alembic.ini upgrade head
```
Tenant DBs are provisioned automatically on first signup via `provision_tenant_db()`.

---

## Phase 2: Agent Integrations (Must Complete Before Launch)

Each agent currently has a `_SyncAgentAdapter` wrapper that passes a generic dict. Each agent needs a dedicated adapter matching its actual signature:

### 2.1 Agent 1 — Requirements Agent
- [ ] Adapter unpacks `raw_input`, `jira_issue_key` from payload
- [ ] Jira integration tested: `JiraClient.create_issue()` creates story correctly
- [ ] Claude prompt tested end-to-end with real transcript input
- [ ] Output `RequirementsDoc` schema validated

### 2.2 Agent 2 — Mapping Agent
- [ ] Adapter unpacks `requirements`, `jira_issue_key` from payload
- [ ] BigQuery schema discovery tested (multi-turn tool-use)
- [ ] `DataMapping` Pydantic schema validated
- [ ] Confluence page creation tested (via RovoConnector)

### 2.3 Agent 3 — Engineering Orchestrator + Sub-agents (3a–3e)
- [ ] Each sub-agent adapter wired with correct input fields
- [ ] 3a SQL generation tested against a real BQ dataset
- [ ] 3b Code conversion tested with Teradata sample
- [ ] 3c DQ rules generated and validated as Dataform assertions
- [ ] 3d Observability hooks generated with correct alert thresholds
- [ ] 3e Metadata published to Dataplex successfully
- [ ] GitHub PR creation tested: `GitHubClient.publish_artifacts()`
- [ ] Parallel execution confirmed (all 5 sub-agents run concurrently)

### 2.4 Agent 4 — QA Agent
- [ ] QA test suite generation tested
- [ ] BQ execution of generated tests validated
- [ ] `QAReport` schema validated with pass/fail results

---

## Phase 3: UI Dashboard

The existing PHP UI (`ui/`) needs to be connected to the new API endpoints:

- [ ] Login page calling `POST /auth/login`
- [ ] Signup page calling `POST /auth/signup`
- [ ] Pipeline trigger form calling `POST /pipelines/trigger`
- [ ] Run status page polling `GET /pipelines/{run_id}`
- [ ] Gate approval UI calling `POST /gates/{run_id}/approve` and `/reject`
- [ ] Artifact viewer showing generated SQL, DQ rules, etc.
- [ ] Slack notification deep-link points to correct gate approval URL

---

## Phase 4: End-to-End Testing

- [ ] Full pipeline run from raw transcript → QA sign-off with a real Jira project
- [ ] Gate approval flow: pause at each gate, approve, verify pipeline resumes
- [ ] Gate rejection flow: verify run marked FAILED, Slack notified
- [ ] Server restart test: start pipeline, restart API, verify AWAITING_GATE run recovers
- [ ] Two-tenant isolation test: run pipelines for two tenants simultaneously, verify no data bleed
- [ ] Load test: 5 concurrent pipeline runs (one per tenant)

---

## Phase 5: Security Hardening

- [ ] Replace `allow_origins=["*"]` in CORS middleware with actual domain allowlist
- [ ] Enable HTTPS-only (Cloud Run handles TLS termination)
- [ ] Rate-limit `/auth/login` and `/auth/signup` (e.g., via Cloud Armor or FastAPI middleware)
- [ ] Audit log: every gate approval/rejection records IP + user agent
- [ ] Rotate `SECRET_KEY` process documented (invalidates all tokens — requires re-login)
- [ ] Fernet key rotation process documented for `ENCRYPTION_KEY`
- [ ] `.env` file removed from git (already in `.gitignore`? verify)
- [ ] Postgres SSL connections enforced (`?sslmode=require` in DATABASE_URL)

---

## Phase 6: Observability

- [ ] Structured logging enabled (JSON format for Cloud Logging ingestion)
- [ ] Health check endpoint `/api/health` returns 200 (already exists)
- [ ] Uptime check configured in Cloud Monitoring
- [ ] Alert on: API error rate >1%, P99 latency >10s, agent timeout rate >5%
- [ ] Pipeline success/failure rate dashboard in Cloud Monitoring or Grafana
- [ ] SQLAlchemy connection pool metrics exposed

---

## Phase 7: Deployment

### 7.1 Docker Build
```bash
# Build and push
docker build -t gcr.io/<project>/sqlgen-api:latest .
docker push gcr.io/<project>/sqlgen-api:latest
```

### 7.2 Cloud Run Deploy
```bash
gcloud run deploy sqlgen-api \
  --image gcr.io/<project>/sqlgen-api:latest \
  --region us-central1 \
  --set-env-vars "$(gsd-env-from-secret-manager)" \
  --min-instances 1 \
  --max-instances 10 \
  --memory 2Gi \
  --cpu 2
```

### 7.3 Run Platform Migration
```bash
gcloud run jobs create migrate-platform \
  --image gcr.io/<project>/sqlgen-api:latest \
  --command "alembic" \
  --args "-c,core/migrations/platform/alembic.ini,upgrade,head"
gcloud run jobs execute migrate-platform
```

---

## Phase 8: Go-Live Checklist

- [ ] Custom domain configured (`api.your-product.com`)
- [ ] First admin tenant created manually via signup endpoint
- [ ] Smoke test: trigger a pipeline with a known Jira issue, approve all gates, verify artifacts
- [ ] On-call runbook created: what to do when pipeline FAILS, when Slack notifications stop, when BQ quota exceeded
- [ ] Backup policy: Cloud SQL automated backups enabled (daily, 7-day retention)
- [ ] Billing alerts configured in GCP

---

## Quick Reference: What's Already Done

| Component | Status |
|-----------|--------|
| Core infra (auth, tenant isolation, orchestrator, gates) | ✅ Built & tested |
| Alembic migrations (platform + tenant) | ✅ Ready |
| FastAPI API (auth, pipelines, gates routes) | ✅ Built |
| Agent skeletons (1–4 + 3a–3e) | ✅ Exist, need adapters wired |
| PHP UI | ✅ Exists, needs new API endpoints wired |
| Docker + docker-compose | ✅ Exists |
| Tests (35 unit/contract/integration) | ✅ Passing |
| GCS artifact storage | 🔲 Seam ready, not implemented |
| Enterprise SSO (SAML/OIDC) | 🔲 Planned, not started |
| Temporal/Cloud Workflows migration | 🔲 Future — AsyncioEngine swap |

---

## Estimated Effort to Ship (MVP)

| Phase | Effort |
|-------|--------|
| Prerequisites (infra, secrets) | 1 day |
| Agent adapters + integration tests | 3–5 days |
| UI wiring | 2–3 days |
| E2E testing | 2 days |
| Security hardening | 1 day |
| Deployment + go-live | 1 day |
| **Total** | **~2 weeks** |
