"""Integration test fixtures — spins up real Postgres containers per tenant."""

import os
import pytest
import pytest_asyncio

# Skip all integration tests if Docker is unavailable
try:
    import docker as _docker
    _docker.from_env().ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False

skip_no_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE, reason="Docker not available"
)

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:
    PostgresContainer = None  # type: ignore


@pytest.fixture(scope="session")
def platform_pg():
    """Spin up a Postgres container for the platform DB."""
    if not DOCKER_AVAILABLE or PostgresContainer is None:
        pytest.skip("Docker/testcontainers not available")
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def tenant_pg():
    """Spin up a second Postgres container for tenant DB."""
    if not DOCKER_AVAILABLE or PostgresContainer is None:
        pytest.skip("Docker/testcontainers not available")
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session")
async def platform_engine(platform_pg):
    from sqlalchemy.ext.asyncio import create_async_engine
    from core.models.platform import PlatformBase

    url = platform_pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(PlatformBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def tenant_engine(tenant_pg):
    from sqlalchemy.ext.asyncio import create_async_engine
    from core.models.tenant import TenantBase

    url = tenant_pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)
    yield engine
    await engine.dispose()
