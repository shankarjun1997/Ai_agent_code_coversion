import pytest, asyncio
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

class FakeIn(BaseModel): value: str
class FakeOut(BaseModel): result: str

@pytest.mark.asyncio
async def test_run_agent_calls_registered():
    from core.engine.asyncio_engine import AsyncioEngine
    agent = MagicMock(run=AsyncMock(return_value=FakeOut(result="done")))
    engine = AsyncioEngine(registry={"a": agent}, timeout_seconds=5)
    out = await engine.run_agent("a", FakeIn(value="x"))
    assert out.result == "done"

@pytest.mark.asyncio
async def test_run_agent_timeout():
    from core.engine.asyncio_engine import AsyncioEngine
    from core.errors import AgentTimeoutError
    async def slow(i): await asyncio.sleep(10)
    engine = AsyncioEngine(registry={"s": MagicMock(run=slow)}, timeout_seconds=0.01)
    with pytest.raises(AgentTimeoutError):
        await engine.run_agent("s", FakeIn(value="x"))

@pytest.mark.asyncio
async def test_parallel_runs_concurrently():
    from core.engine.asyncio_engine import AsyncioEngine
    import time
    async def timed(i): await asyncio.sleep(0.05); return FakeOut(result="ok")
    engine = AsyncioEngine(registry={k: MagicMock(run=timed) for k in ["a","b","c"]}, timeout_seconds=5)
    start = time.monotonic()
    results = await engine.run_agents_parallel([("a",FakeIn(value="x")),("b",FakeIn(value="y")),("c",FakeIn(value="z"))])
    assert time.monotonic() - start < 0.15
    assert len(results) == 3
