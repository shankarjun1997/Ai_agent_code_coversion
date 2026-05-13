"""Base classes for STM agentic pipeline stages.

Every stage (L1–L6) is an StmAgent subclass.  The coordinator calls
``agent.run(ctx)`` and receives a BlackboardDelta back.

AgentContext  — read-only view the agent receives (blackboard + config)
BlackboardDelta — the mutations the agent wants applied to the blackboard
StmAgent      — ABC; subclasses implement _execute()
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from core.stm.blackboard import StmBlackboard

logger = logging.getLogger(__name__)


# ── LLM client protocol ───────────────────────────────────────────────────────

class LLMClientProtocol:
    """Minimal interface expected by agents — real impl lives in core/llm_client.py."""

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 8192,
        temperature: float = 0.1,
    ) -> str:  # pragma: no cover
        raise NotImplementedError


# ── AgentContext ──────────────────────────────────────────────────────────────

@dataclass
class AgentContext:
    """Immutable context passed into each agent run."""

    blackboard: StmBlackboard
    llm: LLMClientProtocol
    # Per-stage config overrides (e.g. model name, max_tokens)
    config: Dict[str, Any] = field(default_factory=dict)
    # Callback for publishing SSE progress events mid-run (optional)
    emit: Optional[Callable[[str, Dict[str, Any]], None]] = None

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)


# ── BlackboardDelta ───────────────────────────────────────────────────────────

@dataclass
class BlackboardDelta:
    """Mutations the agent wants applied to the shared blackboard.

    The coordinator applies these after a successful agent run by calling
    ``delta.apply(blackboard)``.
    """

    updates: Dict[str, Any] = field(default_factory=dict)
    # LLM usage metadata (for cost tracking)
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    llm_model: Optional[str] = None
    duration_ms: int = 0
    error: Optional[str] = None

    def apply(self, bb: StmBlackboard) -> None:
        """Apply ``updates`` to *bb* in-place."""
        for attr, value in self.updates.items():
            if hasattr(bb, attr):
                setattr(bb, attr, value)
            else:
                logger.warning("BlackboardDelta.apply: unknown attribute %r on StmBlackboard", attr)

    @classmethod
    def failure(cls, error: str, duration_ms: int = 0) -> "BlackboardDelta":
        return cls(error=error, duration_ms=duration_ms)


# ── StmAgent ABC ──────────────────────────────────────────────────────────────

class StmAgent(ABC):
    """Abstract base for all STM pipeline stages.

    Subclasses must implement ``_execute(ctx)``.  The ``run()`` wrapper
    handles timing, error catching, and logging so subclasses stay focused
    on business logic.
    """

    #: Stage label used in events/logs (e.g. "L1", "L2")
    stage: str = "??"

    async def run(self, ctx: AgentContext) -> BlackboardDelta:
        """Run the agent, returning a BlackboardDelta (never raises)."""
        t0 = time.monotonic()
        try:
            delta = await self._execute(ctx)
            delta.duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info("Agent %s completed in %dms", self.stage, delta.duration_ms)
            return delta
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.exception("Agent %s failed: %s", self.stage, exc)
            return BlackboardDelta.failure(str(exc), duration_ms=duration_ms)

    @abstractmethod
    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        """Core logic — implemented by each stage subclass."""
        ...  # pragma: no cover
