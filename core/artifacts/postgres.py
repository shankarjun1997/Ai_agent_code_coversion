import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.artifacts.base import ArtifactStore, Artifact
from core.models.tenant import GeneratedArtifact

class PostgresArtifactStore(ArtifactStore):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, artifact: Artifact) -> None:
        row = GeneratedArtifact(id=uuid.uuid4(), run_id=artifact.run_id, agent_id=artifact.agent_id,
                                artifact_type=artifact.artifact_type, filename=artifact.filename, content=artifact.content)
        self._session.add(row)
        await self._session.commit()

    async def list_by_run(self, run_id: str) -> list[Artifact]:
        result = await self._session.execute(select(GeneratedArtifact).where(GeneratedArtifact.run_id == run_id))
        return [Artifact(run_id=str(r.run_id), agent_id=r.agent_id, artifact_type=r.artifact_type,
                         filename=r.filename, content=r.content) for r in result.scalars().all()]
