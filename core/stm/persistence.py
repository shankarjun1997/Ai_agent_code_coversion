"""STM session + event persistence using SQLAlchemy Core.

Source-first schema:
  - stm_sessions       (one row per agentic session)
  - stm_stage_events   (audit log of L1..L4 + gate events)
  - stm_gate_decisions (gate1_shortlist, gate2_mapping decisions)
  - mapping_memory     (one row per MappingRow at each gate2 decision)

Sync engine wrapped in asyncio.to_thread. Async DB driver suffixes are
normalised to sync drivers.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column, DateTime, Float, Index, Integer,
    MetaData, String, Table, Text, create_engine, insert, select, update,
)
from sqlalchemy.engine import Engine

from core.stm.blackboard import StmBlackboard


_engine: Optional[Engine] = None
_meta: Optional[MetaData] = None


def _build_schema(meta: MetaData) -> None:
    """Declare STM tables in MetaData (matches alembic migrations)."""
    Table(
        "stm_sessions", meta,
        Column("session_id", String(36), primary_key=True),
        Column("status", String(32), nullable=False),
        Column("current_stage", String(16), nullable=False),
        Column("source_table_name", String(255), nullable=True),
        Column("target_project", String(128), nullable=True),
        Column("target_dataset", String(128), nullable=True),
        Column("business_context", Text(), nullable=True),
        Column("blackboard_json", Text(), nullable=False),
        Column("created_at", DateTime(), nullable=False),
        Column("updated_at", DateTime(), nullable=False),
        Column("created_by", String(128), nullable=True),
        # Batch linkage columns (added by d1e2f3a4b5c6 migration)
        Column("batch_id", String(36), nullable=True),
        Column("catalog_source_id", String(36), nullable=True),
        Column("catalog_target_id", String(36), nullable=True),
        Column("catalog_source_table_id", String(36), nullable=True),
    )
    Table(
        "stm_stage_events", meta,
        Column("event_id", String(36), primary_key=True),
        Column("session_id", String(36), nullable=False),
        Column("stage", String(16), nullable=False),
        Column("event_kind", String(32), nullable=False),
        Column("artifact_kind", String(32), nullable=True),
        Column("artifact_json", Text(), nullable=True),
        Column("llm_model", String(64), nullable=True),
        Column("llm_tokens_in", Integer(), nullable=True),
        Column("llm_tokens_out", Integer(), nullable=True),
        Column("duration_ms", Integer(), nullable=True),
        Column("message", Text(), nullable=True),
        Column("created_at", DateTime(), nullable=False),
        Index("idx_stm_stage_events_session", "session_id", "created_at"),
    )
    Table(
        "stm_gate_decisions", meta,
        Column("decision_id", String(36), primary_key=True),
        Column("session_id", String(36), nullable=False),
        Column("gate_name", String(32), nullable=False),
        Column("decision", String(16), nullable=False),
        Column("reviewer", String(128), nullable=True),
        Column("notes", Text(), nullable=True),
        Column("refine_target", String(16), nullable=True),
        Column("refine_feedback", Text(), nullable=True),
        Column("decided_at", DateTime(), nullable=False),
    )
    Table(
        "mapping_memory", meta,
        Column("id", String(36), primary_key=True),
        Column("session_id", String(36), nullable=False),
        Column("gate_name", String(32), nullable=False),
        Column("decision", String(16), nullable=False),
        Column("reviewer", String(128), nullable=True),
        Column("decided_at", DateTime(), nullable=False),

        Column("business_context", Text(), nullable=True),

        Column("source_table", String(128), nullable=False),
        Column("source_column", String(128), nullable=False),
        Column("target_project", String(128), nullable=True),
        Column("target_dataset", String(128), nullable=True),
        Column("target_table", String(128), nullable=True),
        Column("target_column", String(128), nullable=True),

        Column("mapping_type", String(16), nullable=False),
        Column("business_logic", Text(), nullable=True),
        Column("rationale", Text(), nullable=True),
        Column("evidence_json", Text(), nullable=True),

        Column("reviewer_notes", Text(), nullable=True),
        Column("refine_feedback", Text(), nullable=True),

        Column("created_at", DateTime(), nullable=False),
        Index("idx_mapping_memory_target", "target_dataset", "target_table", "target_column"),
        Index("idx_mapping_memory_source", "source_table", "source_column"),
        Index("idx_mapping_memory_decision", "decision"),
        Index("idx_mapping_memory_created", "created_at"),
    )


def _resolve_db_url() -> str:
    raw = os.environ.get("STM_DB_URL") or os.environ.get("DATABASE_URL") or "sqlite:////app/output/stm.db"
    url = raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    url = url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


def _eng() -> Engine:
    """Lazy engine with auto-create. Falls back to local sqlite if configured DB unreachable."""
    global _engine, _meta
    if _engine is None:
        url = _resolve_db_url()
        try:
            _engine = create_engine(url, future=True)
            _meta = MetaData()
            _build_schema(_meta)
            _meta.create_all(_engine, checkfirst=True)
        except Exception:
            fallback = "sqlite:////app/output/stm.db" if os.path.isdir("/app/output") else "sqlite:///./stm.db"
            _engine = create_engine(fallback, future=True)
            _meta = MetaData()
            _build_schema(_meta)
            _meta.create_all(_engine, checkfirst=True)
    return _engine


def _t(name: str) -> Table:
    _eng()
    return _meta.tables[name]  # type: ignore[index]


# ── Session CRUD ────────────────────────────────────────────────────────────

def _create_session_sync(bb: StmBlackboard) -> None:
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_sessions")).values(
            session_id=bb.session_id,
            status="created",
            current_stage=bb.current_stage,
            source_table_name=bb.source_table_name or None,
            target_project=bb.target_project or None,
            target_dataset=bb.target_dataset or None,
            business_context=bb.business_context or None,
            blackboard_json=bb.model_dump_json(),
            created_at=bb.created_at or now,
            updated_at=now,
            batch_id=bb.batch_id,
            catalog_source_id=bb.catalog_source_id,
            catalog_target_id=bb.catalog_target_id,
            catalog_source_table_id=bb.catalog_source_table_id,
        ))


async def create_session(bb: StmBlackboard) -> None:
    await asyncio.to_thread(_create_session_sync, bb)


def _load_blackboard_sync(session_id: str) -> StmBlackboard:
    with _eng().connect() as conn:
        row = conn.execute(
            select(_t("stm_sessions").c.blackboard_json)
            .where(_t("stm_sessions").c.session_id == session_id)
        ).first()
    if not row:
        raise KeyError(f"Session not found: {session_id}")
    return StmBlackboard.model_validate_json(row[0])


async def load_blackboard(session_id: str) -> StmBlackboard:
    return await asyncio.to_thread(_load_blackboard_sync, session_id)


def _save_blackboard_sync(bb: StmBlackboard) -> None:
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(
            update(_t("stm_sessions"))
            .where(_t("stm_sessions").c.session_id == bb.session_id)
            .values(
                current_stage=bb.current_stage,
                source_table_name=bb.source_table_name or None,
                target_project=bb.target_project or None,
                target_dataset=bb.target_dataset or None,
                business_context=bb.business_context or None,
                blackboard_json=bb.model_dump_json(),
                updated_at=now,
            )
        )


async def save_blackboard(bb: StmBlackboard) -> None:
    await asyncio.to_thread(_save_blackboard_sync, bb)


def _set_session_status_sync(session_id: str, status: str) -> None:
    with _eng().begin() as conn:
        conn.execute(
            update(_t("stm_sessions"))
            .where(_t("stm_sessions").c.session_id == session_id)
            .values(status=status, updated_at=datetime.utcnow())
        )


async def set_session_status(session_id: str, status: str) -> None:
    await asyncio.to_thread(_set_session_status_sync, session_id, status)


def _get_session_status_sync(session_id: str) -> Optional[str]:
    with _eng().connect() as conn:
        row = conn.execute(
            select(_t("stm_sessions").c.status)
            .where(_t("stm_sessions").c.session_id == session_id)
        ).first()
    return row[0] if row else None


async def get_session_status(session_id: str) -> Optional[str]:
    return await asyncio.to_thread(_get_session_status_sync, session_id)


def _list_running_sync() -> List[Dict[str, Any]]:
    with _eng().connect() as conn:
        rows = conn.execute(
            select(_t("stm_sessions").c.session_id, _t("stm_sessions").c.status)
            .where(_t("stm_sessions").c.status.in_(["running", "awaiting_review", "awaiting_attachments"]))
        ).mappings().all()
    return [dict(r) for r in rows]


async def list_running_sessions() -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_list_running_sync)


def _list_sessions_sync(limit: int = 50) -> List[Dict[str, Any]]:
    t = _t("stm_sessions")
    with _eng().connect() as conn:
        rows = conn.execute(
            select(t.c.session_id, t.c.status, t.c.current_stage,
                   t.c.source_table_name, t.c.target_project, t.c.target_dataset,
                   t.c.created_at, t.c.updated_at)
            .order_by(t.c.created_at.desc())
            .limit(limit)
        ).mappings().all()
    return [dict(r) for r in rows]


async def list_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_list_sessions_sync, limit)


# ── Events / Gate decisions ─────────────────────────────────────────────────

def _append_event_sync(
    session_id: str, *, stage: str, kind: str,
    artifact_kind: Optional[str] = None, artifact_json: Optional[str] = None,
    llm_model: Optional[str] = None, llm_tokens_in: Optional[int] = None,
    llm_tokens_out: Optional[int] = None, duration_ms: Optional[int] = None,
    message: Optional[str] = None,
) -> None:
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_stage_events")).values(
            event_id=str(uuid.uuid4()),
            session_id=session_id, stage=stage, event_kind=kind,
            artifact_kind=artifact_kind, artifact_json=artifact_json,
            llm_model=llm_model, llm_tokens_in=llm_tokens_in,
            llm_tokens_out=llm_tokens_out, duration_ms=duration_ms,
            message=message, created_at=datetime.utcnow(),
        ))


async def append_event(session_id: str, **kw) -> None:
    await asyncio.to_thread(_append_event_sync, session_id, **kw)


def _list_events_sync(session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    t = _t("stm_stage_events")
    with _eng().connect() as conn:
        rows = conn.execute(
            select(t.c.event_id, t.c.stage, t.c.event_kind, t.c.duration_ms,
                   t.c.llm_model, t.c.message, t.c.created_at)
            .where(t.c.session_id == session_id)
            .order_by(t.c.created_at.asc())
            .limit(limit)
        ).mappings().all()
    return [dict(r) for r in rows]


async def list_events(session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_list_events_sync, session_id, limit)


def _record_gate_decision_sync(
    session_id: str, *, gate_name: str, decision: str,
    reviewer: Optional[str], notes: Optional[str],
    refine_target: Optional[str], refine_feedback: Optional[str],
) -> None:
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_gate_decisions")).values(
            decision_id=str(uuid.uuid4()),
            session_id=session_id, gate_name=gate_name, decision=decision,
            reviewer=reviewer, notes=notes,
            refine_target=refine_target, refine_feedback=refine_feedback,
            decided_at=datetime.utcnow(),
        ))


async def record_gate_decision(session_id: str, **kw) -> None:
    await asyncio.to_thread(_record_gate_decision_sync, session_id, **kw)


# ── Mapping memory v2 ───────────────────────────────────────────────────────

def _log_mapping_memory_rows_sync(
    *,
    session_id: str, gate_name: str, decision: str,
    reviewer: Optional[str], decided_at: datetime,
    blackboard: StmBlackboard,
    reviewer_notes: Optional[str], refine_feedback: Optional[str],
) -> int:
    if not blackboard.mappings:
        return 0
    evidence_by_table: Dict[str, List[str]] = {}
    if blackboard.shortlist:
        for e in blackboard.shortlist.rows:
            evidence_by_table[e.table] = list(e.evidence)
    common = {
        "session_id": session_id, "gate_name": gate_name, "decision": decision,
        "reviewer": reviewer, "decided_at": decided_at,
        "business_context": blackboard.business_context or None,
        "target_project": blackboard.target_project or None,
        "target_dataset": blackboard.target_dataset or None,
        "reviewer_notes": reviewer_notes, "refine_feedback": refine_feedback,
    }
    rows: List[Dict[str, Any]] = []
    for m in blackboard.mappings:
        rows.append({
            "id": str(uuid.uuid4()),
            **common,
            "source_table": m.source_table,
            "source_column": m.source_column,
            "target_table": m.target_table or None,
            "target_column": m.target_column or None,
            "mapping_type": m.mapping_type,
            "business_logic": m.business_logic or None,
            "rationale": m.rationale or None,
            "evidence_json": json.dumps(evidence_by_table.get(m.target_table, [])) if m.target_table else None,
            "created_at": decided_at,
        })
    if not rows:
        return 0
    with _eng().begin() as conn:
        conn.execute(insert(_t("mapping_memory")), rows)
    return len(rows)


async def log_mapping_memory_rows(
    *, session_id: str, gate_name: str, decision: str,
    reviewer: Optional[str], blackboard: StmBlackboard,
    reviewer_notes: Optional[str] = None, refine_feedback: Optional[str] = None,
) -> int:
    return await asyncio.to_thread(
        _log_mapping_memory_rows_sync,
        session_id=session_id, gate_name=gate_name, decision=decision,
        reviewer=reviewer, decided_at=datetime.utcnow(),
        blackboard=blackboard,
        reviewer_notes=reviewer_notes, refine_feedback=refine_feedback,
    )


def _mapping_memory_stats_sync() -> Dict[str, Any]:
    from sqlalchemy import func as sa_func
    t = _t("mapping_memory")
    with _eng().connect() as conn:
        total = conn.execute(select(sa_func.count()).select_from(t)).scalar() or 0
        by_decision = dict(conn.execute(
            select(t.c.decision, sa_func.count()).group_by(t.c.decision)
        ).all())
        by_type = dict(conn.execute(
            select(t.c.mapping_type, sa_func.count()).group_by(t.c.mapping_type)
        ).all())
        recent = conn.execute(
            select(
                t.c.id, t.c.session_id, t.c.decision, t.c.source_table, t.c.source_column,
                t.c.target_dataset, t.c.target_table, t.c.target_column,
                t.c.mapping_type, t.c.business_logic, t.c.created_at,
            ).order_by(t.c.created_at.desc()).limit(20)
        ).mappings().all()
    return {
        "total": int(total),
        "by_decision": {k: int(v) for k, v in by_decision.items()},
        "by_mapping_type": {k: int(v) for k, v in by_type.items()},
        "recent": [dict(r) for r in recent],
    }


async def mapping_memory_stats() -> Dict[str, Any]:
    return await asyncio.to_thread(_mapping_memory_stats_sync)


def reset_engine_for_tests() -> None:
    global _engine, _meta
    _engine = None
    _meta = None
