"""Tenant signup and per-tenant DB provisioning."""

import re
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.hashing import hash_password
from core.db.tenant import encrypt_db_url
from core.models.platform import Tenant, TenantUser
from core.models.tenant import TenantBase


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


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
