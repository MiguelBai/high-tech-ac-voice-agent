#!/usr/bin/env python3
"""Generate Retell AI Conversational Flow Plan PDF for High Tech Air Conditioning."""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MANYFAI_LOGO = "/Users/miguelbarbosa/Desktop/pics/logo.png"
HTAC_LOGO = "/Users/miguelbarbosa/ANTIGRAVITY V1 TEST/HVAC Retell/.firecrawl/hightechac-logo.png"
OUTPUT_DIR = "/Users/miguelbarbosa/ANTIGRAVITY V1 TEST/HVAC Retell"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "Retell_Conversational_Flow_Plan.pdf")

CYAN = HexColor("#00E5CC")
DARK = HexColor("#1A1A2E")
GRAY = HexColor("#555555")
LIGHT_BG = HexColor("#F0FFFE")
CYAN_DARK = HexColor("#00B8A9")
WHITE = white
ORANGE = HexColor("#FF6B35")
RED = HexColor("#E63946")
GREEN = HexColor("#2D936C")
BLUE = HexColor("#457B9D")

# ─── STYLES ───────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

sTitle = ParagraphStyle("title", parent=styles["Title"], fontSize=20, leading=24,
                        textColor=DARK, alignment=TA_CENTER, spaceAfter=1, fontName="Helvetica-Bold")
sSubtitle = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=10, leading=13,
                           textColor=GRAY, alignment=TA_CENTER, spaceAfter=2)
sH1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=13, leading=16,
                      textColor=DARK, spaceAfter=3, spaceBefore=6, fontName="Helvetica-Bold")
sH2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=10, leading=13,
                      textColor=DARK, spaceAfter=2, spaceBefore=3, fontName="Helvetica-Bold")
sBody = ParagraphStyle("body", parent=styles["Normal"], fontSize=8.5, leading=11.5,
                        textColor=GRAY, spaceAfter=1.5)
sBullet = ParagraphStyle("bullet", parent=sBody, leftIndent=16, bulletIndent=5, spaceAfter=0.5)
sFooter = ParagraphStyle("footer", parent=styles["Normal"], fontSize=7.5, leading=10,
                          textColor=GRAY, alignment=TA_CENTER)
sNode = ParagraphStyle("node", parent=styles["Normal"], fontSize=8, leading=11,
                        textColor=WHITE, alignment=TA_CENTER, fontName="Helvetica-Bold")
sNodeBody = ParagraphStyle("nodeBody", parent=styles["Normal"], fontSize=7.5, leading=10,
                            textColor=GRAY)
sPrompt = ParagraphStyle("prompt", parent=styles["Normal"], fontSize=8, leading=11,
                          textColor=DARK, fontName="Helvetica-Oblique", leftIndent=10)
sArrow = ParagraphStyle("arrow", parent=styles["Normal"], fontSize=14, leading=16,
                         textColor=CYAN_DARK, alignment=TA_CENTER, fontName="Helvetica-Bold")

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def cyan_hr():
    return HRFlowable(width="100%", thickness=1.5, color=CYAN, spaceAfter=3, spaceBefore=1)

def bullet(text):
    return Paragraph(f"<bullet>&bull;</bullet> {text}", sBullet)

def arrow():
    return Paragraph("\u25bc", sArrow)

def flow_node(title, color, items, sarah_says=None):
    """Create a visual flow node box."""
    elements = []
    # Title bar
    title_para = Paragraph(title, sNode)
    title_table = Table([[title_para]], colWidths=[5.5*inch])
    title_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(title_table)

    # Content
    content = []
    for item in items:
        content.append(Paragraph(f"<bullet>&bull;</bullet> {item}", ParagraphStyle(
            "nb", parent=sNodeBody, leftIndent=14, bulletIndent=4, spaceAfter=1)))
    if sarah_says:
        content.append(Spacer(1, 2))
        content.append(Paragraph(f'Sarah says: "{sarah_says}"', sPrompt))

    content_table = Table([[content]], colWidths=[5.5*inch])
    content_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 1, color),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(content_table)
    return KeepTogether(elements)

def page_header():
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

# ==================== PAGE 1 — COVER + MAIN FLOW ====================

# Dual logo header
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

story.append(Paragraph("Retell AI — Conversational Flow Plan", sTitle))
story.append(HRFlowable(width="30%", thickness=3, color=CYAN, spaceAfter=4, spaceBefore=1))
story.append(Paragraph("High Tech Air Conditioning — Agent Build Guide", sSubtitle))
story.append(Spacer(1, 0.06*inch))

# Overview
story.append(cyan_hr())
story.append(Paragraph("Flow Overview", sH1))
story.append(Paragraph(
    "This document maps the complete conversational flow for the Retell AI agent (Sarah). "
    "Use this as your guide when building the agent in the Retell dashboard. Each node below "
    "represents a step in the conversation tree.",
    sBody
))
story.append(Spacer(1, 0.04*inch))

# ── FLOW NODES ──

# Node 1: Greeting
story.append(flow_node(
    "1. GREETING",
    CYAN_DARK,
    [
        "Agent picks up the call immediately",
        "Warm, professional greeting using the company name",
        "Open-ended question to understand the caller's need",
    ],
    "Thank you for calling High Tech Air Conditioning, this is Sarah. How can I help you today?"
))
story.append(arrow())

# Node 2: Emergency Check
story.append(flow_node(
    "2. EMERGENCY OR NORMAL VISIT?",
    RED,
    [
        "Listen for urgency keywords: <b>no AC, no heat, gas smell, carbon monoxide, flooding, water leak, pipe burst</b>",
        "If caller mentions any of these → flag as <b>EMERGENCY</b> → skip to Node 4 (collect info fast)",
        "If it sounds routine (maintenance, tune-up, repair, installation) → <b>NORMAL</b> → continue to Node 3",
        "If unclear, ask directly: is this an urgent situation?",
    ],
    "Is this something urgent, or would you like to schedule a regular service visit?"
))
story.append(arrow())

# Node 3: What's the Problem
story.append(flow_node(
    "3. IDENTIFY THE PROBLEM / SERVICE TYPE",
    BLUE,
    [
        "Ask what type of service they need",
        "Listen for: <b>AC repair, heating repair, maintenance/tune-up, installation/replacement, ductwork, thermostat, indoor air quality</b>",
        "Get a brief description of the issue (e.g., \"AC is blowing warm air\", \"furnace won't turn on\")",
        "Do NOT diagnose or troubleshoot — just capture the problem",
        "Save this as the <b>service_type</b> and <b>notes</b> for the appointment",
    ],
    "What type of service do you need? Is this for your AC, heating, or something else?"
))

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Retell Conversational Flow  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 2 — CONTINUED FLOW ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))
story.append(cyan_hr())

# Node 4: Existing or New Customer
story.append(flow_node(
    "4. EXISTING OR NEW CUSTOMER?",
    CYAN_DARK,
    [
        "Ask if they've used High Tech AC before",
        "If <b>YES</b> → ask for name or phone number → call <b>lookup_customer</b> tool",
        "If <b>NO</b> → go to Node 5 to collect their information",
        "If existing customer found → skip to Node 6 (already have address on file)",
    ],
    "Have you used High Tech Air Conditioning before?"
))
story.append(arrow())

# Node 5: Collect Customer Info
story.append(flow_node(
    "5. COLLECT CUSTOMER INFORMATION (New Customers)",
    BLUE,
    [
        "Collect <b>first name</b> and <b>last name</b>",
        "Collect <b>phone number</b> — read it back to confirm",
        "Collect <b>email address</b> (optional — if they don't want to give it, that's fine)",
        "Collect <b>service address</b>: street, city, state, zip code",
        "Confirm the address by reading it back",
    ],
    "Great, let me get your information. Can I start with your first and last name?"
))
story.append(arrow())

# Node 6: Address Confirmation
story.append(flow_node(
    "6. CONFIRM SERVICE ADDRESS",
    GREEN,
    [
        "For existing customers: confirm the address on file is correct — \"Is [address] still the right address?\"",
        "For new customers: read back the address they just gave",
        "If address is <b>outside service area</b> (Orlando, Windermere, Celebration, Winter Garden, surrounding counties) → let them know and offer a callback",
        "If address is good → continue to Node 7",
    ],
    "Just to confirm, the service address is [address] — is that correct?"
))
story.append(arrow())

# Node 7: Check Calendar
story.append(flow_node(
    "7. CHECK CALENDAR AVAILABILITY",
    BLUE,
    [
        "Call the <b>check_availability</b> tool",
        "If caller has a preferred date → pass it as <b>preferred_date</b>",
        "If no preference → tool returns next available slots",
        "Offer <b>2-3 time windows</b> for the caller to choose from",
        "For <b>EMERGENCY</b>: offer the <b>next available priority slot</b> (same day or next morning)",
        "Time windows are typically 2-4 hour arrival windows (e.g., \"between 8am and 12pm\")",
    ],
    "Let me check what we have available... I have [Day] between [time] or [Day] between [time]. Which works better for you?"
))

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Retell Conversational Flow  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 3 — BOOKING + SUMMARY ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))
story.append(cyan_hr())

# Node 8: Book Appointment
story.append(flow_node(
    "8. BOOK THE APPOINTMENT",
    GREEN,
    [
        "Caller picks a time slot",
        "Call the <b>create_appointment</b> tool with all collected data:",
        "&nbsp;&nbsp;&nbsp; - customer_id / address_id (existing) OR name, phone, email, address (new)",
        "&nbsp;&nbsp;&nbsp; - date, start_time, end_time",
        "&nbsp;&nbsp;&nbsp; - service_type (from Node 3)",
        "&nbsp;&nbsp;&nbsp; - is_emergency (true/false from Node 2)",
        "&nbsp;&nbsp;&nbsp; - notes (problem description from Node 3)",
        "Tool books the appointment in Housecall Pro",
    ],
    "I'm booking that for you right now..."
))
story.append(arrow())

# Node 9: Confirmation
story.append(flow_node(
    "9. CONFIRMATION",
    CYAN_DARK,
    [
        "Read back the full appointment details: <b>date, time window, address, service type</b>",
        "Let them know they'll receive a <b>confirmation text</b>",
        "Ask if there's <b>anything else</b> they need",
        "For emergencies: reassure them a tech will be there ASAP",
    ],
    "You're all set! I've got you down for [service] on [day] between [time] at [address]. You'll get a confirmation text shortly. Is there anything else I can help with?"
))
story.append(arrow())

# Node 10: Wrap Up
story.append(flow_node(
    "10. WRAP UP & END CALL",
    DARK,
    [
        "Thank the caller",
        "Use the company name one more time",
        "Friendly sign-off",
    ],
    "Thank you for calling High Tech Air Conditioning! We look forward to helping you. Have a great day!"
))

story.append(Spacer(1, 0.15*inch))

# ── Decision Tree Summary Table ──
story.append(Paragraph("Quick Decision Reference", sH1))

ref_data = [
    ["Scenario", "Path Through Flow"],
    ["Normal visit — new customer",
     "1 → 2 (normal) → 3 → 4 (no) → 5 → 6 → 7 → 8 → 9 → 10"],
    ["Normal visit — existing customer",
     "1 → 2 (normal) → 3 → 4 (yes, lookup) → 6 → 7 → 8 → 9 → 10"],
    ["Emergency — new customer",
     "1 → 2 (emergency) → 3 → 4 (no) → 5 → 6 → 7 (priority) → 8 → 9 → 10"],
    ["Emergency — existing customer",
     "1 → 2 (emergency) → 3 → 4 (yes, lookup) → 6 → 7 (priority) → 8 → 9 → 10"],
]
ref_table = Table(ref_data, colWidths=[2.2*inch, 3.8*inch])
ref_table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), DARK),
    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, 0), 8.5),
    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE", (0, 1), (-1, -1), 8),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#DDDDDD")),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
]))
story.append(ref_table)

story.append(Spacer(1, 0.1*inch))

# ── Retell Tools Reference ──
story.append(Paragraph("Retell Tools to Configure", sH1))

tools_data = [
    ["Tool Name", "When to Call", "Key Parameters"],
    ["lookup_customer",
     "When caller says they're an existing customer",
     "search_query (name or phone)"],
    ["check_availability",
     "After collecting info, before booking",
     "preferred_date (optional, YYYY-MM-DD)"],
    ["create_appointment",
     "After caller picks a time slot",
     "date, start_time, end_time, service_type,\nis_emergency, customer info, notes"],
]
tools_table = Table(tools_data, colWidths=[1.3*inch, 2.2*inch, 2.5*inch])
tools_table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), DARK),
    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, 0), 8.5),
    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE", (0, 1), (-1, -1), 7.5),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#DDDDDD")),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
]))
story.append(tools_table)

story.append(Spacer(1, 6))
story.append(Paragraph("ManyFai  |  Retell Conversational Flow  |  High Tech Air Conditioning", sFooter))

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
