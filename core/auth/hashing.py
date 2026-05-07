"""bcrypt password hashing utilities."""

import bcrypt


def hash_password(plain: str) -> str:
    """Hash a plain-text password."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches hashed."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())
