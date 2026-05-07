"""GitHub integration — create branches, commit files, open PRs."""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: str, owner: str, repo: str):
        self.token   = token
        self.owner   = owner
        self.repo    = repo
        self.base    = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept":        "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, path: str) -> Dict:
        resp = requests.get(f"{self.base}{path}", headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Dict) -> Dict:
        resp = requests.post(
            f"{self.base}{path}", headers=self.headers, json=body, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, body: Dict) -> Dict:
        resp = requests.put(
            f"{self.base}{path}", headers=self.headers, json=body, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    # ── Branch helpers ────────────────────────────────────────────────────────

    def get_default_branch_sha(self) -> str:
        data = self._get(f"/repos/{self.owner}/{self.repo}")
        default = data["default_branch"]
        ref = self._get(f"/repos/{self.owner}/{self.repo}/git/ref/heads/{default}")
        return ref["object"]["sha"]

    def create_branch(self, branch_name: str, base_sha: str) -> None:
        self._post(f"/repos/{self.owner}/{self.repo}/git/refs", {
            "ref": f"refs/heads/{branch_name}",
            "sha": base_sha,
        })
        logger.info("Created branch %s", branch_name)

    # ── File commits ──────────────────────────────────────────────────────────

    def upsert_file(
        self,
        branch:   str,
        path:     str,
        content:  str,
        message:  str,
    ) -> None:
        encoded = base64.b64encode(content.encode()).decode()
        body: Dict = {
            "message": message,
            "content": encoded,
            "branch":  branch,
        }
        # Check if file already exists (get its SHA for update)
        try:
            existing = self._get(
                f"/repos/{self.owner}/{self.repo}/contents/{path}?ref={branch}"
            )
            body["sha"] = existing["sha"]
        except requests.HTTPError:
            pass  # file doesn't exist yet — that's fine

        self._put(f"/repos/{self.owner}/{self.repo}/contents/{path}", body)

    def commit_files(
        self,
        branch:  str,
        files:   List[Dict],   # [{"path": ..., "content": ...}]
        message: str,
    ) -> None:
        for f in files:
            self.upsert_file(branch, f["path"], f["content"], message)

    # ── Pull Request ──────────────────────────────────────────────────────────

    def create_pr(
        self,
        head:    str,
        title:   str,
        body:    str,
        base:    Optional[str] = None,
    ) -> str:
        """Return the PR HTML URL."""
        if base is None:
            data = self._get(f"/repos/{self.owner}/{self.repo}")
            base = data["default_branch"]
        pr = self._post(f"/repos/{self.owner}/{self.repo}/pulls", {
            "title": title,
            "head":  head,
            "base":  base,
            "body":  body,
        })
        url = pr["html_url"]
        logger.info("Created PR: %s", url)
        return url

    # ── Convenience ───────────────────────────────────────────────────────────

    def publish_artifacts(
        self,
        jira_issue:   str,
        artifacts:    List[Dict],   # [{"filename": ..., "content": ...}]
        pr_title:     str,
        pr_body:      str,
        base_folder:  str = "generated",
    ) -> str:
        """
        Create a branch, commit all artifacts, open a PR.
        Returns the PR URL.
        """
        ts     = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        branch = f"data-gen/{jira_issue.lower()}-{ts}"

        sha = self.get_default_branch_sha()
        self.create_branch(branch, sha)

        files = [
            {"path": f"{base_folder}/{jira_issue}/{a['filename']}", "content": a["content"]}
            for a in artifacts
        ]
        self.commit_files(branch, files, f"feat({jira_issue}): add generated pipeline assets")

        return self.create_pr(head=branch, title=pr_title, body=pr_body)
