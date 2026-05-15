"""Persistence round-trip tests for catalogs."""
import json
import uuid
from datetime import datetime

import pytest

from core.catalog.parser import ParsedColumn, ParsedSchema, ParsedTable
from core.catalog.persistence import (
    save_source_catalog, list_source_catalogs, load_source_catalog,
    save_target_catalog, list_target_catalogs, load_target_catalog,
)


@pytest.mark.asyncio
async def test_save_and_list_source_catalog():
    schema = ParsedSchema(
        tables=[
            ParsedTable(
                table_name="orders",
                columns=[
                    {"name": "order_id", "type": "string", "description": None, "ordinal": 0},
                    {"name": "amount", "type": "float", "description": None, "ordinal": 1},
                ],
            ),
            ParsedTable(
                table_name="customers",
                columns=[
                    {"name": "customer_id", "type": "string", "description": None, "ordinal": 0},
                ],
            ),
        ],
        strategy="schema_dump",
    )

    catalog_id = await save_source_catalog(
        tenant_id="default",
        catalog_name="frontier_test_" + uuid.uuid4().hex[:8],
        source_kind="databricks_upload",
        raw_filename="test.xlsx",
        description="round-trip test",
        schema=schema,
    )

    rows = await list_source_catalogs(tenant_id="default")
    assert any(r["id"] == catalog_id for r in rows)

    loaded = await load_source_catalog(catalog_id)
    assert loaded["table_count"] == 2
    assert loaded["column_count"] == 3
    names = {t["table_name"] for t in loaded["tables"]}
    assert names == {"orders", "customers"}
    orders = next(t for t in loaded["tables"] if t["table_name"] == "orders")
    assert orders["columns"][0]["name"] == "order_id"
    assert orders["columns"][0]["type"] == "string"


@pytest.mark.asyncio
async def test_save_and_list_target_catalog():
    tables = [
        {
            "table_name": "dim_customer",
            "description": "Customer dimension",
            "columns": [
                {"name": "customer_key", "type": "INTEGER", "description": None, "ordinal": 0},
                {"name": "customer_id", "type": "STRING", "description": None, "ordinal": 1},
            ],
        },
        {
            "table_name": "fact_orders",
            "description": "Orders fact table",
            "columns": [
                {"name": "order_key", "type": "INTEGER", "description": None, "ordinal": 0},
            ],
        },
    ]

    project = "my-gcp-project"
    dataset = "dw_test_" + uuid.uuid4().hex[:8]

    catalog_id = await save_target_catalog(
        tenant_id="default",
        project=project,
        dataset=dataset,
        tables=tables,
    )

    rows = await list_target_catalogs(tenant_id="default")
    assert any(r["id"] == catalog_id for r in rows)

    loaded = await load_target_catalog(catalog_id)
    assert loaded["table_count"] == 2
    assert loaded["column_count"] == 3
    assert loaded["project"] == project
    assert loaded["dataset"] == dataset
    tbl_names = {t["table_name"] for t in loaded["tables"]}
    assert tbl_names == {"dim_customer", "fact_orders"}
    dim = next(t for t in loaded["tables"] if t["table_name"] == "dim_customer")
    assert dim["columns"][0]["name"] == "customer_key"
    assert dim["columns"][0]["type"] == "INTEGER"
