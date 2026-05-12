"""Postgres schema discovery via information_schema (read-only)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


class PostgresProvider:
    """Reads schema metadata from a Postgres database. No DDL/DML."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    async def _connect(self) -> asyncpg.Connection:
        return await asyncpg.connect(self.dsn)

    async def ping(self) -> Dict[str, Any]:
        conn = await self._connect()
        try:
            version = await conn.fetchval("SELECT version()")
            current_db = await conn.fetchval("SELECT current_database()")
            return {"ok": True, "version": version, "database": current_db}
        finally:
            await conn.close()

    async def list_schemas(self) -> List[Dict[str, Any]]:
        """Return non-system schemas with table counts."""
        sql = """
            SELECT
                n.nspname                                     AS schema_name,
                COUNT(c.oid) FILTER (WHERE c.relkind='r')     AS table_count
            FROM pg_namespace n
            LEFT JOIN pg_class c ON c.relnamespace = n.oid
            WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
              AND n.nspname NOT LIKE 'pg_temp_%'
              AND n.nspname NOT LIKE 'pg_toast_temp_%'
            GROUP BY n.nspname
            ORDER BY n.nspname
        """
        conn = await self._connect()
        try:
            rows = await conn.fetch(sql)
            return [{"name": r["schema_name"], "table_count": r["table_count"]} for r in rows]
        finally:
            await conn.close()

    async def list_tables(self, schema: str) -> List[Dict[str, Any]]:
        """Return tables in a schema with row estimates and last-modified."""
        sql = """
            SELECT
                c.relname                                  AS table_name,
                obj_description(c.oid)                     AS description,
                c.reltuples::bigint                        AS row_estimate,
                pg_size_pretty(pg_total_relation_size(c.oid)) AS size_pretty,
                CASE
                    WHEN c.relname LIKE '%audit%' OR c.relname LIKE '%log%' THEN 'audit'
                    WHEN c.relname IN ('orders','order_items','invoices','payments','sales','transactions') THEN 'fact'
                    WHEN c.relname IN ('customers','products','sales_reps','reps','dim_date') THEN 'dim'
                    ELSE 'table'
                END                                        AS classification
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = $1
              AND c.relkind = 'r'
            ORDER BY c.relname
        """
        conn = await self._connect()
        try:
            rows = await conn.fetch(sql, schema)
            return [
                {
                    "name": r["table_name"],
                    "description": r["description"],
                    "rows": int(r["row_estimate"] or 0),
                    "size": r["size_pretty"],
                    "tag": r["classification"],
                }
                for r in rows
            ]
        finally:
            await conn.close()

    async def get_columns(self, schema: str, table: str) -> List[Dict[str, Any]]:
        """Return column metadata for a table."""
        sql = """
            SELECT
                a.attnum                                AS ordinal,
                a.attname                               AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                NOT a.attnotnull                        AS is_nullable,
                col_description(a.attrelid, a.attnum)   AS description,
                CASE
                    WHEN i.indisprimary THEN TRUE ELSE FALSE
                END                                     AS is_primary_key
            FROM pg_attribute a
            JOIN pg_class c        ON c.oid = a.attrelid
            JOIN pg_namespace n    ON n.oid = c.relnamespace
            LEFT JOIN pg_index i   ON i.indrelid = c.oid AND a.attnum = ANY(i.indkey) AND i.indisprimary
            WHERE n.nspname = $1
              AND c.relname = $2
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
        """
        conn = await self._connect()
        try:
            rows = await conn.fetch(sql, schema, table)
            return [
                {
                    "ordinal": r["ordinal"],
                    "name": r["column_name"],
                    "type": r["data_type"],
                    "nullable": r["is_nullable"],
                    "description": r["description"],
                    "is_primary_key": r["is_primary_key"],
                }
                for r in rows
            ]
        finally:
            await conn.close()


import asyncio
import time
from typing import Any, List
from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo,
    ColumnProfile, ColumnHit,
)


class PostgresProviderAsync(SourceProvider):
    """Async SourceProvider wrapper for Postgres discovery."""
    dialect = "postgres"

    async def ping(self, profile: Any) -> PingResult:
        def _sync():
            t0 = time.perf_counter()
            try:
                import asyncpg
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    conn = loop.run_until_complete(asyncpg.connect(profile.dsn, timeout=5))
                    loop.run_until_complete(conn.close())
                    return PingResult(ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
                finally:
                    loop.close()
            except Exception as exc:
                return PingResult(ok=False, message=str(exc))
        return await asyncio.to_thread(_sync)

    async def list_schemas(self, profile: Any) -> List[str]:
        def _sync():
            import asyncpg
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _query():
                    conn = await asyncpg.connect(profile.dsn)
                    try:
                        rows = await conn.fetch("""
                            SELECT schema_name FROM information_schema.schemata
                            WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
                            ORDER BY schema_name
                        """)
                        return [r[0] for r in rows]
                    finally:
                        await conn.close()
                return loop.run_until_complete(_query())
            finally:
                loop.close()
        return await asyncio.to_thread(_sync)

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _sync():
            import asyncpg
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _query():
                    conn = await asyncpg.connect(profile.dsn)
                    try:
                        rows = await conn.fetch("""
                            SELECT table_name FROM information_schema.tables
                            WHERE table_schema = $1 AND table_type='BASE TABLE'
                            ORDER BY table_name
                        """, schema)
                        return [TableInfo(schema=schema, name=r[0]) for r in rows]
                    finally:
                        await conn.close()
                return loop.run_until_complete(_query())
            finally:
                loop.close()
        return await asyncio.to_thread(_sync)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _sync():
            import asyncpg
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _query():
                    conn = await asyncpg.connect(profile.dsn)
                    try:
                        rows = await conn.fetch("""
                            SELECT c.column_name, c.data_type, c.is_nullable, c.column_default,
                                   CASE WHEN tc.constraint_type='PRIMARY KEY' THEN TRUE ELSE FALSE END AS is_pk
                            FROM information_schema.columns c
                            LEFT JOIN information_schema.key_column_usage kcu
                              ON kcu.table_schema=c.table_schema AND kcu.table_name=c.table_name AND kcu.column_name=c.column_name
                            LEFT JOIN information_schema.table_constraints tc
                              ON tc.constraint_name=kcu.constraint_name AND tc.constraint_type='PRIMARY KEY'
                            WHERE c.table_schema=$1 AND c.table_name=$2
                            ORDER BY c.ordinal_position
                        """, schema, table)
                        return [
                            ColumnInfo(
                                schema=schema, table=table, name=r[0],
                                data_type=r[1], nullable=(r[2] == "YES"),
                                default=r[3], is_primary_key=bool(r[4]),
                            )
                            for r in rows
                        ]
                    finally:
                        await conn.close()
                return loop.run_until_complete(_query())
            finally:
                loop.close()
        return await asyncio.to_thread(_sync)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        def _sync():
            import asyncpg
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _query():
                    conn = await asyncpg.connect(profile.dsn)
                    try:
                        rows = await conn.fetch("""
                            SELECT kcu.column_name, ccu.table_schema, ccu.table_name, ccu.column_name, tc.constraint_name
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu USING (constraint_name, table_schema)
                            JOIN information_schema.constraint_column_usage ccu USING (constraint_name, table_schema)
                            WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema=$1 AND tc.table_name=$2
                        """, schema, table)
                        return [
                            FKInfo(schema=schema, table=table, column=r[0],
                                   ref_schema=r[1], ref_table=r[2], ref_column=r[3], constraint_name=r[4])
                            for r in rows
                        ]
                    finally:
                        await conn.close()
                return loop.run_until_complete(_query())
            finally:
                loop.close()
        return await asyncio.to_thread(_sync)

    async def profile_column(self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0) -> ColumnProfile:
        def _sync():
            import asyncpg
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _query():
                    conn = await asyncpg.connect(profile.dsn)
                    try:
                        row = await conn.fetchrow(f'SELECT COUNT(*) as rc, COUNT(DISTINCT "{column}") as dc, 100.0 * AVG(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END) as np FROM "{schema}"."{table}"')
                        rc, dc, np_ = row[0], row[1], float(row[2]) if row[2] is not None else None
                        samples = []
                        if sample_rows > 0:
                            sample_rows_data = await conn.fetch(f'SELECT "{column}" FROM "{schema}"."{table}" WHERE "{column}" IS NOT NULL LIMIT {int(sample_rows)}')
                            samples = [r[0] for r in sample_rows_data]
                        return ColumnProfile(row_count=rc, distinct_count=dc, null_pct=np_, sample_values=samples)
                    finally:
                        await conn.close()
                return loop.run_until_complete(_query())
            finally:
                loop.close()
        return await asyncio.to_thread(_sync)

    async def search_by_keywords(self, profile: Any, keywords: List[str], limit: int = 50) -> List[ColumnHit]:
        def _sync():
            if not keywords:
                return []
            import asyncpg
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _query():
                    conn = await asyncpg.connect(profile.dsn)
                    try:
                        patterns = [f"%{k.lower()}%" for k in keywords]
                        placeholders = " OR ".join([f"LOWER(column_name) LIKE ${i+1}" for i in range(len(patterns))])
                        sql = f"""
                            SELECT table_schema, table_name, column_name, data_type
                            FROM information_schema.columns
                            WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
                              AND ({placeholders})
                            ORDER BY table_schema, table_name, ordinal_position
                            LIMIT ${len(patterns)+1}
                        """
                        rows = await conn.fetch(sql, *patterns, limit)
                        return [ColumnHit(schema=r[0], table=r[1], column=r[2], data_type=r[3], score=1.0, matched_on="name") for r in rows]
                    finally:
                        await conn.close()
                return loop.run_until_complete(_query())
            finally:
                loop.close()
        return await asyncio.to_thread(_sync)
