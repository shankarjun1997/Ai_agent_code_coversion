# OneFiber Migration AI Agent Framework

Two tools in one framework:

| Tool | What it does |
|------|-------------|
| **`convert_oracle.py`** | Take raw Oracle PL/SQL → produce BigQuery SQL + full deployment scaffold (16 files) |
| **`main.py`** | Scan existing BQ modules → find issues → auto-fix (4-agent pipeline) |

---

## Prerequisites

### 1. Python 3.10+

```bash
python --version    # must be 3.10 or higher
```

### 2. Install dependencies

```bash
cd migration_ai_agents
pip install -r requirements.txt
```

This installs only **pyyaml** and **pytest** (both lightweight).  
LLM and BigQuery packages are optional — see the LLM section below.

### 3. Repository structure

This framework lives inside your onefiber repo:

```
onefiber/                         ← Git repo root
├── ned_dashboard/                ← Existing module
│   ├── pipelines/src/main/
│   │   ├── sql/*.sql
│   │   ├── config/deployprd.cfg, deployuat.cfg, deploydev.cfg
│   │   └── scripts/run_bq_ddl_deploy.sh
│   └── dag/
│       ├── python/*.py
│       └── config/*.yml, base_config.yaml
├── Jenkinsfile                   ← Your CI/CD pipeline
├── deploy.yaml                   ← Environment configs
├── migration_ai_agents/          ← THIS FRAMEWORK
│   ├── convert_oracle.py         ← Oracle → BQ converter CLI
│   ├── main.py                   ← 4-agent scanner/fixer CLI
│   └── ...
```

### 4. (Optional) LLM API Key — only if using `--use-llm`

```bash
# For OpenAI
set OPENAI_API_KEY=sk-your-key-here

# For Azure OpenAI
set AZURE_OPENAI_API_KEY=your-key-here

# For Vertex AI — use gcloud auth instead
gcloud auth application-default login
```

> **Without an LLM key**, the framework works 100% with rule-based conversion.  
> LLM just adds a refinement pass for complex edge cases.

---

## Tool 1: Oracle → BigQuery Conversion (`convert_oracle.py`)

### When to use

You have a **raw Oracle PL/SQL stored procedure** and want to:
1. Convert it to BigQuery SQL
2. Generate all deploy configs (deployprd.cfg, deployuat.cfg, deploydev.cfg)
3. Generate Airflow DAG Python + YAML configs
4. Generate Jenkins packaging (.conf) file
5. Create the exact folder structure that your Jenkinsfile expects

### Step-by-step

#### Step 1: Put your Oracle SQL file somewhere

```bash
# Create a folder for your Oracle source files
mkdir migration_ai_agents\oracle_input

# Copy/paste your Oracle procedure into a .sql file
# Example: oracle_input\my_daily_load.sql
```

The file should be a standard Oracle PL/SQL procedure, e.g.:

```sql
CREATE OR REPLACE PROCEDURE SCHEMA.MY_DAILY_LOAD(
    p_run_date IN DATE
)
IS
    v_count NUMBER;
BEGIN
    INSERT INTO target_table
    SELECT * FROM source_table
    WHERE created_date >= p_run_date;
    
    v_count := SQL%ROWCOUNT;
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE;
END;
```

#### Step 2: Dry-run (preview what will be generated)

```bash
cd migration_ai_agents

python convert_oracle.py ^
    --input oracle_input\my_daily_load.sql ^
    --module my_new_dashboard ^
    --proc-name sp_onef_my_daily_load
```

This prints a report showing:
- Complexity score (LOW / MEDIUM / HIGH / VERY_HIGH)
- Oracle functions detected and their BQ equivalents
- Items needing manual review
- List of 16 files that WOULD be generated

#### Step 3: Apply (write files to the repo)

```bash
python convert_oracle.py ^
    --input oracle_input\my_daily_load.sql ^
    --module my_new_dashboard ^
    --proc-name sp_onef_my_daily_load ^
    --apply
```

This creates the full folder structure:

```
onefiber/
├── my_new_dashboard/                          ← NEW MODULE
│   ├── pipelines/src/main/
│   │   ├── sql/sp_onef_my_daily_load.sql      ← Converted BQ SQL
│   │   ├── config/
│   │   │   ├── deployprd.cfg                  ← prod config (environment=prod)
│   │   │   ├── deployuat.cfg                  ← uat config  (environment=uat)
│   │   │   └── deploydev.cfg                  ← dev config  (environment=dev)
│   │   ├── scripts/
│   │   │   ├── run_bq_ddl_deploy.sh           ← BQ deployment script
│   │   │   └── run_copy_to_gcs.sh             ← GCS DAG copy script
│   │   ├── bq_ddl/                            ← DDL scripts (empty, add yours)
│   │   └── ddl_script/                        ← Env DDL runners (empty)
│   ├── dag/
│   │   ├── python/
│   │   │   ├── sp_onef_my_daily_load.py       ← Airflow DAG
│   │   │   └── DO_utils.py                    ← Copied from existing module
│   │   ├── config/
│   │   │   ├── sp_onef_my_daily_load.yml      ← DAG YAML config
│   │   │   └── base_config.yaml               ← Base config
│   │   ├── uat/python/...                     ← UAT copies
│   │   ├── uat/config/...
│   │   └── DPF/                               ← DPF folder (empty)
│   ├── assembly/packages/
│   └── CONVERSION_REPORT.md                   ← What was converted + checklist
├── my_new_dashboard.conf                      ← Jenkins packaging config
```

#### Step 4: Review the converted SQL

Open `my_new_dashboard/pipelines/src/main/sql/sp_onef_my_daily_load.sql` and check:

- [ ] DECODE → CASE WHEN conversions are correct
- [ ] TO_DATE format strings converted to BQ format
- [ ] Oracle (+) joins replaced with LEFT/RIGHT JOIN
- [ ] Cursors converted to FOR...IN (SELECT) DO
- [ ] Table names mapped correctly to `${config_var}` references
- [ ] query_label block has the right table_id entries
- [ ] CONVERSION_REPORT.md lists any items needing manual review

#### Step 5: Update deploy configs

Edit the generated `.cfg` files to set correct:
- Source/target table names (the converter auto-detects, but verify)
- Source dataset names
- Any module-specific config values

#### Step 6: Add to Jenkinsfile

Add your new module to the `build_module` choices in `Jenkinsfile`:

```groovy
choice(
  name: 'build_module',
  choices: [
    // ... existing modules ...
    'my_new_dashboard',   // ← ADD THIS
  ],
```

#### Step 7: Deploy via Jenkins

```
Jenkins → Build with Parameters:
  build_module = my_new_dashboard
  environment  = dev
  deploy_bq_stored_procedure = YES
  deploy_dag   = DPF_Dag_creation
  BRANCH       = dynamic_task_dag
```

### Advanced options

```bash
# Convert with LLM refinement (handles complex DECODE, cursors, etc.)
python convert_oracle.py --input oracle_input\my_proc.sql --module my_dash --use-llm --apply

# Convert ALL Oracle files in a directory
python convert_oracle.py --input-dir oracle_input\ --module my_dash --apply

# Custom output directory for reports
python convert_oracle.py --input oracle_input\my_proc.sql --module my_dash --output-dir reports\
```

### What gets auto-converted (20+ rules)

| Oracle | BigQuery |
|--------|----------|
| `VARCHAR2(n)`, `NUMBER`, `DATE` | `STRING`, `INT64`/`NUMERIC`, `DATETIME` |
| `NVL(a, b)` | `IFNULL(a, b)` |
| `SYSDATE` / `SYSTIMESTAMP` | `CURRENT_DATETIME()` / `CURRENT_TIMESTAMP()` |
| `TO_DATE(str, fmt)` | `PARSE_DATETIME(fmt, str)` (review format) |
| `TO_CHAR(date, fmt)` | `FORMAT_DATETIME(fmt, date)` (review format) |
| `TO_NUMBER(x)` | `CAST(x AS NUMERIC)` |
| `DECODE(a,b,c,d)` | `CASE WHEN` (flagged for review) |
| `LISTAGG() / WM_CONCAT()` | `STRING_AGG()` |
| `REGEXP_SUBSTR()` | `REGEXP_EXTRACT()` |
| `INSTR()` | `STRPOS()` |
| `(+)` outer joins | Flagged → convert to `LEFT JOIN` |
| `COMMIT / ROLLBACK` | Removed (BQ auto-commits) |
| `SQLERRM / SQLCODE` | `@@error.message / @@error.statement_text` |
| `EXCEPTION WHEN OTHERS` | `EXCEPTION WHEN ERROR THEN` |
| `DBMS_OUTPUT.PUT_LINE(x)` | `SELECT x AS debug_message;` |
| `EXECUTE IMMEDIATE` | Flagged for manual review |
| `ROWNUM` | Flagged → `ROW_NUMBER() OVER()` / `LIMIT` |
| `sequence.NEXTVAL` | Flagged → `GENERATE_UUID()` |
| Oracle hints `/*+ */` | Removed |
| `CURSOR...FOR LOOP` | `FOR...IN (SELECT) DO...END FOR` |
| `BULK COLLECT / FORALL` | Flagged → set-based conversion |

---

## Tool 2: Scan & Fix Existing Modules (`main.py`)

### When to use

Your module already exists in the repo (BQ SQL + configs + DAGs) and you want to:
1. **Scan** for issues (missing config vars, wrong environment, hardcoded values, etc.)
2. **Diagnose** root causes
3. **Auto-fix** problems

### Step-by-step

#### List all modules

```bash
python main.py --list-modules
```

#### Scan a single module (dry-run)

```bash
python main.py --module ned_dashboard --mode full --dry-run
```

#### Scan ALL modules

```bash
python main.py --mode full --dry-run
```

#### Run only specific stages

```bash
# Just conversion checks
python main.py --module ned_dashboard --mode convert

# Conversion + validation
python main.py --module ned_dashboard --mode validate

# Conversion + validation + debug diagnosis
python main.py --module ned_dashboard --mode debug

# Full pipeline including auto-fix (dry-run)
python main.py --module ned_dashboard --mode fix --dry-run
```

#### Apply auto-fixes

```bash
python main.py --module ned_dashboard --mode fix --apply
```

#### Re-run fix from a saved debug report

```bash
python main.py --mode fix-only --debug-report output\debug_result.json --apply
```

### What it checks

| Check | Description |
|-------|-------------|
| **Query label** | Every DML has `SET @@query_label` with all required fields |
| **Config vars** | No hardcoded GCP project IDs — all use `${config_var}` |
| **table_id ordering** | First DML → `table_id`, second → `table_id_1`, etc. |
| **Metadata fields** | `etl_type`, `application`, `environment`, `vsad` use config vars |
| **Cross-env consistency** | deployprd/uat/dev.cfg all have the same keys |
| **Environment values** | deployprd=prod, deployuat=uat, deploydev=dev |
| **DAG id naming** | Must contain `_nar_` (format: `gudv_nar_onef_<name>`) |
| **DAG overrides** | No hardcoded `gcp_project` or `google_cloud_conn_id` in DAG Python |
| **SQL syntax** | BEGIN/END balance, backtick balance, procedure references |
| **SQL ↔ Config alignment** | All `${var}` in SQL have matching `export` in .cfg |
| **YAML ↔ SQL alignment** | stored_proc in YAML matches actual SQL file names |

### Output

Results are saved to `migration_ai_agents/output/`:

```
output/
├── pipeline_summary.json      ← Overall summary
├── conversion_result.json     ← Agent 1 findings
├── validation_result.json     ← Agent 2 findings
├── debug_result.json          ← Agent 3 root-cause analysis
├── fix_result.json            ← Agent 4 changes applied
└── migration_agent.log        ← Full log
```

---

## End-to-End Workflow: Oracle → Production

```
                    YOU                              FRAMEWORK
                     │                                  │
   1. Get Oracle SQL │                                  │
      from DBA/repo  │                                  │
                     │                                  │
   2. ───────────────┼──► convert_oracle.py --apply     │
                     │    (converts + scaffolds)        │
                     │                                  │
   3. Review ◄───────┼── CONVERSION_REPORT.md           │
      converted SQL  │   (checklist of manual items)    │
                     │                                  │
   4. Fix any items  │                                  │
      flagged ⚠️      │                                  │
                     │                                  │
   5. ───────────────┼──► main.py --mode full           │
                     │    (validate the conversion)     │
                     │                                  │
   6. ───────────────┼──► main.py --mode fix --apply    │
                     │    (auto-fix remaining issues)   │
                     │                                  │
   7. git add + commit + push                           │
                     │                                  │
   8. Jenkins Build ─┼──► deploy-stored-procedure       │
      (Jenkinsfile)  │    (bq query via .cfg)           │
                     │──► Deploy DAG                    │
                     │    (copy to GCS Composer)        │
```

---

## Configuration (`configs/config.yaml`)

Key sections to customize:

```yaml
# GCP project IDs (already set for OneFiber)
gcp:
  dev:
    project_id: "vz-it-np-gudv-dev-dtwndo-0"
  prod:
    project_id: "vz-it-pr-gudv-dtwndo-0"

# LLM (optional — only needed for --use-llm)
llm:
  provider: "openai"          # openai | vertex_ai | azure_openai
  model: "gpt-4o"
```

---

## Running Tests

```bash
cd migration_ai_agents
python -m pytest tests\test_agents.py -v
```

---

## Folder Structure

```
migration_ai_agents/
├── convert_oracle.py           # CLI: Oracle → BQ + scaffold
├── main.py                     # CLI: 4-agent scan/fix pipeline
├── configs/config.yaml         # Master configuration
├── agents/
│   ├── __init__.py             # BaseAgent + AgentResult
│   ├── conversion_agent.py     # Agent 1: Scan for issues
│   ├── validation_agent.py     # Agent 2: Cross-validate
│   ├── debug_agent.py          # Agent 3: Root-cause analysis
│   └── fix_agent.py            # Agent 4: Auto-fix
├── converters/
│   ├── oracle_to_bq.py         # Oracle→BQ rule engine (20+ rules)
│   └── scaffold_generator.py   # Writes full module folder structure
├── parsers/
│   ├── oracle_parser.py        # Parse Oracle PL/SQL
│   ├── sql_parser.py           # Parse BigQuery SQL
│   ├── config_parser.py        # Parse deploy .cfg files
│   ├── dag_parser.py           # Parse Airflow DAG Python
│   └── yaml_parser.py          # Parse DAG YAML configs
├── models/
│   └── llm_client.py           # LLM integration (OpenAI/Vertex/Azure)
├── workflows/
│   └── migration_pipeline.py   # Agent orchestrator
├── prompts/                    # LLM prompt templates
│   ├── oracle_to_bq.txt
│   ├── convert_sql.txt
│   ├── convert_dag.txt
│   ├── debug_mismatch.txt
│   └── fix_code.txt
├── sample_oracle/              # Sample Oracle SQL for testing
├── output/                     # Agent outputs
├── tests/test_agents.py        # Unit tests (29 tests)
└── requirements.txt
```
