import asyncio

_registry: dict = {}

def get_agent(agent_id: str):
    if agent_id not in _registry:
        raise KeyError(f"Agent '{agent_id}' not registered")
    return _registry[agent_id]

def list_agents() -> list:
    return list(_registry.keys())

def register(agent_id: str):
    def _decorator(fn):
        _registry[agent_id] = fn
        return fn
    return _decorator

def clear_registry() -> None:
    _registry.clear()


def build_registry() -> dict:
    from agents.agent_1_requirements import RequirementsAgent
    from agents.agent_2_mapping import MappingAgent
    from agents.agent_3_orchestrator import EngineeringOrchestrator
    from agents.agent_4_qa import QAAgent
    from core.llm_client import LLMClient
    llm = LLMClient()
    return {
        "agent_1": _SyncAgentAdapter(RequirementsAgent(llm=llm)),
        "agent_2": _SyncAgentAdapter(MappingAgent(llm=llm)),
        "agent_3": _SyncAgentAdapter(EngineeringOrchestrator(llm=llm)),
        "agent_4": _SyncAgentAdapter(QAAgent(llm=llm)),
    }

class _SyncAgentAdapter:
    def __init__(self, agent): self._agent = agent
    async def run(self, input):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._agent.run, input)

def build_engine():
    from core.config import get_settings
    from core.engine.asyncio_engine import AsyncioEngine
    return AsyncioEngine(registry=build_registry(), timeout_seconds=get_settings().AGENT_TIMEOUT_SECONDS)
