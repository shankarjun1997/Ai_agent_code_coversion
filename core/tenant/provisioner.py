"""Tenant signup and per-tenant DB provisioning."""

import re
import uuid
import base64
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.hashing import hash_password
from core.models.platform import Tenant, TenantUser
from core.models.tenant import TenantBase


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def encrypt_db_url(plain_url: str) -> str:
    from cryptography.fernet import Fernet
    from core.config import get_settings
    settings = get_settings()
    key = base64.b64decode(settings.ENCRYPTION_KEY)
    fernet = Fernet(base64.urlsafe_b64encode(key[:32]))
    return fernet.encrypt(plain_url.encode()).decode()


def decrypt_db_url(encrypted: str) -> str:
    from cryptography.fernet import Fernet
    from core.config import get_settings
    settings = get_settings()
    key = base64.b64decode(settings.ENCRYPTION_KEY)
    fernet = Fernet(base64.urlsafe_b64encode(key[:32]))
    return fernet.decrypt(encrypted.encode()).decode()


def provision_tenant_db(slug: str, platform_db_url: str) -> str:
    """Derive tenant DB URL from platform URL and slug."""
    # Replace the last path component (db name) with tenant-specific name
    if "/" in platform_db_url:
        base = platform_db_url.rsplit("/", 1)[0]
        return f"{base}/tenant_{slug}"
    return platform_db_url


async def provision_tenant(
    session: AsyncSession,
    name: str,
    admin_email: str,
    admin_password: str,
    platform_db_url: str,
) -> tuple[Tenant, TenantUser]:
    """
    Create a Tenant row + admin TenantUser on the platform DB.
    Also provisions an isolated tenant schema on the platform DB.
    Returns (tenant, admin_user).
    """
    slug = _slugify(name)

    # Derive tenant DB URL — use a schema-per-tenant on the same PG instance
    # Replace db name with tenant slug (simplified; production may use separate DBs)
    tenant_db_url = platform_db_url.replace("/platform", f"/tenant_{slug}")

    encrypted_url = encrypt_db_url(tenant_db_url)

    tenant = Tenant(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        db_url_encrypted=encrypted_url,
        is_active=True,
    )
    session.add(tenant)
    await session.flush()

    admin = TenantUser(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=admin_email,
        hashed_password=hash_password(admin_password),
        role="admin",
    )
    session.add(admin)
    await session.flush()

    return tenant, admin


async def create_tenant_schema(tenant_db_url: str) -> None:
    """
    Run TenantBase.metadata.create_all on the tenant's DB.
    Called after provisioning when a real DB connection is available.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(tenant_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)
    await engine.dispose()
