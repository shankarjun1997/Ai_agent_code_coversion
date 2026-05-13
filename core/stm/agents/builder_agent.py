"""L6 Builder Agent — produces the final MappingResult / STM output.

Task 4.3: stub implementation — pass-through that marks the session done
and stores an empty stm_result placeholder.

Full implementation (Task 7.3) will call core/stm/exporter.py to render
the xlsx/csv from CandidateMappings + Transformations + ValidationReport.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import StageStatus

logger = logging.getLogger(__name__)


class BuilderAgent(StmAgent):
    """L6 — assembles the final STM artifact.

    Stub: produces a minimal stm_result dict and advances stage to 'done'.
    Replace _execute body in Task 7.3 with full exporter call.
    """

    stage = "L6"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard

        # Stub result — real builder will call exporter.to_xlsx() here
        stm_result: Dict[str, Any] = {
            "status": "stub",
            "session_id": bb.session_id,
            "target_table": bb.target_table,
            "target_dataset": bb.target_dataset,
            "mapping_count": len(bb.candidate_mappings.rows),
            "transformation_count": len(bb.transformations.rows),
            "overall_band": bb.validation.overall_band,
            "xlsx_bytes": None,  # populated in Task 7.3
        }

        logger.info(
            "BuilderAgent stub: session=%s mappings=%d",
            bb.session_id,
            stm_result["mapping_count"],
        )

        return BlackboardDelta(
            updates={
                "stm_result": stm_result,
                "current_stage": "done",
            },
        )
