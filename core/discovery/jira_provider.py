"""Jira as a first-class connection profile.

Not a relational source — implements SourceProvider with empty schema/table/column
methods so it slots into the same ProfileRegistry, but adds `get_issue` and `ping`
specialised for the Jira REST v3 API. Auth = Basic (email + api_token).
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from core.discovery.base import (
    ColumnHit, ColumnInfo, ColumnProfile, FKInfo, PingResult,
    SourceProvider, TableInfo,
)
from core.discovery.credentials import decrypt


def _auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _decode_creds(profile: Any) -> Dict[str, str]:
    """Return {email, api_token} from encrypted_credentials, or {} if absent."""
    blob = getattr(profile, "encrypted_credentials", None)
    if not blob:
        return {}
    try:
        return decrypt(blob)
    except Exception:
        return {}


def _request_json(method: str, url: str, headers: Dict[str, str], timeout: int = 10) -> Dict[str, Any]:
    req = urllib.request.Request(url, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


class JiraProvider(SourceProvider):
    """Jira REST v3 wrapper. Non-schema source — most SourceProvider methods are stubs."""
    dialect = "jira"

    async def ping(self, profile: Any) -> PingResult:
        def _sync() -> PingResult:
            creds = _decode_creds(profile)
            email = creds.get("email") or getattr(profile, "extra", {}).get("email", "")
            token = creds.get("api_token", "")
            base = (profile.dsn or "").rstrip("/")
            if not (base and email and token):
                return PingResult(ok=False, message="missing base_url, email or api_token")
            url = f"{base}/rest/api/3/myself"
            t0 = time.perf_counter()
            try:
                data = _request_json(
                    "GET", url,
                    headers={"Authorization": _auth_header(email, token), "Accept": "application/json"},
                )
                latency = int((time.perf_counter() - t0) * 1000)
                return PingResult(ok=True, latency_ms=latency, message=data.get("displayName") or data.get("emailAddress"))
            except urllib.error.HTTPError as exc:
                return PingResult(ok=False, message=f"HTTP {exc.code}: {exc.reason}")
            except Exception as exc:
                return PingResult(ok=False, message=str(exc))
        return await asyncio.to_thread(_sync)

    async def get_issue(self, profile: Any, issue_key: str) -> Dict[str, Any]:
        """Fetch a single Jira issue — summary, description, status, labels, assignee."""
        def _sync() -> Dict[str, Any]:
            creds = _decode_creds(profile)
            email = creds.get("email") or getattr(profile, "extra", {}).get("email", "")
            token = creds.get("api_token", "")
            base = (profile.dsn or "").rstrip("/")
            if not (base and email and token):
                return {"ok": False, "message": "missing creds"}
            url = f"{base}/rest/api/3/issue/{issue_key}?fields=summary,description,status,labels,assignee"
            try:
                data = _request_json(
                    "GET", url,
                    headers={"Authorization": _auth_header(email, token), "Accept": "application/json"},
                )
                f = data.get("fields", {})
                desc = f.get("description")
                if isinstance(desc, dict):
                    desc = _adf_to_text(desc)
                return {
                    "ok": True,
                    "key": data.get("key", issue_key),
                    "summary": f.get("summary", ""),
                    "description": desc or "",
                    "status": (f.get("status") or {}).get("name", ""),
                    "labels": f.get("labels", []),
                    "assignee": (f.get("assignee") or {}).get("displayName", ""),
                }
            except urllib.error.HTTPError as exc:
                return {"ok": False, "message": f"HTTP {exc.code}", "key": issue_key}
            except Exception as exc:
                return {"ok": False, "message": str(exc), "key": issue_key}
        return await asyncio.to_thread(_sync)

    # SourceProvider schema methods — N/A for Jira (returns empty lists)
    async def list_schemas(self, profile: Any) -> List[str]:
        return []

    async def list_tables(self, profile: Any, schema: str) -> List[TableInfo]:
        return []

    async def get_columns(self, profile: Any, schema: str, table: str) -> List[ColumnInfo]:
        return []

    async def get_foreign_keys(self, profile: Any, schema: str, table: str) -> List[FKInfo]:
        return []

    async def profile_column(self, profile: Any, schema: str, table: str, column: str,
                              sample_rows: int = 0) -> ColumnProfile:
        return ColumnProfile()

    async def search_by_keywords(self, profile: Any, keywords: List[str], limit: int = 50) -> List[ColumnHit]:
        return []


def _adf_to_text(adf: Dict[str, Any]) -> str:
    """Best-effort flatten of Jira Atlassian Document Format to plain text."""
    out: List[str] = []
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and "text" in node:
                out.append(node["text"])
            for child in node.get("content", []) or []:
                walk(child)
            if node.get("type") in ("paragraph", "heading", "listItem"):
                out.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(adf)
    return "".join(out).strip()
