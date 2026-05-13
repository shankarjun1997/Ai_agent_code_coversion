"""STM session + event persistence using SQLAlchemy core."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, MetaData, Table, select, insert, update
from sqlalchemy.engine import Engine

from core.stm.blackboard import StmBlackboard


_engine: Optional[Engine] = None
_meta: Optional[MetaData] = None


def _eng() -> Engine:
    global _engine, _meta
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "sqlite:///./app.db")
        _engine = create_engine(url, future=True)
        _meta = MetaData()
        _meta.reflect(bind=_engine, only=["stm_sessions", "stm_stage_events", "stm_gate_decisions"])
    return _engine


def _t(name: str) -> Table:
    _eng()
    return _meta.tables[name]


async def create_session(
    bb: StmBlackboard,
    *,
    raw_input: str,
    intent_source: str,
    jira_issue_key: Optional[str],
    created_by: Optional[str] = None,
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


async def load_blackboard(session_id: str) -> StmBlackboard:
    with _eng().connect() as conn:
        row = conn.execute(
            select(_t("stm_sessions").c.blackboard_json).where(
                _t("stm_sessions").c.session_id == session_id
            )
        ).fetchone()
    if row is None:
        raise KeyError(session_id)
    return StmBlackboard.model_validate_json(row[0])


async def save_blackboard(bb: StmBlackboard) -> None:
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(
            update(_t("stm_sessions"))
            .where(_t("stm_sessions").c.session_id == bb.session_id)
            .values(
                status="awaiting_review" if any(
                    g.decision == "pending" and g.name in bb.gates and bb.gates[g.name].decision == "pending"
                    for g in bb.gates.values()
                    if g.decision == "pending"
                ) else "running",
                current_stage=bb.current_stage,
                blackboard_json=bb.model_dump_json(),
                updated_at=now,
            )
        )


async def set_session_status(session_id: str, status: str) -> None:
    with _eng().begin() as conn:
        conn.execute(
            update(_t("stm_sessions"))
            .where(_t("stm_sessions").c.session_id == session_id)
            .values(status=status, updated_at=datetime.utcnow())
        )


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
    eid = str(uuid.uuid4())
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_stage_events")).values(
            event_id=eid, session_id=session_id, stage=stage, event_kind=event_kind,
            artifact_kind=artifact_kind, artifact_json=artifact_json, confidence=confidence,
            llm_model=llm_model, llm_tokens_in=llm_tokens_in, llm_tokens_out=llm_tokens_out,
            duration_ms=duration_ms, message=message, created_at=datetime.utcnow(),
        ))
    return eid


async def list_events(session_id: str) -> List[Dict[str, Any]]:
    with _eng().connect() as conn:
        rows = conn.execute(
            select(_t("stm_stage_events")).where(
                _t("stm_stage_events").c.session_id == session_id
            ).order_by(_t("stm_stage_events").c.created_at)
        ).fetchall()
    return [dict(r._mapping) for r in rows]


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
    did = str(uuid.uuid4())
    now = datetime.utcnow()
    with _eng().begin() as conn:
        conn.execute(insert(_t("stm_gate_decisions")).values(
            decision_id=did, session_id=session_id, gate_name=gate_name, decision=decision,
            reviewer=reviewer, notes=notes, refine_target=refine_target,
            refine_feedback=refine_feedback, decided_at=now,
        ))
    await append_event(
        session_id, stage="GATE", event_kind="gate_decided",
        message=f"{gate_name}:{decision}",
        artifact_kind=gate_name,
        artifact_json=json.dumps({"decision": decision, "refine_target": refine_target, "refine_feedback": refine_feedback}),
    )
    return did


async def list_running_sessions() -> List[Dict[str, Any]]:
    with _eng().connect() as conn:
        rows = conn.execute(
            select(_t("stm_sessions")).where(_t("stm_sessions").c.status == "running")
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def reset_engine_for_tests() -> None:
    global _engine, _meta
    _engine = None
    _meta = None
