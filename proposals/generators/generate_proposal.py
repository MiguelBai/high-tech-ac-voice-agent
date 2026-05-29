#!/usr/bin/env python3
"""Generate ManyFai custom proposal for High Tech Air Conditioning — 3 pages, branded."""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    PageBreak, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MANYFAI_LOGO = "/Users/miguelbarbosa/Desktop/pics/logo.png"
HTAC_LOGO = "/Users/miguelbarbosa/ANTIGRAVITY V1 TEST/HVAC Retell/.firecrawl/hightechac-logo.png"
OUTPUT_DIR = "/Users/miguelbarbosa/ANTIGRAVITY V1 TEST/HVAC Retell"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "CLIENT_Proposal_HVAC_Voice_Agent.pdf")

CYAN = HexColor("#00E5CC")
DARK = HexColor("#1A1A2E")
GRAY = HexColor("#555555")
LIGHT_BG = HexColor("#F0FFFE")
CYAN_DARK = HexColor("#00B8A9")
WHITE = white

# ─── STYLES ───────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

sTitle = ParagraphStyle("title", parent=styles["Title"], fontSize=22, leading=26,
                        textColor=DARK, alignment=TA_CENTER, spaceAfter=2, fontName="Helvetica-Bold")
sSubtitle = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=13, leading=16,
                           textColor=GRAY, alignment=TA_CENTER, spaceAfter=4)
sH1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=17, leading=20,
                      textColor=DARK, spaceAfter=5, spaceBefore=2, fontName="Helvetica-Bold")
sH2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, leading=15,
                      textColor=DARK, spaceAfter=3, spaceBefore=3, fontName="Helvetica-Bold")
sBody = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=13,
                        textColor=GRAY, spaceAfter=3)
sBullet = ParagraphStyle("bullet", parent=sBody, leftIndent=18, bulletIndent=6, spaceAfter=1)
sStatNum = ParagraphStyle("statNum", parent=styles["Normal"], fontSize=20, leading=24,
                           textColor=CYAN_DARK, alignment=TA_CENTER, fontName="Helvetica-Bold")
sStatLabel = ParagraphStyle("statLabel", parent=styles["Normal"], fontSize=8.5, leading=11,
                             textColor=GRAY, alignment=TA_CENTER)
sPriceNum = ParagraphStyle("priceNum", parent=styles["Normal"], fontSize=18, leading=22,
                            textColor=CYAN_DARK, alignment=TA_CENTER, fontName="Helvetica-Bold")
sFooter = ParagraphStyle("footer", parent=styles["Normal"], fontSize=7.5, leading=10,
                          textColor=GRAY, alignment=TA_CENTER)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def cyan_hr():
    return HRFlowable(width="100%", thickness=2, color=CYAN, spaceAfter=6, spaceBefore=2)

def bullet(text):
    return Paragraph(f"<bullet>&bull;</bullet> {text}", sBullet)

def table_style_base():
    return [
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#DDDDDD")),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]

# ─── BUILD STORY ──────────────────────────────────────────────────────────────
story = []

# ==================== PAGE 1 — COVER + PROBLEM ====================

# Dual logo header: ManyFai + High Tech AC
manyfai_logo = Image(MANYFAI_LOGO, width=1.6*inch, height=0.55*inch)
htac_logo = Image(HTAC_LOGO, width=0.7*inch, height=0.7*inch)
logo_row = Table([[manyfai_logo, Paragraph("&times;", ParagraphStyle("x", parent=sBody,
    fontSize=16, textColor=GRAY, alignment=TA_CENTER)), htac_logo]],
    colWidths=[2*inch, 0.6*inch, 1*inch])
logo_row.setStyle(TableStyle([
    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 0),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
]))
logo_row.hAlign = "CENTER"
story.append(Spacer(1, 0.2*inch))
story.append(logo_row)
story.append(Spacer(1, 0.15*inch))

# Title
story.append(Paragraph("AI Voice Agent Proposal", sTitle))
story.append(Paragraph("for High Tech Air Conditioning", sTitle))
story.append(Spacer(1, 3))
story.append(HRFlowable(width="30%", thickness=3, color=CYAN, spaceAfter=8, spaceBefore=2))
story.append(Paragraph("Never Miss Another Call. Book More Jobs. 24/7.", sSubtitle))
story.append(Spacer(1, 4))
story.append(Paragraph("Prepared by Miguel  |  ManyFai", ParagraphStyle("prep", parent=sBody,
             alignment=TA_CENTER, textColor=GRAY, fontSize=10)))
story.append(Paragraph("Custom proposal for High Tech Air Conditioning — Orlando, FL", ParagraphStyle("client", parent=sBody,
             alignment=TA_CENTER, textColor=CYAN_DARK, fontSize=9)))
story.append(Paragraph("March 2026", ParagraphStyle("date", parent=sBody,
             alignment=TA_CENTER, textColor=GRAY, fontSize=9)))
story.append(Spacer(1, 0.15*inch))

# ── Problem Section ──
story.append(cyan_hr())
story.append(Paragraph("The Problem: Missed Calls = Lost Revenue", sH1))
story.append(Paragraph("Every unanswered call is a customer choosing your competitor.", sBody))
story.append(Spacer(1, 4))

# Stats boxes
stat_data = [
    [Paragraph("27%", sStatNum), Paragraph("$31K – $52K", sStatNum)],
    [Paragraph("of HVAC calls go unanswered", sStatLabel),
     Paragraph("lost revenue/year from just<br/>2 missed calls per week", sStatLabel)],
]
stat_table = Table(stat_data, colWidths=[2.8*inch, 3.2*inch])
stat_table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
    ("BOX", (0, 0), (-1, -1), 1, HexColor("#D0F0ED")),
    ("LINEAFTER", (0, 0), (0, -1), 0.5, HexColor("#D0F0ED")),
    ("TOPPADDING", (0, 0), (-1, 0), 8),
    ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
    ("TOPPADDING", (0, 1), (-1, 1), 2),
    ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
]))
story.append(stat_table)
story.append(Spacer(1, 6))

story.append(Paragraph("With 40+ years of combined experience serving Orlando, Windermere, Celebration, Winter Garden "
                        "and surrounding counties — your team is in the field. Calls come in during jobs, after hours, "
                        "weekends, and peak season. Every missed call is a <b>$150–$500</b> service job walking to a competitor.", sBody))
story.append(Spacer(1, 3))
story.append(Paragraph("<b>Common pain points for High Tech AC:</b>", sBody))
for p in [
    "Calls going to voicemail after hours &amp; weekends across your Orlando service area",
    "Techs too busy on AC, heating &amp; duct cleaning jobs to answer",
    "Summer AC peak season overwhelming your front desk",
    "No way to qualify residential vs. commercial leads before dispatching",
    "Emergency calls (no AC, refrigerant leak) lost in voicemail",
]:
    story.append(bullet(p))

story.append(Spacer(1, 6))
story.append(Paragraph("ManyFai  |  Custom Proposal for High Tech Air Conditioning", sFooter))

# ==================== PAGE 2 — SOLUTION + BENEFITS ====================
story.append(PageBreak())

# Header: ManyFai logo left, HTAC logo right
mf_sm = Image(MANYFAI_LOGO, width=1.2*inch, height=0.4*inch)
ht_sm = Image(HTAC_LOGO, width=0.45*inch, height=0.45*inch)
hdr = Table([[mf_sm, ht_sm]], colWidths=[5.2*inch, 0.8*inch])
hdr.setStyle(TableStyle([
    ("ALIGN", (0, 0), (0, 0), "LEFT"),
    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 0),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
]))
story.append(hdr)
story.append(Spacer(1, 4))

story.append(cyan_hr())
story.append(Paragraph("The Solution: Your AI-Powered Phone Agent", sH1))
story.append(Paragraph("A custom AI voice agent built specifically for High Tech Air Conditioning — "
                        "answering every call 24/7/365 with natural conversations tailored to your services.", sBody))
story.append(Spacer(1, 4))

story.append(Paragraph("What Your AI Agent Does", sH2))

features = [
    ("<b>Answers Every Call</b> — picks up instantly, day or night, weekday or weekend.",),
    ("<b>Books Appointments</b> — checks your real calendar and schedules service calls on the spot.",),
    ("<b>Qualifies Leads</b> — asks about system type, issue, address &amp; urgency; separates residential from commercial.",),
    ("<b>Handles Emergencies</b> — detects urgent keywords (no AC, refrigerant leak) and routes to your on-call tech.",),
    ("<b>Provides Info</b> — answers FAQs about your AC, heating, duct cleaning services &amp; service areas.",),
    ("<b>Sends Confirmations</b> — texts the customer a booking confirmation; sends you a lead alert.",),
    ("<b>Speaks Naturally</b> — real, flowing conversations — not robotic phone trees.",),
    ("<b>Transfers When Needed</b> — seamlessly hands off to a live person for complex situations.",),
]
for f in features:
    story.append(bullet(f[0]))

story.append(Spacer(1, 4))

# How It Works
story.append(Paragraph("How It Works", sH2))
how_data = [
    ["Step", "What Happens"],
    ["1. Customer Calls", "AI answers instantly with a friendly High Tech AC greeting."],
    ["2. AI Converses", "Natural conversation — asks relevant questions, understands the need."],
    ["3. Action Taken", "Books appointment, routes emergency, or captures lead details."],
    ["4. You Get Notified", "Instant notification with call details, recording, and any bookings."],
]
how_table = Table(how_data, colWidths=[1.3*inch, 4.7*inch])
how_table.setStyle(TableStyle(table_style_base() + [
    ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
]))
story.append(how_table)

story.append(Spacer(1, 5))

# Why ManyFai
story.append(Paragraph("Why Work With ManyFai", sH2))
why_points = [
    "<b>Custom, Not Cookie-Cutter</b> — built around High Tech AC's services, Orlando service area, scheduling &amp; brand voice.",
    "<b>Continuous Optimization</b> — monthly call reviews &amp; AI fine-tuning. Your agent gets better every month.",
    "<b>Real Conversations</b> — no \"press 1\" menus. Just a helpful, intelligent conversation.",
    "<b>Transparent Reporting</b> — full access to recordings, transcripts &amp; analytics.",
    "<b>No Long-Term Contracts</b> — month-to-month after setup. We earn your business every month.",
]
for w in why_points:
    story.append(bullet(w))

story.append(Spacer(1, 6))
story.append(Paragraph("ManyFai  |  Custom Proposal for High Tech Air Conditioning", sFooter))

# ==================== PAGE 3 — PRICING + ROI + TIMELINE ====================
story.append(PageBreak())

# Header
hdr2 = Table([[Image(MANYFAI_LOGO, width=1.2*inch, height=0.4*inch),
               Image(HTAC_LOGO, width=0.45*inch, height=0.45*inch)]],
             colWidths=[5.2*inch, 0.8*inch])
hdr2.setStyle(TableStyle([
    ("ALIGN", (0, 0), (0, 0), "LEFT"),
    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 0),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
]))
story.append(hdr2)
story.append(Spacer(1, 2))

story.append(cyan_hr())
story.append(Paragraph("Investment", sH1))
story.append(Paragraph("Simple, transparent pricing with no hidden fees.", sBody))
story.append(Spacer(1, 3))

# Pricing table
price_data = [
    ["", "What's Included", "Investment"],
    [
        Paragraph("<b>One-Time Setup</b>", ParagraphStyle("tc", parent=sBody, fontSize=8, textColor=DARK, fontName="Helvetica-Bold")),
        Paragraph("Custom AI agent built for High Tech AC  |  Conversation flow design &amp; testing  |  "
                  "Phone number &amp; calendar setup  |  Emergency routing  |  Training call",
                  ParagraphStyle("tc2", parent=sBody, fontSize=8, leading=11)),
        Paragraph("<b>$749</b>", sPriceNum),
    ],
    [
        Paragraph("<b>Monthly Service</b>", ParagraphStyle("tc", parent=sBody, fontSize=8, textColor=DARK, fontName="Helvetica-Bold")),
        Paragraph("24/7 AI answering (750 min)  |  Ongoing optimization  |  Call recordings &amp; analytics  |  "
                  "Seasonal updates  |  Priority support",
                  ParagraphStyle("tc2", parent=sBody, fontSize=8, leading=11)),
        Paragraph("<b>$389/mo</b>", sPriceNum),
    ],
]
price_table = Table(price_data, colWidths=[1.1*inch, 3.4*inch, 1.5*inch])
price_table.setStyle(TableStyle(table_style_base() + [
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ALIGN", (2, 0), (2, -1), "CENTER"),
]))
story.append(price_table)

story.append(Spacer(1, 2))
story.append(Paragraph("<i>750 included minutes covers the vast majority of HVAC businesses. Most clients never exceed this.</i>",
                        ParagraphStyle("note", parent=sBody, fontSize=7.5, textColor=GRAY)))
story.append(Spacer(1, 5))

# ROI section
story.append(Paragraph("The Math: How This Pays for Itself", sH2))

roi_data = [
    ["Metric", "Value"],
    ["Average HVAC service call value", "$250 – $500"],
    ["Missed calls per week (industry avg.)", "5 – 15 calls"],
    ["If AI captures just 2 extra jobs/month", "$500 – $1,000 gained"],
    ["Your monthly investment", "$389"],
    ["Net gain from month 1", "$111 – $611/month"],
    ["Annual ROI", "250% – 700%+"],
]
roi_table = Table(roi_data, colWidths=[3.2*inch, 2.8*inch])
roi_table.setStyle(TableStyle(table_style_base() + [
    ("ALIGN", (1, 0), (1, -1), "CENTER"),
    ("BACKGROUND", (0, -1), (-1, -1), LIGHT_BG),
    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story.append(roi_table)

story.append(Spacer(1, 2))
story.append(Paragraph("<b>vs. hiring:</b> A receptionist costs $3,000–$4,300/mo. Your AI agent is <b>$389/mo</b> "
                        "24/7 — <b>90% savings</b> with better coverage.",
                        ParagraphStyle("cmp", parent=sBody, fontSize=8.5)))

story.append(Spacer(1, 5))

# Getting Started Timeline
story.append(Paragraph("Getting Started", sH2))
timeline_data = [
    ["Timeline", "What Happens"],
    ["Day 1–2", "You fill out a short form so we understand High Tech AC's services & key questions."],
    ["Day 3–5", "We build your custom AI agent with tailored conversation flows."],
    ["Day 6–7", "Testing phase — real-world scenarios, fine-tuning responses."],
    ["Day 8–10", "Go live! AI starts answering calls. We monitor closely the first week."],
    ["Ongoing", "Monthly optimization, seasonal updates & performance reviews."],
]
timeline_table = Table(timeline_data, colWidths=[1.1*inch, 4.9*inch])
timeline_table.setStyle(TableStyle(table_style_base() + [
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story.append(timeline_table)

story.append(Spacer(1, 8))
story.append(Paragraph("ManyFai  |  Custom Proposal for High Tech Air Conditioning  |  March 2026", sFooter))

# ─── RENDER ───────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUTPUT_FILE,
    pagesize=letter,
    topMargin=0.4*inch,
    bottomMargin=0.3*inch,
    leftMargin=0.75*inch,
    rightMargin=0.75*inch,
)
doc.build(story)
print(f"PDF saved to {OUTPUT_FILE}")
