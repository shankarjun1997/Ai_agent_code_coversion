import os
import pytest
from core.discovery.base import SourceProvider
from core.discovery.bigquery_provider import BigQueryProvider

def test_bq_provider_implements_interface():
    p = BigQueryProvider()
    assert isinstance(p, SourceProvider)
    assert p.dialect == "bigquery"
