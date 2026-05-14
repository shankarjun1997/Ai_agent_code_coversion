"""STM Session Coordinator — 4-stage source-first pipeline.

  L1 (schemas) → L2 (shortlist) → [Gate 1] → L3 (mapping) → [Gate 2] → L4 (sql) → done

Each stage runs its StmAgent, applies the BlackboardDelta to the shared
blackboard, persists the updated state, and publishes SSE events.

Gate stalls use asyncio.Event — the pipeline task waits until a reviewer
calls approve / reject / refine via the gate decision API.

Recovery on startup is handled in app.py:_recover_stm_sessions().
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.stm.agents import (
    AgentContext, LLMClientProtocol,
    MappingAgent, SchemasAgent, ShortlistAgent, SqlAgent, StmAgent,
)
from core.stm.blackboard import StageStatus, Stage, StmBlackboard
from core.stm.events import EventKind, SseEvent, get_broker
from core.stm.persistence import (
    append_event, create_session, load_blackboard, record_gate_decision,
    save_blackboard, set_session_status,
)

logger = logging.getLogger(__name__)


_STAGE_ORDER: List[Stage] = ["L1", "L2", "L3", "L4"]

_STAGE_AGENTS: Dict[Stage, type[StmAgent]] = {
    "L1": SchemasAgent,
    "L2": ShortlistAgent,
    "L3": MappingAgent,
    "L4": SqlAgent,
}

# Gate fires AFTER the named stage completes
_GATE_AFTER: Dict[Stage, str] = {
    "L2": "gate1_shortlist",
    "L3": "gate2_mapping",
}

GATE_AT: Dict[Stage, str] = _GATE_AFTER  # exported alias for the UI

_running: Dict[str, asyncio.Task] = {}
_gate_events: Dict[str, Dict[str, asyncio.Event]] = {}
_start_events: Dict[str, asyncio.Event] = {}


# ── Public coordinator API ──────────────────────────────────────────────────

def is_running(session_id: str) -> bool:
    task = _running.get(session_id)
    return task is not None and not task.done()


def signal_start(session_id: str) -> bool:
    """Unblock a session that was created with pause_for_attachments=True."""
    ev = _start_events.get(session_id)
    if ev is None:
        return False
    ev.set()
    return True


def _get_start_event(session_id: str) -> asyncio.Event:
    if session_id not in _start_events:
        _start_events[session_id] = asyncio.Event()
    return _start_events[session_id]


def _get_gate_event(session_id: str, gate_name: str) -> asyncio.Event:
    per_session = _gate_events.setdefault(session_id, {})
    if gate_name not in per_session:
        per_session[gate_name] = asyncio.Event()
    return per_session[gate_name]


# ── LLM wiring ──────────────────────────────────────────────────────────────

def _make_llm() -> LLMClientProtocol:
    """Build the real LLM client from env, or return a no-op stub."""
    try:
        from core.llm_client import LLMClient
        api_key = (
            os.environ.get("LLM_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        if not api_key:
            logger.warning("No LLM API key configured — STM will fail on first LLM call")
        base_url = os.environ.get("LLM_BASE_URL")
        model = os.environ.get("LLM_MODEL") or os.environ.get("STM_LLM_MODEL_L1", "")
        return LLMClient(api_key=api_key, base_url=base_url, model=model)
    except Exception as exc:
        logger.warning("LLM client init failed: %s — falling back to stub", exc)

        class _Stub:
            def complete(self, prompt, system="", max_tokens=8192, temperature=0.1):
                raise RuntimeError("LLM not configured")
        return _Stub()


# ── Session lifecycle ───────────────────────────────────────────────────────

async def start_session(
    bb: StmBlackboard,
    *,
    business_context: str = "",
    config: Optional[Dict[str, Any]] = None,
    pause_for_attachments: bool = False,
    llm: Optional[LLMClientProtocol] = None,
) -> str:
    """Create the session record and kick off the pipeline task."""
    bb.business_context = business_context or bb.business_context
    bb.current_stage = "L1"
    await create_session(bb)
    await save_blackboard(bb)

    cfg = dict(config or {})
    cfg.setdefault("pause_for_attachments", bool(pause_for_attachments))

    _llm = llm or _make_llm()
    task = asyncio.create_task(_run_pipeline(bb.session_id, cfg, _llm))
    _running[bb.session_id] = task
    return bb.session_id


async def resume_session(session_id: str, llm: Optional[LLMClientProtocol] = None) -> None:
    """Resume a session whose task was lost (server restart)."""
    if is_running(session_id):
        return
    bb = await load_blackboard(session_id)
    cfg: Dict[str, Any] = {}
    _llm = llm or _make_llm()
    task = asyncio.create_task(_run_pipeline(bb.session_id, cfg, _llm))
    _running[session_id] = task


async def decide_gate(
    session_id: str,
    *,
    gate_name: str,
    decision: str,
    reviewer: Optional[str] = None,
    notes: Optional[str] = None,
    refine_target: Optional[str] = None,
    refine_feedback: Optional[str] = None,
) -> None:
    if decision not in ("approved", "rejected", "refine"):
        raise ValueError(f"Invalid gate decision: {decision!r}")

    bb = await load_blackboard(session_id)
    gate = bb.gates.get(gate_name)
    if gate is None:
        raise KeyError(f"Gate {gate_name!r} not found in session {session_id!r}")

    gate.decision = decision  # type: ignore[assignment]
    gate.reviewer = reviewer
    gate.notes = notes
    gate.refine_target_stage = refine_target  # type: ignore[assignment]
    gate.refine_feedback = refine_feedback
    gate.decided_at = datetime.now(timezone.utc)
    await save_blackboard(bb)

    await record_gate_decision(
        session_id,
        gate_name=gate_name,
        decision=decision,
        reviewer=reviewer,
        notes=notes,
        refine_target=refine_target,
        refine_feedback=refine_feedback,
    )

    # Log to mapping_memory only after gate2 (per-row trust signal exists by then)
    if gate_name == "gate2_mapping":
        try:
            from core.stm.persistence import log_mapping_memory_rows
            await log_mapping_memory_rows(
                session_id=session_id,
                gate_name=gate_name,
                decision=decision,
                reviewer=reviewer,
                blackboard=bb,
                reviewer_notes=notes,
                refine_feedback=refine_feedback,
            )
        except Exception as e:
            logger.warning("mapping_memory log failed: %s", e)

    ev = _get_gate_event(session_id, gate_name)
    ev.set()

    broker = get_broker()
    await broker.publish(session_id, SseEvent(
        kind=EventKind.gate_decided, stage="GATE",
        data={"gate": gate_name, "decision": decision},
        session_id=session_id,
    ))


# ── Pipeline runner ─────────────────────────────────────────────────────────

async def _run_pipeline(session_id: str, cfg: Dict[str, Any], llm: LLMClientProtocol) -> None:
    broker = get_broker()

    if cfg.get("pause_for_attachments"):
        start_ev = _get_start_event(session_id)
        await set_session_status(session_id, "awaiting_attachments")
        await broker.publish(session_id, SseEvent(
            kind=EventKind.session_started, stage="L1",
            data={"awaiting": "attachments"}, session_id=session_id,
        ))
        try:
            await asyncio.wait_for(start_ev.wait(), timeout=24 * 3600)
        except asyncio.TimeoutError:
            await set_session_status(session_id, "failed")
            await broker.publish(session_id, SseEvent(
                kind=EventKind.session_failed, stage="L1",
                data={"reason": "timeout_awaiting_attachments"}, session_id=session_id,
            ))
            return

    try:
        await set_session_status(session_id, "running")
        await broker.publish(session_id, SseEvent(
            kind=EventKind.session_started, stage="L1", data={}, session_id=session_id,
        ))

        for stage in _STAGE_ORDER:
            ok = await _run_stage(session_id, stage, cfg, llm)
            if not ok:
                return
            gate_name = _GATE_AFTER.get(stage)
            if gate_name:
                fired = await _wait_for_gate(session_id, stage, gate_name)
                if not fired:
                    return

        await set_session_status(session_id, "done")
        await broker.publish(session_id, SseEvent(
            kind=EventKind.session_done, stage="L4", data={}, session_id=session_id,
        ))
    finally:
        _running.pop(session_id, None)
        _gate_events.pop(session_id, None)
        _start_events.pop(session_id, None)


async def _run_stage(session_id: str, stage: Stage, cfg: Dict[str, Any], llm: LLMClientProtocol) -> bool:
    broker = get_broker()
    bb = await load_blackboard(session_id)
    bb.current_stage = stage
    await save_blackboard(bb)
    await broker.publish(session_id, SseEvent(
        kind=EventKind.stage_started, stage=stage, data={}, session_id=session_id,
    ))

    agent = _STAGE_AGENTS[stage]()

    def _emit(kind: str, data: Dict[str, Any]) -> None:
        asyncio.create_task(broker.publish(session_id, SseEvent(
            kind=EventKind(kind) if kind in EventKind.__members__ else EventKind.stage_progress,
            stage=stage, data=data, session_id=session_id,
        )))

    ctx = AgentContext(blackboard=bb, llm=llm, config=cfg, emit=_emit)
    delta = await agent.run(ctx)

    if delta.error:
        await append_event(session_id, stage=stage, kind="stage_failed",
                            message=delta.error, duration_ms=delta.duration_ms)
        await broker.publish(session_id, SseEvent(
            kind=EventKind.stage_failed, stage=stage,
            data={"error": delta.error}, session_id=session_id,
        ))
        await set_session_status(session_id, "failed")
        return False

    delta.apply(bb)
    bb.updated_at = datetime.now(timezone.utc)
    await save_blackboard(bb)
    await append_event(session_id, stage=stage, kind="stage_ready",
                        duration_ms=delta.duration_ms, llm_model=delta.llm_model,
                        llm_tokens_in=delta.llm_tokens_in, llm_tokens_out=delta.llm_tokens_out)
    await broker.publish(session_id, SseEvent(
        kind=EventKind.stage_ready, stage=stage,
        data={"duration_ms": delta.duration_ms, "llm_model": delta.llm_model},
        session_id=session_id,
    ))
    return True


async def _wait_for_gate(session_id: str, stage: Stage, gate_name: str) -> bool:
    """Stall for human approval. Returns True if approved (continue), False otherwise."""
    from core.stm.blackboard import GateDecision
    broker = get_broker()
    bb = await load_blackboard(session_id)
    if gate_name not in bb.gates:
        bb.gates[gate_name] = GateDecision(name=gate_name)  # type: ignore[arg-type]
        await save_blackboard(bb)

    await set_session_status(session_id, "awaiting_review")
    await broker.publish(session_id, SseEvent(
        kind=EventKind.gate_waiting, stage=stage,
        data={"gate": gate_name}, session_id=session_id,
    ))

    gate_event = _get_gate_event(session_id, gate_name)
    await gate_event.wait()
    gate_event.clear()

    bb = await load_blackboard(session_id)
    gate = bb.gates.get(gate_name)
    if gate is None:
        return False
    if gate.decision == "approved":
        await set_session_status(session_id, "running")
        return True
    if gate.decision == "refine":
        # Loop back: rerun from refine target stage onward
        target_stage = gate.refine_target_stage or stage
        await broker.publish(session_id, SseEvent(
            kind=EventKind.stage_started, stage=target_stage,  # type: ignore[arg-type]
            data={"reason": "refine"}, session_id=session_id,
        ))
        # Reset gate so it can re-fire after rerun
        gate.decision = "pending"
        gate.decided_at = None
        await save_blackboard(bb)
        # Rerun in-line
        for s in _STAGE_ORDER[_STAGE_ORDER.index(target_stage):]:  # type: ignore[arg-type]
            ok = await _run_stage(session_id, s, {}, _make_llm())
            if not ok:
                return False
            gn = _GATE_AFTER.get(s)
            if gn:
                fired = await _wait_for_gate(session_id, s, gn)
                if not fired:
                    return False
        return True
    # rejected
    await set_session_status(session_id, "failed")
    await broker.publish(session_id, SseEvent(
        kind=EventKind.session_failed, stage=stage,
        data={"reason": "gate_rejected"}, session_id=session_id,
    ))
    return False
