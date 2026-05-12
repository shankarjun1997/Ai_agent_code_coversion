"""Smoke tests: verify STM tables exist in the DB after alembic upgrade head."""
import os

import pytest
from sqlalchemy import create_engine, inspect, text


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    # Convert asyncpg URL to psycopg2 for sync inspection
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping DB smoke tests",
)
def test_stm_tables_present():
    engine = create_engine(_sync_url())
    tables = set(inspect(engine).get_table_names())
    assert "stm_sessions" in tables
    assert "stm_stage_events" in tables
    assert "stm_gate_decisions" in tables
    engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping DB smoke tests",
)
def test_stm_stage_events_index():
    engine = create_engine(_sync_url())
    idx_names = [i["name"] for i in inspect(engine).get_indexes("stm_stage_events")]
    assert "idx_stm_stage_events_session" in idx_names
    engine.dispose()
