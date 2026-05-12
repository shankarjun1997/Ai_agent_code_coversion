"""BigQuery provider wrapping core/bq_client.py."""
from __future__ import annotations

import asyncio
import time
from typing import Any, List

from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo,
    ColumnProfile, ColumnHit,
)


class BigQueryProvider(SourceProvider):
    dialect = "bigquery"

    def _client(self, profile: Any):
        from core.bq_client import BQClient
        return BQClient(project_id=profile.dsn or "")

    async def ping(self, profile: Any) -> PingResult:
        def _sync():
            t0 = time.perf_counter()
            try:
                self._client(profile).get_all_datasets()
                return PingResult(ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
            except Exception as exc:
                return PingResult(ok=False, message=str(exc))
        return await asyncio.to_thread(_sync)

    async def list_schemas(self, profile: Any) -> List[str]:
        return await asyncio.to_thread(lambda: self._client(profile).get_all_datasets())

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _sync():
            names = self._client(profile).get_tables_in_dataset(schema)
            return [TableInfo(schema=schema, name=n) for n in names]
        return await asyncio.to_thread(_sync)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _sync():
            rows = self._client(profile).get_table_schema(schema, table)
            return [
                ColumnInfo(
                    schema=schema, table=table, name=r["column_name"],
                    data_type=r["data_type"], nullable=(r.get("is_nullable") == "YES"),
                    default=r.get("column_default"),
                )
                for r in rows if "error" not in r
            ]
        return await asyncio.to_thread(_sync)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        return []

    async def profile_column(self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0) -> ColumnProfile:
        def _sync():
            client = self._client(profile)
            rc = client.get_row_count(schema, table)
            samples = []
            if sample_rows > 0:
                samples = [r.get(column) for r in client.get_sample_rows(schema, table, n=sample_rows)]
            return ColumnProfile(row_count=rc, sample_values=samples)
        return await asyncio.to_thread(_sync)

    async def search_by_keywords(self, profile: Any, keywords: List[str], limit: int = 50) -> List[ColumnHit]:
        def _sync():
            client = self._client(profile)
            hits: List[ColumnHit] = []
            for ds in client.get_all_datasets():
                for r in client.search_schema(ds, keywords):
                    if "error" in r:
                        continue
                    hits.append(ColumnHit(schema=ds, table=r["table_name"], column=r["column_name"], data_type=r["data_type"], score=1.0, matched_on="name"))
                    if len(hits) >= limit:
                        return hits
            return hits
        return await asyncio.to_thread(_sync)
