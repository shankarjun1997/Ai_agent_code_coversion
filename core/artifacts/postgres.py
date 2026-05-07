"""PostgreSQL-backed ArtifactStore using SQLAlchemy async sessions."""

import uuid
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.artifacts.base import ArtifactStore
from core.models.tenant import GeneratedArtifact


class PostgresArtifactStore(ArtifactStore):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(
        self,
        run_id: uuid.UUID,
        artifact_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        artifact = GeneratedArtifact(
            id=uuid.uuid4(),
            run_id=run_id,
            artifact_type=artifact_type,
            content=content,
            metadata_=metadata,
        )
        self._session.add(artifact)
        await self._session.flush()
        return artifact.id

    async def get(self, artifact_id: uuid.UUID) -> dict[str, Any] | None:
        result = await self._session.get(GeneratedArtifact, artifact_id)
        if result is None:
            return None
        return self._to_dict(result)

    async def list_for_run(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        stmt = select(GeneratedArtifact).where(GeneratedArtifact.run_id == run_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_dict(r) for r in rows]

    async def delete(self, artifact_id: uuid.UUID) -> bool:
        stmt = delete(GeneratedArtifact).where(GeneratedArtifact.id == artifact_id)
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    @staticmethod
    def _to_dict(a: GeneratedArtifact) -> dict[str, Any]:
        return {
            "id": str(a.id),
            "run_id": str(a.run_id),
            "artifact_type": a.artifact_type,
            "content": a.content,
            "metadata": a.metadata_,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
