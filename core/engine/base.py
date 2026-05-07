"""Abstract base class for agent execution engines."""

import uuid
from abc import ABC, abstractmethod
from typing import Any


class AgentContext:
    """Carries per-run context passed to each agent."""

    def __init__(
        self,
        run_id: uuid.UUID,
        tenant_id: str,
        pipeline_name: str,
        input_data: dict[str, Any],
        shared_state: dict[str, Any] | None = None,
    ):
        self.run_id = run_id
        self.tenant_id = tenant_id
        self.pipeline_name = pipeline_name
        self.input_data = input_data
        self.shared_state: dict[str, Any] = shared_state or {}


class AgentResult:
    def __init__(
        self,
        agent_id: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ):
        self.agent_id = agent_id
        self.output = output
        self.error = error
        self.duration_ms = duration_ms

    @property
    def success(self) -> bool:
        return self.error is None


class ExecutionEngine(ABC):
    """Interface for running a single agent step."""

    @abstractmethod
    async def run_agent(
        self,
        agent_id: str,
        context: AgentContext,
    ) -> AgentResult:
        """Execute agent and return result."""
        ...

    @abstractmethod
    async def run_pipeline(
        self,
        agent_ids: list[str],
        context: AgentContext,
    ) -> list[AgentResult]:
        """Execute agents sequentially, stopping on error."""
        ...
