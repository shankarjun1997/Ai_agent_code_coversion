"""SQLite-backed state management for all pipeline runs."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.schemas import (
    ApprovalStatus,
    EngineeringPackage,
    HumanApproval,
    PipelineRun,
    PipelineStage,
    QAReport,
    DataMapping,
    RequirementsDoc,
    GeneratedArtifact,
)

DB_PATH = Path(__file__).parent.parent / "output" / "state.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id          TEXT PRIMARY KEY,
            jira_issue      TEXT NOT NULL,
            started_at      TEXT NOT NULL,
            completed_at    TEXT,
            stage           TEXT NOT NULL DEFAULT 'requirements',
            status          TEXT NOT NULL DEFAULT 'running',
            requirements_json TEXT,
            mapping_json    TEXT,
            engineering_json TEXT,
            qa_report_json  TEXT,
            approvals_json  TEXT DEFAULT '[]',
            errors_json     TEXT DEFAULT '[]',
            log_json        TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS generated_artifacts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,
            artifact_type   TEXT NOT NULL,
            filename        TEXT NOT NULL,
            content         TEXT NOT NULL,
            explanation     TEXT,
            dry_run_valid   INTEGER,
            dry_run_bytes   INTEGER,
            created_at      TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS data_mappings (
            mapping_id  TEXT PRIMARY KEY,
            jira_issue  TEXT NOT NULL,
            version     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL,
            mapping_json TEXT NOT NULL
        );
    """)
    conn.commit()


# ── Write helpers ─────────────────────────────────────────────────────────────

def upsert_run(run: PipelineRun) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO pipeline_runs
                (run_id, jira_issue, started_at, completed_at, stage, status,
                 requirements_json, mapping_json, engineering_json, qa_report_json,
                 approvals_json, errors_json, log_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                completed_at       = excluded.completed_at,
                stage              = excluded.stage,
                status             = excluded.status,
                requirements_json  = excluded.requirements_json,
                mapping_json       = excluded.mapping_json,
                engineering_json   = excluded.engineering_json,
                qa_report_json     = excluded.qa_report_json,
                approvals_json     = excluded.approvals_json,
                errors_json        = excluded.errors_json,
                log_json           = excluded.log_json
        """, (
            run.run_id, run.jira_issue,
            run.started_at.isoformat(),
            run.completed_at.isoformat() if run.completed_at else None,
            run.stage.value, run.status,
            run.requirements.model_dump_json()  if run.requirements  else None,
            run.mapping.model_dump_json()       if run.mapping       else None,
            run.engineering.model_dump_json()   if run.engineering   else None,
            run.qa_report.model_dump_json()     if run.qa_report     else None,
            json.dumps([a.model_dump(mode="json") for a in run.approvals]),
            json.dumps(run.errors),
            json.dumps(run.log_entries),
        ))
        conn.commit()


def append_log(run_id: str, message: str) -> None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT log_json FROM pipeline_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            return
        logs: List[str] = json.loads(row["log_json"] or "[]")
        logs.append(f"[{datetime.utcnow().isoformat()}] {message}")
        conn.execute(
            "UPDATE pipeline_runs SET log_json=? WHERE run_id=?",
            (json.dumps(logs), run_id),
        )
        conn.commit()


def save_artifact(run_id: str, artifact: GeneratedArtifact) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO generated_artifacts
                (run_id, artifact_type, filename, content, explanation,
                 dry_run_valid, dry_run_bytes, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            run_id, artifact.artifact_type.value, artifact.filename,
            artifact.content, artifact.explanation,
            1 if artifact.dry_run_valid else 0 if artifact.dry_run_valid is False else None,
            artifact.dry_run_bytes,
            artifact.created_at.isoformat(),
        ))
        conn.commit()


def save_mapping(mapping: DataMapping) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO data_mappings (mapping_id, jira_issue, version, created_at, mapping_json)
            VALUES (?,?,?,?,?)
            ON CONFLICT(mapping_id) DO UPDATE SET
                mapping_json = excluded.mapping_json,
                version      = excluded.version
        """, (
            mapping.mapping_id, mapping.jira_issue, mapping.version,
            mapping.created_at.isoformat(), mapping.model_dump_json(),
        ))
        conn.commit()


def record_approval(run_id: str, approval: HumanApproval) -> None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT approvals_json FROM pipeline_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            return
        approvals: List[Dict] = json.loads(row["approvals_json"] or "[]")
        approvals.append(approval.model_dump(mode="json"))
        conn.execute(
            "UPDATE pipeline_runs SET approvals_json=? WHERE run_id=?",
            (json.dumps(approvals), run_id),
        )
        conn.commit()


# ── Read helpers ──────────────────────────────────────────────────────────────

def get_run(run_id: str) -> Optional[Dict]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None


def get_recent_runs(limit: int = 30) -> List[Dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_run_artifacts(run_id: str) -> List[Dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM generated_artifacts WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_mappings(limit: int = 30) -> List[Dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM data_mappings ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_reviews() -> List[Dict]:
    """Runs currently waiting for a human reviewer."""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT * FROM pipeline_runs
            WHERE status = 'waiting_review'
            ORDER BY started_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
