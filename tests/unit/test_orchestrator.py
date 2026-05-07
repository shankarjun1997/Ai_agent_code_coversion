import pytest, uuid
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

class StubOut(BaseModel): data: str = "ok"

@pytest.fixture
def mocks():
    engine = MagicMock(run_agent=AsyncMock(return_value=StubOut()), run_agents_parallel=AsyncMock(return_value=[StubOut()]*5))
    gate = MagicMock(wait_for_approval=AsyncMock(), restore_gate=MagicMock())
    db = AsyncMock()
    db.add = MagicMock()
    return engine, gate, db

@pytest.mark.asyncio
async def test_calls_all_agents(mocks):
    from core.pipeline.orchestrator import PipelineOrchestrator
    engine, gate, db = mocks
    await PipelineOrchestrator(engine=engine, gate=gate).run(str(uuid.uuid4()), {}, db)
    calls = [c.args[0] for c in engine.run_agent.call_args_list]
    assert "agent_1" in calls and "agent_2" in calls and "agent_4" in calls
    engine.run_agents_parallel.assert_called_once()

@pytest.mark.asyncio
async def test_waits_four_gates(mocks):
    from core.pipeline.orchestrator import PipelineOrchestrator
    engine, gate, db = mocks
    await PipelineOrchestrator(engine=engine, gate=gate).run(str(uuid.uuid4()), {}, db)
    assert gate.wait_for_approval.call_count == 4

@pytest.mark.asyncio
async def test_marks_failed_on_rejection(mocks):
    from core.pipeline.orchestrator import PipelineOrchestrator
    from core.errors import GateRejectedError
    engine, gate, db = mocks
    gate.wait_for_approval = AsyncMock(side_effect=GateRejectedError("bad"))
    await PipelineOrchestrator(engine=engine, gate=gate).run(str(uuid.uuid4()), {}, db)
    assert any("FAILED" in str(c) for c in db.execute.call_args_list)
