"""Render a MappingResult to .xlsx (openpyxl) or .csv. Stakeholder-ready format."""
from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.stm.mapping_engine import MappingResult


HEADERS = [
    "Source System", "Source Schema", "Source Table", "Source Column", "Source Type",
    "Nullable", "Source Description",
    "Target Dataset", "Target Table", "Target Column", "Target Type",
    "Transformation", "PII", "Sensitivity", "Notes",
]


def _row_values(r) -> list:
    return [
        r.source_system, r.source_schema, r.source_table, r.source_column, r.source_type,
        "Y" if r.source_nullable else "N", r.source_description or "",
        r.target_dataset, r.target_table, r.target_column, r.target_type,
        r.transformation, "Y" if r.is_pii else "N", r.sensitivity, r.notes,
    ]


def to_csv(result: "MappingResult") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    for r in result.rows:
        w.writerow(_row_values(r))
    return buf.getvalue().encode("utf-8")


def to_xlsx(result: "MappingResult") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    # ── Sheet 1: Mapping ─────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Mapping"

    header_fill = PatternFill(start_color="07111F", end_color="07111F", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FBBF24")
    body_font   = Font(name="Calibri", size=10)
    pii_fill    = PatternFill(start_color="FFE4E6", end_color="FFE4E6", fill_type="solid")
    thin = Side(border_style="thin", color="E5E7EB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col_idx, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="left", vertical="center")
        cell.border = border

    for i, r in enumerate(result.rows, 2):
        for col_idx, val in enumerate(_row_values(r), 1):
            cell = ws.cell(row=i, column=col_idx, value=val)
            cell.font = body_font
            cell.border = border
            if r.is_pii:
                cell.fill = pii_fill

    # Column widths
    widths = [14, 14, 16, 22, 22, 9, 36, 18, 22, 22, 14, 38, 6, 12, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    # ── Sheet 2: Summary ─────────────────────────────────────────────────
    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = "Source-to-Target Mapping (STM)"
    ws2["A1"].font = Font(name="Calibri", size=16, bold=True, color="07111F")
    summary = [
        ("STM ID",               result.stm_id),
        ("Generated at",         result.generated_at),
        ("Source system",        result.source_system),
        ("Source schema",        result.source_schema),
        ("Source tables",        ", ".join(result.source_tables)),
        ("Target dataset",       result.target_dataset),
        ("Target table",         result.target_table),
        ("Field count",          result.field_count),
        ("PII fields detected",  result.pii_count),
        ("Partition field",      result.partition_field or "—"),
        ("Idempotency strategy", result.idempotency_strategy),
        ("Idempotency key",      result.idempotency_key or "—"),
    ]
    for i, (k, v) in enumerate(summary, 3):
        ws2.cell(row=i, column=1, value=k).font = Font(bold=True, color="64748B")
        ws2.cell(row=i, column=2, value=str(v)).font = body_font

    # Business rules
    base_row = len(summary) + 5
    ws2.cell(row=base_row, column=1, value="Business rules").font = Font(bold=True, size=12, color="07111F")
    for i, rule in enumerate(result.business_rules, 1):
        ws2.cell(row=base_row + i, column=1, value=f"  {i}. {rule}").font = body_font

    ws2.column_dimensions["A"].width = 24
    ws2.column_dimensions["B"].width = 80

    # ── Output ───────────────────────────────────────────────────────────
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
