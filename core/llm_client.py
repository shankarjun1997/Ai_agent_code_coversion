"""OpenAI-compatible LLM client — works with OpenRouter, DeepSeek, OpenAI, vLLM, etc.

Pick a provider via env:
  LLM_BASE_URL = https://api.deepseek.com/v1        (or openrouter / openai / your own)
  LLM_API_KEY  = <provider key>                     (OPENROUTER_API_KEY also accepted for back-compat)
  LLM_MODEL    = deepseek-chat | deepseek-reasoner  (or any model the provider supports)
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List

from openai import OpenAI, RateLimitError, APIStatusError

logger = logging.getLogger(__name__)

DEFAULT_MODEL    = os.environ.get("LLM_MODEL", "deepseek-chat")
DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
MAX_TOKENS       = 8192
MAX_TOOL_TURNS   = 15
_RETRY_CODES     = {429, 524, 503, 502}
_MAX_RETRIES     = 5


class LLMClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model  = model
        logger.info("LLMClient initialised: model=%s base_url=%s", model, base_url)

    # ── Single-turn completion ────────────────────────────────────────────────

    def complete(
        self,
        prompt:      str,
        system:      str = "",
        max_tokens:  int = MAX_TOKENS,
        temperature: float = 0.1,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(_MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=messages,
                )
                choices = response.choices or []
                if not choices:
                    err = getattr(response, 'error', None)
                    code = err.get('code') if isinstance(err, dict) else None
                    msg  = err.get('message', str(response)) if isinstance(err, dict) else str(response)
                    if code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
                        wait = 30 * (attempt + 1)
                        logger.warning("Provider error %s, retrying in %ds… (attempt %d)", code, wait, attempt + 1)
                        time.sleep(wait)
                        continue
                    raise RuntimeError(f"LLM provider error: {msg}")
                content = choices[0].message.content or ""
                return content.strip()
            except (RateLimitError, APIStatusError) as exc:
                if attempt < _MAX_RETRIES - 1:
                    wait = 30 * (attempt + 1)
                    logger.warning("Rate-limit/API error, retrying in %ds: %s", wait, exc)
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("Max retries exceeded")

    def complete_json(
        self,
        prompt:     str,
        system:     str = "",
        max_tokens: int = MAX_TOKENS,
    ) -> Dict:
        raw = self.complete(prompt, system=system, max_tokens=max_tokens)
        # Strip markdown fences if present
        if "```" in raw:
            parts = raw.split("```")
            # find the json block
            for i, part in enumerate(parts):
                candidate = part.lstrip("json").strip()
                if candidate.startswith(("{", "[")):
                    raw = candidate
                    break
        raw = raw.strip()
        if not raw:
            raise ValueError("Model returned empty response for JSON request")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try extracting first {...} or [...] block
            import re
            m = re.search(r'(\{.*\}|\[.*\])', raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"Model did not return valid JSON:\n{raw[:500]}")

    # ── Multi-turn agentic tool-use loop ──────────────────────────────────────

    def run_agent(
        self,
        system:       str,
        user_message: str,
        tools:        List[Dict],
        tool_handler: Callable[[str, Dict], str],
        max_tokens:   int = MAX_TOKENS,
    ) -> tuple[str, List[Dict]]:
        """Run an agentic loop until the model stops. Returns (final_text, tool_call_history)."""
        messages: List[Dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_message})

        # Convert Anthropic-style tools to OpenAI format if needed
        oai_tools = _to_openai_tools(tools)
        tool_history: List[Dict] = []
        turn = 0

        while turn < MAX_TOOL_TURNS:
            turn += 1
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=messages,
                tools=oai_tools,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            messages.append(msg)

            if response.choices[0].finish_reason == "stop":
                return msg.content or "", tool_history

            if response.choices[0].finish_reason == "tool_calls":
                tool_results = []
                for tc in msg.tool_calls or []:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments)
                    logger.debug("Tool call: %s(%s)", name, args)
                    result = tool_handler(name, args)
                    tool_history.append({"tool": name, "input": args, "result": result})
                    tool_results.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      result,
                    })
                messages.extend(tool_results)
                continue

            break

        last = messages[-1]
        return (last.get("content") or last.content or ""), tool_history


def _to_openai_tools(tools: List[Dict]) -> List[Dict]:
    """Accept either OpenAI-format or Anthropic-format tool dicts."""
    result = []
    for t in tools:
        if "type" in t and t["type"] == "function":
            result.append(t)
        else:
            result.append({
                "type": "function",
                "function": {
                    "name":        t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters":  t.get("input_schema", t.get("parameters", {})),
                },
            })
    return result
