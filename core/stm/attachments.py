"""Attachment parser — turns uploaded files into blackboard Attachments.

Supported kinds:
  - csv  → text excerpt + inferred schema {columns: [{name, type, samples}]}
  - pdf  → text excerpt via pdfplumber (falls back to bytes-as-text)
  - docx → text excerpt via python-docx
  - txt  → raw text

Schema inference is deliberately tiny — first 200 rows, type buckets
(int / float / date / bool / string). This is enough for L2 to synthesise
plausible source-side nodes when no relational source covers the use case.
"""
from __future__ import annotations

import csv as _csv
import io
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_BOOL_VALS = {"true", "false", "yes", "no", "0", "1", "t", "f", "y", "n"}
_DATE_HINTS = (
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
)


def _classify(value: str) -> str:
    v = value.strip()
    if not v:
        return ""
    low = v.lower()
    if low in _BOOL_VALS and not _INT_RE.match(v):
        return "BOOL"
    if _INT_RE.match(v):
        return "INT"
    if _FLOAT_RE.match(v):
        return "FLOAT"
    for fmt in _DATE_HINTS:
        try:
            datetime.strptime(v, fmt)
            return "TIMESTAMP" if "%H" in fmt else "DATE"
        except ValueError:
            continue
    return "STRING"


def _consolidate(types: List[str]) -> str:
    types = [t for t in types if t]
    if not types:
        return "STRING"
    uniq = set(types)
    if uniq <= {"INT"}:
        return "INT"
    if uniq <= {"INT", "FLOAT"}:
        return "FLOAT"
    if uniq <= {"BOOL"}:
        return "BOOL"
    if uniq <= {"DATE"}:
        return "DATE"
    if uniq <= {"DATE", "TIMESTAMP"}:
        return "TIMESTAMP"
    return "STRING"


def _infer_csv_schema(path: str, sample_rows: int = 200) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        head = f.read(8192)
        f.seek(0)
        try:
            dialect = _csv.Sniffer().sniff(head, delimiters=",;\t|")
        except Exception:
            dialect = _csv.excel
        has_header = True
        try:
            has_header = _csv.Sniffer().has_header(head)
        except Exception:
            pass
        reader = _csv.reader(f, dialect=dialect)
        rows = list(reader)
    if not rows:
        return {"columns": [], "row_sample_count": 0, "has_header": False, "delimiter": ","}
    if has_header:
        headers = [str(c).strip() or f"col_{i}" for i, c in enumerate(rows[0])]
        body = rows[1: 1 + sample_rows]
    else:
        headers = [f"col_{i}" for i in range(len(rows[0]))]
        body = rows[: sample_rows]
    width = len(headers)
    type_grids: List[List[str]] = [[] for _ in range(width)]
    samples: List[List[str]] = [[] for _ in range(width)]
    for row in body:
        for i in range(width):
            cell = row[i] if i < len(row) else ""
            type_grids[i].append(_classify(str(cell)))
            if len(samples[i]) < 5 and str(cell).strip():
                samples[i].append(str(cell))
    columns = [
        {"name": headers[i], "type": _consolidate(type_grids[i]), "samples": samples[i]}
        for i in range(width)
    ]
    return {
        "columns": columns,
        "row_sample_count": len(body),
        "has_header": has_header,
        "delimiter": getattr(dialect, "delimiter", ","),
    }


def _extract_pdf_text(path: str) -> str:
    try:
        import pdfplumber  # type: ignore
        out: List[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:20]:
                t = page.extract_text() or ""
                if t:
                    out.append(t)
        return "\n\n".join(out)
    except Exception:
        try:
            with open(path, "rb") as f:
                raw = f.read(64 * 1024)
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return ""


def _extract_docx_text(path: str) -> str:
    try:
        from docx import Document  # type: ignore
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception:
        return ""


def _read_txt(path: str, limit: int = 64 * 1024) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except Exception:
        return ""


def _detect_kind(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext in ("csv", "tsv"):
        return "csv"
    if ext == "pdf":
        return "pdf"
    if ext in ("docx", "doc"):
        return "docx"
    return "txt"


def parse_attachment(path: str, filename: str) -> Dict[str, Any]:
    """Return {kind, text_excerpt, csv_schema?, bytes} for a stored attachment."""
    kind = _detect_kind(filename)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    if kind == "csv":
        try:
            schema = _infer_csv_schema(path)
        except Exception:
            schema = {"columns": [], "row_sample_count": 0, "has_header": False, "delimiter": ","}
        cols_str = ", ".join(c["name"] + ":" + c["type"] for c in schema.get("columns", [])[:20])
        excerpt = f"[CSV {filename}] {schema.get('row_sample_count', 0)} rows sampled. Columns: {cols_str}"
        return {"kind": "csv", "text_excerpt": excerpt, "csv_schema": schema, "bytes": size}
    if kind == "pdf":
        return {"kind": "pdf", "text_excerpt": _extract_pdf_text(path)[:8000], "csv_schema": None, "bytes": size}
    if kind == "docx":
        return {"kind": "docx", "text_excerpt": _extract_docx_text(path)[:8000], "csv_schema": None, "bytes": size}
    return {"kind": "txt", "text_excerpt": _read_txt(path)[:8000], "csv_schema": None, "bytes": size}


def storage_dir(session_id: str) -> str:
    root = os.environ.get("STM_ATTACHMENT_ROOT", "/app/output/stm_attachments")
    if not os.path.isdir("/app/output"):
        root = os.environ.get("STM_ATTACHMENT_ROOT", "./output/stm_attachments")
    path = os.path.join(root, session_id)
    os.makedirs(path, exist_ok=True)
    return path
