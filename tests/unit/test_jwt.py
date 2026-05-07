import os
os.environ.setdefault("DATABASE_URL","postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("SECRET_KEY","test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY","dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdA==")
import pytest

def test_create_and_decode_access_token():
    from core.auth.jwt_utils import create_access_token, decode_access_token
    token = create_access_token("u1","t1","admin")
    payload = decode_access_token(token)
    assert payload["user_id"] == "u1"
    assert payload["tenant_id"] == "t1"
    assert payload["role"] == "admin"

def test_decode_invalid_token_raises():
    from core.auth.jwt_utils import decode_access_token
    from jose import JWTError
    with pytest.raises(JWTError):
        decode_access_token("bad.token.here")

def test_refresh_token_unique_and_hashable():
    from core.auth.jwt_utils import create_refresh_token, hash_refresh_token
    t = create_refresh_token()
    assert create_refresh_token() != t
    assert hash_refresh_token(t) == hash_refresh_token(t)
    assert hash_refresh_token(t) != t
