"""Agent registry — maps agent_id strings to callable agent functions."""

import asyncio
from typing import Any, Callable, Awaitable

from core.engine.base import AgentContext, AgentResult

# Agent callable signature: async (context: AgentContext) -> dict[str, Any]
AgentFn = Callable[[AgentContext], Awaitable[dict[str, Any]]]

_registry: dict[str, AgentFn] = {}


def register(agent_id: str) -> Callable[[AgentFn], AgentFn]:
    """Decorator to register an agent function."""

    def _decorator(fn: AgentFn) -> AgentFn:
        _registry[agent_id] = fn
        return fn

    return _decorator


def get_agent(agent_id: str) -> AgentFn:
    if agent_id not in _registry:
        raise KeyError(f"Agent '{agent_id}' not registered. Available: {list(_registry)}")
    return _registry[agent_id]


def list_agents() -> list[str]:
    return list(_registry.keys())


def clear_registry() -> None:
    """Test helper — reset registry."""
    _registry.clear()
