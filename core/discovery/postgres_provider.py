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
