"""Jira REST API v3 client — read stories, write comments, transition issues."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth

from core.schemas import JiraStory

logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, url: str, email: str, api_token: str):
        self.base   = url.rstrip("/")
        self.auth   = HTTPBasicAuth(email, api_token)
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        resp = requests.get(
            f"{self.base}/rest/api/3/{path}",
            auth=self.auth, headers=self.headers, params=params or {}, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Dict) -> Dict:
        resp = requests.post(
            f"{self.base}/rest/api/3/{path}",
            auth=self.auth, headers=self.headers, json=body, timeout=30
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def get_issue(self, issue_key: str, ac_field: Optional[str] = None) -> JiraStory:
        data = self._get(f"issue/{issue_key}")
        fields = data.get("fields", {})

        description = _extract_text(fields.get("description"))
        acceptance_criteria = ""
        if ac_field:
            acceptance_criteria = _extract_text(fields.get(ac_field)) or ""

        return JiraStory(
            issue_key=issue_key,
            summary=fields.get("summary", ""),
            description=description,
            acceptance_criteria=acceptance_criteria,
            labels=fields.get("labels", []),
            priority=fields.get("priority", {}).get("name") if fields.get("priority") else None,
            assignee=fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None,
            components=[c["name"] for c in fields.get("components", [])],
            status=fields.get("status", {}).get("name") if fields.get("status") else None,
            story_type=fields.get("issuetype", {}).get("name") if fields.get("issuetype") else None,
            attachments=[
                att.get("content", "")
                for att in fields.get("attachment", [])
            ],
        )

    def search_issues(self, jql: str, max_results: int = 50) -> List[Dict]:
        data = self._get("search", params={"jql": jql, "maxResults": max_results,
                                            "fields": "summary,status,priority,assignee,labels"})
        return data.get("issues", [])

    # ── Write ─────────────────────────────────────────────────────────────────

    def create_issue(self, project_key: str, summary: str, description: str,
                     issue_type: str = "Story", labels: Optional[List[str]] = None,
                     acceptance_criteria: str = "", ac_field: Optional[str] = None) -> str:
        fields: Dict[str, Any] = {
            "project":   {"key": project_key},
            "summary":   summary,
            "issuetype": {"name": issue_type},
            "description": _adf_doc(description),
            "labels":    labels or [],
        }
        if ac_field and acceptance_criteria:
            fields[ac_field] = _adf_doc(acceptance_criteria)

        data = self._post("issue", {"fields": fields})
        return data.get("key", "")

    def add_comment(self, issue_key: str, body: str) -> None:
        self._post(f"issue/{issue_key}/comment", {"body": _adf_doc(body)})
        logger.info("Comment added to %s", issue_key)

    def transition_issue(self, issue_key: str, transition_name: str) -> None:
        transitions = self._get(f"issue/{issue_key}/transitions").get("transitions", [])
        target = next((t for t in transitions if t["name"].lower() == transition_name.lower()), None)
        if not target:
            logger.warning("Transition '%s' not found for %s", transition_name, issue_key)
            return
        requests.post(
            f"{self.base}/rest/api/3/issue/{issue_key}/transitions",
            auth=self.auth, headers=self.headers,
            json={"transition": {"id": target["id"]}}, timeout=30,
        ).raise_for_status()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(adf: Any) -> str:
    """Flatten Atlassian Document Format → plain text."""
    if adf is None:
        return ""
    if isinstance(adf, str):
        return adf
    if isinstance(adf, dict):
        parts = []
        for node in adf.get("content", []):
            parts.append(_extract_text(node))
        text = adf.get("text", "")
        if text:
            parts.append(text)
        return " ".join(p for p in parts if p)
    return str(adf)


def _adf_doc(text: str) -> Dict:
    """Wrap plain text in minimal ADF structure."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }
