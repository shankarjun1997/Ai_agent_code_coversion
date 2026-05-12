import importlib


def test_stm_config_defaults(monkeypatch):
    for key in (
        "STM_POOL_SIZE", "STM_LLM_MODEL_L1", "STM_JIRA_WRITEBACK_ENABLED",
        "STM_VALIDATION_WEIGHTS", "STM_PROBE_TIMEOUT_SEC", "STM_METADATA_CACHE_TTL_SEC",
    ):
        monkeypatch.delenv(key, raising=False)

    import core.config as cfg
    importlib.reload(cfg)
    cfg._lru_cache_clear = getattr(cfg.get_settings, "cache_clear", None)
    if cfg._lru_cache_clear:
        cfg._lru_cache_clear()

    s = cfg.Settings(
        DATABASE_URL="sqlite:///./test.db",
        SECRET_KEY="test",
        ENCRYPTION_KEY="test",
    )
    assert s.STM_POOL_SIZE == 4
    assert s.STM_LLM_MODEL_L1 == "claude-haiku-4-5-20251001"
    assert s.STM_JIRA_WRITEBACK_ENABLED is False
    weights = s.stm_validation_weights_tuple
    assert abs(sum(weights) - 1.0) < 1e-9
    assert s.STM_PROBE_TIMEOUT_SEC == 30
    assert s.STM_METADATA_CACHE_TTL_SEC == 900
