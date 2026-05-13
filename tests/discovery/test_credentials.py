from core.discovery.credentials import encrypt, decrypt, generate_key

def test_roundtrip(monkeypatch):
    key = generate_key()
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", key)
    blob = encrypt({"user": "alice", "password": "s3cret"})
    assert isinstance(blob, bytes)
    assert b"alice" not in blob
    data = decrypt(blob)
    assert data == {"user": "alice", "password": "s3cret"}

def test_missing_key_raises(monkeypatch):
    import pytest
    monkeypatch.delenv("STM_PROFILE_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        encrypt({"x": 1})
