"""
HVAC Voice Agent Backend Server — High Tech Air Conditioning
Connects Retell AI custom tools to Housecall Pro API

Deploy on Railway ($5/mo) — stays awake 24/7 for live voice calls.
"""

import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ============================================================
# CONFIGURATION
# ============================================================
HCP_API_KEY = os.environ.get("HCP_API_KEY", "YOUR_HOUSECALL_PRO_API_KEY")
HCP_BASE_URL = "https://api.housecallpro.com"
RETELL_API_KEY = os.environ.get("RETELL_API_KEY", "YOUR_RETELL_API_KEY")

# Default employee to assign jobs to (get from HCP dashboard or /employees endpoint)
DEFAULT_EMPLOYEE_ID = os.environ.get("DEFAULT_EMPLOYEE_ID", "")

# ── High Tech AC Business Config (from intake form) ──
BUSINESS_HOURS_START = 6    # 6 AM — service/dispatch hours
BUSINESS_HOURS_END = 22     # 10 PM
SLOT_DURATION_HOURS = 2     # 2-hour arrival windows
DAYS_AHEAD_TO_CHECK = 7     # Check 7 days ahead for availability

# Emergency on-call tech
EMERGENCY_TECH_NAME = "Keivin Rivero"
EMERGENCY_TECH_PHONE = "(786) 532-8419"
EMERGENCY_FEE = "$120"

# Service area
SERVICE_AREA = [
    "Orlando", "Winter Park", "Winter Garden", "Kissimmee", "Davenport",
    "Clermont", "Windermere", "Doctor Phillips", "Celebration", "Lake Buena Vista",
]

# Services that CANNOT be booked — collect info only
DO_NOT_BOOK_SERVICES = ["duct cleaning"]


# ============================================================
# HOUSECALL PRO API HELPERS
# ============================================================

def hcp_headers():
    return {
        "Authorization": f"Token {HCP_API_KEY}",
        "Content-Type": "application/json",
    }


def hcp_get(endpoint, params=None):
    """Make a GET request to Housecall Pro API."""
    resp = requests.get(
        f"{HCP_BASE_URL}{endpoint}",
        headers=hcp_headers(),
        params=params or {},
    )
    resp.raise_for_status()
    return resp.json()


def hcp_post(endpoint, data):
    """Make a POST request to Housecall Pro API."""
    resp = requests.post(
        f"{HCP_BASE_URL}{endpoint}",
        headers=hcp_headers(),
        json=data,
    )
    resp.raise_for_status()
    return resp.json()


# ============================================================
# TOOL 1: CHECK AVAILABILITY
# ============================================================

@app.route("/check-availability", methods=["POST"])
def check_availability():
    """
    Check available appointment slots by looking at existing jobs
    in Housecall Pro and finding gaps.
    Service hours: Mon-Sun 6am-10pm (no day restrictions).
    """
    body = request.json
    args = body.get("args", {})

    preferred_date = args.get("preferred_date", "")

    try:
        if preferred_date:
            try:
                start_date = datetime.strptime(preferred_date, "%Y-%m-%d")
            except ValueError:
                start_date = datetime.now()
            end_date = start_date + timedelta(days=3)
        else:
            start_date = datetime.now()
            end_date = start_date + timedelta(days=DAYS_AHEAD_TO_CHECK)

        # Get existing jobs in this date range
        params = {
            "scheduled_start_min": start_date.strftime("%Y-%m-%dT00:00:00"),
            "scheduled_start_max": end_date.strftime("%Y-%m-%dT23:59:59"),
            "work_status": "scheduled",
            "page_size": 100,
        }

        data = hcp_get("/jobs", params=params)
        existing_jobs = data.get("jobs", [])

        # Build a set of busy time slots
        busy_slots = set()
        for job in existing_jobs:
            schedule = job.get("schedule", {})
            job_start = schedule.get("scheduled_start")
            if job_start:
                try:
                    dt = datetime.fromisoformat(job_start.replace("Z", "+00:00"))
                    busy_slots.add((dt.date(), dt.hour))
                except (ValueError, AttributeError):
                    pass

        # Generate available slots — Mon-Sun, 6am-10pm
        available_slots = []
        current = start_date
        while current <= end_date and len(available_slots) < 6:
            if current.date() < datetime.now().date():
                current += timedelta(days=1)
                continue

            for hour in range(BUSINESS_HOURS_START, BUSINESS_HOURS_END, SLOT_DURATION_HOURS):
                if current.date() == datetime.now().date() and hour <= datetime.now().hour:
                    continue

                if (current.date(), hour) not in busy_slots:
                    slot_start = current.replace(hour=hour, minute=0, second=0)
                    slot_end = slot_start + timedelta(hours=SLOT_DURATION_HOURS)

                    day_name = slot_start.strftime("%A, %B %d")
                    start_str = slot_start.strftime("%-I:%M %p")
                    end_str = slot_end.strftime("%-I:%M %p")

                    available_slots.append({
                        "date": slot_start.strftime("%Y-%m-%d"),
                        "start_time": slot_start.strftime("%H:%M"),
                        "end_time": slot_end.strftime("%H:%M"),
                        "display": f"{day_name} between {start_str} and {end_str}",
                    })

                    if len(available_slots) >= 6:
                        break

            current += timedelta(days=1)

        if not available_slots:
            return jsonify({
                "result": "It looks like our schedule is quite full in the next few days. Let me have our scheduling team call you back to find the best time. Can I confirm your phone number?"
            })

        slot_text = "\n".join([f"- {s['display']}" for s in available_slots[:3]])
        return jsonify({
            "result": json.dumps({
                "available_slots": available_slots[:3],
                "display_text": f"Here are the next available appointments:\n{slot_text}",
            })
        })

    except requests.HTTPError:
        return jsonify({
            "result": "I'm having trouble checking the schedule right now. Let me take your information and have our team call you back to confirm a time."
        })


# ============================================================
# TOOL 2: CREATE APPOINTMENT
# ============================================================

@app.route("/create-appointment", methods=["POST"])
def create_appointment():
    """
    Create a job/appointment in Housecall Pro.
    Always creates a new customer (no lookup) — collects info every time.
    Handles the duct cleaning exception: captures info but does NOT book.
    Tags emergency jobs and adds the $120 fee note.
    """
    body = request.json
    args = body.get("args", {})

    first_name = args.get("first_name", "")
    last_name = args.get("last_name", "")
    phone = args.get("phone", "")
    email = args.get("email", "")
    street = args.get("street", "")
    city = args.get("city", "")
    state = args.get("state", "")
    zip_code = args.get("zip_code", "")
    date = args.get("date", "")              # YYYY-MM-DD
    start_time = args.get("start_time", "")  # HH:MM
    end_time = args.get("end_time", "")      # HH:MM
    service_type = args.get("service_type", "HVAC Service")
    is_emergency = args.get("is_emergency", False)
    notes = args.get("notes", "")

    # ── Validation ──
    if not first_name or not last_name or not phone:
        return jsonify({
            "result": "I need the customer's first name, last name, and phone number to continue. Could you provide those?"
        })

    # ── Duct Cleaning Exception ──
    if any(svc in service_type.lower() for svc in DO_NOT_BOOK_SERVICES):
        # Don't book — just capture the lead info
        try:
            customer_data = {
                "first_name": first_name,
                "last_name": last_name,
                "mobile_number": phone,
                "notifications_enabled": True,
            }
            if email:
                customer_data["email"] = email

            cust_resp = hcp_post("/customers", customer_data)
            customer_id = cust_resp.get("id", "")

            # Add address if provided
            if street:
                addr_data = {
                    "street": street,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                    "type": "service",
                }
                requests.post(
                    f"{HCP_BASE_URL}/customers/{customer_id}/addresses",
                    headers=hcp_headers(),
                    json=addr_data,
                )

            # Create a lead/note in HCP so the team knows to call back
            lead_data = {
                "customer_id": customer_id,
                "notes": f"DUCT CLEANING REQUEST — booked via AI phone agent. "
                         f"Customer: {first_name} {last_name}, Phone: {phone}. "
                         f"Address: {street}, {city}, {state} {zip_code}. "
                         f"Please call back with duct cleaning availability. {notes}".strip(),
            }
            try:
                hcp_post("/leads", lead_data)
            except requests.HTTPError:
                pass  # Lead creation is best-effort

        except requests.HTTPError:
            pass  # Customer creation failed — info is still in Retell logs

        return jsonify({
            "result": json.dumps({
                "success": True,
                "duct_cleaning": True,
                "message": f"I've taken down the information for {first_name} {last_name}. "
                           f"Our team will call back shortly with duct cleaning availability.",
            })
        })

    # ── Create Customer in Housecall Pro ──
    try:
        customer_data = {
            "first_name": first_name,
            "last_name": last_name,
            "mobile_number": phone,
            "notifications_enabled": True,
        }
        if email:
            customer_data["email"] = email

        cust_resp = hcp_post("/customers", customer_data)
        customer_id = cust_resp.get("id", "")

        # Add address
        address_id = ""
        if street:
            addr_data = {
                "street": street,
                "city": city,
                "state": state,
                "zip": zip_code,
                "type": "service",
            }
            addr_resp = requests.post(
                f"{HCP_BASE_URL}/customers/{customer_id}/addresses",
                headers=hcp_headers(),
                json=addr_data,
            )
            addr_resp.raise_for_status()
            address_id = addr_resp.json().get("id", "")

    except requests.HTTPError:
        return jsonify({
            "result": "I'm having a little trouble setting up the account right now. "
                      "Let me take your information and have our team call you back "
                      "within the hour to confirm your appointment."
        })

    if not customer_id or not address_id:
        return jsonify({
            "result": "I need the service address to complete the booking. Could you confirm the full address?"
        })

    # ── Create the Job ──
    try:
        scheduled_start = f"{date}T{start_time}:00"
        scheduled_end = f"{date}T{end_time}:00"

        # Build notes
        job_notes = "Booked via AI phone agent."
        if is_emergency:
            job_notes = f"EMERGENCY — {EMERGENCY_FEE} emergency fee acknowledged by customer. Booked via AI phone agent."
        if notes:
            job_notes += f" Problem: {notes}"

        job_data = {
            "customer_id": customer_id,
            "address_id": address_id,
            "schedule": {
                "scheduled_start": scheduled_start,
                "scheduled_end": scheduled_end,
                "arrival_window": SLOT_DURATION_HOURS * 60,
            },
            "line_items": [
                {
                    "name": service_type,
                    "description": f"{'EMERGENCY - ' if is_emergency else ''}{service_type}",
                    "quantity": 1,
                }
            ],
            "notes": job_notes,
        }

        if DEFAULT_EMPLOYEE_ID:
            job_data["assigned_employee_ids"] = [DEFAULT_EMPLOYEE_ID]

        if is_emergency:
            job_data["tags"] = ["emergency", "ai-booked"]
        else:
            job_data["tags"] = ["ai-booked"]

        job_resp = hcp_post("/jobs", job_data)
        job_id = job_resp.get("id", "")

        # Format confirmation
        start_dt = datetime.strptime(scheduled_start, "%Y-%m-%dT%H:%M:%S")
        end_dt = datetime.strptime(scheduled_end, "%Y-%m-%dT%H:%M:%S")

        confirmation = {
            "success": True,
            "job_id": job_id,
            "date": start_dt.strftime("%A, %B %d"),
            "time_window": f"{start_dt.strftime('%-I:%M %p')} to {end_dt.strftime('%-I:%M %p')}",
            "service_type": service_type,
            "is_emergency": is_emergency,
            "message": f"Appointment confirmed for {start_dt.strftime('%A, %B %d')} "
                       f"between {start_dt.strftime('%-I:%M %p')} and {end_dt.strftime('%-I:%M %p')}. "
                       f"The customer will receive a confirmation text.",
        }

        return jsonify({"result": json.dumps(confirmation)})

    except requests.HTTPError:
        return jsonify({
            "result": "I'm having trouble completing the booking right now. I've captured all the information "
                      "— let me have our scheduling team confirm your appointment and call you back shortly."
        })


# ============================================================
# TOOL 3: TRANSFER TO EMERGENCY TECH
# ============================================================

@app.route("/transfer-emergency", methods=["POST"])
def transfer_emergency():
    """
    Captures customer info and returns the emergency tech's phone number
    for Retell to transfer the call.
    Used when caller has an emergency AND agrees to the $120 fee.
    """
    body = request.json
    args = body.get("args", {})

    first_name = args.get("first_name", "")
    last_name = args.get("last_name", "")
    phone = args.get("phone", "")
    email = args.get("email", "")
    street = args.get("street", "")
    city = args.get("city", "")
    state = args.get("state", "")
    zip_code = args.get("zip_code", "")
    notes = args.get("notes", "")

    # Create the customer in HCP so there's a record
    try:
        customer_data = {
            "first_name": first_name,
            "last_name": last_name,
            "mobile_number": phone,
            "notifications_enabled": True,
        }
        if email:
            customer_data["email"] = email

        cust_resp = hcp_post("/customers", customer_data)
        customer_id = cust_resp.get("id", "")

        if street:
            addr_data = {
                "street": street,
                "city": city,
                "state": state,
                "zip": zip_code,
                "type": "service",
            }
            requests.post(
                f"{HCP_BASE_URL}/customers/{customer_id}/addresses",
                headers=hcp_headers(),
                json=addr_data,
            )

        # Create an emergency lead/note
        lead_data = {
            "customer_id": customer_id,
            "notes": f"EMERGENCY CALL — {EMERGENCY_FEE} fee acknowledged. "
                     f"Transferred to {EMERGENCY_TECH_NAME} at {EMERGENCY_TECH_PHONE}. "
                     f"Booked via AI phone agent. "
                     f"Customer: {first_name} {last_name}, Phone: {phone}. "
                     f"Address: {street}, {city}, {state} {zip_code}. "
                     f"Problem: {notes}".strip(),
        }
        try:
            hcp_post("/leads", lead_data)
        except requests.HTTPError:
            pass

    except requests.HTTPError:
        pass  # Even if HCP fails, we still transfer the call

    return jsonify({
        "result": json.dumps({
            "success": True,
            "transfer_to": EMERGENCY_TECH_PHONE,
            "tech_name": EMERGENCY_TECH_NAME,
            "message": f"Transferring to {EMERGENCY_TECH_NAME} now. "
                       f"Customer {first_name} {last_name} has an emergency and agreed to the {EMERGENCY_FEE} fee.",
        })
    })


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "high-tech-ac-voice-agent",
        "tools": ["check-availability", "create-appointment", "transfer-emergency"],
    })


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
