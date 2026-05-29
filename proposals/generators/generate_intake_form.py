#!/usr/bin/env python3
"""Generate Client Intake Form PDF — collects all info needed to build the Retell AI voice agent."""

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
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "Client_Intake_Form_High_Tech_AC.pdf")

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
sH1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=13, leading=16,
                      textColor=DARK, spaceAfter=3, spaceBefore=6, fontName="Helvetica-Bold")
sBody = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=12,
                        textColor=GRAY, spaceAfter=1.5)
sFooter = ParagraphStyle("footer", parent=styles["Normal"], fontSize=7.5, leading=10,
                          textColor=GRAY, alignment=TA_CENTER)
sIntro = ParagraphStyle("intro", parent=sBody, fontSize=9, leading=12.5, textColor=GRAY, spaceAfter=4)
sQuestion = ParagraphStyle("question", parent=styles["Normal"], fontSize=9, leading=12,
                            textColor=DARK, fontName="Helvetica-Bold", spaceAfter=1)
sHint = ParagraphStyle("hint", parent=styles["Normal"], fontSize=7.5, leading=10,
                        textColor=HexColor("#888888"), fontName="Helvetica-Oblique", spaceAfter=1)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def cyan_hr():
    return HRFlowable(width="100%", thickness=1.5, color=CYAN, spaceAfter=3, spaceBefore=1)

def section_header(num, title):
    return Paragraph(f"{num}. {title}", sH1)

def question_block(q_text, hint=None, lines=2):
    """A question with an answer area."""
    elements = []
    elements.append(Paragraph(q_text, sQuestion))
    if hint:
        elements.append(Paragraph(hint, sHint))
    # Answer lines
    blank = "_" * 95
    line_style = ParagraphStyle("line", parent=sBody, fontSize=9, textColor=HexColor("#CCCCCC"), spaceAfter=4)
    for _ in range(lines):
        elements.append(Paragraph(blank, line_style))
    elements.append(Spacer(1, 2))
    return KeepTogether(elements)

def checkbox_question(q_text, options, hint=None, columns=2):
    """A question with checkbox options."""
    elements = []
    elements.append(Paragraph(q_text, sQuestion))
    if hint:
        elements.append(Paragraph(hint, sHint))

    box = "\u2610"  # empty checkbox
    opt_style = ParagraphStyle("opt", parent=sBody, fontSize=8.5, textColor=GRAY, spaceAfter=0)

    if columns == 2:
        rows = []
        for i in range(0, len(options), 2):
            left = f"{box}  {options[i]}"
            right = f"{box}  {options[i+1]}" if i + 1 < len(options) else ""
            rows.append([Paragraph(left, opt_style), Paragraph(right, opt_style)])
        t = Table(rows, colWidths=[3*inch, 3*inch])
        t.setStyle(TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
    else:
        for opt in options:
            elements.append(Paragraph(f"{box}  {opt}", opt_style))

    elements.append(Spacer(1, 4))
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

# ==================== PAGE 1 ====================

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

story.append(Paragraph("AI Voice Agent — Client Intake Form", sTitle))
story.append(HRFlowable(width="30%", thickness=3, color=CYAN, spaceAfter=4, spaceBefore=1))
story.append(Paragraph("Please fill out the information below so we can build your custom AI phone agent.", sSubtitle))
story.append(Spacer(1, 0.04*inch))

story.append(Paragraph(
    "This form helps us understand your business, services, and preferences so your AI agent sounds "
    "and acts exactly like a member of your team. The more detail you provide, the better your agent "
    "will perform from day one. Most questions take just a few words — don't overthink it!",
    sIntro
))

# ── Section 1: Business Info ──
story.append(cyan_hr())
story.append(section_header(1, "Business Information"))

story.append(question_block("Company name (as you want the agent to say it on calls):", lines=1))
story.append(question_block("Company phone number (the main line the agent will answer):", lines=1))
story.append(question_block("Company address:", lines=1))
story.append(question_block("Company website:", lines=1))
story.append(question_block("Owner / main point of contact name:", lines=1))
story.append(question_block("Best phone number to reach you:", lines=1))
story.append(question_block("Best email to reach you:", lines=1))

# ── Section 2: Business Hours ──
story.append(section_header(2, "Business Hours"))

story.append(question_block("What are your office hours?",
    hint="e.g., Mon-Fri 8am-5pm, Sat 9am-1pm", lines=1))
story.append(question_block("What are your service/dispatch hours?",
    hint="e.g., Mon-Sat 7am-7pm", lines=1))
story.append(question_block("Do you offer after-hours or weekend emergency service?",
    hint="If yes, how should emergency calls be handled outside business hours?", lines=2))

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Client Intake Form  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 2 ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))

# ── Section 3: Service Area ──
story.append(cyan_hr())
story.append(section_header(3, "Service Area"))

story.append(question_block("What cities, counties, or zip codes do you serve?",
    hint="List all areas your techs will travel to.", lines=3))
story.append(question_block("Are there any areas you do NOT service?",
    hint="e.g., certain zip codes, counties, or distances.", lines=2))

# ── Section 4: Services Offered ──
story.append(section_header(4, "Services You Offer"))

story.append(checkbox_question(
    "Which services do you offer? (check all that apply)",
    [
        "AC Repair",
        "AC Installation / Replacement",
        "Heating / Furnace Repair",
        "Heating Installation / Replacement",
        "Maintenance / Tune-Up",
        "Ductwork / Duct Cleaning",
        "Thermostat Repair / Installation",
        "Indoor Air Quality",
        "Commercial HVAC",
        "New Construction",
        "Mini-Split / Ductless Systems",
        "Other (write below)",
    ]
))
story.append(question_block("If you checked \"Other\", please describe:", lines=1))

story.append(question_block("Do you serve both residential and commercial customers?", lines=1))

story.append(question_block("Are there any services you do NOT want the agent to book?",
    hint="e.g., new construction, commercial — anything that needs a different process.", lines=2))

# ── Section 5: Emergency Handling ──
story.append(section_header(5, "Emergency Calls"))

story.append(question_block("What do you consider an emergency call?",
    hint="e.g., no heat in winter, no AC in summer, gas smell, water leak, carbon monoxide alarm.", lines=2))
story.append(question_block("When there's an emergency, what should happen?",
    hint="e.g., transfer to an on-call tech, text a specific number, book the next available slot.", lines=2))
story.append(question_block("On-call technician name and phone number (for emergency transfers):", lines=1))

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Client Intake Form  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 3 ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))

# ── Section 6: Scheduling Preferences ──
story.append(cyan_hr())
story.append(section_header(6, "Scheduling &amp; Appointments"))

story.append(question_block("What scheduling / calendar system do you use?",
    hint="e.g., Housecall Pro, ServiceTitan, Google Calendar, Jobber, other.", lines=1))

story.append(question_block("What are your typical appointment time windows?",
    hint="e.g., 8am-12pm, 12pm-4pm, or specific 2-hour windows.", lines=1))

story.append(question_block("How far in advance can appointments be booked?",
    hint="e.g., same day, next day, up to 2 weeks out.", lines=1))

story.append(question_block("How long is a typical service visit?",
    hint="e.g., 1 hour for maintenance, 2-4 hours for repairs.", lines=1))

story.append(question_block("Are there any days or times you do NOT want appointments booked?",
    hint="e.g., no Sundays, no appointments after 4pm on Fridays.", lines=2))

# ── Section 7: Pricing & Quotes ──
story.append(section_header(7, "Pricing &amp; Quotes"))

story.append(question_block(
    "Should the agent give pricing or quotes over the phone?",
    hint="Most HVAC companies prefer NOT to quote over the phone. We recommend saying: "
         "\"Our technician will provide upfront pricing on-site before any work begins.\"",
    lines=1
))

story.append(question_block("Do you charge a service call / diagnostic fee? If so, how much?",
    hint="e.g., $89 diagnostic fee, waived if they proceed with repair.", lines=1))

story.append(question_block("Is there anything about pricing the agent SHOULD mention?",
    hint="e.g., free estimates on replacements, seasonal specials, military discount.", lines=2))

# ── Section 8: Brand Voice & Personality ──
story.append(section_header(8, "Brand Voice &amp; Personality"))

story.append(question_block("How would you describe your company's personality?",
    hint="e.g., friendly and casual, professional and polished, southern hospitality, family-owned feel.", lines=2))

story.append(question_block("What name should the AI agent use?",
    hint="e.g., Sarah, Jessica, Mike — or we can pick one for you.", lines=1))

story.append(checkbox_question(
    "Should the agent's voice be:",
    ["Female", "Male", "No preference"],
    columns=2
))

story.append(question_block("Is there anything the agent should ALWAYS say?",
    hint="e.g., a tagline, a thank-you line, mention a current promotion.", lines=2))

story.append(Spacer(1, 3))
story.append(Paragraph("ManyFai  |  Client Intake Form  |  High Tech Air Conditioning", sFooter))

# ==================== PAGE 4 ====================
story.append(PageBreak())
story.append(page_header())
story.append(Spacer(1, 4))

# ── Section 9: Common Caller Questions ──
story.append(cyan_hr())
story.append(section_header(9, "Common Caller Questions"))

story.append(Paragraph(
    "What are the most common questions callers ask? Write the question and how you'd want the agent to answer it. "
    "We'll program these into the agent so it sounds like your team.",
    sIntro
))

for i in range(1, 6):
    story.append(question_block(f"Q{i}:", lines=1))
    story.append(question_block(f"Answer:", lines=1))

# ── Section 10: Anything Else ──
story.append(section_header(10, "Anything Else We Should Know"))

story.append(question_block(
    "Is there anything else you want the agent to know about your business?",
    hint="Special instructions, things to avoid saying, VIP customers, competitor names to never mention, etc.",
    lines=4
))

story.append(question_block(
    "How should the agent handle calls it can't resolve?",
    hint="e.g., take a message, transfer to a specific number, promise a callback within 1 hour.",
    lines=2
))

story.append(Spacer(1, 0.15*inch))
story.append(HRFlowable(width="60%", thickness=1, color=HexColor("#DDDDDD"), spaceAfter=6, spaceBefore=4))
story.append(Paragraph(
    "Thank you for filling this out! Once we receive your answers, we'll have your AI agent "
    "built and ready for testing within 3-5 business days.",
    ParagraphStyle("thanks", parent=sBody, fontSize=9, textColor=CYAN_DARK, alignment=TA_CENTER, fontName="Helvetica-Bold")
))
story.append(Spacer(1, 4))
story.append(Paragraph("ManyFai  |  Client Intake Form  |  High Tech Air Conditioning", sFooter))

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
