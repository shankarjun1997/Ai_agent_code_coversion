"""FakeLLMClient — deterministic LLM stub for unit tests.

Usage::

    llm = FakeLLMClient(responses=["first response", "second response"])
    result = llm.complete("prompt")   # → "first response"
    result = llm.complete("prompt")   # → "second response"
    result = llm.complete("prompt")   # → "second response" (last repeats)

Or set a callable::

    llm = FakeLLMClient(fn=lambda prompt, **kw: '{"entity": "customer"}')
"""
from __future__ import annotations

from typing import Callable, List, Optional

from core.stm.agents.base import LLMClientProtocol


class FakeLLMClient(LLMClientProtocol):
    """Test double for any LLMClientProtocol consumer."""

    def __init__(
        self,
        responses: Optional[List[str]] = None,
        fn: Optional[Callable[..., str]] = None,
        default: str = "",
    ) -> None:
        self._responses = list(responses or [])
        self._fn = fn
        self._default = default
        self.calls: List[dict] = []

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 8192,
        temperature: float = 0.1,
    ) -> str:
        self.calls.append(
            {"prompt": prompt, "system": system, "max_tokens": max_tokens, "temperature": temperature}
        )
        if self._fn is not None:
            return self._fn(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
        if self._responses:
            return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        return self._default

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def reset(self) -> None:
        self.calls.clear()
