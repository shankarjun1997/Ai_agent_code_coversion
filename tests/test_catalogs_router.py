# tests/test_catalogs_router.py
"""Router integration: upload + list + refresh-mocked."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app import app

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"

@pytest.mark.asyncio
async def test_upload_source_then_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with open(FIXTURES / "target_information_schema.xlsx", "rb") as f:
            resp = await client.post(
                "/api/catalogs/source",
                files={"file": ("target_information_schema.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"catalog_name": "router_test_catalog", "description": "router test"},
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["table_count"] == 11
        assert body["column_count"] == 255
        cid = body["catalog_id"]

        resp = await client.get("/api/catalogs/source")
        assert resp.status_code == 200
        items = resp.json()["catalogs"]
        assert any(c["id"] == cid for c in items)

@pytest.mark.asyncio
async def test_refresh_target_mocked():
    transport = ASGITransport(app=app)
    fake_client = MagicMock()
    fake_client.list_columns_in_dataset.return_value = [
        {"table_name": "t1", "column_name": "c1", "data_type": "STRING", "is_nullable": "NO", "description": None},
        {"table_name": "t1", "column_name": "c2", "data_type": "INT64",  "is_nullable": "YES", "description": None},
        {"table_name": "t2", "column_name": "c1", "data_type": "STRING", "is_nullable": "NO", "description": None},
    ]
    with patch("core.catalog.bq_refresh.BQClient", return_value=fake_client):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/catalogs/target/refresh",
                json={"project": "test-proj", "dataset": "rtest_ds"},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["table_count"] == 2
            assert body["column_count"] == 3
