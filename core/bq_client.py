"""BigQuery client wrapper — schema discovery, dry-run, and execution."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery


class BQClient:
    def __init__(self, project_id: str):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id

    # ── Discovery ─────────────────────────────────────────────────────────────

    def get_all_datasets(self) -> List[str]:
        return [ds.dataset_id for ds in self.client.list_datasets()]

    def get_tables_in_dataset(self, dataset: str) -> List[str]:
        try:
            return [t.table_id for t in self.client.list_tables(dataset)]
        except Exception:
            return []

    def search_schema(self, dataset: str, keywords: List[str]) -> List[Dict]:
        """Keyword search over INFORMATION_SCHEMA.COLUMNS."""
        if not keywords:
            return []
        kw_lower = [k.lower() for k in keywords]
        col_preds = " OR ".join(f"LOWER(column_name) LIKE '%{k}%'" for k in kw_lower)
        tbl_preds = " OR ".join(f"LOWER(table_name) LIKE '%{k}%'" for k in kw_lower)
        query = f"""
            SELECT table_name, column_name, data_type, is_nullable
            FROM `{self.project_id}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
            WHERE {col_preds} OR {tbl_preds}
            ORDER BY table_name, ordinal_position
            LIMIT 400
        """
        try:
            return [dict(r) for r in self.client.query(query).result()]
        except Exception as exc:
            return [{"error": str(exc)}]

    def get_table_schema(self, dataset: str, table: str) -> List[Dict]:
        """Full column list for a specific table."""
        query = f"""
            SELECT column_name, data_type, is_nullable, column_default
            FROM `{self.project_id}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = '{table}'
            ORDER BY ordinal_position
        """
        try:
            return [dict(r) for r in self.client.query(query).result()]
        except Exception as exc:
            return [{"error": str(exc)}]

    def get_table_partitioning(self, dataset: str, table: str) -> Optional[Dict]:
        """Return partitioning/clustering info for a table."""
        query = f"""
            SELECT ddl
            FROM `{self.project_id}.{dataset}.INFORMATION_SCHEMA.TABLES`
            WHERE table_name = '{table}'
        """
        try:
            rows = list(self.client.query(query).result())
            return {"ddl": rows[0]["ddl"]} if rows else None
        except Exception:
            return None

    def get_row_count(self, dataset: str, table: str) -> Optional[int]:
        query = f"SELECT COUNT(*) AS cnt FROM `{self.project_id}.{dataset}.{table}`"
        try:
            rows = list(self.client.query(query).result())
            return rows[0]["cnt"] if rows else None
        except Exception:
            return None

    def get_sample_rows(self, dataset: str, table: str, n: int = 5) -> List[Dict]:
        query = f"SELECT * FROM `{self.project_id}.{dataset}.{table}` LIMIT {n}"
        try:
            return [dict(r) for r in self.client.query(query).result()]
        except Exception:
            return []

    # ── Validation ────────────────────────────────────────────────────────────

    def dry_run(self, sql: str) -> Tuple[bool, Optional[int], Optional[str]]:
        """Return (valid, bytes_processed, error_message)."""
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        try:
            job = self.client.query(sql, job_config=job_config)
            return True, job.total_bytes_processed, None
        except Exception as exc:
            return False, None, str(exc)

    # ── Execution ─────────────────────────────────────────────────────────────

    def run_query(self, sql: str) -> List[Dict]:
        rows = self.client.query(sql).result()
        return [dict(r) for r in rows]

    def schema_as_json(self, dataset: str, keywords: List[str]) -> str:
        """Convenience: return schema search result as formatted JSON string."""
        return json.dumps(self.search_schema(dataset, keywords), indent=2)
