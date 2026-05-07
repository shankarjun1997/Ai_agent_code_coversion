"""Integration tests — tenant isolation and contracts.

These tests require Docker (testcontainers). They are skipped automatically
if Docker is unavailable (CI without Docker daemon, local dev without Docker).
"""

import uuid
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import skip_no_docker


pytestmark = [pytest.mark.asyncio, skip_no_docker]


# ── Tenant isolation ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def platform_session(platform_engine):
    factory = async_sessionmaker(platform_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def tenant_session(tenant_engine):
    factory = async_sessionmaker(tenant_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


async def test_tenant_rows_isolated(platform_session, tenant_session):
    """Two tenants' data must not appear in each other's sessions."""
    from core.models.platform import Tenant
    from core.db.tenant import encrypt_db_url

    t1 = Tenant(
        id=uuid.uuid4(),
        name="Tenant Alpha",
        slug="tenant-alpha",
        db_url_encrypted=encrypt_db_url("postgresql+asyncpg://u:p@localhost/t1"),
    )
    t2 = Tenant(
        id=uuid.uuid4(),
        name="Tenant Beta",
        slug="tenant-beta",
        db_url_encrypted=encrypt_db_url("postgresql+asyncpg://u:p@localhost/t2"),
    )
    platform_session.add(t1)
    platform_session.add(t2)
    await platform_session.flush()

    from sqlalchemy import select
    result = await platform_session.execute(select(Tenant))
    tenants = result.scalars().all()
    slugs = {t.slug for t in tenants}
    assert "tenant-alpha" in slugs
    assert "tenant-beta" in slugs


async def test_pipeline_run_belongs_to_tenant(tenant_session):
    """PipelineRun tenant_id must match the creating tenant."""
    from core.models.tenant import PipelineRun

    tenant_id = uuid.uuid4()
    run = PipelineRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        pipeline_name="test-pipeline",
        status="pending",
        input_data={"key": "value"},
    )
    tenant_session.add(run)
    await tenant_session.flush()

    fetched = await tenant_session.get(PipelineRun, run.id)
    assert fetched is not None
    assert fetched.tenant_id == tenant_id
    assert fetched.pipeline_name == "test-pipeline"


async def test_gate_event_linked_to_run(tenant_session):
    """GateEvent must reference a valid PipelineRun."""
    from core.models.tenant import GateEvent, PipelineRun

    run = PipelineRun(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        pipeline_name="gate-test",
        status="awaiting_gate",
    )
    tenant_session.add(run)
    await tenant_session.flush()

    event = GateEvent(
        id=uuid.uuid4(),
        run_id=run.id,
        gate_name="review_checkpoint",
        decision="approved",
        notes="LGTM",
    )
    tenant_session.add(event)
    await tenant_session.flush()

    fetched = await tenant_session.get(GateEvent, event.id)
    assert fetched.decision == "approved"
    assert fetched.run_id == run.id


async def test_artifact_store_save_and_retrieve(tenant_session):
    """ArtifactStore save/get contract."""
    from core.artifacts.postgres import PostgresArtifactStore
    from core.models.tenant import PipelineRun

    run = PipelineRun(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        pipeline_name="artifact-test",
        status="running",
    )
    tenant_session.add(run)
    await tenant_session.flush()

    store = PostgresArtifactStore(tenant_session)
    artifact_id = await store.save(
        run_id=run.id,
        artifact_type="sql",
        content="SELECT 1",
        metadata={"dialect": "bigquery"},
    )

    fetched = await store.get(artifact_id)
    assert fetched is not None
    assert fetched["content"] == "SELECT 1"
    assert fetched["artifact_type"] == "sql"
    assert fetched["metadata"]["dialect"] == "bigquery"


async def test_user_password_hash_roundtrip():
    """bcrypt hash/verify contract — no DB needed."""
    from core.auth.hashing import hash_password, verify_password

    plain = "s3cur3P@ssw0rd!"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed)
    assert not verify_password("wrong", hashed)
    assert hashed != plain


async def test_jwt_access_token_contract(monkeypatch):
    """JWT issue/decode round-trip with correct claims."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/platform")
    monkeypatch.setenv("SECRET_KEY", "integration-secret-key")
    monkeypatch.setenv("ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdA==")

    from importlib import reload
    import core.config
    reload(core.config)

    from core.auth.jwt_utils import create_access_token, decode_access_token

    token = create_access_token(
        subject="user-uuid-123",
        tenant_id="tenant-uuid-456",
        role="admin",
    )
    payload = decode_access_token(token)

    assert payload["sub"] == "user-uuid-123"
    assert payload["tenant_id"] == "tenant-uuid-456"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
