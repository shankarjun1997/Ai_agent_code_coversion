"""SVG workflow diagram generator for DataMapping objects.

Produces a standalone SVG showing:
  - Source table boxes (left) with all columns
  - Target table box (right) with all mapped fields
  - Bezier connector lines: source field → target field
  - Transformation labels on lines
  - Business rules panel
  - DQ / observability / metadata badges
  - Schema verification result overlay
  - PII field markers
  - Legend
"""
from __future__ import annotations

import html
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Layout constants ──────────────────────────────────────────────────────────

W            = 1500   # total canvas width
MARGIN       = 48
SRC_X        = MARGIN
SRC_W        = 380
CONN_MID_X   = SRC_X + SRC_W + 150   # midpoint of connector zone
TGT_X        = CONN_MID_X + 150
TGT_W        = 400
ROW_H        = 30
HDR_H        = 44
TBL_PAD      = 14
TBL_GAP      = 22
TOP_PAD      = 120   # below header bar
BOTTOM_PAD   = 180   # for rules + legend

COLORS = {
    "bg":          "#F8FAFC",
    "hdr_bg":      "#1E293B",
    "hdr_txt":     "#F1F5F9",
    "src_hdr":     "#2563EB",
    "src_hdr_txt": "#FFFFFF",
    "src_row":     "#EFF6FF",
    "src_border":  "#BFDBFE",
    "tgt_hdr":     "#059669",
    "tgt_hdr_txt": "#FFFFFF",
    "tgt_row":     "#ECFDF5",
    "tgt_border":  "#6EE7B7",
    "line":        "#94A3B8",
    "line_tx":     "#F97316",
    "pii_bg":      "#FEF2F2",
    "pii_dot":     "#EF4444",
    "rule_bg":     "#FFFBEB",
    "rule_border": "#FDE68A",
    "legend_bg":   "#F1F5F9",
    "verify_ok":   "#D1FAE5",
    "verify_err":  "#FEE2E2",
    "miss_row":    "#FEE2E2",
    "title_txt":   "#0F172A",
    "sub_txt":     "#64748B",
    "shadow":      "rgba(0,0,0,0.08)",
}


# ── Public entry point ────────────────────────────────────────────────────────

def generate_mapping_svg(
    mapping: Any,                           # DataMapping pydantic model
    verify_result: Optional[Any] = None,    # SchemaVerificationResult | None
    output_dir: str = "output/diagrams",
) -> str:
    """
    Generate SVG, write to output_dir/{mapping_id}.svg, return file path.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    svg_path = os.path.join(output_dir, f"{mapping.mapping_id}.svg")
    svg_content = _build_svg(mapping, verify_result)
    Path(svg_path).write_text(svg_content, encoding="utf-8")
    return svg_path


# ── SVG builder ───────────────────────────────────────────────────────────────

def _build_svg(mapping: Any, verify: Optional[Any]) -> str:
    src_tables  = mapping.source_tables
    tgt_fields  = mapping.field_mappings
    biz_rules   = mapping.business_rules
    filters     = mapping.filters

    # ── Compute layout heights ────────────────────────────────────────────────
    def table_h(n_fields: int) -> int:
        return HDR_H + n_fields * ROW_H + TBL_PAD

    # We need "actual" source field counts — use mapping references
    # Group target fields by their source alias for rough per-table counts
    src_field_counts = {t.table: 0 for t in src_tables}
    for fm in tgt_fields:
        for tbl in src_tables:
            if tbl.alias in fm.source_expression:
                src_field_counts[tbl.table] += 1
                break
    # Ensure at least 1 row per table
    for k in src_field_counts:
        src_field_counts[k] = max(src_field_counts[k], 1)

    total_src_h = sum(
        table_h(src_field_counts[t.table]) + TBL_GAP
        for t in src_tables
    )
    tgt_h = table_h(len(tgt_fields))
    body_h = max(total_src_h, tgt_h)
    canvas_h = TOP_PAD + body_h + BOTTOM_PAD + 40

    parts: List[str] = []

    # ── Root SVG ──────────────────────────────────────────────────────────────
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{W}" height="{canvas_h}" viewBox="0 0 {W} {canvas_h}" '
        f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
        f'style="background:{COLORS["bg"]}">'
    )

    parts.append(_defs())
    parts.append(_header_bar(mapping))
    parts.append(_metadata_bar(mapping, verify))

    # ── Source tables ─────────────────────────────────────────────────────────
    src_row_centers: Dict[str, List[Tuple[int, int]]] = {}  # alias → [(x, y), ...]
    y_cursor = TOP_PAD

    for tbl in src_tables:
        alias   = tbl.alias
        n_rows  = src_field_counts[tbl.table]
        h       = table_h(n_rows)

        # Collect fields that reference this table
        my_fields = [
            fm for fm in tgt_fields
            if alias in fm.source_expression
        ]
        # Pad to n_rows
        while len(my_fields) < n_rows:
            my_fields.append(None)

        parts.append(_source_table_box(tbl, my_fields[:n_rows], SRC_X, y_cursor))

        centers = []
        for i in range(n_rows):
            cy = y_cursor + HDR_H + i * ROW_H + ROW_H // 2
            centers.append((SRC_X + SRC_W, cy))
        src_row_centers[alias] = centers

        y_cursor += h + TBL_GAP

    # ── Target table ──────────────────────────────────────────────────────────
    tgt_top = TOP_PAD
    parts.append(_target_table_box(mapping, tgt_fields, TGT_X, tgt_top, verify))

    tgt_row_centers: List[Tuple[int, int]] = []
    for i in range(len(tgt_fields)):
        cy = tgt_top + HDR_H + i * ROW_H + ROW_H // 2
        tgt_row_centers.append((TGT_X, cy))

    # ── Connector lines ───────────────────────────────────────────────────────
    import re as _re
    for i, fm in enumerate(tgt_fields):
        tx, ty = tgt_row_centers[i]
        refs = _re.findall(
            r'\b([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)\b',
            fm.source_expression or ""
        )
        drawn = False
        for alias, _ in refs:
            centers = src_row_centers.get(alias, [])
            if not centers:
                continue
            # Pick the closest source row to the target row
            sx, sy = min(centers, key=lambda c: abs(c[1] - ty))
            has_tx = _is_transformed(fm.source_expression, fm.target_field)
            parts.append(_connector(sx, sy, tx, ty, fm, has_tx))
            drawn = True
            break
        if not drawn:
            # Computed field — draw a dashed line from the midpoint
            mid_x = SRC_X + SRC_W
            mid_y = TOP_PAD + body_h // 2
            parts.append(_connector(mid_x, mid_y, tx, ty, fm, True, dashed=True))

    # ── Business rules & filters ──────────────────────────────────────────────
    rules_y = TOP_PAD + body_h + 24
    parts.append(_rules_panel(biz_rules, filters, MARGIN, rules_y))

    # ── Legend ────────────────────────────────────────────────────────────────
    parts.append(_legend(W - 320, rules_y))

    # ── Verification overlay ──────────────────────────────────────────────────
    if verify and not verify.is_clean:
        parts.append(_verify_overlay(verify, W - 320, TOP_PAD + 10))

    parts.append("</svg>")
    return "\n".join(parts)


# ── SVG component builders ────────────────────────────────────────────────────

def _defs() -> str:
    return """
<defs>
  <filter id="shadow" x="-4%" y="-4%" width="108%" height="108%">
    <feDropShadow dx="0" dy="2" stdDeviation="4" flood-color="#00000014"/>
  </filter>
  <marker id="arrow" markerWidth="8" markerHeight="8"
          refX="6" refY="3" orient="auto">
    <path d="M0,0 L0,6 L8,3 z" fill="#94A3B8"/>
  </marker>
  <marker id="arrow-tx" markerWidth="8" markerHeight="8"
          refX="6" refY="3" orient="auto">
    <path d="M0,0 L0,6 L8,3 z" fill="#F97316"/>
  </marker>
  <style>
    text { font-size: 12px; }
    .tbl-hdr { font-size: 13px; font-weight: 600; }
    .field-name { font-size: 11.5px; }
    .field-type { font-size: 10px; fill: #64748B; }
    .pii-label  { font-size: 9px;  fill: #EF4444; font-weight: 700; }
    .tx-label   { font-size: 10px; fill: #EA580C; }
    .rule-text  { font-size: 11px; fill: #92400E; }
    .meta-text  { font-size: 11px; fill: #475569; }
    .badge      { font-size: 10px; font-weight: 600; }
  </style>
</defs>"""


def _header_bar(m: Any) -> str:
    jira  = html.escape(m.jira_issue)
    ds    = html.escape(f"{m.target_dataset}.{m.target_table}")
    mid   = html.escape(m.mapping_id)
    strat = html.escape(m.idempotency_strategy.value)
    n_src = len(m.source_tables)
    n_fld = len(m.field_mappings)
    otypes = html.escape(", ".join(o.value for o in m.output_types))

    return f"""
<rect x="0" y="0" width="{W}" height="82" fill="{COLORS['hdr_bg']}"/>
<text x="{MARGIN}" y="32" font-size="20" font-weight="700"
      fill="{COLORS['hdr_txt']}">Data Mapping Workflow</text>
<text x="{MARGIN}" y="54" font-size="13" fill="#94A3B8">
  Mapping ID: {mid}  ·  Jira: {jira}  ·  Target: {ds}
</text>
<text x="{MARGIN}" y="72" font-size="12" fill="#64748B">
  Sources: {n_src}  ·  Fields: {n_fld}  ·  Strategy: {strat}  ·  Outputs: {otypes}
</text>"""


def _metadata_bar(m: Any, verify: Optional[Any]) -> str:
    pii_count = sum(1 for f in m.field_mappings if f.is_pii)
    sched  = html.escape(m.schedule or "on-demand")
    owner  = html.escape(m.data_owner or "—")
    steward= html.escape(m.data_steward or "—")

    verify_txt = ""
    if verify:
        color = COLORS["verify_ok"] if verify.is_clean else COLORS["verify_err"]
        msg   = "Schema ✓" if verify.is_clean else f"⚠ {len(verify.missing_fields)} missing"
        verify_txt = f"""
<rect x="{W-220}" y="84" width="168" height="22" rx="4"
      fill="{color}"/>
<text x="{W-136}" y="99" text-anchor="middle" class="badge"
      fill="{'#065F46' if verify.is_clean else '#991B1B'}">{html.escape(msg)}</text>"""

    return f"""
<rect x="0" y="82" width="{W}" height="30" fill="#F1F5F9"
      style="border-bottom:1px solid #E2E8F0"/>
<text x="{MARGIN}" y="102" class="meta-text">
  Owner: {owner}  ·  Steward: {steward}  ·  Schedule: {sched}  ·  PII fields: {pii_count}
</text>{verify_txt}"""


def _source_table_box(tbl: Any, fields: List, x: int, y: int) -> str:
    alias = html.escape(tbl.alias)
    name  = html.escape(f"{tbl.dataset}.{tbl.table}")
    join  = html.escape(f"  ({tbl.join_type} JOIN)" if tbl.join_type else "")
    n     = len(fields)
    h     = HDR_H + n * ROW_H + TBL_PAD

    parts = [
        f'<g filter="url(#shadow)">',
        f'<rect x="{x}" y="{y}" width="{SRC_W}" height="{h}" rx="8" '
        f'fill="white" stroke="{COLORS["src_border"]}" stroke-width="1.5"/>',
        # Header
        f'<rect x="{x}" y="{y}" width="{SRC_W}" height="{HDR_H}" rx="8" '
        f'fill="{COLORS["src_hdr"]}"/>',
        f'<rect x="{x}" y="{y+HDR_H-8}" width="{SRC_W}" height="8" '
        f'fill="{COLORS["src_hdr"]}"/>',
        f'<text x="{x+TBL_PAD}" y="{y+22}" class="tbl-hdr" '
        f'fill="{COLORS["src_hdr_txt"]}">{alias}</text>',
        f'<text x="{x+TBL_PAD}" y="{y+38}" font-size="10" '
        f'fill="#BFDBFE">{name}{join}</text>',
    ]

    for i, fm in enumerate(fields):
        ry = y + HDR_H + i * ROW_H
        bg = COLORS["pii_bg"] if (fm and fm.is_pii) else (
            COLORS["src_row"] if i % 2 == 0 else "white"
        )
        parts.append(
            f'<rect x="{x+1}" y="{ry}" width="{SRC_W-2}" height="{ROW_H}" fill="{bg}"/>'
        )
        if fm:
            # Extract source column name from expression
            import re as _re
            refs = _re.findall(r'\b\w+\.(\w+)\b', fm.source_expression or "")
            col_name = html.escape(refs[0] if refs else fm.source_expression[:28])
            f_type   = html.escape(fm.data_type[:12])
            label    = f'<text x="{x+TBL_PAD}" y="{ry+ROW_H-10}" class="field-name" fill="#1E40AF">{col_name}</text>'
            type_lbl = f'<text x="{x+SRC_W-TBL_PAD-50}" y="{ry+ROW_H-10}" class="field-type" text-anchor="end">{f_type}</text>'
            parts += [label, type_lbl]
            if fm.is_pii:
                parts.append(
                    f'<circle cx="{x+SRC_W-8}" cy="{ry+ROW_H//2}" r="4" fill="{COLORS["pii_dot"]}"/>'
                )

    bottom_y = y + HDR_H + n * ROW_H
    parts.append(
        f'<line x1="{x}" y1="{bottom_y}" x2="{x+SRC_W}" y2="{bottom_y}" '
        f'stroke="{COLORS["src_border"]}" stroke-width="1"/>'
    )
    parts.append("</g>")
    return "\n".join(parts)


def _target_table_box(
    mapping: Any,
    fields: List,
    x: int,
    y: int,
    verify: Optional[Any],
) -> str:
    name  = html.escape(f"{mapping.target_dataset}.{mapping.target_table}")
    n     = len(fields)
    h     = HDR_H + n * ROW_H + TBL_PAD

    # Build set of missing target fields for red highlighting
    missing_targets = set()
    if verify:
        for mf in verify.missing_fields:
            missing_targets.add(mf.get("target_field", ""))

    parts = [
        f'<g filter="url(#shadow)">',
        f'<rect x="{x}" y="{y}" width="{TGT_W}" height="{h}" rx="8" '
        f'fill="white" stroke="{COLORS["tgt_border"]}" stroke-width="1.5"/>',
        # Header
        f'<rect x="{x}" y="{y}" width="{TGT_W}" height="{HDR_H}" rx="8" '
        f'fill="{COLORS["tgt_hdr"]}"/>',
        f'<rect x="{x}" y="{y+HDR_H-8}" width="{TGT_W}" height="8" '
        f'fill="{COLORS["tgt_hdr"]}"/>',
        f'<text x="{x+TBL_PAD}" y="{y+22}" class="tbl-hdr" '
        f'fill="{COLORS["tgt_hdr_txt"]}">TARGET</text>',
        f'<text x="{x+TBL_PAD}" y="{y+38}" font-size="10" '
        f'fill="#A7F3D0">{name}</text>',
    ]

    # Partition / cluster badges
    bx = x + TGT_W - TBL_PAD
    if mapping.partition_field:
        pf = html.escape(f"PARTITION: {mapping.partition_field}")
        parts.append(
            f'<rect x="{x+TBL_PAD}" y="{y+HDR_H+4}" width="130" height="16" '
            f'rx="3" fill="#D1FAE5"/>'
            f'<text x="{x+TBL_PAD+4}" y="{y+HDR_H+15}" font-size="9" fill="#065F46">{pf}</text>'
        )

    for i, fm in enumerate(fields):
        ry  = y + HDR_H + i * ROW_H
        err = fm.target_field in missing_targets
        bg  = COLORS["miss_row"] if err else (
            COLORS["pii_bg"] if fm.is_pii else (
                COLORS["tgt_row"] if i % 2 == 0 else "white"
            )
        )
        parts.append(
            f'<rect x="{x+1}" y="{ry}" width="{TGT_W-2}" height="{ROW_H}" fill="{bg}"/>'
        )
        fname    = html.escape(fm.target_field[:28])
        f_type   = html.escape(fm.data_type[:14])
        nullable = "" if fm.nullable else " NOT NULL"
        desc     = html.escape((fm.description or "")[:32])

        parts.append(
            f'<text x="{x+TBL_PAD}" y="{ry+ROW_H-10}" class="field-name" '
            f'fill="{"#991B1B" if err else "#065F46"}">{fname}</text>'
        )
        parts.append(
            f'<text x="{x+TGT_W-TBL_PAD}" y="{ry+ROW_H-10}" class="field-type" '
            f'text-anchor="end" fill="#6B7280">{f_type}{nullable}</text>'
        )
        if fm.is_pii:
            parts.append(
                f'<circle cx="{x+TGT_W-8}" cy="{ry+ROW_H//2}" r="4" '
                f'fill="{COLORS["pii_dot"]}"/>'
            )
        if desc:
            parts.append(
                f'<text x="{x+TBL_PAD+130}" y="{ry+ROW_H-10}" '
                f'font-size="9" fill="#9CA3AF">{desc}</text>'
            )

    parts.append("</g>")
    return "\n".join(parts)


def _connector(
    sx: int, sy: int,
    tx: int, ty: int,
    fm: Any,
    is_transformed: bool,
    dashed: bool = False,
) -> str:
    color  = COLORS["line_tx"] if is_transformed else COLORS["line"]
    marker = "arrow-tx" if is_transformed else "arrow"
    dash   = 'stroke-dasharray="5,4"' if dashed else ""

    # Cubic bezier control points
    dx = abs(tx - sx)
    cp1x = sx + dx * 0.55
    cp2x = tx - dx * 0.55
    d    = f"M{sx},{sy} C{cp1x},{sy} {cp2x},{ty} {tx},{ty}"

    parts = [
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5" '
        f'opacity="0.6" marker-end="url(#{marker})" {dash}/>'
    ]

    # Transformation label at midpoint
    if is_transformed and fm:
        expr = html.escape(_shorten(fm.source_expression, 28))
        mid_x = (sx + tx) // 2
        mid_y = (sy + ty) // 2 - 6
        parts.append(
            f'<rect x="{mid_x-2}" y="{mid_y-12}" width="{len(expr)*6+8}" '
            f'height="15" rx="3" fill="#FFF7ED" opacity="0.9"/>'
        )
        parts.append(
            f'<text x="{mid_x+2}" y="{mid_y}" class="tx-label">{expr}</text>'
        )

    return "\n".join(parts)


def _rules_panel(rules: List[str], filters: List[str], x: int, y: int) -> str:
    all_items = [f"FILTER: {f}" for f in filters] + rules
    h = max(60, 30 + len(all_items) * 18 + 12)
    w = TGT_X - MARGIN - 20

    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
        f'fill="{COLORS["rule_bg"]}" stroke="{COLORS["rule_border"]}" stroke-width="1.2"/>',
        f'<text x="{x+12}" y="{y+20}" font-size="12" font-weight="700" fill="#92400E">'
        f'Business Rules &amp; Filters ({len(all_items)})</text>',
    ]
    for i, rule in enumerate(all_items[:12]):
        ry = y + 36 + i * 18
        dot_color = "#3B82F6" if rule.startswith("FILTER") else "#F59E0B"
        parts.append(
            f'<circle cx="{x+16}" cy="{ry-4}" r="3" fill="{dot_color}"/>'
            f'<text x="{x+26}" y="{ry}" class="rule-text">{html.escape(rule[:80])}</text>'
        )
    if len(all_items) > 12:
        parts.append(
            f'<text x="{x+26}" y="{y+36+12*18}" class="rule-text" fill="#A16207">'
            f'… and {len(all_items)-12} more</text>'
        )
    return "\n".join(parts)


def _legend(x: int, y: int) -> str:
    items = [
        (COLORS["src_hdr"],  "Source table"),
        (COLORS["tgt_hdr"],  "Target table"),
        (COLORS["line"],     "Direct mapping"),
        (COLORS["line_tx"],  "Transformed mapping"),
        (COLORS["pii_dot"],  "PII field"),
        (COLORS["miss_row"], "Missing / unverified field"),
    ]
    h = 30 + len(items) * 22 + 12
    parts = [
        f'<rect x="{x}" y="{y}" width="290" height="{h}" rx="8" '
        f'fill="{COLORS["legend_bg"]}" stroke="#CBD5E1" stroke-width="1"/>',
        f'<text x="{x+12}" y="{y+20}" font-size="12" font-weight="700" fill="#334155">Legend</text>',
    ]
    for i, (color, label) in enumerate(items):
        iy = y + 36 + i * 22
        parts.append(
            f'<rect x="{x+12}" y="{iy-10}" width="16" height="14" rx="3" fill="{color}"/>'
            f'<text x="{x+36}" y="{iy}" font-size="11" fill="#475569">{html.escape(label)}</text>'
        )
    return "\n".join(parts)


def _verify_overlay(verify: Any, x: int, y: int) -> str:
    items  = verify.missing_fields[:8]
    h      = 28 + max(1, len(items)) * 18 + 12
    parts  = [
        f'<rect x="{x}" y="{y}" width="290" height="{h}" rx="8" '
        f'fill="{COLORS["verify_err"]}" stroke="#FCA5A5" stroke-width="1.2"/>',
        f'<text x="{x+12}" y="{y+20}" font-size="12" font-weight="700" fill="#991B1B">'
        f'⚠ Schema Verification Issues</text>',
    ]
    for i, mf in enumerate(items):
        iy = y + 34 + i * 18
        ref = html.escape(f"{mf.get('table','?')}.{mf.get('field','?')}")
        tgt = html.escape(mf.get('target_field', ''))
        parts.append(
            f'<text x="{x+14}" y="{iy}" font-size="10" fill="#7F1D1D">'
            f'Missing: {ref} → {tgt}</text>'
        )
    if len(verify.missing_fields) > 8:
        parts.append(
            f'<text x="{x+14}" y="{y+34+8*18}" font-size="10" fill="#991B1B">'
            f'… and {len(verify.missing_fields)-8} more</text>'
        )
    return "\n".join(parts)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_transformed(expr: str, target_field: str) -> bool:
    """True if the expression is more than just 'alias.column'."""
    import re
    return bool(re.search(r'[()\[\]{}]|CAST|COALESCE|IF|CASE|DATE|FORMAT|LOWER|UPPER|TRIM', expr, re.I))


def _shorten(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"
