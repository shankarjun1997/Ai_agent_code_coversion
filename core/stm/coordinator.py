"""STM Session Coordinator.

Manages per-session asyncio.Task pipeline execution:
  L1 → L2 → L3 → L4 → L5 → L6 → done

Each stage runs its StmAgent, applies the BlackboardDelta to the shared
blackboard, persists the updated state, and publishes SSE events.

Gate stalls (Gate 1 after L2, Gate 2 after L5) are added in Task 5.2.
Recovery on startup is handled in Task 4.6.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from core.stm.agents.base import AgentContext, LLMClientProtocol
from core.stm.agents.builder_agent import BuilderAgent
from core.stm.agents.intent_agent import IntentAgent
from core.stm.agents.metadata_agent import MetadataAgent
from core.stm.agents.semantic_mapping_agent import SemanticMappingAgent
from core.stm.agents.transformation_agent import TransformationAgent
from core.stm.agents.validation_agent import ValidationAgent
from core.stm.blackboard import StmBlackboard
from core.stm.events import EventKind, SseEvent, get_broker
from core.stm.locks import SessionLockRegistry, get_registry as get_lock_registry
from core.stm.persistence import (
    append_event, create_session, load_blackboard, save_blackboard,
    set_session_status,
)

logger = logging.getLogger(__name__)

# Stage → Agent mapping (ordered pipeline)
_STAGE_ORDER = ["L1", "L2", "L3", "L4", "L5", "L6"]

_STAGE_AGENTS = {
    "L1": IntentAgent,
    "L2": MetadataAgent,
    "L3": SemanticMappingAgent,
    "L4": TransformationAgent,
    "L5": ValidationAgent,
    "L6": BuilderAgent,
}

# Active coordinator tasks keyed by session_id
_running: Dict[str, asyncio.Task] = {}


def _make_llm() -> LLMClientProtocol:
    """Build the real LLM client from env, or return a no-op stub."""
    try:
        api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_API_KEY", "")
        if api_key:
            from core.llm_client import LLMClient
            return LLMClient(api_key=api_key)
    except Exception as exc:
        logger.warning("Could not build LLM client: %s", exc)

    # Stub LLM returns empty JSON — agents fall back to deterministic floor
    class _StubLLM:
        def complete(self, *a, **kw) -> str:
            return "{}"

    return _StubLLM()


async def _run_pipeline(
    session_id: str,
    llm: LLMClientProtocol,
    config: Dict[str, Any],
    lock_registry: SessionLockRegistry,
) -> None:
    """Inner coroutine — runs all stages L1→L6 sequentially."""
    broker = get_broker()

    async def emit(kind: EventKind, stage: str, data: Dict[str, Any] = None):
        event = SseEvent(kind=kind, stage=stage, data=data or {}, session_id=session_id)
        await broker.publish(session_id, event)
        await append_event(
            session_id, stage=stage, event_kind=kind.value,
            message=data.get("message") if data else None,
        )

    try:
        bb = await load_blackboard(session_id)
    except KeyError:
        logger.error("Coordinator: session %s not found in DB", session_id)
        return

    for stage in _STAGE_ORDER:
        # Skip stages already completed (recovery path)
        stage_order_idx = _STAGE_ORDER.index(stage)
        current_idx = _STAGE_ORDER.index(bb.current_stage) if bb.current_stage in _STAGE_ORDER else 0
        if stage_order_idx < current_idx:
            continue

        AgentClass = _STAGE_AGENTS[stage]
        agent = AgentClass()

        await emit(EventKind.stage_started, stage=stage)

        ctx = AgentContext(
            blackboard=bb,
            llm=llm,
            config=config,
        )

        delta = await agent.run(ctx)

        if delta.error:
            logger.error("Coordinator: stage %s failed: %s", stage, delta.error)
            await emit(EventKind.stage_failed, stage=stage, data={"error": delta.error})
            async with lock_registry._meta_lock:
                pass  # ensure lock is clean
            await set_session_status(session_id, "failed")
            await broker.publish(session_id, SseEvent(
                kind=EventKind.session_failed,
                stage=stage,
                data={"error": delta.error},
                session_id=session_id,
            ))
            await broker.close(session_id)
            return

        # Apply delta and persist
        delta.apply(bb)
        await save_blackboard(bb)

        await emit(EventKind.stage_ready, stage=stage, data={
            "duration_ms": delta.duration_ms,
            "llm_model": delta.llm_model,
        })

    # Session complete
    await set_session_status(session_id, "done")
    await broker.publish(session_id, SseEvent(
        kind=EventKind.session_done,
        stage="L6",
        data={"session_id": session_id},
        session_id=session_id,
    ))
    await append_event(session_id, stage="done", event_kind=EventKind.session_done.value)
    await broker.close(session_id)
    logger.info("Coordinator: session %s completed successfully", session_id)


async def start_session(
    bb: StmBlackboard,
    *,
    raw_input: str,
    intent_source: str,
    jira_issue_key: Optional[str] = None,
    llm: Optional[LLMClientProtocol] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a new STM session and start the pipeline as a background task.

    Returns session_id.
    """
    session_id = bb.session_id
    await create_session(
        bb,
        raw_input=raw_input,
        intent_source=intent_source,
        jira_issue_key=jira_issue_key,
    )

    _llm = llm or _make_llm()
    _config = config or {}
    lock_registry = get_lock_registry()

    task = asyncio.create_task(
        _run_pipeline(session_id, _llm, _config, lock_registry),
        name=f"stm-pipeline-{session_id}",
    )
    _running[session_id] = task

    def _cleanup(t: asyncio.Task):
        _running.pop(session_id, None)

    task.add_done_callback(_cleanup)
    return session_id


async def resume_session(
    session_id: str,
    *,
    llm: Optional[LLMClientProtocol] = None,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Re-queue a session that was interrupted (e.g. after server restart)."""
    if session_id in _running:
        logger.warning("Coordinator.resume_session: %s already running", session_id)
        return

    _llm = llm or _make_llm()
    _config = config or {}
    lock_registry = get_lock_registry()

    task = asyncio.create_task(
        _run_pipeline(session_id, _llm, _config, lock_registry),
        name=f"stm-pipeline-resume-{session_id}",
    )
    _running[session_id] = task
    task.add_done_callback(lambda t: _running.pop(session_id, None))


def is_running(session_id: str) -> bool:
    return session_id in _running


def running_sessions() -> list[str]:
    return list(_running.keys())
