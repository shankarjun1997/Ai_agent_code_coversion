from core.discovery.credentials import encrypt, decrypt, generate_key

def test_roundtrip(monkeypatch):
    key = generate_key()
    monkeypatch.setenv("STM_PROFILE_ENCRYPTION_KEY", key)
    blob = encrypt({"user": "alice", "password": "s3cret"})
    assert isinstance(blob, bytes)
    assert b"alice" not in blob
    data = decrypt(blob)
    assert data == {"user": "alice", "password": "s3cret"}

def test_missing_key_falls_back_to_plain(monkeypatch):
    monkeypatch.delenv("STM_PROFILE_ENCRYPTION_KEY", raising=False)
    blob = encrypt({"x": 1})
    # Without a key, encrypt falls back to reversible base64 (dev mode).
    assert blob.startswith(b"PLAIN:")
    assert decrypt(blob) == {"x": 1}
