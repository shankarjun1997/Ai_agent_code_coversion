class GateRejectedError(Exception):
    def __init__(self, notes: str = ""):
        self.notes = notes
        super().__init__(f"Gate rejected: {notes}")


class AgentTimeoutError(Exception):
    def __init__(self, agent_id: str, timeout: int):
        super().__init__(f"Agent {agent_id} timed out after {timeout}s")


class TenantNotFoundError(Exception):
    def __init__(self, tenant_id: str):
        super().__init__(f"Tenant {tenant_id} not found")
