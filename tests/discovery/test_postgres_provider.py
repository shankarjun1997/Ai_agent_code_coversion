import os
import pytest
from core.discovery.base import SourceProvider
from core.discovery.postgres_provider import PostgresProviderAsync

def test_postgres_provider_implements_interface():
    p = PostgresProviderAsync()
    assert isinstance(p, SourceProvider)
    assert p.dialect == "postgres"
