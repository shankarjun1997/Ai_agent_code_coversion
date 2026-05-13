"""MySQL source provider — pymysql."""
from __future__ import annotations
import asyncio, time
from typing import Any, List
from urllib.parse import urlparse
import pymysql
from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo, ColumnProfile, ColumnHit,
)

def _parse(dsn: str) -> dict:
    u = urlparse(dsn)
    return dict(host=u.hostname or "localhost", port=u.port or 3306,
                user=u.username or "", password=u.password or "",
                database=(u.path or "/").lstrip("/"), charset="utf8mb4", connect_timeout=5)

class MySQLProvider(SourceProvider):
    dialect = "mysql"

    def _connect(self, profile: Any):
        return pymysql.connect(**_parse(profile.dsn))

    async def ping(self, profile: Any) -> PingResult:
        def _s():
            t0=time.perf_counter()
            try:
                self._connect(profile).close()
                return PingResult(ok=True,latency_ms=int((time.perf_counter()-t0)*1000))
            except Exception as e:
                return PingResult(ok=False,message=str(e))
        return await asyncio.to_thread(_s)

    async def list_schemas(self, profile: Any) -> List[str]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('mysql','sys','performance_schema','information_schema') ORDER BY schema_name")
                return [r[0] for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("SELECT table_name,table_rows,table_comment FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",(schema,))
                return [TableInfo(schema=schema,name=r[0],row_estimate=r[1],comment=r[2] or None) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("SELECT column_name,data_type,is_nullable,column_default,column_key FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",(schema,table))
                return [ColumnInfo(schema=schema,table=table,name=r[0],data_type=r[1],nullable=(r[2]=="YES"),default=r[3],is_primary_key=(r[4]=="PRI")) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("SELECT column_name,referenced_table_schema,referenced_table_name,referenced_column_name,constraint_name FROM information_schema.key_column_usage WHERE table_schema=%s AND table_name=%s AND referenced_table_name IS NOT NULL",(schema,table))
                return [FKInfo(schema=schema,table=table,column=r[0],ref_schema=r[1],ref_table=r[2],ref_column=r[3],constraint_name=r[4]) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def profile_column(self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0) -> ColumnProfile:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute(f"SELECT COUNT(*),COUNT(DISTINCT `{column}`),100*AVG(CASE WHEN `{column}` IS NULL THEN 1 ELSE 0 END) FROM `{schema}`.`{table}`")
                rc,dc,np=cur.fetchone(); samples=[]
                if sample_rows>0:
                    cur.execute(f"SELECT `{column}` FROM `{schema}`.`{table}` WHERE `{column}` IS NOT NULL LIMIT {int(sample_rows)}")
                    samples=[r[0] for r in cur.fetchall()]
                return ColumnProfile(row_count=rc,distinct_count=dc,null_pct=float(np) if np else None,sample_values=samples)
        return await asyncio.to_thread(_s)

    async def search_by_keywords(self, profile: Any, keywords: List[str], limit: int = 50) -> List[ColumnHit]:
        def _s():
            if not keywords: return []
            patterns=[f"%{k.lower()}%" for k in keywords]
            clauses=" OR ".join(["LOWER(column_name) LIKE %s"]*len(patterns))
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute(f"SELECT table_schema,table_name,column_name,data_type FROM information_schema.columns WHERE table_schema NOT IN ('mysql','sys','performance_schema','information_schema') AND ({clauses}) LIMIT %s",(*patterns,limit))
                return [ColumnHit(schema=r[0],table=r[1],column=r[2],data_type=r[3],score=1.0,matched_on="name") for r in cur.fetchall()]
        return await asyncio.to_thread(_s)
