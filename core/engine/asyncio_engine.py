"""AsyncIO-based execution engine."""

import asyncio
import time
from typing import Any

from core.errors import AgentTimeoutError


class AsyncioEngine:
    def __init__(self, registry: dict | None = None, timeout_seconds: float = 30):
        self._registry = registry or {}
        self.timeout = timeout_seconds

    async def run_agent(self, agent_id: str, input: Any) -> Any:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent '{agent_id}' not registered")
        try:
            return await asyncio.wait_for(agent.run(input), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise AgentTimeoutError(agent_id, self.timeout)

    async def run_agents_parallel(self, tasks: list[tuple[str, Any]]) -> list[Any]:
        coros = [self.run_agent(agent_id, inp) for agent_id, inp in tasks]
        return await asyncio.gather(*coros)
