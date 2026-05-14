"""STM session + event persistence using SQLAlchemy core.

Uses a sync engine wrapped in asyncio.to_thread so we don't block the
event loop on DB IO. DATABASE_URL with an async driver suffix
(`+asyncpg`, `+aiosqlite`) is normalised to the matching sync driver.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer, LargeBinary,
    MetaData, String, Table, Text, create_engine, insert, select, update,
)
from sqlalchemy.engine import Engine

from core.stm.blackboard import StmBlackboard


_engine: Optional[Engine] = None
_meta: Optional[MetaData] = None


def _build_schema(meta: MetaData) -> None:
    """Declare STM tables in MetaData (matches the alembic migration)."""
    Table(
        "stm_sessions", meta,
        Column("session_id", String(36), primary_key=True),
        Column("status", String(32), nullable=False),
        Column("current_stage", String(16), nullable=False),
        Column("target_table", String(128), nullable=False),
        Column("target_dataset", String(128), nullable=False),
        Column("source_profiles", Text(), nullable=False),
        Column("intent_source", String(16), nullable=False),
        Column("jira_issue_key", String(64), nullable=True),
        Column("raw_input", Text(), nullable=False),
        Column("blackboard_json", Text(), nullable=False),
        Column("created_at", DateTime(), nullable=False),
        Column("updated_at", DateTime(), nullable=False),
        Column("created_by", String(128), nullable=True),
    )
    Table(
        "stm_stage_events", meta,
        Column("event_id", String(36), primary_key=True),
        Column("session_id", String(36), nullable=False),
        Column("stage", String(16), nullable=False),
        Column("event_kind", String(32), nullable=False),
        Column("artifact_kind", String(32), nullable=True),
        Column("artifact_json", Text(), nullable=True),
        Column("confidence", Float(), nullable=True),
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
        Column("decision", String(16), nullable=False),  # approved / refine / rejected
        Column("reviewer", String(128), nullable=True),
        Column("decided_at", DateTime(), nullable=False),

        Column("intent_kind", String(32), nullable=True),
        Column("intent_action", String(32), nullable=True),
        Column("intent_entity", String(128), nullable=True),
        Column("intent_keywords_json", Text(), nullable=True),
        Column("jira_issue_key", String(64), nullable=True),

        Column("target_dataset", String(128), nullable=False),
        Column("target_table", String(128), nullable=False),
        Column("target_field", String(128), nullable=True),
        Column("target_type", String(64), nullable=True),

        Column("source_node_ids_json", Text(), nullable=True),
        Column("source_expression", Text(), nullable=True),
        Column("cardinality", String(16), nullable=True),
        Column("rationale", Text(), nullable=True),

        Column("transformation_kind", String(32), nullable=True),
        Column("transformation_logic", Text(), nullable=True),

        Column("confidence_band", String(16), nullable=True),
        Column("confidence_final", Float(), nullable=True),
        Column("score_llm", Float(), nullable=True),
        Column("score_name_sim", Float(), nullable=True),
        Column("score_type_compat", Float(), nullable=True),
        Column("score_profile_overlap", Float(), nullable=True),
        Column("score_fk_evidence", Float(), nullable=True),

        Column("reviewer_notes", Text(), nullable=True),
        Column("refine_feedback", Text(), nullable=True),

        Column("created_at", DateTime(), nullable=False),
        Index("idx_mapping_memory_target", "target_dataset", "target_table", "target_field"),
        Index("idx_mapping_memory_decision", "decision"),
        Index("idx_mapping_memory_created", "created_at"),
    )


def _resolve_db_url() -> str:
    """STM_DB_URL > DATABASE_URL > sqlite fallback. Async drivers stripped."""
    raw = os.environ.get("STM_DB_URL") or os.environ.get("DATABASE_URL") or "sqlite:////app/output/stm.db"
    url = raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    url = url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


def _eng() -> Engine:
    """Lazy engine with auto-create. STM tables are created if missing so demos
    don't require alembic to have run against the platform DB."""
    global _engine, _meta
    if _engine is None:
        url = _resolve_db_url()
        try:
            _engine = create_engine(url, future=True)
            _meta = MetaData()
            _build_schema(_meta)
            _meta.create_all(_engine, checkfirst=True)
        except Exception:
            # If the configured DB is unreachable, fall back to a local sqlite
            # so STM demos work without a platform Postgres in place.
            fallback = "sqlite:////app/output/stm.db" if os.path.isdir("/app/output") else "sqlite:///./stm.db"
            _engine = create_engine(fallback, future=True)
            _meta = MetaData()
            _build_schema(_meta)
            _meta.create_all(_engine, checkfirst=True)
    return _engine


def _t(name: str) -> Table:
    _eng()
    return _meta.tables[name]


def _create_session_sync(
    bb: StmBlackboard, raw_input: str, intent_source: str,
    jira_issue_key: Optional[str], created_by: Optional[str],
) -> None:
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_sessions")).values(
            session_id=bb.session_id,
            status="running",
            current_stage=bb.current_stage,
            target_table=bb.target_table,
            target_dataset=bb.target_dataset,
            source_profiles=json.dumps(bb.selected_source_profiles),
            intent_source=intent_source,
            jira_issue_key=jira_issue_key,
            raw_input=raw_input,
            blackboard_json=bb.model_dump_json(),
            created_at=now,
            updated_at=now,
            created_by=created_by,
        ))


async def create_session(
    bb: StmBlackboard,
    *,
    raw_input: str,
    intent_source: str,
    jira_issue_key: Optional[str],
    created_by: Optional[str] = None,
) -> None:
    await asyncio.to_thread(
        _create_session_sync, bb, raw_input, intent_source, jira_issue_key, created_by
    )


def _load_blackboard_sync(session_id: str) -> StmBlackboard:
    with _eng().connect() as conn:
        row = conn.execute(
            select(_t("stm_sessions").c.blackboard_json).where(
                _t("stm_sessions").c.session_id == session_id
            )
        ).fetchone()
    if row is None:
        raise KeyError(session_id)
    return StmBlackboard.model_validate_json(row[0])


async def load_blackboard(session_id: str) -> StmBlackboard:
    return await asyncio.to_thread(_load_blackboard_sync, session_id)


def _save_blackboard_sync(bb: StmBlackboard) -> None:
    now = datetime.utcnow()
    new_status = "awaiting_review" if any(
        g.decision == "pending" for g in bb.gates.values()
    ) and bb.current_stage in ("L2", "L5") else "running"
    with _eng().begin() as conn:
        conn.execute(
            update(_t("stm_sessions"))
            .where(_t("stm_sessions").c.session_id == bb.session_id)
            .values(
                current_stage=bb.current_stage,
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


def _append_event_sync(
    session_id: str, stage: str, event_kind: str,
    artifact_kind: Optional[str], artifact_json: Optional[str],
    confidence: Optional[float], llm_model: Optional[str],
    llm_tokens_in: Optional[int], llm_tokens_out: Optional[int],
    duration_ms: Optional[int], message: Optional[str],
) -> str:
    eid = str(uuid.uuid4())
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_stage_events")).values(
            event_id=eid, session_id=session_id, stage=stage, event_kind=event_kind,
            artifact_kind=artifact_kind, artifact_json=artifact_json, confidence=confidence,
            llm_model=llm_model, llm_tokens_in=llm_tokens_in, llm_tokens_out=llm_tokens_out,
            duration_ms=duration_ms, message=message, created_at=datetime.utcnow(),
        ))
    return eid


async def append_event(
    session_id: str,
    *,
    stage: str,
    event_kind: str,
    artifact_kind: Optional[str] = None,
    artifact_json: Optional[str] = None,
    confidence: Optional[float] = None,
    llm_model: Optional[str] = None,
    llm_tokens_in: Optional[int] = None,
    llm_tokens_out: Optional[int] = None,
    duration_ms: Optional[int] = None,
    message: Optional[str] = None,
) -> str:
    return await asyncio.to_thread(
        _append_event_sync, session_id, stage, event_kind, artifact_kind,
        artifact_json, confidence, llm_model, llm_tokens_in, llm_tokens_out,
        duration_ms, message,
    )


def _list_events_sync(session_id: str) -> List[Dict[str, Any]]:
    with _eng().connect() as conn:
        rows = conn.execute(
            select(_t("stm_stage_events")).where(
                _t("stm_stage_events").c.session_id == session_id
            ).order_by(_t("stm_stage_events").c.created_at)
        ).fetchall()
    return [dict(r._mapping) for r in rows]


async def list_events(session_id: str) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_list_events_sync, session_id)


def _record_gate_decision_sync(
    session_id: str, gate_name: str, decision: str,
    reviewer: Optional[str], notes: Optional[str],
    refine_target: Optional[str], refine_feedback: Optional[str],
) -> str:
    did = str(uuid.uuid4())
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_gate_decisions")).values(
            decision_id=did, session_id=session_id, gate_name=gate_name, decision=decision,
            reviewer=reviewer, notes=notes, refine_target=refine_target,
            refine_feedback=refine_feedback, decided_at=now,
        ))
    return did


async def record_gate_decision(
    session_id: str,
    *,
    gate_name: str,
    decision: str,
    reviewer: Optional[str],
    notes: Optional[str],
    refine_target: Optional[str],
    refine_feedback: Optional[str],
) -> str:
    did = await asyncio.to_thread(
        _record_gate_decision_sync, session_id, gate_name, decision,
        reviewer, notes, refine_target, refine_feedback,
    )
    await append_event(
        session_id, stage="GATE", event_kind="gate_decided",
        message=f"{gate_name}:{decision}",
        artifact_kind=gate_name,
        artifact_json=json.dumps({"decision": decision, "refine_target": refine_target, "refine_feedback": refine_feedback}),
    )
    return did


def _get_session_status_sync(session_id: str) -> Optional[str]:
    with _eng().connect() as conn:
        row = conn.execute(
            select(_t("stm_sessions").c.status).where(
                _t("stm_sessions").c.session_id == session_id
            )
        ).fetchone()
    return row[0] if row else None


async def get_session_status(session_id: str) -> Optional[str]:
    return await asyncio.to_thread(_get_session_status_sync, session_id)


def _list_running_sessions_sync() -> List[Dict[str, Any]]:
    with _eng().connect() as conn:
        rows = conn.execute(
            select(_t("stm_sessions")).where(_t("stm_sessions").c.status == "running")
        ).fetchall()
    return [dict(r._mapping) for r in rows]


async def list_running_sessions() -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_list_running_sessions_sync)


def _find_latest_stm_by_target_sync(
    target_dataset: str, target_table: str, exclude_session_id: Optional[str] = None,
) -> Optional[str]:
    """Return the session_id of the most recently completed STM for this target,
    or None if none exist. Used by Phase E enhancement detection."""
    t = _t("stm_sessions")
    q = (
        select(t.c.session_id)
        .where(t.c.target_dataset == target_dataset)
        .where(t.c.target_table == target_table)
        .where(t.c.status == "done")
        .order_by(t.c.updated_at.desc())
        .limit(5)
    )
    with _eng().connect() as conn:
        rows = conn.execute(q).fetchall()
    for r in rows:
        sid = r[0]
        if sid != exclude_session_id:
            return sid
    return None


async def find_latest_stm_by_target(
    target_dataset: str, target_table: str, exclude_session_id: Optional[str] = None,
) -> Optional[str]:
    return await asyncio.to_thread(
        _find_latest_stm_by_target_sync, target_dataset, target_table, exclude_session_id,
    )


def reset_engine_for_tests() -> None:
    global _engine, _meta
    _engine = None
    _meta = None


# ── Mapping memory (Phase A: log every gate2 decision) ────────────────────

def _log_mapping_memory_rows_sync(
    *,
    session_id: str,
    gate_name: str,
    decision: str,
    reviewer: Optional[str],
    decided_at: datetime,
    blackboard: StmBlackboard,
    reviewer_notes: Optional[str],
    refine_feedback: Optional[str],
) -> int:
    intent = blackboard.intent
    validation = blackboard.validation
    mappings = blackboard.candidate_mappings
    transforms = blackboard.transformations

    score_by_field: Dict[str, Any] = {}
    if validation and getattr(validation, "scores", None):
        for s in validation.scores:
            score_by_field[s.target_field] = s

    tx_by_field: Dict[str, Any] = {}
    if transforms and getattr(transforms, "rows", None):
        for t in transforms.rows:
            tx_by_field[t.target_field] = t

    common = {
        "session_id": session_id,
        "gate_name": gate_name,
        "decision": decision,
        "reviewer": reviewer,
        "decided_at": decided_at,
        "intent_kind": getattr(intent, "intent_kind", None) if intent else None,
        "intent_action": getattr(intent, "action", None) if intent else None,
        "intent_entity": getattr(intent, "entity", None) if intent else None,
        "intent_keywords_json": json.dumps(getattr(intent, "extracted_keywords", []) or []) if intent else None,
        "jira_issue_key": getattr(intent, "jira_issue_key", None) if intent else None,
        "target_dataset": blackboard.target_dataset,
        "target_table": blackboard.target_table,
        "reviewer_notes": reviewer_notes,
        "refine_feedback": refine_feedback,
    }

    rows: List[Dict[str, Any]] = []

    # If we have per-field mappings, log one row per target field
    if mappings and getattr(mappings, "rows", None):
        for m in mappings.rows:
            score = score_by_field.get(m.target_field)
            tx = tx_by_field.get(m.target_field)
            rows.append({
                "id": str(uuid.uuid4()),
                **common,
                "target_field": m.target_field,
                "target_type": m.target_type,
                "source_node_ids_json": json.dumps(m.source_node_ids or []),
                "source_expression": m.source_expression or None,
                "cardinality": m.cardinality,
                "rationale": m.rationale or None,
                "transformation_kind": getattr(tx, "kind", None) if tx else None,
                "transformation_logic": getattr(tx, "logic", None) if tx else None,
                "confidence_band": getattr(score, "band", None) if score else None,
                "confidence_final": getattr(score, "final", None) if score else None,
                "score_llm": getattr(score, "llm_score", None) if score else None,
                "score_name_sim": getattr(score, "name_sim_score", None) if score else None,
                "score_type_compat": getattr(score, "type_compat_score", None) if score else None,
                "score_profile_overlap": getattr(score, "profile_overlap_score", None) if score else None,
                "score_fk_evidence": getattr(score, "fk_evidence_score", None) if score else None,
                "created_at": decided_at,
            })
    else:
        # Session-level entry for refines/rejects that may not have full mappings
        rows.append({
            "id": str(uuid.uuid4()),
            **common,
            "target_field": None,
            "target_type": None,
            "source_node_ids_json": None,
            "source_expression": None,
            "cardinality": None,
            "rationale": None,
            "transformation_kind": None,
            "transformation_logic": None,
            "confidence_band": getattr(validation, "overall_band", None) if validation else None,
            "confidence_final": None,
            "score_llm": None,
            "score_name_sim": None,
            "score_type_compat": None,
            "score_profile_overlap": None,
            "score_fk_evidence": None,
            "created_at": decided_at,
        })

    if not rows:
        return 0

    with _eng().begin() as conn:
        conn.execute(insert(_t("mapping_memory")), rows)
    return len(rows)


async def log_mapping_memory_rows(
    *,
    session_id: str,
    gate_name: str,
    decision: str,
    reviewer: Optional[str],
    blackboard: StmBlackboard,
    reviewer_notes: Optional[str] = None,
    refine_feedback: Optional[str] = None,
) -> int:
    return await asyncio.to_thread(
        _log_mapping_memory_rows_sync,
        session_id=session_id,
        gate_name=gate_name,
        decision=decision,
        reviewer=reviewer,
        decided_at=datetime.utcnow(),
        blackboard=blackboard,
        reviewer_notes=reviewer_notes,
        refine_feedback=refine_feedback,
    )


def _mapping_memory_stats_sync() -> Dict[str, Any]:
    from sqlalchemy import func as sa_func
    t = _t("mapping_memory")
    with _eng().connect() as conn:
        total = conn.execute(select(sa_func.count()).select_from(t)).scalar() or 0
        by_decision = dict(conn.execute(
            select(t.c.decision, sa_func.count()).group_by(t.c.decision)
        ).all())
        recent = conn.execute(
            select(
                t.c.id, t.c.session_id, t.c.decision, t.c.target_dataset, t.c.target_table,
                t.c.target_field, t.c.confidence_band, t.c.confidence_final, t.c.created_at,
            ).order_by(t.c.created_at.desc()).limit(20)
        ).mappings().all()
    return {
        "total": int(total),
        "by_decision": {k: int(v) for k, v in by_decision.items()},
        "recent": [dict(r) for r in recent],
    }


async def mapping_memory_stats() -> Dict[str, Any]:
    return await asyncio.to_thread(_mapping_memory_stats_sync)
