#!/usr/bin/env python3
"""Generate ManyFai Service Agreement for High Tech Air Conditioning — 2-3 pages, branded."""

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
CLIENT_NAME = "High Tech Air Conditioning"
CLIENT_LOCATION = "Orlando, FL"
PROVIDER_NAME = "ManyFai"
PROVIDER_CONTACT_NAME = "Miguel"
PROVIDER_EMAIL = "miguel@manyfai.com"
PROVIDER_PHONE = "(407) 555-0100"

SETUP_FEE = "$749"
MONTHLY_FEE = "$389"
INCLUDED_MINUTES = "500"
OVERAGE_RATE = "$0.22"
EFFECTIVE_DATE = "April 1, 2026"

MANYFAI_LOGO = "/Users/miguelbarbosa/Desktop/pics/logo.png"
HTAC_LOGO = "/Users/miguelbarbosa/ANTIGRAVITY V1 TEST/HVAC Retell/.firecrawl/hightechac-logo.png"
OUTPUT_DIR = "/Users/miguelbarbosa/ANTIGRAVITY V1 TEST/HVAC Retell"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "SERVICE_Contract_High_Tech_AC.pdf")

CYAN = HexColor("#00E5CC")
DARK = HexColor("#1A1A2E")
GRAY = HexColor("#555555")
LIGHT_BG = HexColor("#F0FFFE")
CYAN_DARK = HexColor("#00B8A9")
WHITE = white

# ─── STYLES ───────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

sTitle = ParagraphStyle("title", parent=styles["Title"], fontSize=20, leading=24,
                        textColor=DARK, alignment=TA_CENTER, spaceAfter=1, fontName="Helvetica-Bold")
sSubtitle = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=10, leading=13,
                           textColor=GRAY, alignment=TA_CENTER, spaceAfter=2)
sH1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=12, leading=15,
                      textColor=DARK, spaceAfter=3, spaceBefore=4, fontName="Helvetica-Bold")
sH2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=10, leading=13,
                      textColor=DARK, spaceAfter=2, spaceBefore=2, fontName="Helvetica-Bold")
sBody = ParagraphStyle("body", parent=styles["Normal"], fontSize=8.5, leading=11.5,
                        textColor=GRAY, spaceAfter=1.5)
sBullet = ParagraphStyle("bullet", parent=sBody, leftIndent=16, bulletIndent=5, spaceAfter=0.5)
sFooter = ParagraphStyle("footer", parent=styles["Normal"], fontSize=7.5, leading=10,
                          textColor=GRAY, alignment=TA_CENTER)
sSmall = ParagraphStyle("small", parent=sBody, fontSize=7.5, leading=10, textColor=GRAY)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def cyan_hr():
    return HRFlowable(width="100%", thickness=1.5, color=CYAN, spaceAfter=3, spaceBefore=1)

def bullet(text):
    return Paragraph(f"<bullet>&bull;</bullet> {text}", sBullet)

def section(num, title):
    return Paragraph(f"{num}. {title}", sH1)

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

def page_header():
    """Dual-logo header for pages after page 1."""
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
    return hdr

# ─── BUILD STORY ──────────────────────────────────────────────────────────────
story = []

# ==================== PAGE 1 — COVER + SECTIONS 1-4 ====================

# Dual logo header (centered)
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
story.append(Spacer(1, 0.1*inch))
story.append(logo_row)
story.append(Spacer(1, 0.06*inch))

# Title block
story.append(Paragraph("Service Agreement", sTitle))
story.append(HRFlowable(width="30%", thickness=3, color=CYAN, spaceAfter=4, spaceBefore=1))
story.append(Paragraph("AI Voice Agent Services", sSubtitle))
story.append(Paragraph(
    f"Between <b>{PROVIDER_NAME}</b> (\"Provider\") and <b>{CLIENT_NAME}</b> (\"Client\")",
    ParagraphStyle("parties", parent=sBody, alignment=TA_CENTER, fontSize=9.5)
))
story.append(Paragraph(
    f"Effective Date: {EFFECTIVE_DATE}",
    ParagraphStyle("date", parent=sBody, alignment=TA_CENTER, fontSize=9.5)
))
story.append(Spacer(1, 0.04*inch))

# ── Section 1: Service Description ──
story.append(cyan_hr())
story.append(section(1, "Service Description"))
story.append(Paragraph(
    f"Provider agrees to build and operate a custom AI voice agent for {CLIENT_NAME}. "
    "The AI agent will answer inbound telephone calls 24 hours a day, 7 days a week, "
    "and perform the following functions on behalf of the Client:",
    sBody
))
for item in [
    "Greet callers using the Client's brand voice and business identity",
    "Qualify leads by collecting service type, address, system details, and urgency",
    "Book appointments via real-time calendar integration",
    "Detect and route emergency calls (no AC, gas leak, no heat) to the Client's on-call technician",
    "Provide information about the Client's services, service areas, and business hours",
    "Send booking confirmations via text message and notify the Client of new leads",
]:
    story.append(bullet(item))

story.append(Spacer(1, 0.03*inch))

# ── Section 2: Fees & Payment Terms ──
story.append(section(2, "Fees &amp; Payment Terms"))

price_data = [
    ["Item", "Description", "Amount"],
    ["One-Time Setup Fee",
     "Custom AI agent build, conversation flow design,\nphone number setup, calendar integration, training call",
     SETUP_FEE],
    ["Monthly Service Fee",
     f"24/7 AI answering, {INCLUDED_MINUTES} included minutes,\nrecordings, analytics, optimization, support",
     f"{MONTHLY_FEE}/mo"],
    ["Overage Rate",
     f"Per-minute charge for usage exceeding\n{INCLUDED_MINUTES} minutes in a billing period",
     f"{OVERAGE_RATE}/min"],
]
price_table = Table(price_data, colWidths=[1.3*inch, 3.2*inch, 1.2*inch])
price_table.setStyle(TableStyle(table_style_base() + [
    ("ALIGN", (2, 0), (2, -1), "CENTER"),
    ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
]))
story.append(price_table)
story.append(Spacer(1, 3))
story.append(Paragraph(
    "<b>Payment Terms:</b> Setup fee is due before onboarding begins. Monthly fees are invoiced "
    "on the 1st of each month. Payment is due within 15 days of invoice (Net-15). "
    "Late payments may result in service suspension after a 7-day grace period.",
    sSmall
))
story.append(Spacer(1, 0.03*inch))

# ── Section 3: Setup & Onboarding ──
story.append(section(3, "Setup &amp; Onboarding Timeline"))
timeline_data = [
    ["Timeline", "What Happens"],
    ["Day 1-2", "Client fills out an intake form covering services, scheduling, and preferences."],
    ["Day 3-5", "Provider builds the custom AI agent with tailored conversation flows."],
    ["Day 6-7", "Testing phase with real-world call scenarios and fine-tuning."],
    ["Day 8-10", "Go live. AI begins answering calls. Provider monitors closely the first week."],
    ["Ongoing", "Monthly optimization, seasonal updates, and performance reviews."],
]
timeline_table = Table(timeline_data, colWidths=[1.1*inch, 4.9*inch])
timeline_table.setStyle(TableStyle(table_style_base() + [
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story.append(timeline_table)
story.append(Spacer(1, 0.03*inch))

# ── Section 4: Included Services ──
story.append(section(4, "Included Services"))
story.append(Paragraph("The monthly service fee includes the following:", sBody))
for item in [
    "<b>24/7 AI Voice Answering</b> — instant call pickup, every day of the year",
    "<b>Appointment Booking</b> — real-time calendar integration with automatic scheduling",
    "<b>Call Recordings &amp; Analytics</b> — full access to recordings, transcripts, and performance data",
    "<b>Ongoing Optimization</b> — monthly call reviews and AI prompt tuning for better results",
    "<b>Seasonal Messaging Updates</b> — adjusted scripts for summer AC, winter heating, and promotions",
    "<b>Priority Support</b> — dedicated support with fast response times",
    "<b>Monthly Performance Review</b> — scheduled review of call metrics and optimization plan",
]:
    story.append(bullet(item))

story.append(Spacer(1, 3))
story.append(Paragraph(f"ManyFai  |  Service Agreement  |  {CLIENT_NAME}", sFooter))

# ==================== PAGE 2 — SECTIONS 5-8 ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))
story.append(cyan_hr())

# ── Section 5: Maintenance & Ongoing Optimization ──
story.append(section(5, "Maintenance &amp; Ongoing Optimization"))
story.append(Paragraph(
    "Provider will continuously maintain and improve the AI agent to ensure optimal performance:",
    sBody
))
for item in [
    "<b>Monthly Call Reviews</b> — Provider reviews call recordings and transcripts to identify improvement areas",
    "<b>AI Prompt Tuning</b> — conversation flows are refined based on real call data and Client feedback",
    "<b>Seasonal Updates</b> — messaging adjusted for peak seasons (summer AC, winter heating) and promotions",
    "<b>System Monitoring</b> — Provider monitors uptime and performance, resolving issues proactively",
    "<b>Flow Adjustments</b> — new services, scheduling changes, or routing updates are implemented as needed",
]:
    story.append(bullet(item))

story.append(Spacer(1, 0.04*inch))

# ── Section 6: Support ──
story.append(section(6, "Support"))
story.append(Paragraph(
    "Provider offers priority support to ensure the Client's AI agent is always performing at its best.",
    sBody
))

support_data = [
    ["Channel", "Details", "Response Time"],
    ["Email", PROVIDER_EMAIL, "Within 24 hours"],
    ["Phone", PROVIDER_PHONE, "Within 24 hours"],
    ["Urgent / Outage", "Email or phone with subject marked URGENT", "Within 4 hours"],
]
support_table = Table(support_data, colWidths=[1.2*inch, 2.8*inch, 1.7*inch])
support_table.setStyle(TableStyle(table_style_base() + [
    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
]))
story.append(support_table)
story.append(Spacer(1, 3))
story.append(Paragraph(
    "For general requests (new greetings, scheduling changes, etc.), Client may contact Provider "
    "via email or phone at any time. Changes are typically implemented within 1-2 business days.",
    sSmall
))

story.append(Spacer(1, 0.04*inch))

# ── Section 7: Cancellation & Termination ──
story.append(section(7, "Cancellation &amp; Termination"))
for item in [
    "This is a <b>month-to-month agreement</b>. There is no long-term commitment required.",
    "Either party may cancel this agreement with <b>30 days written notice</b> via email.",
    "Upon cancellation, service will continue through the end of the current billing period.",
    "The one-time setup fee is <b>non-refundable</b>, as it covers the cost of building and configuring the AI agent.",
    "Upon termination, Provider will make all call recordings and data available to the Client upon request.",
]:
    story.append(bullet(item))

story.append(Spacer(1, 0.04*inch))

# ── Section 8: Limitation of Liability ──
story.append(section(8, "Limitation of Liability"))
story.append(Paragraph(
    "Provider shall not be liable for any indirect, incidental, special, or consequential damages "
    "arising from the use of the AI voice agent service, including but not limited to lost profits "
    "or business interruption.",
    sBody
))
story.append(Paragraph(
    f"Provider's total aggregate liability under this agreement shall not exceed the total fees "
    f"paid by Client in the three (3) months immediately preceding the claim.",
    sBody
))
story.append(Paragraph(
    "The AI voice agent is intended as a <b>supplement to, not a replacement for</b>, human staff "
    "in emergency or life-safety situations. Client acknowledges that AI technology, while highly "
    "capable, may occasionally misinterpret caller intent. Provider commits to commercially "
    "reasonable uptime and will address any service disruptions promptly.",
    sBody
))

story.append(Spacer(1, 0.04*inch))

# ── Section 9: Agreement & Signatures ──
story.append(section(9, "Agreement &amp; Signatures"))
story.append(Paragraph(
    f"By signing below, both parties acknowledge that they have read, understood, and agree to "
    f"all terms and conditions outlined in this Service Agreement. This agreement becomes effective "
    f"on the date indicated above and remains in force until terminated per the cancellation terms in Section 7.",
    sBody
))
story.append(Spacer(1, 0.2*inch))

# Signature blocks — side by side
sig_line = "_" * 35
sig_style = ParagraphStyle("sig", parent=sBody, fontSize=9, textColor=DARK, spaceAfter=6)
sig_label = ParagraphStyle("sigLabel", parent=sBody, fontSize=8, textColor=GRAY, spaceAfter=14)

sig_filled = ParagraphStyle("sigFilled", parent=sBody, fontSize=10, textColor=DARK, spaceAfter=6, fontName="Helvetica-Oblique")

left_sig = [
    Paragraph(f"<b>{PROVIDER_NAME}</b>", ParagraphStyle("sigHead", parent=sBody, fontSize=10, textColor=DARK, fontName="Helvetica-Bold")),
    Spacer(1, 0.15*inch),
    Paragraph("Miguel Barbosa", sig_filled),
    Paragraph("Name", sig_label),
    Paragraph("<i>Miguel Barbosa</i>", sig_filled),
    Paragraph("Signature", sig_label),
    Paragraph("April 1, 2026", sig_filled),
    Paragraph("Date", sig_label),
]

right_sig = [
    Paragraph(f"<b>{CLIENT_NAME}</b>", ParagraphStyle("sigHead2", parent=sBody, fontSize=10, textColor=DARK, fontName="Helvetica-Bold")),
    Spacer(1, 0.2*inch),
    Paragraph(sig_line, sig_style),
    Paragraph("Name", sig_label),
    Paragraph(sig_line, sig_style),
    Paragraph("Signature", sig_label),
    Paragraph(sig_line, sig_style),
    Paragraph("Date", sig_label),
]

# Use a table to place signature blocks side by side
from reportlab.platypus import ListFlowable

sig_table = Table(
    [[left_sig, Spacer(1, 1), right_sig]],
    colWidths=[2.7*inch, 0.6*inch, 2.7*inch]
)
sig_table.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 0),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
]))
story.append(sig_table)

story.append(Spacer(1, 0.3*inch))
story.append(HRFlowable(width="60%", thickness=1, color=HexColor("#DDDDDD"), spaceAfter=8, spaceBefore=4))
story.append(Paragraph(f"ManyFai  |  Service Agreement  |  {CLIENT_NAME}  |  April 2026", sFooter))

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
print(f"Contract PDF saved to {OUTPUT_FILE}")
