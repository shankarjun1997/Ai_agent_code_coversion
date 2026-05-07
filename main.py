import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from google.cloud import bigquery
from jira import JIRA
from openai import OpenAI


@dataclass
class GeneratedSql:
    sql: str
    explanation: str
    raw_response: str


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def get_jira_issue_context(issue_key: str) -> Dict[str, str]:
    jira_url = _require_env("JIRA_URL")
    jira_email = _require_env("JIRA_EMAIL")
    jira_api_token = _require_env("JIRA_API_TOKEN")

    jira = JIRA(server=jira_url, basic_auth=(jira_email, jira_api_token))
    issue = jira.issue(issue_key)

    summary = getattr(issue.fields, "summary", "") or ""
    description = getattr(issue.fields, "description", "") or ""
    acceptance_criteria = ""

    # Some Jira projects store acceptance criteria in custom fields.
    if os.getenv("JIRA_ACCEPTANCE_CRITERIA_FIELD"):
        custom_field_name = os.getenv("JIRA_ACCEPTANCE_CRITERIA_FIELD")
        acceptance_criteria = getattr(issue.fields, custom_field_name, "") or ""

    return {
        "issue_key": issue_key,
        "summary": summary.strip(),
        "description": str(description).strip(),
        "acceptance_criteria": str(acceptance_criteria).strip(),
    }


def _extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", text.lower())
    stopwords = {
        "this",
        "that",
        "with",
        "from",
        "where",
        "when",
        "then",
        "have",
        "into",
        "for",
        "and",
        "the",
        "user",
        "story",
        "jira",
        "data",
        "table",
        "query",
        "metric",
        "should",
        "must",
    }
    deduped = []
    seen = set()
    for word in words:
        if word in stopwords or word in seen:
            continue
        seen.add(word)
        deduped.append(word)
        if len(deduped) >= max_keywords:
            break
    return deduped


def get_schema_context(
    bq_client: bigquery.Client, project_id: str, dataset: str, story_text: str
) -> str:
    keywords = _extract_keywords(story_text)
    like_predicates = " OR ".join(
        [f"LOWER(column_name) LIKE '%{kw}%'" for kw in keywords]
        + [f"LOWER(table_name) LIKE '%{kw}%'" for kw in keywords]
    )

    if not like_predicates:
        like_predicates = "TRUE"

    query = f"""
        SELECT
            table_name,
            column_name,
            data_type
        FROM `{project_id}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
        WHERE {like_predicates}
        ORDER BY table_name, ordinal_position
        LIMIT 500
    """
    rows = bq_client.query(query).result()

    collected = []
    for row in rows:
        collected.append(
            {
                "table_name": row["table_name"],
                "column_name": row["column_name"],
                "data_type": row["data_type"],
            }
        )

    if not collected:
        fallback_query = f"""
            SELECT
                table_name,
                column_name,
                data_type
            FROM `{project_id}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
            ORDER BY table_name, ordinal_position
            LIMIT 200
        """
        fallback_rows = bq_client.query(fallback_query).result()
        for row in fallback_rows:
            collected.append(
                {
                    "table_name": row["table_name"],
                    "column_name": row["column_name"],
                    "data_type": row["data_type"],
                }
            )

    return json.dumps(collected, indent=2)


def _build_prompt(
    issue_context: Dict[str, str], schema_context: str, previous_error: Optional[str]
) -> str:
    retry_instruction = ""
    if previous_error:
        retry_instruction = (
            "The previous SQL failed BigQuery dry run with this error:\n"
            f"{previous_error}\n"
            "Fix the SQL based on this error.\n"
        )

    return f"""
You are an expert Analytics Engineer writing BigQuery SQL.

Task:
- Generate one valid BigQuery Standard SQL query that satisfies the Jira story.
- Return STRICT JSON with exactly two keys:
  - "sql": the SQL text
  - "explanation": one short paragraph

Rules:
- Use only tables/columns from provided schema context.
- Prefer readable SQL with CTEs.
- Do not include markdown fences.
- JSON only, no extra keys, no commentary outside JSON.

Jira issue: {issue_context["issue_key"]}
Summary: {issue_context["summary"]}
Description:
{issue_context["description"]}

Acceptance criteria:
{issue_context["acceptance_criteria"] or "(not provided)"}

Schema context (JSON):
{schema_context}

{retry_instruction}
""".strip()


def generate_sql_with_llm(
    llm_client: OpenAI,
    model: str,
    issue_context: Dict[str, str],
    schema_context: str,
    previous_error: Optional[str] = None,
) -> GeneratedSql:
    prompt = _build_prompt(issue_context, schema_context, previous_error)

    response = llm_client.responses.create(
        model=model,
        input=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        temperature=0.1,
    )
    raw_text = response.output_text.strip()

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as err:
        raise ValueError(
            f"LLM did not return valid JSON. Raw output:\n{raw_text}"
        ) from err

    sql = payload.get("sql")
    explanation = payload.get("explanation")
    if not sql or not explanation:
        raise ValueError(
            f"LLM JSON missing required keys 'sql' and/or 'explanation': {payload}"
        )

    return GeneratedSql(sql=sql.strip(), explanation=explanation.strip(), raw_response=raw_text)


def dry_run_sql(
    bq_client: bigquery.Client, sql: str
) -> Tuple[bool, Optional[int], Optional[str]]:
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)

    try:
        query_job = bq_client.query(sql, job_config=job_config)
        return True, query_job.total_bytes_processed, None
    except Exception as err:  # noqa: BLE001 - surfaced to retry loop
        return False, None, str(err)


def run_pipeline(issue_key: str, max_retries: int) -> None:
    project_id = _require_env("BQ_PROJECT_ID")
    dataset = _require_env("BQ_DATASET")
    openai_api_key = _require_env("OPENAI_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4.1-mini")

    bq_client = bigquery.Client(project=project_id)
    llm_client = OpenAI(api_key=openai_api_key)

    issue_context = get_jira_issue_context(issue_key)
    story_blob = (
        f"{issue_context['summary']}\n{issue_context['description']}\n"
        f"{issue_context['acceptance_criteria']}"
    )
    schema_context = get_schema_context(bq_client, project_id, dataset, story_blob)

    attempt = 0
    last_error: Optional[str] = None
    last_generation: Optional[GeneratedSql] = None

    while attempt <= max_retries:
        attempt += 1
        print(f"\n--- Attempt {attempt}/{max_retries + 1} ---")

        generation = generate_sql_with_llm(
            llm_client=llm_client,
            model=model,
            issue_context=issue_context,
            schema_context=schema_context,
            previous_error=last_error,
        )
        last_generation = generation

        valid, bytes_scanned, dry_run_error = dry_run_sql(bq_client, generation.sql)
        if valid:
            print("\nDry run successful.")
            print(f"Estimated bytes scanned: {bytes_scanned:,}")
            print("\nGenerated SQL:\n")
            print(generation.sql)
            print("\nExplanation:\n")
            print(generation.explanation)
            return

        last_error = dry_run_error
        print("\nDry run failed. Error:")
        print(last_error)

    raise RuntimeError(
        "Pipeline failed after all retries.\n"
        f"Last error: {last_error}\n"
        f"Last LLM response: {last_generation.raw_response if last_generation else 'N/A'}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="POC SQL generation pipeline: Jira -> schema -> LLM -> BigQuery dry run"
    )
    parser.add_argument("--issue-key", required=True, help="Jira issue key, e.g. DATA-1042")
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="How many LLM repair retries after initial attempt",
    )
    return parser.parse_args()


if __name__ == "__main__":
    load_dotenv()
    args = parse_args()
    run_pipeline(issue_key=args.issue_key, max_retries=args.max_retries)
