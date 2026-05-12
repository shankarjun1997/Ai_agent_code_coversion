import pytest
from core.discovery.base import (
    SourceProvider, PingResult, TableInfo, ColumnInfo,
    FKInfo, ColumnProfile, ColumnHit,
)


def test_source_provider_is_abstract():
    with pytest.raises(TypeError):
        SourceProvider()


def test_ping_result_shape():
    r = PingResult(ok=True, latency_ms=12, message=None)
    assert r.ok is True
    assert r.latency_ms == 12


def test_table_info_shape():
    t = TableInfo(schema="public", name="customers", row_estimate=1000, comment=None)
    assert t.schema == "public"


def test_column_info_shape():
    c = ColumnInfo(
        schema="public", table="customers", name="customer_id",
        data_type="bigint", nullable=False, is_primary_key=True,
        default=None, comment=None,
    )
    assert c.is_primary_key is True
