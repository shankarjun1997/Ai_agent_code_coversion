"""L6 Builder Agent — produces the final MappingResult + xlsx/csv output.

Reads CandidateMappings + Transformations + ValidationReport from the
blackboard, constructs a MappingResult compatible with exporter.py, and
stores both the result dict and xlsx bytes in stm_result.

Task 4.3 stub is replaced by this full implementation (Task 7.3).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import StageStatus
from core.stm.mapping_engine import MappingResult, MappingRow, detect_pii

logger = logging.getLogger(__name__)


def _build_mapping_rows(bb) -> List[MappingRow]:
    """Convert CandidateMappings + Transformations into MappingRow objects."""
    rows: List[MappingRow] = []

    # Build a set of derived/audit field names from transformations
    derived_fields = {t.target_field for t in bb.transformations.rows}

    for m in bb.candidate_mappings.rows:
        # Determine source info from node id: profile.schema.table.column
        parts = (m.source_node_ids[0].split(".") if m.source_node_ids else [])
        source_system = parts[0] if len(parts) > 0 else bb.selected_source_profiles[0] if bb.selected_source_profiles else "unknown"
        source_schema  = parts[1] if len(parts) > 1 else "public"
        source_table   = parts[2] if len(parts) > 2 else bb.target_table
        source_column  = parts[3] if len(parts) > 3 else (m.source_expression or m.target_field)
        source_type    = "unknown"

        # PII detection
        is_pii, pii_level = detect_pii(m.target_field)
        sensitivity = pii_level if is_pii else "none"

        # Transformation logic
        if m.target_field in derived_fields:
            tx = next((t for t in bb.transformations.rows if t.target_field == m.target_field), None)
            transformation = tx.logic if tx else m.source_expression or m.target_field
        else:
            transformation = m.source_expression or m.target_field

        rows.append(MappingRow(
            source_system=source_system,
            source_schema=source_schema,
            source_table=source_table,
            source_column=source_column,
            source_type=source_type,
            source_nullable=True,
            source_description=m.rationale or None,
            target_dataset=bb.target_dataset,
            target_table=bb.target_table,
            target_column=m.target_field,
            target_type=m.target_type,
            transformation=transformation,
            is_pii=is_pii,
            sensitivity=sensitivity,
            notes=f"band:{bb.validation.overall_band}" if bb.validation.scores else "",
        ))

    # Add audit/derived rows from transformations that aren't already in mappings
    mapping_fields = {m.target_field for m in bb.candidate_mappings.rows}
    for tx in bb.transformations.rows:
        if tx.target_field not in mapping_fields:
            is_pii, pii_level = detect_pii(tx.target_field)
            rows.append(MappingRow(
                source_system="derived",
                source_schema="",
                source_table="",
                source_column="",
                source_type="",
                source_nullable=False,
                source_description=tx.rationale or None,
                target_dataset=bb.target_dataset,
                target_table=bb.target_table,
                target_column=tx.target_field,
                target_type="TIMESTAMP" if tx.kind == "audit" else "STRING",
                transformation=tx.logic,
                is_pii=is_pii,
                sensitivity=pii_level if is_pii else "none",
                notes=f"kind:{tx.kind}",
            ))

    return rows


class BuilderAgent(StmAgent):
    """L6 — assembles final MappingResult, calls exporter to produce xlsx."""

    stage = "L6"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard

        rows = _build_mapping_rows(bb)

        source_tables = list({r.source_table for r in rows if r.source_table})
        pii_count = sum(1 for r in rows if r.is_pii)

        result = MappingResult(
            stm_id=str(uuid.uuid4()),
            profile_id=bb.selected_source_profiles[0] if bb.selected_source_profiles else "unknown",
            source_system=bb.selected_source_profiles[0] if bb.selected_source_profiles else "unknown",
            source_schema="public",
            source_tables=source_tables,
            target_dataset=bb.target_dataset,
            target_table=bb.target_table,
            partition_field=bb.transformations.partition_field,
            rows=rows,
            business_rules=[],
            pii_count=pii_count,
            field_count=len(rows),
            idempotency_strategy="delete_insert",
            idempotency_key=bb.transformations.idempotency_key,
            generated_at=datetime.utcnow().isoformat(),
        )

        # Produce xlsx bytes
        xlsx_bytes: Optional[bytes] = None
        try:
            from core.stm.exporter import to_xlsx
            xlsx_bytes = to_xlsx(result)
        except Exception as exc:
            logger.warning("BuilderAgent: xlsx export failed: %s", exc)

        # xlsx_bytes is excluded from the blackboard JSON (not serialisable).
        # Callers that need xlsx should regenerate via exporter.to_xlsx(MappingResult).
        stm_result: Dict[str, Any] = {
            **result.summary(),
            "status": "done",
            "overall_band": bb.validation.overall_band,
            "xlsx_available": xlsx_bytes is not None,
        }

        # Enhancement run: emit a changelog.md alongside xlsx
        if getattr(bb.intent, "intent_kind", "new") == "enhance_existing":
            try:
                changelog = _build_changelog(bb)
                stm_result["changelog_md"] = changelog
            except Exception as exc:
                logger.warning("changelog build failed: %s", exc)

        logger.info(
            "BuilderAgent: session=%s fields=%d pii=%d band=%s",
            bb.session_id, len(rows), pii_count, bb.validation.overall_band,
        )

        return BlackboardDelta(
            updates={
                "stm_result": stm_result,
                "current_stage": "done",
            },
        )


def _build_changelog(bb) -> str:
    """Diff baseline mappings vs current mappings; emit markdown changelog."""
    baseline_id = (bb.intent.baseline_stm_id if bb.intent else None) or getattr(bb, "baseline_stm_id", None)
    baseline_rows = []
    if baseline_id:
        try:
            from core.stm.persistence import _load_blackboard_sync
            prior = _load_blackboard_sync(baseline_id)
            baseline_rows = list(prior.candidate_mappings.rows) if prior and prior.candidate_mappings else []
        except Exception:
            baseline_rows = []
    base_by_field = {r.target_field: r for r in baseline_rows}
    cur_by_field = {r.target_field: r for r in bb.candidate_mappings.rows}

    added, removed, changed = [], [], []
    for f, r in cur_by_field.items():
        if f not in base_by_field:
            added.append(r)
        else:
            b = base_by_field[f]
            if b.source_expression != r.source_expression or b.target_type != r.target_type:
                changed.append((b, r))
    for f, b in base_by_field.items():
        if f not in cur_by_field:
            removed.append(b)

    tx_changed = []
    if baseline_id:
        try:
            from core.stm.persistence import _load_blackboard_sync
            prior = _load_blackboard_sync(baseline_id)
            base_tx = {t.target_field: t for t in (prior.transformations.rows if prior.transformations else [])}
            for t in bb.transformations.rows:
                if t.target_field in base_tx and base_tx[t.target_field].logic != t.logic:
                    tx_changed.append((base_tx[t.target_field], t))
        except Exception:
            pass

    lines = [f"# STM enhancement changelog — {bb.target_dataset}.{bb.target_table}",
             f"_Baseline session: `{baseline_id}` → new session: `{bb.session_id}`_",
             ""]
    if added:
        lines.append("## Added columns")
        for r in added:
            lines.append(f"- **{r.target_field}** ({r.target_type}) — `{r.source_expression or '(derived)'}` — {r.rationale}")
        lines.append("")
    if changed:
        lines.append("## Changed columns")
        for b, r in changed:
            lines.append(f"- **{r.target_field}**: type `{b.target_type}` → `{r.target_type}`, expr `{b.source_expression}` → `{r.source_expression}`")
        lines.append("")
    if removed:
        lines.append("## Removed columns")
        for r in removed:
            lines.append(f"- ~~{r.target_field}~~ ({r.target_type}) — was: `{r.source_expression}`")
        lines.append("")
    if tx_changed:
        lines.append("## Changed transformations")
        for b, t in tx_changed:
            lines.append(f"- **{t.target_field}** [{t.kind}]:\n  - before: `{b.logic}`\n  - after:  `{t.logic}`")
        lines.append("")
    if not (added or changed or removed or tx_changed):
        lines.append("_No structural deltas detected — this enhancement re-ran with identical mappings._")
    return "\n".join(lines)
