import pytest
from unittest.mock import AsyncMock, MagicMock, patch

def _cm(rows):
    r = MagicMock(); r.scalars.return_value.all.return_value = rows
    s = AsyncMock(); s.execute = AsyncMock(return_value=r)
    cm = MagicMock(); cm.__aenter__ = AsyncMock(return_value=s); cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)

@pytest.mark.asyncio
async def test_awaiting_gates_restored():
    from core.gates.engine import GateEngine
    tenant = MagicMock(slug="acme", db_url_encrypted="enc")
    run = MagicMock(id="run-1")
    gate = GateEngine()
    with patch("app.get_platform_session_factory", return_value=_cm([tenant])), \
         patch("app.get_tenant_session_factory", return_value=_cm([run])), \
         patch("app.decrypt_db_url", return_value="postgresql+asyncpg://u:p@h/t"):
        from app import recover_awaiting_gates
        await recover_awaiting_gates(gate)
    assert "run-1" in gate._gates

@pytest.mark.asyncio
async def test_broken_tenant_does_not_crash():
    from core.gates.engine import GateEngine
    tenant = MagicMock(slug="bad", db_url_encrypted="bad")
    gate = GateEngine()
    with patch("app.get_platform_session_factory", return_value=_cm([tenant])), \
         patch("app.decrypt_db_url", side_effect=Exception("fail")):
        from app import recover_awaiting_gates
        await recover_awaiting_gates(gate)
    assert len(gate._gates) == 0
