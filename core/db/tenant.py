"""Per-tenant async engine + session factory, keyed by tenant slug."""

from typing import AsyncGenerator

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings
from core.errors import TenantNotFoundError

import base64

_engines: dict[str, AsyncEngine] = {}
_factories: dict[str, async_sessionmaker[AsyncSession]] = {}


def _decrypt_db_url(encrypted: str) -> str:
    settings = get_settings()
    key = base64.b64decode(settings.ENCRYPTION_KEY)
    # Fernet requires 32-byte URL-safe base64 key
    fernet = Fernet(base64.urlsafe_b64encode(key[:32]))
    return fernet.decrypt(encrypted.encode()).decode()


def encrypt_db_url(plain_url: str) -> str:
    settings = get_settings()
    key = base64.b64decode(settings.ENCRYPTION_KEY)
    fernet = Fernet(base64.urlsafe_b64encode(key[:32]))
    return fernet.encrypt(plain_url.encode()).decode()


def get_tenant_engine(tenant_slug: str, db_url_encrypted: str) -> AsyncEngine:
    if tenant_slug not in _engines:
        db_url = _decrypt_db_url(db_url_encrypted)
        _engines[tenant_slug] = create_async_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engines[tenant_slug]


def get_tenant_session_factory(
    tenant_slug: str, db_url_encrypted: str
) -> async_sessionmaker[AsyncSession]:
    if tenant_slug not in _factories:
        engine = get_tenant_engine(tenant_slug, db_url_encrypted)
        _factories[tenant_slug] = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _factories[tenant_slug]


async def get_tenant_session(
    tenant_slug: str, db_url_encrypted: str
) -> AsyncGenerator[AsyncSession, None]:
    factory = get_tenant_session_factory(tenant_slug, db_url_encrypted)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_tenant_engine(tenant_slug: str) -> None:
    if tenant_slug in _engines:
        await _engines[tenant_slug].dispose()
        del _engines[tenant_slug]
        _factories.pop(tenant_slug, None)
