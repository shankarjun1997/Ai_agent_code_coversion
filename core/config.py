from __future__ import annotations

import os
from functools import lru_cache
from typing import Tuple

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SECRET_KEY: str
    ENCRYPTION_KEY: str
    OPENROUTER_API_KEY: str = ""
    SLACK_WEBHOOK_URL: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    AGENT_TIMEOUT_SECONDS: int = 300

    # STM agentic evolution
    STM_PROFILE_ENCRYPTION_KEY: str = ""
    STM_POOL_SIZE: int = 4
    STM_JIRA_WRITEBACK_ENABLED: bool = False
    STM_LLM_MODEL_L1: str = "claude-haiku-4-5-20251001"
    STM_LLM_MODEL_L2: str = "claude-sonnet-4-6"
    STM_LLM_MODEL_L3: str = "claude-opus-4-7"
    STM_LLM_MODEL_L4: str = "claude-opus-4-7"
    STM_VALIDATION_WEIGHTS: str = "0.4,0.25,0.2,0.1,0.05"
    STM_VALIDATION_LLM_EXPLAIN: bool = False
    STM_PROBE_TIMEOUT_SEC: int = 30
    STM_METADATA_CACHE_TTL_SEC: int = 900

    @property
    def stm_validation_weights_tuple(self) -> Tuple[float, ...]:
        return tuple(float(x) for x in self.STM_VALIDATION_WEIGHTS.split(","))


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Module-level aliases for legacy code that does `from core.config import STM_POOL_SIZE`
def __getattr__(name: str):
    s = get_settings()
    if hasattr(s, name):
        return getattr(s, name)
    if name == "STM_VALIDATION_WEIGHTS":
        return s.stm_validation_weights_tuple
    raise AttributeError(name)
