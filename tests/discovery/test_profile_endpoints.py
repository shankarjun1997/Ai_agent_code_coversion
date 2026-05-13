import os, pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", key)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("ENCRYPTION_KEY", "test-enc-key-32chars-padded12345")
    from app import app
    return TestClient(app, raise_server_exceptions=True)

def test_post_oracle_profile(client):
    r = client.post("/api/discovery/profiles/oracle", json={"label": "test-ora", "dsn": "user/pass@host:1521/svc"})
    assert r.status_code == 200
    assert r.json()["dialect"] == "oracle"

def test_post_mysql_profile(client):
    r = client.post("/api/discovery/profiles/mysql", json={"label": "test-my", "host": "h", "port": 3306, "db": "d", "user": "u", "password": "p"})
    assert r.status_code == 200
    assert r.json()["dialect"] == "mysql"

def test_post_mssql_profile(client):
    r = client.post("/api/discovery/profiles/mssql", json={"label": "test-ms", "host": "h", "port": 1433, "db": "d", "user": "u", "password": "p"})
    assert r.status_code == 200
    assert r.json()["dialect"] == "mssql"

def test_post_bigquery_profile(client):
    r = client.post("/api/discovery/profiles/bigquery", json={"label": "test-bq", "project_id": "my-project"})
    assert r.status_code == 200
    assert r.json()["dialect"] == "bigquery"
