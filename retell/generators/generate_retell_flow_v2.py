#!/usr/bin/env python3
"""Generate Retell AI Conversational Flow Plan V2 — customized with High Tech AC intake form data."""

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
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "Retell_Flow_High_Tech_AC_FINAL.pdf")

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
PURPLE = HexColor("#6C5CE7")

# ─── STYLES ───────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

sTitle = ParagraphStyle("title", parent=styles["Title"], fontSize=20, leading=24,
                        textColor=DARK, alignment=TA_CENTER, spaceAfter=1, fontName="Helvetica-Bold")
sSubtitle = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=10, leading=13,
                           textColor=GRAY, alignment=TA_CENTER, spaceAfter=2)
sH1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=13, leading=16,
                      textColor=DARK, spaceAfter=3, spaceBefore=5, fontName="Helvetica-Bold")
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
sData = ParagraphStyle("data", parent=styles["Normal"], fontSize=8, leading=11,
                        textColor=DARK, fontName="Helvetica-Bold")
sDataValue = ParagraphStyle("dataValue", parent=styles["Normal"], fontSize=8, leading=11,
                             textColor=GRAY)
sImportant = ParagraphStyle("important", parent=styles["Normal"], fontSize=8.5, leading=12,
                             textColor=RED, fontName="Helvetica-Bold")

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def cyan_hr():
    return HRFlowable(width="100%", thickness=1.5, color=CYAN, spaceAfter=3, spaceBefore=1)

def bullet(text):
    return Paragraph(f"<bullet>&bull;</bullet> {text}", sBullet)

def arrow():
    return Paragraph("\u25bc", sArrow)

def flow_node(title, color, items, sarah_says=None):
    elements = []
    title_para = Paragraph(title, sNode)
    title_table = Table([[title_para]], colWidths=[5.5*inch])
    title_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(title_table)

    content = []
    for item in items:
        content.append(Paragraph(f"<bullet>&bull;</bullet> {item}", ParagraphStyle(
            "nb", parent=sNodeBody, leftIndent=14, bulletIndent=4, spaceAfter=1)))
    if sarah_says:
        content.append(Spacer(1, 2))
        content.append(Paragraph(f'Sarah says: <i>"{sarah_says}"</i>', sPrompt))

    content_table = Table([[content]], colWidths=[5.5*inch])
    content_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 1, color),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(content_table)
    return KeepTogether(elements)

def info_table(rows):
    """Key-value info table."""
    data = []
    for label, value in rows:
        data.append([
            Paragraph(f"<b>{label}</b>", ParagraphStyle("kl", parent=sBody, fontSize=8, textColor=DARK, fontName="Helvetica-Bold")),
            Paragraph(value, ParagraphStyle("kv", parent=sBody, fontSize=8, textColor=GRAY)),
        ])
    t = Table(data, colWidths=[1.8*inch, 4.2*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BG),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#DDDDDD")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t

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

# ==================== PAGE 1 — BUSINESS DATA + START OF FLOW ====================

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
story.append(Spacer(1, 0.08*inch))
story.append(logo_row)
story.append(Spacer(1, 0.05*inch))

story.append(Paragraph("Retell AI — Conversational Flow", sTitle))
story.append(HRFlowable(width="30%", thickness=3, color=CYAN, spaceAfter=4, spaceBefore=1))
story.append(Paragraph("High Tech Air Conditioning — Final Agent Build Guide", sSubtitle))
story.append(Spacer(1, 0.03*inch))

# ── Business Data Summary ──
story.append(cyan_hr())
story.append(Paragraph("Business Data (from Client Intake Form)", sH1))

story.append(info_table([
    ("Company Name", "High Tech Air Conditioning"),
    ("Main Phone", "(407) 837-7332"),
    ("Address", "6148 Hanging Moss Rd, Orlando, FL 32807"),
    ("Website", "www.hightechacfl.com"),
    ("Owner / Contact", "Alfredo Frassino"),
    ("Contact Phone", "(954) 669-6259"),
    ("Contact Email", "info@frassinogroup.com"),
]))
story.append(Spacer(1, 0.03*inch))

story.append(info_table([
    ("Office Hours", "Mon–Fri 7am–5pm, Sat 7am–3pm"),
    ("Service Hours", "Mon–Sun 6am–10pm"),
    ("After-Hours", "Yes — collect info, explain $120 emergency fee, transfer to tech if customer agrees"),
    ("Emergency Tech", "Keivin Rivero — (786) 532-8419"),
]))
story.append(Spacer(1, 0.03*inch))

story.append(info_table([
    ("Service Area", "Orlando, Winter Park, Winter Garden, Kissimmee, Davenport, Clermont, Windermere, Doctor Phillips, Celebration, Lake Buena Vista"),
    ("Services", "AC Repair, AC Install, Heating Repair, Heating Install, Maintenance, Ductwork, Thermostat, Indoor Air Quality, Commercial, New Construction, Mini-Splits"),
    ("Do NOT Book", "Duct Cleaning — collect info, tell caller we will call back with availability"),
    ("Emergencies", "No heat, no cool, water leak → collect info → transfer to Keivin Rivero"),
]))

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Retell Conversational Flow  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 2 — FLOW NODES 1-4 ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))
story.append(cyan_hr())
story.append(Paragraph("Conversational Flow — Step by Step", sH1))

# Node 1: Greeting
story.append(flow_node(
    "1. GREETING",
    CYAN_DARK,
    [
        "Agent picks up immediately — warm, professional tone",
        "Use the full company name: <b>High Tech Air Conditioning</b>",
        "Open with a question to understand why they're calling",
    ],
    "Thank you for calling High Tech Air Conditioning, this is Sarah. How can I help you today?"
))
story.append(arrow())

# Node 2: Emergency Check
story.append(flow_node(
    "2. EMERGENCY OR NORMAL VISIT?",
    RED,
    [
        "Listen for keywords: <b>no AC, no cool, no heat, water leak</b>",
        "If emergency → explain the <b>$120 emergency fee</b> before proceeding",
        "If customer <b>agrees</b> to the fee → collect info → transfer to <b>Keivin Rivero (786) 532-8419</b>",
        "If customer <b>declines</b> the fee → offer to schedule next available regular appointment",
        "If it sounds routine (maintenance, tune-up, repair, install) → continue to Node 3",
    ],
    "It sounds like this could be an emergency situation. We do have an emergency technician available — there is a $120 emergency service fee. Would you like me to connect you with our emergency tech right away?"
))
story.append(arrow())

# Node 3: Identify the Problem
story.append(flow_node(
    "3. IDENTIFY THE PROBLEM / SERVICE TYPE",
    BLUE,
    [
        "Ask what type of service they need",
        "Listen for: <b>AC repair, heating repair, maintenance, installation, thermostat, indoor air quality, mini-split, commercial</b>",
        'If caller says <b>"duct cleaning"</b> → do NOT book → say: <i>"Let me take down your information and we\'ll call you back shortly with availability for duct cleaning."</i>',
        "Get a brief description of the issue",
        "Do NOT diagnose or quote prices — just capture the problem",
    ],
    "What type of service do you need? Is this for your AC, heating, or something else?"
))
story.append(arrow())

# Node 4: Collect Customer Info (always)
story.append(flow_node(
    "4. COLLECT CUSTOMER INFORMATION",
    BLUE,
    [
        "Always collect info — no customer lookup",
        "Collect <b>first name</b> and <b>last name</b>",
        "Collect <b>phone number</b> — read it back to confirm",
        "Ask for <b>email address</b> — if they prefer not to share, that's okay",
        "Collect <b>service address</b>: street, city, state, zip code",
    ],
    "Let me get your information. Can I start with your first and last name?"
))

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Retell Conversational Flow  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 3 — FLOW NODES 5-8 ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))
story.append(cyan_hr())

# Node 5: Confirm Address + Service Area Check
story.append(flow_node(
    "5. CONFIRM ADDRESS &amp; SERVICE AREA CHECK",
    GREEN,
    [
        "Read back the full address to confirm it's correct",
        "Check if address is in service area: <b>Orlando, Winter Park, Winter Garden, Kissimmee, Davenport, Clermont, Windermere, Doctor Phillips, Celebration, Lake Buena Vista</b>",
        "If <b>outside service area</b> → <i>\"I'm sorry, that address may be outside our current service area. Let me have someone from our team confirm and call you back.\"</i>",
    ],
    "Just to confirm, the service address is [address] — is that correct?"
))
story.append(arrow())

# Node 6: Check Calendar
story.append(flow_node(
    "6. CHECK CALENDAR AVAILABILITY",
    BLUE,
    [
        "Call the <b>check_availability</b> tool",
        "If caller has a preferred date → pass as <b>preferred_date</b>",
        "Service hours: <b>Mon–Sun 6am–10pm</b>",
        "Offer <b>2-3 time windows</b> for the caller to choose from",
        "For emergencies where customer <b>declined the $120 fee</b>: offer next available regular slot",
    ],
    "Let me check what we have available... I have [Day] between [time] or [Day] between [time]. Which works better for you?"
))
story.append(arrow())

# Node 7: Book Appointment
story.append(flow_node(
    "7. BOOK THE APPOINTMENT",
    GREEN,
    [
        "Caller picks a time → call <b>create_appointment</b> tool",
        "Pass all collected data: name, phone, email, address, date, time, service type, notes",
        "Set <b>is_emergency = true</b> if it was flagged as emergency in Node 2",
        "Include problem description in <b>notes</b>",
    ],
    "I'm booking that for you right now..."
))

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Retell Conversational Flow  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 4 — NODES 9-10 + SPECIAL CASES + REFERENCES ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))
story.append(cyan_hr())

# Node 8: Confirmation
story.append(flow_node(
    "8. CONFIRMATION",
    CYAN_DARK,
    [
        "Read back full details: <b>date, time window, address, service type</b>",
        "Let them know they'll get a <b>confirmation text</b>",
        "Ask: <i>\"Is there anything else I can help with?\"</i>",
    ],
    "You're all set! I've got you down for [service] on [day] between [time] at [address]. You'll get a confirmation text shortly. Is there anything else I can help with?"
))
story.append(arrow())

# Node 9: Wrap Up
story.append(flow_node(
    "9. WRAP UP",
    DARK,
    [
        "Thank the caller by name if you have it",
        "Use the company name one more time",
    ],
    "Thank you for calling High Tech Air Conditioning! We look forward to helping you. Have a great day!"
))

story.append(Spacer(1, 0.12*inch))

# ── Special Scenarios ──
story.append(Paragraph("Special Scenarios", sH1))

special_data = [
    ["Scenario", "What Sarah Does"],
    ["Caller needs DUCT CLEANING",
     'Do NOT book. Say: "Let me take your info and we\'ll call you back shortly with duct cleaning availability." Collect name, phone, address.'],
    ["EMERGENCY — customer agrees\nto $120 fee",
     "Collect name, phone, address, problem. Transfer call directly to Keivin Rivero at (786) 532-8419."],
    ["EMERGENCY — customer declines\n$120 fee",
     '"I understand. Would you like me to schedule the next available regular appointment instead?"'],
    ["After-hours call\n(outside Mon-Fri 7-5 / Sat 7-3)",
     "Agent still answers 24/7. For emergencies: $120 fee + transfer. For non-urgent: book next available slot during service hours (6am-10pm)."],
    ["Caller asks for a price / quote",
     '"Our technician will provide upfront pricing on-site before any work begins, so there are never any surprises. Would you like me to get you scheduled?"'],
    ["Caller is outside service area",
     '"I\'m sorry, that address may be outside our service area. Let me have our team confirm and call you back. Can I get your phone number?"'],
    ["Caller asks a question Sarah\ncan't answer",
     '"That\'s a great question — I want to make sure you get the right answer. I\'ll have someone from our team call you back. Can I confirm your number?"'],
]
special_table = Table(special_data, colWidths=[1.8*inch, 4.2*inch])
special_table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), DARK),
    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, 0), 8.5),
    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE", (0, 1), (-1, -1), 7.5),
    ("LEADING", (0, 1), (-1, -1), 10),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#DDDDDD")),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
]))
story.append(special_table)

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Retell Conversational Flow  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 5 — DECISION PATHS + TOOLS ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))
story.append(cyan_hr())

# ── Decision Paths ──
story.append(Paragraph("Decision Paths — Quick Reference", sH1))

ref_data = [
    ["Scenario", "Path Through Flow"],
    ["Normal visit",
     "1 \u2192 2 (normal) \u2192 3 \u2192 4 (collect info) \u2192 5 \u2192 6 \u2192 7 \u2192 8 \u2192 9"],
    ["Emergency — agrees to $120 fee",
     "1 \u2192 2 (emergency, agrees) \u2192 4 (collect info) \u2192 TRANSFER to Keivin (786) 532-8419"],
    ["Emergency — declines $120 fee",
     "1 \u2192 2 (emergency, declines) \u2192 3 \u2192 4 \u2192 5 \u2192 6 \u2192 7 \u2192 8 \u2192 9"],
    ["Duct cleaning request",
     "1 \u2192 2 (normal) \u2192 3 (duct cleaning) \u2192 4 (collect info) \u2192 \"We'll call back with availability\""],
    ["Outside service area",
     "1 \u2192 2 \u2192 3 \u2192 4 \u2192 5 (outside area) \u2192 \"We'll confirm and call you back\""],
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
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
]))
story.append(ref_table)

story.append(Spacer(1, 0.1*inch))

# ── Retell Tools ──
story.append(Paragraph("Retell Tools to Configure", sH1))

tools_data = [
    ["Tool Name", "When to Call", "Key Parameters"],
    ["check_availability",
     "After collecting info, before booking",
     "preferred_date (optional, YYYY-MM-DD)"],
    ["create_appointment",
     "After caller picks a time slot",
     "date, start_time, end_time, service_type,\nis_emergency, name, phone, email, address, notes"],
    ["transfer_call",
     "Emergency — customer agrees to $120 fee",
     "Transfer to Keivin Rivero\n(786) 532-8419"],
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

story.append(Spacer(1, 0.12*inch))

# ── Key Data for Agent Prompt ──
story.append(Paragraph("Key Data to Paste Into Retell Agent Prompt", sH1))

prompt_data = [
    ["Field", "Value"],
    ["Company Name", "High Tech Air Conditioning"],
    ["Agent Name", "Sarah"],
    ["Office Hours", "Mon–Fri 7am–5pm, Sat 7am–3pm"],
    ["Service Hours", "Mon–Sun 6am–10pm"],
    ["Emergency Fee", "$120"],
    ["Emergency Tech", "Keivin Rivero — (786) 532-8419"],
    ["Service Area", "Orlando, Winter Park, Winter Garden, Kissimmee, Davenport, Clermont, Windermere, Doctor Phillips, Celebration, Lake Buena Vista"],
    ["Do NOT Book", "Duct Cleaning — take info, promise callback"],
    ["Do NOT Quote", "Never give prices — tech provides upfront pricing on-site"],
]
prompt_table = Table(prompt_data, colWidths=[1.5*inch, 4.5*inch])
prompt_table.setStyle(TableStyle([
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
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
]))
story.append(prompt_table)

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
