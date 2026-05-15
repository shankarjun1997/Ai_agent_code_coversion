import uuid
import pytest
from core.batch.persistence import create_batch, get_batch, list_batches, update_batch_status


@pytest.mark.asyncio
async def test_create_and_get_batch():
    bid = await create_batch(
        tenant_id="default",
        catalog_source_id=str(uuid.uuid4()),
        catalog_target_id=str(uuid.uuid4()),
        business_context="test batch",
        session_count=3,
    )
    assert bid

    batch = await get_batch(bid)
    assert batch["id"] == bid
    assert batch["status"] == "pending"
    assert batch["session_count"] == 3
    assert batch["done_count"] == 0


@pytest.mark.asyncio
async def test_update_batch_status():
    bid = await create_batch(
        tenant_id="default",
        catalog_source_id=str(uuid.uuid4()),
        catalog_target_id=str(uuid.uuid4()),
        business_context=None,
        session_count=1,
    )
    await update_batch_status(bid, status="running", done_count=0)
    batch = await get_batch(bid)
    assert batch["status"] == "running"
