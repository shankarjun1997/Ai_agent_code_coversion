"""Test BQ refresh with a mocked BQClient."""
from unittest.mock import MagicMock, patch

import pytest

from core.catalog.bq_refresh import refresh_target_catalog


@pytest.mark.asyncio
async def test_refresh_target_catalog_persists_grouped_rows():
    fake_rows = [
        {"table_name": "orders",    "column_name": "order_id",   "data_type": "STRING",    "is_nullable": "NO",  "description": "PK"},
        {"table_name": "orders",    "column_name": "amount",     "data_type": "FLOAT64",   "is_nullable": "YES", "description": None},
        {"table_name": "customers", "column_name": "customer_id","data_type": "STRING",    "is_nullable": "NO",  "description": None},
        {"table_name": "customers", "column_name": "email",      "data_type": "STRING",    "is_nullable": "YES", "description": "user email"},
    ]

    fake_client = MagicMock()
    fake_client.list_columns_in_dataset.return_value = fake_rows

    with patch("core.catalog.bq_refresh.BQClient", return_value=fake_client):
        out = await refresh_target_catalog(
            tenant_id="default",
            project="test-proj",
            dataset="test_ds",
        )

    assert out["table_count"] == 2
    assert out["column_count"] == 4
    assert out["catalog_id"]
    fake_client.list_columns_in_dataset.assert_called_once_with("test_ds")
