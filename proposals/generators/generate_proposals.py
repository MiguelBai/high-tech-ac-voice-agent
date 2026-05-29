#!/usr/bin/env python3
"""Generate two PDF proposals for HVAC Voice AI Agent service."""

from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import os

BASE_DIR = "/Users/miguelbarbosa/ANTIGRAVITY V1 TEST/HVAC Retell"

# Brand colors
DARK = HexColor("#1a1a2e")
PRIMARY = HexColor("#16213e")
ACCENT = HexColor("#0f3460")
HIGHLIGHT = HexColor("#e94560")
LIGHT_BG = HexColor("#f8f9fa")
LIGHT_GRAY = HexColor("#e9ecef")
MEDIUM_GRAY = HexColor("#6c757d")
GREEN = HexColor("#28a745")
BLUE = HexColor("#007bff")


def get_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "MainTitle", fontSize=28, leading=34, textColor=DARK,
        fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        "Subtitle", fontSize=14, leading=18, textColor=MEDIUM_GRAY,
        fontName="Helvetica", alignment=TA_CENTER, spaceAfter=20
    ))
    styles.add(ParagraphStyle(
        "SectionHead", fontSize=18, leading=22, textColor=DARK,
        fontName="Helvetica-Bold", spaceBefore=20, spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        "SubHead", fontSize=13, leading=17, textColor=ACCENT,
        fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        "BodyText2", fontSize=10.5, leading=15, textColor=HexColor("#333333"),
        fontName="Helvetica", spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        "BulletCustom", fontSize=10.5, leading=15, textColor=HexColor("#333333"),
        fontName="Helvetica", leftIndent=20, bulletIndent=8, spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        "SmallNote", fontSize=9, leading=12, textColor=MEDIUM_GRAY,
        fontName="Helvetica-Oblique", spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        "BigNumber", fontSize=36, leading=40, textColor=HIGHLIGHT,
        fontName="Helvetica-Bold", alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        "PriceLabel", fontSize=11, leading=14, textColor=MEDIUM_GRAY,
        fontName="Helvetica", alignment=TA_CENTER, spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        "Footer", fontSize=8, leading=10, textColor=MEDIUM_GRAY,
        fontName="Helvetica", alignment=TA_CENTER
    ))
    return styles


def styled_table(data, col_widths, header=True):
    """Create a consistently styled table."""
    t = Table(data, colWidths=col_widths)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT_BG))
    t.setStyle(TableStyle(style_cmds))
    return t


def divider():
    return HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY, spaceAfter=10, spaceBefore=10)


# ============================================================
# INTERNAL PROPOSAL (for you)
# ============================================================
def generate_internal_proposal():
    path = os.path.join(BASE_DIR, "INTERNAL_Proposal_HVAC_Voice_Agent.pdf")
    doc = SimpleDocTemplate(path, pagesize=letter,
                            topMargin=0.75*inch, bottomMargin=0.75*inch,
                            leftMargin=0.85*inch, rightMargin=0.85*inch)
    s = get_styles()
    story = []

    # Title page
    story.append(Spacer(1, 1.5*inch))
    story.append(Paragraph("INTERNAL BUSINESS ANALYSIS", s["MainTitle"]))
    story.append(Paragraph("HVAC AI Voice Agent Service", s["Subtitle"]))
    story.append(Spacer(1, 0.3*inch))
    story.append(HRFlowable(width="40%", thickness=2, color=HIGHLIGHT, spaceAfter=20))
    story.append(Paragraph("Cost Breakdown &bull; Pricing Strategy &bull; Profit Analysis", s["Subtitle"]))
    story.append(Spacer(1, 0.4*inch))
    story.append(Paragraph("CONFIDENTIAL &mdash; For Internal Use Only", s["SmallNote"]))
    story.append(Paragraph("Prepared: March 2026", s["SmallNote"]))
    story.append(PageBreak())

    # ---- Section 1: Platform Comparison ----
    story.append(Paragraph("1. Platform Comparison: Vapi vs Retell", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("Both platforms offer pay-as-you-go pricing with no monthly minimums. Here's a side-by-side comparison:", s["BodyText2"]))
    story.append(Spacer(1, 6))

    comp_data = [
        ["Feature", "Vapi", "Retell"],
        ["Platform Fee", "$0.05/min", "$0.055/min (incl. STT)"],
        ["STT Cost", "$0.01/min (Deepgram)", "Included in platform fee"],
        ["LLM (GPT-4.1)", "~$0.03-0.06/min", "$0.045/min"],
        ["TTS (Standard)", "$0.022/min (Vapi Voices)", "$0.015/min (Platform Voices)"],
        ["TTS (ElevenLabs)", "$0.036/min", "$0.040/min"],
        ["Telephony (US)", "Free (Vapi numbers)", "$0.015/min (Twilio/Telnyx)"],
        ["Total (Basic Stack)", "$0.11 - $0.14/min", "$0.13/min"],
        ["Total (Premium Stack)", "$0.15 - $0.20/min", "$0.17 - $0.22/min"],
        ["Free Credits", "$10", "$10"],
        ["Concurrency (Free)", "10 lines", "20 lines"],
        ["Phone Numbers", "10 free US numbers", "$2/mo per number"],
        ["Billing Granularity", "Per-minute", "Per-second"],
    ]
    story.append(styled_table(comp_data, [1.8*inch, 2.2*inch, 2.2*inch]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Recommendation:</b> Retell is the better choice for this use case.", s["BodyText2"]))
    story.append(Paragraph("&bull; Simpler pricing (all-inclusive per-minute)", s["BulletCustom"]))
    story.append(Paragraph("&bull; Per-second billing saves money on short calls", s["BulletCustom"]))
    story.append(Paragraph("&bull; 20 free concurrent lines (vs 10 on Vapi)", s["BulletCustom"]))
    story.append(Paragraph("&bull; Clean dashboard with call analytics built in", s["BulletCustom"]))
    story.append(Paragraph("&bull; Better documentation and easier setup", s["BulletCustom"]))

    # ---- Section 2: Your Actual Costs ----
    story.append(PageBreak())
    story.append(Paragraph("2. Your Actual Cost to Run (Per Client)", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("<b>Recommended Stack (Retell):</b>", s["SubHead"]))
    cost_data = [
        ["Component", "Provider", "Cost/Min"],
        ["Platform + STT", "Retell", "$0.055"],
        ["LLM", "GPT-4.1", "$0.045"],
        ["TTS", "Retell Platform Voices", "$0.015"],
        ["Telephony", "Retell Twilio (US)", "$0.015"],
        ["TOTAL PER MINUTE", "", "$0.13"],
    ]
    t = styled_table(cost_data, [2*inch, 2.2*inch, 1.5*inch])
    # Bold last row
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, -1), (-1, -1), ACCENT),
        ("TEXTCOLOR", (0, -1), (-1, -1), white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Monthly Fixed Costs:</b>", s["SubHead"]))
    fixed_data = [
        ["Item", "Cost"],
        ["Phone Number (1 US number)", "$2/month"],
        ["Knowledge Base (if used)", "Free (first 10)"],
        ["Your Time (maintenance ~2hrs/mo)", "Your labor"],
        ["Total Fixed", "~$2/month + your time"],
    ]
    story.append(styled_table(fixed_data, [3.5*inch, 2.5*inch]))

    # ---- Section 3: Cost Projections ----
    story.append(Spacer(1, 15))
    story.append(Paragraph("3. Monthly Cost Projections by Call Volume", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("Assuming average call duration of 2.5 minutes:", s["BodyText2"]))
    proj_data = [
        ["Scenario", "Calls/Mo", "Minutes", "Your Cost", "Revenue @$349", "Profit"],
        ["Low Volume", "100", "250", "$32.50", "$349", "$316.50"],
        ["Small HVAC", "200", "500", "$65.00", "$349", "$284.00"],
        ["Medium HVAC", "300", "750", "$97.50", "$349", "$251.50"],
        ["Busy Season", "500", "1,250", "$162.50", "$349 + overage", "$186.50+"],
        ["High Volume", "700", "1,750", "$227.50", "$349 + overage", "Varies"],
    ]
    t = styled_table(proj_data, [1.1*inch, 0.8*inch, 0.8*inch, 1*inch, 1.3*inch, 1*inch])
    story.append(t)

    # ---- Section 4: Pricing Strategy ----
    story.append(PageBreak())
    story.append(Paragraph("4. Pricing Strategy &mdash; Two Options", s["SectionHead"]))
    story.append(divider())

    # Option A
    story.append(Paragraph("OPTION A: Your Original Pricing", s["SubHead"]))
    oa_data = [
        ["Item", "Price", "Notes"],
        ["Setup Fee", "$749 (one-time)", "Covers your build time (~8-15 hrs)"],
        ["Monthly Fee", "$349/month", "Includes 500 minutes"],
        ["Overage Rate", "$0.25/minute", "After 500 min exceeded"],
        ["Your Cost (500 min)", "$65/month", "At $0.13/min"],
        ["Your Margin (Monthly)", "$284/month", "81% margin"],
        ["Your Margin (Setup)", "$749", "Minus your labor"],
    ]
    t = styled_table(oa_data, [1.5*inch, 1.5*inch, 3*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, -2), (-1, -1), HexColor("#e8f5e9")),
        ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Analysis:</b> This is a solid starting point. The $749 setup is on the lower end for custom-built voice agents (agencies typically charge $2,000-$5,000). The $349/month is competitive in the mid-market range. You're leaving money on the table on the setup fee, but the monthly recurring revenue is where the real value is.", s["BodyText2"]))

    story.append(Spacer(1, 15))

    # Option B
    story.append(Paragraph("OPTION B: Recommended Pricing (Higher Value)", s["SubHead"]))
    ob_data = [
        ["Item", "Price", "Notes"],
        ["Setup Fee", "$1,497 (one-time)", "Positions as premium/custom solution"],
        ["Monthly Fee", "$397/month", "Includes 750 minutes"],
        ["Overage Rate", "$0.22/minute", "Competitive vs hiring staff"],
        ["Your Cost (750 min)", "$97.50/month", "At $0.13/min"],
        ["Your Margin (Monthly)", "$299.50/month", "75% margin"],
        ["Your Margin (Setup)", "$1,497", "Minus your labor"],
        ["Annual Recurring Rev.", "$4,764/year", "Per client"],
    ]
    t = styled_table(ob_data, [1.5*inch, 1.5*inch, 3*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, -3), (-1, -1), HexColor("#e8f5e9")),
        ("FONTNAME", (0, -3), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Why this is better:</b>", s["BodyText2"]))
    story.append(Paragraph("&bull; <b>Higher setup fee is justified</b> &mdash; you're building a custom AI agent tailored to their business, not installing off-the-shelf software. Competitors charge $2K-$5K.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>750 included minutes covers 90%+ of small HVAC businesses</b> &mdash; most won't hit overage, which makes the price feel \"all-inclusive\" and predictable.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>$397/mo is still a fraction of a receptionist</b> &mdash; a full-time receptionist costs $3,000-$4,300/month. You're saving them 90%.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>Lower overage rate ($0.22)</b> feels fairer and builds trust &mdash; you still make $0.09/min profit on overages.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>The $397 price point psychologically signals quality</b> without breaking $400/mo.", s["BulletCustom"]))

    # ---- Section 5: APIs and Tech Stack ----
    story.append(PageBreak())
    story.append(Paragraph("5. APIs &amp; Tech Stack You'll Need", s["SectionHead"]))
    story.append(divider())

    api_data = [
        ["API / Service", "Purpose", "Cost"],
        ["Retell AI", "Voice agent platform (STT + orchestration)", "$0.055/min"],
        ["OpenAI (GPT-4.1)", "LLM for conversation intelligence", "$0.045/min"],
        ["Retell Platform Voices", "Text-to-speech", "$0.015/min"],
        ["Twilio (via Retell)", "Phone number + telephony", "$0.015/min + $2/mo"],
        ["Google Calendar API", "Appointment booking", "Free"],
        ["Zapier / Make.com", "Workflow automation (optional)", "$0-20/month"],
        ["ServiceTitan API", "FSM integration (if client uses it)", "Varies"],
        ["Housecall Pro API", "FSM integration (alternative)", "Varies"],
        ["SendGrid / Twilio SMS", "Confirmation texts/emails", "~$0.01/SMS"],
        ["Your CRM / Airtable", "Lead tracking dashboard", "Free-$20/mo"],
    ]
    story.append(styled_table(api_data, [1.8*inch, 2.2*inch, 1.8*inch]))

    story.append(Spacer(1, 15))
    story.append(Paragraph("6. What You Need to Know Before Starting", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("<b>Build Time Estimate:</b> 8-15 hours for first agent, 3-5 hours for subsequent clients (you'll reuse the template).", s["BodyText2"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Key Setup Steps:</b>", s["BodyText2"]))
    story.append(Paragraph("&bull; Create Retell account + connect Twilio for phone number", s["BulletCustom"]))
    story.append(Paragraph("&bull; Design conversation flows (greeting, qualification, booking, emergency routing, FAQ)", s["BulletCustom"]))
    story.append(Paragraph("&bull; Configure LLM prompt with HVAC-specific knowledge (services, pricing, service areas)", s["BulletCustom"]))
    story.append(Paragraph("&bull; Set up calendar integration for appointment booking", s["BulletCustom"]))
    story.append(Paragraph("&bull; Configure call transfer rules (emergencies go to on-call tech)", s["BulletCustom"]))
    story.append(Paragraph("&bull; Test extensively with real HVAC scenarios", s["BulletCustom"]))
    story.append(Paragraph("&bull; Set up monitoring dashboard and alerts", s["BulletCustom"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Ongoing Maintenance:</b>", s["BodyText2"]))
    story.append(Paragraph("&bull; Monitor call logs weekly (1-2 hrs/month per client)", s["BulletCustom"]))
    story.append(Paragraph("&bull; Tune prompts based on real call data", s["BulletCustom"]))
    story.append(Paragraph("&bull; Update seasonal messaging (summer AC, winter heating)", s["BulletCustom"]))
    story.append(Paragraph("&bull; Handle client requests for flow changes", s["BulletCustom"]))

    # ---- Section 6: Scaling Math ----
    story.append(PageBreak())
    story.append(Paragraph("7. Revenue Scaling: 1 to 10 Clients", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("Using Option B pricing ($1,497 setup + $397/month):", s["BodyText2"]))
    scale_data = [
        ["Clients", "Setup Rev.", "Monthly Rev.", "Monthly Cost", "Monthly Profit", "Annual Profit"],
        ["1", "$1,497", "$397", "~$100", "$297", "$3,564"],
        ["3", "$4,491", "$1,191", "~$300", "$891", "$10,692"],
        ["5", "$7,485", "$1,985", "~$500", "$1,485", "$17,820"],
        ["10", "$14,970", "$3,970", "~$1,000", "$2,970", "$35,640"],
    ]
    t = styled_table(scale_data, [0.7*inch, 1*inch, 1.1*inch, 1.1*inch, 1.1*inch, 1.1*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, -1), (-1, -1), HexColor("#e8f5e9")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph("<i>Note: Setup revenue is one-time. Monthly costs assume ~750 min/client avg. Your time investment decreases per client as you build reusable templates.</i>", s["SmallNote"]))

    story.append(Spacer(1, 20))
    story.append(Paragraph("8. Final Recommendation", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("Go with <b>Option B ($1,497 + $397/month)</b> for new clients. If the client pushes back on price, you can fall back to <b>Option A ($749 + $349/month)</b> as a \"startup package\" &mdash; this gives you negotiation room without undercutting your value.", s["BodyText2"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Use Retell as your platform.</b> It's simpler, has per-second billing, better documentation, and the recommended stack costs only $0.13/min.", s["BodyText2"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Lead with ROI in your sales pitch.</b> A missed call costs an HVAC company $150-$500. If your agent catches just 2 extra calls per month, it pays for itself. At $397/month, you're saving them $30,000+/year vs. hiring a receptionist.", s["BodyText2"]))

    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY))
    story.append(Spacer(1, 8))
    story.append(Paragraph("CONFIDENTIAL &mdash; Antigravity Internal Document &mdash; March 2026", s["Footer"]))

    doc.build(story)
    return path


# ============================================================
# CLIENT-FACING PROPOSAL
# ============================================================
def generate_client_proposal():
    path = os.path.join(BASE_DIR, "CLIENT_Proposal_HVAC_Voice_Agent.pdf")
    doc = SimpleDocTemplate(path, pagesize=letter,
                            topMargin=0.75*inch, bottomMargin=0.75*inch,
                            leftMargin=0.85*inch, rightMargin=0.85*inch)
    s = get_styles()
    story = []

    # ---- Cover Page ----
    story.append(Spacer(1, 1.8*inch))
    story.append(Paragraph("AI Voice Agent", s["MainTitle"]))
    story.append(Paragraph("for Your HVAC Business", s["MainTitle"]))
    story.append(Spacer(1, 0.2*inch))
    story.append(HRFlowable(width="30%", thickness=3, color=HIGHLIGHT, spaceAfter=20))
    story.append(Paragraph("Never Miss Another Call. Book More Jobs. 24/7.", s["Subtitle"]))
    story.append(Spacer(1, 0.8*inch))
    story.append(Paragraph("Prepared by Antigravity", s["Subtitle"]))
    story.append(Paragraph("March 2026", s["SmallNote"]))
    story.append(PageBreak())

    # ---- The Problem ----
    story.append(Paragraph("The Problem: Missed Calls = Lost Revenue", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("Every unanswered call is a customer choosing your competitor.", s["BodyText2"]))
    story.append(Spacer(1, 10))

    # Stats boxes as table
    stats = Table([
        [Paragraph("<b>27%</b>", s["BigNumber"]),
         Paragraph("<b>$31K - $52K</b>", s["BigNumber"])],
        [Paragraph("of HVAC calls go unanswered", s["PriceLabel"]),
         Paragraph("lost revenue per year from just\n2 missed calls per week", s["PriceLabel"])],
    ], colWidths=[3*inch, 3*inch])
    stats.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 15),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 15),
        ("BOX", (0, 0), (0, -1), 1, LIGHT_GRAY),
        ("BOX", (1, 0), (1, -1), 1, LIGHT_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
    ]))
    story.append(stats)
    story.append(Spacer(1, 15))

    story.append(Paragraph("Your team is busy in the field. Calls come in during jobs, after hours, on weekends, and during peak season when every tech is booked. Every missed call is a potential $150-$500 service job walking straight to your competition.", s["BodyText2"]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Common pain points:</b>", s["BodyText2"]))
    story.append(Paragraph("&bull; Calls going to voicemail after hours and on weekends", s["BulletCustom"]))
    story.append(Paragraph("&bull; Technicians too busy on jobs to answer the phone", s["BulletCustom"]))
    story.append(Paragraph("&bull; Summer/winter peak season overwhelming your front desk", s["BulletCustom"]))
    story.append(Paragraph("&bull; No way to qualify leads before dispatching a tech", s["BulletCustom"]))
    story.append(Paragraph("&bull; Emergency calls (no heat, gas leak) getting lost in voicemail", s["BulletCustom"]))

    # ---- The Solution ----
    story.append(PageBreak())
    story.append(Paragraph("The Solution: Your AI-Powered Phone Agent", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("We build you a custom AI voice agent that answers every call &mdash; 24 hours a day, 7 days a week, 365 days a year. It sounds natural, handles real conversations, and does the work of a trained receptionist at a fraction of the cost.", s["BodyText2"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph("What Your AI Agent Does:", s["SubHead"]))

    features = [
        ["Answers Every Call", "Never miss a lead again. Your AI agent picks up instantly, day or night, weekday or weekend."],
        ["Books Appointments", "Checks your real calendar availability and schedules service calls on the spot."],
        ["Qualifies Leads", "Asks the right questions: system type, issue description, address, urgency level."],
        ["Handles Emergencies", "Detects urgent keywords (no heat, gas leak, flooding) and immediately routes to your on-call technician."],
        ["Provides Information", "Answers FAQs about your services, service areas, pricing ranges, and business hours."],
        ["Sends Confirmations", "Texts the customer a booking confirmation and sends you a lead notification instantly."],
        ["Speaks Naturally", "Uses advanced AI to have real, flowing conversations &mdash; not robotic menu trees."],
        ["Transfers When Needed", "Seamlessly transfers to a live person for complex situations."],
    ]
    for feat in features:
        story.append(Paragraph(f"&bull; <b>{feat[0]}:</b> {feat[1]}", s["BulletCustom"]))
    story.append(Spacer(1, 6))

    # ---- How It Works ----
    story.append(Spacer(1, 10))
    story.append(Paragraph("How It Works", s["SubHead"]))
    steps_data = [
        ["Step", "What Happens"],
        ["1. Customer Calls", "Your phone rings and the AI agent answers instantly with a friendly, professional greeting customized to your business."],
        ["2. AI Converses", "The agent has a natural conversation, asking relevant questions and understanding the customer's needs."],
        ["3. Action Taken", "Based on the call, the agent books an appointment, routes an emergency, or captures the lead details."],
        ["4. You Get Notified", "You receive an instant notification with all call details, recording, and any booked appointments."],
    ]
    story.append(styled_table(steps_data, [1.3*inch, 5*inch]))

    # ---- Pricing ----
    story.append(PageBreak())
    story.append(Paragraph("Investment", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("Simple, transparent pricing with no hidden fees.", s["BodyText2"]))
    story.append(Spacer(1, 10))

    # Pricing table
    price_data = [
        ["", "What's Included", "Investment"],
        ["One-Time\nSetup", "Custom AI agent built for your business\nConversation flow design & testing\nPhone number setup\nCalendar integration\nEmergency routing configuration\nFull training & onboarding call", "$1,497"],
        ["Monthly\nService", "24/7 AI answering (up to 750 minutes)\nOngoing optimization & tuning\nCall recordings & analytics dashboard\nSeasonal messaging updates\nPriority support\nMonthly performance review", "$397/mo"],
        ["Overage\nMinutes", "Additional minutes beyond 750/month\nbilled only if exceeded", "$0.22/min"],
    ]
    t = Table(price_data, colWidths=[1*inch, 3.5*inch, 1.3*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTSIZE", (2, 1), (2, -1), 14),
        ("TEXTCOLOR", (2, 1), (2, -1), HIGHLIGHT),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
        ("BACKGROUND", (0, 1), (-1, 1), LIGHT_BG),
        ("BACKGROUND", (0, 3), (-1, 3), LIGHT_BG),
    ]))
    story.append(t)

    story.append(Spacer(1, 15))
    story.append(Paragraph("<i>750 included minutes covers the vast majority of small-to-medium HVAC businesses. Most clients never hit overage.</i>", s["SmallNote"]))

    # ---- ROI ----
    story.append(Spacer(1, 15))
    story.append(Paragraph("The Math: How This Pays for Itself", s["SubHead"]))

    roi_data = [
        ["Metric", "Value"],
        ["Average HVAC service call value", "$250 - $500"],
        ["Missed calls per week (industry avg.)", "5 - 15 calls"],
        ["If AI captures just 2 extra jobs/month", "$500 - $1,000 gained"],
        ["Your monthly investment", "$397"],
        ["Net gain from month 1", "$103 - $603/month"],
        ["Annual ROI", "250% - 700%+"],
    ]
    t = styled_table(roi_data, [3*inch, 2.5*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, -1), (-1, -1), HexColor("#e8f5e9")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)

    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Compared to hiring:</b> A full-time receptionist costs $3,000-$4,300/month and only works business hours. Your AI agent costs $397/month and works 24/7 &mdash; that's a <b>90% savings</b> with better coverage.", s["BodyText2"]))

    # ---- What Sets Us Apart ----
    story.append(PageBreak())
    story.append(Paragraph("Why Work With Us", s["SectionHead"]))
    story.append(divider())

    story.append(Paragraph("&bull; <b>Built Specifically for HVAC:</b> Your agent understands heating, cooling, and plumbing terminology. It knows how to triage emergencies and qualify leads the way your best CSR would.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>Custom, Not Cookie-Cutter:</b> This isn't a generic chatbot. We build your agent around your services, your service area, your scheduling, and your brand voice.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>Continuous Optimization:</b> We review call data monthly and fine-tune the AI to get better over time. Your agent improves every month.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>Real Conversations, Not Phone Trees:</b> Customers talk naturally. No \"press 1 for service, press 2 for billing\" &mdash; just a helpful, intelligent conversation.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>Transparent Reporting:</b> Full access to call recordings, transcripts, and analytics so you can see exactly what's happening.", s["BulletCustom"]))
    story.append(Paragraph("&bull; <b>No Long-Term Contracts:</b> Month-to-month after setup. We earn your business every month.", s["BulletCustom"]))

    # ---- Getting Started ----
    story.append(Spacer(1, 20))
    story.append(Paragraph("Getting Started", s["SectionHead"]))
    story.append(divider())

    timeline_data = [
        ["Timeline", "What Happens"],
        ["Day 1-2", "Kickoff call: we learn your business, services, service area, and how you want calls handled."],
        ["Day 3-5", "We build your custom AI agent with tailored conversation flows and integrate your calendar."],
        ["Day 6-7", "Testing phase: we run real-world scenarios and fine-tune responses."],
        ["Day 8-10", "Go live! Your AI agent starts answering calls. We monitor closely during the first week."],
        ["Ongoing", "Monthly optimization, seasonal updates, and performance reviews."],
    ]
    story.append(styled_table(timeline_data, [1*inch, 5.2*inch]))

    story.append(Spacer(1, 20))

    # CTA
    cta = Table(
        [[Paragraph("<b>Ready to stop missing calls and start booking more jobs?</b><br/><br/>Let's schedule a quick 15-minute call to discuss how an AI voice agent<br/>can work specifically for your HVAC business.",
                     ParagraphStyle("CTA", fontSize=12, leading=16, textColor=white, fontName="Helvetica", alignment=TA_CENTER))]],
        colWidths=[5.8*inch]
    )
    cta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
        ("TOPPADDING", (0, 0), (-1, -1), 25),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 25),
        ("LEFTPADDING", (0, 0), (-1, -1), 20),
        ("RIGHTPADDING", (0, 0), (-1, -1), 20),
        ("ROUNDEDCORNERS", [8, 8, 8, 8]),
    ]))
    story.append(cta)

    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Antigravity &mdash; AI Solutions for Home Service Businesses &mdash; March 2026", s["Footer"]))

    doc.build(story)
    return path


if __name__ == "__main__":
    p1 = generate_internal_proposal()
    print(f"Internal proposal: {p1}")
    p2 = generate_client_proposal()
    print(f"Client proposal: {p2}")
