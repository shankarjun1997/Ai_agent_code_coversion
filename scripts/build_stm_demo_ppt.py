"""Generate the STM Agentic Evolution demo deck (docs/STM_Agentic_Demo.pptx)."""
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

# Palette
INK = RGBColor(0x0F, 0x17, 0x2A)
MUTED = RGBColor(0x5B, 0x67, 0x82)
ACCENT = RGBColor(0x2A, 0x6D, 0xF4)
ACCENT_DARK = RGBColor(0x16, 0x3F, 0x9F)
GREEN = RGBColor(0x16, 0xA3, 0x4A)
AMBER = RGBColor(0xE0, 0x8E, 0x0B)
RED = RGBColor(0xDC, 0x26, 0x26)
BG = RGBColor(0xF7, 0xF8, 0xFC)
CARD = RGBColor(0xFF, 0xFF, 0xFF)
RULE = RGBColor(0xE2, 0xE6, 0xEF)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def new_deck() -> Presentation:
    p = Presentation()
    p.slide_width = SLIDE_W
    p.slide_height = SLIDE_H
    return p


def blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def fill(shape, color: RGBColor):
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()


def outline(shape, color: RGBColor, weight=0.75):
    shape.line.color.rgb = color
    shape.line.width = Pt(weight)


def add_rect(slide, x, y, w, h, color):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    fill(s, color)
    return s


def add_round(slide, x, y, w, h, color, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    s.adjustments[0] = 0.12
    fill(s, color)
    if line is None:
        s.line.fill.background()
    else:
        outline(s, line, 0.75)
    return s


def add_text(slide, x, y, w, h, text, *, size=14, bold=False, color=INK,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, font="Inter"):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    tf.vertical_anchor = anchor
    lines = text.split("\n") if isinstance(text, str) else text
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.name = font
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
    return tb


def add_bullets(slide, x, y, w, h, items, *, size=14, color=INK, bullet="•"):
    text = "\n".join(f"{bullet}  {it}" for it in items)
    return add_text(slide, x, y, w, h, text, size=size, color=color)


def page_chrome(slide, eyebrow: str, title: str, page_num: int, total: int):
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, BG)
    # top bar
    add_rect(slide, 0, 0, SLIDE_W, Inches(0.08), ACCENT)
    add_text(slide, Inches(0.6), Inches(0.32), Inches(8), Inches(0.3),
             eyebrow.upper(), size=10, bold=True, color=ACCENT_DARK)
    add_text(slide, Inches(0.6), Inches(0.55), Inches(12), Inches(0.7),
             title, size=28, bold=True, color=INK)
    add_text(slide, Inches(11.5), Inches(0.32), Inches(1.3), Inches(0.3),
             f"{page_num:02d} / {total:02d}", size=10, bold=True,
             color=MUTED, align=PP_ALIGN.RIGHT)
    # divider
    add_rect(slide, Inches(0.6), Inches(1.25), Inches(12.13), Emu(9525), RULE)


def footer(slide, label: str):
    add_text(slide, Inches(0.6), Inches(7.05), Inches(8), Inches(0.3),
             label, size=9, color=MUTED)
    add_text(slide, Inches(11.5), Inches(7.05), Inches(1.3), Inches(0.3),
             "sql gen v2  •  STM agentic", size=9, color=MUTED,
             align=PP_ALIGN.RIGHT)


# ----- Slides ---------------------------------------------------------------

TOTAL = 12  # will sync after building list


def slide_title(prs):
    s = blank(prs)
    add_rect(s, 0, 0, SLIDE_W, SLIDE_H, INK)
    # accent band
    add_rect(s, 0, Inches(3.4), SLIDE_W, Inches(0.05), ACCENT)
    add_text(s, Inches(0.8), Inches(2.4), Inches(10), Inches(0.4),
             "SQL-GEN V2  •  TEAM DEMO", size=12, bold=True,
             color=RGBColor(0x9A, 0xB3, 0xE8))
    add_text(s, Inches(0.8), Inches(2.8), Inches(12), Inches(0.9),
             "STM Mapping Agent", size=44, bold=True,
             color=RGBColor(0xFF, 0xFF, 0xFF))
    add_text(s, Inches(0.8), Inches(3.7), Inches(12), Inches(0.7),
             "From prompt-to-Excel to a six-layer reasoning pipeline.",
             size=22, color=RGBColor(0xC9, 0xD3, 0xEC))
    add_text(s, Inches(0.8), Inches(4.45), Inches(12), Inches(0.5),
             "Progressive certainty  ·  human governance  ·  zero regressions",
             size=14, color=RGBColor(0x9A, 0xB3, 0xE8))
    # bottom meta
    add_text(s, Inches(0.8), Inches(6.6), Inches(8), Inches(0.3),
             "15-minute walkthrough  ·  v1 ships on feat/stm-agentic-evolution",
             size=11, color=RGBColor(0x6F, 0x83, 0xB0))
    add_text(s, Inches(10), Inches(6.6), Inches(3), Inches(0.3),
             "2026-05-13", size=11, color=RGBColor(0x6F, 0x83, 0xB0),
             align=PP_ALIGN.RIGHT)


def slide_tldr(prs, n, total):
    s = blank(prs)
    page_chrome(s, "TL;DR", "Excel is the rendered view. The blackboard is the product.", n, total)
    # quote card
    card = add_round(s, Inches(0.8), Inches(1.7), Inches(11.7), Inches(2.0),
                     CARD, line=RULE)
    add_text(s, Inches(1.2), Inches(1.95), Inches(11), Inches(1.5),
             "“Until last week, STM was: prompt → Excel.\n"
             "Now it's a six-stage reasoning pipeline where each stage hands a richer, "
             "more confident artifact to the next — with two human checkpoints.”",
             size=18, color=INK)
    add_text(s, Inches(1.2), Inches(3.25), Inches(11), Inches(0.3),
             "The blackboard IS the product.", size=13, bold=True, color=ACCENT_DARK)

    # three pillars
    pillars = [
        ("No regressions", "POST /api/stm/generate still serves the rule-based path. Every existing demo keeps working.", GREEN),
        ("Progressive certainty", "Each layer enriches the blackboard, raises confidence, hands a more structured artifact forward.", ACCENT),
        ("Governance built-in", "Two gates. Approve / Reject / Refine. Refinement marks downstream stale and reruns.", AMBER),
    ]
    x = Inches(0.8)
    for title, body, color in pillars:
        card = add_round(s, x, Inches(4.0), Inches(3.9), Inches(2.6), CARD, line=RULE)
        add_rect(s, x, Inches(4.0), Inches(0.1), Inches(2.6), color)
        add_text(s, x + Inches(0.3), Inches(4.2), Inches(3.5), Inches(0.5),
                 title, size=16, bold=True, color=INK)
        add_text(s, x + Inches(0.3), Inches(4.75), Inches(3.5), Inches(1.7),
                 body, size=12, color=MUTED)
        x += Inches(4.0)
    footer(s, "TL;DR for the room")


def stage_card(slide, x, y, w, h, code, name, sub, model, color):
    add_round(slide, x, y, w, h, CARD, line=RULE)
    add_rect(slide, x, y, Inches(0.1), h, color)
    add_text(slide, x + Inches(0.25), y + Inches(0.18), Inches(0.9), Inches(0.4),
             code, size=14, bold=True, color=color)
    add_text(slide, x + Inches(1.05), y + Inches(0.18), w - Inches(1.2), Inches(0.4),
             name, size=14, bold=True, color=INK)
    add_text(slide, x + Inches(0.25), y + Inches(0.7), w - Inches(0.4), h - Inches(1.0),
             sub, size=11, color=MUTED)
    add_text(slide, x + Inches(0.25), y + h - Inches(0.45), w - Inches(0.4), Inches(0.3),
             model, size=9, bold=True, color=ACCENT_DARK)


def slide_six_layers(prs, n, total):
    s = blank(prs)
    page_chrome(s, "The pipeline", "Six layers. Each one raises certainty.", n, total)
    layers = [
        ("L1", "Intent Extraction", "Jira / free-text → structured business intent.", "Haiku", ACCENT),
        ("L2", "Metadata Intelligence", "Parallel probe across all source DBs; build a knowledge graph.", "Sonnet", ACCENT),
        ("L3", "Semantic Mapping", "Rule baseline + LLM refinement → candidate field mappings.", "Opus + rules", ACCENT_DARK),
        ("L4", "Transformation Synthesis", "SCD, audit columns, derived fields, idempotency.", "Opus", ACCENT_DARK),
        ("L5", "Validation & Governance", "Deterministic confidence scoring + rule-based findings.", "Deterministic", AMBER),
        ("L6", "STM Generation", "Compose MappingResult → render xlsx / csv.", "Deterministic", GREEN),
    ]
    cols = 3
    cw = Inches(4.0)
    ch = Inches(2.5)
    x0 = Inches(0.8)
    y0 = Inches(1.55)
    for i, (code, name, sub, model, color) in enumerate(layers):
        r, c = divmod(i, cols)
        x = x0 + c * (cw + Inches(0.1))
        y = y0 + r * (ch + Inches(0.15))
        stage_card(s, x, y, cw, ch, code, name, sub, model, color)
    footer(s, "core/stm/agents/L1…L6")


def slide_gates(prs, n, total):
    s = blank(prs)
    page_chrome(s, "Human governance", "Two gates, three decisions.", n, total)

    # gate panels
    gate_specs = [
        ("Gate 1", "after L2 — Metadata", AMBER,
         "Review the metadata graph before the LLM reasons about it.",
         "Highest ambiguity. Cheapest place to course-correct."),
        ("Gate 2", "after L5 — Validation", RED,
         "Review the confidence band and rule findings before shipping.",
         "Highest stakes. Last checkpoint before xlsx render."),
    ]
    for i, (title, sub, color, body, why) in enumerate(gate_specs):
        x = Inches(0.8) + i * Inches(6.1)
        add_round(s, x, Inches(1.55), Inches(5.95), Inches(2.9), CARD, line=RULE)
        add_rect(s, x, Inches(1.55), Inches(0.12), Inches(2.9), color)
        add_text(s, x + Inches(0.35), Inches(1.75), Inches(4), Inches(0.4),
                 title, size=20, bold=True, color=INK)
        add_text(s, x + Inches(0.35), Inches(2.15), Inches(5), Inches(0.4),
                 sub, size=12, bold=True, color=color)
        add_text(s, x + Inches(0.35), Inches(2.55), Inches(5.3), Inches(0.9),
                 body, size=13, color=INK)
        add_text(s, x + Inches(0.35), Inches(3.55), Inches(5.3), Inches(0.8),
                 "Why here  ·  " + why, size=11, color=MUTED)

    # decisions row
    decisions = [
        ("Approve", GREEN, "Stage stays ready. Pipeline advances."),
        ("Reject", RED, "Session terminates with reason. Clone to retry."),
        ("Refine", AMBER, "Target a stage + free-text feedback. Downstream marked stale; reruns."),
    ]
    for i, (lbl, color, body) in enumerate(decisions):
        x = Inches(0.8) + i * Inches(4.1)
        add_round(s, x, Inches(4.75), Inches(4.0), Inches(1.85), CARD, line=RULE)
        add_round(s, x + Inches(0.3), Inches(5.0), Inches(1.3), Inches(0.45), color)
        add_text(s, x + Inches(0.3), Inches(5.04), Inches(1.3), Inches(0.4),
                 lbl, size=12, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF),
                 align=PP_ALIGN.CENTER)
        add_text(s, x + Inches(0.3), Inches(5.6), Inches(3.6), Inches(1.1),
                 body, size=12, color=MUTED)
    footer(s, "asyncio.Event stalls — gates are the steering wheel, not blockers")


def slide_blackboard(prs, n, total):
    s = blank(prs)
    page_chrome(s, "Mental model", "Stage-as-agent. Shared blackboard.", n, total)

    # central blackboard
    bb_x, bb_y, bb_w, bb_h = Inches(4.5), Inches(2.9), Inches(4.3), Inches(2.4)
    add_round(s, bb_x, bb_y, bb_w, bb_h, INK)
    add_text(s, bb_x, bb_y + Inches(0.3), bb_w, Inches(0.5),
             "BLACKBOARD", size=12, bold=True,
             color=RGBColor(0x9A, 0xB3, 0xE8), align=PP_ALIGN.CENTER)
    add_text(s, bb_x, bb_y + Inches(0.75), bb_w, Inches(0.5),
             "stm_sessions.blackboard_json", size=16, bold=True,
             color=RGBColor(0xFF, 0xFF, 0xFF), align=PP_ALIGN.CENTER)
    add_text(s, bb_x + Inches(0.3), bb_y + Inches(1.25), bb_w - Inches(0.6), Inches(1.0),
             "intent  ·  metadata graph  ·  mappings  ·  transforms  ·  validation  ·  artifacts",
             size=11, color=RGBColor(0xC9, 0xD3, 0xEC), align=PP_ALIGN.CENTER)

    # orbiting agents
    agents = [
        ("L1", Inches(0.9), Inches(1.7), ACCENT),
        ("L2", Inches(0.9), Inches(3.5), ACCENT),
        ("L3", Inches(0.9), Inches(5.3), ACCENT_DARK),
        ("L4", Inches(11.1), Inches(1.7), ACCENT_DARK),
        ("L5", Inches(11.1), Inches(3.5), AMBER),
        ("L6", Inches(11.1), Inches(5.3), GREEN),
    ]
    for code, x, y, color in agents:
        add_round(s, x, y, Inches(1.4), Inches(1.0), CARD, line=RULE)
        add_rect(s, x, y, Inches(0.1), Inches(1.0), color)
        add_text(s, x + Inches(0.2), y + Inches(0.2), Inches(1.1), Inches(0.4),
                 code, size=18, bold=True, color=color)
        add_text(s, x + Inches(0.2), y + Inches(0.55), Inches(1.1), Inches(0.4),
                 "agent", size=10, color=MUTED)

    # bottom note
    add_round(s, Inches(0.8), Inches(5.8), Inches(11.7), Inches(0.9), CARD, line=RULE)
    add_text(s, Inches(1.0), Inches(5.95), Inches(11.3), Inches(0.6),
             "Every agent reads from and writes to the blackboard.  "
             "Crash mid-run? `_recover_stm_sessions()` resumes from persisted state.  "
             "Reload mid-stage? SSE replays from DB then tails live.",
             size=12, color=INK)
    footer(s, "core/stm/blackboard.py  ·  core/stm/coordinator.py")


def slide_demo_flow(prs, n, total):
    s = blank(prs)
    page_chrome(s, "Demo flow", "Four acts. ~15 minutes.", n, total)
    acts = [
        ("Act 1",  "What we had", "1 min",
         "Tab A — `/mapping_compose_react.html`. Pick profile → schema → columns → Generate STM. Excel downloads. No regressions."),
        ("Act 2",  "What we built", "8 min",
         "Tab B — `?mode=agentic`. Start session → watch L1→L6 over SSE → Gate 1 refine → flow to L5 → Gate 2 approve → download xlsx."),
        ("Act 3",  "What's underneath", "3 min",
         "Persisted blackboard, crash recovery, SSE replay, clone & retry, Jira write-back on session_done."),
        ("Act 4",  "Why this matters", "2 min",
         "No regressions. Progressive certainty. Governance built-in. Excel is the rendered view; blackboard is the product."),
    ]
    y = Inches(1.55)
    for label, name, dur, body in acts:
        add_round(s, Inches(0.8), y, Inches(11.7), Inches(1.25), CARD, line=RULE)
        add_round(s, Inches(1.0), y + Inches(0.25), Inches(1.0), Inches(0.75), ACCENT)
        add_text(s, Inches(1.0), y + Inches(0.32), Inches(1.0), Inches(0.6),
                 label, size=14, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF),
                 align=PP_ALIGN.CENTER)
        add_text(s, Inches(2.3), y + Inches(0.2), Inches(7), Inches(0.5),
                 name, size=16, bold=True, color=INK)
        add_text(s, Inches(11), y + Inches(0.22), Inches(1.4), Inches(0.4),
                 dur, size=11, bold=True, color=MUTED, align=PP_ALIGN.RIGHT)
        add_text(s, Inches(2.3), y + Inches(0.65), Inches(10), Inches(0.55),
                 body, size=11, color=MUTED)
        y += Inches(1.35)
    footer(s, "docs/STM_AGENTIC_DEMO.md")


def slide_session_start(prs, n, total):
    s = blank(prs)
    page_chrome(s, "Act 2 — open the agentic UI", "One intent. Many sources. Governed pipeline.", n, total)
    # left: form mock
    add_round(s, Inches(0.8), Inches(1.55), Inches(6.5), Inches(5.0), CARD, line=RULE)
    add_text(s, Inches(1.0), Inches(1.75), Inches(6), Inches(0.4),
             "Create agentic session", size=16, bold=True, color=INK)
    fields = [
        ("Target table", "fact_customer_360"),
        ("Target dataset", "analytics_warehouse"),
        ("Sources", "pg-demo  (live Postgres profile)"),
        ("Intent source", "Free text"),
        ("Describe", "Load customer 360 dimension from CRM into BigQuery, daily refresh, mask PII"),
    ]
    y = Inches(2.3)
    for k, v in fields:
        add_text(s, Inches(1.0), y, Inches(2.4), Inches(0.3),
                 k, size=11, bold=True, color=MUTED)
        add_round(s, Inches(3.3), y - Inches(0.05), Inches(3.85), Inches(0.4),
                  BG, line=RULE)
        add_text(s, Inches(3.45), y, Inches(3.6), Inches(0.3),
                 v, size=11, color=INK)
        y += Inches(0.55)
    add_round(s, Inches(1.0), Inches(5.7), Inches(2.0), Inches(0.55), ACCENT)
    add_text(s, Inches(1.0), Inches(5.78), Inches(2.0), Inches(0.4),
             "Start session", size=12, bold=True,
             color=RGBColor(0xFF, 0xFF, 0xFF), align=PP_ALIGN.CENTER)

    # right: messages
    add_round(s, Inches(7.5), Inches(1.55), Inches(5.0), Inches(5.0), CARD, line=RULE)
    add_text(s, Inches(7.7), Inches(1.75), Inches(4.6), Inches(0.4),
             "What the room hears", size=16, bold=True, color=INK)
    msgs = [
        ("Intent", "Plain English about the load and the policy (PII masking, cadence)."),
        ("Sources", "Multi-dialect: Postgres, Oracle, MySQL, MSSQL, BigQuery."),
        ("Target", "BigQuery dataset + table."),
        ("Then", "L1 runs in ~1s.  L2 fans out and probes every source.  Stepper turns live."),
    ]
    y = Inches(2.25)
    for k, v in msgs:
        add_text(s, Inches(7.7), y, Inches(4.6), Inches(0.3),
                 k, size=12, bold=True, color=ACCENT_DARK)
        add_text(s, Inches(7.7), y + Inches(0.3), Inches(4.6), Inches(0.8),
                 v, size=11, color=MUTED)
        y += Inches(1.05)
    footer(s, "ui/mapping_compose_react.html — AgenticApp")


def slide_gate_walk(prs, n, total):
    s = blank(prs)
    page_chrome(s, "Gates in motion", "Refine is the loop. Approve is the release.", n, total)
    # stepper
    steps = [
        ("L1", "ready", GREEN),
        ("L2", "awaiting_review", AMBER),
        ("L3", "running", ACCENT),
        ("L4", "queued", MUTED),
        ("L5", "queued", MUTED),
        ("L6", "queued", MUTED),
    ]
    x = Inches(0.8)
    for code, status, color in steps:
        add_round(s, x, Inches(1.55), Inches(1.9), Inches(1.1), CARD, line=RULE)
        add_rect(s, x, Inches(1.55), Inches(0.08), Inches(1.1), color)
        add_text(s, x + Inches(0.2), Inches(1.7), Inches(1.7), Inches(0.4),
                 code, size=16, bold=True, color=INK)
        add_text(s, x + Inches(0.2), Inches(2.1), Inches(1.7), Inches(0.4),
                 status, size=10, bold=True, color=color)
        x += Inches(2.02)

    # gate panel mock
    add_round(s, Inches(0.8), Inches(3.0), Inches(7.5), Inches(3.5), CARD, line=RULE)
    add_rect(s, Inches(0.8), Inches(3.0), Inches(0.12), Inches(3.5), AMBER)
    add_text(s, Inches(1.05), Inches(3.15), Inches(7), Inches(0.4),
             "Gate 1 — Metadata review", size=16, bold=True, color=INK)
    add_text(s, Inches(1.05), Inches(3.55), Inches(7), Inches(0.4),
             "Reviewer  shankar@example.com", size=11, color=MUTED)
    add_text(s, Inches(1.05), Inches(4.0), Inches(7), Inches(0.4),
             "Refine target", size=11, bold=True, color=ACCENT_DARK)
    add_round(s, Inches(1.05), Inches(4.3), Inches(1.1), Inches(0.4), BG, line=RULE)
    add_text(s, Inches(1.15), Inches(4.36), Inches(1.0), Inches(0.3),
             "L2", size=11, bold=True, color=INK)
    add_text(s, Inches(1.05), Inches(4.85), Inches(7), Inches(0.4),
             "Feedback", size=11, bold=True, color=ACCENT_DARK)
    add_round(s, Inches(1.05), Inches(5.15), Inches(7), Inches(0.6), BG, line=RULE)
    add_text(s, Inches(1.15), Inches(5.25), Inches(6.8), Inches(0.4),
             "“only the public schema is in scope”", size=11, color=INK)
    # buttons
    for i, (lbl, color) in enumerate([("Reject", RED), ("Refine", AMBER), ("Approve", GREEN)]):
        bx = Inches(1.05) + i * Inches(1.5)
        add_round(s, bx, Inches(5.95), Inches(1.4), Inches(0.45), color)
        add_text(s, bx, Inches(6.0), Inches(1.4), Inches(0.4),
                 lbl, size=11, bold=True,
                 color=RGBColor(0xFF, 0xFF, 0xFF), align=PP_ALIGN.CENTER)

    # right: explainer
    add_round(s, Inches(8.5), Inches(3.0), Inches(4.0), Inches(3.5), CARD, line=RULE)
    add_text(s, Inches(8.7), Inches(3.15), Inches(3.7), Inches(0.4),
             "What happens", size=14, bold=True, color=INK)
    add_bullets(s, Inches(8.7), Inches(3.55), Inches(3.7), Inches(2.9), [
        "Refine → L2 reruns",
        "Downstream marked stale",
        "Stepper turns L2 amber → blue → green",
        "Second pass: Approve",
        "Pipeline advances to L3",
    ], size=11, color=MUTED)
    footer(s, "routers/stm_sessions.py — decide_gate")


def slide_l3_l5(prs, n, total):
    s = blank(prs)
    page_chrome(s, "L3 → L5", "Rules-as-floor. LLM-on-top. Confidence at the seam.", n, total)
    # L3 card
    add_round(s, Inches(0.8), Inches(1.55), Inches(5.85), Inches(5.0), CARD, line=RULE)
    add_rect(s, Inches(0.8), Inches(1.55), Inches(0.12), Inches(5.0), ACCENT_DARK)
    add_text(s, Inches(1.05), Inches(1.75), Inches(5), Inches(0.4),
             "L3 · Semantic Mapping", size=16, bold=True, color=INK)
    add_text(s, Inches(1.05), Inches(2.15), Inches(5.5), Inches(0.4),
             "rule baseline → LLM refines → score per row", size=11, color=MUTED)
    # mini table
    headers = ["source.col", "→", "target.col", "conf"]
    rows = [
        ("crm.email",      "→", "email_norm",     "0.94"),
        ("crm.first_name", "→", "first_name",     "0.99"),
        ("crm.dob",        "→", "birth_date",     "0.86"),
        ("crm.zip",        "→", "postal_code",    "0.91"),
    ]
    col_w = [Inches(1.7), Inches(0.3), Inches(1.7), Inches(0.8)]
    x0 = Inches(1.05); y0 = Inches(2.7)
    cx = x0
    for i, h in enumerate(headers):
        add_text(s, cx, y0, col_w[i], Inches(0.3), h, size=10, bold=True,
                 color=ACCENT_DARK)
        cx += col_w[i]
    add_rect(s, x0, y0 + Inches(0.3), sum(col_w, Inches(0)), Emu(9525), RULE)
    yy = y0 + Inches(0.4)
    for row in rows:
        cx = x0
        for i, v in enumerate(row):
            color = GREEN if (i == 3 and float(v) >= 0.9) else AMBER if i == 3 else INK
            add_text(s, cx, yy, col_w[i], Inches(0.35), v, size=11,
                     bold=(i == 3), color=color)
            cx += col_w[i]
        yy += Inches(0.45)

    # L5 card
    add_round(s, Inches(6.85), Inches(1.55), Inches(5.65), Inches(5.0), CARD, line=RULE)
    add_rect(s, Inches(6.85), Inches(1.55), Inches(0.12), Inches(5.0), AMBER)
    add_text(s, Inches(7.1), Inches(1.75), Inches(5), Inches(0.4),
             "L5 · Validation & Governance", size=16, bold=True, color=INK)
    add_text(s, Inches(7.1), Inches(2.15), Inches(5.3), Inches(0.4),
             "deterministic confidence band + rule findings", size=11, color=MUTED)
    # band
    add_round(s, Inches(7.1), Inches(2.7), Inches(5.2), Inches(1.0), BG, line=RULE)
    add_text(s, Inches(7.3), Inches(2.85), Inches(2.5), Inches(0.3),
             "overall_band", size=10, bold=True, color=MUTED)
    add_round(s, Inches(7.3), Inches(3.15), Inches(1.0), Inches(0.4), GREEN)
    add_text(s, Inches(7.3), Inches(3.2), Inches(1.0), Inches(0.4),
             "green", size=11, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF),
             align=PP_ALIGN.CENTER)
    add_text(s, Inches(8.6), Inches(3.2), Inches(3.5), Inches(0.4),
             "score 0.91   ·   coverage 100%", size=11, color=INK)
    # findings
    add_text(s, Inches(7.1), Inches(3.95), Inches(5), Inches(0.4),
             "Findings", size=12, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(7.1), Inches(4.3), Inches(5.3), Inches(2.1), [
        "PII coverage OK — email + dob masked",
        "Type coercions reviewed (3)",
        "FK chain depth ≤ 2 — within budget",
        "No orphan source columns",
    ], size=11, color=MUTED)
    footer(s, "core/stm/mapping_engine.py is the deterministic floor inside L3")


def slide_underneath(prs, n, total):
    s = blank(prs)
    page_chrome(s, "Act 3 — what's underneath", "The blackboard is persisted. The pipeline is observable.", n, total)
    cards = [
        ("Persisted blackboard",
         "Every stage writes to `stm_sessions.blackboard_json`.\n"
         "Crash the API mid-run → restart → `_recover_stm_sessions()` resumes."),
        ("SSE replay + tail",
         "Reload the page mid-stage — the stream replays from DB,\n"
         "then tails live. No lost events, no double-events."),
        ("Clone & retry",
         "Rejected or failed? Click Clone & retry to spawn a fresh\n"
         "session reusing sources + target + intent."),
        ("Jira write-back",
         "On `session_done` the Jira issue gets a comment with\n"
         "target, confidence band, field count, sources. Env-gated."),
    ]
    cw, ch = Inches(5.9), Inches(2.3)
    positions = [
        (Inches(0.8), Inches(1.55)),
        (Inches(6.85), Inches(1.55)),
        (Inches(0.8), Inches(4.05)),
        (Inches(6.85), Inches(4.05)),
    ]
    for (title, body), (x, y) in zip(cards, positions):
        add_round(s, x, y, cw, ch, CARD, line=RULE)
        add_rect(s, x, y, Inches(0.1), ch, ACCENT)
        add_text(s, x + Inches(0.3), y + Inches(0.25), cw - Inches(0.5), Inches(0.4),
                 title, size=15, bold=True, color=INK)
        add_text(s, x + Inches(0.3), y + Inches(0.75), cw - Inches(0.5), ch - Inches(1.0),
                 body, size=12, color=MUTED)
    footer(s, "core/stm/coordinator.py  ·  core/stm/events.py  ·  app.py")


def slide_architecture(prs, n, total):
    s = blank(prs)
    page_chrome(s, "Architecture", "Where the bits live.", n, total)

    layers = [
        ("UI",         "ui/mapping_compose_react.html  —  AgenticApp ?mode=agentic", ACCENT),
        ("REST + SSE", "routers/stm_sessions.py  —  POST /api/stm/sessions  ·  /events  ·  /gates  ·  /clone  ·  /export", ACCENT_DARK),
        ("Coordinator","core/stm/coordinator.py  —  pipeline loop, gate stalls, recovery hook", AMBER),
        ("Agents",     "core/stm/agents/  —  L1 intent · L2 metadata · L3 mapping · L4 transforms · L5 validation · L6 builder", GREEN),
        ("Blackboard", "core/stm/blackboard.py  —  shared session state Pydantic models", INK),
        ("Persistence","stm_sessions  ·  stm_stage_events  ·  stm_gate_decisions  (alembic-managed)", MUTED),
    ]
    y = Inches(1.55)
    for label, path, color in layers:
        add_round(s, Inches(0.8), y, Inches(11.7), Inches(0.78), CARD, line=RULE)
        add_rect(s, Inches(0.8), y, Inches(0.1), Inches(0.78), color)
        add_text(s, Inches(1.05), y + Inches(0.18), Inches(2.5), Inches(0.4),
                 label, size=13, bold=True, color=color)
        add_text(s, Inches(3.6), y + Inches(0.18), Inches(9), Inches(0.4),
                 path, size=11, color=INK)
        y += Inches(0.88)
    footer(s, "docs/superpowers/specs/2026-05-11-stm-agentic-evolution-design.md")


def slide_faq(prs, n, total):
    s = blank(prs)
    page_chrome(s, "Anticipated questions", "What the room will ask.", n, total)
    qs = [
        ("Why two gates and not three?",
         "L2 is highest ambiguity (raw metadata).  L5 is highest stakes (about to ship).  L1/L3/L4 are reversible via Refine."),
        ("What runs the LLM?",
         "OpenRouter today.  L1 Haiku · L2 Sonnet · L3 + L4 Opus · L5/L6 deterministic."),
        ("Can a reviewer edit fields inline?",
         "Not in v1 — explicit non-goal.  Refine-with-feedback is the supported edit path.  Inline edits land in a follow-up."),
        ("What if two reviewers click Approve at once?",
         "`asyncio.Event.set()` is idempotent.  Second decision overwrites the row; pipeline already left the stall."),
        ("Is the rule-based path going away?",
         "No.  It's the deterministic floor inside L3, and still served at `POST /api/stm/generate`."),
        ("Single-worker uvicorn?",
         "Yes, intentional for v1.  Multi-worker needs DB advisory locks — deferred."),
    ]
    cw, ch = Inches(5.9), Inches(1.65)
    for i, (q, a) in enumerate(qs):
        r, c = divmod(i, 2)
        x = Inches(0.8) + c * (cw + Inches(0.15))
        y = Inches(1.55) + r * (ch + Inches(0.15))
        add_round(s, x, y, cw, ch, CARD, line=RULE)
        add_text(s, x + Inches(0.3), y + Inches(0.18), cw - Inches(0.5), Inches(0.5),
                 q, size=12, bold=True, color=INK)
        add_text(s, x + Inches(0.3), y + Inches(0.6), cw - Inches(0.5), Inches(1.0),
                 a, size=11, color=MUTED)
    footer(s, "Q&A")


def slide_close(prs):
    s = blank(prs)
    add_rect(s, 0, 0, SLIDE_W, SLIDE_H, INK)
    add_rect(s, 0, Inches(3.3), SLIDE_W, Inches(0.05), ACCENT)
    add_text(s, Inches(0.8), Inches(2.4), Inches(10), Inches(0.4),
             "ONE LINE TO REMEMBER", size=12, bold=True,
             color=RGBColor(0x9A, 0xB3, 0xE8))
    add_text(s, Inches(0.8), Inches(2.8), Inches(12), Inches(0.9),
             "Excel is the rendered view.", size=40, bold=True,
             color=RGBColor(0xFF, 0xFF, 0xFF))
    add_text(s, Inches(0.8), Inches(3.6), Inches(12), Inches(0.9),
             "The blackboard is the product.", size=40, bold=True,
             color=RGBColor(0xC9, 0xD3, 0xEC))
    add_text(s, Inches(0.8), Inches(5.0), Inches(12), Inches(0.5),
             "feat/stm-agentic-evolution  ·  docs/STM_AGENTIC_DEMO.md  ·  core/stm/",
             size=13, color=RGBColor(0x6F, 0x83, 0xB0))
    add_text(s, Inches(0.8), Inches(6.6), Inches(10), Inches(0.3),
             "Thanks.  Questions →", size=14, bold=True,
             color=RGBColor(0xFF, 0xFF, 0xFF))


# ----- build ----------------------------------------------------------------

def build(out_path: Path) -> Path:
    prs = new_deck()
    builders = [
        ("title", slide_title),
        ("tldr", slide_tldr),
        ("layers", slide_six_layers),
        ("gates", slide_gates),
        ("blackboard", slide_blackboard),
        ("demo flow", slide_demo_flow),
        ("session start", slide_session_start),
        ("gate walk", slide_gate_walk),
        ("L3/L5", slide_l3_l5),
        ("underneath", slide_underneath),
        ("architecture", slide_architecture),
        ("faq", slide_faq),
        ("close", slide_close),
    ]
    total = len(builders)
    for i, (_, fn) in enumerate(builders, start=1):
        if fn is slide_title or fn is slide_close:
            fn(prs)
        else:
            fn(prs, i, total)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out_path)
    return out_path


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    out = here / "docs" / "STM_Agentic_Demo.pptx"
    written = build(out)
    print(f"wrote {written}")
