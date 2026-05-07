import os
os.environ.setdefault("DATABASE_URL","postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("SECRET_KEY","test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY","dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdA==")
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from core.auth.jwt_utils import create_access_token
from core.auth.middleware import require_role

def make_app(role):
    app = FastAPI()
    @app.get("/p")
    def p(u=Depends(require_role(role))): return {"role": u["role"]}
    return app

def test_valid_token_passes():
    resp = TestClient(make_app("admin")).get("/p", headers={"Authorization": f"Bearer {create_access_token('u1','t1','admin')}"})
    assert resp.status_code == 200

def test_missing_token_401():
    assert TestClient(make_app("admin")).get("/p").status_code == 401

def test_wrong_role_403():
    resp = TestClient(make_app("admin")).get("/p", headers={"Authorization": f"Bearer {create_access_token('u1','t1','viewer')}"})
    assert resp.status_code == 403

def test_hierarchy_engineer_passes_viewer_route():
    resp = TestClient(make_app("viewer")).get("/p", headers={"Authorization": f"Bearer {create_access_token('u1','t1','engineer')}"})
    assert resp.status_code == 200
