"""
Oracle-to-BigQuery SQL Converter — Rule-Based + LLM-Assisted.

Transforms Oracle PL/SQL stored procedures into BigQuery SQL stored procedures
following the OneFiber production folder structure and coding conventions.

Conversion Pipeline:
  1. Parse Oracle SQL (extract structure)
  2. Apply rule-based transformations (data types, functions, joins, syntax)
  3. Wrap in BigQuery CREATE OR REPLACE PROCEDURE with ${config_var}
  4. Add query_label block
  5. Add session logging (onef_sess_status_logs)
  6. Optionally refine with LLM
"""
import re
import os
import textwrap
from typing import Optional

from parsers.oracle_parser import OracleSQLParser


class OracleToBQConverter:
    """Convert Oracle PL/SQL to BigQuery SQL following OneFiber conventions."""

    def __init__(self, config: dict = None, llm_client=None):
        """
        Args:
            config: Config dict (from config.yaml)
            llm_client: Optional LLMClient for LLM-assisted conversion
        """
        self.config = config or {}
        self.llm_client = llm_client

    def convert(
        self,
        oracle_sql: str,
        module_name: str,
        proc_name: str,
        source_tables: list = None,
        target_tables: list = None,
        use_llm: bool = False,
    ) -> dict:
        """
        Full conversion pipeline: Oracle SQL → BigQuery SQL + deploy configs + DAG.

        Args:
            oracle_sql: Raw Oracle PL/SQL source code
            module_name: Target module name (e.g. 'ned_dashboard')
            proc_name: Target procedure name (e.g. 'sp_onef_ned_refresh')
            source_tables: List of source table names (optional — auto-detected if None)
            target_tables: List of target table names (optional — auto-detected if None)
            use_llm: Whether to refine with LLM after rule-based conversion

        Returns:
            dict with keys: bq_sql, deploy_configs, dag_python, dag_yaml, conf_file, report
        """
        # 1. Parse the Oracle SQL
        parser = OracleSQLParser(oracle_sql, filename=f"{proc_name}.sql")
        analysis = parser.parse()

        # Auto-detect tables if not provided
        if source_tables is None:
            source_tables = [t for t in analysis["table_references"]
                            if not t.upper().startswith("TMP_") and "." in t]
        if target_tables is None:
            target_tables = [op["target"] for op in analysis["dml_operations"]
                            if op["type"] in ("INSERT", "MERGE")]

        # 2. Apply rule-based conversion
        bq_sql = self._rule_based_convert(oracle_sql, analysis, proc_name, source_tables, target_tables)

        # 3. Optionally refine with LLM
        if use_llm and self.llm_client and self.llm_client.is_available():
            bq_sql = self._llm_refine(oracle_sql, bq_sql, analysis, proc_name)

        # 4. Generate deploy configs
        deploy_configs = self._generate_deploy_configs(
            module_name, proc_name, source_tables, target_tables
        )

        # 5. Generate DAG Python
        dag_python = self._generate_dag_python(module_name, proc_name)

        # 6. Generate DAG YAML config
        dag_yaml = self._generate_dag_yaml(module_name, proc_name, source_tables)

        # 7. Generate base_config.yaml
        base_config_yaml = self._generate_base_config(module_name)

        # 8. Generate .conf file
        conf_file = self._generate_conf_file(module_name, proc_name)

        # 9. Generate deploy scripts
        deploy_scripts = self._generate_deploy_scripts()

        # 10. Build conversion report
        report = self._build_report(analysis, bq_sql, proc_name, module_name)

        return {
            "bq_sql": bq_sql,
            "deploy_configs": deploy_configs,
            "dag_python": dag_python,
            "dag_yaml": dag_yaml,
            "base_config_yaml": base_config_yaml,
            "conf_file": conf_file,
            "deploy_scripts": deploy_scripts,
            "analysis": analysis,
            "report": report,
        }

    # ─────────────────────────────────────────────
    # Rule-Based SQL Conversion
    # ─────────────────────────────────────────────

    def _rule_based_convert(
        self,
        oracle_sql: str,
        analysis: dict,
        proc_name: str,
        source_tables: list,
        target_tables: list,
    ) -> str:
        """Apply rule-based transformations to Oracle SQL."""
        sql = oracle_sql

        # 1. Replace Oracle procedure header → BQ procedure header
        sql = self._convert_procedure_header(sql, proc_name)

        # 2. Replace data types
        sql = self._convert_data_types(sql)

        # 3. Replace Oracle functions → BQ functions
        sql = self._convert_functions(sql)

        # 4. Replace Oracle (+) joins → ANSI LEFT/RIGHT JOIN
        sql = self._convert_oracle_joins(sql)

        # 5. Replace Oracle string concatenation (||) — BQ also supports ||, so keep it
        # (BigQuery supports || for string concat, no change needed)

        # 6. Replace SYSDATE / SYSTIMESTAMP
        sql = re.sub(r'\bSYSDATE\b', 'CURRENT_DATETIME()', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bSYSTIMESTAMP\b', 'CURRENT_TIMESTAMP()', sql, flags=re.IGNORECASE)

        # 7. Replace NVL → IFNULL
        sql = re.sub(r'\bNVL\s*\(', 'IFNULL(', sql, flags=re.IGNORECASE)

        # 8. Replace DECODE → CASE WHEN (simple cases)
        sql = self._convert_decode(sql)

        # 9. Replace TO_DATE → PARSE_DATETIME
        sql = self._convert_to_date(sql)

        # 10. Replace TO_CHAR for dates → FORMAT_DATETIME
        sql = self._convert_to_char(sql)

        # 11. Replace TO_NUMBER → CAST(... AS NUMERIC)
        sql = self._convert_to_number(sql)

        # 12. Replace ROWNUM → ROW_NUMBER()
        sql = self._convert_rownum(sql)

        # 13. Replace sequences → GENERATE_UUID() or manual ID
        sql = self._convert_sequences(sql)

        # 14. Remove Oracle hints /*+ ... */
        sql = re.sub(r'/\*\+.*?\*/', '', sql, flags=re.DOTALL)

        # 15. Remove EXIT/RETURN with no value → just keep RETURN
        sql = re.sub(r'\bEXIT\s*;', '-- EXIT removed (no BQ equivalent)', sql, flags=re.IGNORECASE)

        # 16. Replace cursor FOR loops → BQ FOR...IN pattern
        sql = self._convert_cursor_loops(sql)

        # 17. Replace exception handlers → BQ BEGIN...EXCEPTION
        sql = self._convert_exception_handlers(sql)

        # 18. Replace COMMIT/ROLLBACK → comments (BQ auto-commits)
        sql = re.sub(r'\bCOMMIT\s*;', '-- COMMIT removed (BigQuery auto-commits)', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bROLLBACK\s*;', '-- ROLLBACK removed (BigQuery auto-commits)', sql, flags=re.IGNORECASE)

        # 19. Replace DBMS_OUTPUT.PUT_LINE → SELECT for debugging
        sql = re.sub(
            r'DBMS_OUTPUT\.PUT_LINE\s*\((.+?)\)\s*;',
            r'SELECT \1 AS debug_message;',
            sql, flags=re.IGNORECASE
        )

        # 20. Add table references with config vars
        sql = self._add_config_var_references(sql, source_tables, target_tables)

        # 21. Add query_label block
        sql = self._add_query_label(sql, target_tables)

        return sql

    def _convert_procedure_header(self, sql: str, proc_name: str) -> str:
        """Replace Oracle procedure header with BQ format."""
        # Remove Oracle CREATE OR REPLACE PROCEDURE with params and IS/AS
        header_pattern = re.compile(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+\w+(?:\.\w+)*'
            r'\s*(?:\([^)]*\))?\s*(?:IS|AS)\b',
            re.IGNORECASE | re.DOTALL
        )
        bq_header = (
            f'CREATE OR REPLACE PROCEDURE '
            f'`${{target_project_id}}.${{target_dataset_name}}.{proc_name}`()\n'
            f'OPTIONS(strict_mode=FALSE)\n'
            f'BEGIN'
        )
        if header_pattern.search(sql):
            sql = header_pattern.sub(bq_header, sql, count=1)
            # Remove the first standalone BEGIN after header (BQ header already includes it)
            sql = re.sub(r'\nBEGIN\s*\n', '\n', sql, count=1, flags=re.IGNORECASE)
        else:
            # If no CREATE PROCEDURE, just wrap the body
            sql = bq_header + "\n" + sql

        # Ensure END; at the bottom
        if not sql.rstrip().endswith("END;"):
            sql = sql.rstrip().rstrip(";").rstrip() + "\nEND;"

        return sql

    def _convert_data_types(self, sql: str) -> str:
        """Replace Oracle data types with BigQuery equivalents in DECLARE statements."""
        for oracle_type, bq_type in OracleSQLParser.DATATYPE_MAP.items():
            if bq_type is None:
                continue
            # Match in DECLARE: variable_name TYPE → DECLARE variable_name TYPE
            sql = re.sub(
                rf'(\bDECLARE\s+\w+\s+){re.escape(oracle_type)}\b(\([^)]*\))?',
                rf'\g<1>{bq_type}',
                sql, flags=re.IGNORECASE
            )
            # Also in variable declarations inside the block
            sql = re.sub(
                rf'(\w+\s+){re.escape(oracle_type)}\b(\([^)]*\))?\s*(?=;|:=|DEFAULT)',
                rf'\g<1>{bq_type}',
                sql, flags=re.IGNORECASE
            )
        return sql

    def _convert_functions(self, sql: str) -> str:
        """Replace Oracle functions with BigQuery equivalents."""
        # LISTAGG / WM_CONCAT → STRING_AGG
        sql = re.sub(r'\bLISTAGG\s*\(', 'STRING_AGG(', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bWM_CONCAT\s*\(', 'STRING_AGG(', sql, flags=re.IGNORECASE)

        # REGEXP_SUBSTR → REGEXP_EXTRACT
        sql = re.sub(r'\bREGEXP_SUBSTR\s*\(', 'REGEXP_EXTRACT(', sql, flags=re.IGNORECASE)

        # INSTR → STRPOS (note: different arg order for some overloads)
        sql = re.sub(r'\bINSTR\s*\(', 'STRPOS(', sql, flags=re.IGNORECASE)

        # LENGTH → LENGTH (same in BQ, no change)
        # SUBSTR → SUBSTR (same in BQ, no change)
        # TRIM/LTRIM/RTRIM → same
        # UPPER/LOWER → same
        # ROUND/CEIL/FLOOR → same
        # COALESCE → same
        # GREATEST/LEAST → same

        return sql

    def _convert_oracle_joins(self, sql: str) -> str:
        """Convert Oracle (+) join syntax to ANSI JOIN."""
        # This is complex for general cases; flag for manual review
        if "(+)" in sql:
            sql = sql.replace("(+)", "/* (+) → convert to LEFT/RIGHT JOIN */")
        return sql

    def _convert_decode(self, sql: str) -> str:
        """Convert DECODE(expr, val1, result1, val2, result2, ..., default) to CASE."""
        # Simple DECODE → CASE conversion
        def decode_to_case(match):
            inner = match.group(1)
            # This is a simplified converter; complex DECODEs need LLM
            return f"/* DECODE converted — verify: */ CASE /* {inner} */ END"

        sql = re.sub(r'\bDECODE\s*\((.+?)\)', decode_to_case, sql, flags=re.IGNORECASE | re.DOTALL)
        return sql

    def _convert_to_date(self, sql: str) -> str:
        """Convert TO_DATE(str, fmt) → PARSE_DATETIME(bq_fmt, str)."""
        def to_date_replace(match):
            args = match.group(1)
            return f"PARSE_DATETIME(/* convert Oracle format */{args})"

        sql = re.sub(r'\bTO_DATE\s*\((.+?)\)', to_date_replace, sql, flags=re.IGNORECASE)
        return sql

    def _convert_to_char(self, sql: str) -> str:
        """Convert TO_CHAR(date, fmt) → FORMAT_DATETIME(bq_fmt, date)."""
        def to_char_replace(match):
            args = match.group(1)
            return f"FORMAT_DATETIME(/* convert Oracle format */{args})"

        sql = re.sub(r'\bTO_CHAR\s*\((.+?)\)', to_char_replace, sql, flags=re.IGNORECASE)
        return sql

    def _convert_to_number(self, sql: str) -> str:
        """Convert TO_NUMBER(expr) → CAST(expr AS NUMERIC)."""
        sql = re.sub(
            r'\bTO_NUMBER\s*\((.+?)\)',
            r'CAST(\1 AS NUMERIC)',
            sql, flags=re.IGNORECASE
        )
        return sql

    def _convert_rownum(self, sql: str) -> str:
        """Convert ROWNUM references."""
        if re.search(r'\bROWNUM\b', sql, re.IGNORECASE):
            sql = re.sub(
                r'\bROWNUM\b',
                '/* ROWNUM → use ROW_NUMBER() OVER() or LIMIT */',
                sql, flags=re.IGNORECASE
            )
        return sql

    def _convert_sequences(self, sql: str) -> str:
        """Convert sequence.NEXTVAL/CURRVAL → GENERATE_UUID() or row counter."""
        sql = re.sub(
            r'(\w+)\.NEXTVAL',
            r'/* \1.NEXTVAL → use GENERATE_UUID() or FARM_FINGERPRINT() */',
            sql, flags=re.IGNORECASE
        )
        sql = re.sub(
            r'(\w+)\.CURRVAL',
            r'/* \1.CURRVAL → sequence removed, assign variable instead */',
            sql, flags=re.IGNORECASE
        )
        return sql

    def _convert_cursor_loops(self, sql: str) -> str:
        """Convert Oracle cursor FOR loops to BQ FOR...IN."""
        # Simple pattern: FOR rec IN cursor_name LOOP → FOR rec IN (SELECT ...) DO
        sql = re.sub(
            r'\bFOR\s+(\w+)\s+IN\s+(\w+)\s+LOOP',
            r'FOR \1 IN (\2) DO  -- Verify: replace cursor name with actual SELECT',
            sql, flags=re.IGNORECASE
        )
        sql = re.sub(r'\bEND\s+LOOP\s*;', 'END FOR;', sql, flags=re.IGNORECASE)
        return sql

    def _convert_exception_handlers(self, sql: str) -> str:
        """Convert Oracle EXCEPTION blocks to BQ EXCEPTION WHEN ERROR THEN."""
        # Oracle: EXCEPTION WHEN <name> THEN ... → BQ: EXCEPTION WHEN ERROR THEN
        sql = re.sub(
            r'\bEXCEPTION\s+WHEN\s+OTHERS\s+THEN',
            'EXCEPTION WHEN ERROR THEN',
            sql, flags=re.IGNORECASE
        )
        sql = re.sub(
            r'\bEXCEPTION\s+WHEN\s+NO_DATA_FOUND\s+THEN',
            'EXCEPTION WHEN ERROR THEN\n    -- Was: NO_DATA_FOUND',
            sql, flags=re.IGNORECASE
        )
        sql = re.sub(
            r'\bEXCEPTION\s+WHEN\s+(\w+)\s+THEN',
            r'EXCEPTION WHEN ERROR THEN\n    -- Was: \1',
            sql, flags=re.IGNORECASE
        )
        # Replace SQLERRM/SQLCODE with BQ equivalents
        sql = re.sub(r'\bSQLERRM\b', '@@error.message', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bSQLCODE\b', '@@error.statement_text', sql, flags=re.IGNORECASE)
        return sql

    def _add_config_var_references(self, sql: str, source_tables: list, target_tables: list) -> str:
        """Replace hardcoded schema.table references with ${config_var} pattern."""
        # For each source table, replace schema.table → `${src_project_id}.${src_dataset_name}.${src_<table>}`
        for table in source_tables:
            if "." in table:
                schema, tname = table.rsplit(".", 1)
                sql = sql.replace(
                    f"{schema}.{tname}",
                    f"`${{src_project_id}}.${{src_dataset_name}}.${{src_{tname}}}`"
                )
            else:
                sql = re.sub(
                    rf'\b{re.escape(table)}\b(?!`)',
                    f"`${{src_project_id}}.${{src_dataset_name}}.${{src_{table}}}`",
                    sql
                )
        return sql

    def _add_query_label(self, sql: str, target_tables: list) -> str:
        """Insert query_label block after DECLARE section."""
        # Build table_id entries
        table_id_parts = []
        for i, table in enumerate(target_tables[:5]):  # max 5
            tname = table.rsplit(".", 1)[-1] if "." in table else table
            key = "table_id" if i == 0 else f"table_id_{i}"
            table_id_parts.append(f"        {key}: ${{target_{tname}_snm}}")

        if not table_id_parts:
            table_id_parts.append("        table_id: ${target_main_table_snm}")

        table_id_block = ",\n".join(table_id_parts)
        query_label = textwrap.dedent(f"""\
    DECLARE run_time STRING;
    BEGIN

    SET run_time = (
        SELECT REGEXP_REPLACE(
            SUBSTR(CAST(CURRENT_TIMESTAMP() AS STRING), 1, 16),
            r'[^0-9]',
            ''
        )
    );
    SET @@query_label = FORMAT(
        \"\"\"etl_type: ${{etl_type}},
        application:${{application}},
        environment: ${{environment}},
        vsad: ${{vsad}},
        dataset_id: ${{target_dataset_name}},
{table_id_block},
        frequency: ${frequency}
        run_time: %s\"\"\",
        run_time
    );""")

        # Insert after the first BEGIN
        sql = re.sub(
            r'(BEGIN\s*\n)',
            f'\\1\n{query_label}\n\n',
            sql, count=1
        )
        return sql

    # ─────────────────────────────────────────────
    # LLM-Assisted Refinement
    # ─────────────────────────────────────────────

    def _llm_refine(self, oracle_sql: str, bq_sql: str, analysis: dict, proc_name: str) -> str:
        """Use LLM to refine the rule-based conversion."""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "prompts", "oracle_to_bq.txt"
        )
        if os.path.exists(prompt_path):
            from models.llm_client import LLMClient
            prompt = LLMClient.load_prompt_template(
                prompt_path,
                proc_name=proc_name,
                oracle_sql=oracle_sql,
                rule_based_bq_sql=bq_sql,
                complexity=analysis.get("complexity_score", {}),
                oracle_functions=str(analysis.get("oracle_functions", [])),
            )
        else:
            prompt = (
                f"Refine this Oracle-to-BigQuery SQL conversion.\n\n"
                f"## Original Oracle SQL:\n```sql\n{oracle_sql}\n```\n\n"
                f"## Rule-Based BQ Conversion:\n```sql\n{bq_sql}\n```\n\n"
                f"Fix any remaining Oracle syntax and ensure it's valid BigQuery SQL.\n"
                f"Return ONLY the corrected BigQuery SQL, no explanation."
            )

        system_prompt = (
            "You are an expert Oracle-to-BigQuery migration specialist. "
            "Fix any remaining Oracle-specific syntax in the converted SQL. "
            "Ensure it follows BigQuery stored procedure conventions. "
            "Return ONLY the corrected SQL code."
        )

        try:
            refined = self.llm_client.analyze(prompt, system_prompt)
            # Strip markdown code blocks if present
            if "```sql" in refined:
                start = refined.index("```sql") + 6
                end = refined.index("```", start)
                refined = refined[start:end].strip()
            elif "```" in refined:
                start = refined.index("```") + 3
                end = refined.index("```", start)
                refined = refined[start:end].strip()
            return refined
        except Exception as e:
            # Fallback to rule-based version
            return bq_sql + f"\n-- LLM refinement failed: {e}"

    # ─────────────────────────────────────────────
    # Generate Deployment Artifacts
    # ─────────────────────────────────────────────

    def _generate_deploy_configs(
        self,
        module_name: str,
        proc_name: str,
        source_tables: list,
        target_tables: list,
    ) -> dict:
        """Generate deployprd.cfg, deployuat.cfg, deploydev.cfg."""
        gcp = self.config.get("gcp", {})
        prod_project = gcp.get("prod_project_id", "vz-it-pr-gudv-dtwndo-0")
        dev_project = gcp.get("dev_project_id", "vz-it-np-gudv-dev-dtwndo-0")
        src_prod_project = gcp.get("src_prod_project_id", "vz-it-pr-i37v-ndlpr-0")
        src_dev_project = gcp.get("src_dev_project_id", "vz-it-pr-i37v-ndldo-0")
        target_dataset = gcp.get("target_dataset", "aid_nar_poc_tbls")
        src_dataset = gcp.get("src_dataset", "vzn_ndl_ien_core_tbls")

        envs = {
            "deployprd.cfg": {
                "environment": "prod",
                "target_project_id": prod_project,
                "src_project_id": src_prod_project,
                "src_dataset_name": src_dataset,
            },
            "deployuat.cfg": {
                "environment": "uat",
                "target_project_id": prod_project,
                "src_project_id": src_prod_project,
                "src_dataset_name": src_dataset,
            },
            "deploydev.cfg": {
                "environment": "dev",
                "target_project_id": dev_project,
                "src_project_id": src_dev_project,
                "src_dataset_name": f"{src_dataset}_rd_v",
            },
        }

        configs = {}
        for filename, env_cfg in envs.items():
            lines = []
            lines.append("")
            lines.append("# ============================================")
            lines.append("# QUERY LABEL METADATA")
            lines.append("# ============================================")
            lines.append(f"export etl_type=bq_sp")
            lines.append(f"export application={proc_name}")
            lines.append(f"export environment={env_cfg['environment']}")
            lines.append(f"export vsad=gudv")
            lines.append("")
            lines.append("# ============================================")
            lines.append("# SOURCE, TARGET DATASET & PROJECT ID")
            lines.append("# ============================================")
            lines.append(f"export src_project_id={env_cfg['src_project_id']}")
            lines.append(f"export src_dataset_name={env_cfg['src_dataset_name']}")
            lines.append(f"export target_project_id={env_cfg['target_project_id']}")
            lines.append(f"export target_dataset_name={target_dataset}")
            lines.append("")
            lines.append("# ============================================")
            lines.append("# SOURCE TABLE NAMES")
            lines.append("# ============================================")
            for table in source_tables:
                tname = table.rsplit(".", 1)[-1] if "." in table else table
                lines.append(f"export src_{tname}={tname}")
            lines.append("")
            lines.append("# ============================================")
            lines.append("# TARGET TABLE NAMES")
            lines.append("# ============================================")
            for table in target_tables:
                tname = table.rsplit(".", 1)[-1] if "." in table else table
                lines.append(f"export target_{tname}_snm={tname}")
            lines.append("")
            lines.append("# ============================================")
            lines.append("# STORED PROCEDURE NAME")
            lines.append("# ============================================")
            lines.append(f"export sp_name={proc_name}")
            lines.append("")

            configs[filename] = "\n".join(lines)

        return configs

    def _generate_dag_python(self, module_name: str, proc_name: str) -> str:
        """Generate Airflow DAG Python file following OneFiber conventions."""
        return textwrap.dedent(f'''\
# One Fiber - {module_name}
from datetime import datetime, timedelta
from airflow import DAG, AirflowException
import os, sys, yaml
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.bash import BashOperator
from airflow.operators.dummy import DummyOperator
from functools import partial
from google.cloud import bigquery
from airflow.composer.data_lineage.entities import BigQueryTable
from airflow.utils.email import send_email

# ---- Paths & Config ----
BASE_DIR = "/home/airflow/gcs/dags/vz-it-gudv-dtwndo-0/nar"
sys.path.append(f"{{BASE_DIR}}/{module_name}/python")
from DO_utils import publishLog, create_do_dict

project = os.environ[\'GCP_PROJECT\']
with open(f"{{BASE_DIR}}/{module_name}/config/base_config.yaml", \'r\') as file:
    base_config = yaml.full_load(file)
with open(f"{{BASE_DIR}}/{module_name}/config/{proc_name}.yml", \'r\') as file:
    dag_config = yaml.full_load(file)

config_values = {{}}
base_dict = dict(filter(lambda e: e[0] == project, base_config.items()))
app_dict  = dict(filter(lambda e: e[0] == project, dag_config.items()))

if base_dict:
    config_values = {{**config_values, **base_dict[project][0]}}
else:
    raise ValueError(f"No base config for project \'{{project}}\'. Available: {{list(base_config.keys())}}")

if app_dict:
    config_values = {{**config_values, **app_dict[project][0]}}
else:
    raise ValueError(f"No app config for project \'{{project}}\'. Available: {{list(dag_config.keys())}}")

# ---- Config Vars ----
GCP_PROJECT_ID = config_values[\'gcp_project\']
bq_connection_id = config_values[\'google_cloud_conn_id\']
DAG_ID = config_values[\'dag_id\']
raw_schedule = config_values.get(\'schedule_interval\')
if isinstance(raw_schedule, str) and raw_schedule.strip().lower() in {{"null", "none", "@none", "~", ""}}:
    schedule_interval = None
else:
    schedule_interval = raw_schedule
failure_email_alert_distro = config_values[\'failure_email_alert_distro\']
priority = config_values.get(\'priority\', \'BATCH\')
concurrency = int(config_values.get(\'concurrency\', 10))
max_active_runs = int(config_values.get(\'max_active_runs\', 1))

tgt_project = config_values[\'tgt_project_id\']
tgt_dataset = config_values[\'tgt_dataset_id\']
stored_proc = config_values.get(\'stored_proc\')

# ---- Helper Functions ----

def run_stored_proc(**context):
    """Execute the BigQuery stored procedure."""
    hook = BigQueryHook(gcp_conn_id=bq_connection_id, use_legacy_sql=False)
    client = hook.get_client(project_id=GCP_PROJECT_ID)
    query = f"CALL `{{tgt_project}}.{{tgt_dataset}}.{{stored_proc}}`()"
    job = client.query(query, project=GCP_PROJECT_ID, priority=priority)
    job.result()
    context[\'ti\'].xcom_push(key=\'job_id\', value=job.job_id)
    return job.job_id


def send_failure_email(context):
    """Send email on task failure."""
    subject = f"Airflow Alert: {{DAG_ID}} - Task {{context[\'task_instance\'].task_id}} Failed"
    body = f"""
    DAG: {{DAG_ID}}
    Task: {{context[\'task_instance\'].task_id}}
    Execution Date: {{context[\'execution_date\']}}
    Log URL: {{context[\'task_instance\'].log_url}}
    """
    send_email(to=failure_email_alert_distro, subject=subject, html_content=body)


# ---- DAG Definition ----
default_args = {{
    \'owner\': \'airflow\',
    \'depends_on_past\': False,
    \'retries\': 0,
    \'on_failure_callback\': send_failure_email,
}}

with DAG(
    dag_id=DAG_ID,
    default_args=default_args,
    schedule_interval=schedule_interval,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    concurrency=concurrency,
    max_active_runs=max_active_runs,
    tags=[\'onefiber\', \'{module_name}\'],
) as dag:

    start = DummyOperator(task_id=\'start\')

    run_sp = PythonOperator(
        task_id=\'run_{proc_name}\',
        python_callable=run_stored_proc,
        provide_context=True,
    )

    end = DummyOperator(
        task_id=\'end\',
        trigger_rule=\'all_success\',
    )

    start >> run_sp >> end
''')

    def _generate_dag_yaml(self, module_name: str, proc_name: str, source_tables: list) -> str:
        """Generate DAG YAML config (sp_<name>.yml)."""
        src_tables_str = ",".join(
            t.rsplit(".", 1)[-1] if "." in t else t
            for t in source_tables
        )
        gcp = self.config.get("gcp", {})
        dev_project = gcp.get("dev_project_id", "vz-it-np-gudv-dev-dtwndo-0")
        prod_project = gcp.get("prod_project_id", "vz-it-pr-gudv-dtwndo-0")
        src_dev_project = gcp.get("src_dev_project_id", "vz-it-pr-i37v-ndldo-0")
        src_prod_project = gcp.get("src_prod_project_id", "vz-it-pr-i37v-ndlpr-0")
        target_dataset = gcp.get("target_dataset", "aid_nar_poc_tbls")
        src_dev_dataset = gcp.get("src_dev_dataset", "vzn_ndl_ien_core_tbls_rd_v")
        src_prod_dataset = gcp.get("src_prod_dataset", "vzn_ndl_ien_core_tbls")

        dag_id = f"gudv_nar_onef_{module_name}"

        return textwrap.dedent(f"""\
vz-it-np-wdwg-dev-aidcom-0:
- dag_id: {dag_id}
  tgt_project_id: {dev_project}
  tgt_dataset_id: {target_dataset}
  stored_proc: {proc_name}
  schedule_interval: 'null'
  priority: BATCH
  ien_src_project_id: {src_dev_project}
  ien_src_dataset_id: {src_dev_dataset}
  src_tables: {src_tables_str}
vz-it-pr-wdwg-aidcom-0:
- dag_id: {dag_id}
  tgt_project_id: {prod_project}
  tgt_dataset_id: {target_dataset}
  stored_proc: {proc_name}
  schedule_interval: 'null'
  priority: BATCH
  ien_src_project_id: {src_prod_project}
  ien_src_dataset_id: {src_prod_dataset}
  src_tables: {src_tables_str}
""")

    def _generate_base_config(self, module_name: str) -> str:
        """Generate base_config.yaml for the module."""
        gcp = self.config.get("gcp", {})
        dev_project = gcp.get("dev_project_id", "vz-it-np-gudv-dev-dtwndo-0")
        prod_project = gcp.get("prod_project_id", "vz-it-pr-gudv-dtwndo-0")

        return textwrap.dedent(f"""\
vz-it-np-wdwg-dev-aidcom-0:
  - gcp_project: {dev_project}
    google_cloud_conn_id: sa-vz-it-gudv-dtwndo-0-app
    region: us-east4
    env: dev
    base_directory: gs://gudv-dev-dtwndo-0-usmr-warehouse/dtwin
    latest_tag: gs://source_tag/temp
    failure_email_alert_distro: your.email@verizon.com
    concurrency: 1
    max_active_runs: 1
    project_name: one_fiber
    system_name: {module_name}
    tool_name: GCP_BQ
    source_servername: vz-it-pr-i37v-ndldo-0
    target_servername: {dev_project}
    application_name: gudv_ndtwin
    target_environment: GCP_BQ

vz-it-pr-wdwg-aidcom-0:
  - gcp_project: {prod_project}
    google_cloud_conn_id: sa-vz-it-gudv-dtwndo-0-app
    env: prod
    base_directory: gs://gudv-prod-dtwndo-0-usmr-warehouse/dtwin
    region: us-east4
    latest_tag: gs://source_tag/temp
    failure_email_alert_distro: your.email@verizon.com
    concurrency: 1
    max_active_runs: 1
    project_name: one_fiber
    system_name: {module_name}
    tool_name: GCP_BQ
    source_servername: vz-it-pr-i37v-ndlpr-0
    target_servername: {prod_project}
    application_name: gudv_ndtwin
    target_environment: GCP_BQ
""")

    def _generate_conf_file(self, module_name: str, proc_name: str) -> str:
        """Generate the .conf file for Jenkins packaging."""
        return textwrap.dedent(f"""\
PRODUCT_NAME={module_name}
BASE_VERSION=1.0
ARTIFACTORY_REPO=https://oneartifactoryci.verizon.com/artifactory/gudv-maven-prod/dtwin/{module_name}/test/
SERVER_ID=oneci_dtwin
VERSION=`sh ./bin/auto_increment_version.sh -p ${{PRODUCT_NAME}} -b ${{BASE_VERSION}} -a ${{ARTIFACTORY_REPO}} -j ${{SERVER_ID}}`

# Assembly Folder
# f - - - |conf/gudv_{module_name}_assembly/|{module_name}/assembly/packages

# Coordinators Folder
# g - - - |conf/gudv_{module_name}/scripts/|{module_name}/pipelines/src/main/scripts/*
# g - - - |conf/gudv_{module_name}/bq_deploy_config/|{module_name}/pipelines/src/main/config/*
# g - - - |conf/gudv_{module_name}/sql/|{module_name}/pipelines/src/main/sql/*

#dag Folder
# g - - - |conf/gudv_{module_name}/dag/config/|{module_name}/dag/config/*
# g - - - |conf/gudv_{module_name}/dag/python/|{module_name}/dag/python/*

#dag Folder UAT
# g - - - |conf/gudv_{module_name}/dag/uat/config/|{module_name}/dag/uat/config/*
# g - - - |conf/gudv_{module_name}/dag/uat/python/|{module_name}/dag/uat/python/*
""")

    def _generate_deploy_scripts(self) -> dict:
        """Generate standard deployment shell scripts."""
        run_bq_ddl = textwrap.dedent("""\
#!/bin/bash
HOME_DIR=`pwd`
LOGDIR=$HOME_DIR/bq_deploy/logs
PROCESS=$(basename ${0%.*})
DATE=`date +"%Y%m%d"`
LOGFILE=$LOGDIR/$PROCESS.$DATE.log

    if [[ -z "$1" ]] ; then
        echo "Incorrect number of inputs";
        echo "Usage: `basename $0` deploydev.cfg";
        exit 0;
    fi

mkdir -p $LOGDIR

scriptlogger(){
DT=`date +"%Y/%m/%d %H:%M:%S"`
echo "[$2][$3][$DT] $4" >> $1
}

 scriptlogger $LOGFILE $PROCESS $$ "started script to create bq objects using config file $1"

source $HOME_DIR/config/$1

cd $HOME_DIR/sql
file_list=$(ls -1f *.[sh]ql 2>/dev/null)

for file in $file_list
  do
          if grep -iqw "drop" $file
          then
                 echo "$file contains DROP statement, please fix/remove and retry."
                 scriptlogger $LOGFILE $PROCESS $$ "ERROR: $file not executed due to DROP statement."
                 scriptlogger $LOGFILE $PROCESS $$ "Process failed"
                 exit $rc;
          else
                 echo "check and replace the project_id,dataset and table_name placeholders"
                         scriptlogger $LOGFILE $PROCESS $$ "Running bq deploy for $file "
                         cat $file | envsubst > $LOGDIR/query_out.sql
                         bq query --nouse_legacy_sql -q=true "$(< $LOGDIR/query_out.sql)" >>$LOGFILE 2>&1
                         rc=$?
                           if [[ $rc -ne 0 ]]
                               then
                                 scriptlogger $LOGFILE $PROCESS $$ "ERROR: while running bq query."
                                 scriptlogger $LOGFILE $PROCESS $$ "Process failed"
                                 exit $rc;
                           else
                             scriptlogger $LOGFILE $PROCESS $$ "deleting processed $file"
                           fi
          fi
  done;

scriptlogger $LOGFILE $PROCESS $$ "Process completed"
exit $?
""")

        run_copy_to_gcs = textwrap.dedent("""\
#!/bin/bash
# Copy DAG files to GCS for Composer deployment
while getopts C:E: flag; do
    case "${flag}" in
        C) CONFIG=${OPTARG};;
        E) ENVIRONMENT=${OPTARG};;
    esac
done

if [[ -z "$CONFIG" || -z "$ENVIRONMENT" ]]; then
    echo "Usage: $0 -C <config_file> -E <environment>"
    exit 1
fi

source $CONFIG

echo "Copying DAG files to GCS: $GCS_DAG_LOCATION"
gsutil -m cp -r python/* $GCS_DAG_LOCATION/python/
gsutil -m cp -r config/* $GCS_DAG_LOCATION/config/
echo "DAG deployment complete for $ENVIRONMENT"
""")

        return {
            "run_bq_ddl_deploy.sh": run_bq_ddl,
            "run_copy_to_gcs.sh": run_copy_to_gcs,
        }

    # ─────────────────────────────────────────────
    # Report Generation
    # ─────────────────────────────────────────────

    def _build_report(self, analysis: dict, bq_sql: str, proc_name: str, module_name: str) -> dict:
        """Build a conversion report."""
        complexity = analysis.get("complexity_score", {})
        oracle_funcs = analysis.get("oracle_functions", [])
        manual_items = [f for f in oracle_funcs if f.get("needs_manual_review")]

        return {
            "module_name": module_name,
            "procedure_name": proc_name,
            "complexity": complexity,
            "oracle_functions_converted": len(oracle_funcs) - len(manual_items),
            "functions_needing_manual_review": [f["oracle_function"] for f in manual_items],
            "has_cursors": len(analysis.get("cursors", [])) > 0,
            "has_dynamic_sql": analysis.get("has_dynamic_sql", False),
            "has_sequences": len(analysis.get("sequences_used", [])) > 0,
            "has_oracle_joins": len(analysis.get("oracle_join_syntax", [])) > 0,
            "total_dml_operations": len(analysis.get("dml_operations", [])),
            "total_tables_referenced": len(analysis.get("table_references", [])),
            "bq_sql_lines": len(bq_sql.splitlines()),
            "files_generated": [
                f"{module_name}/pipelines/src/main/sql/{proc_name}.sql",
                f"{module_name}/pipelines/src/main/config/deployprd.cfg",
                f"{module_name}/pipelines/src/main/config/deployuat.cfg",
                f"{module_name}/pipelines/src/main/config/deploydev.cfg",
                f"{module_name}/pipelines/src/main/scripts/run_bq_ddl_deploy.sh",
                f"{module_name}/pipelines/src/main/scripts/run_copy_to_gcs.sh",
                f"{module_name}/dag/python/{proc_name}.py",
                f"{module_name}/dag/python/DO_utils.py",
                f"{module_name}/dag/config/{proc_name}.yml",
                f"{module_name}/dag/config/base_config.yaml",
                f"{module_name}.conf",
            ],
            "review_checklist": self._build_review_checklist(analysis),
        }

    def _build_review_checklist(self, analysis: dict) -> list:
        """Build a checklist of items that need human review."""
        checklist = []

        manual_funcs = [f for f in analysis.get("oracle_functions", []) if f.get("needs_manual_review")]
        for f in manual_funcs:
            checklist.append(f"⚠️  Review: {f['oracle_function']} has no direct BQ equivalent ({f['occurrences']} occurrences)")

        if analysis.get("has_dynamic_sql"):
            checklist.append("⚠️  Review: Dynamic SQL (EXECUTE IMMEDIATE) needs manual conversion")

        if analysis.get("has_autonomous_transaction"):
            checklist.append("⚠️  Review: PRAGMA AUTONOMOUS_TRANSACTION has no BQ equivalent")

        if analysis.get("has_bulk_operations"):
            checklist.append("⚠️  Review: BULK COLLECT/FORALL needs manual conversion to set-based operations")

        for cursor in analysis.get("cursors", []):
            checklist.append(f"⚠️  Review: Cursor '{cursor['name']}' — verify FOR...IN conversion")

        for seq in analysis.get("sequences_used", []):
            checklist.append(f"⚠️  Review: Sequence '{seq}' — replace with GENERATE_UUID() or counter logic")

        if analysis.get("oracle_join_syntax"):
            checklist.append(f"⚠️  Review: {len(analysis['oracle_join_syntax'])} Oracle (+) joins need ANSI JOIN conversion")

        if not checklist:
            checklist.append("✅ No items requiring manual review — straightforward conversion")

        return checklist
