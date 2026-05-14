"""L2 — Shortlist agent.

For one source table + a target dataset's INFORMATION_SCHEMA, produces a
ranked shortlist of 3–10 target tables that should receive data from the
source. Each pick carries evidence (specific source.col → target.col matches)
that justifies it. Reviewer can uncheck/add at Gate 1.

Single LLM call — content-matching, not name-similarity.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import Shortlist, ShortlistEntry, StageStatus

logger = logging.getLogger(__name__)


SYSTEM = (
    "You match one source table against many candidate target tables in a data "
    "warehouse. You decide which targets should receive data from the source. "
    "Match by content (column semantics), not by name similarity. Surface "
    "evidence for every pick."
)


class ShortlistAgent(StmAgent):
    stage = "L2"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        if bb.source_table is None or bb.target_schema is None:
            return BlackboardDelta.failure("Schemas missing — L1 must complete first")

        source_ctx = {
            "table": bb.source_table.name,
            "cols": [
                {k: v for k, v in {"n": c.name, "t": c.type, "d": c.description}.items() if v}
                for c in bb.source_table.columns
            ],
        }
        target_ctx = [
            {
                "table": t.name,
                "cols": [
                    {k: v for k, v in {"n": c.name, "t": c.type, "d": c.description}.items() if v}
                    for c in t.columns
                ],
            }
            for t in bb.target_schema.tables
        ]
        n_targets = len(target_ctx)
        max_picks = min(10, max(3, (n_targets + 1) // 2))

        prompt = (
            "You are deciding which target tables in a data warehouse should "
            "receive data from one upstream source table.\n\n"
            "This is NOT a name-similarity exercise. Match by CONTENT: compare "
            "source column semantics (name + type + description) against target "
            "column semantics. A target qualifies only if MULTIPLE source columns "
            "have a clear semantic home in it.\n\n"
            f"SOURCE TABLE (mapping FROM):\n{json.dumps(source_ctx, separators=(',', ':'))}\n\n"
            f"TARGET INFORMATION SCHEMA (mapping TO):\n{json.dumps(target_ctx, separators=(',', ':'))}\n\n"
        )
        if bb.business_context:
            prompt += f"BUSINESS CONTEXT FROM USER:\n{bb.business_context}\n\n"
        prompt += (
            "Decision rubric for each candidate target table:\n"
            "1. Walk the source columns. For each, ask: 'Does this target have a column that semantically matches — same concept, compatible type, similar description?'\n"
            "2. Count how many source columns have a real match in this target (not just FK joins).\n"
            "3. A target qualifies only if it has >= 3 strongly-matching source columns OR the source naturally aggregates to this target's grain.\n"
            "4. Reject targets where the only match is an account_id / customer_id FK — those are joins, not destinations.\n\n"
            f"Return between 3 and {max_picks} target tables, ranked by strength of match.\n\n"
            "For each pick, surface EVIDENCE — at least 3 specific source.col -> target.col matches.\n\n"
            "Return ONLY valid JSON with this shape:\n"
            '{ "shortlist": ['
            '{ "table": "target_table_name", "reason": "one-line role", "match_count": 8, '
            '"evidence": ["source.col_a -> target.col_x (1:1)", "..."] }'
            "] }"
        )

        raw = ctx.llm.complete(prompt, system=SYSTEM, max_tokens=3000, temperature=0.0)
        try:
            parsed = _extract_json(raw)
        except Exception as exc:
            return BlackboardDelta.failure(f"Shortlist JSON parse failed: {exc}")

        rows: List[ShortlistEntry] = []
        for item in parsed.get("shortlist", []) or []:
            tbl = (item.get("table") or "").strip()
            if not tbl:
                continue
            rows.append(ShortlistEntry(
                table=tbl,
                reason=(item.get("reason") or "").strip(),
                match_count=int(item.get("match_count") or 0),
                evidence=[str(e) for e in (item.get("evidence") or [])],
                picked=True,
            ))
        if not rows:
            return BlackboardDelta.failure("LLM returned empty shortlist")

        return BlackboardDelta(updates={
            "shortlist": Shortlist(rows=rows, status=StageStatus.awaiting_review),
        })


def _extract_json(text: str) -> Dict[str, Any]:
    """Tolerate markdown fences + leading prose."""
    cleaned = text.strip()
    if "```" in cleaned:
        # strip first ```json ... ``` block
        start = cleaned.find("```")
        end = cleaned.find("```", start + 3)
        if end != -1:
            block = cleaned[start + 3:end]
            if block.startswith("json"):
                block = block[4:]
            cleaned = block.strip()
    # find first { ... matching }
    depth = 0
    in_str = False
    esc = False
    start_i = cleaned.find("{")
    if start_i < 0:
        raise ValueError("no JSON object found")
    for i in range(start_i, len(cleaned)):
        c = cleaned[i]
        if esc:
            esc = False; continue
        if c == "\\":
            esc = True; continue
        if c == '"':
            in_str = not in_str; continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start_i:i + 1])
    raise ValueError("unbalanced JSON")
