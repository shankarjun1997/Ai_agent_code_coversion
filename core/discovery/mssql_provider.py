"""MSSQL source provider — pure-Python pytds."""
from __future__ import annotations
import asyncio, time
from typing import Any, List
from urllib.parse import urlparse
import pytds
from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo, ColumnProfile, ColumnHit,
)

def _parse(dsn: str) -> dict:
    u = urlparse(dsn)
    return dict(server=u.hostname or "localhost", port=u.port or 1433,
                user=u.username or "", password=u.password or "",
                database=(u.path or "/").lstrip("/"), login_timeout=5, timeout=10)

class MSSQLProvider(SourceProvider):
    dialect = "mssql"

    def _connect(self, profile: Any):
        return pytds.connect(**_parse(profile.dsn))

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
                cur.execute("SELECT name FROM sys.schemas WHERE name NOT IN ('sys','INFORMATION_SCHEMA','db_owner','db_accessadmin','db_securityadmin','db_ddladmin','db_backupoperator','db_datareader','db_datawriter','db_denydatareader','db_denydatawriter','guest') ORDER BY name")
                return [r[0] for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",(schema,))
                return [TableInfo(schema=schema,name=r[0]) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("""
                    SELECT c.column_name,c.data_type,c.is_nullable,c.column_default,
                        CASE WHEN tc.constraint_type='PRIMARY KEY' THEN 1 ELSE 0 END
                    FROM information_schema.columns c
                    LEFT JOIN information_schema.key_column_usage kcu ON kcu.table_schema=c.table_schema AND kcu.table_name=c.table_name AND kcu.column_name=c.column_name
                    LEFT JOIN information_schema.table_constraints tc ON tc.constraint_name=kcu.constraint_name AND tc.constraint_type='PRIMARY KEY'
                    WHERE c.table_schema=%s AND c.table_name=%s ORDER BY c.ordinal_position
                """,(schema,table))
                return [ColumnInfo(schema=schema,table=table,name=r[0],data_type=r[1],nullable=(r[2]=="YES"),default=r[3],is_primary_key=bool(r[4])) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("""
                    SELECT col.name,OBJECT_SCHEMA_NAME(fkc.referenced_object_id),OBJECT_NAME(fkc.referenced_object_id),refcol.name,fk.name
                    FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fk.object_id=fkc.constraint_object_id
                    JOIN sys.columns col ON col.object_id=fkc.parent_object_id AND col.column_id=fkc.parent_column_id
                    JOIN sys.columns refcol ON refcol.object_id=fkc.referenced_object_id AND refcol.column_id=fkc.referenced_column_id
                    WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id)=%s AND OBJECT_NAME(fk.parent_object_id)=%s
                """,(schema,table))
                return [FKInfo(schema=schema,table=table,column=r[0],ref_schema=r[1],ref_table=r[2],ref_column=r[3],constraint_name=r[4]) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def profile_column(self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0) -> ColumnProfile:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute(f"SELECT COUNT(*),COUNT(DISTINCT [{column}]),100.0*AVG(CASE WHEN [{column}] IS NULL THEN 1.0 ELSE 0.0 END) FROM [{schema}].[{table}]")
                rc,dc,np=cur.fetchone(); samples=[]
                if sample_rows>0:
                    cur.execute(f"SELECT TOP {int(sample_rows)} [{column}] FROM [{schema}].[{table}] WHERE [{column}] IS NOT NULL")
                    samples=[r[0] for r in cur.fetchall()]
                return ColumnProfile(row_count=rc,distinct_count=dc,null_pct=float(np) if np else None,sample_values=samples)
        return await asyncio.to_thread(_s)

    async def search_by_keywords(self, profile: Any, keywords: List[str], limit: int = 50) -> List[ColumnHit]:
        def _s():
            if not keywords: return []
            patterns=[f"%{k.lower()}%" for k in keywords]
            clauses=" OR ".join(["LOWER(column_name) LIKE %s"]*len(patterns))
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute(f"SELECT TOP {int(limit)} table_schema,table_name,column_name,data_type FROM information_schema.columns WHERE table_schema NOT IN ('sys','INFORMATION_SCHEMA') AND ({clauses})",tuple(patterns))
                return [ColumnHit(schema=r[0],table=r[1],column=r[2],data_type=r[3],score=1.0,matched_on="name") for r in cur.fetchall()]
        return await asyncio.to_thread(_s)
