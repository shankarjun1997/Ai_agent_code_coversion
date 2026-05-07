"""Agent 1 — Requirement & Prototyping Agent.

Translates unstructured stakeholder inputs (transcripts, emails, meeting notes)
into structured Jira user stories with acceptance criteria, a task breakdown,
clarifying questions, contradiction detection, and a data prototype spec.

Human-in-the-loop gate: reviewer must approve before stories are pushed to Jira.
Assigned to: Paramjit
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from core.llm_client import LLMClient
from core.schemas import (
    ClarifyingQuestion,
    JiraStory,
    PrototypeSpec,
    RequirementsDoc,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior data engineering requirements analyst.
Your role is to parse unstructured stakeholder inputs and produce structured,
actionable data engineering requirements.

Always ensure the task breakdown includes ALL of:
  - Data ingestion tasks
  - Data curation / transformation tasks
  - Audit and lineage tasks
  - Data quality (DQ) tasks
  - Observability / monitoring tasks

Detect contradictions and offer concrete suggestions to resolve them.
If requirements are ambiguous, generate targeted clarifying questions.
Always produce a data prototype showing what the output table will look like.

Return STRICT JSON matching the schema below — no markdown, no extra keys.
"""

OUTPUT_SCHEMA = """{
  "summary": "one-line Jira story summary",
  "description": "full user story in 'As a ... I want ... so that ...' format",
  "acceptance_criteria": "numbered list of measurable ACs",
  "labels": ["label1", "label2"],
  "priority": "High|Medium|Low",
  "task_breakdown": [
    "Ingestion: ...",
    "Curation: ...",
    "Audit: ...",
    "DQ: ...",
    "Observability: ..."
  ],
  "clarifying_questions": [
    {
      "question": "...",
      "context": "why this matters",
      "category": "data_source|transformation|business_rule|scope|governance|performance|other",
      "priority": "high|medium|low"
    }
  ],
  "contradictions": ["Contradiction: X vs Y. Suggestion: ..."],
  "prototype": {
    "target_table": "dataset.table_name",
    "columns": [
      {"name": "col_name", "type": "STRING", "description": "what this represents"}
    ],
    "sample_rows": [
      {"col_name": "example_value"}
    ],
    "notes": "optional notes on data freshness, grain, etc."
  }
}"""


class RequirementsAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, raw_input: str, context: Optional[str] = None) -> RequirementsDoc:
        """
        Parse raw stakeholder input → RequirementsDoc.

        Args:
            raw_input: Free-form text (transcript, email, meeting notes).
            context:   Optional additional context (prior conversation, SME inputs).
        """
        extra = f"\n\nAdditional context:\n{context}" if context else ""
        prompt = f"""Analyse the following stakeholder input and produce the requirements JSON.

=== STAKEHOLDER INPUT ===
{raw_input}{extra}

=== EXPECTED JSON SCHEMA ===
{OUTPUT_SCHEMA}

Return only the JSON object. No markdown fences, no commentary.
"""
        payload = self.llm.complete_json(prompt, system=SYSTEM_PROMPT)

        jira_story = JiraStory(
            issue_key="DRAFT",
            summary=payload.get("summary", ""),
            description=payload.get("description", ""),
            acceptance_criteria=payload.get("acceptance_criteria", ""),
            labels=payload.get("labels", []),
            priority=payload.get("priority"),
        )

        questions = [
            ClarifyingQuestion(**q)
            for q in payload.get("clarifying_questions", [])
        ]

        prototype_data = payload.get("prototype")
        prototype = PrototypeSpec(**prototype_data) if prototype_data else None

        doc = RequirementsDoc(
            raw_input_summary=raw_input[:500],
            jira_story_draft=jira_story,
            task_breakdown=payload.get("task_breakdown", []),
            clarifying_questions=questions,
            contradictions=payload.get("contradictions", []),
            prototype=prototype,
        )
        logger.info("Agent 1: requirements doc %s created — %d tasks, %d questions",
                    doc.doc_id, len(doc.task_breakdown), len(doc.clarifying_questions))
        return doc

    def iterate(
        self,
        existing_doc: RequirementsDoc,
        follow_up_input: str,
    ) -> RequirementsDoc:
        """Refine an existing requirements doc with follow-up stakeholder input."""
        prior = json.dumps({
            "summary":  existing_doc.jira_story_draft.summary,
            "description": existing_doc.jira_story_draft.description,
            "acceptance_criteria": existing_doc.jira_story_draft.acceptance_criteria,
            "task_breakdown": existing_doc.task_breakdown,
            "open_questions": [q.question for q in existing_doc.clarifying_questions],
            "contradictions": existing_doc.contradictions,
        }, indent=2)

        prompt = f"""You previously produced these requirements:

{prior}

New stakeholder follow-up input:
{follow_up_input}

Update and refine the requirements based on this new input.
Address any previously open questions if answered.
Flag any new contradictions.
Return the complete updated JSON (same schema as before).
"""
        return self.run(prompt)
