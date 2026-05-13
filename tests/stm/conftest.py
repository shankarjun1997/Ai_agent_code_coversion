import os
import pytest


def _apply_schema(db_url: str) -> None:
    """Apply STM table DDL directly via sync SQLAlchemy (bypasses async alembic env.py)."""
    from sqlalchemy import create_engine, text
    engine = create_engine(db_url, future=True)
    ddl = """
    CREATE TABLE IF NOT EXISTS stm_sessions (
        session_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        current_stage TEXT NOT NULL,
        target_table TEXT NOT NULL,
        target_dataset TEXT NOT NULL,
        source_profiles TEXT NOT NULL,
        intent_source TEXT NOT NULL,
        jira_issue_key TEXT,
        raw_input TEXT NOT NULL,
        blackboard_json TEXT NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        created_by TEXT
    );
    CREATE TABLE IF NOT EXISTS stm_stage_events (
        event_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES stm_sessions(session_id),
        stage TEXT NOT NULL,
        event_kind TEXT NOT NULL,
        artifact_kind TEXT,
        artifact_json TEXT,
        confidence REAL,
        llm_model TEXT,
        llm_tokens_in INTEGER,
        llm_tokens_out INTEGER,
        duration_ms INTEGER,
        message TEXT,
        created_at DATETIME NOT NULL
    );
    CREATE TABLE IF NOT EXISTS stm_gate_decisions (
        decision_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES stm_sessions(session_id),
        gate_name TEXT NOT NULL,
        decision TEXT NOT NULL,
        reviewer TEXT,
        notes TEXT,
        refine_target TEXT,
        refine_feedback TEXT,
        decided_at DATETIME NOT NULL
    );
    """
    with engine.begin() as conn:
        for stmt in ddl.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
    engine.dispose()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    _apply_schema(db_url)
    yield db_path


@pytest.fixture(autouse=True)
def _reset_engine():
    from core.stm.persistence import reset_engine_for_tests
    reset_engine_for_tests()
    yield
    reset_engine_for_tests()
