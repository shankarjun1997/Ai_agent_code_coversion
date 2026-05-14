"""L1 Intent Extraction Agent.

Parses raw_input (or Jira issue text) into a structured IntentArtifact.
Uses a Haiku-class LLM call to extract entity, action, SCD hint, filters,
and grain from the raw business requirement.

Rules-as-floor: a deterministic keyword pass runs first; the LLM refines
only those fields that remain ambiguous.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import IntentArtifact, StageStatus

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert data engineer. Extract structured intent from a business requirement.

Return ONLY valid JSON with these fields (no markdown, no explanation):
{
  "entity": "<primary business entity, e.g. customer, order, product>",
  "action": "<load|transform|migrate|sync|backfill>",
  "is_dimension": <true|false>,
  "is_fact": <true|false>,
  "scd_hint": "<type1|type2|type3|none|null>",
  "filters": ["<filter expression>", ...],
  "grain_hint": "<grain description or null>",
  "extracted_keywords": ["<keyword>", ...]
}

Rules:
- entity: single lowercase noun (no spaces).
- scd_hint: "type2" if requirement mentions "history", "changes over time", "slowly changing".
- is_dimension: true for reference/lookup data (customers, products, regions).
- is_fact: true for transactional/event data (orders, payments, events).
- filters: only include if explicitly mentioned in the text.
- grain_hint: describe the level of detail (e.g. "one row per order per day").
"""


# ── Deterministic keyword extraction (floor) ──────────────────────────────────

_SCD2_KEYWORDS = re.compile(
    r"\b(history|historical|track changes|slowly changing|scd2|scd type 2|over time)\b",
    re.IGNORECASE,
)
_DIM_KEYWORDS = re.compile(
    r"\b(dimension|lookup|reference|master data|customer|product|region|category)\b",
    re.IGNORECASE,
)
_FACT_KEYWORDS = re.compile(
    r"\b(fact|transaction|event|order|payment|sale|log|activity)\b",
    re.IGNORECASE,
)
_ENHANCE_KEYWORDS = re.compile(
    r"\b(add|append|extend|enhance|new column|update existing|alter)\b",
    re.IGNORECASE,
)


def _keyword_floor(raw: str) -> Dict[str, Any]:
    """Cheap deterministic pre-pass to populate obvious fields."""
    return {
        "scd_hint": "type2" if _SCD2_KEYWORDS.search(raw) else None,
        "is_dimension": bool(_DIM_KEYWORDS.search(raw)),
        "is_fact": bool(_FACT_KEYWORDS.search(raw)),
        "enhance_hint": bool(_ENHANCE_KEYWORDS.search(raw)),
    }


def _parse_llm_json(text: str) -> Dict[str, Any]:
    """Extract JSON from LLM response, tolerating markdown fences."""
    text = text.strip()
    # Strip markdown code fences if present
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


class IntentAgent(StmAgent):
    """L1 — extracts structured IntentArtifact from raw text or Jira issue."""

    stage = "L1"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        intent = bb.intent
        raw = intent.raw_input

        # ── 1. Deterministic floor ────────────────────────────────────────────
        floor = _keyword_floor(raw)

        # ── 2. LLM refinement ────────────────────────────────────────────────
        model = ctx.get("llm_model_l1", "haiku")
        llm_result: Dict[str, Any] = {}
        llm_tokens_in = 0
        llm_tokens_out = 0

        try:
            response = ctx.llm.complete(
                prompt=f"Business requirement:\n{raw}",
                system=_SYSTEM_PROMPT,
                max_tokens=512,
                temperature=0.0,
            )
            llm_result = _parse_llm_json(response)
            # Rough token estimate (real client tracks usage)
            llm_tokens_in = len(_SYSTEM_PROMPT.split()) + len(raw.split())
            llm_tokens_out = len(response.split())
        except Exception as exc:
            logger.warning("IntentAgent LLM call failed, using floor only: %s", exc)
            llm_result = {}

        # ── 3. Merge: floor wins on SCD hint / dim/fact; LLM fills the rest ──
        entity = llm_result.get("entity", "")
        action = llm_result.get("action", "load")
        is_dim = llm_result.get("is_dimension", floor["is_dimension"])
        is_fact = llm_result.get("is_fact", floor["is_fact"])
        scd_hint = floor["scd_hint"] or llm_result.get("scd_hint")
        filters: List[str] = llm_result.get("filters", [])
        grain_hint: Optional[str] = llm_result.get("grain_hint")
        keywords: List[str] = llm_result.get("extracted_keywords", [])

        # Normalise scd_hint
        if scd_hint not in ("type1", "type2", "type3", "none", None):
            scd_hint = None

        # ── Enhancement detection: look up prior approved STM for this target ──
        intent_kind = "new"
        baseline_id: Optional[str] = None
        if floor["enhance_hint"]:
            try:
                from core.stm.persistence import _find_latest_stm_by_target_sync
                baseline_id = _find_latest_stm_by_target_sync(
                    bb.target_dataset, bb.target_table, exclude_session_id=bb.session_id,
                )
                if baseline_id:
                    intent_kind = "enhance_existing"
            except Exception as exc:
                logger.warning("baseline STM lookup failed: %s", exc)

        updated_intent = IntentArtifact(
            source=intent.source,
            raw_input=intent.raw_input,
            jira_issue_key=intent.jira_issue_key,
            entity=entity,
            action=action,
            is_dimension=is_dim,
            is_fact=is_fact,
            scd_hint=scd_hint,
            filters=filters,
            grain_hint=grain_hint,
            extracted_keywords=keywords,
            status=StageStatus.ready,
            intent_kind=intent_kind,
            baseline_stm_id=baseline_id,
        )

        return BlackboardDelta(
            updates={"intent": updated_intent, "current_stage": "L2"},
            llm_tokens_in=llm_tokens_in,
            llm_tokens_out=llm_tokens_out,
            llm_model=model,
        )
