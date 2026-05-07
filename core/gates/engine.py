"""GateEngine — human-in-the-loop approval gates using asyncio Events."""

import asyncio
from typing import Any

from core.errors import GateRejectedError


class GateEngine:
    def __init__(self, slack=None):
        self._gates: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, dict] = {}
        self._slack = slack

    def restore_gate(self, run_id: str) -> None:
        if run_id not in self._gates:
            self._gates[run_id] = asyncio.Event()

    async def wait_for_approval(self, run_id: str, stage: str, db: Any = None) -> None:
        if run_id not in self._gates:
            self._gates[run_id] = asyncio.Event()
        event = self._gates[run_id]
        await event.wait()
        decision = self._decisions.get(run_id, {})
        if decision.get("action") == "rejected":
            raise GateRejectedError(decision.get("notes", ""))

    async def approve(self, run_id: str, stage: str, reviewer: str = "", notes: str = "", db: Any = None) -> None:
        if run_id not in self._gates:
            self._gates[run_id] = asyncio.Event()
        self._decisions[run_id] = {"action": "approved", "reviewer": reviewer, "notes": notes, "stage": stage}
        self._gates[run_id].set()
        if self._slack:
            await self._slack.notify(run_id=run_id, stage=stage, action="approved")

    async def reject(self, run_id: str, stage: str, reviewer: str = "", notes: str = "", db: Any = None) -> None:
        if run_id not in self._gates:
            self._gates[run_id] = asyncio.Event()
        self._decisions[run_id] = {"action": "rejected", "reviewer": reviewer, "notes": notes, "stage": stage}
        self._gates[run_id].set()
        if self._slack:
            await self._slack.notify(run_id=run_id, stage=stage, action="rejected")
