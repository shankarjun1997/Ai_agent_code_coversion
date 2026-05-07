"""Abstract base class for artifact storage."""

import uuid
from abc import ABC, abstractmethod
from typing import Any


class ArtifactStore(ABC):
    """Interface for storing and retrieving generated artifacts."""

    @abstractmethod
    async def save(
        self,
        run_id: uuid.UUID,
        artifact_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        """Persist an artifact. Returns artifact ID."""
        ...

    @abstractmethod
    async def get(self, artifact_id: uuid.UUID) -> dict[str, Any] | None:
        """Retrieve an artifact by ID. Returns None if not found."""
        ...

    @abstractmethod
    async def list_for_run(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        """List all artifacts for a pipeline run."""
        ...

    @abstractmethod
    async def delete(self, artifact_id: uuid.UUID) -> bool:
        """Delete an artifact. Returns True if deleted."""
        ...
