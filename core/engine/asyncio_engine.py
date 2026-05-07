"""AsyncIO-based ExecutionEngine implementation."""

import asyncio
import time
import uuid
from typing import Any

from core.config import get_settings
from core.engine.base import AgentContext, AgentResult, ExecutionEngine
from core.engine.registry import get_agent
from core.errors import AgentTimeoutError


class AsyncioEngine(ExecutionEngine):
    def __init__(self, timeout_seconds: int | None = None):
        settings = get_settings()
        self.timeout = timeout_seconds or settings.AGENT_TIMEOUT_SECONDS

    async def run_agent(
        self,
        agent_id: str,
        context: AgentContext,
    ) -> AgentResult:
        fn = get_agent(agent_id)
        start = time.monotonic()
        try:
            output = await asyncio.wait_for(fn(context), timeout=self.timeout)
            duration_ms = int((time.monotonic() - start) * 1000)
            return AgentResult(agent_id=agent_id, output=output, duration_ms=duration_ms)
        except asyncio.TimeoutError:
            raise AgentTimeoutError(agent_id, self.timeout)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return AgentResult(
                agent_id=agent_id,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=duration_ms,
            )

    async def run_pipeline(
        self,
        agent_ids: list[str],
        context: AgentContext,
    ) -> list[AgentResult]:
        results: list[AgentResult] = []
        for agent_id in agent_ids:
            result = await self.run_agent(agent_id, context)
            results.append(result)
            if not result.success:
                break
            # Merge output into shared state for next agent
            if result.output:
                context.shared_state.update(result.output)
        return results
