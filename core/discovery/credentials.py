"""Fernet-based credential encryption for source profiles."""
from __future__ import annotations
import json, os
from cryptography.fernet import Fernet

def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")

def _fernet() -> Fernet:
    key = os.environ.get("STM_PROFILE_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("STM_PROFILE_ENCRYPTION_KEY not set")
    return Fernet(key.encode("ascii") if isinstance(key, str) else key)

def encrypt(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode("utf-8"))

def decrypt(blob: bytes) -> dict:
    return json.loads(_fernet().decrypt(blob).decode("utf-8"))
