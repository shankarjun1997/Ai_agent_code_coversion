from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Artifact:
    run_id: str
    agent_id: str
    artifact_type: str
    filename: str
    content: str

class ArtifactStore(ABC):
    @abstractmethod
    async def save(self, artifact: Artifact) -> None: ...
    @abstractmethod
    async def list_by_run(self, run_id: str) -> list[Artifact]: ...
