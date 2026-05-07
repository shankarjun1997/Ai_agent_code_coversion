"""Main pipeline orchestrator with human-in-the-loop gates.

Flow:
  Agent 1 (Requirements) → REVIEW GATE → push to Jira
  Agent 2 (Mapping)      → REVIEW GATE → approve design
  Agent 3 (Engineering)  → REVIEW GATE → merge PR
  Agent 4 (QA)           → REVIEW GATE → release sign-off
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Optional

from agents.agent_1_requirements  import RequirementsAgent
from agents.agent_2_mapping       import MappingAgent
from agents.agent_3_orchestrator  import EngineeringOrchestrator
from agents.agent_4_qa            import QAAgent
from agents.shared.jira_client    import JiraClient
from agents.shared.github_client  import GitHubClient
from agents.shared.rovo_connector import RovoConnector
from core.bq_client               import BQClient
from core.llm_client              import LLMClient
from core.schemas                 import (
    ApprovalStatus,
    HumanApproval,
    JiraStory,
    PipelineRun,
    PipelineStage,
    RequirementsDoc,
)
from core import state_db

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self):
        self.llm    = LLMClient(api_key=_require("ANTHROPIC_API_KEY"))
        self.bq     = BQClient(project_id=_require("BQ_PROJECT_ID"))
        self.jira   = JiraClient(
            url=_require("JIRA_URL"),
            email=_require("JIRA_EMAIL"),
            api_token=_require("JIRA_API_TOKEN"),
        )
        self.rovo   = RovoConnector(
            jira_url=_require("JIRA_URL"),
            email=_require("JIRA_EMAIL"),
            api_token=_require("JIRA_API_TOKEN"),
            confluence_url=os.getenv("CONFLUENCE_URL"),
            confluence_space=os.getenv("CONFLUENCE_SPACE"),
        )
        github_token = os.getenv("GITHUB_TOKEN")
        self.github  = GitHubClient(
            token=github_token,
            owner=_require("GITHUB_OWNER"),
            repo=_require("GITHUB_REPO"),
        ) if github_token else None

        self.agent1 = RequirementsAgent(self.llm)
        self.agent2 = MappingAgent(self.llm, self.bq)
        self.agent4 = QAAgent(self.llm, self.bq)

    # ── Public API ────────────────────────────────────────────────────────────

    def trigger(
        self,
        raw_input:      str,
        jira_issue_key: Optional[str] = None,
        legacy_code:    Optional[str] = None,
        legacy_dialect: Optional[str] = None,
    ) -> PipelineRun:
        """
        Start a new pipeline run in a background thread.
        Returns the PipelineRun immediately so the caller can track run_id.
        """
        # If a Jira key is provided, fetch the story context
        if jira_issue_key and not raw_input:
            story   = self.jira.get_issue(jira_issue_key, os.getenv("JIRA_AC_FIELD"))
            raw_input = f"{story.summary}\n\n{story.description}\n\nAC:\n{story.acceptance_criteria}"

        run = PipelineRun(jira_issue=jira_issue_key or "DRAFT")
        state_db.upsert_run(run)

        thread = threading.Thread(
            target=self._run_pipeline,
            args=(run, raw_input, jira_issue_key, legacy_code, legacy_dialect),
            daemon=True,
        )
        thread.start()
        return run

    def approve(self, run_id: str, reviewer: str, notes: str = "") -> bool:
        """Approve the current review gate and advance the pipeline."""
        row = state_db.get_run(run_id)
        if not row or row["status"] != "waiting_review":
            return False

        run = self._load_run(row)
        approval = HumanApproval(
            stage=run.stage,
            status=ApprovalStatus.APPROVED,
            reviewer=reviewer,
            notes=notes,
        )
        run.approvals.append(approval)
        state_db.record_approval(run_id, approval)
        state_db.append_log(run_id, f"APPROVED by {reviewer}: {notes}")

        # Advance the stage
        next_stage = _next_stage(run.stage)
        if next_stage:
            run.stage  = next_stage
            run.status = "running"
            state_db.upsert_run(run)
            # Resume pipeline in background
            thread = threading.Thread(
                target=self._resume_pipeline,
                args=(run,),
                daemon=True,
            )
            thread.start()
        return True

    def reject(self, run_id: str, reviewer: str, notes: str = "") -> bool:
        """Reject the current review gate — marks run as failed."""
        row = state_db.get_run(run_id)
        if not row or row["status"] != "waiting_review":
            return False

        run = self._load_run(row)
        approval = HumanApproval(
            stage=run.stage,
            status=ApprovalStatus.REJECTED,
            reviewer=reviewer,
            notes=notes,
        )
        run.approvals.append(approval)
        run.status = "failed"
        run.errors.append(f"Rejected by {reviewer} at stage {run.stage.value}: {notes}")
        run.completed_at = datetime.utcnow()
        state_db.upsert_run(run)
        state_db.record_approval(run_id, approval)
        state_db.append_log(run_id, f"REJECTED by {reviewer}: {notes}")
        return True

    # ── Internal pipeline execution ───────────────────────────────────────────

    def _run_pipeline(
        self,
        run:            PipelineRun,
        raw_input:      str,
        jira_issue_key: Optional[str],
        legacy_code:    Optional[str],
        legacy_dialect: Optional[str],
    ) -> None:
        try:
            # ── Agent 1: Requirements ─────────────────────────────────────────
            self._log(run, "Agent 1: generating requirements...")
            run.stage = PipelineStage.REQUIREMENTS
            state_db.upsert_run(run)

            doc = self.agent1.run(raw_input)
            run.requirements = doc
            state_db.upsert_run(run)

            # Notify Jira of requirements draft
            if jira_issue_key:
                try:
                    self.rovo.comment_requirements_ready(jira_issue_key, doc)
                except Exception as exc:
                    self._log(run, f"Jira comment failed: {exc}")

            # ── GATE 1: Requirements review ───────────────────────────────────
            self._log(run, "Waiting for requirements approval (Paramjit)...")
            run.stage  = PipelineStage.REQUIREMENTS_REVIEW
            run.status = "waiting_review"
            state_db.upsert_run(run)
            return   # paused — will resume via approve()

        except Exception as exc:
            self._fail(run, exc)

    def _resume_pipeline(self, run: PipelineRun) -> None:
        """Continue from the current stage after approval."""
        try:
            jira_issue_key = run.jira_issue if run.jira_issue != "DRAFT" else None

            if run.stage == PipelineStage.MAPPING:
                self._run_mapping(run, jira_issue_key)

            elif run.stage == PipelineStage.ENGINEERING:
                self._run_engineering(run, jira_issue_key)

            elif run.stage == PipelineStage.QA:
                self._run_qa(run, jira_issue_key)

        except Exception as exc:
            self._fail(run, exc)

    def _run_mapping(self, run: PipelineRun, jira_issue_key: Optional[str]) -> None:
        # Push story to Jira if not yet done
        if jira_issue_key and run.requirements:
            try:
                story = run.requirements.jira_story_draft
                if story.issue_key == "DRAFT":
                    new_key = self.jira.create_issue(
                        project_key=os.getenv("JIRA_PROJECT_KEY", "DATA"),
                        summary=story.summary,
                        description=story.description,
                        acceptance_criteria=story.acceptance_criteria,
                        labels=story.labels,
                        ac_field=os.getenv("JIRA_AC_FIELD"),
                    )
                    jira_issue_key = new_key or jira_issue_key
                    run.jira_issue = jira_issue_key
            except Exception as exc:
                self._log(run, f"Jira story push failed: {exc}")

        # ── Agent 2: Mapping ──────────────────────────────────────────────────
        self._log(run, "Agent 2: building data mapping...")
        run.stage = PipelineStage.MAPPING
        state_db.upsert_run(run)

        story = run.requirements.jira_story_draft if run.requirements else JiraStory(
            issue_key=run.jira_issue, summary="", description="", acceptance_criteria=""
        )
        mapping = self.agent2.run(story)
        run.mapping = mapping
        state_db.save_mapping(mapping)
        state_db.upsert_run(run)

        if jira_issue_key:
            try:
                self.rovo.comment_mapping_ready(jira_issue_key, mapping)
                conf_url = self.rovo.create_mapping_page(jira_issue_key, mapping)
                if conf_url:
                    self._log(run, f"Confluence page: {conf_url}")
            except Exception as exc:
                self._log(run, f"Rovo write-back failed: {exc}")

        # ── GATE 2: Mapping review ────────────────────────────────────────────
        self._log(run, "Waiting for mapping approval (Shankar)...")
        run.stage  = PipelineStage.MAPPING_REVIEW
        run.status = "waiting_review"
        state_db.upsert_run(run)

    def _run_engineering(self, run: PipelineRun, jira_issue_key: Optional[str]) -> None:
        self._log(run, "Agent 3: running engineering sub-agents (3a–3e)...")
        run.stage = PipelineStage.ENGINEERING
        state_db.upsert_run(run)

        eng = EngineeringOrchestrator(
            llm=self.llm,
            bq=self.bq,
            github=self.github,
        )
        pkg = eng.run(run.mapping)
        run.engineering = pkg

        # Persist artifacts
        for art in pkg.artifacts:
            state_db.save_artifact(run.run_id, art)
        state_db.upsert_run(run)

        if jira_issue_key:
            try:
                self.rovo.comment_engineering_ready(jira_issue_key, pkg)
            except Exception as exc:
                self._log(run, f"Jira comment failed: {exc}")

        # ── GATE 3: Engineering review ────────────────────────────────────────
        self._log(run, "Waiting for engineering review (Pradeep/Chirag/Rahul/Dinesh)...")
        run.stage  = PipelineStage.ENGINEERING_REVIEW
        run.status = "waiting_review"
        state_db.upsert_run(run)

    def _run_qa(self, run: PipelineRun, jira_issue_key: Optional[str]) -> None:
        self._log(run, "Agent 4: running QA...")
        run.stage = PipelineStage.QA
        state_db.upsert_run(run)

        qa_report = self.agent4.run(
            mapping=run.mapping,
            requirements=run.requirements,
            pkg=run.engineering,
        )
        run.qa_report = qa_report
        state_db.upsert_run(run)

        if jira_issue_key:
            try:
                self.rovo.comment_qa_ready(jira_issue_key, qa_report)
            except Exception as exc:
                self._log(run, f"Jira comment failed: {exc}")

        # ── GATE 4: QA sign-off ───────────────────────────────────────────────
        self._log(run, "Waiting for QA sign-off (Sandeep/Saikrishna)...")
        run.stage  = PipelineStage.QA_REVIEW
        run.status = "waiting_review"
        state_db.upsert_run(run)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, run: PipelineRun, msg: str) -> None:
        run.log_entries.append(f"[{datetime.utcnow().isoformat()}] {msg}")
        state_db.append_log(run.run_id, msg)
        logger.info("[%s] %s", run.run_id[:8], msg)

    def _fail(self, run: PipelineRun, exc: Exception) -> None:
        msg = f"Pipeline failed at stage {run.stage.value}: {exc}"
        logger.exception(msg)
        run.status = "failed"
        run.errors.append(msg)
        run.completed_at = datetime.utcnow()
        state_db.upsert_run(run)

    def _load_run(self, row: dict) -> PipelineRun:
        import json
        from core.schemas import DataMapping, EngineeringPackage, QAReport, RequirementsDoc
        run = PipelineRun(
            run_id=row["run_id"],
            jira_issue=row["jira_issue"],
            stage=PipelineStage(row["stage"]),
            status=row["status"],
        )
        run.started_at = datetime.fromisoformat(row["started_at"])
        if row.get("requirements_json"):
            run.requirements = RequirementsDoc.model_validate_json(row["requirements_json"])
        if row.get("mapping_json"):
            run.mapping = DataMapping.model_validate_json(row["mapping_json"])
        if row.get("engineering_json"):
            run.engineering = EngineeringPackage.model_validate_json(row["engineering_json"])
        if row.get("qa_report_json"):
            run.qa_report = QAReport.model_validate_json(row["qa_report_json"])
        run.errors = json.loads(row.get("errors_json") or "[]")
        run.log_entries = json.loads(row.get("log_json") or "[]")
        run.approvals = [
            HumanApproval(**a)
            for a in json.loads(row.get("approvals_json") or "[]")
        ]
        return run


def _next_stage(stage: PipelineStage) -> Optional[PipelineStage]:
    flow = {
        PipelineStage.REQUIREMENTS_REVIEW: PipelineStage.MAPPING,
        PipelineStage.MAPPING_REVIEW:       PipelineStage.ENGINEERING,
        PipelineStage.ENGINEERING_REVIEW:   PipelineStage.QA,
        PipelineStage.QA_REVIEW:            PipelineStage.COMPLETED,
    }
    return flow.get(stage)


def _require(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise EnvironmentError(f"Missing required env var: {name}")
    return v
