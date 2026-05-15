"""Root conftest — shared fixtures for all tests."""
import pytest
import pytest_asyncio
from core.db.platform import close_engine


@pytest_asyncio.fixture(autouse=True)
async def reset_platform_engine():
    """Dispose the async engine after each test to prevent event-loop conflicts."""
    yield
    await close_engine()
