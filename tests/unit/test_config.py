import pytest
import os

def test_config_loads_required_vars(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/platform")
    monkeypatch.setenv("SECRET_KEY", "supersecretkey123")
    monkeypatch.setenv("ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdA==")

    from core.config import Settings
    s = Settings()
    assert s.DATABASE_URL.startswith("postgresql")
    assert s.SECRET_KEY == "supersecretkey123"

def test_config_raises_on_missing_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(Exception):
        from importlib import reload
        import core.config
        reload(core.config)
        core.config.Settings()
