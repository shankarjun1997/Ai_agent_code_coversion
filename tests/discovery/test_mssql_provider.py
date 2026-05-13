import os, pytest
pytestmark = pytest.mark.skipif(not os.environ.get("MSSQL_TEST_DSN"), reason="MSSQL_TEST_DSN not set")
from core.discovery.base import SourceProvider
from core.discovery.mssql_provider import MSSQLProvider

def test_mssql_provider_implements_interface():
    assert isinstance(MSSQLProvider(), SourceProvider)
    assert MSSQLProvider().dialect == "mssql"
