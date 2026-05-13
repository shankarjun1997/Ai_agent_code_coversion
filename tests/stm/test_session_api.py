"""Tests for routers/stm_sessions.py — Session API endpoints."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from core.stm.events import reset_broker_for_tests
from core.stm.locks import reset_registry_for_tests
from core.stm.persistence import reset_engine_for_tests


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    from tests.stm.conftest import _apply_schema
    _apply_schema(db_url)
    yield db_path


@pytest.fixture(autouse=True)
def _reset_all():
    reset_engine_for_tests()
    reset_broker_for_tests()
    reset_registry_for_tests()
    yield
    reset_engine_for_tests()
    reset_broker_for_tests()
    reset_registry_for_tests()


@pytest.fixture
def client(tmp_db):
    # Import app after env is patched
    from app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── POST /api/stm/sessions ────────────────────────────────────────────────────

def test_create_session_returns_201(client):
    resp = client.post("/api/stm/sessions", json={
        "target_table": "dim_customer",
        "target_dataset": "wh",
        "source_profiles": ["pg-demo"],
        "raw_input": "load customer dimension",
        "intent_source": "freetext",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert "session_id" in body
    assert body["status"] == "running"
    assert "/api/stm/sessions/" in body["events_url"]


def test_create_session_missing_required_fields(client):
    resp = client.post("/api/stm/sessions", json={
        "target_table": "dim_customer",
        # missing target_dataset, source_profiles, raw_input
    })
    assert resp.status_code == 422


def test_create_session_returns_uuid(client):
    resp = client.post("/api/stm/sessions", json={
        "target_table": "orders",
        "target_dataset": "analytics",
        "source_profiles": ["pg-demo"],
        "raw_input": "load orders",
    })
    assert resp.status_code == 201
    sid = resp.json()["session_id"]
    # Should be a valid UUID
    uuid.UUID(sid)


# ── GET /api/stm/sessions/{id} ────────────────────────────────────────────────

def test_get_session_after_create(client):
    create_resp = client.post("/api/stm/sessions", json={
        "target_table": "dim_customer",
        "target_dataset": "wh",
        "source_profiles": ["pg-demo"],
        "raw_input": "load customers",
    })
    assert create_resp.status_code == 201
    sid = create_resp.json()["session_id"]

    get_resp = client.get(f"/api/stm/sessions/{sid}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["session_id"] == sid
    assert body["target_table"] == "dim_customer"
    assert body["target_dataset"] == "wh"


def test_get_session_not_found(client):
    resp = client.get("/api/stm/sessions/nonexistent-session-id")
    assert resp.status_code == 404


def test_get_session_summary_fields(client):
    create_resp = client.post("/api/stm/sessions", json={
        "target_table": "fact_orders",
        "target_dataset": "warehouse",
        "source_profiles": ["pg-demo"],
        "raw_input": "load order facts",
    })
    sid = create_resp.json()["session_id"]
    body = client.get(f"/api/stm/sessions/{sid}").json()

    expected_keys = {
        "session_id", "status", "current_stage", "target_table",
        "target_dataset", "source_profiles", "stm_result_available",
        "is_running",
    }
    assert expected_keys.issubset(body.keys())


# ── GET /api/stm/sessions/{id}/events ────────────────────────────────────────

def test_events_endpoint_exists_for_valid_session(client):
    create_resp = client.post("/api/stm/sessions", json={
        "target_table": "dim_x",
        "target_dataset": "wh",
        "source_profiles": ["pg-demo"],
        "raw_input": "load x",
    })
    sid = create_resp.json()["session_id"]

    # Just check the endpoint starts streaming (don't read all events)
    with client.stream("GET", f"/api/stm/sessions/{sid}/events") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


def test_events_endpoint_not_found_for_missing_session(client):
    resp = client.get("/api/stm/sessions/no-such-session/events")
    assert resp.status_code == 404


# ── GET /api/stm/sessions/{id}/export ────────────────────────────────────────

def test_export_not_ready_returns_409(client):
    create_resp = client.post("/api/stm/sessions", json={
        "target_table": "dim_y",
        "target_dataset": "wh",
        "source_profiles": ["pg-demo"],
        "raw_input": "load y",
    })
    sid = create_resp.json()["session_id"]

    # Session just started, not done yet
    resp = client.get(f"/api/stm/sessions/{sid}/export")
    assert resp.status_code == 409


def test_export_not_found(client):
    resp = client.get("/api/stm/sessions/ghost-session/export")
    assert resp.status_code == 404
