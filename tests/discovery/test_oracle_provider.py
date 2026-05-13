import os, pytest
pytestmark = pytest.mark.skipif(not os.environ.get("ORACLE_TEST_DSN"), reason="ORACLE_TEST_DSN not set")
from core.discovery.base import SourceProvider
from core.discovery.oracle_provider import OracleProvider

def test_oracle_provider_implements_interface():
    assert isinstance(OracleProvider(), SourceProvider)
    assert OracleProvider().dialect == "oracle"
