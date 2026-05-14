"""STM Session Coordinator.

Manages per-session asyncio.Task pipeline execution:
  L1 → L2 → [Gate 1] → L3 → L4 → L5 → [Gate 2] → L6 → done

Each stage runs its StmAgent, applies the BlackboardDelta to the shared
blackboard, persists the updated state, and publishes SSE events.

Gate stalls use asyncio.Event — the pipeline task waits until a reviewer
calls approve/reject/refine via the gate decision API.

Recovery on startup is handled in app.py/_recover_stm_sessions().
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.stm.agents.base import AgentContext, LLMClientProtocol
from core.stm.agents.builder_agent import BuilderAgent
from core.stm.agents.intent_agent import IntentAgent
from core.stm.agents.metadata_agent import MetadataAgent
from core.stm.agents.semantic_mapping_agent import SemanticMappingAgent
from core.stm.agents.transformation_agent import TransformationAgent
from core.stm.agents.validation_agent import ValidationAgent
from core.stm.blackboard import StageStatus, StmBlackboard
from core.stm.events import EventKind, SseEvent, get_broker
from core.stm.locks import SessionLockRegistry, get_registry as get_lock_registry
from core.stm.persistence import (
    append_event, create_session, load_blackboard, record_gate_decision,
    save_blackboard, set_session_status,
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

# Gates: which stage they stall after, and the gate name
# key = stage that just completed → gate to check
_GATE_AFTER: Dict[str, str] = {
    "L2": "gate1_metadata",
    "L5": "gate2_validation",
}

# Active coordinator tasks keyed by session_id
_running: Dict[str, asyncio.Task] = {}

# Per-session gate events: session_id → {gate_name → asyncio.Event}
_gate_events: Dict[str, Dict[str, asyncio.Event]] = {}

# Per-session start gates (used when session was created with pause_for_attachments=true)
_start_events: Dict[str, asyncio.Event] = {}


def _get_start_event(session_id: str) -> asyncio.Event:
    if session_id not in _start_events:
        _start_events[session_id] = asyncio.Event()
    return _start_events[session_id]


def signal_start(session_id: str) -> bool:
    """Unblock a session waiting on pause_for_attachments. Returns True if unblocked."""
    ev = _start_events.get(session_id)
    if ev is None:
        return False
    ev.set()
    return True


def _make_llm() -> LLMClientProtocol:
    """Build the real LLM client from env, or return a no-op stub.

    Provider precedence (first found wins):
      LLM_API_KEY  (preferred — generic)
      DEEPSEEK_API_KEY
      OPENROUTER_API_KEY
      ANTHROPIC_API_KEY (only if LLM_BASE_URL points at an Anthropic-compat endpoint)

    Base URL: LLM_BASE_URL env (defaults to OpenRouter in llm_client).
    Model:    LLM_MODEL env.
    """
    try:
        api_key = (
            os.environ.get("LLM_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        if api_key:
            from core.llm_client import LLMClient
            return LLMClient(api_key=api_key)
    except Exception as exc:
        logger.warning("Could not build LLM client: %s", exc)

    class _StubLLM:
        def complete(self, *a, **kw) -> str:
            return "{}"

    return _StubLLM()


def _get_gate_event(session_id: str, gate_name: str) -> asyncio.Event:
    if session_id not in _gate_events:
        _gate_events[session_id] = {}
    if gate_name not in _gate_events[session_id]:
        _gate_events[session_id][gate_name] = asyncio.Event()
    return _gate_events[session_id][gate_name]


def _cleanup_gate_events(session_id: str) -> None:
    _gate_events.pop(session_id, None)


async def _run_pipeline(
    session_id: str,
    llm: LLMClientProtocol,
    config: Dict[str, Any],
    lock_registry: SessionLockRegistry,
) -> None:
    """Inner coroutine — runs all stages L1→L6 with gate stalls."""
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

    # Pause-for-attachments: if the session was created with pause flag,
    # wait until /start is called or 5 minutes elapse, then RELOAD bb so the
    # attachments uploaded during the pause are visible to L1/L2.
    if config.get("pause_for_attachments") and bb.current_stage == "L1":
        await emit(EventKind.stage_started, stage="L0", data={"message": "awaiting attachments"})
        start_event = _get_start_event(session_id)
        try:
            await asyncio.wait_for(start_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            logger.warning("Coordinator: pause_for_attachments timed out for %s", session_id)
        finally:
            _start_events.pop(session_id, None)
        try:
            bb = await load_blackboard(session_id)
        except KeyError:
            logger.error("Coordinator: session %s gone after pause", session_id)
            return

    try:
        for stage in _STAGE_ORDER:
            # Skip stages already completed (recovery path)
            stage_order_idx = _STAGE_ORDER.index(stage)
            current_idx = _STAGE_ORDER.index(bb.current_stage) if bb.current_stage in _STAGE_ORDER else 0
            if stage_order_idx < current_idx:
                continue

            AgentClass = _STAGE_AGENTS[stage]
            agent = AgentClass()

            await emit(EventKind.stage_started, stage=stage)

            ctx = AgentContext(blackboard=bb, llm=llm, config=config)
            delta = await agent.run(ctx)

            if delta.error:
                logger.error("Coordinator: stage %s failed: %s", stage, delta.error)
                await emit(EventKind.stage_failed, stage=stage, data={"error": delta.error})
                await set_session_status(session_id, "failed")
                await broker.publish(session_id, SseEvent(
                    kind=EventKind.session_failed, stage=stage,
                    data={"error": delta.error}, session_id=session_id,
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

            # ── Gate stall check ──────────────────────────────────────────────
            gate_name = _GATE_AFTER.get(stage)
            if gate_name:
                gate = bb.gates.get(gate_name)
                # Only stall if gate hasn't already been decided (recovery)
                # and gates are not configured to auto-approve (test/CI mode)
                gates_enabled = config.get("gates_enabled", True)
                if gate and gate.decision == "pending" and gates_enabled:
                    await set_session_status(session_id, "awaiting_review")
                    await emit(EventKind.gate_waiting, stage=stage,
                               data={"gate": gate_name})

                    # Wait for reviewer decision
                    gate_event = _get_gate_event(session_id, gate_name)
                    await gate_event.wait()

                    # Reload blackboard to get gate decision
                    bb = await load_blackboard(session_id)
                    gate = bb.gates.get(gate_name)

                    if gate and gate.decision == "rejected":
                        logger.info("Coordinator: gate %s rejected session %s", gate_name, session_id)
                        await set_session_status(session_id, "rejected")
                        await broker.publish(session_id, SseEvent(
                            kind=EventKind.session_failed, stage=stage,
                            data={"reason": "gate_rejected", "gate": gate_name},
                            session_id=session_id,
                        ))
                        await broker.close(session_id)
                        return

                    if gate and gate.decision == "refine":
                        # Mark stages downstream of refine_target as stale
                        refine_target = gate.refine_target_stage
                        if refine_target and refine_target in _STAGE_ORDER:
                            refine_idx = _STAGE_ORDER.index(refine_target)
                            # Reset current_stage to refine_target to re-run from there
                            bb.current_stage = refine_target
                            # Mark downstream artifacts stale
                            _mark_stale_from(bb, refine_idx)
                            await save_blackboard(bb)
                            await set_session_status(session_id, "running")
                            # Re-start pipeline from refine_target by restarting loop
                            # (handled by the skip logic at top of for loop)
                            # We need to restart the whole loop
                            break  # exits for loop, handled below

                    # approved → continue
                    await set_session_status(session_id, "running")
        else:
            # Normal completion (no break from refine)
            await set_session_status(session_id, "done")
            await _jira_writeback(bb)
            await broker.publish(session_id, SseEvent(
                kind=EventKind.session_done, stage="L6",
                data={"session_id": session_id}, session_id=session_id,
            ))
            await append_event(session_id, stage="done", event_kind=EventKind.session_done.value)
            await broker.close(session_id)
            logger.info("Coordinator: session %s completed", session_id)
            return

        # Refine path: restart pipeline recursively (new task to avoid stack overflow)
        logger.info("Coordinator: session %s refinement requested, restarting pipeline", session_id)
        await _run_pipeline(session_id, llm, config, lock_registry)

    finally:
        _cleanup_gate_events(session_id)


def _mark_stale_from(bb: StmBlackboard, from_idx: int) -> None:
    """Mark all stage artifacts from from_idx onwards as stale."""
    stage_artifacts = {
        0: "intent",
        1: "metadata_graph",
        2: "candidate_mappings",
        3: "transformations",
        4: "validation",
    }
    for idx in range(from_idx, len(_STAGE_ORDER) - 1):  # skip L6
        attr = stage_artifacts.get(idx)
        if attr:
            artifact = getattr(bb, attr, None)
            if artifact and hasattr(artifact, "status"):
                artifact.status = StageStatus.stale


async def decide_gate(
    session_id: str,
    gate_name: str,
    decision: str,
    reviewer: Optional[str] = None,
    notes: Optional[str] = None,
    refine_target: Optional[str] = None,
    refine_feedback: Optional[str] = None,
) -> None:
    """Record a gate decision and unblock the waiting pipeline task."""
    if decision not in ("approved", "rejected", "refine"):
        raise ValueError(f"Invalid gate decision: {decision!r}")

    # Load blackboard and update gate
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

    # Mapping-memory seed: log every gate2 decision (approved/refine/rejected) as
    # training signal for future RAG retrieval. Gate1 decisions skipped — they
    # don't yet have per-field mappings.
    if gate_name == "gate2_validation":
        try:
            from core.stm.persistence import log_mapping_memory_rows  # local import to avoid cycle on cold start
            await log_mapping_memory_rows(
                session_id=session_id,
                gate_name=gate_name,
                decision=decision,
                reviewer=reviewer,
                blackboard=bb,
                reviewer_notes=notes,
                refine_feedback=refine_feedback,
            )
        except Exception as e:  # never block the gate path on memory write
            logging.getLogger(__name__).warning("mapping_memory log failed: %s", e)

    # Unblock the waiting pipeline task
    gate_event = _get_gate_event(session_id, gate_name)
    gate_event.set()

    # Publish SSE
    broker = get_broker()
    await broker.publish(session_id, SseEvent(
        kind=EventKind.gate_decided, stage="GATE",
        data={"gate": gate_name, "decision": decision},
        session_id=session_id,
    ))


async def start_session(
    bb: StmBlackboard,
    *,
    raw_input: str,
    intent_source: str,
    jira_issue_key: Optional[str] = None,
    llm: Optional[LLMClientProtocol] = None,
    config: Optional[Dict[str, Any]] = None,
    pause_for_attachments: bool = False,
) -> str:
    """Create a new STM session and start the pipeline as a background task.

    If pause_for_attachments=True, the coordinator pauses before L1 until
    signal_start(session_id) is called (or 5min timeout). UI uses this to
    upload CSV/PDF/DOCX attachments after create but before L1 runs.
    """
    session_id = bb.session_id
    await create_session(
        bb,
        raw_input=raw_input,
        intent_source=intent_source,
        jira_issue_key=jira_issue_key,
    )

    _llm = llm or _make_llm()
    _config = dict(config or {})
    if pause_for_attachments:
        _config["pause_for_attachments"] = True
        _get_start_event(session_id)
    lock_registry = get_lock_registry()

    task = asyncio.create_task(
        _run_pipeline(session_id, _llm, _config, lock_registry),
        name=f"stm-pipeline-{session_id}",
    )
    _running[session_id] = task
    task.add_done_callback(lambda _t: _running.pop(session_id, None))
    return session_id


async def resume_session(
    session_id: str,
    *,
    llm: Optional[LLMClientProtocol] = None,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Re-queue a session interrupted by server restart."""
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
    task.add_done_callback(lambda _t: _running.pop(session_id, None))


async def _jira_writeback(bb: StmBlackboard) -> None:
    """Post a comment on the Jira issue when session completes successfully.

    Env-gated by STM_JIRA_WRITEBACK_ENABLED. Best-effort — failures logged but
    do not surface to the user.
    """
    if os.environ.get("STM_JIRA_WRITEBACK_ENABLED", "false").lower() not in ("1", "true", "yes"):
        return
    if not bb.intent or bb.intent.source != "jira" or not bb.intent.jira_issue_key:
        return

    url = os.environ.get("JIRA_URL")
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not (url and email and token):
        logger.warning("STM_JIRA_WRITEBACK_ENABLED set but Jira creds missing")
        return

    issue_key = bb.intent.jira_issue_key
    band = bb.validation.overall_band if bb.validation else "n/a"
    n_fields = len(bb.candidate_mappings.mappings) if bb.candidate_mappings else 0
    body = (
        f"STM generated for {bb.target_dataset}.{bb.target_table}\n"
        f"Session: {bb.session_id}\n"
        f"Confidence band: {band}\n"
        f"Field mappings: {n_fields}\n"
        f"Sources: {', '.join(bb.selected_source_profiles)}"
    )

    try:
        from agents.shared.jira_client import JiraClient
        client = JiraClient(url=url, email=email, api_token=token)
        await asyncio.to_thread(client.add_comment, issue_key, body)
        logger.info("Posted Jira comment on %s for session %s", issue_key, bb.session_id)
    except Exception as exc:
        logger.warning("Jira write-back failed for %s: %s", issue_key, exc)


def is_running(session_id: str) -> bool:
    return session_id in _running


def running_sessions() -> List[str]:
    return list(_running.keys())
