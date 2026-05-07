import pytest, asyncio
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_suspends_until_approved():
    from core.gates.engine import GateEngine
    gate = GateEngine(slack=MagicMock(notify=AsyncMock()))
    db = AsyncMock()
    task = asyncio.create_task(gate.wait_for_approval("r1","agent_1",db))
    await asyncio.sleep(0.01)
    assert not task.done()
    await gate.approve("r1","agent_1","alice","LGTM",db)
    await task

@pytest.mark.asyncio
async def test_rejection_raises():
    from core.gates.engine import GateEngine
    from core.errors import GateRejectedError
    gate = GateEngine(slack=MagicMock(notify=AsyncMock()))
    db = AsyncMock()
    task = asyncio.create_task(gate.wait_for_approval("r2","agent_1",db))
    await asyncio.sleep(0.01)
    await gate.reject("r2","agent_1","bob","Bad",db)
    with pytest.raises(GateRejectedError): await task

def test_restore_gate():
    from core.gates.engine import GateEngine
    gate = GateEngine()
    gate.restore_gate("r3")
    assert "r3" in gate._gates
