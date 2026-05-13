import os, pytest
pytestmark = pytest.mark.skipif(not os.environ.get("MYSQL_TEST_DSN"), reason="MYSQL_TEST_DSN not set")
from core.discovery.base import SourceProvider
from core.discovery.mysql_provider import MySQLProvider

def test_mysql_provider_implements_interface():
    assert isinstance(MySQLProvider(), SourceProvider)
    assert MySQLProvider().dialect == "mysql"
