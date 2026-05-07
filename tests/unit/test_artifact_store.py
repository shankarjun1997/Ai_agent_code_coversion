import pytest, uuid
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_save_artifact():
    from core.artifacts.postgres import PostgresArtifactStore
    from core.artifacts.base import Artifact
    mock_session = AsyncMock()
    store = PostgresArtifactStore(session=mock_session)
    await store.save(Artifact(run_id=str(uuid.uuid4()), agent_id="agent_3a", artifact_type="SQL", filename="f.sql", content="SELECT 1"))
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()

@pytest.mark.asyncio
async def test_list_by_run():
    from core.artifacts.postgres import PostgresArtifactStore
    run_id = str(uuid.uuid4())
    mock_row = MagicMock(run_id=run_id, agent_id="a", artifact_type="SQL", filename="f.sql", content="x")
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_row]
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    store = PostgresArtifactStore(session=mock_session)
    results = await store.list_by_run(run_id)
    assert len(results) == 1 and results[0].filename == "f.sql"
