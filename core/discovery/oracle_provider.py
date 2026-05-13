"""Oracle source provider — oracledb thin mode (no Oracle client required)."""
from __future__ import annotations
import asyncio, time
from typing import Any, List
import oracledb
from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo, FKInfo, ColumnProfile, ColumnHit,
)

class OracleProvider(SourceProvider):
    dialect = "oracle"

    def _connect(self, profile: Any):
        return oracledb.connect(profile.dsn)

    async def ping(self, profile: Any) -> PingResult:
        def _s():
            t0 = time.perf_counter()
            try:
                self._connect(profile).close()
                return PingResult(ok=True, latency_ms=int((time.perf_counter()-t0)*1000))
            except Exception as e:
                return PingResult(ok=False, message=str(e))
        return await asyncio.to_thread(_s)

    async def list_schemas(self, profile: Any) -> List[str]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("SELECT username FROM all_users ORDER BY username")
                return [r[0] for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("SELECT table_name,num_rows FROM all_tables WHERE owner=:o ORDER BY table_name", o=schema.upper())
                return [TableInfo(schema=schema, name=r[0], row_estimate=r[1]) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("""
                    SELECT col.column_name,col.data_type,col.nullable,col.data_default,
                           CASE WHEN cc.constraint_type='P' THEN 'Y' ELSE 'N' END
                    FROM all_tab_columns col
                    LEFT JOIN all_cons_columns cc_col ON cc_col.owner=col.owner AND cc_col.table_name=col.table_name AND cc_col.column_name=col.column_name
                    LEFT JOIN all_constraints cc ON cc.owner=cc_col.owner AND cc.constraint_name=cc_col.constraint_name AND cc.constraint_type='P'
                    WHERE col.owner=:o AND col.table_name=:t ORDER BY col.column_id
                """, o=schema.upper(), t=table.upper())
                return [ColumnInfo(schema=schema,table=table,name=r[0],data_type=r[1],nullable=(r[2]=="Y"),default=str(r[3]) if r[3] else None,is_primary_key=(r[4]=="Y")) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute("""
                    SELECT a.column_name,c_pk.owner,c_pk.table_name,b.column_name,a.constraint_name
                    FROM all_cons_columns a JOIN all_constraints c ON a.owner=c.owner AND a.constraint_name=c.constraint_name
                    JOIN all_constraints c_pk ON c.r_owner=c_pk.owner AND c.r_constraint_name=c_pk.constraint_name
                    JOIN all_cons_columns b ON c_pk.owner=b.owner AND c_pk.constraint_name=b.constraint_name AND b.position=a.position
                    WHERE c.constraint_type='R' AND a.owner=:o AND a.table_name=:t
                """, o=schema.upper(), t=table.upper())
                return [FKInfo(schema=schema,table=table,column=r[0],ref_schema=r[1],ref_table=r[2],ref_column=r[3],constraint_name=r[4]) for r in cur.fetchall()]
        return await asyncio.to_thread(_s)

    async def profile_column(self, profile: Any, schema: str, table: str, column: str, sample_rows: int = 0) -> ColumnProfile:
        def _s():
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute(f'SELECT COUNT(*),COUNT(DISTINCT "{column}"),100*AVG(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END) FROM "{schema.upper()}"."{table.upper()}"')
                rc,dc,np=cur.fetchone(); samples=[]
                if sample_rows>0:
                    cur.execute(f'SELECT "{column}" FROM "{schema.upper()}"."{table.upper()}" WHERE "{column}" IS NOT NULL AND ROWNUM<={int(sample_rows)}')
                    samples=[r[0] for r in cur.fetchall()]
                return ColumnProfile(row_count=rc,distinct_count=dc,null_pct=float(np) if np else None,sample_values=samples)
        return await asyncio.to_thread(_s)

    async def search_by_keywords(self, profile: Any, keywords: List[str], limit: int = 50) -> List[ColumnHit]:
        def _s():
            if not keywords: return []
            patterns=[f"%{k.lower()}%" for k in keywords]
            clauses=" OR ".join([f"LOWER(column_name) LIKE :k{i}" for i in range(len(patterns))])
            params={f"k{i}":p for i,p in enumerate(patterns)}; params["lim"]=limit
            with self._connect(profile) as c, c.cursor() as cur:
                cur.execute(f"SELECT owner,table_name,column_name,data_type FROM all_tab_columns WHERE ({clauses}) AND owner NOT IN ('SYS','SYSTEM','XDB') AND ROWNUM<=:lim",**params)
                return [ColumnHit(schema=r[0],table=r[1],column=r[2],data_type=r[3],score=1.0,matched_on="name") for r in cur.fetchall()]
        return await asyncio.to_thread(_s)
