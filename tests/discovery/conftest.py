import os
import pytest
from core.discovery.profiles import ConnectionProfile


@pytest.fixture
def demo_pg_profile():
    dsn = os.environ.get("DEMO_DB_DSN", "postgresql://demo:demo@localhost:5432/crm_demo")
    host = dsn.split("@", 1)[-1] if "@" in dsn else dsn
    return ConnectionProfile(id="test-pg", label="test", dialect="postgres", dsn=dsn, host=host)


@pytest.fixture
def bq_profile():
    return ConnectionProfile(
        id="test-bq", label="test", dialect="bigquery",
        dsn=os.environ.get("BQ_PROJECT_ID", ""), host="bigquery",
    )
