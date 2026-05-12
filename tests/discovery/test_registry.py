import pytest
from core.discovery.registry import get_provider, register_provider
from core.discovery.base import SourceProvider, PingResult


class _Fake(SourceProvider):
    dialect = "postgres"
    async def ping(self, p): return PingResult(ok=True)
    async def list_schemas(self, p): return []
    async def list_tables(self, p, s): return []
    async def get_columns(self, p, s, t): return []
    async def get_foreign_keys(self, p, s, t): return []
    async def profile_column(self, p, s, t, c, sample_rows=0): return None
    async def search_by_keywords(self, p, kw, limit=50): return []


def test_unknown_dialect_raises():
    with pytest.raises(ValueError):
        get_provider("nonexistent")


def test_register_and_get():
    fake = _Fake()
    register_provider("postgres", fake)
    assert get_provider("postgres") is fake
