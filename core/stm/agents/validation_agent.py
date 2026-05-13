"""L5 Validation & Governance Agent.

Deterministic only — no LLM calls.

Produces ValidationReport with:
- ConfidenceScore per target field (using core/stm/scoring.py)
- ValidationFindings (block/warn/info) from rule-based checks
- overall_band computed from low_confidence_count and block_count
"""
from __future__ import annotations

import logging
from typing import List

from core.stm.agents.base import AgentContext, BlackboardDelta, StmAgent
from core.stm.blackboard import (
    ConfidenceScore, StageStatus, ValidationFinding, ValidationReport,
)
from core.stm.scoring import score_mapping

logger = logging.getLogger(__name__)

# Thresholds
_MIN_MAPPINGS = 1
_LOW_CONF_WARN_THRESHOLD = 0.5   # fraction of fields with low band → warn
_LOW_CONF_BLOCK_THRESHOLD = 0.8  # fraction → block


def _bq_type_for_mapping(mapping) -> str:
    """Extract BQ type from a CandidateMapping."""
    return (mapping.target_type or "STRING").upper()


def _findings_for_mapping(mapping, score: ConfidenceScore) -> List[ValidationFinding]:
    """Generate per-field validation findings."""
    findings = []

    if not mapping.source_expression:
        findings.append(ValidationFinding(
            severity="warn",
            target_field=mapping.target_field,
            rule="missing_source_expression",
            message=f"No source expression for target field '{mapping.target_field}'",
        ))

    if score.final < 0.3 and mapping.source_expression:
        findings.append(ValidationFinding(
            severity="warn",
            target_field=mapping.target_field,
            rule="low_confidence_mapping",
            message=(
                f"Low confidence mapping for '{mapping.target_field}' "
                f"(score={score.final:.2f})"
            ),
        ))

    return findings


def _global_findings(
    mappings,
    scores: List[ConfidenceScore],
    transformations,
) -> List[ValidationFinding]:
    """Global validation rules across the whole mapping set."""
    findings = []

    if not mappings.rows:
        findings.append(ValidationFinding(
            severity="block",
            target_field=None,
            rule="no_mappings",
            message="No candidate mappings were produced — cannot proceed to STM generation.",
        ))
        return findings

    low_count = sum(1 for s in scores if s.band == "low")
    total = len(scores)
    if total > 0:
        low_fraction = low_count / total
        if low_fraction >= _LOW_CONF_BLOCK_THRESHOLD:
            findings.append(ValidationFinding(
                severity="block",
                target_field=None,
                rule="too_many_low_confidence",
                message=(
                    f"{low_count}/{total} fields have low confidence "
                    f"({low_fraction:.0%}) — review required before proceeding."
                ),
            ))
        elif low_fraction >= _LOW_CONF_WARN_THRESHOLD:
            findings.append(ValidationFinding(
                severity="warn",
                target_field=None,
                rule="high_low_confidence_ratio",
                message=(
                    f"{low_count}/{total} fields have low confidence "
                    f"({low_fraction:.0%})."
                ),
            ))

    # Check SCD2 has at least an effective date field
    if transformations.scd_strategy == "type2":
        has_date = any(
            f in ("effective_from", "valid_from", "start_date", "eff_date")
            for m in mappings.rows
            for f in [m.target_field.lower()]
        )
        if not has_date:
            findings.append(ValidationFinding(
                severity="warn",
                target_field=None,
                rule="scd2_missing_effective_date",
                message=(
                    "SCD Type 2 detected but no effective_from/valid_from field found. "
                    "Consider adding an effective date column."
                ),
            ))

    # Warn if no partition field defined
    if transformations.partition_field is None and len(mappings.rows) > 5:
        findings.append(ValidationFinding(
            severity="info",
            target_field=None,
            rule="no_partition_field",
            message="No partition field detected. Consider adding date/timestamp partitioning.",
        ))

    return findings


def _overall_band(scores: List[ConfidenceScore], block_count: int) -> str:
    if block_count > 0:
        return "low"
    if not scores:
        return "high"
    avg = sum(s.final for s in scores) / len(scores)
    if avg >= 0.70:
        return "high"
    if avg >= 0.45:
        return "medium"
    return "low"


class ValidationAgent(StmAgent):
    """L5 — deterministic confidence scoring + rule-based findings."""

    stage = "L5"

    async def _execute(self, ctx: AgentContext) -> BlackboardDelta:
        bb = ctx.blackboard
        mappings = bb.candidate_mappings
        transformations = bb.transformations
        graph = bb.metadata_graph

        scores: List[ConfidenceScore] = []
        all_findings: List[ValidationFinding] = []

        # ── Per-field scoring + findings ──────────────────────────────────────
        for mapping in mappings.rows:
            score = score_mapping(
                mapping,
                graph,
                source_bq_type=_bq_type_for_mapping(mapping),
                target_bq_type=_bq_type_for_mapping(mapping),
            )
            scores.append(score)
            all_findings.extend(_findings_for_mapping(mapping, score))

        # ── Global findings ───────────────────────────────────────────────────
        all_findings.extend(_global_findings(mappings, scores, transformations))

        # ── Aggregate metrics ─────────────────────────────────────────────────
        low_confidence_count = sum(1 for s in scores if s.band == "low")
        block_count = sum(1 for f in all_findings if f.severity == "block")

        report = ValidationReport(
            scores=scores,
            findings=all_findings,
            low_confidence_count=low_confidence_count,
            block_count=block_count,
            overall_band=_overall_band(scores, block_count),
            status=StageStatus.ready,
        )

        return BlackboardDelta(
            updates={"validation": report, "current_stage": "L6"},
        )
