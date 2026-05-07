"""Atlassian Rovo + Jira write-back connector.

Rovo itself runs on top of Jira/Confluence REST APIs.
This module handles:
  - Posting structured pipeline summaries as Jira comments
  - Transitioning Jira issue status
  - Creating Confluence documentation pages (optional)
  - Triggering Rovo agent actions via Atlassian Connect (when available)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth

from core.schemas import DataMapping, EngineeringPackage, PipelineRun, QAReport, RequirementsDoc

logger = logging.getLogger(__name__)


class RovoConnector:
    def __init__(
        self,
        jira_url:   str,
        email:      str,
        api_token:  str,
        confluence_url: Optional[str] = None,
        confluence_space: Optional[str] = None,
    ):
        self.jira_base  = jira_url.rstrip("/")
        self.auth       = HTTPBasicAuth(email, api_token)
        self.headers    = {"Accept": "application/json", "Content-Type": "application/json"}
        self.conf_base  = (confluence_url or "").rstrip("/")
        self.conf_space = confluence_space

    # ── Jira comment helpers ──────────────────────────────────────────────────

    def _post_comment(self, issue_key: str, body_adf: Dict) -> None:
        url = f"{self.jira_base}/rest/api/3/issue/{issue_key}/comment"
        resp = requests.post(url, auth=self.auth, headers=self.headers,
                             json={"body": body_adf}, timeout=30)
        resp.raise_for_status()
        logger.info("Posted comment to %s", issue_key)

    def comment_requirements_ready(self, issue_key: str, doc: RequirementsDoc) -> None:
        lines = [
            f"**Requirements draft ready** (ID: {doc.doc_id})",
            "",
            f"**Tasks identified:** {len(doc.task_breakdown)}",
        ]
        for task in doc.task_breakdown:
            lines.append(f"  - {task}")
        if doc.clarifying_questions:
            lines.append("")
            lines.append(f"**Clarifying questions ({len(doc.clarifying_questions)}):**")
            for q in doc.clarifying_questions[:5]:
                lines.append(f"  - [{q.priority.upper()}] {q.question}")
        if doc.contradictions:
            lines.append("")
            lines.append("**Contradictions detected:**")
            for c in doc.contradictions:
                lines.append(f"  - {c}")
        lines.append("")
        lines.append("*Awaiting reviewer approval before Jira story is pushed.*")
        self._post_comment(issue_key, _adf_doc("\n".join(lines)))

    def comment_mapping_ready(self, issue_key: str, mapping: DataMapping) -> None:
        lines = [
            f"**Data mapping ready** (mapping_id: {mapping.mapping_id})",
            "",
            f"**Source tables:** {', '.join(f'{t.dataset}.{t.table}' for t in mapping.source_tables)}",
            f"**Target:** {mapping.target_dataset}.{mapping.target_table}",
            f"**Fields mapped:** {len(mapping.field_mappings)}",
            f"**Output types:** {', '.join(t.value for t in mapping.output_types)}",
            f"**Idempotency:** {mapping.idempotency_strategy.value}",
            "",
            "*Awaiting Shankar's review and approval.*",
        ]
        self._post_comment(issue_key, _adf_doc("\n".join(lines)))

    def comment_engineering_ready(self, issue_key: str, pkg: EngineeringPackage) -> None:
        artifact_types = list({a.artifact_type.value for a in pkg.artifacts})
        dq_count = len(pkg.dq_report.rules) if pkg.dq_report else 0
        lines = [
            f"**Engineering package ready** (pkg_id: {pkg.package_id})",
            "",
            f"**Artifacts generated:** {len(pkg.artifacts)} ({', '.join(artifact_types)})",
            f"**DQ rules:** {dq_count}",
            f"**GitHub PR:** {pkg.github_pr_url or 'Not yet created'}",
            "",
            "*Awaiting engineer review before merge/deploy.*",
        ]
        self._post_comment(issue_key, _adf_doc("\n".join(lines)))

    def comment_qa_ready(self, issue_key: str, qa: QAReport) -> None:
        lines = [
            f"**QA report ready** (report_id: {qa.report_id})",
            "",
            f"**Test cases:** {len(qa.test_cases)}",
            f"**Defects found:** {len(qa.defects)}",
            f"**Sign-off ready:** {'Yes' if qa.sign_off_ready else 'No — defects outstanding'}",
            "",
            "*Awaiting QA lead sign-off.*",
        ]
        self._post_comment(issue_key, _adf_doc("\n".join(lines)))

    def comment_pipeline_complete(self, issue_key: str, run: PipelineRun) -> None:
        lines = [
            "**Pipeline completed successfully**",
            "",
            f"**Run ID:** {run.run_id}",
            f"**PR URL:** {run.engineering.github_pr_url if run.engineering else 'N/A'}",
            "",
            "All agents have completed and the engineering package has been merged.",
        ]
        self._post_comment(issue_key, _adf_doc("\n".join(lines)))

    def transition_issue(self, issue_key: str, transition_name: str) -> None:
        url = f"{self.jira_base}/rest/api/3/issue/{issue_key}/transitions"
        transitions = requests.get(url, auth=self.auth, headers=self.headers, timeout=30).json()
        target = next(
            (t for t in transitions.get("transitions", [])
             if t["name"].lower() == transition_name.lower()),
            None,
        )
        if not target:
            logger.warning("Transition '%s' not found for %s", transition_name, issue_key)
            return
        requests.post(url, auth=self.auth, headers=self.headers,
                      json={"transition": {"id": target["id"]}}, timeout=30).raise_for_status()

    # ── Confluence page creation ───────────────────────────────────────────────

    def create_mapping_page(self, issue_key: str, mapping: DataMapping) -> Optional[str]:
        """Create a Confluence page with the mapping spec. Returns page URL."""
        if not self.conf_base or not self.conf_space:
            return None
        content = _mapping_to_confluence(mapping)
        body = {
            "type":  "page",
            "title": f"[{issue_key}] Data Mapping — {mapping.target_dataset}.{mapping.target_table}",
            "space": {"key": self.conf_space},
            "body":  {"storage": {"value": content, "representation": "storage"}},
        }
        resp = requests.post(
            f"{self.conf_base}/rest/api/content",
            auth=self.auth, headers=self.headers, json=body, timeout=30,
        )
        if resp.ok:
            page_id = resp.json().get("id")
            return f"{self.conf_base}/wiki/spaces/{self.conf_space}/pages/{page_id}"
        logger.warning("Failed to create Confluence page: %s", resp.text)
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _adf_doc(text: str) -> Dict:
    paragraphs = []
    for line in text.split("\n"):
        paragraphs.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": line or " "}],
        })
    return {"type": "doc", "version": 1, "content": paragraphs}


def _mapping_to_confluence(m: DataMapping) -> str:
    rows = "".join(
        f"<tr><td>{f.target_field}</td><td>{f.source_expression}</td>"
        f"<td>{f.data_type}</td><td>{f.description or ''}</td></tr>"
        for f in m.field_mappings
    )
    return f"""
<h2>Data Mapping — {m.mapping_id}</h2>
<p><b>Jira Issue:</b> {m.jira_issue} | <b>Version:</b> {m.version}</p>
<h3>Source Tables</h3>
<ul>{''.join(f'<li>{t.dataset}.{t.table} AS {t.alias}</li>' for t in m.source_tables)}</ul>
<h3>Target</h3>
<p>{m.target_dataset}.{m.target_table}</p>
<h3>Field Mappings</h3>
<table>
  <thead><tr><th>Target Field</th><th>Source Expression</th><th>Type</th><th>Description</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
<h3>Business Rules</h3>
<ul>{''.join(f'<li>{r}</li>' for r in m.business_rules)}</ul>
<h3>Filters</h3>
<ul>{''.join(f'<li>{f}</li>' for f in m.filters)}</ul>
"""
