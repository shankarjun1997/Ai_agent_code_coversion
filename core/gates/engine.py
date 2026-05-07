"""GateEngine — human-in-the-loop approval gates for pipeline runs."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import GateRejectedError
from core.models.tenant import GateEvent, PipelineRun


class GateEngine:
    """
    Manages gate checkpoints in a pipeline run.
    Writes GateEvent rows and raises GateRejectedError on rejection.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def record_gate(
        self,
        run_id: uuid.UUID,
        gate_name: str,
        decision: str,  # "approved" | "rejected"
        reviewer_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> GateEvent:
        """Persist a gate decision."""
        event = GateEvent(
            id=uuid.uuid4(),
            run_id=run_id,
            gate_name=gate_name,
            decision=decision,
            reviewer_id=reviewer_id,
            notes=notes,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def enforce_gate(
        self,
        run_id: uuid.UUID,
        gate_name: str,
        decision: str,
        reviewer_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> GateEvent:
        """
        Record gate and raise GateRejectedError if rejected.
        Call this during pipeline execution at checkpoint boundaries.
        """
        event = await self.record_gate(run_id, gate_name, decision, reviewer_id, notes)
        if decision == "rejected":
            raise GateRejectedError(notes=notes or "")
        return event
