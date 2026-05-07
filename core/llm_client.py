"""Anthropic Claude client wrapper — single-turn and multi-turn tool-use."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

import anthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL  = "claude-sonnet-4-6"
MAX_TOKENS     = 8192
MAX_TOOL_TURNS = 15   # safety cap on agentic loops


class LLMClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model  = model

    # ── Single-turn completion ────────────────────────────────────────────────

    def complete(
        self,
        prompt:      str,
        system:      str = "",
        max_tokens:  int = MAX_TOKENS,
        temperature: float = 0.1,
    ) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    def complete_json(
        self,
        prompt:     str,
        system:     str = "",
        max_tokens: int = MAX_TOKENS,
    ) -> Dict:
        """Complete and parse JSON output from the model."""
        raw = self.complete(prompt, system=system, max_tokens=max_tokens)
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model did not return valid JSON:\n{raw}") from exc

    # ── Multi-turn agentic tool-use loop ──────────────────────────────────────

    def run_agent(
        self,
        system:       str,
        user_message: str,
        tools:        List[Dict],
        tool_handler: Callable[[str, Dict], str],
        max_tokens:   int = MAX_TOKENS,
    ) -> tuple[str, List[Dict]]:
        """
        Run an agentic loop until the model stops or calls a finalise tool.

        Returns (final_text, tool_call_history).
        """
        messages: List[Dict] = [{"role": "user", "content": user_message}]
        tool_history: List[Dict] = []
        turn = 0

        while turn < MAX_TOOL_TURNS:
            turn += 1
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
            )

            # Collect assistant content
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                text_blocks = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(text_blocks), tool_history

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    logger.debug("Tool call: %s(%s)", block.name, block.input)
                    result = tool_handler(block.name, block.input)
                    tool_history.append({
                        "tool": block.name,
                        "input": block.input,
                        "result": result,
                    })
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            # stop_reason not handled
            break

        text_blocks = []
        if messages and messages[-1]["role"] == "assistant":
            for block in messages[-1].get("content", []):
                if hasattr(block, "text"):
                    text_blocks.append(block.text)
        return "\n".join(text_blocks), tool_history
