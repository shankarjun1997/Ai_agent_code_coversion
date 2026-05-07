"""PipelineOrchestrator — coordinates agents, gates, and artifact persistence."""

import uuid
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.artifacts.postgres import PostgresArtifactStore
from core.engine.asyncio_engine import AsyncioEngine
from core.engine.base import AgentContext, AgentResult
from core.errors import AgentTimeoutError, GateRejectedError
from core.gates.engine import GateEngine
from core.gates.slack import SlackNotifier
from core.models.tenant import AgentOutput, PipelineRun

logger = logging.getLogger(__name__)


class PipelineDefinition:
    """Describes a pipeline: ordered agent steps and optional gate checkpoints."""

    def __init__(
        self,
        name: str,
        steps: list[str],  # agent_ids in order
        gates: dict[str, str] | None = None,  # {after_agent_id: gate_name}
    ):
        self.name = name
        self.steps = steps
        self.gates = gates or {}


class PipelineOrchestrator:
    def __init__(
        self,
        session: AsyncSession | None = None,
        engine: AsyncioEngine | None = None,
        gate: GateEngine | None = None,
        notifier: SlackNotifier | None = None,
    ):
        self._session = session
        self._engine = engine or AsyncioEngine()
        self._notifier = notifier or SlackNotifier()
        self._gate_engine = gate or GateEngine()
        self._artifact_store = PostgresArtifactStore(session) if session else None

    async def run(self, run_id: str, input_data: dict, db: Any) -> None:
        """High-level run method: executes all 4 agents with 4 gate checkpoints."""
        try:
            await self._engine.run_agent("agent_1", input_data)
            await self._gate_engine.wait_for_approval(run_id, "agent_1", db)
            await self._engine.run_agent("agent_2", input_data)
            await self._gate_engine.wait_for_approval(run_id, "agent_2", db)
            results = await self._engine.run_agents_parallel([
                ("agent_3a", input_data), ("agent_3b", input_data),
                ("agent_3c", input_data), ("agent_3d", input_data),
                ("agent_3e", input_data),
            ])
            await self._gate_engine.wait_for_approval(run_id, "agent_3", db)
            await self._engine.run_agent("agent_4", input_data)
            await self._gate_engine.wait_for_approval(run_id, "agent_4", db)
        except GateRejectedError:
            await db.execute(f"UPDATE pipeline_runs SET status='FAILED' WHERE id='{run_id}'")

    async def start_run(
        self,
        tenant_id: str,
        pipeline: PipelineDefinition,
        input_data: dict[str, Any],
    ) -> PipelineRun:
        run = PipelineRun(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            pipeline_name=pipeline.name,
            status="running",
            input_data=input_data,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def _persist_agent_output(
        self, run_id: uuid.UUID, result: AgentResult
    ) -> None:
        row = AgentOutput(
            id=uuid.uuid4(),
            run_id=run_id,
            agent_id=result.agent_id,
            output=result.output,
            error=result.error,
            duration_ms=result.duration_ms,
        )
        self._session.add(row)
        await self._session.flush()

    async def execute(
        self,
        run: PipelineRun,
        pipeline: PipelineDefinition,
        input_data: dict[str, Any],
    ) -> PipelineRun:
        """
        Execute pipeline steps sequentially.
        Pauses at gate checkpoints (status → awaiting_gate).
        The gate decision must be submitted externally via the gate router.
        This method runs until a gate or completion.
        """
        context = AgentContext(
            run_id=run.id,
            tenant_id=str(run.tenant_id),
            pipeline_name=pipeline.name,
            input_data=input_data,
        )

        try:
            for agent_id in pipeline.steps:
                result = await self._engine.run_agent(agent_id, context)
                await self._persist_agent_output(run.id, result)

                if not result.success:
                    run.status = "failed"
                    logger.error("Agent %s failed: %s", agent_id, result.error)
                    break

                if result.output:
                    context.shared_state.update(result.output)

                # Check if gate follows this step
                if agent_id in pipeline.gates:
                    gate_name = pipeline.gates[agent_id]
                    run.status = "awaiting_gate"
                    await self._session.flush()

                    await self._notifier.notify_gate_pending(
                        run_id=run.id,
                        gate_name=gate_name,
                        pipeline_name=pipeline.name,
                        tenant_id=str(run.tenant_id),
                        summary=result.output,
                    )
                    # Return — gate decision submitted later via API
                    return run

            else:
                run.status = "completed"

        except AgentTimeoutError as exc:
            run.status = "failed"
            logger.error("Pipeline timed out: %s", exc)
        except GateRejectedError as exc:
            run.status = "failed"
            logger.info("Gate rejected: %s", exc)

        await self._session.flush()
        return run

    async def resume_after_gate(
        self,
        run: PipelineRun,
        pipeline: PipelineDefinition,
        gate_name: str,
        decision: str,
        reviewer_id: uuid.UUID | None,
        notes: str | None,
        input_data: dict[str, Any],
    ) -> PipelineRun:
        """Continue execution after a gate decision."""
        await self._gate_engine.enforce_gate(
            run_id=run.id,
            gate_name=gate_name,
            decision=decision,
            reviewer_id=reviewer_id,
            notes=notes,
        )
        await self._notifier.notify_gate_decided(run.id, gate_name, decision, notes or "")

        if decision == "rejected":
            run.status = "failed"
            await self._session.flush()
            return run

        # Find the agent that had the gate and continue from the next step
        gate_agent = next(
            (a for a, g in pipeline.gates.items() if g == gate_name), None
        )
        remaining = pipeline.steps
        if gate_agent and gate_agent in pipeline.steps:
            idx = pipeline.steps.index(gate_agent)
            remaining = pipeline.steps[idx + 1 :]

        context = AgentContext(
            run_id=run.id,
            tenant_id=str(run.tenant_id),
            pipeline_name=pipeline.name,
            input_data=input_data,
        )
        run.status = "running"
        temp_pipeline = PipelineDefinition(pipeline.name, remaining, pipeline.gates)
        return await self.execute(run, temp_pipeline, input_data)
