"""Fernet-based credential encryption for source profiles.

When STM_PROFILE_ENCRYPTION_KEY is set → Fernet-encrypted blob.
When unset → reversible base64 (NOT secure, but keeps demos working in dev).
"""
from __future__ import annotations
import base64
import json
import logging
import os
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)
_WARNED = False


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _fernet() -> "Fernet | None":
    key = os.environ.get("STM_PROFILE_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    return Fernet(key.encode("ascii") if isinstance(key, str) else key)


def encrypt(data: dict) -> bytes:
    global _WARNED
    payload = json.dumps(data).encode("utf-8")
    f = _fernet()
    if f is None:
        if not _WARNED:
            logger.warning("STM_PROFILE_ENCRYPTION_KEY not set — storing profile credentials base64-only (dev).")
            _WARNED = True
        return b"PLAIN:" + base64.b64encode(payload)
    return f.encrypt(payload)


def decrypt(blob: bytes) -> dict:
    if blob.startswith(b"PLAIN:"):
        return json.loads(base64.b64decode(blob[6:]).decode("utf-8"))
    f = _fernet()
    if f is None:
        # Encrypted blob exists but no key — fail closed
        raise RuntimeError("STM_PROFILE_ENCRYPTION_KEY required to decrypt this profile")
    return json.loads(f.decrypt(blob).decode("utf-8"))
