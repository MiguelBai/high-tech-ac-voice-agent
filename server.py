"""
HVAC Voice Agent Backend Server — High Tech Air Conditioning
Connects Retell AI custom tools to Housecall Pro API

Deploy on Railway ($5/mo) — stays awake 24/7 for live voice calls.
"""

import os
import json
import queue
import time
import base64
import uuid
import sqlite3
import threading
import gevent
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, Response, render_template_string
import requests
from dotenv import load_dotenv

load_dotenv()

def _load_logo_data_uri():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = (
        os.path.join(here, "logo.png"),
        os.path.join(here, "assets", "logo.png"),
        os.path.join(here, "deploy", "assets", "logo.png"),
        os.path.join(here, "deploy", "logo.png"),
    )
    for path in candidates:
        try:
            with open(path, "rb") as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
        except FileNotFoundError:
            continue
    return ""

LOGO_DATA_URI = _load_logo_data_uri()

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
LOCAL_TZ = ZoneInfo("America/New_York")  # Orlando, FL = Eastern Time
BUSINESS_HOURS_START = 6    # 6 AM — service/dispatch hours
BUSINESS_HOURS_END = 22     # 10 PM
SLOT_DURATION_HOURS = 2     # 2-hour arrival windows
DAYS_AHEAD_TO_CHECK = 7     # Check 7 days ahead for availability

# Field techs who can be assigned jobs (from HCP /employees)
FIELD_TECHS = [
    {"id": "pro_d48f51094f9d4c458a11545bc8b8efdb", "name": "Keivin Rivero"},
    {"id": "pro_47ced5a0d0c342b2918d564ad24d086a", "name": "Alfredo Frassino"},
    {"id": "pro_de49d1154df04b5bb383d67ba15117b5", "name": "Daniel Soto"},
    {"id": "pro_da603dce9bc5404b8f5ef009121708fa", "name": "Oscar Contreras"},
]

# Emergency on-call tech
EMERGENCY_TECH_NAME = "Keivin Rivero"
EMERGENCY_TECH_PHONE = "(786) 532-8419"
EMERGENCY_FEE = "$120"

# Service area
SERVICE_AREA = [
    "Orlando", "Winter Park", "Winter Garden", "Kissimmee", "Davenport",
    "Clermont", "Windermere", "Doctor Phillips", "Celebration", "Lake Buena Vista",
]

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "hvac2026")
DASHBOARD_PUBLIC_URL = os.environ.get("DASHBOARD_PUBLIC_URL", "https://hvac-retell-alfredo-production.up.railway.app")

# ── Retell request authenticity (X-Retell-Signature) ───────────────────────────
# Retell signs its requests: header "v={unix_ms},d={hex}" where hex =
# HMAC-SHA256(api_key, raw_body + unix_ms). We verify so nobody who guesses the
# Railway URLs can POST fake bookings / fire emergency Telegram alerts.
# Rollout is staged via RETELL_VERIFY_MODE so we never break live traffic if a
# given request type turns out not to be signed:
#   off     — skip entirely
#   monitor — verify + log result, but ALWAYS process (default; safe to deploy)
#   enforce — reject (401) when the signature is missing/invalid
import hmac as _hmac
import hashlib as _hashlib
import re as _sig_re
from functools import wraps as _wraps

RETELL_VERIFY_MODE = os.environ.get("RETELL_VERIFY_MODE", "monitor").strip().lower()


def _retell_signature_valid(raw_body, signature):
    if not RETELL_API_KEY or RETELL_API_KEY == "YOUR_RETELL_API_KEY":
        return False
    m = _sig_re.match(r"\s*v=(\d+),\s*d=([0-9a-fA-F]+)\s*$", signature or "")
    if not m:
        return False
    ts, digest = m.group(1), m.group(2)
    body = raw_body.decode("utf-8", "replace") if isinstance(raw_body, (bytes, bytearray)) else (raw_body or "")
    expected = _hmac.new(RETELL_API_KEY.encode("utf-8"), (body + ts).encode("utf-8"), _hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected.lower(), digest.lower())


def require_retell_signature(fn):
    """Gate a Retell-facing endpoint on the X-Retell-Signature header (see RETELL_VERIFY_MODE)."""
    @_wraps(fn)
    def _wrap(*args, **kwargs):
        if RETELL_VERIFY_MODE == "off":
            return fn(*args, **kwargs)
        sig = request.headers.get("X-Retell-Signature", "")
        raw = request.get_data(cache=True) or b""   # cache=True so request.json still works downstream
        if _retell_signature_valid(raw, sig):
            logger.info(f"[retell-verify] ok {request.path}")
            return fn(*args, **kwargs)
        reason = "missing" if not sig else "mismatch"
        if RETELL_VERIFY_MODE == "enforce":
            logger.warning(f"[retell-verify] REJECTED {request.path} ({reason})")
            return jsonify({"error": "invalid signature"}), 401
        logger.warning(f"[retell-verify] monitor: {request.path} signature {reason} — allowing "
                       "(set RETELL_VERIFY_MODE=enforce to block once all 5 Retell endpoints log 'ok')")
        return fn(*args, **kwargs)
    return _wrap


def _clean_env(v: str) -> str:
    """Strip whitespace + stray unicode separators that can sneak in from copy-paste."""
    if not v:
        return ""
    return "".join(c for c in v if not c.isspace() or c == " ").strip()


# Telegram bot notifications
TELEGRAM_BOT_TOKEN = _clean_env(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = _clean_env(os.environ.get("TELEGRAM_CHAT_ID", ""))

# Web Push (iPhone home-screen PWA banners). Keys live in Railway → Variables.
VAPID_PUBLIC_KEY = _clean_env(os.environ.get("VAPID_PUBLIC_KEY", ""))
VAPID_PRIVATE_KEY = _clean_env(os.environ.get("VAPID_PRIVATE_KEY", ""))
VAPID_SUBJECT = _clean_env(os.environ.get("VAPID_SUBJECT", "mailto:alerts@hightechacfl.com"))

# Human-transfer destinations — changeable in Railway → Variables (no redeploy needed).
# Both default to Alfredo's cell for now; can be pointed at different numbers later.
ALFREDO_TRANSFER_PHONE = _clean_env(os.environ.get("ALFREDO_TRANSFER_PHONE", "+19546696259"))
HUMAN_TRANSFER_PHONE = _clean_env(os.environ.get("HUMAN_TRANSFER_PHONE", "+19546696259"))

# Minimum lead time before a NON-emergency appointment may start. Emergencies are
# handled via transfer, not booked here, so this only gates regular scheduling.
MIN_BOOKING_LEAD_HOURS = int(os.environ.get("MIN_BOOKING_LEAD_HOURS", "12"))


def send_telegram_alert(message: str, parse_mode: str = "Markdown"):
    """Send a Telegram message to TELEGRAM_CHAT_ID. Non-blocking — failures logged, not raised."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        logger.info("[telegram] skipped - not configured")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=5,
        )
        if r.status_code >= 300:
            logger.warning(f"[telegram] failed {r.status_code}: {r.text[:200]}")
        else:
            logger.info("[telegram] sent")
    except Exception as e:
        logger.warning(f"[telegram] exception: {e}")


def _format_call_ended_alert(c):
    """Build the end-of-call Telegram summary (HTML) from an ACTIVE_CALLS entry.
    Uses the analyzed call data (summary, outcome, priority, follow-up) plus any
    booking made on the call. HTML parse mode so free-text fields escape cleanly."""
    import html
    e = html.escape
    analysis = c.get("analysis") or {}
    custom = analysis.get("custom_analysis_data") or {}
    booking = c.get("booking_summary") or {}

    summary = (analysis.get("call_summary") or "").strip()
    outcome = (custom.get("outcome") or "").strip()
    priority = (custom.get("priority") or "").strip().upper()
    sentiment = (analysis.get("user_sentiment") or "").strip()
    should_followup = custom.get("should_followup")
    followup_reason = (custom.get("followup_reason") or "").strip()
    lead_source = (custom.get("lead_source") or "").strip()

    # Name: prefer the booked customer name, else the name extracted by analysis.
    name = (booking.get("customer_name") or custom.get("caller_name") or "").strip()
    caller = c.get("from_number") or "unknown"

    dur_ms = c.get("duration_ms") or 0
    mins, secs = divmod(int(dur_ms / 1000), 60)
    dur = f"{mins}m {secs}s" if mins else f"{secs}s"

    prio_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(priority, "✅")
    outcome_disp = outcome.replace("_", " ").title() if outcome else "Call ended"

    lines = [f"{prio_emoji} <b>Call ended — {e(outcome_disp)}</b>"]
    lines.append(f"👤 {e(name) if name else 'Name not given'}  ·  <code>{e(caller)}</code>")
    if summary:
        lines.append(f"📋 {e(summary)}")
    if lead_source:
        lines.append(f"📣 Heard via: {e(lead_source)}")
    if booking:
        lines.append(
            f"🗓 <b>Booked:</b> {e(booking.get('service_type',''))} — "
            f"{e(booking.get('date',''))}, {e(booking.get('time_window',''))}\n"
            f"     Tech: {e(booking.get('tech',''))} · {e(booking.get('address',''))}"
        )
        if c.get("hcp_job_url"):
            lines.append(f"     <a href=\"{e(c['hcp_job_url'])}\">Open HCP job</a>")
        # Ready-to-send confirmation text the tech can copy and send to the customer.
        first = name.split()[0] if name else "there"
        confirm = (
            f"Hi {first}, this is High Tech Air Conditioning confirming your "
            f"{booking.get('service_type','')} appointment on {booking.get('date','')}, "
            f"{booking.get('time_window','')}, at {booking.get('address','')}. "
            f"Reply to confirm, or let us know if you need to reschedule. See you then!"
        )
        lines.append(f"📲 <b>Confirmation text to send:</b>\n<pre>{e(confirm)}</pre>")
    meta = []
    if dur_ms:
        meta.append(f"⏱ {dur}")
    if sentiment:
        meta.append(e(sentiment.title()))
    if meta:
        lines.append("  ·  ".join(meta))
    if should_followup:
        lines.append(f"🔔 <b>Follow up</b>{(': ' + e(followup_reason)) if followup_reason else ''}")
    dash = f"{DASHBOARD_PUBLIC_URL}/dashboard?key={DASHBOARD_PASSWORD}"
    lines.append(f"<a href=\"{e(dash)}\">View on dashboard</a>")
    return "\n".join(lines)


def _format_call_ended_plain(c):
    """Plain-text (ico, title, body) mirror of the Telegram wrap-up, for the
    dashboard message center and the iPhone push banner (no HTML/Markdown)."""
    analysis = c.get("analysis") or {}
    custom = analysis.get("custom_analysis_data") or {}
    booking = c.get("booking_summary") or {}

    summary = (analysis.get("call_summary") or "").strip()
    outcome = (custom.get("outcome") or "").strip()
    priority = (custom.get("priority") or "").strip().upper()
    should_followup = custom.get("should_followup")
    name = (booking.get("customer_name") or custom.get("caller_name") or "").strip()
    caller = c.get("from_number") or "unknown"

    ico = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(priority, "✅")
    # Only append the outcome when there's a real one — otherwise it reads "Call ended — Call ended".
    title = f"Call ended — {outcome.replace('_', ' ').title()}" if outcome else "Call ended"

    parts = [name or caller]
    if booking:
        bk = f"Booked {booking.get('service_type','')} {booking.get('date','')} {booking.get('time_window','')}".strip()
        parts.append(" ".join(bk.split()))
    elif summary:
        parts.append(summary)
    if should_followup:
        parts.append("Needs follow-up")
    body = " · ".join(p for p in parts if p)
    return ico, title, body


def _call_meta(c):
    """Structured fields for the in-app message bubble — everything that's in the
    Telegram wrap-up (name, number, summary, duration, follow-up, booking, the
    ready-to-send confirmation text, HCP link), so the client can render it nicely
    and offer Call/Text/Copy/HCP/View-call actions."""
    analysis = c.get("analysis") or {}
    custom = analysis.get("custom_analysis_data") or {}
    booking = c.get("booking_summary") or {}

    summary = (analysis.get("call_summary") or "").strip()
    outcome = (custom.get("outcome") or "").strip()
    priority = (custom.get("priority") or "").strip().upper()
    sentiment = (analysis.get("user_sentiment") or "").strip()
    should_followup = bool(custom.get("should_followup"))
    followup_reason = (custom.get("followup_reason") or "").strip()
    lead_source = (custom.get("lead_source") or "").strip()
    name = (booking.get("customer_name") or custom.get("caller_name") or "").strip()
    caller = c.get("from_number") or ""

    dur_ms = c.get("duration_ms") or 0
    mins, secs = divmod(int(dur_ms / 1000), 60)
    dur = (f"{mins}m {secs}s" if mins else f"{secs}s") if dur_ms else ""

    bk, confirm = None, ""
    if booking:
        first = name.split()[0] if name else "there"
        confirm = (
            f"Hi {first}, this is High Tech Air Conditioning confirming your "
            f"{booking.get('service_type','')} appointment on {booking.get('date','')}, "
            f"{booking.get('time_window','')}, at {booking.get('address','')}. "
            f"Reply to confirm, or let us know if you need to reschedule. See you then!"
        )
        bk = {
            "service_type": booking.get("service_type", ""),
            "date": booking.get("date", ""),
            "time_window": booking.get("time_window", ""),
            "tech": booking.get("tech", ""),
            "address": booking.get("address", ""),
        }
    return {
        "kind": "ended",
        "name": name,
        "phone": caller,
        "outcome": outcome.replace("_", " ").title() if outcome else "",
        "priority": priority,
        "summary": summary,
        "lead_source": lead_source,
        "duration": dur,
        "sentiment": sentiment.title() if sentiment else "",
        "followup": should_followup,
        "followup_reason": followup_reason,
        "booking": bk,
        "hcp_url": c.get("hcp_job_url") or "",
        "confirm_text": confirm,
        "call_id": c.get("call_id", ""),
    }


# Services that CANNOT be booked — collect info only
DO_NOT_BOOK_SERVICES = ["duct cleaning"]

# ── Call Quality Reviewer config ──
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
RETELL_AGENT_ID   = os.environ.get("RETELL_AGENT_ID", "")
REVIEW_MODEL      = os.environ.get("REVIEW_MODEL", "claude-haiku-4-5")
SYNTH_MODEL       = os.environ.get("SYNTH_MODEL", "claude-opus-4-7")
REVIEW_INTERVAL_S = int(os.environ.get("REVIEW_INTERVAL_S", "300"))   # 5 min
STALE_ACTIVE_SECONDS = int(os.environ.get("STALE_ACTIVE_SECONDS", "7200"))  # 2h — no real call runs this long
SYNTH_HOUR_LOCAL  = int(os.environ.get("SYNTH_HOUR_LOCAL", "8"))      # 8 AM Eastern
DATA_DIR = os.environ.get("DATA_DIR", "/data" if os.path.isdir("/data") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
if not str(DATA_DIR).startswith("/data"):
    logger.warning(f"[startup] DATA_DIR={DATA_DIR} is NOT the Railway volume (/data). "
                   "On-call schedule, transfer contacts, and calls.db will NOT persist across redeploys.")
DB_PATH  = os.path.join(DATA_DIR, "calls.db")


# ============================================================
# CALL DATABASE (SQLite, persists on a Railway Volume mounted at /data)
# ============================================================

_DB_LOCK = threading.RLock()
_DB_CONN = None  # singleton; gevent runs on one OS thread so a locked shared conn is fine

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  call_id              TEXT PRIMARY KEY,
  from_number          TEXT,
  to_number            TEXT,
  state                TEXT,                -- active | ended | analyzed
  started_at           TEXT,                -- ISO 8601 local
  ended_at             TEXT,
  duration_ms          INTEGER,
  transcript_json      TEXT,                -- JSON array of turn objects
  retell_analysis_json TEXT,                -- JSON of Retell call_analysis
  recording_url        TEXT,
  created_at           TEXT DEFAULT (datetime('now')),
  updated_at           TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_calls_started   ON calls(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_state     ON calls(state);

CREATE TABLE IF NOT EXISTS reviews (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  call_id              TEXT NOT NULL UNIQUE,
  success_score        INTEGER,             -- 0-100
  category             TEXT,                -- success | lost_caller | incomplete_info | wrong_routing | hallucination | escalation_failure | low_quality
  severity             TEXT,                -- low | med | high
  one_line_summary     TEXT,
  what_went_well_json  TEXT,                -- JSON array of strings
  what_went_wrong_json TEXT,                -- JSON array of strings
  specific_fixes_json  TEXT,                -- JSON array of strings
  model                TEXT,
  raw_response_json    TEXT,
  cost_cents           REAL,
  created_at           TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (call_id) REFERENCES calls(call_id)
);
CREATE INDEX IF NOT EXISTS idx_reviews_score    ON reviews(success_score);
CREATE INDEX IF NOT EXISTS idx_reviews_category ON reviews(category);
CREATE INDEX IF NOT EXISTS idx_reviews_created  ON reviews(created_at DESC);

CREATE TABLE IF NOT EXISTS recommendations (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  period_start             TEXT,
  period_end               TEXT,
  calls_reviewed           INTEGER,
  avg_success_score        REAL,
  summary_md               TEXT,
  top_issues_json          TEXT,
  proposed_prompt          TEXT,
  prior_prompt_snapshot    TEXT,
  proposed_prompt_diff     TEXT,
  retell_agent_id          TEXT,
  model                    TEXT,
  applied_at               TEXT,
  applied_by               TEXT,
  reverted_at              TEXT,
  created_at               TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recs_created ON recommendations(created_at DESC);
"""


def db_init():
    """Create the data dir + open the SQLite connection. Idempotent."""
    global _DB_CONN
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(DB_SCHEMA)
    _DB_CONN = conn
    logger.info(f"[db] opened {DB_PATH}")


def db():
    """Return the shared connection (call db_init first)."""
    if _DB_CONN is None:
        db_init()
    return _DB_CONN


def db_upsert_call(c):
    """Write-through: store the current state of a call into SQLite."""
    if not c or not c.get("call_id"):
        return
    payload = (
        c.get("call_id"),
        c.get("from_number") or "",
        c.get("to_number") or "",
        c.get("state") or "",
        c.get("started_at") or "",
        c.get("ended_at") or "",
        int(c.get("duration_ms") or 0),
        json.dumps(c.get("transcript") or []),
        json.dumps(c.get("analysis") or {}) if c.get("analysis") else None,
        c.get("recording_url") or "",
    )
    with _DB_LOCK:
        db().execute("""
            INSERT INTO calls (
                call_id, from_number, to_number, state,
                started_at, ended_at, duration_ms,
                transcript_json, retell_analysis_json, recording_url,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(call_id) DO UPDATE SET
                from_number          = COALESCE(NULLIF(excluded.from_number, ''), calls.from_number),
                to_number            = COALESCE(NULLIF(excluded.to_number, ''),   calls.to_number),
                state                = excluded.state,
                started_at           = COALESCE(NULLIF(excluded.started_at, ''),  calls.started_at),
                ended_at             = COALESCE(NULLIF(excluded.ended_at, ''),    calls.ended_at),
                duration_ms          = COALESCE(NULLIF(excluded.duration_ms, 0),  calls.duration_ms),
                transcript_json      = excluded.transcript_json,
                retell_analysis_json = COALESCE(excluded.retell_analysis_json,    calls.retell_analysis_json),
                recording_url        = COALESCE(NULLIF(excluded.recording_url, ''), calls.recording_url),
                updated_at           = datetime('now');
        """, payload)


def db_load_recent_calls(days=7, limit=500):
    """Return rows from `calls` ordered newest-first within the window."""
    cutoff = (datetime.now(LOCAL_TZ) - timedelta(days=days)).isoformat()
    with _DB_LOCK:
        rows = db().execute("""
            SELECT * FROM calls
             WHERE started_at >= ?
             ORDER BY started_at DESC
             LIMIT ?
        """, (cutoff, limit)).fetchall()
    return [dict(r) for r in rows]


def db_call_to_dict(row):
    """Hydrate a SQLite row into the same shape ACTIVE_CALLS expects."""
    if isinstance(row, sqlite3.Row):
        row = dict(row)
    return {
        "call_id":       row["call_id"],
        "state":         row["state"],
        "from_number":   row["from_number"],
        "to_number":     row["to_number"],
        "started_at":    row["started_at"],
        "ended_at":      row["ended_at"] or None,
        "duration_ms":   row["duration_ms"] or 0,
        "transcript":    json.loads(row["transcript_json"] or "[]"),
        "analysis":      json.loads(row["retell_analysis_json"] or "null"),
        "recording_url": row["recording_url"] or "",
    }


def db_unreviewed_call_ids(limit=20):
    """Calls that have a Retell analysis but no Claude review yet."""
    with _DB_LOCK:
        rows = db().execute("""
            SELECT c.call_id
              FROM calls c
              LEFT JOIN reviews r ON r.call_id = c.call_id
             WHERE c.retell_analysis_json IS NOT NULL
               AND r.id IS NULL
             ORDER BY c.started_at DESC
             LIMIT ?
        """, (limit,)).fetchall()
    return [r["call_id"] for r in rows]


def db_review_for(call_id):
    """Return the review row for a call, or None."""
    with _DB_LOCK:
        row = db().execute("SELECT * FROM reviews WHERE call_id = ?", (call_id,)).fetchone()
    return dict(row) if row else None


def db_review_to_dict(row):
    if isinstance(row, sqlite3.Row):
        row = dict(row)
    return {
        "id":               row.get("id"),
        "call_id":          row["call_id"],
        "success_score":    row.get("success_score"),
        "category":         row.get("category"),
        "severity":         row.get("severity"),
        "one_line_summary": row.get("one_line_summary") or "",
        "what_went_well":   json.loads(row.get("what_went_well_json") or "[]"),
        "what_went_wrong":  json.loads(row.get("what_went_wrong_json") or "[]"),
        "specific_fixes":   json.loads(row.get("specific_fixes_json") or "[]"),
        "model":            row.get("model"),
        "created_at":       row.get("created_at"),
    }


def db_save_review(call_id, parsed, raw, model, cost_cents=None):
    with _DB_LOCK:
        db().execute("""
            INSERT INTO reviews (
                call_id, success_score, category, severity, one_line_summary,
                what_went_well_json, what_went_wrong_json, specific_fixes_json,
                model, raw_response_json, cost_cents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(call_id) DO UPDATE SET
                success_score        = excluded.success_score,
                category             = excluded.category,
                severity             = excluded.severity,
                one_line_summary     = excluded.one_line_summary,
                what_went_well_json  = excluded.what_went_well_json,
                what_went_wrong_json = excluded.what_went_wrong_json,
                specific_fixes_json  = excluded.specific_fixes_json,
                model                = excluded.model,
                raw_response_json    = excluded.raw_response_json,
                cost_cents           = excluded.cost_cents,
                created_at           = datetime('now');
        """, (
            call_id,
            int(parsed.get("success_score", 0)),
            parsed.get("category", "unknown"),
            parsed.get("severity", "low"),
            (parsed.get("one_line_summary") or "")[:240],
            json.dumps(parsed.get("what_went_well") or []),
            json.dumps(parsed.get("what_went_wrong") or []),
            json.dumps(parsed.get("specific_fixes") or []),
            model,
            json.dumps(raw)[:8000] if raw is not None else None,
            cost_cents,
        ))


# ============================================================
# CALL QUALITY REVIEWER (Claude Haiku 4.5)
# ============================================================

REVIEWER_SYSTEM = """You are a quality assurance analyst grading calls handled by the voice agent for High Tech Air Conditioning (Orlando, FL). The agent's job is to schedule service appointments by phone.

The agent's job is to: warmly greet, identify the service need, collect customer info (name, phone, email, full address), check availability, and book — OR — transfer emergencies after the $120 fee, OR flag duct cleaning for a callback (never book it).

The agent's hard rules:
- Never quotes prices or diagnoses problems.
- Always collects: first/last name, phone, email, full street address.
- Service area is fixed: Orlando, Winter Park, Winter Garden, Kissimmee, Davenport, Clermont, Windermere, Doctor Phillips, Celebration, Lake Buena Vista. Anything outside is callback-only.
- Emergencies (no AC, no heat, water leak): require $120 fee acceptance, then transfer to on-call tech. If declined, schedule a regular slot.
- Duct cleaning is NEVER booked — only logged for callback.
- Hours are 6 AM – 10 PM, 7 days, 2-hour windows.

Categories — pick exactly ONE:
- success: caller's need was fully addressed (booked correctly, transferred correctly, or accurately routed to callback).
- lost_caller: caller hung up frustrated or before getting what they wanted.
- incomplete_info: agent failed to collect a required field, or proceeded without it.
- wrong_routing: agent missed an emergency, booked an out-of-area address, or booked a do-not-book service like duct cleaning.
- hallucination: agent invented info — prices, technicians, services not offered, hours that don't exist.
- escalation_failure: should have transferred but didn't.
- low_quality: agent was rude, robotic, long-winded, or repeated questions unnecessarily.

Severity:
- low — minor friction, customer outcome was fine.
- med — customer got a result but with avoidable friction.
- high — wrong business outcome (out-of-area booking, missed emergency, hallucinated info, lost the customer).

Output ONLY a single JSON object with this exact shape — no prose, no markdown fences:
{
  "success_score": <integer 0-100>,
  "category": "<one of: success, lost_caller, incomplete_info, wrong_routing, hallucination, escalation_failure, low_quality>",
  "severity": "<low | med | high>",
  "one_line_summary": "<≤120 chars, specific>",
  "what_went_well": ["<short bullet>", "..."],
  "what_went_wrong": ["<short bullet>", "..."],
  "specific_fixes": ["<concrete prompt change that would prevent this>", "..."]
}

Be specific in `specific_fixes` — quote the rule that was violated when possible. If nothing went wrong, return an empty array, do not invent issues."""


def _format_transcript(turns):
    if not turns:
        return "(empty)"
    lines = []
    for t in turns:
        role = (t.get("role") or "").lower()
        content = t.get("content") or t.get("transcript") or ""
        if role == "agent":
            lines.append(f"SARAH: {content}")
        elif role == "user":
            lines.append(f"CALLER: {content}")
        elif role == "tool_call_invocation":
            lines.append(f"[tool: {t.get('name','?')}({json.dumps(t.get('arguments',{}))[:200]})]")
        elif role == "tool_call_result":
            lines.append(f"[tool result]")
        else:
            lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _review_user_message(call):
    a = call.get("analysis") or {}
    cad = a.get("custom_analysis_data") or {}
    return (
        f"Call ID: {call.get('call_id','?')}\n"
        f"From: {call.get('from_number','?')}  Duration: {int((call.get('duration_ms') or 0)/1000)}s\n"
        f"Retell-reported outcome: {cad.get('outcome','?')}\n"
        f"Retell-reported sentiment: {a.get('user_sentiment','?')}\n"
        f"Retell call_successful flag: {a.get('call_successful','?')}\n"
        f"Retell summary: {a.get('call_summary','(none)')}\n\n"
        f"=== TRANSCRIPT ===\n{_format_transcript(call.get('transcript') or [])}"
    )


def _parse_json_object(text):
    """Best-effort JSON extraction from Claude's response."""
    if not text:
        return None
    text = text.strip()
    # Strip ```json fences if present
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        # Try to locate the first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except Exception:
                return None
    return None


def claude_review_call(call):
    """Send a single call to Claude Haiku and return the parsed review dict (or None)."""
    if not ANTHROPIC_API_KEY:
        logger.warning("[reviewer] ANTHROPIC_API_KEY not set — skipping")
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": REVIEW_MODEL,
                "max_tokens": 1024,
                "system": [{
                    "type": "text",
                    "text": REVIEWER_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": _review_user_message(call)}],
            },
            timeout=60,
        )
        if r.status_code != 200:
            logger.error(f"[reviewer] {call.get('call_id','?')[:20]} HTTP {r.status_code}: {r.text[:200]}")
            return None
        body = r.json()
        text = "".join(b.get("text","") for b in (body.get("content") or []) if b.get("type") == "text")
        parsed = _parse_json_object(text)
        if not parsed:
            logger.error(f"[reviewer] {call.get('call_id','?')[:20]} unparseable: {text[:200]}")
            return None
        # Estimate cost in cents (Haiku: $0.80/1M in, $4.00/1M out)
        u = body.get("usage") or {}
        cost_cents = (u.get("input_tokens",0) * 0.00008) + (u.get("output_tokens",0) * 0.0004)
        return parsed, body, cost_cents
    except Exception as e:
        logger.error(f"[reviewer] {call.get('call_id','?')[:20]} error: {e}")
        return None


def review_one_call(call_id):
    """Hydrate a call from DB, run the reviewer, persist the result."""
    with _DB_LOCK:
        row = db().execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
    if not row:
        return False
    call = db_call_to_dict(row)
    out = claude_review_call(call)
    if not out:
        return False
    parsed, raw, cost_cents = out
    db_save_review(call_id, parsed, raw, REVIEW_MODEL, cost_cents)
    logger.info(f"[reviewer] {call_id[:20]} → score={parsed.get('success_score')} cat={parsed.get('category')} ¢{cost_cents:.2f}")
    return True


def reviewer_loop():
    """Pick up unreviewed analyzed calls every REVIEW_INTERVAL_S seconds."""
    logger.info(f"[reviewer] loop started (every {REVIEW_INTERVAL_S}s, model={REVIEW_MODEL})")
    while True:
        try:
            _reconcile_stale_active(broadcast=True)  # sweep stuck-active calls every cycle
            ids = db_unreviewed_call_ids(limit=10)
            for cid in ids:
                review_one_call(cid)
                gevent.sleep(0.5)  # gentle pacing
        except Exception as e:
            logger.exception(f"[reviewer] loop iteration failed: {e}")
        gevent.sleep(REVIEW_INTERVAL_S)


# ============================================================
# RETELL AGENT HELPERS — read + update the conversation flow
# ============================================================

def retell_get_agent(agent_id):
    if not RETELL_API_KEY or not agent_id:
        return None
    try:
        r = requests.get(
            f"https://api.retellai.com/get-agent/{agent_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            timeout=20,
        )
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"[retell] get_agent failed: {e}")
        return None


def retell_get_conversation_flow(flow_id):
    try:
        r = requests.get(
            f"https://api.retellai.com/get-conversation-flow/{flow_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            timeout=20,
        )
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"[retell] get_conversation_flow failed: {e}")
        return None


def fetch_current_global_prompt():
    """Returns (flow_id, global_prompt, version) or (None, None, None)."""
    if not RETELL_AGENT_ID:
        return None, None, None
    agent = retell_get_agent(RETELL_AGENT_ID)
    if not agent:
        return None, None, None
    re_ = agent.get("response_engine") or {}
    flow_id = re_.get("conversation_flow_id")
    if not flow_id:
        logger.warning(f"[retell] agent {RETELL_AGENT_ID} is not a conversation-flow agent (type={re_.get('type')})")
        return None, None, None
    flow = retell_get_conversation_flow(flow_id)
    if not flow:
        return flow_id, None, None
    return flow_id, flow.get("global_prompt") or "", flow.get("version")


def retell_update_global_prompt(flow_id, new_global_prompt):
    """PATCH the conversation flow with a new global_prompt. Returns (ok, message)."""
    try:
        r = requests.patch(
            f"https://api.retellai.com/update-conversation-flow/{flow_id}",
            headers={
                "Authorization": f"Bearer {RETELL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"global_prompt": new_global_prompt},
            timeout=30,
        )
        ok = r.status_code in (200, 201, 204)
        return ok, (r.text[:500] if not ok else "ok")
    except Exception as e:
        return False, str(e)


def retell_list_calls(limit=10):
    """Fetch the most recent N calls from Retell."""
    try:
        r = requests.post(
            "https://api.retellai.com/v2/list-calls",
            headers={
                "Authorization": f"Bearer {RETELL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"limit": limit, "sort_order": "descending"},
            timeout=30,
        )
        if r.status_code != 200:
            logger.error(f"[retell] list-calls HTTP {r.status_code}: {r.text[:300]}")
            return []
        data = r.json()
        if isinstance(data, dict):
            data = data.get("calls") or data.get("data") or []
        return data or []
    except Exception as e:
        logger.error(f"[retell] list-calls error: {e}")
        return []


def _ms_to_iso(epoch_ms):
    if not epoch_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)
        return dt.isoformat()
    except Exception:
        return ""


def _normalize_retell_call(c):
    """Convert a Retell call object into the shape our DB / dashboard expects."""
    if not c.get("call_id"):
        return None
    state = "active"
    if c.get("call_status") in ("ended", "error"):
        state = "analyzed" if c.get("call_analysis") else "ended"
    return {
        "call_id":       c["call_id"],
        "from_number":   c.get("from_number") or "",
        "to_number":     c.get("to_number") or "",
        "state":         state,
        "started_at":    _ms_to_iso(c.get("start_timestamp")),
        "ended_at":      _ms_to_iso(c.get("end_timestamp")),
        "duration_ms":   int(c.get("duration_ms") or 0),
        "transcript":    c.get("transcript_object") or [],
        "analysis":      c.get("call_analysis") or None,
        "recording_url": c.get("recording_url") or "",
    }


def backfill_recent_calls(limit=10, run_reviews=True):
    """Pull the last N calls from Retell, persist them, optionally review immediately.
    Returns a stats dict."""
    raw = retell_list_calls(limit=limit)
    stats = {"fetched": len(raw), "imported": 0, "reviewed": 0, "skipped_no_analysis": 0, "review_errors": 0}
    for c in raw:
        norm = _normalize_retell_call(c)
        if not norm:
            continue
        ACTIVE_CALLS[norm["call_id"]] = norm
        db_upsert_call(norm)
        stats["imported"] += 1
        # Trigger review inline so the dashboard fills in immediately
        if run_reviews and norm.get("analysis"):
            try:
                ok = review_one_call(norm["call_id"])
                if ok:
                    stats["reviewed"] += 1
                else:
                    stats["review_errors"] += 1
            except Exception as e:
                logger.error(f"[backfill] review of {norm['call_id'][:20]} failed: {e}")
                stats["review_errors"] += 1
        elif not norm.get("analysis"):
            stats["skipped_no_analysis"] += 1
    logger.info(f"[backfill] {stats}")
    return stats


# ============================================================
# DAILY SYNTHESIS (Claude Opus 4.7) — proposes a new global_prompt
# ============================================================

SYNTH_SYSTEM = """You are a senior conversational AI engineer reviewing a 24-hour window of calls handled by a voice agent for High Tech Air Conditioning. The agent runs on Retell's conversation-flow runtime; you are editing its `global_prompt` ONLY (the system-level instructions every node inherits).

You will receive:
1. The CURRENT `global_prompt` running in production.
2. A summary of every call reviewed in the window: score, category, severity, what went wrong, and proposed fixes.

Your task: produce a structured improvement plan plus a concrete updated `global_prompt`.

Hard rules for your output:
- Preserve all factual constraints already in the prompt: business identity, service area cities, hard rules (no pricing, no diagnosis, $120 emergency fee, duct cleaning is never booked), required info collection list. Don't drop them.
- Only change wording/structure that demonstrably caused failures in the reviews. If reviews show no signal for a section, leave it alone.
- Keep length ≤ 1.5x the current prompt. Tighter is better.
- Do not add new sections unless a recurring failure pattern justifies it.
- Each prompt change must trace to a category in the reviews. State the trace in `rationale`.
- If fewer than 3 reviews were provided, set `proposed_prompt` to the current prompt unchanged and explain in `summary` that there isn't enough signal yet.

Output ONLY a single JSON object — no prose, no markdown fences:
{
  "summary": "<≤300 word markdown overview: how the agent did, top failure pattern, top win>",
  "top_issues": [
    {"category": "<one category>", "count": <int>, "examples": ["<call_id>", ...], "fix_strategy": "<one sentence>"},
    ...
  ],
  "proposed_global_prompt": "<the FULL new global_prompt — entire text, not a diff>",
  "rationale": "<paragraph mapping prompt edits to specific review patterns>"
}"""


def _compact_review_for_synth(row):
    """Shrink a review row to a small dict for the synthesis context."""
    return {
        "call_id":          row["call_id"],
        "score":            row.get("success_score"),
        "category":         row.get("category"),
        "severity":         row.get("severity"),
        "summary":          (row.get("one_line_summary") or "")[:160],
        "what_went_wrong":  json.loads(row.get("what_went_wrong_json") or "[]")[:4],
        "specific_fixes":   json.loads(row.get("specific_fixes_json") or "[]")[:4],
    }


def _synth_user_message(current_prompt, compact_reviews, period_label):
    return (
        f"=== PERIOD ===\n{period_label}\n"
        f"Reviews in window: {len(compact_reviews)}\n\n"
        f"=== CURRENT global_prompt ===\n{current_prompt}\n\n"
        f"=== REVIEWS ===\n{json.dumps(compact_reviews, ensure_ascii=False, indent=2)}"
    )


def claude_synthesize(current_prompt, compact_reviews, period_label):
    """Call Opus to propose a new global_prompt. Returns (parsed, raw, cost_cents) or None."""
    if not ANTHROPIC_API_KEY:
        logger.warning("[synth] ANTHROPIC_API_KEY not set — skipping")
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": SYNTH_MODEL,
                "max_tokens": 4096,
                "system": [{
                    "type": "text",
                    "text": SYNTH_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": _synth_user_message(current_prompt, compact_reviews, period_label)}],
            },
            timeout=120,
        )
        if r.status_code != 200:
            logger.error(f"[synth] HTTP {r.status_code}: {r.text[:300]}")
            return None
        body = r.json()
        text = "".join(b.get("text","") for b in (body.get("content") or []) if b.get("type") == "text")
        parsed = _parse_json_object(text)
        if not parsed or not parsed.get("proposed_global_prompt"):
            logger.error(f"[synth] unparseable response: {text[:300]}")
            return None
        u = body.get("usage") or {}
        # Opus 4.7: $15/1M input, $75/1M output (≈ in cents per token)
        cost_cents = (u.get("input_tokens",0) * 0.0015) + (u.get("output_tokens",0) * 0.0075)
        return parsed, body, cost_cents
    except Exception as e:
        logger.error(f"[synth] error: {e}")
        return None


def _make_diff(old_text, new_text):
    """Return a unified diff string."""
    import difflib
    diff = difflib.unified_diff(
        (old_text or "").splitlines(keepends=False),
        (new_text or "").splitlines(keepends=False),
        fromfile="current global_prompt",
        tofile="proposed global_prompt",
        lineterm="",
    )
    return "\n".join(diff)


def db_save_recommendation(period_start, period_end, calls_reviewed, avg_score,
                            summary_md, top_issues, proposed_prompt, prior_prompt,
                            diff_text, model):
    with _DB_LOCK:
        cur = db().execute("""
            INSERT INTO recommendations (
                period_start, period_end, calls_reviewed, avg_success_score,
                summary_md, top_issues_json, proposed_prompt, prior_prompt_snapshot,
                proposed_prompt_diff, retell_agent_id, model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            period_start, period_end, calls_reviewed, avg_score,
            summary_md, json.dumps(top_issues or []),
            proposed_prompt, prior_prompt, diff_text,
            RETELL_AGENT_ID, model,
        ))
    return cur.lastrowid


def db_list_recommendations(limit=20):
    with _DB_LOCK:
        rows = db().execute("""
            SELECT id, period_start, period_end, calls_reviewed, avg_success_score,
                   summary_md, top_issues_json, applied_at, applied_by, reverted_at,
                   model, created_at
              FROM recommendations
             ORDER BY created_at DESC
             LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def db_get_recommendation(rec_id):
    with _DB_LOCK:
        row = db().execute("SELECT * FROM recommendations WHERE id = ?", (rec_id,)).fetchone()
    return dict(row) if row else None


def db_mark_applied(rec_id, by="dashboard"):
    with _DB_LOCK:
        db().execute("UPDATE recommendations SET applied_at = datetime('now'), applied_by = ?, reverted_at = NULL WHERE id = ?", (by, rec_id))


def db_mark_reverted(rec_id):
    with _DB_LOCK:
        db().execute("UPDATE recommendations SET reverted_at = datetime('now') WHERE id = ?", (rec_id,))


def synthesize_window(window_hours=24, force=False):
    """Run a full synthesis pass over the last `window_hours`. Returns the recommendation id, or None."""
    cutoff = (datetime.now(LOCAL_TZ) - timedelta(hours=window_hours))
    cutoff_iso = cutoff.isoformat()
    with _DB_LOCK:
        rows = db().execute("""
            SELECT * FROM reviews WHERE created_at >= ? ORDER BY created_at DESC
        """, (cutoff_iso,)).fetchall()
    rows = [dict(r) for r in rows]
    if len(rows) < 3 and not force:
        logger.info(f"[synth] only {len(rows)} reviews in last {window_hours}h, skipping (need ≥3 unless force=true)")
        return None
    flow_id, current_prompt, version = fetch_current_global_prompt()
    if not current_prompt:
        logger.error("[synth] could not fetch current global_prompt — RETELL_AGENT_ID set?")
        return None
    avg_score = sum(r.get("success_score") or 0 for r in rows) / max(1, len(rows))
    compact = [_compact_review_for_synth(r) for r in rows]
    period_label = f"{cutoff.strftime('%Y-%m-%d %H:%M %Z')} → now"
    out = claude_synthesize(current_prompt, compact, period_label)
    if not out:
        return None
    parsed, raw, cost_cents = out
    proposed = (parsed.get("proposed_global_prompt") or "").strip()
    if not proposed:
        logger.error("[synth] empty proposed prompt — bailing")
        return None
    diff_text = _make_diff(current_prompt, proposed)
    rec_id = db_save_recommendation(
        period_start=cutoff_iso,
        period_end=datetime.now(LOCAL_TZ).isoformat(),
        calls_reviewed=len(rows),
        avg_score=round(avg_score, 1),
        summary_md=parsed.get("summary") or "",
        top_issues=parsed.get("top_issues") or [],
        proposed_prompt=proposed,
        prior_prompt=current_prompt,
        diff_text=diff_text,
        model=SYNTH_MODEL,
    )
    logger.info(f"[synth] rec#{rec_id} saved (calls={len(rows)} avg={avg_score:.1f} ¢{cost_cents:.2f})")
    return rec_id


def _seconds_until_next_local_hour(hour):
    """Seconds from now until the next time it's <hour>:00 in LOCAL_TZ."""
    now = datetime.now(LOCAL_TZ)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return max(60, int((target - now).total_seconds()))


def synthesis_loop():
    """Run synthesize_window() once a day at SYNTH_HOUR_LOCAL."""
    logger.info(f"[synth] loop started (target hour={SYNTH_HOUR_LOCAL} {LOCAL_TZ}, model={SYNTH_MODEL})")
    while True:
        wait_s = _seconds_until_next_local_hour(SYNTH_HOUR_LOCAL)
        logger.info(f"[synth] next run in {wait_s//60}m")
        gevent.sleep(wait_s)
        try:
            synthesize_window(window_hours=24, force=False)
        except Exception as e:
            logger.exception(f"[synth] loop iteration failed: {e}")


# ============================================================
# STARTUP — open DB, hydrate ACTIVE_CALLS, spawn reviewer
# ============================================================
db_init()


def hydrate_active_calls():
    """Load the most recent calls from SQLite into ACTIVE_CALLS so the dashboard shows history immediately."""
    try:
        rows = db_load_recent_calls(days=7, limit=200)
        for r in rows:
            c = db_call_to_dict(r)
            ACTIVE_CALLS[c["call_id"]] = c
        logger.info(f"[hydrate] loaded {len(rows)} calls from {DB_PATH}")
        _reconcile_stale_active()  # clear any "active" call whose end-event was missed before a restart
    except Exception as e:
        logger.exception(f"[hydrate] failed: {e}")


def _reconcile_stale_active(broadcast=False):
    """Mark any call still 'active'/'ongoing' past the max plausible call length as ended.
    A missed call_ended webhook (or a restart mid-call) would otherwise leave a phantom
    'unknown' live call on the dashboard forever."""
    now = datetime.now(LOCAL_TZ)
    fixed = []
    for cid, c in list(ACTIVE_CALLS.items()):
        if c.get("state") not in ("active", "ongoing"):
            continue
        stale = True
        sa = c.get("started_at")
        if sa:
            try:
                stale = (now - datetime.fromisoformat(sa)).total_seconds() > STALE_ACTIVE_SECONDS
            except Exception:
                stale = True
        if stale:
            c["state"] = "ended"
            c.setdefault("ended_at", now.isoformat())
            try:
                db_upsert_call(c)
            except Exception:
                pass
            fixed.append(cid)
    if fixed:
        logger.info(f"[stale] reconciled {len(fixed)} stuck-active call(s)")
        if broadcast:
            for cid in fixed:
                try:
                    broadcast_event("call_ended", ACTIVE_CALLS[cid])
                except Exception:
                    pass
    return fixed


# ACTIVE_CALLS is defined later; hydration runs after that block — see _start_background_jobs()


# ============================================================
# HOUSECALL PRO API HELPERS
# ============================================================

def hcp_headers():
    return {
        "Authorization": f"Token {HCP_API_KEY}",
        "Content-Type": "application/json",
    }


HCP_TIMEOUT = 15  # seconds — never let a slow HCP response hang the single worker


def hcp_get(endpoint, params=None):
    """Make a GET request to Housecall Pro API."""
    resp = requests.get(
        f"{HCP_BASE_URL}{endpoint}",
        headers=hcp_headers(),
        params=params or {},
        timeout=HCP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def hcp_post(endpoint, data):
    """Make a POST request to Housecall Pro API."""
    resp = requests.post(
        f"{HCP_BASE_URL}{endpoint}",
        headers=hcp_headers(),
        json=data,
        timeout=HCP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _digits10(phone):
    """Last 10 digits of a phone string, or '' if fewer than 10."""
    import re
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else ""


def hcp_find_customer_by_phone(phone, timeout=6.0):
    """
    Look up an existing HCP customer by the calling phone number.

    Returns the best single match as a normalized dict, or None. "Best" =
    most recently updated customer that has a service address (falling back to
    most recent overall). The caller still CONFIRMS this profile before we use
    it — see the create_appointment / prompt flow — so an imperfect pick is
    corrected on the call rather than silently trusted.
    """
    last10 = _digits10(phone)
    if not last10:
        return None
    try:
        resp = requests.get(
            f"{HCP_BASE_URL}/customers",
            headers=hcp_headers(),
            params={"q": last10, "page_size": 20},
            timeout=timeout,
        )
        resp.raise_for_status()
        custs = resp.json().get("customers", []) or []
    except Exception as e:
        logger.warning(f"[hcp-lookup] customer search failed: {e}")
        return None

    def num_match(c):
        for f in ("mobile_number", "home_number", "work_number"):
            if _digits10(c.get(f)) == last10:
                return True
        return False

    matches = [c for c in custs if num_match(c)]
    if not matches:
        return None

    with_addr = [c for c in matches if (c.get("addresses") or [])]
    pool = with_addr or matches
    best = max(pool, key=lambda c: c.get("updated_at") or c.get("created_at") or "")

    addrs = best.get("addresses") or []
    addr = addrs[0] if addrs else {}
    street = (addr.get("street") or "").strip()
    return {
        "customer_id": best.get("id", "") or "",
        "first_name": best.get("first_name", "") or "",
        "last_name": best.get("last_name", "") or "",
        "email": best.get("email", "") or "",
        "has_email": bool(best.get("email")),
        "address_id": addr.get("id", "") or "",
        "street": street,
        "street_number": street.split()[0] if street else "",
        "city": (addr.get("city") or "").strip(),
        "state": (addr.get("state") or "").strip(),
        "zip": (addr.get("zip") or "").strip(),
    }


def get_busy_hours_by_tech(start_date, end_date):
    """
    Query HCP for all scheduled jobs in a date range.
    Returns a dict: { tech_id: set of (date, hour) tuples } in local Orlando time.
    """
    params = {
        "scheduled_start_min": start_date.astimezone(timezone.utc).strftime("%Y-%m-%dT00:00:00Z"),
        "scheduled_start_max": end_date.astimezone(timezone.utc).strftime("%Y-%m-%dT23:59:59Z"),
        "work_status[]": "scheduled",
        "page_size": 200,
    }
    # Paginate — a single 200-job page silently dropped later jobs in a busy week,
    # making occupied hours look free → double-booking. Loop until a short page (cap 10 pages).
    existing_jobs = []
    page = 1
    while page <= 10:
        params["page"] = page
        data = hcp_get("/jobs", params=params)
        batch = data.get("jobs", [])
        existing_jobs.extend(batch)
        if len(batch) < params["page_size"]:
            break
        page += 1
    else:
        logger.warning("[availability] HCP /jobs hit the 10-page cap — schedule may be incomplete")

    busy_by_tech = {}
    all_busy = set()  # hours where ANY tech is busy

    for job in existing_jobs:
        schedule = job.get("schedule", {})
        job_start_str = schedule.get("scheduled_start")
        job_end_str = schedule.get("scheduled_end")
        if not job_start_str or not job_end_str:
            continue
        try:
            job_start_utc = datetime.fromisoformat(job_start_str.replace("Z", "+00:00"))
            job_end_utc = datetime.fromisoformat(job_end_str.replace("Z", "+00:00"))
            job_start_local = job_start_utc.astimezone(LOCAL_TZ)
            job_end_local = job_end_utc.astimezone(LOCAL_TZ)

            # Get assigned tech IDs
            tech_ids = [e.get("id") for e in job.get("assigned_employees", [])]

            # Mark every hour this job occupies
            current_hour = job_start_local.replace(minute=0, second=0, microsecond=0)
            while current_hour < job_end_local:
                hour_key = (current_hour.date(), current_hour.hour)
                all_busy.add(hour_key)
                for tid in tech_ids:
                    if tid not in busy_by_tech:
                        busy_by_tech[tid] = set()
                    busy_by_tech[tid].add(hour_key)
                current_hour += timedelta(hours=1)
        except (ValueError, AttributeError):
            pass

    return busy_by_tech, all_busy


# ============================================================
# AVAILABILITY CACHE — avoids slow HCP queries on every call
# ============================================================
# HCP /jobs pagination can take 30-45 s per check. We pre-warm on startup,
# refresh every 4 min in background, and serve check_availability from cache
# (< 1 s). The create_appointment double-check still hits HCP live.
_AVAIL_CACHE: dict = {
    "busy_by_tech": {},
    "all_busy": set(),
    "fetched_at": 0.0,
    "cache_date": None,
}
_AVAIL_CACHE_TTL = 300  # seconds (5 min)


def _refresh_avail_cache() -> None:
    now = datetime.now(LOCAL_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=DAYS_AHEAD_TO_CHECK + 1)
    try:
        busy_by_tech, all_busy = get_busy_hours_by_tech(start, end)
        _AVAIL_CACHE["busy_by_tech"] = busy_by_tech
        _AVAIL_CACHE["all_busy"] = all_busy
        _AVAIL_CACHE["fetched_at"] = time.time()
        _AVAIL_CACHE["cache_date"] = now.date()
        logger.info("[avail-cache] refreshed OK")
    except Exception as exc:
        logger.warning(f"[avail-cache] refresh failed: {exc}")


def _avail_cache_loop() -> None:
    while True:
        gevent.sleep(250)
        _refresh_avail_cache()


def get_busy_hours_cached(start_date, end_date):
    """Return busy hours from cache when fresh; fall back to live HCP otherwise."""
    now_ts = time.time()
    today = datetime.now(LOCAL_TZ).date()
    if (
        _AVAIL_CACHE["fetched_at"] > 0
        and now_ts - _AVAIL_CACHE["fetched_at"] < _AVAIL_CACHE_TTL
        and _AVAIL_CACHE["cache_date"] == today
    ):
        return _AVAIL_CACHE["busy_by_tech"], _AVAIL_CACHE["all_busy"]
    # Cache miss — fetch live and populate for next caller
    busy_by_tech, all_busy = get_busy_hours_by_tech(start_date, end_date)
    _AVAIL_CACHE["busy_by_tech"] = busy_by_tech
    _AVAIL_CACHE["all_busy"] = all_busy
    _AVAIL_CACHE["fetched_at"] = now_ts
    _AVAIL_CACHE["cache_date"] = today
    return busy_by_tech, all_busy


# ============================================================
# ON-CALL SCHEDULE — persisted to JSON file on Railway disk
# ============================================================
# Persist to the Railway volume (DATA_DIR=/data), NOT /tmp — /tmp is wiped on every
# redeploy/restart, which silently erased the on-call schedule (so the AI fell back to
# all techs). DATA_DIR survives deploys.
ONCALL_FILE = os.environ.get("ONCALL_FILE", os.path.join(DATA_DIR, "oncall_schedule.json"))

def load_oncall():
    """
    Per-date on-call schedule:
    {
      "dates": {
         "2026-05-04": ["pro_id1"],
         "2026-05-05": ["pro_id1", "pro_id2"]
      }
    }
    Date keys are YYYY-MM-DD. If no entry for a date, ALL techs are eligible (default).
    Empty list also means default behavior.
    """
    try:
        if os.path.exists(ONCALL_FILE):
            with open(ONCALL_FILE) as f:
                data = json.load(f)
            # Migrate old "weeks" format if present
            if "dates" not in data and "weeks" in data:
                data = {"dates": {}}
            return data
    except Exception as e:
        logger.error(f"[oncall] load failed: {e}")
    return {"dates": {}}


def save_oncall(data):
    try:
        with open(ONCALL_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"[oncall] save failed: {e}")
        return False


def get_eligible_techs_for_date(date_obj):
    """
    Return the list of techs eligible for assignment on a given date.
    - If the date has an explicit on-call list: only those techs are eligible.
    - Otherwise: all FIELD_TECHS (default).
    """
    schedule = load_oncall()
    date_key = date_obj.strftime("%Y-%m-%d") if hasattr(date_obj, "strftime") else str(date_obj)
    on_call = schedule.get("dates", {}).get(date_key) or []
    if on_call:
        oncall_set = set(on_call)
        return [t for t in FIELD_TECHS if t["id"] in oncall_set]
    return list(FIELD_TECHS)


def find_available_tech(busy_by_tech, date_obj, start_hour, duration_hours):
    """Find a field tech who is free for all hours in the requested slot AND eligible for that date (on-call/not-off)."""
    eligible = get_eligible_techs_for_date(date_obj)
    for tech in eligible:
        tech_busy = busy_by_tech.get(tech["id"], set())
        is_free = True
        for h in range(start_hour, start_hour + duration_hours):
            if (date_obj, h) in tech_busy:
                is_free = False
                break
        if is_free:
            return tech
    return None


# ============================================================
# TRANSFER CONTACTS — dashboard-managed numbers the AI transfers to.
# Persisted to the Railway volume (DATA_DIR). Two roles: 'alfredo' and 'human'.
# /retell/inbound feeds the chosen numbers into the transfer_call tools' dynamic
# variables; falls back to the env vars when no contact is assigned to a role.
# ============================================================
TRANSFER_FILE = os.environ.get("TRANSFER_FILE", os.path.join(DATA_DIR, "transfer_contacts.json"))


def load_transfer():
    try:
        if os.path.exists(TRANSFER_FILE):
            with open(TRANSFER_FILE) as f:
                d = json.load(f)
            d.setdefault("contacts", [])
            d.setdefault("alfredo_id", None)
            d.setdefault("human_id", None)
            d.setdefault("emergency_id", None)
            return d
    except Exception as e:
        logger.error(f"[transfer] load failed: {e}")
    return {"contacts": [], "alfredo_id": None, "human_id": None, "emergency_id": None}


def save_transfer(data):
    try:
        with open(TRANSFER_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"[transfer] save failed: {e}")
        return False


# ---- Web Push (iPhone PWA notifications) ----
PUSH_SUBS_FILE = os.environ.get("PUSH_SUBS_FILE", os.path.join(DATA_DIR, "push_subs.json"))


def load_push_subs():
    try:
        if os.path.exists(PUSH_SUBS_FILE):
            with open(PUSH_SUBS_FILE) as f:
                return json.load(f) or []
    except Exception as e:
        logger.error(f"[push] load failed: {e}")
    return []


def save_push_subs(subs):
    try:
        with open(PUSH_SUBS_FILE, "w") as f:
            json.dump(subs, f)
    except Exception as e:
        logger.error(f"[push] save failed: {e}")


def send_web_push(title, body, url="/dashboard", tag="call"):
    """Send a Web Push to every stored subscription. Fire-and-forget; prunes expired subs."""
    if not (VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY):
        return
    try:
        from pywebpush import webpush, WebPushException
    except Exception as e:
        logger.warning(f"[push] pywebpush unavailable: {e}")
        return
    subs = load_push_subs()
    if not subs:
        return
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    keep, changed = [], False
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_SUBJECT})
            keep.append(sub)
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                changed = True  # subscription gone — drop it
                logger.info("[push] pruned expired subscription")
            else:
                keep.append(sub)
                logger.warning(f"[push] send failed ({code}): {e}")
        except Exception as e:
            keep.append(sub)
            logger.warning(f"[push] send error: {e}")
    if changed:
        save_push_subs(keep)


# ── Message Center ──
# A server-side mirror of every alert. The SAME content is sent to Telegram,
# stored here for the in-app message center, and pushed to the iPhone banner —
# so all three channels stay in sync. Persisted to the Railway volume so the
# feed survives restarts.
MESSAGES_FILE = os.environ.get("MESSAGES_FILE", os.path.join(DATA_DIR, "messages.json"))
_MSG_LOCK = threading.RLock()


def load_messages():
    try:
        if os.path.exists(MESSAGES_FILE):
            with open(MESSAGES_FILE) as f:
                return json.load(f) or []
    except Exception as e:
        logger.error(f"[messages] load failed: {e}")
    return []


def save_messages(msgs):
    try:
        with open(MESSAGES_FILE, "w") as f:
            json.dump(msgs[:100], f)
    except Exception as e:
        logger.error(f"[messages] save failed: {e}")


def _peer_key(peer):
    """Group key for the Message Center: a phone's digits, or 'unknown'/'system'.
    All blank/unknown callers collapse into one 'unknown' chat; everything sharing
    the same digits lands in the same chat thread."""
    if not peer:
        return "unknown"
    if peer == "system":
        return "system"
    digits = "".join(ch for ch in str(peer) if ch.isdigit())
    return digits or "unknown"


def notify_event(ico, title, body, tg_text=None, tg_parse="Markdown", call_id="", tag="msg", peer="", meta=None):
    """One alert → three places, same content:
      1. Telegram   (rich `tg_text` if given, else a plain title/body)
      2. Dashboard message center  (persisted + broadcast live over SSE)
      3. iPhone/PWA push banner    (fires even when the app is closed)
    `peer` is the caller's phone (or 'system'); it groups the message into a
    per-number chat thread in the dashboard and deep-links the push to that chat.
    All fire-and-forget so the webhook stays fast."""
    gevent.spawn(send_telegram_alert, tg_text or f"*{title}*\n{body}", tg_parse)
    pkey = _peer_key(peer)
    item = {
        "id": uuid.uuid4().hex,
        "ico": ico,
        "title": title,
        "body": body,
        "ts": int(datetime.now(LOCAL_TZ).timestamp() * 1000),
        "call_id": call_id,
        "peer": peer,
        "peer_key": pkey,
        "meta": meta or {},
    }
    try:
        with _MSG_LOCK:
            msgs = load_messages()
            msgs.insert(0, item)
            save_messages(msgs)
    except Exception as e:
        logger.error(f"[messages] record failed: {e}")
    broadcast_event("message", item)
    gevent.spawn(send_web_push, f"{ico} {title}", body or title,
                 f"/dashboard?key={DASHBOARD_PASSWORD}&chat={pkey}", tag)
    return item


def transfer_contact_for(role):
    """The assigned contact dict for a role ('alfredo'|'human'|'emergency'), else None."""
    d = load_transfer()
    cid = d.get(f"{role}_id")
    if not cid:
        return None
    for c in d.get("contacts", []):
        if c.get("id") == cid:
            return c
    return None


def transfer_number_for(role):
    """Phone for a role ('alfredo'|'human'|'emergency') from the assigned contact, else None."""
    c = transfer_contact_for(role)
    return ((c.get("phone") or "").strip() or None) if c else None


# ============================================================
# TOOL 1: CHECK AVAILABILITY
# ============================================================

@app.route("/check-availability", methods=["POST"])
@require_retell_signature
def check_availability():
    """
    Check available appointment slots by looking at existing jobs
    in Housecall Pro and finding gaps.
    Service hours: Mon-Sun 6am-10pm (no day restrictions).
    """
    body = request.json or {}
    logger.info(f"[check-availability] Received: {json.dumps(body)[:500]}")
    # Handle both formats: Retell sends {args: {...}} or top-level params
    args = body.get("args", body)

    preferred_date = args.get("preferred_date", "")
    preferred_time = args.get("preferred_time", "")  # e.g. "16:00" or "afternoon" or "morning"

    # Parse preferred_time into target_hour (the START of the matching 2-hour window)
    target_hour = None
    if preferred_time:
        pt = str(preferred_time).strip().lower()
        if pt in ("morning",):
            target_hour = 8  # 8 AM-10 AM
        elif pt in ("afternoon",):
            target_hour = 14  # 2 PM-4 PM
        elif pt in ("evening", "night"):
            target_hour = 18  # 6 PM-8 PM
        else:
            # Try HH:MM or "4pm" / "4 pm"
            import re as _re
            m = _re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$', pt)
            if m:
                h = int(m.group(1))
                ampm = m.group(3)
                if ampm == 'pm' and h < 12:
                    h += 12
                if ampm == 'am' and h == 12:
                    h = 0
                # Honor the EXACT requested hour — we book a 2-hour arrival window
                # starting at it, so we don't snap to a fixed even-hour grid.
                target_hour = h

    try:
        now_local = datetime.now(LOCAL_TZ)

        if preferred_date:
            try:
                start_date = datetime.strptime(preferred_date, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
            except ValueError:
                start_date = now_local
            # If preferred_date AND preferred_time both specified, search up to 7 days
            # so we can find that specific time on later days if today is full
            end_date = start_date + timedelta(days=DAYS_AHEAD_TO_CHECK if target_hour is not None else 3)
        else:
            start_date = now_local
            end_date = start_date + timedelta(days=DAYS_AHEAD_TO_CHECK)

        # Get per-tech busy hours
        busy_by_tech, _ = get_busy_hours_cached(start_date, end_date)

        # Generate available slots — a slot is open if at least 1 tech is free
        # Higher cap when only one date so we return ALL slots for that day
        max_slots = 12 if (preferred_date and target_hour is None) else 8
        available_slots = []
        current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        while current.date() <= end_date.date() and len(available_slots) < max_slots:
            if current.date() < now_local.date():
                current += timedelta(days=1)
                continue

            # When the caller named a specific time, check THAT exact hour (e.g. 17:00);
            # otherwise scan the standard even-hour windows.
            hours_to_try = [target_hour] if target_hour is not None else list(range(BUSINESS_HOURS_START, BUSINESS_HOURS_END, SLOT_DURATION_HOURS))
            for hour in hours_to_try:
                # A 2-hour window must fit inside business hours (6 AM–10 PM).
                if hour < BUSINESS_HOURS_START or hour + SLOT_DURATION_HOURS > BUSINESS_HOURS_END:
                    continue
                # Enforce the minimum booking lead time (no non-emergency slots < MIN_BOOKING_LEAD_HOURS out).
                if current.replace(hour=hour, minute=0, second=0, microsecond=0) < now_local + timedelta(hours=MIN_BOOKING_LEAD_HOURS):
                    continue

                # Check if at least one tech is free for this entire slot
                tech = find_available_tech(busy_by_tech, current.date(), hour, SLOT_DURATION_HOURS)
                if tech:
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

                    if len(available_slots) >= max_slots:
                        break

            current += timedelta(days=1)

        if not available_slots:
            return jsonify({
                "result": "It looks like our schedule is quite full in the next few days. Let me have our scheduling team call you back to find the best time. Can I confirm your phone number?"
            })

        # Filter to business-hours daytime only (8 AM start, end by 5 PM / 17:00)
        # so the agent never proactively surfaces 6 AM or after-5 PM slots.
        daytime_slots = [
            s for s in available_slots
            if int(s["start_time"].split(":")[0]) >= 8
            and int(s["end_time"].split(":")[0]) <= 17
        ]
        if not daytime_slots:
            daytime_slots = available_slots  # fallback: nothing in range, use all

        # Return ALL slots for the requested day so the agent can read them all.
        # When no specific date was given, return the first 5 daytime slots.
        if preferred_date and target_hour is None:
            same_day = [s for s in daytime_slots if s["date"] == preferred_date]
            slots_to_return = same_day if same_day else daytime_slots[:5]
        elif target_hour is not None:
            slots_to_return = available_slots[:2]
        else:
            slots_to_return = daytime_slots[:5]

        slot_text = "\n".join([f"- {s['display']}" for s in slots_to_return])
        return jsonify({
            "result": json.dumps({
                "available_slots": slots_to_return,
                "display_text": f"Here are the available appointments:\n{slot_text}",
            })
        })

    except (requests.RequestException, ValueError, KeyError) as e:
        # Includes timeouts/connection errors (not just HTTPError) so a slow HCP
        # degrades to a graceful callback line instead of 500-ing mid-call.
        logger.error(f"[check-availability] failed: {e}")
        return jsonify({
            "result": "I'm having trouble checking the schedule right now. Let me take your information and have our team call you back to confirm a time."
        })


# ============================================================
# TOOL 2: CREATE APPOINTMENT
# ============================================================

@app.route("/create-appointment", methods=["POST"])
@require_retell_signature
def create_appointment():
    """
    Create a job/appointment in Housecall Pro.
    Always creates a new customer (no lookup) — collects info every time.
    Handles the duct cleaning exception: captures info but does NOT book.
    Tags emergency jobs and adds the $120 fee note.
    """
    body = request.json or {}
    logger.info(f"[create-appointment] Received: {json.dumps(body)[:500]}")
    args = body.get("args", body)

    # ── Idempotency: if this call already booked, return the same confirmation
    #    instead of creating a duplicate customer + job on a re-confirmation. ──
    retell_call_id = (body.get("call") or {}).get("call_id", "")
    if retell_call_id and retell_call_id in ACTIVE_CALLS:
        prior = ACTIVE_CALLS[retell_call_id].get("confirmation")
        if prior:
            logger.info(f"[create-appointment] duplicate suppressed for {retell_call_id[:20]}")
            return jsonify({"result": json.dumps(prior)})

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
    # Returning caller confirmed the address we have on file — reuse it as-is.
    use_address_on_file = bool(args.get("use_address_on_file", False))
    # Returning caller verbally confirmed "yes, book under that profile" — set by
    # the agent ONLY after the caller says yes. Gates booking under a found profile.
    profile_confirmed = bool(args.get("profile_confirmed", False))

    # ── Sanitize fields the LLM may have polluted ──
    # Strip LLM placeholder text like "(street name unclear from call, needs confirmation)"
    import re as _re
    if street:
        street = _re.sub(r'\s*\([^)]*\)\s*', '', street).strip()
        # Strip "???" tokens
        street = _re.sub(r'\?{2,}\s*', '', street).strip()
    # Default state to FL since the service area is exclusively Florida
    if not state or state == "":
        state = "FL"
    # If ZIP is missing, try to infer from city (most common service area zips)
    if not zip_code:
        city_zip_map = {
            "orlando": "32801",
            "winter park": "32789",
            "winter garden": "34787",
            "kissimmee": "34741",
            "davenport": "33837",
            "clermont": "34711",
            "windermere": "34786",
            "doctor phillips": "32819",
            "celebration": "34747",
            "lake buena vista": "32830",
        }
        zip_code = city_zip_map.get((city or "").lower().strip(), "")

    # ── Validation ── (name + phone + email all required)
    if not first_name or not last_name:
        return jsonify({
            "result": "I need the customer's first and last name to continue. Could you provide those?"
        })
    if not phone:
        return jsonify({
            "result": "I still need a phone number — is the number you're calling from okay to use, or is there a better one?"
        })

    # Look up the caller's existing profile once — reused for the email check,
    # the confirmation gate, and the find-or-create below.
    existing = hcp_find_customer_by_phone(phone) if phone else None

    # Email is required for our records — but a returning caller who already has
    # one on file doesn't need to give it again. (We do NOT email confirmations.)
    if not email and not (existing and existing["has_email"]):
        return jsonify({
            "result": "I also need an email for our records — what's the best email for you?"
        })

    # Honor the caller's requested START time, but always store a 2-hour arrival
    # window from it in Housecall Pro (e.g. caller asks "5 to 6" → we book 5–7).
    # We never tell the caller about the 2-hour policy.
    if start_time:
        try:
            end_time = (datetime.strptime(start_time, "%H:%M") + timedelta(hours=SLOT_DURATION_HOURS)).strftime("%H:%M")
        except ValueError:
            pass

    # ── Minimum lead time for non-emergency bookings ──
    if not is_emergency and date and start_time:
        try:
            req_start = datetime.strptime(f"{date}T{start_time}:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=LOCAL_TZ)
            if req_start < datetime.now(LOCAL_TZ) + timedelta(hours=MIN_BOOKING_LEAD_HOURS):
                return jsonify({"result": json.dumps({
                    "success": False,
                    "too_soon": True,
                    "message": f"For non-emergency visits the soonest we can schedule is about {MIN_BOOKING_LEAD_HOURS} hours out. "
                               f"Could we pick a later window? What day works best for you?",
                })})
        except ValueError:
            pass

    # ── Check slot availability before doing anything ──
    assigned_tech = None
    if date and start_time:
        try:
            req_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
            req_hour = int(start_time.split(":")[0])
            end_date_check = req_date + timedelta(days=DAYS_AHEAD_TO_CHECK)

            busy_by_tech, _ = get_busy_hours_cached(req_date, end_date_check)
            assigned_tech = find_available_tech(busy_by_tech, req_date.date(), req_hour, SLOT_DURATION_HOURS)

            if not assigned_tech:
                # Slot is full — find alternative suggestions
                alt_slots = []
                check_date = req_date.replace(hour=0, minute=0, second=0, microsecond=0)
                now_local = datetime.now(LOCAL_TZ)
                days_checked = 0
                while days_checked < DAYS_AHEAD_TO_CHECK and len(alt_slots) < 3:
                    if check_date.date() >= now_local.date():
                        for h in range(BUSINESS_HOURS_START, BUSINESS_HOURS_END, SLOT_DURATION_HOURS):
                            if check_date.replace(hour=h, minute=0, second=0, microsecond=0) < now_local + timedelta(hours=MIN_BOOKING_LEAD_HOURS):
                                continue
                            tech = find_available_tech(busy_by_tech, check_date.date(), h, SLOT_DURATION_HOURS)
                            if tech:
                                s = check_date.replace(hour=h, minute=0, second=0)
                                e = s + timedelta(hours=SLOT_DURATION_HOURS)
                                alt_slots.append(f"{s.strftime('%A, %B %d')} between {s.strftime('%-I:%M %p')} and {e.strftime('%-I:%M %p')}")
                                if len(alt_slots) >= 3:
                                    break
                    check_date += timedelta(days=1)
                    days_checked += 1

                if alt_slots:
                    suggestions = "\n".join([f"- {s}" for s in alt_slots])
                    return jsonify({
                        "result": json.dumps({
                            "success": False,
                            "slot_unavailable": True,
                            "message": f"Unfortunately that time slot is not available — all of our technicians are booked. "
                                       f"Here are the next available openings:\n{suggestions}",
                            "available_slots": alt_slots,
                        })
                    })
                else:
                    return jsonify({
                        "result": "That time slot is not available and our schedule is quite full. "
                                  "Let me have our scheduling team call you back to find the best time."
                    })
        except (ValueError, requests.HTTPError):
            pass  # If check fails, proceed anyway and let HCP handle it

    # ── Duct Cleaning Exception ──
    # Match on service_type OR notes, requiring both "duct" and "clean" so that
    # bookable "ductless" / "ductwork repair" services are NOT caught by mistake.
    _dc_text = f"{service_type} {notes}".lower()
    if "duct" in _dc_text and "clean" in _dc_text:
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
                    "country": "US",
                }
                requests.post(
                    f"{HCP_BASE_URL}/customers/{customer_id}/addresses",
                    headers=hcp_headers(),
                    json=addr_data,
                    timeout=HCP_TIMEOUT,
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

    # ── Service-area enforcement (defense in depth; the prompt gates this too) ──
    # If a city is given and it isn't one we serve, do NOT book — confirm a callback.
    if city and city.strip().lower() not in {c.lower() for c in SERVICE_AREA}:
        logger.info(f"[create-appointment] out-of-area city='{city}' — declined (no booking, no callback)")
        return jsonify({
            "result": json.dumps({
                "success": False,
                "out_of_area": True,
                "message": f"I'm sorry, but {city} is outside our Orlando service area, so we won't be "
                           "able to help with this one. (Confirm you didn't mishear the city; if it's "
                           "actually in our area, re-collect it. Otherwise apologize and end the call — "
                           "do not book and do not promise a callback.)",
            })
        })

    # ── Find-or-create the customer in Housecall Pro ──
    # A returning caller is reused (dedupe) instead of spawning a new record
    # every call. `existing` was looked up above (during validation).

    # ── HARD GATE: never book under a found profile without explicit caller
    #    confirmation. The agent must pass profile_confirmed=true, which the
    #    prompt only allows after the caller says "yes, book under that." If it's
    #    missing, refuse to book and hand back the exact line to ask. This is the
    #    server-side guarantee that prompt instructions alone weren't enforcing.
    if existing and not profile_confirmed:
        num = existing.get("street_number") or ""
        confirm_line = (
            f"I found your profile — am I right you're {existing['first_name']} {existing['last_name']}".rstrip()
            + (f", at house number {num}" if num else "")
            + (f", and the best number is {phone}" if phone else "")
            + "? Can I book it under that?"
        )
        return jsonify({"result": json.dumps({
            "needs_profile_confirmation": True,
            "say_to_caller": confirm_line,
            "message": "Do NOT book yet. Say the line in say_to_caller to the caller. Only after they say yes, call create_appointment again with profile_confirmed: true. If they say it's wrong or it's someone else, collect the correct name/address and book that instead.",
        })})

    try:
        if existing:
            customer_id = existing["customer_id"]
            # Backfill a missing email if the caller just gave us one.
            if email and not existing["has_email"]:
                try:
                    requests.patch(
                        f"{HCP_BASE_URL}/customers/{customer_id}",
                        headers=hcp_headers(),
                        json={"email": email},
                        timeout=HCP_TIMEOUT,
                    ).raise_for_status()
                except Exception as e:
                    logger.warning(f"[create-appointment] email backfill failed: {e}")

            reuse_on_file = (use_address_on_file or not street) and existing["address_id"]
            if reuse_on_file:
                # Caller confirmed the address on file — book against it and
                # echo its real values back in the confirmation.
                address_id = existing["address_id"]
                street = existing["street"] or street
                city = existing["city"] or city
                state = existing["state"] or state
                zip_code = existing["zip"] or zip_code
            elif street:
                # Caller gave a new/corrected address — add it to THIS customer
                # (no duplicate customer), and book against it.
                addr_data = {
                    "street": street, "city": city, "state": state,
                    "zip": zip_code, "type": "service", "country": "US",
                }
                addr_resp = requests.post(
                    f"{HCP_BASE_URL}/customers/{customer_id}/addresses",
                    headers=hcp_headers(), json=addr_data, timeout=HCP_TIMEOUT,
                )
                addr_resp.raise_for_status()
                address_id = addr_resp.json().get("id", "")
            else:
                address_id = existing["address_id"]
        else:
            # New caller — create the customer + address.
            customer_data = {
                "first_name": first_name,
                "last_name": last_name,
                "notifications_enabled": True,
            }
            if phone:
                customer_data["mobile_number"] = phone
            if email:
                customer_data["email"] = email

            cust_resp = hcp_post("/customers", customer_data)
            customer_id = cust_resp.get("id", "")

            address_id = ""
            if street:
                addr_data = {
                    "street": street, "city": city, "state": state,
                    "zip": zip_code, "type": "service", "country": "US",
                }
                addr_resp = requests.post(
                    f"{HCP_BASE_URL}/customers/{customer_id}/addresses",
                    headers=hcp_headers(), json=addr_data, timeout=HCP_TIMEOUT,
                )
                addr_resp.raise_for_status()
                address_id = addr_resp.json().get("id", "")

    except requests.HTTPError as e:
        logger.error(f"[create-appointment] HCP customer/address creation failed: {e}")
        return jsonify({
            "result": json.dumps({
                "success": False,
                "system_error": True,
                "should_transfer": True,
                "message": "I'm having a system issue creating the appointment. Let me transfer you to our team to get this booked manually."
            })
        })

    if not customer_id or not address_id:
        return jsonify({
            "result": "I need the service address to complete the booking. Could you confirm the full address?"
        })

    # ── Create the Job ──
    try:
        # Convert local Orlando time to UTC for HCP
        local_start = datetime.strptime(f"{date}T{start_time}:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=LOCAL_TZ)
        local_end = datetime.strptime(f"{date}T{end_time}:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=LOCAL_TZ)
        utc_start = local_start.astimezone(timezone.utc)
        utc_end = local_end.astimezone(timezone.utc)

        scheduled_start = utc_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        scheduled_end = utc_end.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Build notes
        job_notes = "Booked via AI phone agent."
        if is_emergency:
            job_notes = (
                f"🚨 EMERGENCY — {EMERGENCY_FEE} emergency fee acknowledged by customer. "
                f"ON-CALL TECH: please call customer ASAP to confirm ETA. "
                f"Customer was told a tech would call within minutes. "
                f"Booked via AI phone agent."
            )
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

        # Assign to the available tech found during validation, or fall back to default
        if assigned_tech:
            job_data["assigned_employee_ids"] = [assigned_tech["id"]]
        elif DEFAULT_EMPLOYEE_ID:
            job_data["assigned_employee_ids"] = [DEFAULT_EMPLOYEE_ID]

        if is_emergency:
            job_data["tags"] = ["emergency", "ai-booked"]
        else:
            job_data["tags"] = ["ai-booked"]

        job_resp = hcp_post("/jobs", job_data)
        job_id = job_resp.get("id", "")
        # HCP customer_id is also useful for the dashboard link
        hcp_customer_id = customer_id

        # Format confirmation using local time
        start_dt = local_start
        end_dt = local_end

        tech_name = assigned_tech["name"] if assigned_tech else "a technician"

        # Store the booking on the active call so the dashboard can show a link
        if retell_call_id and retell_call_id in ACTIVE_CALLS:
            ACTIVE_CALLS[retell_call_id]["hcp_job_id"] = job_id
            ACTIVE_CALLS[retell_call_id]["hcp_customer_id"] = hcp_customer_id
            ACTIVE_CALLS[retell_call_id]["hcp_job_url"] = f"https://pro.housecallpro.com/app/jobs/{job_id}" if job_id else ""
            ACTIVE_CALLS[retell_call_id]["booking_summary"] = {
                "service_type": service_type,
                "date": start_dt.strftime("%A, %B %d"),
                "time_window": f"{start_dt.strftime('%-I:%M %p')} to {end_dt.strftime('%-I:%M %p')}",
                "tech": tech_name,
                "address": f"{street}, {city}, {state} {zip_code}",
                "customer_name": f"{first_name} {last_name}",
                "is_emergency": is_emergency,
            }
            broadcast_event("booking_created", ACTIVE_CALLS[retell_call_id])

        confirmation = {
            "success": True,
            "job_id": job_id,
            "date": start_dt.strftime("%A, %B %d"),
            "time_window": f"{start_dt.strftime('%-I:%M %p')} to {end_dt.strftime('%-I:%M %p')}",
            "service_type": service_type,
            "is_emergency": is_emergency,
            "assigned_to": tech_name,
            "message": f"Appointment confirmed for {start_dt.strftime('%A, %B %d')} "
                       f"between {start_dt.strftime('%-I:%M %p')} and {end_dt.strftime('%-I:%M %p')}. "
                       f"The customer will receive a confirmation text.",
        }

        # Remember the confirmation so a re-confirmation in the same call
        # replays it instead of double-booking (see idempotency guard above).
        if retell_call_id and retell_call_id in ACTIVE_CALLS:
            ACTIVE_CALLS[retell_call_id]["confirmation"] = confirmation

        return jsonify({"result": json.dumps(confirmation)})

    except requests.HTTPError as e:
        logger.error(f"[create-appointment] HCP job creation failed: {e}")
        return jsonify({
            "result": json.dumps({
                "success": False,
                "system_error": True,
                "should_transfer": True,
                "message": "I'm having a system issue booking the appointment. Let me transfer you to our team to get this booked manually."
            })
        })


# ============================================================
# TOOL 3: TRANSFER TO EMERGENCY TECH
# ============================================================

@app.route("/transfer-emergency", methods=["POST"])
@require_retell_signature
def transfer_emergency():
    """
    Captures customer info and returns the emergency tech's phone number
    for Retell to transfer the call.
    Used when caller has an emergency AND agrees to the $120 fee.
    """
    body = request.json or {}
    logger.info(f"[transfer-emergency] Received: {json.dumps(body)[:500]}")
    args = body.get("args", body)

    first_name = args.get("first_name", "")
    last_name = args.get("last_name", "")
    phone = args.get("phone", "")
    email = args.get("email", "")
    street = args.get("street", "")
    city = args.get("city", "")
    state = args.get("state", "")
    zip_code = args.get("zip_code", "")
    notes = args.get("notes", "")
    # Caller explicitly agreed to the $120 emergency fee — set by the agent ONLY
    # after a clear "yes." Gates the dispatch so we never bridge (and bill) an
    # emergency visit the customer didn't approve.
    fee_acknowledged = bool(args.get("fee_acknowledged", False))

    # ── HARD GATE: never dispatch the on-call tech without the $120 fee agreed.
    #    Mirrors the create_appointment profile gate — prompt instructions alone
    #    were skippable under pressure (a haggling caller). No transfer, no HCP
    #    record, no alert until fee_acknowledged is true.
    if not fee_acknowledged:
        return jsonify({"result": json.dumps({
            "needs_fee_acknowledgment": True,
            "say_to_caller": "Before I connect you — there's a $120 emergency service fee for the after-hours visit. Is that okay to go ahead with?",
            "message": "Do NOT transfer yet. State the $120 fee and get an explicit yes, then call transfer_emergency again with fee_acknowledged: true. (Human/non-emergency transfers use transfer_to_human instead — no fee.)",
        })})

    # Resolve the emergency transfer destination — dashboard-managed (the
    # 'emergency' contact), falling back to the hardcoded on-call tech. The SAME
    # name/number is used for the actual transfer AND the Telegram alert, so they
    # can never drift when the destination is switched in the dashboard.
    ec = transfer_contact_for("emergency")
    dest_name = (ec.get("name") if ec else "") or EMERGENCY_TECH_NAME
    dest_phone = (ec.get("phone") if ec else "") or EMERGENCY_TECH_PHONE

    # Add the contact to HCP so the tech has a record. Dedupe by phone (reuse an
    # existing customer rather than spawning a duplicate). Best-effort only — a
    # caller who DECLINES to give info (phone-only) must still transfer, so we
    # never block the transfer on HCP.
    customer_id = ""
    try:
        existing = hcp_find_customer_by_phone(phone) if phone else None
        if existing:
            customer_id = existing["customer_id"]
            if email and not existing["has_email"]:
                try:
                    requests.patch(f"{HCP_BASE_URL}/customers/{customer_id}",
                                   headers=hcp_headers(), json={"email": email}, timeout=HCP_TIMEOUT).raise_for_status()
                except Exception:
                    pass
            if street and not existing["address_id"]:
                requests.post(f"{HCP_BASE_URL}/customers/{customer_id}/addresses",
                              headers=hcp_headers(),
                              json={"street": street, "city": city, "state": state, "zip": zip_code, "type": "service", "country": "US"},
                              timeout=HCP_TIMEOUT)
        elif first_name or last_name or phone:
            customer_data = {"first_name": first_name, "last_name": last_name, "notifications_enabled": True}
            if phone:
                customer_data["mobile_number"] = phone
            if email:
                customer_data["email"] = email
            cust_resp = hcp_post("/customers", customer_data)
            customer_id = cust_resp.get("id", "")
            if street:
                requests.post(f"{HCP_BASE_URL}/customers/{customer_id}/addresses",
                              headers=hcp_headers(),
                              json={"street": street, "city": city, "state": state, "zip": zip_code, "type": "service", "country": "US"},
                              timeout=HCP_TIMEOUT)

        if customer_id:
            lead_data = {
                "customer_id": customer_id,
                "notes": f"EMERGENCY CALL — {EMERGENCY_FEE} fee acknowledged. "
                         f"Transferred to {dest_name} at {dest_phone}. "
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

    # Telegram alert — give the on-call tech context before the call lands. Shows
    # whatever was actually collected (blanks if the caller declined) and the
    # real number we're dialing.
    cust_name = f"{first_name} {last_name}".strip() or "(not provided)"
    address_line = ", ".join(p for p in [street, city, state, zip_code] if p) or "(not provided)"
    tg_msg = (
        f"🚨 *Emergency transfer*\n"
        f"Customer: *{cust_name}*\n"
        f"Phone: `{phone or 'unknown'}`\n"
        f"Email: {email or '(not provided)'}\n"
        f"Address: {address_line}\n"
        f"Problem: {notes or '(no notes captured)'}\n"
        f"Fee acknowledged: {EMERGENCY_FEE}\n"
        f"Transferring to: {dest_name} ({dest_phone})"
    )
    notify_event("🚨", "Emergency transfer",
                 f"{cust_name} · {phone or 'unknown'} → {dest_name}"
                 + (f" · {notes}" if notes else ""),
                 tg_msg, "Markdown", "", "emergency", peer=phone,
                 meta={"kind": "emergency", "name": cust_name, "phone": phone,
                       "address": address_line, "problem": notes, "fee": EMERGENCY_FEE,
                       "dest_name": dest_name, "dest_phone": dest_phone})

    return jsonify({
        "result": json.dumps({
            "success": True,
            "transfer_to": dest_phone,
            "tech_name": dest_name,
            "message": f"Transferring to {dest_name} now. "
                       f"Customer {cust_name} has an emergency and agreed to the {EMERGENCY_FEE} fee.",
        })
    })


# ============================================================
# LIVE CALL MONITORING DASHBOARD
# ============================================================

# In-memory store of active and recent calls
ACTIVE_CALLS = {}  # call_id -> { state, transcript, customer_phone, started_at }
SUBSCRIBERS = []   # list of queues for SSE clients
POLL_GREENLETS = {}  # call_id -> gevent greenlet

# Hydrate from SQLite so the dashboard isn't empty after a restart, then start the background loops.
hydrate_active_calls()
gevent.spawn(reviewer_loop)
gevent.spawn(synthesis_loop)
gevent.spawn(_refresh_avail_cache)   # pre-warm availability cache at startup
gevent.spawn(_avail_cache_loop)      # keep it fresh every 4 min

def broadcast_event(event_type, data):
    """Push an event to all connected dashboard clients."""
    payload = json.dumps({"type": event_type, "data": data})
    msg = f"data: {payload}\n\n"
    for q in list(SUBSCRIBERS):
        try:
            q.put_nowait(msg)
        except Exception:
            pass


def poll_call_transcript(call_id, max_polls=400):
    """
    Poll Retell get-call endpoint every 1.5s during an active call.
    Broadcasts transcript updates to dashboard whenever it changes.
    """
    last_len = 0
    polls = 0
    while polls < max_polls:
        polls += 1
        try:
            r = requests.get(
                f"https://api.retellai.com/v2/get-call/{call_id}",
                headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
                timeout=5,
            )
            if r.status_code == 200:
                full_call = r.json()
                transcript = full_call.get("transcript_object") or []
                status = full_call.get("call_status", "")

                if call_id in ACTIVE_CALLS:
                    ACTIVE_CALLS[call_id]["transcript"] = transcript
                    if not ACTIVE_CALLS[call_id].get("from_number"):
                        ACTIVE_CALLS[call_id]["from_number"] = full_call.get("from_number", "")

                # Broadcast if transcript grew
                if len(transcript) != last_len:
                    last_len = len(transcript)
                    logger.info(f"[poll] {call_id[:20]} turns={len(transcript)} status={status}")
                    broadcast_event("transcript_updated", {
                        "call_id": call_id,
                        "transcript": transcript,
                    })

                # Stop polling once the call is ended
                if status in ("ended", "error"):
                    logger.info(f"[poll] {call_id[:20]} stopped — status={status}")
                    break
        except Exception as e:
            logger.error(f"[poll] {call_id[:20]} error: {e}")

        gevent.sleep(1.5)

    POLL_GREENLETS.pop(call_id, None)


def _clean_summary(text):
    """Turn a raw GPT call summary into one short, name-free clause that reads
    naturally after the greeting template 'Last time we spoke, ...'.
    Returns "" for non-substantive calls so they fall back to a standard greeting."""
    if not text:
        return ""
    import re
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    low = first.lower()
    if any(j in low for j in ("hung up", "brief call", "no information",
                              "did not provide", "immediately after", "no meaningful")):
        return ""
    # Strip stale agent names and third-person lead-ins.
    first = re.sub(r"\b(Anna|Sarah|the agent|the (?:AI )?assistant)\b", "", first, flags=re.I)
    first = re.sub(r"^\W*(the\s+)?(caller|customer|client)\s+", "", first, flags=re.I).strip().rstrip(".")
    if first:
        first = first[0].lower() + first[1:]
    return first[:160]


def _inbound_base_vars(from_number=""):
    """Variables every inbound call needs regardless of caller history:
    the caller's own number (to confirm as the contact number) and the
    transfer destinations (so the transfer tools resolve)."""
    return {
        "caller_phone": from_number or "",
        # Dashboard-assigned contact wins; env var is the fallback.
        "alfredo_transfer_number": transfer_number_for("alfredo") or ALFREDO_TRANSFER_PHONE,
        "human_transfer_number": transfer_number_for("human") or HUMAN_TRANSFER_PHONE,
    }


def _customer_dynamic_vars(cust):
    """Dynamic vars describing the HCP profile on file (all-empty when none)."""
    if not cust:
        return {
            "customer_found": "false",
            "customer_first_name": "",
            "customer_last_name": "",
            "customer_street_number": "",
            "customer_city": "",
            "customer_has_email": "false",
        }
    return {
        "customer_found": "true",
        "customer_first_name": cust["first_name"],
        "customer_last_name": cust["last_name"],
        "customer_street_number": cust["street_number"],
        "customer_city": cust["city"],
        "customer_has_email": "true" if cust["has_email"] else "false",
    }


def _lookup_last_retell_call(from_number):
    """Most recent finished Retell call from this number, or None."""
    try:
        r = requests.post(
            "https://api.retellai.com/v2/list-calls",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}", "Content-Type": "application/json"},
            json={
                "filter_criteria": {"from_number": [from_number]},
                "sort_order": "descending",
                "limit": 5,
            },
            timeout=2.0,
        )
        r.raise_for_status()
        calls = r.json() or []
    except Exception as e:
        logger.error(f"[inbound] list-calls failed: {e}")
        return None
    for c in calls:
        if c.get("call_status") == "ongoing":
            continue
        return c
    return None


def _inbound_empty_response(from_number=""):
    v = _inbound_base_vars(from_number)
    v.update({
        "returning_caller": "false",
        "caller_first_name": "",
        "last_call_summary": "",
        "last_call_outcome": "",
    })
    v.update(_customer_dynamic_vars(None))
    return jsonify({"call_inbound": {"dynamic_variables": v}})


@app.route("/retell/inbound", methods=["POST"])
@require_retell_signature
def retell_inbound():
    """
    Called by Retell BEFORE the call connects.
    Looks up the most recent past call from this phone number and injects
    a short summary so Sarah can greet the caller with context.

    Honors two env-var safety knobs:
      INBOUND_CONTEXT_ENABLED          = "false" disables lookup entirely.
      INBOUND_CONTEXT_SKIP_NUMBERS     = comma-separated E.164 numbers to skip.

    Must respond fast — Retell gives up after ~3 seconds.
    """
    body = request.json or {}
    inbound = body.get("call_inbound", {}) or {}
    from_number = (inbound.get("from_number") or "").strip()
    logger.info(f"[inbound] from={from_number}")

    if os.environ.get("INBOUND_CONTEXT_ENABLED", "true").lower() != "true":
        return _inbound_empty_response(from_number)

    skip = {n.strip() for n in os.environ.get("INBOUND_CONTEXT_SKIP_NUMBERS", "").split(",") if n.strip()}
    # Skip-listed numbers suppress only the "welcome back" call-history recap
    # (handy for repeat test calls) — the HCP profile lookup still runs so the
    # address-confirm flow remains testable.
    skip_history = from_number in skip
    if skip_history:
        logger.info(f"[inbound] skip call-history greeting for {from_number}")

    if not from_number:
        return _inbound_empty_response(from_number)

    # Run the two slow lookups concurrently to stay under Retell's ~3s budget:
    #   - past Retell calls (for the greeting recap)
    #   - the existing HCP customer profile (for the address-confirm flow)
    # ThreadPoolExecutor works both under the gunicorn gevent worker (threads
    # are monkey-patched to greenlets) and the plain dev server.
    import time
    from concurrent.futures import ThreadPoolExecutor
    deadline = time.monotonic() + 2.5
    ex = ThreadPoolExecutor(max_workers=2)
    f_call = ex.submit(_lookup_last_retell_call, from_number) if (RETELL_API_KEY and not skip_history) else None
    f_cust = ex.submit(hcp_find_customer_by_phone, from_number, 2.0)

    def _result_or_none(fut):
        if not fut:
            return None
        try:
            return fut.result(timeout=max(0.05, deadline - time.monotonic()))
        except Exception as e:
            logger.warning(f"[inbound] lookup timed out/failed: {e}")
            return None

    last = _result_or_none(f_call)
    cust = _result_or_none(f_cust)
    ex.shutdown(wait=False)

    summary = ""
    outcome = ""
    if last:
        analysis = last.get("call_analysis") or {}
        summary = _clean_summary((analysis.get("call_summary") or "").strip())
        custom = analysis.get("custom_analysis_data") or {}
        outcome = (custom.get("outcome") or "").strip()

    v = _inbound_base_vars(from_number)
    v.update({
        "returning_caller": "true" if summary else "false",
        "caller_first_name": "",
        "last_call_summary": summary,
        "last_call_outcome": outcome,
    })
    v.update(_customer_dynamic_vars(cust))
    return jsonify({"call_inbound": {"dynamic_variables": v}})


@app.route("/webhook/retell", methods=["POST"])
@require_retell_signature
def retell_webhook():
    """Receive Retell call lifecycle webhooks."""
    body = request.json or {}
    event = body.get("event", "")
    call = body.get("call", {})
    call_id = call.get("call_id", "")

    logger.info(f"[webhook] event={event} call_id={call_id}")

    if not call_id:
        return jsonify({"ok": True})

    if event == "call_started":
        ACTIVE_CALLS[call_id] = {
            "call_id": call_id,
            "state": "active",
            "started_at": datetime.now(LOCAL_TZ).isoformat(),
            "from_number": call.get("from_number", ""),
            "to_number": call.get("to_number", ""),
            "transcript": [],
        }
        db_upsert_call(ACTIVE_CALLS[call_id])
        broadcast_event("call_started", ACTIVE_CALLS[call_id])

        # Telegram alert (fire-and-forget greenlet so the webhook stays fast)
        caller = call.get("from_number", "unknown")
        dash_url = f"{DASHBOARD_PUBLIC_URL}/dashboard?key={DASHBOARD_PASSWORD}"
        started_local = datetime.now(LOCAL_TZ).strftime("%-I:%M %p %Z")
        tg_msg = (
            f"📞 *Incoming call*\n"
            f"From: `{caller}`\n"
            f"Time: {started_local}\n"
            f"[Listen live]({dash_url})"
        )
        # Telegram + message center + iPhone push, one call, same content
        body = (f"From {caller}" if caller and caller != "unknown"
                else "A customer is calling now")
        notify_event("📞", "Incoming call", f"{body} · {started_local}",
                     tg_msg, "Markdown", call_id, "call-" + call_id, peer=caller,
                     meta={"kind": "incoming", "phone": caller, "time": started_local,
                           "call_id": call_id})

        # Start polling for live transcript
        if call_id not in POLL_GREENLETS:
            g = gevent.spawn(poll_call_transcript, call_id)
            POLL_GREENLETS[call_id] = g
            logger.info(f"[poll] started for {call_id[:20]}")

    elif event == "call_ended":
        if call_id in ACTIVE_CALLS:
            ACTIVE_CALLS[call_id]["state"] = "ended"
            ACTIVE_CALLS[call_id]["ended_at"] = datetime.now(LOCAL_TZ).isoformat()
            ACTIVE_CALLS[call_id]["recording_url"] = call.get("recording_url", "")
            ACTIVE_CALLS[call_id]["duration_ms"] = call.get("duration_ms", 0)
            # Try to fetch the final transcript
            try:
                r = requests.get(
                    f"https://api.retellai.com/v2/get-call/{call_id}",
                    headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
                    timeout=5,
                )
                if r.status_code == 200:
                    full = r.json()
                    ACTIVE_CALLS[call_id]["transcript"] = full.get("transcript_object") or []
            except Exception:
                pass
            db_upsert_call(ACTIVE_CALLS[call_id])
            broadcast_event("call_ended", ACTIVE_CALLS[call_id])

    elif event == "call_analyzed":
        # Fetch the analyzed call to get AI summary + custom analysis fields
        if call_id in ACTIVE_CALLS:
            try:
                r = requests.get(
                    f"https://api.retellai.com/v2/get-call/{call_id}",
                    headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
                    timeout=5,
                )
                if r.status_code == 200:
                    full = r.json()
                    analysis = full.get("call_analysis") or {}
                    ACTIVE_CALLS[call_id]["analysis"] = analysis
                    ACTIVE_CALLS[call_id]["state"] = "analyzed"
                    ACTIVE_CALLS[call_id]["recording_url"] = full.get("recording_url", "")
                    if not ACTIVE_CALLS[call_id].get("transcript"):
                        ACTIVE_CALLS[call_id]["transcript"] = full.get("transcript_object") or []
                    logger.info(f"[analysis] {call_id[:20]} outcome={analysis.get('custom_analysis_data',{}).get('outcome')}")
                    db_upsert_call(ACTIVE_CALLS[call_id])
                    broadcast_event("call_analyzed", ACTIVE_CALLS[call_id])

                    # Wrap-up to all three channels: who called, what happened,
                    # status, follow-up. Telegram gets the rich version; the
                    # message center + iPhone push get the plain mirror.
                    ico, title, body = _format_call_ended_plain(ACTIVE_CALLS[call_id])
                    notify_event(ico, title, body,
                                 _format_call_ended_alert(ACTIVE_CALLS[call_id]), "HTML",
                                 call_id, "ended-" + call_id,
                                 peer=ACTIVE_CALLS[call_id].get("from_number", ""),
                                 meta=_call_meta(ACTIVE_CALLS[call_id]))
            except Exception as e:
                logger.error(f"[analysis] fetch failed: {e}")

    elif event == "transcript_updated":
        # The webhook payload doesn't include the transcript — fetch it from Retell API
        transcript = []
        try:
            r = requests.get(
                f"https://api.retellai.com/v2/get-call/{call_id}",
                headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
                timeout=5,
            )
            if r.status_code == 200:
                full_call = r.json()
                transcript = full_call.get("transcript_object") or []
                logger.info(f"[transcript] fetched {len(transcript)} turns from API")
        except Exception as e:
            logger.error(f"[transcript] fetch failed: {e}")

        if call_id not in ACTIVE_CALLS:
            ACTIVE_CALLS[call_id] = {
                "call_id": call_id,
                "state": "active",
                "started_at": datetime.now(LOCAL_TZ).isoformat(),
                "from_number": call.get("from_number", ""),
                "to_number": call.get("to_number", ""),
                "transcript": [],
            }

        ACTIVE_CALLS[call_id]["transcript"] = transcript
        logger.info(f"[transcript] turns={len(transcript)} subscribers={len(SUBSCRIBERS)}")
        db_upsert_call(ACTIVE_CALLS[call_id])
        broadcast_event("transcript_updated", {
            "call_id": call_id,
            "transcript": transcript,
        })

    return jsonify({"ok": True})


@app.route("/api/active-calls", methods=["GET"])
def list_active_calls():
    """Return all known calls (active + recent). Key-gated — exposes customer PII."""
    if not _require_key():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(list(ACTIVE_CALLS.values()))


# ============================================================
# ON-CALL DASHBOARD API
# ============================================================

@app.route("/api/techs", methods=["GET"])
def list_techs():
    """Return all field techs from FIELD_TECHS config."""
    if not _require_key():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(FIELD_TECHS)


@app.route("/api/oncall", methods=["GET"])
def get_oncall():
    """Get the full per-date on-call schedule + helpers for the dashboard."""
    if not _require_key():
        return jsonify({"error": "unauthorized"}), 401
    schedule = load_oncall()
    today = datetime.now(LOCAL_TZ)
    return jsonify({
        "dates": schedule.get("dates", {}),
        "today": today.strftime("%Y-%m-%d"),
        "techs": FIELD_TECHS,
    })


@app.route("/api/oncall", methods=["POST"])
def set_oncall():
    """
    Set on-call assignments for one or more dates.
    Body: {
      "key": "<password>",
      "assignments": { "2026-05-04": ["pro_id1"], "2026-05-05": ["pro_id1","pro_id2"] }
    }
    Empty list for a date = remove the override (default behavior).
    """
    body = request.json or {}
    key = body.get("key", "") or request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    assignments = body.get("assignments") or {}
    if not isinstance(assignments, dict):
        return jsonify({"ok": False, "error": "assignments must be an object"}), 400

    schedule = load_oncall()
    if "dates" not in schedule:
        schedule["dates"] = {}
    for date_key, tech_ids in assignments.items():
        if not tech_ids:
            schedule["dates"].pop(date_key, None)
        else:
            schedule["dates"][date_key] = list(tech_ids)
    saved = save_oncall(schedule)
    if saved:
        broadcast_event("oncall_updated", {"assignments": assignments})
    return jsonify({"ok": saved, "schedule": schedule})


@app.route("/api/oncall/<date_key>", methods=["DELETE"])
def delete_oncall(date_key):
    """Remove the on-call override for a specific date."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    schedule = load_oncall()
    schedule.get("dates", {}).pop(date_key, None)
    save_oncall(schedule)
    broadcast_event("oncall_updated", {"date": date_key, "removed": True})
    return jsonify({"ok": True})


# ---- Transfer contacts (dashboard-managed transfer numbers) ----
def _require_key():
    key = (request.json or {}).get("key", "") if request.is_json else ""
    key = key or request.args.get("key", "")
    return key == DASHBOARD_PASSWORD


@app.route("/api/transfer-contacts", methods=["GET"])
def get_transfer_contacts():
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    d = load_transfer()
    return jsonify({
        "contacts": d.get("contacts", []),
        "alfredo_id": d.get("alfredo_id"),
        "human_id": d.get("human_id"),
        "emergency_id": d.get("emergency_id"),
        "env_fallback": {"alfredo": ALFREDO_TRANSFER_PHONE, "human": HUMAN_TRANSFER_PHONE, "emergency": EMERGENCY_TECH_PHONE},
    })


@app.route("/api/transfer-contacts", methods=["POST"])
def add_transfer_contact():
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    body = request.json or {}
    name = (body.get("name") or "").strip()
    phone = (body.get("phone") or "").strip()
    if not name or not phone:
        return jsonify({"ok": False, "error": "name and phone required"}), 400
    d = load_transfer()
    cid = uuid.uuid4().hex[:8]
    d["contacts"].append({"id": cid, "name": name, "phone": phone})
    ok = save_transfer(d)
    broadcast_event("transfer_updated", {"contacts": d["contacts"]})
    return jsonify({"ok": ok, "id": cid, "contacts": d["contacts"]})


@app.route("/api/transfer-contacts/<cid>", methods=["DELETE"])
def delete_transfer_contact(cid):
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    d = load_transfer()
    d["contacts"] = [c for c in d.get("contacts", []) if c.get("id") != cid]
    if d.get("alfredo_id") == cid:
        d["alfredo_id"] = None
    if d.get("human_id") == cid:
        d["human_id"] = None
    if d.get("emergency_id") == cid:
        d["emergency_id"] = None
    ok = save_transfer(d)
    broadcast_event("transfer_updated", {"contacts": d["contacts"]})
    return jsonify({"ok": ok, "alfredo_id": d["alfredo_id"], "human_id": d["human_id"], "emergency_id": d["emergency_id"]})


@app.route("/api/transfer-contacts/assign", methods=["POST"])
def assign_transfer_contact():
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    body = request.json or {}
    role = body.get("role")
    cid = body.get("id")  # may be null to clear the role
    if role not in ("alfredo", "human", "emergency"):
        return jsonify({"ok": False, "error": "role must be alfredo, human, or emergency"}), 400
    d = load_transfer()
    if cid is not None and not any(c.get("id") == cid for c in d.get("contacts", [])):
        return jsonify({"ok": False, "error": "unknown contact"}), 400
    d[f"{role}_id"] = cid
    ok = save_transfer(d)
    broadcast_event("transfer_updated", {"alfredo_id": d["alfredo_id"], "human_id": d["human_id"], "emergency_id": d["emergency_id"]})
    return jsonify({"ok": ok, "alfredo_id": d["alfredo_id"], "human_id": d["human_id"], "emergency_id": d["emergency_id"]})


@app.route("/api/how-found-stats", methods=["GET"])
def how_found_stats():
    """Aggregate 'how_found' answers across all calls for the dashboard chart."""
    if not _require_key():
        return jsonify({"error": "unauthorized"}), 401
    counts = {}
    total = 0
    for c in ACTIVE_CALLS.values():
        analysis = c.get("analysis") or {}
        cad = analysis.get("custom_analysis_data") or {}
        src = (cad.get("how_found") or "").upper().strip()
        if not src or src == "NOT_ASKED":
            continue
        counts[src] = counts.get(src, 0) + 1
        total += 1
    items = sorted(counts.items(), key=lambda x: -x[1])
    return jsonify({"total": total, "items": [{"source": s, "count": n} for s, n in items]})


@app.route("/api/reset", methods=["POST"])
def reset_dashboard():
    """Clear all stored calls and analytics. Password-protected."""
    key = request.args.get("key", "") or (request.json or {}).get("key", "")
    if key != DASHBOARD_PASSWORD:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    cleared = len(ACTIVE_CALLS)
    ACTIVE_CALLS.clear()
    # Stop any active polling greenlets
    for cid, g in list(POLL_GREENLETS.items()):
        try:
            g.kill(block=False)
        except Exception:
            pass
    POLL_GREENLETS.clear()
    broadcast_event("reset", {"cleared": cleared})
    return jsonify({"ok": True, "cleared": cleared})


@app.route("/api/end-call/<call_id>", methods=["POST"])
def force_end_call(call_id):
    """End an active Retell call via the Retell API. Key-gated."""
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        # Retell uses POST /v2/stop-call/{call_id}
        resp = requests.post(
            f"https://api.retellai.com/v2/stop-call/{call_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            timeout=8,
        )
        ok = resp.status_code in (200, 204)
        return jsonify({
            "ok": ok,
            "status_code": resp.status_code,
            "body": resp.text[:200] if not ok else "",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/stream", methods=["GET"])
def stream():
    """Server-Sent Events stream for the dashboard. Key-gated via ?key= (EventSource can't send headers)."""
    if request.args.get("key", "") != DASHBOARD_PASSWORD:
        return Response("unauthorized", status=401)
    def event_stream():
        q = queue.Queue(maxsize=200)
        SUBSCRIBERS.append(q)
        try:
            # Send initial snapshot
            snapshot = json.dumps({"type": "snapshot", "data": list(ACTIVE_CALLS.values())})
            yield f"data: {snapshot}\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            try:
                SUBSCRIBERS.remove(q)
            except ValueError:
                pass

    return Response(event_stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>High Tech Air Conditioning — Call Intelligence</title>
<link rel="icon" href="{{ logo_data_uri }}">
<!-- PWA / Add to Home Screen -->
<meta name="theme-color" content="#05070B">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="High Tech AC">
<link rel="apple-touch-icon" href="/app-icon-192.png">
<link rel="manifest" href="/manifest.webmanifest?key={{ dashboard_key }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root {
    /* === Futuristic dark theme — near-black with cyan accents === */
    /* Cyan accent system (primary) */
    --cyan: #22D3EE;
    --cyan-bright: #67E8F9;
    --cyan-dim: #0E7490;
    --cyan-soft: rgba(34, 211, 238, 0.12);
    --cyan-glow: rgba(34, 211, 238, 0.55);

    /* The old theme used --brand-red as its PRIMARY accent everywhere, so we point
       it at cyan to re-skin the whole UI. True alerts use --danger (a real red) below. */
    --brand-red: var(--cyan);
    --brand-red-warm: var(--cyan-bright);
    --brand-red-soft: var(--cyan-soft);
    --brand-blue: var(--cyan);
    --brand-blue-light: var(--cyan-bright);
    --brand-blue-soft: var(--cyan-soft);
    --brand-cream: #0E1620;

    /* Surfaces (deep space black, layered) */
    --bg: #05070B;
    --surface: #0C121B;
    --surface-soft: #121C28;
    --hairline: rgba(34, 211, 238, 0.12);
    --hairline-strong: rgba(34, 211, 238, 0.26);

    /* Ink (cool near-white → muted cyan-gray) */
    --ink: #E8F4F8;
    --ink-soft: #B6C8D2;
    --ink-muted: #7C93A0;
    --ink-dim: #51697A;

    /* Functional states — luminous on black */
    --warning: #FBBF24;
    --warning-soft: rgba(251, 191, 36, 0.14);
    --success: #34F5C5;
    --success-soft: rgba(52, 245, 197, 0.13);
    --danger: #FF5063;
    --danger-soft: rgba(255, 80, 99, 0.15);
    --info: var(--cyan);
    --info-soft: var(--cyan-soft);

    /* Elevation — depth + cyan glow instead of soft drop shadows */
    --shadow-card: 0 1px 0 rgba(255,255,255,0.03) inset, 0 20px 44px -28px rgba(0,0,0,0.9);
    --shadow-card-hover: 0 0 0 1px var(--hairline-strong), 0 24px 60px -26px rgba(34,211,238,0.22);
    --shadow-inset-top: inset 0 1px 0 rgba(255, 255, 255, 0.05);

    /* Motion */
    --ease: cubic-bezier(0.16, 1, 0.3, 1);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  html { overflow-x: hidden; }
  body {
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    background-image:
      radial-gradient(900px 520px at 8% -10%, rgba(34, 211, 238, 0.10), transparent 60%),
      radial-gradient(1000px 640px at 108% 4%, rgba(34, 211, 238, 0.06), transparent 55%),
      linear-gradient(rgba(34,211,238,0.022) 1px, transparent 1px),
      linear-gradient(90deg, rgba(34,211,238,0.022) 1px, transparent 1px);
    background-size: auto, auto, 44px 44px, 44px 44px;
    background-attachment: fixed;
    color: var(--ink);
    font-size: 14px;
    line-height: 1.55;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }
  /* ---- Futuristic animated backdrop (GPU-cheap: blurred drifting aurora + slow scan sweep) ---- */
  body::before {
    content: ''; position: fixed; inset: -25%; z-index: -2; pointer-events: none;
    background:
      radial-gradient(38% 38% at 18% 28%, rgba(34,211,238,0.13), transparent 70%),
      radial-gradient(32% 32% at 82% 18%, rgba(34,211,238,0.10), transparent 70%),
      radial-gradient(44% 44% at 62% 88%, rgba(96,131,255,0.09), transparent 70%),
      radial-gradient(30% 30% at 40% 65%, rgba(34,211,238,0.07), transparent 70%);
    filter: blur(46px) saturate(1.1);
    animation: auroraDrift 26s ease-in-out infinite alternate;
    will-change: transform;
  }
  body::after {
    content: ''; position: fixed; left: 0; right: 0; top: 0; height: 42vh; z-index: -1; pointer-events: none;
    background: linear-gradient(180deg, rgba(34,211,238,0.06), transparent);
    animation: scanSweep 9s linear infinite;
    will-change: transform, opacity;
  }
  @keyframes auroraDrift {
    0%   { transform: translate3d(0,0,0) scale(1); }
    50%  { transform: translate3d(3%,-2%,0) scale(1.08); }
    100% { transform: translate3d(-2%,3%,0) scale(1.05); }
  }
  @keyframes scanSweep {
    0%   { transform: translateY(-42vh); opacity: 0; }
    12%  { opacity: 0.5; }
    50%  { opacity: 0.18; }
    100% { transform: translateY(142vh); opacity: 0; }
  }
  @media (prefers-reduced-motion: reduce) {
    body::before, body::after { animation: none; }
  }
  ::selection { background: var(--cyan-soft); color: var(--cyan-bright); }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(34,211,238,0.22); border-radius: 6px; border: 2px solid transparent; background-clip: content-box; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(34,211,238,0.4); background-clip: content-box; }

  /* Inline icon helper */
  .icon { width: 16px; height: 16px; flex-shrink: 0; stroke-width: 1.6; }
  .icon-sm { width: 14px; height: 14px; flex-shrink: 0; }
  .icon-xs { width: 12px; height: 12px; flex-shrink: 0; }
  .icon-lg { width: 20px; height: 20px; flex-shrink: 0; }
  /* Defensive: any unsized inline SVG falls back to icon size, never to default 300x150 */
  svg:not([class*="icon"]):not([width]) { width: 16px; height: 16px; flex-shrink: 0; }

  /* HEADER */
  header {
    background: linear-gradient(180deg, rgba(12,18,27,0.92), rgba(8,12,18,0.72));
    backdrop-filter: blur(16px) saturate(1.2);
    -webkit-backdrop-filter: blur(16px) saturate(1.2);
    border-bottom: 1px solid var(--hairline);
    box-shadow: 0 1px 0 rgba(34,211,238,0.10), 0 16px 40px -28px rgba(0,0,0,0.9);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 20;
  }
  .brand { display: flex; align-items: center; gap: 16px; }
  .brand-mark {
    height: 44px; width: auto; display: block;
    filter: drop-shadow(0 2px 10px rgba(34, 211, 238, 0.30));
    transition: transform 0.4s var(--ease);
  }
  .brand:hover .brand-mark { transform: translateY(-1px) rotate(-0.5deg); }
  .brand-divider {
    width: 1px; height: 32px; background: var(--hairline-strong);
  }
  .brand-text h1 {
    font-size: 14px; font-weight: 600; letter-spacing: -0.01em; color: var(--ink);
    line-height: 1.2;
  }
  .brand-text .subtitle {
    font-size: 11.5px; color: var(--ink-muted); margin-top: 3px;
    font-weight: 500; letter-spacing: 0.005em;
  }
  .brand-text .subtitle b { color: var(--brand-red); font-weight: 600; }
  .brand-link {
    color: var(--brand-red); font-weight: 600;
    text-decoration: none;
    transition: opacity 0.18s var(--ease), text-decoration-color 0.18s var(--ease);
  }
  .brand-link:hover { text-decoration: underline; opacity: 0.85; }
  .header-right { display: flex; align-items: center; gap: 12px; }
  .clock-pill {
    display: none; align-items: center; gap: 7px;
    padding: 7px 13px; border-radius: 100px;
    background: var(--surface); border: 1px solid var(--hairline);
    font-size: 12px; font-weight: 500; color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
  }
  @media (min-width: 720px) { .clock-pill { display: inline-flex; } }
  .clock-pill svg { color: var(--ink-dim); }
  .status-pill {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 7px 14px; border-radius: 100px;
    background: var(--surface); border: 1px solid var(--hairline);
    font-size: 12px; font-weight: 500; color: var(--ink-soft);
    box-shadow: var(--shadow-inset-top);
  }
  .status-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--success);
    box-shadow: 0 0 0 4px var(--success-soft);
    transition: all 0.3s var(--ease);
  }
  .status-dot.disconnected {
    background: var(--brand-red);
    box-shadow: 0 0 0 4px var(--brand-red-soft);
    animation: livePulse 1.4s ease-in-out infinite;
  }

  /* PAGE WRAP */
  .page {
    max-width: 1480px; margin: 0 auto; padding: 24px 32px 0;
  }

  /* STATS — asymmetric Bento 2.0 */
  .stats {
    display: grid;
    grid-template-columns: 1.4fr 1fr 1fr 1fr;
    gap: 14px;
    margin-bottom: 22px;
  }
  .stat {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: 22px;
    padding: 18px 22px 20px;
    display: flex; flex-direction: column; gap: 10px;
    transition: transform 0.4s var(--ease), box-shadow 0.4s var(--ease), border-color 0.3s var(--ease);
    position: relative;
    overflow: hidden;
    box-shadow: var(--shadow-card);
    opacity: 0; transform: translateY(8px);
    animation: fadeUp 0.55s var(--ease) forwards;
    animation-delay: calc(var(--idx, 0) * 70ms);
  }
  .stat:hover { transform: translateY(-2px); box-shadow: var(--shadow-card-hover); }
  .stat::before {
    content: ''; position: absolute; left: 18px; right: 18px; top: 0;
    height: 2px; border-radius: 0 0 6px 6px;
    background: var(--accent-bar, var(--brand-blue));
    opacity: 0.85;
  }
  .stat-label {
    font-size: 11px; color: var(--ink-muted); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    display: inline-flex; align-items: center; gap: 8px;
  }
  .stat-label svg { color: var(--ink-dim); }
  .stat-row { display: flex; align-items: baseline; gap: 12px; }
  .stat-value {
    font-family: 'Geist Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 36px; font-weight: 600;
    letter-spacing: -0.025em; color: var(--ink);
    line-height: 1;
  }
  .stat-value.accent { color: var(--brand-red); --accent-bar: var(--brand-red); }
  .stat-value.warning { color: var(--warning); --accent-bar: var(--warning); }
  .stat-value.success { color: var(--success); --accent-bar: var(--success); }
  .stat-trail { font-size: 12px; color: var(--ink-muted); font-weight: 500; }
  .stat:nth-child(1) { --idx: 0; --accent-bar: var(--brand-red); }
  .stat:nth-child(2) { --idx: 1; --accent-bar: var(--brand-blue); }
  .stat:nth-child(3) { --idx: 2; --accent-bar: var(--warning); }
  .stat:nth-child(4) { --idx: 3; --accent-bar: var(--success); }

  /* MAIN — workspace shell */
  .container {
    display: grid;
    grid-template-columns: 380px 1fr;
    gap: 14px;
    height: calc(100vh - 220px);
    min-height: 560px;
    padding-bottom: 24px;
  }

  .panel {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: 24px;
    box-shadow: var(--shadow-card);
    display: flex; flex-direction: column;
    overflow: hidden;
  }

  /* CALLS LIST */
  .calls-panel { }
  .panel-header {
    padding: 18px 22px;
    border-bottom: 1px solid var(--hairline);
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px;
  }
  .panel-title {
    font-size: 13px; font-weight: 600; color: var(--ink);
    letter-spacing: -0.005em;
    display: inline-flex; align-items: center; gap: 8px;
  }
  .panel-title svg { color: var(--brand-red); }
  .panel-count {
    background: var(--surface-soft); color: var(--ink-soft);
    padding: 3px 10px; border-radius: 100px; font-size: 11px; font-weight: 600;
    font-variant-numeric: tabular-nums;
    border: 1px solid var(--hairline);
  }
  .panel-search {
    padding: 12px 16px;
    border-bottom: 1px solid var(--hairline);
    background: var(--surface);
  }
  .panel-search-wrap {
    position: relative;
    display: flex; align-items: center;
  }
  .panel-search input {
    width: 100%;
    padding: 9px 12px 9px 34px;
    border: 1px solid var(--hairline);
    border-radius: 10px;
    background: var(--surface-soft);
    color: var(--ink);
    font: 500 13px 'Geist', sans-serif;
    transition: border-color 0.2s var(--ease), background 0.2s var(--ease);
  }
  .panel-search input::placeholder { color: var(--ink-dim); }
  .panel-search input:focus {
    outline: none;
    border-color: var(--brand-blue);
    background: var(--surface);
    box-shadow: 0 0 0 3px var(--brand-blue-soft);
  }
  .panel-search svg {
    position: absolute; left: 11px; color: var(--ink-dim); pointer-events: none;
  }
  .calls-list { flex: 1; overflow-y: auto; padding: 6px 0 12px; }
  .call-item {
    margin: 0 12px;
    padding: 14px 14px 14px 16px;
    border-radius: 14px;
    cursor: pointer;
    transition: background 0.18s var(--ease), border-color 0.18s var(--ease), transform 0.18s var(--ease);
    border: 1px solid transparent;
    position: relative;
    opacity: 0; transform: translateY(4px);
    animation: fadeUp 0.4s var(--ease) forwards;
    animation-delay: calc(var(--i, 0) * 35ms);
  }
  .call-item + .call-item { margin-top: 4px; }
  .call-item::before {
    content: ''; position: absolute; left: 4px; top: 16px; bottom: 16px;
    width: 2px; border-radius: 2px;
    background: transparent; transition: background 0.2s var(--ease);
  }
  .call-item:hover { background: var(--surface-soft); }
  .call-item:active { transform: translateY(1px); }
  .call-item.selected {
    background: var(--surface-soft);
    border-color: var(--hairline-strong);
  }
  .call-item.live::before { background: var(--success); }
  .call-item-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 8px;
  }
  .call-from {
    font-size: 14px; font-weight: 600; letter-spacing: -0.005em;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
    display: flex; align-items: center; gap: 6px;
  }
  .call-time {
    font-size: 11px; color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
    font-family: 'Geist Mono', ui-monospace, monospace;
  }
  .call-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .badge {
    font-size: 10px; font-weight: 600;
    padding: 3px 9px; border-radius: 100px;
    text-transform: uppercase; letter-spacing: 0.06em;
    display: inline-flex; align-items: center; gap: 5px;
    border: 1px solid transparent;
  }
  .badge-active {
    background: var(--success-soft); color: var(--success);
    border-color: rgba(4, 120, 87, 0.22);
  }
  .badge-ended {
    background: var(--surface-soft); color: var(--ink-muted);
    border-color: var(--hairline);
    font-variant-numeric: tabular-nums;
  }
  .badge-followup {
    background: var(--warning-soft); color: var(--warning);
    border-color: rgba(183, 121, 31, 0.22);
  }
  .badge-success {
    background: var(--success-soft); color: var(--success);
    border-color: rgba(4, 120, 87, 0.18);
  }
  .badge-danger {
    background: var(--danger-soft); color: var(--danger);
    border-color: rgba(255, 80, 99, 0.30);
  }
  /* ---- Priority-coded status badges (match the header legend) ---- */
  .badge-p-high      { background: var(--danger-soft);  color: var(--danger);      border-color: rgba(255, 80, 99, 0.32); }
  .badge-p-attention { background: var(--warning-soft); color: var(--warning);     border-color: rgba(251, 191, 36, 0.34); }
  .badge-p-good      { background: var(--success-soft); color: var(--success);     border-color: rgba(52, 245, 197, 0.30); }
  .badge-p-check     { background: var(--cyan-soft);    color: var(--cyan-bright); border-color: rgba(34, 211, 238, 0.34); }
  /* Left-accent bar on each call row reflects its priority tier */
  .call-item.tier-high::before      { background: var(--danger); }
  .call-item.tier-attention::before { background: var(--warning); }
  .call-item.tier-good::before      { background: var(--success); }
  .call-item.tier-check::before     { background: var(--cyan); }
  .call-item.tier-live::before      { background: var(--success); }
  /* Header priority legend */
  .legend { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .legend .lg { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600; color: var(--ink-soft); white-space: nowrap; }
  .legend .lg-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; box-shadow: 0 0 7px currentColor; }
  .lg-high { background: var(--danger); color: var(--danger); }
  .lg-attention { background: var(--warning); color: var(--warning); }
  .lg-good { background: var(--success); color: var(--success); }
  .lg-check { background: var(--cyan); color: var(--cyan); }
  /* Notifications bell + feed */
  .notif-bell { position: relative; }
  .notif-badge {
    position: absolute; top: -5px; right: -5px; min-width: 16px; height: 16px; padding: 0 4px;
    border-radius: 8px; background: var(--danger); color: #fff; font-size: 9px; font-weight: 800;
    display: none; align-items: center; justify-content: center; line-height: 1; box-shadow: 0 0 8px var(--danger);
  }
  .notif-badge.show { display: inline-flex; }
  .notif-list { display: flex; flex-direction: column; gap: 8px; max-height: 60vh; overflow-y: auto; }
  .notif-item { display: flex; gap: 12px; padding: 12px 14px; border-radius: 12px;
    background: var(--surface); border: 1px solid var(--hairline); }
  .notif-item.unread { border-color: var(--hairline-strong); background: var(--surface-soft); }
  .notif-ico { font-size: 18px; line-height: 1.4; flex-shrink: 0; }
  .notif-body { flex: 1; min-width: 0; }
  .notif-title { font-size: 13px; font-weight: 600; color: var(--ink); }
  .notif-sub { font-size: 12px; color: var(--ink-muted); margin-top: 2px; }
  .notif-time { font-size: 11px; color: var(--ink-dim); margin-top: 3px; }
  .notif-empty { padding: 28px; text-align: center; color: var(--ink-muted); font-size: 13px; }
  /* ---- Message Center: WhatsApp-style chats grouped by phone number ---- */
  #notif-modal .oncall-card { max-width: 460px; width: 100%; display: flex; flex-direction: column; }
  #chat-listview, #chat-threadview { display: flex; flex-direction: column; min-height: 0; flex: 1; }
  .chat-list { display: flex; flex-direction: column; gap: 6px; max-height: 62vh; overflow-y: auto; padding: 2px; }
  .chat-row {
    display: flex; gap: 12px; align-items: center; padding: 11px 12px; border-radius: 14px;
    background: var(--surface); border: 1px solid var(--hairline); cursor: pointer;
    transition: background 0.16s var(--ease), border-color 0.16s var(--ease), transform 0.16s var(--ease);
  }
  .chat-row:hover { background: var(--surface-soft); }
  .chat-row:active { transform: scale(0.99); }
  .chat-row.unread { border-color: var(--hairline-strong); background: var(--surface-soft); }
  .chat-avatar {
    width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0; font-size: 19px;
    display: flex; align-items: center; justify-content: center;
    background: var(--cyan-soft); border: 1px solid var(--hairline);
  }
  .chat-row-body { flex: 1; min-width: 0; }
  .chat-row-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .chat-row-name { font-size: 14px; font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .chat-row.unread .chat-row-name { font-weight: 700; }
  .chat-row-time { font-size: 11px; color: var(--ink-dim); flex-shrink: 0; }
  .chat-row-bottom { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 2px; }
  .chat-row-preview { font-size: 12px; color: var(--ink-muted); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; flex: 1; min-width: 0; }
  .chat-row-ico { margin-right: 5px; opacity: 0.9; }
  .chat-row.unread .chat-row-preview { color: var(--ink-soft); }
  .chat-row-badge {
    min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; background: var(--cyan); color: #04121a;
    font-size: 10px; font-weight: 800; display: inline-flex; align-items: center; justify-content: center;
    flex-shrink: 0; box-shadow: 0 0 7px var(--cyan-glow);
  }
  .chat-thread-head { display: flex; align-items: center; gap: 10px; }
  .chat-head-avatar { width: 34px; height: 34px; font-size: 16px; }
  .chat-back {
    width: 32px; height: 32px; flex-shrink: 0; border-radius: 9px; cursor: pointer;
    background: var(--surface-soft); border: 1px solid var(--hairline); color: var(--ink);
    font-size: 20px; line-height: 1; display: flex; align-items: center; justify-content: center;
  }
  .chat-back:hover { background: var(--surface); }
  .chat-thread {
    display: flex; flex-direction: column; gap: 8px; max-height: 60vh; overflow-y: auto;
    padding: 10px 2px 4px;
  }
  .msg-bubble {
    align-self: flex-start; max-width: 86%; padding: 9px 12px; border-radius: 4px 14px 14px 14px;
    background: var(--surface-soft); border: 1px solid var(--hairline);
  }
  .msg-bubble-head { display: flex; align-items: center; gap: 6px; }
  .msg-bubble-ico { font-size: 13px; }
  /* The alert type is a small kicker label; the body is the real message text. */
  .msg-bubble-title { font-size: 11px; font-weight: 700; letter-spacing: 0.02em; text-transform: uppercase; color: var(--ink-muted); }
  .msg-bubble-body { font-size: 13.5px; color: var(--ink); margin-top: 4px; white-space: pre-wrap; line-height: 1.45; }
  .msg-bubble-time { font-size: 10px; color: var(--ink-dim); margin-top: 4px; text-align: right; }
  /* Day separator + conversation-start caption */
  .msg-day { text-align: center; margin: 6px 0 2px; }
  .msg-day span { display: inline-block; font-size: 10.5px; font-weight: 700; letter-spacing: 0.03em;
    color: var(--ink-muted); background: var(--surface-soft); border: 1px solid var(--hairline);
    border-radius: 999px; padding: 3px 10px; }
  .msg-start { text-align: center; font-size: 10.5px; color: var(--ink-dim); padding: 2px 0 6px; }
  /* Rich bubbles — mirror the full Telegram wrap-up + action buttons */
  .msg-bubble.rich { max-width: 96%; width: 100%; border-radius: 14px; padding: 11px 13px; }
  .msg-kicker { display: flex; align-items: center; gap: 6px; font-size: 10.5px; font-weight: 800;
    letter-spacing: 0.04em; text-transform: uppercase; color: var(--cyan-bright); }
  .msg-kicker-ico { font-size: 12px; }
  .msg-name { font-size: 16px; font-weight: 700; color: var(--ink); margin-top: 4px; letter-spacing: -0.01em; }
  .msg-phone { display: inline-block; font-size: 13px; font-weight: 600; color: var(--cyan-bright);
    text-decoration: none; font-variant-numeric: tabular-nums; margin-top: 1px; }
  .msg-phone:active { opacity: 0.7; }
  .msg-field { display: flex; gap: 7px; align-items: flex-start; font-size: 13px; color: var(--ink-soft);
    margin-top: 7px; line-height: 1.42; }
  .msg-field-ico { flex-shrink: 0; }
  .msg-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .msg-chip { font-size: 11px; font-weight: 600; color: var(--ink-muted); background: var(--surface);
    border: 1px solid var(--hairline); border-radius: 999px; padding: 3px 9px; }
  .msg-followup { margin-top: 8px; font-size: 12.5px; font-weight: 600; color: var(--warning);
    background: var(--warning-soft); border: 1px solid rgba(251, 191, 36, 0.28); border-radius: 9px; padding: 6px 10px; }
  .msg-booking { margin-top: 8px; background: var(--surface); border: 1px solid var(--hairline);
    border-radius: 10px; padding: 8px 11px; }
  .msg-booking-row { font-size: 13px; color: var(--ink); }
  .msg-booking-sub { font-size: 12px; color: var(--ink-muted); margin-top: 2px; }
  .msg-confirm { margin-top: 9px; background: var(--cyan-soft); border: 1px solid rgba(34, 211, 238, 0.22);
    border-radius: 10px; padding: 8px 11px; }
  .msg-confirm-label { font-size: 10px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase; color: var(--cyan-bright); }
  .msg-confirm-text { font-size: 12.5px; color: var(--ink-soft); margin-top: 4px; line-height: 1.45; white-space: pre-wrap; }
  .msg-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }
  .msg-act { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; font-weight: 600;
    color: var(--ink); background: var(--surface); border: 1px solid var(--hairline-strong); border-radius: 10px;
    padding: 8px 11px; min-height: 38px; cursor: pointer; text-decoration: none;
    transition: background 0.15s var(--ease), border-color 0.15s var(--ease), transform 0.1s var(--ease); }
  .msg-act:hover { background: var(--surface-soft); border-color: var(--cyan); }
  .msg-act:active { transform: scale(0.98); }
  /* Polished empty state for the inbox (native-app feel) */
  .chat-empty {
    flex: 1; min-height: 200px; display: flex; flex-direction: column;
    align-items: center; justify-content: center; text-align: center;
    gap: 12px; padding: 40px 28px; color: var(--ink-muted);
  }
  .chat-empty .chat-empty-ico {
    width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    background: var(--cyan-soft); border: 1px solid var(--hairline);
  }
  .chat-empty .chat-empty-ico svg { width: 26px; height: 26px; color: var(--cyan); }
  .chat-empty-title { font-size: 15px; font-weight: 600; color: var(--ink); }
  .chat-empty-sub { font-size: 12.5px; color: var(--ink-muted); max-width: 260px; line-height: 1.5; }
  .live-pulse {
    width: 6px; height: 6px; border-radius: 50%; background: var(--success);
    animation: livePulse 1.5s ease-in-out infinite;
    box-shadow: 0 0 8px 1px rgba(52, 245, 197, 0.7);
  }
  @keyframes livePulse {
    0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(52, 245, 197, 0.55); }
    70% { transform: scale(1.1); box-shadow: 0 0 0 7px rgba(52, 245, 197, 0); }
  }
  @keyframes fadeUp {
    to { opacity: 1; transform: translateY(0); }
  }

  /* DETAIL PANEL */
  .detail-panel { }
  .detail-header {
    padding: 20px 28px;
    border-bottom: 1px solid var(--hairline);
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px;
    background: var(--surface);
  }
  .detail-title h2 {
    font-size: 18px; font-weight: 600; letter-spacing: -0.015em; color: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .detail-title .meta {
    font-size: 12.5px; color: var(--ink-muted); margin-top: 4px;
    display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }
  .meta-dot { width: 3px; height: 3px; border-radius: 50%; background: var(--ink-dim); }
  .actions { display: flex; gap: 8px; }
  .btn {
    padding: 10px 16px; border-radius: 10px; border: 1px solid transparent;
    font-size: 13px; font-weight: 600; cursor: pointer;
    transition: transform 0.18s var(--ease), box-shadow 0.25s var(--ease), background 0.18s var(--ease);
    font-family: inherit; letter-spacing: -0.005em;
    display: inline-flex; align-items: center; gap: 7px;
    text-decoration: none; line-height: 1;
  }
  .btn:active:not(:disabled) { transform: translateY(1px) scale(0.99); }
  .btn:disabled { opacity: 0.45; cursor: not-allowed; }
  .btn-primary {
    background: linear-gradient(180deg, var(--cyan-bright), var(--cyan));
    color: #04090E; font-weight: 600; border-color: transparent;
    box-shadow: 0 0 0 1px rgba(34,211,238,0.5) inset, 0 8px 22px -8px var(--cyan-glow);
  }
  .btn-primary:hover:not(:disabled) {
    background: linear-gradient(180deg, #8DEEFF, var(--cyan-bright));
    transform: translateY(-1px);
    box-shadow: 0 0 0 1px rgba(34,211,238,0.6) inset, 0 16px 34px -10px var(--cyan-glow);
  }
  .btn-danger {
    background: var(--surface); color: var(--danger);
    border-color: rgba(255, 80, 99, 0.30);
  }
  .btn-danger:hover:not(:disabled) {
    background: var(--danger-soft);
    border-color: rgba(255, 80, 99, 0.5);
  }
  .btn-secondary {
    background: var(--surface); color: var(--ink); border-color: var(--hairline);
  }

  /* CONTENT SCROLL */
  .detail-content {
    flex: 1; overflow-y: auto; padding: 24px 28px 28px;
  }

  /* AI SUMMARY CARD — Bento 2.0 */
  .summary-card {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: 20px;
    padding: 22px 24px;
    margin-bottom: 22px;
    position: relative;
    overflow: hidden;
    box-shadow: var(--shadow-card);
  }
  .summary-card::before {
    content: ''; position: absolute; top: 0; left: 0; bottom: 0; width: 3px;
    background: linear-gradient(180deg, var(--brand-red), var(--brand-blue));
  }
  .summary-card-header {
    display: flex; align-items: center; gap: 12px; margin-bottom: 16px;
  }
  .summary-icon {
    width: 32px; height: 32px; border-radius: 9px;
    background: linear-gradient(135deg, var(--brand-red-soft), var(--brand-blue-soft));
    color: var(--brand-red);
    display: inline-flex; align-items: center; justify-content: center;
    border: 1px solid var(--hairline);
  }
  .summary-card-header h3 {
    font-size: 13.5px; font-weight: 600; letter-spacing: -0.005em;
  }
  .summary-card-header .summary-tag {
    margin-left: auto;
    font-size: 10.5px; color: var(--ink-muted); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
  }
  .summary-row {
    display: grid; grid-template-columns: 110px 1fr; gap: 16px;
    align-items: flex-start;
    padding: 12px 0;
    border-top: 1px solid var(--hairline);
  }
  .summary-row:first-of-type { border-top: none; padding-top: 0; }
  .summary-label {
    font-size: 11px; color: var(--ink-muted); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.06em;
    padding-top: 1px;
  }
  .summary-value { font-size: 13.5px; line-height: 1.6; color: var(--ink-soft); }
  .summary-value.bold { font-weight: 600; color: var(--ink); }

  /* FOLLOWUP BANNER */
  .followup-banner {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-left: 3px solid var(--warning);
    border-radius: 14px;
    padding: 14px 18px;
    margin-bottom: 16px;
    display: flex; align-items: center; gap: 14px;
    box-shadow: var(--shadow-card);
  }
  .followup-banner.success { border-left-color: var(--success); }
  .followup-banner.danger { border-left-color: var(--danger); }
  .followup-icon {
    width: 36px; height: 36px; border-radius: 10px;
    display: inline-flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    background: var(--warning-soft); color: var(--warning);
  }
  .followup-banner.success .followup-icon { background: var(--success-soft); color: var(--success); }
  .followup-banner.danger .followup-icon { background: var(--danger-soft); color: var(--danger); }
  .followup-text strong {
    font-size: 13.5px; font-weight: 600; display: block; margin-bottom: 2px;
    color: var(--ink); letter-spacing: -0.005em;
  }
  .followup-text span { font-size: 12.5px; color: var(--ink-muted); }

  /* SUMMARY SHIMMER (loading) */
  .summary-skeleton {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: 20px;
    padding: 22px 24px;
    margin-bottom: 22px;
    display: flex; flex-direction: column; gap: 14px;
    box-shadow: var(--shadow-card);
  }
  .skeleton-bar {
    height: 12px; border-radius: 6px;
    background: linear-gradient(90deg, var(--surface-soft) 0%, rgba(34,211,238,0.16) 50%, var(--surface-soft) 100%);
    background-size: 200% 100%;
    animation: shimmer 1.6s linear infinite;
  }
  @keyframes shimmer {
    from { background-position: 200% 0; }
    to { background-position: -200% 0; }
  }

  /* TRANSCRIPT */
  .transcript-section h3 {
    font-size: 11px; color: var(--ink-muted); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.1em;
    margin-bottom: 16px;
    display: flex; align-items: center; gap: 8px;
  }
  .transcript-section h3 svg { color: var(--brand-red); }
  .transcript { display: flex; flex-direction: column; gap: 8px; }
  .turn {
    padding: 12px 16px;
    border-radius: 16px;
    max-width: 78%;
    line-height: 1.55;
    font-size: 13.5px;
    animation: slideIn 0.3s var(--ease);
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .turn-agent {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-left: 2px solid var(--brand-red);
    border-bottom-left-radius: 6px;
    align-self: flex-start;
    color: var(--ink-soft);
    box-shadow: var(--shadow-card);
  }
  .turn-user {
    background: linear-gradient(135deg, var(--cyan) 0%, var(--cyan-bright) 100%);
    color: #04090E;
    border-bottom-right-radius: 6px;
    align-self: flex-end;
    max-width: 78%;
    box-shadow: 0 8px 22px -10px var(--cyan-glow);
  }
  .turn-tool {
    background: var(--surface-soft);
    border: 1px solid var(--hairline);
    color: var(--ink-muted);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 11px;
    align-self: center;
    max-width: 90%;
    padding: 8px 12px;
    border-radius: 100px;
    display: inline-flex; align-items: center; gap: 6px;
  }
  .turn-tool svg { color: var(--brand-blue-light); }
  .turn-role {
    font-size: 10px; font-weight: 700; opacity: 0.75;
    text-transform: uppercase; letter-spacing: 0.08em;
    margin-bottom: 4px;
    display: inline-flex; align-items: center; gap: 6px;
  }
  .turn-agent .turn-role { color: var(--brand-red); }
  .turn-user .turn-role { color: rgba(4,9,14,0.72); }

  /* EMPTY STATES */
  .empty-state {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 60px 24px; text-align: center; color: var(--ink-muted);
    height: 100%; min-height: 240px;
  }
  .empty-icon {
    width: 56px; height: 56px; border-radius: 16px;
    background: var(--surface-soft);
    border: 1px solid var(--hairline);
    display: inline-flex; align-items: center; justify-content: center;
    margin-bottom: 18px;
    color: var(--ink-dim);
  }
  .empty-icon svg { width: 24px; height: 24px; }
  .empty-title {
    font-size: 14px; font-weight: 600; color: var(--ink);
    margin-bottom: 6px; letter-spacing: -0.005em;
  }
  .empty-subtitle { font-size: 13px; max-width: 320px; line-height: 1.55; }

  /* TWO-SECTION CALL LIST */
  .call-section + .call-section { margin-top: 6px; }
  .section-header {
    padding: 16px 18px 8px;
    font-size: 10.5px; font-weight: 700;
    color: var(--ink-muted);
    text-transform: uppercase; letter-spacing: 0.1em;
    display: flex; align-items: center; gap: 8px;
  }
  .section-dot {
    width: 7px; height: 7px; border-radius: 50%;
    flex-shrink: 0;
  }
  .section-active .section-header { color: var(--success); }
  .section-active .section-dot {
    background: var(--success);
    box-shadow: 0 0 8px 1px rgba(52, 245, 197, 0.6);
    animation: livePulse 1.6s ease-in-out infinite;
  }
  .section-ended .section-header { color: var(--ink-muted); }
  .section-ended .section-dot {
    background: var(--ink-dim);
  }
  .section-count {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    font-size: 10px;
    background: var(--surface-soft);
    color: var(--ink-soft);
    border: 1px solid var(--hairline);
    padding: 2px 8px; border-radius: 100px;
    letter-spacing: 0;
  }
  .section-active .section-count {
    background: var(--success-soft); color: var(--success);
    border-color: rgba(4, 120, 87, 0.18);
  }

  /* HEADER ALERTS BUTTON */
  .alerts-btn {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 7px 13px; border-radius: 100px;
    background: var(--surface); border: 1px solid var(--hairline);
    font: 600 12px 'Geist', sans-serif; color: var(--ink-soft);
    cursor: pointer;
    transition: background 0.18s var(--ease), border-color 0.18s var(--ease), color 0.18s var(--ease);
  }
  .alerts-btn:hover { background: var(--surface-soft); border-color: var(--hairline-strong); }
  .alerts-btn.granted {
    background: var(--success-soft); color: var(--success);
    border-color: rgba(4, 120, 87, 0.22);
  }
  .alerts-btn.denied { color: var(--ink-dim); cursor: default; }
  .alerts-btn svg { color: currentColor; }

  /* TOAST STACK */
  .toast-stack {
    position: fixed; top: 84px; right: 24px;
    z-index: 100;
    display: flex; flex-direction: column; gap: 12px;
    pointer-events: none;
    max-width: calc(100vw - 32px);
  }
  .toast {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-left: 3px solid var(--success);
    border-radius: 16px;
    padding: 14px 18px 14px 16px;
    min-width: 300px; max-width: 380px;
    display: flex; align-items: center; gap: 12px;
    box-shadow: 0 0 0 1px var(--hairline-strong), 0 24px 50px -18px rgba(0,0,0,0.85);
    animation: toastIn 0.42s var(--ease) both;
    pointer-events: auto;
    cursor: pointer;
    position: relative;
    overflow: hidden;
  }
  .toast::after {
    content: ''; position: absolute; bottom: 0; left: 0; height: 2px;
    background: currentColor; opacity: 0.4;
    animation: toastProgress var(--toast-duration, 6s) linear forwards;
  }
  .toast.toast-start { color: var(--success); }
  .toast.toast-ended {
    color: var(--brand-red);
    border-left-color: var(--brand-red);
  }
  .toast.toast-info { color: var(--brand-blue); border-left-color: var(--brand-blue); }
  .toast.dismissed { animation: toastOut 0.3s var(--ease) both; }
  .toast-icon {
    width: 38px; height: 38px; border-radius: 11px;
    display: inline-flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    background: var(--success-soft); color: var(--success);
  }
  .toast.toast-ended .toast-icon { background: var(--brand-red-soft); color: var(--brand-red); }
  .toast.toast-info .toast-icon { background: var(--brand-blue-soft); color: var(--brand-blue); }
  .toast-text { min-width: 0; flex: 1; }
  .toast-text strong {
    font-size: 13.5px; font-weight: 600; color: var(--ink); display: block;
    letter-spacing: -0.005em;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .toast-text span {
    font-size: 12.5px; color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
  }
  .toast-dismiss {
    background: none; border: none; padding: 4px; cursor: pointer;
    color: var(--ink-dim); display: inline-flex;
    border-radius: 6px; transition: background 0.15s var(--ease), color 0.15s var(--ease);
  }
  .toast-dismiss:hover { background: var(--surface-soft); color: var(--ink-soft); }
  @keyframes toastIn {
    from { opacity: 0; transform: translateX(20px) scale(0.96); }
    to { opacity: 1; transform: translateX(0) scale(1); }
  }
  @keyframes toastOut {
    to { opacity: 0; transform: translateX(20px) scale(0.96); }
  }
  @keyframes toastProgress {
    from { width: 100%; } to { width: 0%; }
  }

  /* SCROLLBAR */
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb {
    background: var(--hairline-strong);
    border-radius: 100px;
    border: 2px solid transparent;
    background-clip: content-box;
  }
  ::-webkit-scrollbar-thumb:hover { background: var(--ink-dim); background-clip: content-box; }

  /* RESPONSIVE — strict single column on mobile */
  @media (max-width: 980px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
    .container { grid-template-columns: 1fr; height: auto; min-height: 0; }
    .calls-panel { max-height: 320px; }
    .page { padding: 16px 14px 0; max-width: 100%; }
    header { padding: 12px 16px; gap: 12px; }
    .brand { flex-shrink: 0; }
    /* Header actions never force page overflow — they shrink and scroll horizontally */
    .header-right {
      min-width: 0; flex: 1 1 auto; justify-content: flex-end;
      overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none;
    }
    .header-right::-webkit-scrollbar { display: none; }
    .header-right > * { flex: 0 0 auto; }
    .detail-content, .detail-header { padding-left: 18px; padding-right: 18px; }
    .stat-value { font-size: 28px; }
  }
  @media (max-width: 540px) {
    .stats { grid-template-columns: 1fr; }
    .brand-divider, .brand-text { display: none; }
    .clock-pill { display: none; }
    header { padding: 10px 12px; gap: 10px; }
    .brand { flex-shrink: 0; }
    /* Actions become a clean horizontal-scroll strip instead of overflowing the page */
    .header-right {
      gap: 8px; min-width: 0; flex: 1; justify-content: flex-end;
      overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none;
    }
    .header-right::-webkit-scrollbar { display: none; }
    .header-right > * { flex: 0 0 auto; }
    .page { padding: 14px 12px 0; }
    .stat-value { font-size: 26px; }
  }

  /* ===================== MOBILE APP MODE — bottom tabs + detail sheet ===================== */
  .bottom-tabs { display: none; }
  .detail-back { display: none; }
  .m-insights-only { display: none; }
  .m-tools-label { display: none; }

  @media (max-width: 720px) {
    /* Slim app bar — logo + live dot only; secondary actions move into tabs/Insights */
    header { padding: 11px 16px; flex-wrap: wrap; }
    .brand-divider, .brand-text .subtitle { display: none; }
    .brand-text h1 { font-size: 15px; }
    .clock-pill, #alerts-btn, #oncall-btn, #reset-btn, #transfer-btn, #customize-btn, #analytics-link { display: none; }
    .header-right { gap: 8px; flex: 0 0 auto; }
    /* Legend drops to its own full-width row under the logo */
    .legend { display: none; }   /* legend belongs with the call labels — Calls page only */
    body.m-calls .legend { display: flex; order: 3; flex-basis: 100%; justify-content: space-between;
      gap: 8px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--hairline); }
    .legend .lg { font-size: 10.5px; gap: 5px; }

    /* Room for the fixed tab bar */
    body { padding-bottom: calc(62px + env(safe-area-inset-bottom)); }
    .page { padding: 14px 14px 0; }

    /* --- Tab panels: body.m-calls / .m-insights / .m-oncall toggles what shows --- */
    .stats, .howfound-card, .m-insights-only { display: none; }
    .container { display: block; }                 /* Calls is the default panel */
    /* On desktop these are overlays; on the phone they ARE the On-Call page, shown
       inline only when the On-Call tab is active. */
    #oncall-modal, #transfer-modal { display: none; }
    body.m-insights .stats { display: grid; }
    body.m-insights .howfound-card { display: block; }
    body.m-insights .m-insights-only { display: grid; }
    body.m-insights .container { display: none; }
    body.m-calls .stats, body.m-calls .howfound-card, body.m-calls .m-insights-only { display: none; }
    body.m-calls .container { display: block; }
    body.m-oncall .container, body.m-oncall .stats, body.m-oncall .howfound-card, body.m-oncall .m-insights-only { display: none; }
    body.m-oncall #oncall-modal, body.m-oncall #transfer-modal {
      display: block; position: static; inset: auto; z-index: auto;
      background: transparent; backdrop-filter: none; -webkit-backdrop-filter: none; padding: 0;
    }
    body.m-oncall #oncall-modal .oncall-card, body.m-oncall #transfer-modal .oncall-card {
      max-width: none; width: auto; margin: 0 14px 14px; max-height: none; animation: none;
    }
    body.m-oncall .oncall-close { display: none; }   /* it's a page now, not a popup */
    /* On-Call page — symmetric, phone-friendly */
    body.m-oncall .oncall-card { padding: 16px 14px 18px; border-radius: 18px; }
    body.m-oncall .oncall-head h2 { font-size: 17px; font-weight: 600; }
    body.m-oncall .oncall-week-nav { flex-wrap: wrap; gap: 8px; justify-content: center; }
    body.m-oncall .oncall-week-nav button { flex: 1 1 40%; }
    body.m-oncall .oncall-week-label { flex-basis: 100%; text-align: center; order: -1; }
    body.m-oncall .oncall-quick select { min-width: 0; }
    body.m-oncall .oncall-days { grid-template-columns: repeat(2, 1fr); gap: 10px; }
    body.m-oncall .oncall-day { min-height: 132px; }
    body.m-oncall .oncall-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    body.m-oncall .oncall-actions button { width: 100%; }
    body.m-oncall .transfer-add { flex-direction: column; align-items: stretch; }
    body.m-oncall .transfer-add .btn-primary { width: 100%; }

    /* --- Messages: a full-screen native chat app (un-overlay #notif-modal) --- */
    body.m-messages .container, body.m-messages .stats,
    body.m-messages .howfound-card, body.m-messages .m-insights-only,
    body.m-messages #oncall-modal, body.m-messages #transfer-modal { display: none; }
    body.m-messages #notif-btn { display: none; }   /* the tab replaces the bell on mobile */
    /* Pull the section flush to the page edges so it reads like a real app screen */
    body.m-messages .page { padding: 0; }
    body.m-messages #notif-modal {
      display: block; position: static; inset: auto; z-index: auto;
      background: transparent; backdrop-filter: none; -webkit-backdrop-filter: none;
      padding: 0; overflow: visible;
    }
    body.m-messages #notif-modal .oncall-card {
      max-width: none; width: auto; margin: 0; max-height: none; animation: none;
      padding: 0; border-radius: 0; border: 0; background: transparent; box-shadow: none;
      /* Fill the space between the app bar and the bottom tab bar */
      height: calc(100vh - 56px - 62px - env(safe-area-inset-bottom));
      display: flex; flex-direction: column;
    }
    body.m-messages #chat-listview, body.m-messages #chat-threadview {
      flex: 1; min-height: 0; display: flex; flex-direction: column;
    }
    body.m-messages #chat-threadview[style*="display:none"],
    body.m-messages #chat-threadview[style*="display: none"] { display: none !important; }
    body.m-messages .notif-close, body.m-messages #notif-close,
    body.m-messages #chat-close { display: none; }   /* leave by switching tabs, not a popup X */
    /* Section header — sticky, native app-bar feel */
    body.m-messages .oncall-head, body.m-messages .chat-thread-head {
      margin: 0; padding: 14px 16px; border-bottom: 1px solid var(--hairline);
      background: rgba(8,12,18,0.92); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
      flex-shrink: 0;
    }
    body.m-messages .oncall-head strong { font-size: 18px; }
    body.m-messages .oncall-head .oncall-sub, body.m-messages .chat-thread-head .oncall-sub {
      margin-bottom: 0; margin-top: 2px;
    }
    body.m-messages .chat-back { width: 36px; height: 36px; font-size: 24px; }
    /* Inbox list scrolls inside the section, not the page */
    body.m-messages #chat-list {
      flex: 1; min-height: 0; max-height: none; overflow-y: auto;
      -webkit-overflow-scrolling: touch; gap: 2px; padding: 8px 12px 12px;
    }
    body.m-messages .chat-row { border-radius: 14px; padding: 12px; }
    /* Conversation thread fills + scrolls inside the section */
    body.m-messages #chat-thread {
      flex: 1; min-height: 0; max-height: none; overflow-y: auto;
      -webkit-overflow-scrolling: touch; padding: 14px 14px 18px;
    }
    /* "Clear all" sits pinned at the bottom of the inbox */
    body.m-messages #chat-listview .oncall-actions {
      flex-shrink: 0; padding: 10px 14px calc(10px + env(safe-area-inset-bottom));
      border-top: 1px solid var(--hairline); justify-content: stretch;
    }
    body.m-messages #chat-listview .oncall-actions .oncall-btn { flex: 1; }

    .stats { grid-template-columns: repeat(2, 1fr); gap: 10px; }
    .container { grid-template-columns: 1fr; height: auto; }
    .calls-panel { max-height: none; }

    /* Detail hidden until a call is tapped, then it slides up as a full-screen sheet */
    .detail-panel { display: none; }
    body.detail-open { overflow: hidden; }
    body.detail-open .detail-panel {
      display: flex; flex-direction: column;
      position: fixed; inset: 0; z-index: 80;
      background: var(--bg); overflow-y: auto;
      animation: sheetUp 0.28s var(--ease);
      padding-bottom: calc(24px + env(safe-area-inset-bottom));
    }
    @keyframes sheetUp { from { transform: translateY(100%); opacity: 0.6; } to { transform: translateY(0); opacity: 1; } }
    .detail-back {
      display: flex; align-items: center; gap: 6px;
      position: sticky; top: 0; z-index: 2; width: 100%; border: 0; text-align: left;
      padding: 14px 18px; cursor: pointer;
      background: rgba(8,12,18,0.88); backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--hairline);
      color: var(--cyan); font-weight: 600; font-size: 15px; font-family: inherit;
    }
    .detail-back svg { width: 18px; height: 18px; }

    /* Insights settings row (proxies the hidden header buttons) */
    body.m-insights .m-tools-label { display: block; font-size: 11px; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-muted); margin: 18px 6px 2px; }
    .m-insights-only.settings-row { grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 4px; }
    .settings-item {
      display: flex; flex-direction: column; align-items: center; gap: 6px;
      padding: 16px 8px; border-radius: 16px; cursor: pointer;
      background: var(--surface); border: 1px solid var(--hairline);
      color: var(--ink-soft); font-size: 12px; font-weight: 600; font-family: inherit;
    }
    .settings-item svg { width: 20px; height: 20px; color: var(--cyan); }
    .settings-item:active { transform: scale(0.97); }

    /* Bottom tab bar */
    .bottom-tabs {
      display: flex; position: fixed; left: 0; right: 0; bottom: 0; z-index: 90;
      background: linear-gradient(180deg, rgba(12,18,27,0.92), rgba(6,9,14,0.98));
      backdrop-filter: blur(18px) saturate(1.2); -webkit-backdrop-filter: blur(18px) saturate(1.2);
      border-top: 1px solid var(--hairline);
      box-shadow: 0 -10px 28px -14px rgba(0,0,0,0.85);
      padding-bottom: env(safe-area-inset-bottom);
    }
    .tab-btn {
      flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px;
      padding: 9px 4px 8px; background: none; border: 0; cursor: pointer;
      color: var(--ink-muted); font-size: 10.5px; font-weight: 600; font-family: inherit;
      letter-spacing: 0.02em; transition: color 0.2s var(--ease);
    }
    .tab-btn svg { width: 22px; height: 22px; stroke-width: 1.7; transition: filter 0.2s var(--ease); }
    .tab-btn.active { color: var(--cyan); }
    .tab-btn.active svg { filter: drop-shadow(0 0 7px var(--cyan-glow)); }
    /* Bigger touch targets for the most error-prone controls */
    .oncall-tech-chip { min-height: 44px; padding: 11px 12px; }
    .oncall-close { font-size: 30px; padding: 6px 14px; min-width: 44px; min-height: 44px; }
    .tcontact-actions button { min-height: 38px; padding: 8px 12px; }
    /* Detail-sheet action buttons: full-width, no wrapping */
    .detail-header .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; }
    .detail-header .actions .btn { white-space: nowrap; justify-content: center; }
  }
  /* Live-call badge on the Calls bottom tab */
  .tab-btn { position: relative; }
  .tab-badge {
    position: absolute; top: 3px; left: 50%; transform: translateX(4px);
    min-width: 17px; height: 17px; padding: 0 5px; border-radius: 9px;
    background: var(--success); color: #04090E; font-size: 10px; font-weight: 800;
    display: none; align-items: center; justify-content: center; line-height: 1;
    box-shadow: 0 0 8px var(--success);
  }
  .tab-badge.show { display: inline-flex; }
  .tab-badge.msg-badge { background: var(--cyan); color: #04121a; box-shadow: 0 0 8px var(--cyan-glow); }
</style>
</head>
<body>

<header>
  <div class="brand">
    <img class="brand-mark" src="{{ logo_data_uri }}" alt="High Tech Air Conditioning" />
    <div class="brand-divider"></div>
    <div class="brand-text">
      <h1>Call Intelligence</h1>
      <div class="subtitle">Live monitoring · Powered by <a class="brand-link" href="https://manyfai.com" target="_blank" rel="noopener">ManyFai</a></div>
    </div>
  </div>
  <div class="legend" id="priority-legend" title="What the call colors mean">
    <span class="lg"><span class="lg-dot lg-high"></span>High priority</span>
    <span class="lg"><span class="lg-dot lg-attention"></span>Needs attention</span>
    <span class="lg"><span class="lg-dot lg-good"></span>Good</span>
    <span class="lg"><span class="lg-dot lg-check"></span>Worth a look</span>
  </div>
  <div class="header-right">
    <a class="alerts-btn" id="analytics-link" href="#" title="Call quality analytics">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 6-6"/></svg>
      <span>Analytics</span>
    </a>
    <div class="clock-pill" id="clock-pill">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/></svg>
      <span id="clock-text">—</span>
    </div>
    <button class="alerts-btn" id="alerts-btn" type="button" title="Enable browser notifications + sound for new calls">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
      <span id="alerts-label">Enable alerts</span>
    </button>
    <button class="alerts-btn" id="oncall-btn" type="button" title="Manage on-call tech schedule">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
      <span>On-Call</span>
    </button>
    <button class="alerts-btn" id="transfer-btn" type="button" title="Manage who the AI transfers callers to">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M17 2l4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></svg>
      <span>Transfer</span>
    </button>
    <button class="alerts-btn" id="customize-btn" type="button" title="Customize which boxes show and their order">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>
      <span>Customize</span>
    </button>
    <button class="alerts-btn" id="reset-btn" type="button" title="Clear all calls from the dashboard">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9"/><path d="M3 4v5h5"/></svg>
      <span>Reset</span>
    </button>
    <button class="alerts-btn notif-bell" id="notif-btn" type="button" title="Notifications" aria-label="Notifications">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
      <span class="notif-badge" id="notif-badge"></span>
    </button>
    <div class="status-pill">
      <span class="status-dot" id="status-dot"></span>
      <span id="status-text">Connected</span>
    </div>
  </div>
</header>

<div class="toast-stack" id="toast-stack" aria-live="polite" aria-atomic="false"></div>

<!-- ON-CALL MODAL -->
<style>
  .oncall-overlay {
    display: none;
    position: fixed; inset: 0;
    background: rgba(2, 4, 8, 0.66);
    backdrop-filter: blur(6px);
    z-index: 1000;
    align-items: flex-start;
    justify-content: center;
    padding: 60px 20px 20px;
    overflow-y: auto;
  }
  .oncall-overlay.open { display: flex; }
  .oncall-card {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: 16px;
    padding: 28px;
    max-width: 720px;
    width: 100%;
    box-shadow: var(--shadow-card);
  }
  .oncall-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
  .oncall-head h2 { font-size: 19px; font-weight: 700; color: var(--ink); letter-spacing: -0.01em; }
  .oncall-close { background: transparent; border: none; color: var(--ink-muted); cursor: pointer; font-size: 26px; line-height: 1; padding: 4px 10px; border-radius: 6px; }
  .oncall-close:hover { background: var(--surface-soft); color: var(--ink); }
  .oncall-sub { font-size: 13px; color: var(--ink-muted); margin-bottom: 20px; line-height: 1.5; }
  .oncall-week-nav { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; background: var(--surface-soft); border: 1px solid var(--hairline); border-radius: 10px; margin-bottom: 16px; }
  .oncall-week-nav button { background: transparent; border: 1px solid var(--hairline); color: var(--ink); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600; }
  .oncall-week-nav button:hover { background: var(--surface); border-color: var(--hairline-strong); }
  .oncall-week-label { font-size: 13px; font-weight: 600; color: var(--ink); }
  .oncall-quick { display: flex; gap: 8px; align-items: center; padding: 12px 14px; background: var(--brand-blue-soft); border: 1px solid rgba(13, 89, 123, 0.15); border-radius: 10px; margin-bottom: 16px; flex-wrap: wrap; }
  .oncall-quick-label { font-size: 12px; font-weight: 600; color: var(--brand-blue); margin-right: 4px; white-space: nowrap; }
  .oncall-quick select { background: var(--surface); border: 1px solid var(--hairline-strong); color: var(--ink); padding: 6px 10px; border-radius: 6px; font-size: 12px; flex: 1; min-width: 140px; }
  .oncall-quick button { background: var(--brand-blue); color: #04090E; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600; }
  .oncall-quick button:hover { background: var(--brand-blue-light); }
  .oncall-days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; margin-bottom: 18px; }
  @media (max-width: 720px) { .oncall-days { grid-template-columns: repeat(2, 1fr); } }
  .oncall-day {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: 10px;
    padding: 12px 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .oncall-day.has-assignments { border-color: var(--success); background: var(--success-soft); }
  .oncall-day.is-today { border-color: var(--brand-blue); }
  .oncall-day-header { display: flex; flex-direction: column; gap: 2px; }
  .oncall-day-name { font-size: 11px; font-weight: 700; color: var(--ink-muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .oncall-day-date { font-size: 14px; font-weight: 600; color: var(--ink); }
  .oncall-day-techs { display: flex; flex-direction: column; gap: 4px; }
  .oncall-tech-chip {
    font-size: 11px; padding: 3px 7px; border-radius: 5px;
    background: var(--surface); border: 1px solid var(--hairline-strong); color: var(--ink-soft);
    cursor: pointer; text-align: center; user-select: none; transition: all 0.1s;
    line-height: 1.3;
  }
  .oncall-tech-chip:hover { background: var(--surface-soft); }
  .oncall-tech-chip.active { background: var(--brand-red); color: #04090E; border-color: var(--brand-red); font-weight: 600; }
  .oncall-actions { display: flex; gap: 8px; justify-content: flex-end; padding-top: 16px; border-top: 1px solid var(--hairline); }
  .oncall-btn { padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; border: 1px solid transparent; font-family: inherit; }
  .oncall-btn-secondary { background: var(--surface); color: var(--ink-soft); border-color: var(--hairline-strong); }
  .oncall-btn-secondary:hover { background: var(--surface-soft); }
  .oncall-btn-primary { background: var(--brand-red); color: #04090E; font-weight: 600; }
  .oncall-btn-primary:hover { background: var(--brand-red-warm); }

  /* Transfer contacts modal */
  .transfer-targets { display: grid; gap: 8px; margin-bottom: 14px; }
  .ttarget { display: flex; justify-content: space-between; align-items: center; gap: 10px;
    padding: 11px 14px; border-radius: 12px; background: var(--surface-soft); border: 1px solid var(--hairline); font-size: 13px; }
  .ttarget span { color: var(--ink-muted); font-weight: 600; }
  .ttarget b { color: var(--cyan); font-weight: 600; text-align: right; }
  .transfer-list { display: grid; gap: 8px; max-height: 300px; overflow-y: auto; }
  .tcontact { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 12px;
    background: var(--surface); border: 1px solid var(--hairline); }
  .tcontact-info { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .tcontact-info b { font-size: 14px; color: var(--ink); }
  .tcontact-info span { font-size: 12px; color: var(--ink-muted); font-family: 'Geist Mono', monospace; }
  .tcontact-actions { display: flex; gap: 6px; flex-shrink: 0; }
  .tcontact-actions button { padding: 6px 10px; border-radius: 8px; font-size: 12px; font-weight: 600;
    cursor: pointer; background: var(--surface-soft); border: 1px solid var(--hairline); color: var(--ink-soft); font-family: inherit; }
  .tcontact-actions button.on { background: var(--cyan); color: #04090E; border-color: transparent; }
  .tcontact-actions .tdel { color: var(--danger); border-color: rgba(255,80,99,0.3); padding: 6px 9px; }
  .transfer-add { display: flex; gap: 8px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--hairline); flex-wrap: wrap; }
  .transfer-add input { flex: 1; min-width: 120px; padding: 10px 12px; border-radius: 10px;
    background: var(--surface-soft); border: 1px solid var(--hairline); color: var(--ink); font-size: 14px; font-family: inherit; }
  .transfer-add input::placeholder { color: var(--ink-dim); }
  .transfer-add .btn-primary { flex: 0 0 auto; }
</style>
<div id="oncall-modal" class="oncall-overlay">
  <div class="oncall-card">
    <div class="oncall-head">
      <h2>On-Call Schedule</h2>
      <button id="oncall-close" class="oncall-close" type="button" aria-label="Close">×</button>
    </div>
    <div class="oncall-sub">
      Pick which tech is on-call for each day. The AI will only schedule appointments to those techs. Days with no selection allow all techs.
    </div>

    <div class="oncall-week-nav">
      <button id="oncall-prev" type="button">← Previous week</button>
      <div class="oncall-week-label" id="oncall-week-label">—</div>
      <button id="oncall-next" type="button">Next week →</button>
    </div>

    <div class="oncall-quick">
      <span class="oncall-quick-label">Set whole week:</span>
      <select id="oncall-quick-select"></select>
      <button id="oncall-quick-apply" type="button">Apply to all 7 days</button>
    </div>

    <div class="oncall-days" id="oncall-days"></div>

    <div class="oncall-actions">
      <button id="oncall-clear-week" class="oncall-btn oncall-btn-secondary" type="button">Clear week</button>
      <button id="oncall-save" class="oncall-btn oncall-btn-primary" type="button">Save schedule</button>
    </div>
  </div>
</div>

<div id="transfer-modal" class="oncall-overlay">
  <div class="oncall-card">
    <div class="oncall-head">
      <div>
        <strong>Transfer contacts</strong>
        <div class="oncall-sub">Pick who the AI transfers callers to. Tap a contact to set it as the Alfredo or general target.</div>
      </div>
      <button id="transfer-close" class="oncall-close" type="button" aria-label="Close">×</button>
    </div>
    <div id="transfer-targets" class="transfer-targets"></div>
    <div id="transfer-list" class="transfer-list"></div>
    <div class="transfer-add">
      <input id="tc-name" type="text" placeholder="Name (e.g. Alfredo)" autocomplete="off" />
      <input id="tc-phone" type="tel" placeholder="+1 954 669 6259" autocomplete="off" />
      <button id="tc-add" class="btn btn-primary" type="button">Add contact</button>
    </div>
  </div>
</div>

<div class="page">

<style>
  /* How-found card folded into the widgets grid by JS becomes a full-width row */
  #dash-widgets > .howfound-card { grid-column: 1 / -1; margin: 0; }
  /* Widgets being reordered get a subtle lift */
  #dash-widgets > [data-w].cz-ghost { outline: 1px dashed var(--cyan); outline-offset: 2px; opacity: 0.6; }
  /* Customize modal */
  .cz-hint { font-size: 12px; color: var(--ink-muted); margin: 0 2px 14px; }
  .cz-list { display: flex; flex-direction: column; gap: 8px; }
  .cz-item { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 12px;
    background: var(--surface); border: 1px solid var(--hairline); user-select: none; transition: border-color .15s, transform .12s; }
  .cz-item.dragging { opacity: 0.55; border-color: var(--cyan); box-shadow: 0 0 0 1px var(--cyan), 0 10px 24px -10px var(--cyan-glow); }
  .cz-item.over { border-color: var(--cyan); transform: translateY(2px); }
  .cz-handle { cursor: grab; color: var(--ink-dim); display: flex; align-items: center; touch-action: none; padding: 4px; margin: -4px; }
  .cz-handle:active { cursor: grabbing; color: var(--cyan); }
  .cz-name { flex: 1; font-size: 14px; font-weight: 600; color: var(--ink); }
  .cz-item.hidden-w .cz-name { color: var(--ink-dim); text-decoration: line-through; }
  .cz-eye { background: var(--surface-soft); border: 1px solid var(--hairline); border-radius: 9px;
    width: 40px; height: 36px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
    color: var(--ink-muted); flex-shrink: 0; }
  .cz-eye.on { color: #04090E; border-color: transparent; background: var(--cyan); }
</style>

<div id="notif-modal" class="oncall-overlay">
  <div class="oncall-card">
    <!-- Chat list (inbox) -->
    <div id="chat-listview">
      <div class="oncall-head">
        <div>
          <strong>Messages</strong>
          <div class="oncall-sub">A chat per phone number — all alerts grouped by caller.</div>
        </div>
        <button id="notif-close" class="oncall-close" type="button" aria-label="Close">×</button>
      </div>
      <div id="chat-list" class="chat-list"></div>
      <div class="oncall-actions">
        <button id="notif-clear" class="oncall-btn oncall-btn-secondary" type="button">Clear all</button>
      </div>
    </div>
    <!-- One conversation -->
    <div id="chat-threadview" style="display:none;">
      <div class="oncall-head chat-thread-head">
        <button id="chat-back" class="chat-back" type="button" aria-label="Back">‹</button>
        <div class="chat-avatar chat-head-avatar" id="chat-peer-avatar"></div>
        <div style="flex:1; min-width:0;">
          <strong id="chat-peer-name"></strong>
          <div class="oncall-sub" id="chat-peer-sub"></div>
        </div>
        <button id="chat-close" class="oncall-close" type="button" aria-label="Close">×</button>
      </div>
      <div id="chat-thread" class="chat-thread"></div>
    </div>
  </div>
</div>

<div id="customize-modal" class="oncall-overlay">
  <div class="oncall-card">
    <div class="oncall-head">
      <div>
        <strong>Customize dashboard</strong>
        <div class="oncall-sub">Drag to reorder, tap the eye to show/hide. Saved on this device.</div>
      </div>
      <button id="customize-close" class="oncall-close" type="button" aria-label="Close">×</button>
    </div>
    <div class="cz-hint">Hidden boxes won't appear on your dashboard.</div>
    <div id="cz-list" class="cz-list"></div>
    <div class="oncall-actions">
      <button id="cz-reset" class="oncall-btn oncall-btn-secondary" type="button">Reset to default</button>
    </div>
  </div>
</div>

<div class="stats" id="dash-widgets">
  <div class="stat">
    <span class="stat-label">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/></svg>
      Active Calls
    </span>
    <div class="stat-row">
      <span class="stat-value accent" id="stat-active">0</span>
      <span class="stat-trail">live now</span>
    </div>
  </div>
  <div class="stat">
    <span class="stat-label">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
      Total Today
    </span>
    <div class="stat-row">
      <span class="stat-value" id="stat-total">0</span>
      <span class="stat-trail">since midnight</span>
    </div>
  </div>
  <div class="stat">
    <span class="stat-label">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
      Need Followup
    </span>
    <div class="stat-row">
      <span class="stat-value warning" id="stat-followup">0</span>
      <span class="stat-trail">to call back</span>
    </div>
  </div>
  <div class="stat">
    <span class="stat-label">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="20 6 9 17 4 12"/></svg>
      Successful
    </span>
    <div class="stat-row">
      <span class="stat-value success" id="stat-success">0</span>
      <span class="stat-trail">resolved</span>
    </div>
  </div>
</div>

<style>
  .howfound-card {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: 14px;
    padding: 20px 22px;
    margin: 0 24px 24px;
    box-shadow: var(--shadow-card);
  }
  .howfound-head {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px;
  }
  .howfound-head h3 {
    font-size: 14px; font-weight: 700; color: var(--ink);
    display: flex; align-items: center; gap: 8px;
  }
  .howfound-total { font-size: 12px; color: var(--ink-muted); font-weight: 500; }
  .howfound-bars { display: flex; flex-direction: column; gap: 10px; }
  .howfound-row { display: grid; grid-template-columns: 130px 1fr 50px; align-items: center; gap: 12px; }
  .howfound-label { font-size: 12px; font-weight: 600; color: var(--ink-soft); text-transform: capitalize; }
  .howfound-bar-track { height: 8px; background: var(--surface-soft); border-radius: 4px; overflow: hidden; }
  .howfound-bar-fill {
    height: 100%; border-radius: 4px;
    background: linear-gradient(90deg, var(--brand-red) 0%, var(--brand-red-warm) 100%);
    transition: width 0.4s ease;
  }
  .howfound-count { font-size: 12px; font-weight: 600; color: var(--ink); text-align: right; }
  .howfound-empty { padding: 20px; text-align: center; color: var(--ink-muted); font-size: 13px; }
  @media (max-width: 720px) {
    .howfound-card { margin: 0 16px 16px; }
    .howfound-row { grid-template-columns: 100px 1fr 40px; }
  }
</style>
<div class="howfound-card">
  <div class="howfound-head">
    <h3>
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
      How Customers Found Us
    </h3>
    <span class="howfound-total" id="howfound-total">0 responses</span>
  </div>
  <div id="howfound-bars" class="howfound-bars">
    <div class="howfound-empty">No data yet — answers will appear here as calls come in.</div>
  </div>
</div>

<div class="container">
  <div class="panel calls-panel">
    <div class="panel-header">
      <span class="panel-title">
        <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/></svg>
        Recent Calls
      </span>
      <span class="panel-count" id="calls-count">0</span>
    </div>
    <div class="panel-search">
      <div class="panel-search-wrap">
        <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="11" cy="11" r="7"/><line x1="20" y1="20" x2="16.65" y2="16.65"/></svg>
        <input id="calls-search" placeholder="Search by phone or outcome…" autocomplete="off" />
      </div>
    </div>
    <div class="calls-list" id="calls-list">
      <div class="empty-state">
        <div class="empty-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/></svg></div>
        <div class="empty-title">Waiting for calls</div>
        <div class="empty-subtitle">Live calls will appear here when customers ring in</div>
      </div>
    </div>
  </div>
  <div class="panel detail-panel">
    <button class="detail-back" type="button" onclick="closeDetail()"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg>Back to calls</button>
    <div class="detail-header" id="detail-header" style="display: none;">
      <div class="detail-title">
        <h2 id="detail-from">—</h2>
        <div class="meta" id="detail-meta">—</div>
      </div>
      <div class="actions">
        <a id="btn-takeover" class="btn btn-primary" href="#"></a>
        <button id="btn-end" class="btn btn-danger">End AI Call</button>
      </div>
    </div>
    <div class="detail-content" id="detail-content">
      <div class="empty-state">
        <div class="empty-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div>
        <div class="empty-title">No call selected</div>
        <div class="empty-subtitle">Pick a call from the left to see the transcript and AI summary</div>
      </div>
    </div>
  </div>
</div>

  <div class="m-tools-label">Quick actions</div>
  <div class="m-insights-only settings-row">
    <button class="settings-item" type="button" onclick="document.getElementById('alerts-btn').click()"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>Alerts</button>
    <button class="settings-item" type="button" onclick="document.getElementById('analytics-link').click()"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg>Analytics</button>
    <button class="settings-item" type="button" onclick="openCustomize()"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>Customize</button>
    <button class="settings-item" type="button" onclick="document.getElementById('reset-btn').click()"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>Reset</button>
  </div>
</div>{# /page #}

<nav class="bottom-tabs" role="tablist">
  <button class="tab-btn" id="tab-calls" type="button" onclick="setTab('calls')" role="tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/></svg><span class="tab-badge" id="calls-badge"></span><span>Calls</span></button>
  <button class="tab-btn" id="tab-messages" type="button" onclick="setTab('messages')" role="tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg><span class="tab-badge msg-badge" id="msg-tab-badge"></span><span>Messages</span></button>
  <button class="tab-btn" id="tab-insights" type="button" onclick="setTab('insights')" role="tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg><span>Insights</span></button>
  <button class="tab-btn" id="tab-oncall" type="button" onclick="setTab('oncall')" role="tab"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg><span>On-Call</span></button>
</nav>

<script>
const calls = {};
let selectedCallId = null;
let searchQuery = '';

// ── Inline icon set (Phosphor-style, stroke 1.6). Use the helper below to size them. ──
function iconSvg(body, sizeClass) {
  return `<svg class="${sizeClass || 'icon'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
}
const ICON_BODY = {
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  sparkle: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="3"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  arrowRight: '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
  alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  broadcast: '<path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/>',
  cog: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>',
  bot: '<rect x="4" y="7" width="16" height="12" rx="3"/><line x1="12" y1="3" x2="12" y2="7"/><circle cx="9" cy="13" r="1"/><circle cx="15" cy="13" r="1"/><line x1="2" y1="13" x2="4" y2="13"/><line x1="20" y1="13" x2="22" y2="13"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  bellOff: '<path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M18.63 13A17.89 17.89 0 0 1 18 8"/><path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/><path d="M18 8a6 6 0 0 0-9.33-5"/><line x1="1" y1="1" x2="23" y2="23"/>',
  hangup: '<path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2A19.79 19.79 0 0 1 11.13 19a19.5 19.5 0 0 1-3.07-8.63 2 2 0 0 1 2-2.18h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11Z"/><line x1="23" y1="1" x2="1" y2="23"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
};
// Pre-rendered icons at .icon (16) and .icon-sm (14). Use ICON.x for normal slots, ICON_SM.x for compact.
const ICON = Object.fromEntries(Object.entries(ICON_BODY).map(([k,v]) => [k, iconSvg(v, 'icon')]));
const ICON_SM = Object.fromEntries(Object.entries(ICON_BODY).map(([k,v]) => [k, iconSvg(v, 'icon-sm')]));
const ICON_XS = Object.fromEntries(Object.entries(ICON_BODY).map(([k,v]) => [k, iconSvg(v, 'icon-xs')]));

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  } catch { return ''; }
}

function fmtDuration(ms) {
  if (!ms) return '';
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
}

function fmtPhone(p) {
  if (!p) return 'Unknown';
  const digits = String(p).replace(/\\D/g, '');
  if (digits.length === 11 && digits.startsWith('1')) {
    return `(${digits.slice(1,4)}) ${digits.slice(4,7)}-${digits.slice(7)}`;
  }
  if (digits.length === 10) {
    return `(${digits.slice(0,3)}) ${digits.slice(3,6)}-${digits.slice(6)}`;
  }
  return p;
}

// Priority tier for a call — drives both the status-badge color and the row's
// left-accent. Matches the header legend: high=red, attention=yellow, good=green,
// check(worth a look)=blue, live=in progress, neutral=not analyzed yet.
function callTier(c) {
  if (c.state === 'active') return 'live';
  const a = c.analysis || {};
  const cad = a.custom_analysis_data || {};
  const outcome = (cad.outcome || '').toUpperCase();
  const priority = (cad.priority || '').toUpperCase();
  const followup = cad.should_followup === true || cad.should_followup === 'true';
  const incomplete = cad.incomplete_call === true || cad.incomplete_call === 'true';
  if (!outcome && !priority && !a.call_summary) return 'neutral';
  if (priority === 'HIGH' || outcome.indexOf('EMERGENCY') >= 0 || outcome === 'MISSED' || outcome === 'FAILED') return 'high';
  if (followup || incomplete || priority === 'MEDIUM' || outcome.indexOf('CALLBACK') >= 0) return 'attention';
  if (outcome.indexOf('TRANSFER') >= 0) return 'check';
  return 'good';
}
function outcomeLabel(c, tier) {
  const cad = (c.analysis && c.analysis.custom_analysis_data) || {};
  const outcome = (cad.outcome || '').toUpperCase();
  const followup = cad.should_followup === true || cad.should_followup === 'true';
  const incomplete = cad.incomplete_call === true || cad.incomplete_call === 'true';
  if (outcome.indexOf('EMERGENCY') >= 0) return 'Emergency';
  if (outcome === 'MISSED') return 'Missed';
  if (outcome === 'FAILED') return 'Failed';
  if (outcome.indexOf('CALLBACK') >= 0) return 'Callback';
  if (followup) return tier === 'high' ? 'Urgent follow-up' : 'Needs follow-up';
  if (incomplete) return 'Incomplete info';
  if (outcome.indexOf('TRANSFER') >= 0) return 'Transferred';
  if (outcome === 'SCHEDULED') return 'Scheduled';
  if (outcome === 'RESOLVED') return 'Resolved';
  if (outcome.indexOf('INFO') >= 0) return 'Info';
  return c.state === 'ended' ? 'Ended' : (c.state || 'Unknown');
}
function getOutcomeBadge(c) {
  if (c.state === 'active') return '<span class="badge badge-active"><span class="live-pulse"></span>LIVE</span>';
  const tier = callTier(c);
  const label = outcomeLabel(c, tier);
  if (tier === 'neutral') return '<span class="badge badge-ended">' + label + '</span>';
  const cls = { high: 'badge-p-high', attention: 'badge-p-attention', good: 'badge-p-good', check: 'badge-p-check' }[tier];
  return '<span class="badge ' + cls + '">' + label + '</span>';
}

function updateStats() {
  const list = Object.values(calls);
  const today = new Date().toDateString();
  const active = list.filter(c => c.state === 'active').length;
  const todays = list.filter(c => {
    if (!c.started_at) return false;
    return new Date(c.started_at).toDateString() === today;
  });
  const followup = todays.filter(c => {
    const cad = (c.analysis && c.analysis.custom_analysis_data) || {};
    return cad.should_followup === true || cad.should_followup === 'true';
  }).length;
  const successful = todays.filter(c => {
    const a = c.analysis || {};
    return a.call_successful === true || a.call_successful === 'true';
  }).length;

  document.getElementById('stat-active').textContent = active;
  document.getElementById('stat-total').textContent = todays.length;
  document.getElementById('stat-followup').textContent = followup;
  document.getElementById('stat-success').textContent = successful;

  // Live-call badge on the Calls bottom tab — answers "is a call happening right now?" at a glance
  const badge = document.getElementById('calls-badge');
  if (badge) { badge.textContent = active; badge.classList.toggle('show', active > 0); }

  renderHowFoundChart();
}

const SOURCE_LABELS = {
  GOOGLE: 'Google',
  FACEBOOK: 'Facebook',
  YELP: 'Yelp',
  INSTAGRAM: 'Instagram',
  TIKTOK: 'TikTok',
  REFERRAL: 'Referral',
  WEBSITE: 'Website',
  RETURNING_CUSTOMER: 'Returning Customer',
  OTHER: 'Other',
};

function renderHowFoundChart() {
  const counts = {};
  let total = 0;
  Object.values(calls).forEach(c => {
    const a = c.analysis || {};
    const cad = a.custom_analysis_data || {};
    const src = (cad.how_found || '').toUpperCase().trim();
    if (!src || src === 'NOT_ASKED') return;
    counts[src] = (counts[src] || 0) + 1;
    total++;
  });

  const totalEl = document.getElementById('howfound-total');
  const barsEl = document.getElementById('howfound-bars');
  if (!barsEl || !totalEl) return;

  totalEl.textContent = total + (total === 1 ? ' response' : ' responses');

  if (total === 0) {
    barsEl.innerHTML = '<div class="howfound-empty">No data yet — answers will appear here as calls come in.</div>';
    return;
  }

  const items = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = items[0][1];
  barsEl.innerHTML = items.map(([src, n]) => {
    const label = SOURCE_LABELS[src] || src.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
    const pct = max > 0 ? Math.round((n / max) * 100) : 0;
    return `<div class="howfound-row">
      <div class="howfound-label">${escapeHtml(label)}</div>
      <div class="howfound-bar-track"><div class="howfound-bar-fill" style="width: ${pct}%;"></div></div>
      <div class="howfound-count">${n}</div>
    </div>`;
  }).join('');
}

function matchesSearch(c) {
  if (!searchQuery) return true;
  const q = searchQuery.toLowerCase();
  const phone = (c.from_number || '').toLowerCase();
  const a = c.analysis || {};
  const cad = a.custom_analysis_data || {};
  const haystack = [
    phone, fmtPhone(c.from_number),
    cad.outcome, c.state,
    a.call_summary, cad.followup_reason,
  ].filter(Boolean).join(' ').toLowerCase();
  return haystack.includes(q);
}

function renderCallItem(id, i) {
  const c = calls[id];
  const sel = id === selectedCallId ? ' selected' : '';
  const live = c.state === 'active' ? ' live' : '';
  return `<div class="call-item${sel}${live} tier-${callTier(c)}" style="--i:${i}" onclick="selectCall('${id}')">
    <div class="call-item-header">
      <div class="call-from">${fmtPhone(c.from_number)}</div>
      <div class="call-time">${fmtTime(c.started_at)}</div>
    </div>
    <div class="call-meta">
      ${getOutcomeBadge(c)}
      ${c.duration_ms ? `<span class="badge badge-ended">${fmtDuration(c.duration_ms)}</span>` : ''}
    </div>
  </div>`;
}

function renderCallsList() {
  const list = document.getElementById('calls-list');
  const allIds = Object.keys(calls).sort((a, b) => (calls[b].started_at || '').localeCompare(calls[a].started_at || ''));
  const visible = allIds.filter(id => matchesSearch(calls[id]));
  document.getElementById('calls-count').textContent = allIds.length;

  if (allIds.length === 0) {
    list.innerHTML = `<div class="empty-state">
      <div class="empty-icon">${ICON.phone}</div>
      <div class="empty-title">Waiting for calls</div>
      <div class="empty-subtitle">Live calls will appear here when customers ring in</div>
    </div>`;
    return;
  }

  if (visible.length === 0) {
    list.innerHTML = `<div class="empty-state">
      <div class="empty-icon">${ICON.chat}</div>
      <div class="empty-title">No matches</div>
      <div class="empty-subtitle">Try a different phone number or outcome</div>
    </div>`;
    return;
  }

  const activeIds = visible.filter(id => calls[id].state === 'active');
  const endedIds  = visible.filter(id => calls[id].state !== 'active');

  let html = '';
  let cursor = 0;

  if (activeIds.length > 0) {
    html += `<div class="call-section section-active">
      <div class="section-header">
        <span class="section-dot"></span>
        <span>Active now</span>
        <span class="section-count">${activeIds.length}</span>
      </div>`;
    html += activeIds.map(id => renderCallItem(id, cursor++)).join('');
    html += `</div>`;
  }

  if (endedIds.length > 0) {
    html += `<div class="call-section section-ended">
      <div class="section-header">
        <span class="section-dot"></span>
        <span>Recent</span>
        <span class="section-count">${endedIds.length}</span>
      </div>`;
    html += endedIds.map(id => renderCallItem(id, cursor++)).join('');
    html += `</div>`;
  }

  list.innerHTML = html;
}

function renderDetail() {
  const header = document.getElementById('detail-header');
  const content = document.getElementById('detail-content');

  if (!selectedCallId || !calls[selectedCallId]) {
    header.style.display = 'none';
    content.innerHTML = `<div class="empty-state">
      <div class="empty-icon">${ICON.chat}</div>
      <div class="empty-title">No call selected</div>
      <div class="empty-subtitle">Pick a call from the left to see the transcript and AI summary</div>
    </div>`;
    return;
  }

  const c = calls[selectedCallId];
  header.style.display = 'flex';

  document.getElementById('detail-from').textContent = fmtPhone(c.from_number);
  const dur = c.duration_ms ? fmtDuration(c.duration_ms) : (c.state === 'active' ? 'In progress' : '');
  document.getElementById('detail-meta').innerHTML =
    `<span>${fmtTime(c.started_at)}</span><span class="meta-dot"></span>` +
    `<span>${dur || '—'}</span><span class="meta-dot"></span>${getOutcomeBadge(c)}`;

  // Buttons
  const phone = c.from_number || '';
  const takeover = document.getElementById('btn-takeover');
  takeover.href = phone ? `tel:${phone}` : '#';
  takeover.innerHTML = phone ? `${ICON.phone}<span>Call ${fmtPhone(phone)}</span>` : `${ICON.phone}<span>No number</span>`;
  const endBtn = document.getElementById('btn-end');
  if (c.state === 'active') {
    endBtn.style.display = '';
    endBtn.disabled = false;
  } else {
    endBtn.style.display = 'none';
  }

  // Build content
  let html = '';

  // Booking card — shown when an HCP appointment was created during this call
  if (c.hcp_job_id || c.booking_summary) {
    const b = c.booking_summary || {};
    const hcpUrl = c.hcp_job_url || (c.hcp_job_id ? `https://pro.housecallpro.com/app/jobs/${c.hcp_job_id}` : '');
    const emergencyTag = b.is_emergency ? '<span class="summary-tag" style="background: rgba(255,84,112,0.15); color: var(--danger);">EMERGENCY</span>' : '';
    html += `<div class="summary-card" style="border-color: var(--accent);">
      <div class="summary-card-header">
        <div class="summary-icon">${ICON.calendar || ICON.sparkle}</div>
        <h3>Appointment Booked</h3>
        ${emergencyTag}
        ${hcpUrl ? `<a href="${escapeHtml(hcpUrl)}" target="_blank" rel="noopener" class="brand-link" style="margin-left: auto; font-size: 12px; font-weight: 600;">Open in Housecall Pro →</a>` : ''}
      </div>
      ${b.customer_name ? `<div class="summary-row"><div class="summary-label">Customer</div><div class="summary-value bold">${escapeHtml(b.customer_name)}</div></div>` : ''}
      ${b.service_type ? `<div class="summary-row"><div class="summary-label">Service</div><div class="summary-value">${escapeHtml(b.service_type)}</div></div>` : ''}
      ${b.date ? `<div class="summary-row"><div class="summary-label">When</div><div class="summary-value">${escapeHtml(b.date)} · ${escapeHtml(b.time_window || '')}</div></div>` : ''}
      ${b.address ? `<div class="summary-row"><div class="summary-label">Address</div><div class="summary-value">${escapeHtml(b.address)}</div></div>` : ''}
      ${b.tech ? `<div class="summary-row"><div class="summary-label">Assigned Tech</div><div class="summary-value">${escapeHtml(b.tech)}</div></div>` : ''}
      ${c.hcp_job_id ? `<div class="summary-row"><div class="summary-label">Job ID</div><div class="summary-value" style="font-family: monospace; font-size: 11px;">${escapeHtml(c.hcp_job_id)}</div></div>` : ''}
    </div>`;
  }

  // AI Summary card (only if analysis is available)
  if (c.analysis) {
    const a = c.analysis;
    const cad = a.custom_analysis_data || {};
    const followup = cad.should_followup === true || cad.should_followup === 'true';
    const priority = cad.priority || '';

    let bannerCls = 'success';
    let bannerIcon = ICON.check;
    let bannerTitle = 'No followup needed';
    let bannerSub = cad.followup_reason || 'Call completed successfully';

    if (followup) {
      if (priority === 'HIGH') { bannerCls = 'danger'; bannerIcon = ICON.alert; bannerTitle = 'High priority follow-up'; }
      else { bannerCls = ''; bannerIcon = ICON.phone; bannerTitle = 'Follow-up needed'; }
      bannerSub = cad.followup_reason || 'The team should reach out to this caller';
    }

    html += `<div class="followup-banner ${bannerCls}">
      <div class="followup-icon">${bannerIcon}</div>
      <div class="followup-text">
        <strong>${escapeHtml(bannerTitle)}</strong>
        <span>${escapeHtml(bannerSub)}</span>
      </div>
    </div>`;

    html += `<div class="summary-card">
      <div class="summary-card-header">
        <div class="summary-icon">${ICON.sparkle}</div>
        <h3>AI Call Summary</h3>
        <span class="summary-tag">Generated by <a class="brand-link" href="https://manyfai.com" target="_blank" rel="noopener">ManyFai</a></span>
      </div>`;

    if (a.call_summary) {
      html += `<div class="summary-row">
        <div class="summary-label">Summary</div>
        <div class="summary-value">${escapeHtml(a.call_summary)}</div>
      </div>`;
    }
    if (cad.outcome) {
      html += `<div class="summary-row">
        <div class="summary-label">Outcome</div>
        <div class="summary-value bold">${escapeHtml(cad.outcome)}</div>
      </div>`;
    }
    if (a.user_sentiment) {
      html += `<div class="summary-row">
        <div class="summary-label">Sentiment</div>
        <div class="summary-value">${escapeHtml(a.user_sentiment)}</div>
      </div>`;
    }
    if (priority && priority !== 'NONE') {
      html += `<div class="summary-row">
        <div class="summary-label">Priority</div>
        <div class="summary-value bold">${escapeHtml(priority)}</div>
      </div>`;
    }
    html += `</div>`;
  } else if (c.state === 'ended') {
    html += `<div class="summary-skeleton">
      <div class="summary-card-header" style="margin-bottom:6px;">
        <div class="summary-icon">${ICON.sparkle}</div>
        <h3>Generating AI summary…</h3>
        <span class="summary-tag">5–15 seconds</span>
      </div>
      <div class="skeleton-bar" style="width: 92%;"></div>
      <div class="skeleton-bar" style="width: 78%;"></div>
      <div class="skeleton-bar" style="width: 64%;"></div>
    </div>`;
  }

  // Transcript
  const tHeading = c.state === 'active'
    ? `${ICON.broadcast} Live Transcript`
    : `${ICON.chat} Transcript`;
  html += `<div class="transcript-section">
    <h3>${tHeading}</h3>
    <div class="transcript" id="transcript-turns"></div>
  </div>`;

  content.innerHTML = html;

  // Render transcript turns
  const turnsEl = document.getElementById('transcript-turns');
  const turns = c.transcript || [];
  if (turns.length === 0) {
    turnsEl.innerHTML = `<div class="empty-state" style="padding: 30px; min-height: 0;">
      <div class="empty-icon">${ICON.clock}</div>
      <div class="empty-subtitle">${c.state === 'active' ? 'Waiting for conversation to start…' : 'No transcript available'}</div>
    </div>`;
    return;
  }

  turnsEl.innerHTML = turns.map(turn => {
    const role = (turn.role || '').toLowerCase();
    const content = turn.content || turn.transcript || '';
    if (role === 'agent') {
      return `<div class="turn turn-agent">
        <div class="turn-role">${ICON.bot}<span>Sarah · AI</span></div>
        ${escapeHtml(content)}
      </div>`;
    } else if (role === 'user') {
      return `<div class="turn turn-user">
        <div class="turn-role">${ICON.user}<span>Caller</span></div>
        ${escapeHtml(content)}
      </div>`;
    } else if (role === 'tool_call_invocation') {
      const name = turn.name || 'tool';
      return `<div class="turn turn-tool">${ICON.cog}<span>${escapeHtml(name)}</span></div>`;
    } else if (role === 'tool_call_result') {
      return `<div class="turn turn-tool">${ICON.check}<span>tool result</span></div>`;
    } else {
      return `<div class="turn turn-tool">${escapeHtml(role || 'system')}</div>`;
    }
  }).join('');

  // Auto-scroll to bottom for live calls
  if (c.state === 'active') {
    document.getElementById('detail-content').scrollTop = document.getElementById('detail-content').scrollHeight;
  }
}

function selectCall(id) {
  selectedCallId = id;
  renderCallsList();
  renderDetail();
  if (window.matchMedia('(max-width: 720px)').matches) {
    document.body.classList.add('detail-open');
    const dp = document.querySelector('.detail-panel');
    if (dp) dp.scrollTop = 0;
  }
}

// ---- Mobile tab navigation (bottom bar) ----
function setTab(name) {
  document.body.classList.remove('detail-open');  // never leave the page scroll-locked when switching tabs
  document.body.classList.remove('m-calls', 'm-insights', 'm-oncall', 'm-messages');
  document.body.classList.add('m-' + name);
  ['calls', 'insights', 'oncall', 'messages'].forEach(t => {
    const b = document.getElementById('tab-' + t);
    if (b) b.classList.toggle('active', t === name);
  });
  // On-Call is its own page on mobile: load the schedule + transfer contacts inline (no popup)
  if (name === 'oncall') {
    if (typeof loadOncallData === 'function') loadOncallData();
    if (typeof loadTransfer === 'function') loadTransfer();
  }
  // Messages is its own full-screen page on mobile: always land on the inbox, fresh
  if (name === 'messages') {
    currentChatKey = null;
    if (typeof showThreadView === 'function') showThreadView(false);
    if (typeof loadMessages === 'function') loadMessages();
    else if (typeof renderChatList === 'function') renderChatList();
  }
  window.scrollTo(0, 0);
}
function closeDetail() { document.body.classList.remove('detail-open'); }
// Default to the Calls tab on load
document.body.classList.add('m-calls');
document.getElementById('tab-calls')?.classList.add('active');

// ---- Transfer contacts ----
let transferData = { contacts: [], alfredo_id: null, human_id: null, emergency_id: null, env_fallback: {} };
function _tkey() { return new URLSearchParams(location.search).get('key') || ''; }
async function openTransfer() {
  await loadTransfer();
  document.getElementById('transfer-modal').classList.add('open');
}
async function loadTransfer() {
  try {
    const r = await fetch('/api/transfer-contacts?key=' + encodeURIComponent(_tkey()));
    if (!r.ok) throw new Error('HTTP ' + r.status);
    transferData = await r.json();
  } catch (e) {
    showToast({ kind: 'error', title: 'Could not load transfer contacts', subtitle: 'Check your connection and reopen.' });
  }
  renderTransfer();
}
function _tLabel(id) {
  const c = (transferData.contacts || []).find(x => x.id === id);
  return c ? (escapeHtml(c.name) + ' · ' + escapeHtml(c.phone)) : null;
}
function renderTransfer() {
  const t = transferData, fb = t.env_fallback || {};
  document.getElementById('transfer-targets').innerHTML =
    `<div class="ttarget"><span>Talk to Alfredo</span><b>${_tLabel(t.alfredo_id) || 'Default · ' + escapeHtml(fb.alfredo || '')}</b></div>` +
    `<div class="ttarget"><span>Talk to someone</span><b>${_tLabel(t.human_id) || 'Default · ' + escapeHtml(fb.human || '')}</b></div>` +
    `<div class="ttarget"><span>Emergency / on-call</span><b>${_tLabel(t.emergency_id) || 'Default · ' + escapeHtml(fb.emergency || '')}</b></div>`;
  const list = document.getElementById('transfer-list');
  list.innerHTML = (t.contacts && t.contacts.length) ? t.contacts.map(c => `
    <div class="tcontact">
      <div class="tcontact-info"><b>${escapeHtml(c.name)}</b><span>${escapeHtml(c.phone)}</span></div>
      <div class="tcontact-actions">
        <button class="${t.alfredo_id === c.id ? 'on' : ''}" onclick="assignTransfer('alfredo','${c.id}')">Alfredo</button>
        <button class="${t.human_id === c.id ? 'on' : ''}" onclick="assignTransfer('human','${c.id}')">General</button>
        <button class="${t.emergency_id === c.id ? 'on' : ''}" onclick="assignTransfer('emergency','${c.id}')">Emergency</button>
        <button class="tdel" title="Delete" onclick="deleteTransfer('${c.id}')">✕</button>
      </div>
    </div>`).join('') : '<div class="howfound-empty">No contacts yet — add one below.</div>';
}
async function addTransferContact() {
  const name = document.getElementById('tc-name').value.trim();
  const phone = document.getElementById('tc-phone').value.trim();
  if (!name || !phone) { alert('Enter a name and a phone number.'); return; }
  await fetch('/api/transfer-contacts?key=' + encodeURIComponent(_tkey()), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, phone }) });
  document.getElementById('tc-name').value = '';
  document.getElementById('tc-phone').value = '';
  await loadTransfer();
}
async function assignTransfer(role, id) {
  const cur = transferData[role + '_id'];
  await fetch('/api/transfer-contacts/assign?key=' + encodeURIComponent(_tkey()), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role, id: cur === id ? null : id }) });
  await loadTransfer();
}
async function deleteTransfer(id) {
  if (!confirm('Delete this contact?')) return;
  await fetch('/api/transfer-contacts/' + id + '?key=' + encodeURIComponent(_tkey()), { method: 'DELETE' });
  await loadTransfer();
}
document.getElementById('tc-add')?.addEventListener('click', addTransferContact);
document.getElementById('transfer-close')?.addEventListener('click', () => document.getElementById('transfer-modal').classList.remove('open'));
document.getElementById('transfer-modal')?.addEventListener('click', e => { if (e.target.id === 'transfer-modal') document.getElementById('transfer-modal').classList.remove('open'); });
document.getElementById('transfer-btn')?.addEventListener('click', openTransfer);

// ---- Customizable dashboard layout (show/hide + reorder, saved per-device) ----
const CZ_KEY = 'htac_dash_layout_v1';
const CZ_WIDGETS = [
  { id: 'active',   name: 'Active Calls' },
  { id: 'total',    name: 'Total Today' },
  { id: 'followup', name: 'Need Followup' },
  { id: 'success',  name: 'Successful' },
  { id: 'howfound', name: 'How Customers Found Us' },
];
function _czEl(id) {
  if (id === 'howfound') return document.querySelector('.howfound-card');
  const map = { active: 'stat-active', total: 'stat-total', followup: 'stat-followup', success: 'stat-success' };
  const v = document.getElementById(map[id]);
  return v ? v.closest('.stat') : null;
}
let czLayout = { order: CZ_WIDGETS.map(w => w.id), hidden: [] };
function czLoad() {
  try {
    const s = JSON.parse(localStorage.getItem(CZ_KEY) || 'null');
    if (s && Array.isArray(s.order)) {
      const known = CZ_WIDGETS.map(w => w.id);
      const order = s.order.filter(id => known.includes(id));
      known.forEach(id => { if (!order.includes(id)) order.push(id); });
      czLayout = { order, hidden: (s.hidden || []).filter(id => known.includes(id)) };
    }
  } catch (e) {}
}
function czApply() {
  const grid = document.getElementById('dash-widgets');
  const hf = document.querySelector('.howfound-card');
  if (grid && hf && hf.parentElement !== grid) grid.appendChild(hf);  // fold how-found into the one orderable grid
  czLayout.order.forEach((id, i) => {
    const el = _czEl(id);
    if (!el) return;
    el.style.order = i;
    el.style.display = czLayout.hidden.includes(id) ? 'none' : '';
  });
}
function czSave() { try { localStorage.setItem(CZ_KEY, JSON.stringify(czLayout)); } catch (e) {} }
function openCustomize() { czRenderList(); document.getElementById('customize-modal').classList.add('open'); }
function czRenderList() {
  const eyeOpen = '<svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
  const eyeOff = '<svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
  const dots = '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.4"/><circle cx="9" cy="12" r="1.4"/><circle cx="9" cy="18" r="1.4"/><circle cx="15" cy="6" r="1.4"/><circle cx="15" cy="12" r="1.4"/><circle cx="15" cy="18" r="1.4"/></svg>';
  document.getElementById('cz-list').innerHTML = czLayout.order.map(id => {
    const w = CZ_WIDGETS.find(x => x.id === id); if (!w) return '';
    const hidden = czLayout.hidden.includes(id);
    return `<div class="cz-item${hidden ? ' hidden-w' : ''}" draggable="true" data-cz="${id}">
      <span class="cz-handle" title="Drag to reorder">${dots}</span>
      <span class="cz-name">${escapeHtml(w.name)}</span>
      <button class="cz-eye${hidden ? '' : ' on'}" type="button" title="${hidden ? 'Show' : 'Hide'}" onclick="czToggle('${id}')">${hidden ? eyeOff : eyeOpen}</button>
    </div>`;
  }).join('');
  czWireDrag();
}
function czToggle(id) {
  const i = czLayout.hidden.indexOf(id);
  if (i >= 0) czLayout.hidden.splice(i, 1); else czLayout.hidden.push(id);
  czSave(); czApply(); czRenderList();
}
function czReorder(fromId, toId) {
  if (!fromId || fromId === toId) return;
  const o = czLayout.order;
  o.splice(o.indexOf(fromId), 1);
  o.splice(o.indexOf(toId), 0, fromId);
  czSave(); czApply(); czRenderList();
}
let czDragId = null;
function czWireDrag() {
  document.querySelectorAll('#cz-list .cz-item').forEach(it => {
    it.addEventListener('dragstart', e => { czDragId = it.dataset.cz; it.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; });
    it.addEventListener('dragend', () => { it.classList.remove('dragging'); document.querySelectorAll('.cz-item.over').forEach(x => x.classList.remove('over')); });
    it.addEventListener('dragover', e => { e.preventDefault(); it.classList.add('over'); });
    it.addEventListener('dragleave', () => it.classList.remove('over'));
    it.addEventListener('drop', e => { e.preventDefault(); it.classList.remove('over'); czReorder(czDragId, it.dataset.cz); });
    it.querySelector('.cz-handle').addEventListener('pointerdown', e => czPointerDrag(e, it));
  });
}
function czPointerDrag(e, item) {
  if (e.pointerType === 'mouse') return;  // mouse uses native HTML5 DnD above
  e.preventDefault();
  const id = item.dataset.cz; item.classList.add('dragging');
  const move = ev => {
    const over = (document.elementFromPoint(ev.clientX, ev.clientY) || {}).closest?.('.cz-item');
    document.querySelectorAll('.cz-item.over').forEach(x => x.classList.remove('over'));
    if (over && over.dataset.cz !== id) over.classList.add('over');
  };
  const up = ev => {
    document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up);
    const over = (document.elementFromPoint(ev.clientX, ev.clientY) || {}).closest?.('.cz-item');
    if (over && over.dataset.cz !== id) czReorder(id, over.dataset.cz);
    else item.classList.remove('dragging');
  };
  document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
}
document.getElementById('customize-btn')?.addEventListener('click', openCustomize);
document.getElementById('customize-close')?.addEventListener('click', () => document.getElementById('customize-modal').classList.remove('open'));
document.getElementById('customize-modal')?.addEventListener('click', e => { if (e.target.id === 'customize-modal') document.getElementById('customize-modal').classList.remove('open'); });
document.getElementById('cz-reset')?.addEventListener('click', () => { czLayout = { order: CZ_WIDGETS.map(w => w.id), hidden: [] }; czSave(); czApply(); czRenderList(); });
czLoad(); czApply();

document.getElementById('btn-end').addEventListener('click', async () => {
  if (!selectedCallId) return;
  if (!confirm('End this AI call now? The customer will be disconnected.')) return;
  const r = await fetch(`/api/end-call/${selectedCallId}?key=` + encodeURIComponent(_tkey()), { method: 'POST' });
  const j = await r.json();
  if (!j.ok) alert('Failed to end call: ' + (j.error || j.status_code));
});

// Initial button icon
document.getElementById('btn-takeover').innerHTML = `${ICON.phone}<span>Call Customer</span>`;

// Wire the analytics link to preserve the current ?key=
(function () {
  const link = document.getElementById('analytics-link');
  if (!link) return;
  const key = new URLSearchParams(location.search).get('key') || '';
  link.href = '/analytics?key=' + encodeURIComponent(key);
})();

// Search input
const searchEl = document.getElementById('calls-search');
if (searchEl) {
  searchEl.addEventListener('input', (e) => {
    searchQuery = e.target.value.trim();
    renderCallsList();
  });
}

// Live clock (Eastern Time, matches business location)
function tickClock() {
  const el = document.getElementById('clock-text');
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit',
    timeZone: 'America/New_York', timeZoneName: 'short'
  });
}
tickClock(); setInterval(tickClock, 30000);

// ───── NOTIFICATION SYSTEM ─────────────────────────────────────
// In-page toasts + Web Audio chime + Browser Notification API.
// Snapshot events are skipped (those are pre-existing calls on first connect).

let snapshotReceived = false;
let audioCtx = null;
function getAudioCtx() {
  if (!audioCtx) {
    try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    catch (e) { audioCtx = null; }
  }
  if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

function playChime(kind) {
  const ctx = getAudioCtx();
  if (!ctx) return;
  const t0 = ctx.currentTime;
  const tone = (freq, start, dur, peak = 0.16) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, t0 + start);
    gain.gain.linearRampToValueAtTime(peak, t0 + start + 0.018);
    gain.gain.exponentialRampToValueAtTime(0.001, t0 + start + dur);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0 + start);
    osc.stop(t0 + start + dur + 0.02);
  };
  if (kind === 'start') {
    // Two-tone ascending — attention-grabbing (G5 → C6)
    tone(784, 0.00, 0.20);
    tone(1047, 0.13, 0.30, 0.18);
  } else if (kind === 'ended') {
    // Soft single descending tone
    tone(523, 0.00, 0.32, 0.10);
  }
}

function showToast({ kind = 'info', title, subtitle = '', icon, duration = 6000 }) {
  const stack = document.getElementById('toast-stack');
  if (!stack) return;
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  el.style.setProperty('--toast-duration', duration + 'ms');
  const ic = icon || (kind === 'start' ? ICON.phone : kind === 'ended' ? ICON.hangup : ICON.bell);
  el.innerHTML = `
    <div class="toast-icon">${ic}</div>
    <div class="toast-text">
      <strong>${escapeHtml(title || '')}</strong>
      ${subtitle ? `<span>${escapeHtml(subtitle)}</span>` : ''}
    </div>
    <button class="toast-dismiss" aria-label="Dismiss">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>`;
  const dismiss = () => {
    el.classList.add('dismissed');
    setTimeout(() => el.remove(), 320);
  };
  el.querySelector('.toast-dismiss').addEventListener('click', (e) => { e.stopPropagation(); dismiss(); });
  el.addEventListener('click', dismiss);
  stack.appendChild(el);
  setTimeout(dismiss, duration);
}

function browserNotify(title, body, tag) {
  if (!('Notification' in window)) return;
  if (Notification.permission !== 'granted') return;
  try {
    const n = new Notification(title, {
      body,
      icon: '{{ logo_data_uri }}',
      badge: '{{ logo_data_uri }}',
      tag: tag || 'hightech-call',
      renotify: true,
    });
    n.onclick = () => { window.focus(); n.close(); };
    setTimeout(() => { try { n.close(); } catch {} }, 8000);
  } catch (e) { /* no-op */ }
}

// "Reset" button — clears all calls from the dashboard
document.getElementById('reset-btn').addEventListener('click', async () => {
  if (!confirm('Clear all calls from the dashboard? This cannot be undone.')) return;
  const dashboardKey = new URLSearchParams(window.location.search).get('key') || '';
  try {
    const r = await fetch('/api/reset?key=' + encodeURIComponent(dashboardKey), { method: 'POST' });
    const j = await r.json();
    if (!j.ok) alert('Reset failed: ' + (j.error || 'unknown'));
  } catch (err) {
    alert('Reset failed: ' + err.message);
  }
});

// ============================================================
// ON-CALL SCHEDULE — PER DAY
// ============================================================
const oncallModal = document.getElementById('oncall-modal');
const oncallBtn = document.getElementById('oncall-btn');
const oncallClose = document.getElementById('oncall-close');
const oncallSave = document.getElementById('oncall-save');
const oncallClearWeek = document.getElementById('oncall-clear-week');
const oncallDaysEl = document.getElementById('oncall-days');
const oncallWeekLabel = document.getElementById('oncall-week-label');
const oncallPrev = document.getElementById('oncall-prev');
const oncallNext = document.getElementById('oncall-next');
const oncallQuickSelect = document.getElementById('oncall-quick-select');
const oncallQuickApply = document.getElementById('oncall-quick-apply');

const ONCALL = {
  techs: [],
  // assignments: { "YYYY-MM-DD": Set([techId, ...]) }
  assignments: {},
  // Server state to detect changes for Save
  serverDates: {},
  // Currently displayed week start (Monday)
  weekStart: null,
};

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function startOfWeek(d) {
  // Monday = start of week
  const dt = new Date(d);
  dt.setHours(0, 0, 0, 0);
  const day = dt.getDay(); // 0 Sun..6 Sat
  const offset = day === 0 ? -6 : 1 - day;
  dt.setDate(dt.getDate() + offset);
  return dt;
}

function fmtDate(d) {
  // YYYY-MM-DD in local time
  return d.getFullYear() + '-' +
         String(d.getMonth() + 1).padStart(2, '0') + '-' +
         String(d.getDate()).padStart(2, '0');
}

function fmtDateLong(d) {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

async function openOncall() {
  oncallModal.classList.add('open');   // desktop overlay; on mobile the page shows it inline
  await loadOncallData();
}
async function loadOncallData() {
  try {
    const r = await fetch('/api/oncall?key=' + encodeURIComponent(_tkey()));
    const j = await r.json();
    ONCALL.techs = j.techs || [];
    ONCALL.serverDates = j.dates || {};
    // Convert server data to local Sets
    ONCALL.assignments = {};
    Object.entries(ONCALL.serverDates).forEach(([d, ids]) => {
      ONCALL.assignments[d] = new Set(ids || []);
    });
    // Set week to today
    const todayStr = j.today;
    const todayDate = new Date(todayStr + 'T12:00:00');
    ONCALL.weekStart = startOfWeek(todayDate);
    // Populate quick select
    oncallQuickSelect.innerHTML = '<option value="">— pick a tech —</option>' +
      ONCALL.techs.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('');
    renderOncallWeek();
  } catch (err) { console.error(err); }
}

function renderOncallWeek() {
  const start = ONCALL.weekStart;
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  oncallWeekLabel.textContent = fmtDateLong(start) + ' – ' + fmtDateLong(end) + ', ' + end.getFullYear();

  const todayStr = fmtDate(new Date());
  const html = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    const dKey = fmtDate(d);
    const assigned = ONCALL.assignments[dKey] || new Set();
    const hasAssigned = assigned.size > 0;
    const isToday = dKey === todayStr;
    const cls = ['oncall-day'];
    if (hasAssigned) cls.push('has-assignments');
    if (isToday) cls.push('is-today');
    html.push(`<div class="${cls.join(' ')}" data-date="${dKey}">
      <div class="oncall-day-header">
        <div class="oncall-day-name">${DAY_NAMES[i]}${isToday ? ' • today' : ''}</div>
        <div class="oncall-day-date">${d.getDate()}</div>
      </div>
      <div class="oncall-day-techs">
        ${ONCALL.techs.map(t => {
          const active = assigned.has(t.id);
          // Show first name only on chip to keep it compact
          const short = (t.name.split(' ')[0] || t.name);
          return `<div class="oncall-tech-chip ${active ? 'active' : ''}" data-date="${dKey}" data-tech="${t.id}" title="${escapeHtml(t.name)}">${escapeHtml(short)}</div>`;
        }).join('')}
      </div>
    </div>`);
  }
  oncallDaysEl.innerHTML = html.join('');

  // Wire chip clicks
  oncallDaysEl.querySelectorAll('.oncall-tech-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const date = chip.dataset.date;
      const tech = chip.dataset.tech;
      if (!ONCALL.assignments[date]) ONCALL.assignments[date] = new Set();
      if (ONCALL.assignments[date].has(tech)) {
        ONCALL.assignments[date].delete(tech);
        if (ONCALL.assignments[date].size === 0) delete ONCALL.assignments[date];
      } else {
        ONCALL.assignments[date].add(tech);
      }
      renderOncallWeek();
    });
  });
}

oncallBtn?.addEventListener('click', openOncall);
oncallClose?.addEventListener('click', () => oncallModal.classList.remove('open'));
oncallModal?.addEventListener('click', e => { if (e.target === oncallModal) oncallModal.classList.remove('open'); });

oncallPrev?.addEventListener('click', () => {
  const d = new Date(ONCALL.weekStart);
  d.setDate(d.getDate() - 7);
  ONCALL.weekStart = d;
  renderOncallWeek();
});
oncallNext?.addEventListener('click', () => {
  const d = new Date(ONCALL.weekStart);
  d.setDate(d.getDate() + 7);
  ONCALL.weekStart = d;
  renderOncallWeek();
});

oncallQuickApply?.addEventListener('click', () => {
  const techId = oncallQuickSelect.value;
  if (!techId) { alert('Pick a tech first.'); return; }
  for (let i = 0; i < 7; i++) {
    const d = new Date(ONCALL.weekStart);
    d.setDate(d.getDate() + i);
    const dKey = fmtDate(d);
    ONCALL.assignments[dKey] = new Set([techId]);
  }
  renderOncallWeek();
});

oncallClearWeek?.addEventListener('click', () => {
  if (!confirm('Clear all on-call assignments for this week?')) return;
  for (let i = 0; i < 7; i++) {
    const d = new Date(ONCALL.weekStart);
    d.setDate(d.getDate() + i);
    delete ONCALL.assignments[fmtDate(d)];
  }
  renderOncallWeek();
});

oncallSave?.addEventListener('click', async () => {
  const dashboardKey = new URLSearchParams(window.location.search).get('key') || '';
  // Build assignments payload — include current week's days (set or empty)
  const payload = {};
  for (let i = 0; i < 7; i++) {
    const d = new Date(ONCALL.weekStart);
    d.setDate(d.getDate() + i);
    const dKey = fmtDate(d);
    const set = ONCALL.assignments[dKey];
    payload[dKey] = set ? Array.from(set) : [];
  }
  // Also include any other dates the user touched (across other weeks)
  Object.keys(ONCALL.assignments).forEach(dKey => {
    if (!(dKey in payload)) payload[dKey] = Array.from(ONCALL.assignments[dKey]);
  });
  try {
    const r = await fetch('/api/oncall', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: dashboardKey, assignments: payload })
    });
    const j = await r.json();
    if (j.ok) {
      oncallModal.classList.remove('open');
    } else {
      alert('Save failed: ' + (j.error || 'unknown'));
    }
  } catch (err) {
    alert('Save failed: ' + err.message);
  }
});

// "Enable alerts" button — requests browser notification permission
const alertsBtn = document.getElementById('alerts-btn');
const alertsLabel = document.getElementById('alerts-label');
function refreshAlertsBtn() {
  if (!('Notification' in window)) {
    alertsBtn.classList.add('denied');
    alertsLabel.textContent = 'Alerts unsupported';
    alertsBtn.disabled = true;
    return;
  }
  const p = Notification.permission;
  alertsBtn.classList.remove('granted', 'denied');
  if (p === 'granted') {
    alertsBtn.classList.add('granted');
    alertsLabel.textContent = 'Alerts on';
  } else if (p === 'denied') {
    alertsBtn.classList.add('denied');
    alertsLabel.textContent = 'Alerts blocked';
  } else {
    alertsLabel.textContent = 'Enable alerts';
  }
}
alertsBtn.addEventListener('click', async () => {
  // Prime the audio context (browser requires a user gesture)
  getAudioCtx();
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    try {
      const r = await Notification.requestPermission();
      refreshAlertsBtn();
      if (r === 'granted') {
        const pushed = await subscribePush();
        showToast({ kind: 'info', title: 'Alerts enabled',
          subtitle: pushed ? 'You\\'ll get a phone banner + chime on every new call' : 'You\\'ll get a chime + in-app alert on every new call',
          duration: 4500 });
        playChime('start');
      }
    } catch {}
  } else if (Notification.permission === 'granted') {
    const pushed = await subscribePush();   // (re)register the push subscription
    showToast({ kind: 'info', title: 'Alerts already on', subtitle: pushed ? 'Phone banners active · test chime' : 'Test chime playing', duration: 3500 });
    playChime('start');
  }
});
refreshAlertsBtn();

// ---- Web Push (iPhone home-screen PWA banners) ----
const VAPID_PUBLIC = '{{ vapid_public_key }}';
function urlB64ToUint8(b64) {
  const pad = '='.repeat((4 - b64.length % 4) % 4);
  const s = (b64 + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(s); const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}
let swReg = null;
async function initServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  try { swReg = await navigator.serviceWorker.register('/sw.js'); }
  catch (e) { console.warn('SW register failed', e); }
}
async function subscribePush() {
  try {
    if (!swReg) await initServiceWorker();
    if (!swReg || !VAPID_PUBLIC || !('PushManager' in window) || Notification.permission !== 'granted') return false;
    let sub = await swReg.pushManager.getSubscription();
    if (!sub) sub = await swReg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8(VAPID_PUBLIC) });
    const r = await fetch('/api/push/subscribe?key=' + encodeURIComponent(_tkey()), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subscription: sub }) });
    return r.ok;
  } catch (e) { console.warn('push subscribe failed', e); return false; }
}
initServiceWorker();
if (Notification.permission === 'granted') subscribePush();   // keep the subscription fresh

// ---- Message Center (WhatsApp-style: a chat thread per phone number) ----
// Messages live on the server (/api/messages); we group them by caller number
// client-side. Same number → same chat; all unknown/blocked → one "Unknown"
// chat. Read state is per-device, tracked by message id in localStorage.
const READ_KEY = 'htac_read_v1';
let notifs = [];
let readIds = {};
let currentChatKey = null;     // which chat the thread view is showing, or null = inbox
let _chatDeepLinked = false;   // so a ?chat= deep-link only auto-opens once
try { readIds = JSON.parse(localStorage.getItem(READ_KEY) || '{}'); } catch (e) {}
function saveRead() { try { localStorage.setItem(READ_KEY, JSON.stringify(readIds)); } catch (e) {} }

function chatKeyOf(m) {
  if (m.peer_key) return m.peer_key;
  const p = m.peer || '';
  if (!p) return 'unknown';
  if (p === 'system') return 'system';
  const d = ('' + p).replace(/[^0-9]/g, '');
  return d || 'unknown';
}
function chatLabel(key, sample) {
  if (key === 'unknown') return 'Unknown / blocked';
  if (key === 'system') return 'System';
  return fmtPhone((sample && sample.peer) || key);
}
function chatAvatar(key) {
  // Identity-based (stable per contact), NOT the last message's icon.
  if (key === 'system') return '🔔';
  if (key === 'unknown') return '👤';
  return '📞';
}
function totalUnread() { return notifs.filter(x => !readIds[x.id]).length; }
function refreshNotifBadge() {
  const n = totalUnread();
  ['notif-badge', 'msg-tab-badge'].forEach(id => {
    const b = document.getElementById(id); if (!b) return;
    b.textContent = n > 9 ? '9+' : n; b.classList.toggle('show', n > 0);
  });
}
function fmtAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return new Date(ts).toLocaleDateString();
}
function fmtClock(ts) {
  // Per-bubble time only; the date lives in the day separator.
  try { return new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
  catch (e) { return ''; }
}
function fmtDay(ts) {
  try {
    const d = new Date(ts), now = new Date();
    if (d.toDateString() === now.toDateString()) return 'Today';
    const y = new Date(now); y.setDate(now.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return 'Yesterday';
    return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
  } catch (e) { return ''; }
}
function groupChats() {
  const map = {};
  notifs.forEach(m => {
    const k = chatKeyOf(m);
    if (!map[k]) map[k] = { key: k, items: [], sample: m };
    map[k].items.push(m);
  });
  const arr = Object.keys(map).map(k => {
    const g = map[k];
    g.items.sort((a, b) => a.ts - b.ts);                 // oldest → newest in a chat
    g.last = g.items[g.items.length - 1];
    g.unread = g.items.filter(x => !readIds[x.id]).length;
    g.label = chatLabel(g.key, g.sample);
    return g;
  });
  arr.sort((a, b) => b.last.ts - a.last.ts);             // most recent chat on top
  return arr;
}
function renderChatList() {
  const list = document.getElementById('chat-list'); if (!list) return;
  const chats = groupChats();
  list.innerHTML = chats.length ? chats.map(g => `
    <div class="chat-row${g.unread ? ' unread' : ''}" onclick="openChat('${g.key}')">
      <div class="chat-avatar">${escapeHtml(chatAvatar(g.key))}</div>
      <div class="chat-row-body">
        <div class="chat-row-top">
          <span class="chat-row-name">${escapeHtml(g.label)}</span>
          <span class="chat-row-time">${fmtAgo(g.last.ts)}</span>
        </div>
        <div class="chat-row-bottom">
          <span class="chat-row-preview"><span class="chat-row-ico">${escapeHtml(g.last.ico || '')}</span>${escapeHtml(g.last.body || g.last.title || '')}</span>
          ${g.unread ? `<span class="chat-row-badge">${g.unread}</span>` : ''}
        </div>
      </div>
    </div>`).join('') : `
    <div class="chat-empty">
      <div class="chat-empty-ico"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg></div>
      <div class="chat-empty-title">No messages yet</div>
      <div class="chat-empty-sub">Call alerts and updates will show up here, grouped into a chat per phone number.</div>
    </div>`;
}
function telHref(p) { const d = ('' + (p || '')).replace(/[^0-9+]/g, ''); return d ? 'tel:' + d : ''; }
function smsHref(p) { const d = ('' + (p || '')).replace(/[^0-9+]/g, ''); return d ? 'sms:' + d : ''; }
function msgField(ico, text) {
  return `<div class="msg-field"><span class="msg-field-ico">${ico}</span><span>${escapeHtml(text)}</span></div>`;
}
function msgActions(m) {
  const x = m.meta || {};
  const phone = x.phone || (m.peer && m.peer !== 'system' ? m.peer : '');
  const b = [];
  if (phone) {
    b.push(`<a class="msg-act" href="${telHref(phone)}">📞 Call</a>`);
    b.push(`<a class="msg-act" href="${smsHref(phone)}">💬 Text</a>`);
  }
  if (x.confirm_text) b.push(`<button class="msg-act" type="button" onclick="copyConfirm('${m.id}')">📋 Copy text</button>`);
  if (x.hcp_url) b.push(`<a class="msg-act" href="${escapeHtml(x.hcp_url)}" target="_blank" rel="noopener">🔧 Housecall Pro</a>`);
  if (x.call_id) b.push(`<button class="msg-act" type="button" onclick="openCallFromMsg('${x.call_id}')">📊 View call</button>`);
  return b.length ? `<div class="msg-actions">${b.join('')}</div>` : '';
}
function renderBubble(m) {
  const x = m.meta || {};
  const time = `<div class="msg-bubble-time">${fmtClock(m.ts)}</div>`;
  if (!x.kind) {
    // Legacy / unstructured message
    return `<div class="msg-bubble">
      <div class="msg-bubble-head"><span class="msg-bubble-ico">${escapeHtml(m.ico || '💬')}</span><span class="msg-bubble-title">${escapeHtml(m.title || '')}</span></div>
      ${m.body ? `<div class="msg-bubble-body">${escapeHtml(m.body)}</div>` : ''}${time}</div>`;
  }
  const phone = x.phone || (m.peer && m.peer !== 'system' ? m.peer : '');
  const kick = `<div class="msg-kicker"><span class="msg-kicker-ico">${escapeHtml(m.ico || '💬')}</span>${escapeHtml((m.title || '').toUpperCase())}</div>`;
  const nameRow = x.name ? `<div class="msg-name">${escapeHtml(x.name)}</div>` : '';
  const phoneRow = phone ? `<a class="msg-phone" href="${telHref(phone)}">${escapeHtml(fmtPhone(phone))}</a>` : '';
  let mid = '';
  if (x.kind === 'ended') {
    if (x.summary) mid += msgField('📋', x.summary);
    if (x.lead_source) mid += msgField('📣', 'Heard via ' + x.lead_source);
    const chips = [];
    if (x.duration) chips.push(`<span class="msg-chip">⏱ ${escapeHtml(x.duration)}</span>`);
    if (x.sentiment) chips.push(`<span class="msg-chip">${escapeHtml(x.sentiment)}</span>`);
    if (chips.length) mid += `<div class="msg-chips">${chips.join('')}</div>`;
    if (x.followup) mid += `<div class="msg-followup">🔔 Follow up${x.followup_reason ? ': ' + escapeHtml(x.followup_reason) : ''}</div>`;
    if (x.booking) {
      const bk = x.booking;
      mid += `<div class="msg-booking">
        <div class="msg-booking-row">🗓 <b>${escapeHtml(bk.service_type || 'Appointment')}</b></div>
        ${[bk.date, bk.time_window].filter(Boolean).length ? `<div class="msg-booking-sub">${escapeHtml([bk.date, bk.time_window].filter(Boolean).join(', '))}</div>` : ''}
        ${bk.tech ? `<div class="msg-booking-sub">Tech: ${escapeHtml(bk.tech)}</div>` : ''}
        ${bk.address ? `<div class="msg-booking-sub">${escapeHtml(bk.address)}</div>` : ''}
      </div>`;
    }
    if (x.confirm_text) mid += `<div class="msg-confirm"><div class="msg-confirm-label">Confirmation text to send</div><div class="msg-confirm-text">${escapeHtml(x.confirm_text)}</div></div>`;
  } else if (x.kind === 'incoming') {
    if (x.time) mid += msgField('🕐', x.time);
  } else if (x.kind === 'emergency') {
    if (x.address) mid += msgField('📍', x.address);
    if (x.problem) mid += msgField('⚠️', x.problem);
    if (x.fee) mid += msgField('💵', 'Fee acknowledged: ' + x.fee);
    if (x.dest_name) mid += msgField('➡️', 'Transferring to ' + x.dest_name + (x.dest_phone ? ' (' + fmtPhone(x.dest_phone) + ')' : ''));
  }
  return `<div class="msg-bubble rich">${kick}${nameRow}${phoneRow}${mid}${msgActions(m)}${time}</div>`;
}
function copyConfirm(id) {
  const m = notifs.find(x => x.id === id); const t = m && m.meta && m.meta.confirm_text;
  if (!t) return;
  const done = () => { if (typeof showToast === 'function') showToast({ kind: 'success', title: 'Copied', subtitle: 'Confirmation text copied to clipboard', duration: 2500 }); };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done).catch(() => msgFallbackCopy(t, done));
  else msgFallbackCopy(t, done);
}
function msgFallbackCopy(t, done) {
  try { const ta = document.createElement('textarea'); ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done && done(); } catch (e) {}
}
function openCallFromMsg(callId) {
  if (!callId) return;
  if (typeof setTab === 'function') setTab('calls');
  if (typeof selectCall === 'function') selectCall(callId);
}
function renderChatThread() {
  const wrap = document.getElementById('chat-thread'); if (!wrap || !currentChatKey) return;
  const items = notifs.filter(m => chatKeyOf(m) === currentChatKey).sort((a, b) => a.ts - b.ts);
  let lastDay = '';
  const rows = items.map(m => {
    const day = fmtDay(m.ts);
    let sep = '';
    if (day && day !== lastDay) { lastDay = day; sep = `<div class="msg-day"><span>${escapeHtml(day)}</span></div>`; }
    return sep + renderBubble(m);
  }).join('');
  wrap.innerHTML = `<div class="msg-start">Beginning of conversation</div>` + rows;
  wrap.scrollTop = wrap.scrollHeight;
}
function markChatRead(key) {
  let changed = false;
  notifs.forEach(m => { if (chatKeyOf(m) === key && m.id && !readIds[m.id]) { readIds[m.id] = 1; changed = true; } });
  if (changed) { saveRead(); refreshNotifBadge(); }
}
function showThreadView(on) {
  document.getElementById('chat-listview').style.display = on ? 'none' : 'flex';
  document.getElementById('chat-threadview').style.display = on ? 'flex' : 'none';
}
function msgIsMobile() { return window.matchMedia('(max-width: 720px)').matches; }
function openMsgOverlay() {
  // On mobile, Messages is a full-screen tab; on desktop it's the bell-triggered overlay.
  if (msgIsMobile()) { if (typeof setTab === 'function') setTab('messages'); return; }
  document.getElementById('notif-modal').classList.add('open');
}
function closeMsgOverlay() { document.getElementById('notif-modal').classList.remove('open'); }
function openChat(key) {
  // Make the Messages section visible FIRST — setTab('messages') resets currentChatKey,
  // so we must assign the key after switching, or renderChatThread() would bail out.
  if (msgIsMobile()) {
    if (!document.body.classList.contains('m-messages') && typeof setTab === 'function') setTab('messages');
  } else {
    document.getElementById('notif-modal').classList.add('open');
  }
  currentChatKey = key;
  const g = groupChats().find(x => x.key === key);
  const cnt = g ? g.items.length : 0;
  document.getElementById('chat-peer-name').textContent = g ? g.label : chatLabel(key, null);
  document.getElementById('chat-peer-sub').textContent = cnt + (cnt === 1 ? ' message' : ' messages');
  const av = document.getElementById('chat-peer-avatar'); if (av) av.textContent = chatAvatar(key);
  showThreadView(true);
  renderChatThread();
  markChatRead(key);
  renderChatList();
}
function backToList() {
  currentChatKey = null;
  showThreadView(false);
  renderChatList();
}
function openNotif() {        // bell + Messages tab → always open the inbox
  currentChatKey = null;
  showThreadView(false);
  renderChatList();
  openMsgOverlay();
}
function msgSectionVisible() {
  // Visible either as the desktop overlay (.open) or the mobile full-screen tab (body.m-messages).
  return document.getElementById('notif-modal').classList.contains('open')
      || document.body.classList.contains('m-messages');
}
function addMessage(item, toFront) {
  if (!item || (item.id && notifs.some(x => x.id === item.id))) return;
  if (toFront) notifs.unshift(item); else notifs.push(item);
  if (notifs.length > 200) notifs = notifs.slice(0, 200);
  const open = msgSectionVisible();
  if (open && currentChatKey && chatKeyOf(item) === currentChatKey) {
    renderChatThread(); markChatRead(currentChatKey);
  } else if (open && !currentChatKey) {
    renderChatList();
  }
  refreshNotifBadge();
}
async function loadMessages() {
  try {
    const r = await fetch('/api/messages?key=' + encodeURIComponent(_tkey()));
    if (!r.ok) return;
    const d = await r.json();
    notifs = d.messages || [];
    refreshNotifBadge();
    if (msgSectionVisible()) {
      if (currentChatKey) renderChatThread(); else renderChatList();
    }
    // Deep-link from a tapped push: ?chat=<key> opens that conversation
    const ck = new URLSearchParams(location.search).get('chat');
    if (ck && !_chatDeepLinked) { _chatDeepLinked = true; openChat(ck); }
  } catch (e) {}
}
document.getElementById('notif-btn')?.addEventListener('click', openNotif);
document.getElementById('notif-close')?.addEventListener('click', closeMsgOverlay);
document.getElementById('chat-close')?.addEventListener('click', closeMsgOverlay);
document.getElementById('chat-back')?.addEventListener('click', backToList);
document.getElementById('notif-modal')?.addEventListener('click', e => { if (e.target.id === 'notif-modal') closeMsgOverlay(); });
document.getElementById('notif-clear')?.addEventListener('click', async () => {
  try { await fetch('/api/messages/clear?key=' + encodeURIComponent(_tkey()), { method: 'POST' }); } catch (e) {}
  notifs = []; readIds = {}; saveRead(); refreshNotifBadge(); backToList();
});
// A tapped push (when the app is already open) asks us to jump to a chat
navigator.serviceWorker?.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'open-chat' && e.data.chat) openChat(e.data.chat);
});
refreshNotifBadge();
loadMessages();

const evt = new EventSource('/stream?key=' + encodeURIComponent(_tkey()));
evt.onmessage = (e) => {
  try {
    const msg = JSON.parse(e.data);
    if (msg.type === 'reset') {
      Object.keys(calls).forEach(k => delete calls[k]);
      selectedCallId = null;
      updateStats();
      renderCallsList();
      renderDetail();
      return;
    }
    if (msg.type === 'message') {
      // Server-pushed alert (same content as Telegram + iPhone push)
      addMessage(msg.data, true);
      return;
    }
    if (msg.type === 'snapshot') {
      msg.data.forEach(c => calls[c.call_id] = c);
      snapshotReceived = true;
    } else if (msg.type === 'call_started') {
      calls[msg.data.call_id] = msg.data;
      if (!selectedCallId) selectedCallId = msg.data.call_id;
      // Notify only for events arriving AFTER the initial snapshot
      if (snapshotReceived) {
        const phone = fmtPhone(msg.data.from_number);
        showToast({
          kind: 'start',
          title: 'New call incoming',
          subtitle: phone,
          duration: 7000,
        });
        playChime('start');
        browserNotify('New call — High Tech AC', `Incoming from ${phone}`, msg.data.call_id);
        // Message center + iPhone push are handled server-side (the 'message' event)
        document.title = '🔔 New call — High Tech AC';
      }
    } else if (msg.type === 'call_ended') {
      const wasActive = calls[msg.data.call_id] && calls[msg.data.call_id].state === 'active';
      calls[msg.data.call_id] = { ...calls[msg.data.call_id], ...msg.data };
      if (snapshotReceived && wasActive) {
        const c = calls[msg.data.call_id];
        const phone = fmtPhone(c.from_number);
        const dur = c.duration_ms ? fmtDuration(c.duration_ms) : '';
        showToast({
          kind: 'ended',
          title: 'Call ended',
          subtitle: dur ? `${phone} · ${dur}` : phone,
          duration: 5000,
        });
        playChime('ended');
        document.title = 'High Tech AC — Call Intelligence';
      }
    } else if (msg.type === 'call_analyzed') {
      // Wrap-up message arrives separately via the server 'message' event
      calls[msg.data.call_id] = { ...calls[msg.data.call_id], ...msg.data };
    } else if (msg.type === 'booking_created') {
      calls[msg.data.call_id] = { ...calls[msg.data.call_id], ...msg.data };
    } else if (msg.type === 'transcript_updated') {
      if (calls[msg.data.call_id]) {
        calls[msg.data.call_id].transcript = msg.data.transcript;
      }
    }
    updateStats();
    renderCallsList();
    if (selectedCallId === (msg.data && msg.data.call_id) || msg.type === 'snapshot') {
      renderDetail();
    }
  } catch (err) { console.error(err); }
};
evt.onerror = () => {
  document.getElementById('status-dot').classList.add('disconnected');
  document.getElementById('status-text').textContent = 'Reconnecting...';
};
evt.onopen = () => {
  document.getElementById('status-dot').classList.remove('disconnected');
  document.getElementById('status-text').textContent = 'Connected';
};

fetch('/api/active-calls?key=' + encodeURIComponent(_tkey())).then(r => r.json()).then(data => {
  data.forEach(c => calls[c.call_id] = c);
  updateStats();
  renderCallsList();
});
</script>
</body>
</html>"""


@app.route("/sw.js", methods=["GET"])
def service_worker():
    """Service worker for Web Push — must be served at root scope, no auth."""
    js = """
self.addEventListener('push', function(event) {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) {}
  const title = d.title || 'High Tech AC';
  event.waitUntil(self.registration.showNotification(title, {
    body: d.body || '', tag: d.tag || 'htac', renotify: true,
    icon: '/app-icon-192.png', badge: '/app-icon-192.png',
    data: { url: d.url || '/dashboard' }
  }));
});
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/dashboard';
  let chat = null;
  try { chat = new URL(url, self.location.origin).searchParams.get('chat'); } catch (e) {}
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(list) {
    for (const c of list) {
      if (c.url.indexOf('/dashboard') >= 0 && 'focus' in c) {
        if (chat) c.postMessage({ type: 'open-chat', chat: chat });
        return c.focus();
      }
    }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
"""
    return Response(js, mimetype="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    sub = (request.json or {}).get("subscription")
    if not sub or not sub.get("endpoint"):
        return jsonify({"ok": False, "error": "missing subscription"}), 400
    subs = load_push_subs()
    if not any(s.get("endpoint") == sub["endpoint"] for s in subs):
        subs.append(sub)
        save_push_subs(subs)
    return jsonify({"ok": True, "count": len(subs)})


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    ep = (request.json or {}).get("endpoint")
    subs = [s for s in load_push_subs() if s.get("endpoint") != ep]
    save_push_subs(subs)
    return jsonify({"ok": True, "count": len(subs)})


@app.route("/api/messages", methods=["GET"])
def api_messages():
    """The dashboard message center — every alert that also went to Telegram."""
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return jsonify({"messages": load_messages()})


@app.route("/api/messages/clear", methods=["POST"])
def api_messages_clear():
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    with _MSG_LOCK:
        save_messages([])
    return jsonify({"ok": True})


@app.route("/api/push/test", methods=["POST"])
def push_test():
    if not _require_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    # Exercise the full loop: message center + Telegram + iPhone push.
    notify_event("🔔", "Test notification",
                 "If you can see this in the Message Center and on your phone, everything works.",
                 "🔔 *Test notification*\nMessage Center + Telegram + iPhone push are connected.",
                 "Markdown", "", "test", peer="system")
    return jsonify({"ok": True, "subscriptions": len(load_push_subs())})


@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Live call monitoring dashboard. Password-protected via ?key= query param."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized — append ?key=YOUR_PASSWORD to the URL", status=401)
    return Response(
        render_template_string(DASHBOARD_HTML, logo_data_uri=LOGO_DATA_URI, dashboard_key=key,
                               vapid_public_key=VAPID_PUBLIC_KEY),
        mimetype="text/html",
    )


def _asset_path(name):
    """Locate a bundled asset whether server.py runs at repo root or inside deploy/."""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.path.join(here, "assets"),
              os.path.join(here, "deploy", "assets"), os.path.join(here, "deploy")):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


@app.route("/app-icon-<int:size>.png")
def app_icon(size):
    """Home-screen / PWA icon (public — not secret)."""
    name = f"app-icon-{size}.png" if size in (192, 512) else "app-icon-512.png"
    p = _asset_path(name)
    if not p:
        return Response(status=404)
    with open(p, "rb") as f:
        data = f.read()
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.route("/manifest.webmanifest")
def manifest():
    """PWA manifest. Gated by the dashboard key so the authenticated start_url
    (which carries the key) is never exposed publicly."""
    if request.args.get("key", "") != DASHBOARD_PASSWORD:
        return Response(status=401)
    return jsonify({
        "name": "High Tech AC — Call Intelligence",
        "short_name": "High Tech AC",
        "description": "Live call monitoring for High Tech Air Conditioning.",
        "start_url": f"/dashboard?key={DASHBOARD_PASSWORD}",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#ffffff",
        "theme_color": "#C4080C",
        "icons": [
            {"src": "/app-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/app-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    })


# ============================================================
# CALL QUALITY ANALYTICS — /analytics
# ============================================================

CATEGORY_LABEL = {
    "success":            "Successful",
    "lost_caller":        "Lost caller",
    "incomplete_info":    "Incomplete info",
    "wrong_routing":      "Wrong routing",
    "hallucination":      "Hallucination",
    "escalation_failure": "Escalation failure",
    "low_quality":        "Low quality",
    "unknown":            "Unknown",
}


def _analytics_payload(days=7, recent_limit=25):
    """Aggregate KPIs + per-category counts + per-day trend + recent reviews."""
    cutoff_iso = (datetime.now(LOCAL_TZ) - timedelta(days=days)).isoformat()
    with _DB_LOCK:
        kpi = db().execute("""
            SELECT
              COUNT(*)                                          AS reviewed,
              ROUND(AVG(success_score), 1)                      AS avg_score,
              SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high_sev,
              SUM(CASE WHEN success_score >= 80 THEN 1 ELSE 0 END) AS passing
              FROM reviews
             WHERE created_at >= ?
        """, (cutoff_iso,)).fetchone()

        cats = db().execute("""
            SELECT category, COUNT(*) AS n
              FROM reviews
             WHERE created_at >= ?
             GROUP BY category
             ORDER BY n DESC
        """, (cutoff_iso,)).fetchall()

        trend = db().execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS n, ROUND(AVG(success_score), 1) AS avg_score
              FROM reviews
             WHERE created_at >= ?
             GROUP BY DATE(created_at)
             ORDER BY day ASC
        """, (cutoff_iso,)).fetchall()

        recent = db().execute("""
            SELECT r.*, c.from_number, c.started_at AS call_started_at, c.duration_ms
              FROM reviews r
              JOIN calls   c ON c.call_id = r.call_id
             ORDER BY r.created_at DESC
             LIMIT ?
        """, (recent_limit,)).fetchall()

        # Lifetime totals (any window) for context
        lifetime = db().execute("SELECT COUNT(*) AS reviewed FROM reviews").fetchone()
        calls_total = db().execute("SELECT COUNT(*) AS total FROM calls").fetchone()

        # Cost ($) over the window
        cost_row = db().execute("""
            SELECT ROUND(SUM(COALESCE(cost_cents, 0)) / 100.0, 2) AS dollars
              FROM reviews
             WHERE created_at >= ?
        """, (cutoff_iso,)).fetchone()

    return {
        "days": days,
        "kpi": dict(kpi) if kpi else {},
        "lifetime_reviewed": (dict(lifetime) or {}).get("reviewed", 0),
        "calls_total":       (dict(calls_total) or {}).get("total", 0),
        "cost_dollars":      (dict(cost_row) or {}).get("dollars", 0) or 0,
        "categories":        [dict(r) for r in cats],
        "trend":             [dict(r) for r in trend],
        "recent":            [dict(r) for r in recent],
    }


@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    days = max(1, min(90, int(request.args.get("days", "7"))))
    return jsonify(_analytics_payload(days=days))


@app.route("/api/review/<call_id>", methods=["GET"])
def api_get_review(call_id):
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    row = db_review_for(call_id)
    if not row:
        return jsonify(None), 404
    return jsonify(db_review_to_dict(row))


@app.route("/api/review/<call_id>/run", methods=["POST"])
def api_run_review(call_id):
    """Manually trigger a review for a specific call (useful for retries)."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    ok = review_one_call(call_id)
    return jsonify({"ok": ok})


# ── Recommendations API ───────────────────────────────────────

@app.route("/api/synth/run", methods=["POST"])
def api_run_synth():
    """Manually trigger a synthesis pass. Useful for testing or after a busy day."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    hours = max(1, min(168, int(request.args.get("hours", "24"))))
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    rec_id = synthesize_window(window_hours=hours, force=force)
    if rec_id is None:
        return jsonify({"ok": False, "reason": "no recommendation produced (check logs — usually <3 reviews or API issue)"}), 200
    return jsonify({"ok": True, "recommendation_id": rec_id})


@app.route("/api/recommendations", methods=["GET"])
def api_list_recommendations():
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    rows = db_list_recommendations(limit=int(request.args.get("limit", "20")))
    for r in rows:
        try: r["top_issues"] = json.loads(r.pop("top_issues_json") or "[]")
        except: r["top_issues"] = []
    return jsonify(rows)


@app.route("/api/recommendations/<int:rec_id>", methods=["GET"])
def api_get_recommendation(rec_id):
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    rec = db_get_recommendation(rec_id)
    if not rec:
        return jsonify(None), 404
    try: rec["top_issues"] = json.loads(rec.pop("top_issues_json") or "[]")
    except: rec["top_issues"] = []
    return jsonify(rec)


@app.route("/api/recommendations/<int:rec_id>/apply", methods=["POST"])
def api_apply_recommendation(rec_id):
    """Push the proposed global_prompt to Retell. Records applied_at on success."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    rec = db_get_recommendation(rec_id)
    if not rec:
        return jsonify({"ok": False, "error": "not found"}), 404
    flow_id, current_prompt, _ = fetch_current_global_prompt()
    if not flow_id:
        return jsonify({"ok": False, "error": "Retell agent / flow unavailable"}), 502
    new_prompt = rec["proposed_prompt"]
    ok, msg = retell_update_global_prompt(flow_id, new_prompt)
    if not ok:
        return jsonify({"ok": False, "error": "Retell update failed", "detail": msg}), 502
    db_mark_applied(rec_id, by="dashboard")
    logger.info(f"[synth] rec#{rec_id} applied to flow {flow_id}")
    return jsonify({"ok": True})


@app.route("/api/recommendations/<int:rec_id>/revert", methods=["POST"])
def api_revert_recommendation(rec_id):
    """Restore the prior_prompt_snapshot on the Retell flow."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    rec = db_get_recommendation(rec_id)
    if not rec:
        return jsonify({"ok": False, "error": "not found"}), 404
    if not rec.get("applied_at"):
        return jsonify({"ok": False, "error": "this recommendation was never applied"}), 400
    flow_id, _, _ = fetch_current_global_prompt()
    if not flow_id:
        return jsonify({"ok": False, "error": "Retell agent / flow unavailable"}), 502
    ok, msg = retell_update_global_prompt(flow_id, rec["prior_prompt_snapshot"])
    if not ok:
        return jsonify({"ok": False, "error": "Retell revert failed", "detail": msg}), 502
    db_mark_reverted(rec_id)
    logger.info(f"[synth] rec#{rec_id} reverted on flow {flow_id}")
    return jsonify({"ok": True})


@app.route("/api/agent/global-prompt", methods=["GET"])
def api_current_global_prompt():
    """Quick utility — returns the live global_prompt. Useful for verifying apply/revert worked."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    flow_id, prompt, version = fetch_current_global_prompt()
    return jsonify({"flow_id": flow_id, "version": version, "global_prompt": prompt})


@app.route("/api/admin/backfill", methods=["POST"])
def api_backfill_recent():
    """Pull the last N calls from Retell, persist + review them.
    Use ?limit=10&review=true. Idempotent — UPSERT on call_id."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized", status=401)
    limit = max(1, min(100, int(request.args.get("limit", "10"))))
    review = request.args.get("review", "true").lower() in ("1", "true", "yes")
    stats = backfill_recent_calls(limit=limit, run_reviews=review)
    return jsonify({"ok": True, **stats})


ANALYTICS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Call Quality Analytics — High Tech AC</title>
<link rel="icon" href="{{ logo_data_uri }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root {
    /* Futuristic dark theme — matches the live dashboard */
    --cyan: #22D3EE;
    --cyan-bright: #67E8F9;
    --cyan-soft: rgba(34, 211, 238, 0.12);
    --brand-red: var(--cyan);
    --brand-red-warm: var(--cyan-bright);
    --brand-red-soft: var(--cyan-soft);
    --brand-blue: var(--cyan);
    --brand-blue-light: var(--cyan-bright);
    --brand-blue-soft: var(--cyan-soft);
    --brand-cream: #0E1620;
    --bg: #05070B;
    --surface: #0C121B;
    --surface-soft: #121C28;
    --hairline: rgba(34, 211, 238, 0.12);
    --hairline-strong: rgba(34, 211, 238, 0.26);
    --ink: #E8F4F8;
    --ink-soft: #B6C8D2;
    --ink-muted: #7C93A0;
    --ink-dim: #51697A;
    --warning: #FBBF24;
    --warning-soft: rgba(251, 191, 36, 0.14);
    --success: #34F5C5;
    --success-soft: rgba(52, 245, 197, 0.13);
    --danger: #FF5063;
    --danger-soft: rgba(255, 80, 99, 0.15);
    --shadow-card: 0 1px 0 rgba(255,255,255,0.03) inset, 0 20px 44px -28px rgba(0,0,0,0.9);
    --shadow-card-hover: 0 0 0 1px var(--hairline-strong), 0 24px 60px -26px rgba(34,211,238,0.22);
    --ease: cubic-bezier(0.16, 1, 0.3, 1);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  html { overflow-x: hidden; }
  body {
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    background-image:
      radial-gradient(900px 520px at 8% -10%, rgba(34, 211, 238, 0.10), transparent 60%),
      radial-gradient(1000px 640px at 108% 4%, rgba(34, 211, 238, 0.06), transparent 55%),
      linear-gradient(rgba(34,211,238,0.022) 1px, transparent 1px),
      linear-gradient(90deg, rgba(34,211,238,0.022) 1px, transparent 1px);
    background-size: auto, auto, 44px 44px, 44px 44px;
    background-attachment: fixed;
    color: var(--ink);
    font-size: 14px; line-height: 1.55; overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
  }
  ::selection { background: var(--cyan-soft); color: var(--cyan-bright); }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(34,211,238,0.22); border-radius: 6px; border: 2px solid transparent; background-clip: content-box; }
  svg:not([class*="icon"]):not([width]) { width: 16px; height: 16px; flex-shrink: 0; }
  .icon { width: 16px; height: 16px; flex-shrink: 0; stroke-width: 1.6; }
  .icon-sm { width: 14px; height: 14px; flex-shrink: 0; }
  .icon-xs { width: 12px; height: 12px; flex-shrink: 0; }

  header {
    background: linear-gradient(180deg, rgba(12,18,27,0.92), rgba(8,12,18,0.72));
    backdrop-filter: blur(16px) saturate(1.2);
    -webkit-backdrop-filter: blur(16px) saturate(1.2);
    border-bottom: 1px solid var(--hairline);
    box-shadow: 0 1px 0 rgba(34,211,238,0.10), 0 16px 40px -28px rgba(0,0,0,0.9);
    padding: 16px 32px;
    display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 20;
  }
  .brand { display: flex; align-items: center; gap: 16px; }
  .brand-mark { height: 44px; width: auto; filter: drop-shadow(0 2px 10px rgba(34, 211, 238, 0.30)); }
  .brand-divider { width: 1px; height: 28px; background: var(--hairline-strong); }
  .brand-text h1 { font-size: 14px; font-weight: 600; letter-spacing: -0.01em; }
  .brand-text .subtitle { font-size: 11.5px; color: var(--ink-muted); margin-top: 3px; font-weight: 500; }
  .brand-text .subtitle b { color: var(--brand-red); font-weight: 600; }
  .brand-link {
    color: var(--brand-red); font-weight: 600;
    text-decoration: none;
    transition: opacity 0.18s var(--ease), text-decoration-color 0.18s var(--ease);
  }
  .brand-link:hover { text-decoration: underline; opacity: 0.85; }
  .header-right { display: flex; align-items: center; gap: 10px; }
  .btn-link {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 8px 14px; border-radius: 100px;
    background: var(--surface); border: 1px solid var(--hairline);
    font: 600 12px 'Geist', sans-serif; color: var(--ink-soft);
    text-decoration: none; cursor: pointer;
    transition: background 0.18s var(--ease), border-color 0.18s var(--ease);
  }
  .btn-link:hover { background: var(--surface-soft); border-color: var(--hairline-strong); }
  .btn-link.active {
    background: var(--cyan-soft); color: var(--cyan-bright); border-color: rgba(34,211,238,0.30);
  }
  .range-group { display: inline-flex; gap: 4px; padding: 3px;
    background: var(--surface-soft); border: 1px solid var(--hairline); border-radius: 100px; }
  .range-group button {
    border: 0; background: transparent; padding: 6px 12px; border-radius: 100px;
    font: 600 12px 'Geist', sans-serif; color: var(--ink-muted); cursor: pointer;
  }
  .range-group button.active { background: var(--surface); color: var(--ink);
    box-shadow: 0 1px 0 rgba(255,255,255,0.03) inset, 0 6px 16px -8px rgba(0,0,0,0.8); }

  .page { max-width: 1480px; margin: 0 auto; padding: 24px 32px 60px; }
  .page-title {
    font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin-bottom: 4px;
  }
  .page-sub {
    font-size: 13px; color: var(--ink-muted); margin-bottom: 24px;
    font-variant-numeric: tabular-nums;
  }

  /* KPI strip */
  .kpis {
    display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; gap: 14px;
    margin-bottom: 22px;
  }
  .kpi {
    background: var(--surface); border: 1px solid var(--hairline);
    border-radius: 22px; padding: 18px 22px 20px;
    box-shadow: var(--shadow-card);
    position: relative; overflow: hidden;
    transition: transform 0.4s var(--ease), box-shadow 0.4s var(--ease);
  }
  .kpi:hover { transform: translateY(-2px); box-shadow: var(--shadow-card-hover); }
  .kpi::before {
    content: ''; position: absolute; left: 18px; right: 18px; top: 0;
    height: 2px; border-radius: 0 0 6px 6px; background: var(--accent, var(--brand-blue));
  }
  .kpi:nth-child(1) { --accent: var(--brand-red); }
  .kpi:nth-child(2) { --accent: var(--brand-blue); }
  .kpi:nth-child(3) { --accent: var(--warning); }
  .kpi:nth-child(4) { --accent: var(--success); }
  .kpi-label {
    font-size: 11px; color: var(--ink-muted); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    display: inline-flex; align-items: center; gap: 8px; margin-bottom: 10px;
  }
  .kpi-row { display: flex; align-items: baseline; gap: 12px; }
  .kpi-value {
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 36px; font-weight: 600; letter-spacing: -0.025em; line-height: 1;
  }
  .kpi-value.success { color: var(--success); }
  .kpi-value.warning { color: var(--warning); }
  .kpi-value.brand   { color: var(--brand-red); }
  .kpi-value.info    { color: var(--brand-blue); }
  .kpi-trail { font-size: 12px; color: var(--ink-muted); font-weight: 500; }

  /* Two-column main grid */
  .grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;
  }
  .card {
    background: var(--surface); border: 1px solid var(--hairline);
    border-radius: 24px; padding: 22px 24px; box-shadow: var(--shadow-card);
  }
  .card h2 {
    font-size: 13px; font-weight: 600; color: var(--ink);
    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 18px;
    display: flex; align-items: center; gap: 8px;
  }
  .card h2 svg { color: var(--brand-red); }
  .card .sub {
    font-size: 12px; color: var(--ink-muted); margin-top: -10px; margin-bottom: 18px;
    font-variant-numeric: tabular-nums;
  }

  /* Issue breakdown bars */
  .cat-row {
    display: grid; grid-template-columns: 140px 1fr 40px;
    gap: 12px; align-items: center; padding: 8px 0;
  }
  .cat-row + .cat-row { border-top: 1px solid var(--hairline); }
  .cat-label { font-size: 13px; color: var(--ink-soft); }
  .cat-bar {
    height: 8px; background: var(--surface-soft); border-radius: 100px; overflow: hidden;
    position: relative;
  }
  .cat-bar-fill {
    position: absolute; top: 0; left: 0; bottom: 0;
    background: var(--bar-color, var(--brand-blue));
    border-radius: 100px;
    transition: width 0.7s var(--ease);
  }
  .cat-count {
    font-family: 'Geist Mono', monospace; font-size: 13px; font-weight: 600;
    text-align: right; color: var(--ink);
  }
  .cat-row.success      .cat-bar-fill { background: var(--success); }
  .cat-row.lost_caller, .cat-row.hallucination, .cat-row.wrong_routing { }
  .cat-row.lost_caller       .cat-bar-fill { background: var(--brand-red); }
  .cat-row.wrong_routing     .cat-bar-fill { background: var(--brand-red); }
  .cat-row.hallucination     .cat-bar-fill { background: var(--brand-red); }
  .cat-row.incomplete_info   .cat-bar-fill { background: var(--warning); }
  .cat-row.escalation_failure .cat-bar-fill { background: var(--warning); }
  .cat-row.low_quality       .cat-bar-fill { background: var(--ink-dim); }
  .cat-row.unknown           .cat-bar-fill { background: var(--ink-dim); }

  /* Trend chart (SVG) */
  .trend-wrap { width: 100%; height: 220px; }
  .trend-svg { width: 100%; height: 100%; display: block; }
  .trend-grid { stroke: var(--hairline); stroke-width: 1; }
  .trend-area { fill: var(--brand-blue-soft); }
  .trend-line { fill: none; stroke: var(--brand-blue); stroke-width: 2; }
  .trend-dot  { fill: var(--brand-blue); }
  .trend-axis { font: 500 10px 'Geist Mono', monospace; fill: var(--ink-muted); }

  /* Recent reviews list */
  .review-row {
    display: grid; grid-template-columns: 56px 1fr auto;
    gap: 14px; padding: 14px 0; align-items: center;
    border-top: 1px solid var(--hairline);
  }
  .review-row:first-of-type { border-top: 0; }
  .score-pill {
    width: 50px; height: 38px; border-radius: 10px;
    display: inline-flex; align-items: center; justify-content: center;
    font-family: 'Geist Mono', monospace; font-weight: 600; font-size: 15px;
    background: var(--surface-soft); color: var(--ink);
    border: 1px solid var(--hairline);
  }
  .score-pill.good { background: var(--success-soft); color: var(--success); border-color: rgba(4,120,87,0.18); }
  .score-pill.mid  { background: var(--warning-soft); color: var(--warning); border-color: rgba(183,121,31,0.22); }
  .score-pill.bad  { background: var(--danger-soft); color: var(--danger); border-color: rgba(255,80,99,0.3); }
  .review-body strong {
    font-size: 13.5px; font-weight: 600; display: block;
    color: var(--ink); letter-spacing: -0.005em;
  }
  .review-body .review-meta {
    font-size: 11.5px; color: var(--ink-muted); margin-top: 2px;
    display: inline-flex; align-items: center; gap: 6px;
    font-variant-numeric: tabular-nums;
  }
  .badge {
    font-size: 10px; font-weight: 600; padding: 3px 9px; border-radius: 100px;
    text-transform: uppercase; letter-spacing: 0.06em;
    display: inline-flex; align-items: center; gap: 5px;
    border: 1px solid transparent;
  }
  .b-success { background: var(--success-soft); color: var(--success); border-color: rgba(4,120,87,0.22); }
  .b-warning { background: var(--warning-soft); color: var(--warning); border-color: rgba(183,121,31,0.22); }
  .b-danger  { background: var(--danger-soft); color: var(--danger); border-color: rgba(255,80,99,0.3); }
  .b-neutral { background: var(--surface-soft); color: var(--ink-muted); border-color: var(--hairline); }
  .b-sev-high { background: var(--danger-soft); color: var(--danger); border-color: rgba(255,80,99,0.3); }
  .b-sev-med  { background: var(--warning-soft); color: var(--warning); border-color: rgba(183,121,31,0.22); }
  .b-sev-low  { background: var(--success-soft); color: var(--success); border-color: rgba(4,120,87,0.22); }

  /* Issue drilldown */
  .issue-card { background: var(--surface-soft); border: 1px solid var(--hairline);
    border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; }
  .issue-card .head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .issue-card h4 { font-size: 13.5px; font-weight: 600; color: var(--ink); flex: 1; }
  .issue-card .examples { font-size: 12.5px; color: var(--ink-muted); }
  .issue-card .examples strong { color: var(--ink-soft); font-weight: 600; }

  .empty {
    text-align: center; padding: 38px 24px; color: var(--ink-muted);
    border: 1px dashed var(--hairline); border-radius: 16px;
  }
  .empty strong { display: block; color: var(--ink-soft); font-size: 13.5px; margin-bottom: 4px; }

  /* RECOMMENDATIONS */
  .rec-card {
    background: var(--surface);
    border: 1px solid var(--hairline);
    border-radius: 18px;
    padding: 18px 20px;
    margin-bottom: 12px;
    transition: box-shadow 0.25s var(--ease), border-color 0.25s var(--ease);
  }
  .rec-card:hover { box-shadow: var(--shadow-card); }
  .rec-card.applied { border-left: 3px solid var(--success); }
  .rec-card.reverted { border-left: 3px solid var(--ink-dim); opacity: 0.78; }
  .rec-head {
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    margin-bottom: 6px;
  }
  .rec-head h3 {
    font-size: 14px; font-weight: 600; color: var(--ink); letter-spacing: -0.005em;
    flex: 1; min-width: 200px;
  }
  .rec-meta {
    font-size: 12px; color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
    display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }
  .rec-summary {
    font-size: 13px; color: var(--ink-soft); line-height: 1.6;
    margin-top: 4px;
  }
  .rec-issues { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
  .rec-actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
  .btn {
    padding: 8px 14px; border-radius: 10px; border: 1px solid transparent;
    font: 600 12px 'Geist', sans-serif; cursor: pointer; line-height: 1;
    display: inline-flex; align-items: center; gap: 6px;
    transition: transform 0.15s var(--ease), background 0.15s var(--ease);
  }
  .btn:active:not(:disabled) { transform: translateY(1px); }
  .btn:disabled { opacity: 0.45; cursor: not-allowed; }
  .btn-primary {
    background: linear-gradient(180deg, var(--cyan-bright), var(--cyan)); color: #04090E;
    box-shadow: 0 0 0 1px rgba(34,211,238,0.5) inset, 0 8px 20px -8px rgba(34,211,238,0.55);
  }
  .btn-primary:hover:not(:disabled) { background: var(--brand-red-warm); }
  .btn-ghost { background: var(--surface-soft); color: var(--ink); border-color: var(--hairline); }
  .btn-ghost:hover { background: var(--brand-cream); }
  .btn-quiet {
    background: transparent; color: var(--ink-muted); border-color: var(--hairline);
  }
  .btn-quiet:hover { background: var(--surface-soft); color: var(--ink-soft); }
  .btn-success {
    background: var(--success-soft); color: var(--success);
    border-color: rgba(4,120,87,0.22);
  }

  /* Modal — diff viewer */
  .modal-bg {
    position: fixed; inset: 0; background: rgba(2, 4, 8, 0.66);
    backdrop-filter: blur(6px);
    display: none; z-index: 50;
    animation: fadeIn 0.2s var(--ease);
  }
  .modal-bg.open { display: flex; align-items: center; justify-content: center; padding: 24px; }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
  .modal {
    background: var(--surface); border-radius: 22px;
    width: 100%; max-width: 1080px; max-height: 90vh;
    display: flex; flex-direction: column; overflow: hidden;
    box-shadow: 0 30px 80px -20px rgba(0,0,0,0.85);
    animation: modalIn 0.32s var(--ease);
  }
  @keyframes modalIn { from { opacity: 0; transform: translateY(12px) scale(0.985); } to { opacity: 1; transform: translateY(0) scale(1); } }
  .modal-head {
    padding: 18px 22px; border-bottom: 1px solid var(--hairline);
    display: flex; align-items: center; justify-content: space-between; gap: 14px;
  }
  .modal-head h3 { font-size: 15px; font-weight: 600; }
  .modal-head .close {
    border: 0; background: transparent; cursor: pointer;
    width: 32px; height: 32px; border-radius: 8px;
    display: inline-flex; align-items: center; justify-content: center;
    color: var(--ink-muted);
  }
  .modal-head .close:hover { background: var(--surface-soft); color: var(--ink); }
  .modal-body { padding: 22px; overflow-y: auto; flex: 1; }
  .modal-foot {
    padding: 14px 22px; border-top: 1px solid var(--hairline);
    display: flex; justify-content: flex-end; gap: 8px;
    background: var(--surface-soft);
  }
  .summary-box {
    background: var(--surface-soft); border: 1px solid var(--hairline);
    border-radius: 12px; padding: 14px 16px;
    font-size: 13px; line-height: 1.6; color: var(--ink-soft);
    white-space: pre-wrap; margin-bottom: 18px;
  }
  .rationale {
    font-size: 12.5px; color: var(--ink-muted); line-height: 1.55;
    margin-bottom: 18px;
  }
  .diff-pre {
    background: var(--surface-soft);
    border: 1px solid var(--hairline);
    border-radius: 12px;
    padding: 14px 16px;
    font: 500 12.5px/1.55 'Geist Mono', ui-monospace, monospace;
    overflow-x: auto;
    white-space: pre;
    color: var(--ink-soft);
    max-height: 50vh;
  }
  .diff-pre .add { background: rgba(4, 120, 87, 0.10); color: var(--success); display: block; }
  .diff-pre .del { background: rgba(255, 80, 99, 0.12); color: var(--danger); display: block; }
  .diff-pre .hunk { color: var(--brand-blue); display: block; font-weight: 600; }
  .toast {
    position: fixed; bottom: 24px; right: 24px;
    background: var(--surface); border: 1px solid var(--hairline);
    border-left: 3px solid var(--success);
    border-radius: 14px; padding: 14px 18px;
    box-shadow: 0 18px 44px -14px rgba(0,0,0,0.8);
    font-size: 13px; max-width: 360px;
    animation: modalIn 0.32s var(--ease);
    z-index: 60;
  }
  .toast.error { border-left-color: var(--brand-red); }

  @media (max-width: 980px) {
    .kpis { grid-template-columns: repeat(2, 1fr); }
    .grid { grid-template-columns: 1fr; }
    .page { padding: 18px 16px 40px; }
    header { padding: 12px 16px; }
  }
  @media (max-width: 720px) {
    header { padding: 11px 14px; gap: 10px; }
    .brand-divider, .brand-text .subtitle { display: none; }
    .header-right {
      min-width: 0; flex: 1 1 auto; justify-content: flex-end; gap: 8px;
      overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none;
    }
    .header-right::-webkit-scrollbar { display: none; }
    .header-right > * { flex: 0 0 auto; }
    .kpis { grid-template-columns: 1fr; }
    .page { padding: 14px 14px 48px; }
    .page-title { font-size: 22px; }
  }
</style>
</head>
<body>

<header>
  <div class="brand">
    <img class="brand-mark" src="{{ logo_data_uri }}" alt="High Tech Air Conditioning" />
    <div class="brand-divider"></div>
    <div class="brand-text">
      <h1>Call Quality Analytics</h1>
      <div class="subtitle">Continuous review · Powered by <a class="brand-link" href="https://manyfai.com" target="_blank" rel="noopener">ManyFai</a></div>
    </div>
  </div>
  <div class="header-right">
    <div class="range-group" id="range-group">
      <button data-days="1">24h</button>
      <button data-days="7" class="active">7d</button>
      <button data-days="30">30d</button>
    </div>
    <button id="run-synth-btn" class="btn-link" type="button" title="Run a recommendation pass on the last 24h of reviews">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="3"/></svg>
      <span id="run-synth-label">Run synthesis</span>
    </button>
    <a class="btn-link" href="/dashboard?key={{ key }}">
      <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.6"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
      Live calls
    </a>
  </div>
</header>

<div class="page">
  <div class="page-title" id="page-title">Loading…</div>
  <div class="page-sub" id="page-sub">—</div>

  <div class="kpis" id="kpis"></div>

  <div class="card" style="margin-bottom:14px;">
    <h2>
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="3"/></svg>
      Improvement recommendations
    </h2>
    <div class="sub">Daily synthesis runs at 8 AM Eastern. One-click apply pushes the new <code>global_prompt</code> straight to the Retell agent.</div>
    <div id="recs-list"><div class="empty"><strong>No recommendations yet.</strong>Click <em>Run synthesis</em> in the header once you have ≥3 reviewed calls.</div></div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 6-6"/></svg>
        Success score · daily
      </h2>
      <div class="trend-wrap" id="trend-wrap">
        <div class="empty">Waiting for reviewed calls.</div>
      </div>
    </div>
    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="9" y2="18"/></svg>
        Outcome breakdown
      </h2>
      <div id="cat-list"><div class="empty">Waiting for reviewed calls.</div></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:14px;">
    <h2>
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>
      What needs fixing
    </h2>
    <div class="sub">Top recurring issues from the last <span id="fix-window">7</span> days</div>
    <div id="fix-list"><div class="empty">No issues surfaced yet.</div></div>
  </div>

  <div class="card">
    <h2>
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      Recent reviews
    </h2>
    <div id="reviews-list"><div class="empty">No reviewed calls yet.</div></div>
  </div>
</div>

<div class="modal-bg" id="rec-modal" role="dialog" aria-modal="true">
  <div class="modal" id="rec-modal-inner">
    <div class="modal-head">
      <h3 id="rec-modal-title">—</h3>
      <button class="close" id="rec-modal-close" aria-label="Close">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="modal-body" id="rec-modal-body">—</div>
    <div class="modal-foot" id="rec-modal-foot"></div>
  </div>
</div>

<script>
const KEY = "{{ key }}";
const CAT_LABEL = {{ category_labels | tojson }};
const SEV_BADGE = {high: "b-sev-high", med: "b-sev-med", low: "b-sev-low"};

let currentDays = 7;

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmtPhone(p) {
  if (!p) return "Unknown";
  const d = String(p).replace(/\D/g, "");
  if (d.length === 11 && d.startsWith("1")) return `(${d.slice(1,4)}) ${d.slice(4,7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0,3)}) ${d.slice(3,6)}-${d.slice(6)}`;
  return p;
}
function fmtDuration(ms) {
  if (!ms) return "—";
  const s = Math.round(ms/1000); const m = Math.floor(s/60);
  return m > 0 ? `${m}m ${s%60}s` : `${s}s`;
}
function timeAgo(iso) {
  if (!iso) return "";
  const d = new Date(iso.replace(" ", "T") + (iso.endsWith("Z") ? "" : "Z"));
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff/60) + "m ago";
  if (diff < 86400) return Math.floor(diff/3600) + "h ago";
  return Math.floor(diff/86400) + "d ago";
}
function scoreClass(n) {
  if (n == null) return "";
  if (n >= 80) return "good";
  if (n >= 60) return "mid";
  return "bad";
}
function categoryBadge(cat) {
  const danger = ["lost_caller","wrong_routing","hallucination"];
  const warn   = ["incomplete_info","escalation_failure"];
  if (cat === "success")       return "b-success";
  if (danger.includes(cat))    return "b-danger";
  if (warn.includes(cat))      return "b-warning";
  return "b-neutral";
}

function renderKpis(d) {
  const k = d.kpi || {};
  const pass = k.passing || 0;
  const total = k.reviewed || 0;
  const passPct = total ? Math.round((pass / total) * 100) : 0;
  const html = `
    <div class="kpi">
      <span class="kpi-label">
        <svg class="icon-xs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        Reviewed (${currentDays}d)
      </span>
      <div class="kpi-row">
        <span class="kpi-value brand">${total}</span>
        <span class="kpi-trail">of ${d.calls_total} total · $${(d.cost_dollars || 0).toFixed(2)} spend</span>
      </div>
    </div>
    <div class="kpi">
      <span class="kpi-label">
        <svg class="icon-xs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        Avg score
      </span>
      <div class="kpi-row">
        <span class="kpi-value info">${k.avg_score ?? "—"}</span>
        <span class="kpi-trail">${total ? "out of 100" : "(no data)"}</span>
      </div>
    </div>
    <div class="kpi">
      <span class="kpi-label">
        <svg class="icon-xs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        High-severity
      </span>
      <div class="kpi-row">
        <span class="kpi-value warning">${k.high_sev || 0}</span>
        <span class="kpi-trail">to fix</span>
      </div>
    </div>
    <div class="kpi">
      <span class="kpi-label">
        <svg class="icon-xs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        Passing (≥80)
      </span>
      <div class="kpi-row">
        <span class="kpi-value success">${pass}</span>
        <span class="kpi-trail">${passPct}% pass rate</span>
      </div>
    </div>`;
  document.getElementById("kpis").innerHTML = html;
}

function renderCategories(d) {
  const list = (d.categories || []).filter(c => c.n > 0);
  const total = list.reduce((s, c) => s + c.n, 0);
  const wrap = document.getElementById("cat-list");
  if (total === 0) { wrap.innerHTML = `<div class="empty">No reviewed calls yet in this window.</div>`; return; }
  wrap.innerHTML = list.map(c => {
    const pct = Math.round((c.n / total) * 100);
    const label = CAT_LABEL[c.category] || c.category;
    return `<div class="cat-row ${escapeHtml(c.category)}">
      <div class="cat-label">${escapeHtml(label)}</div>
      <div class="cat-bar"><div class="cat-bar-fill" style="width:${pct}%"></div></div>
      <div class="cat-count">${c.n}</div>
    </div>`;
  }).join("");
}

function renderTrend(d) {
  const wrap = document.getElementById("trend-wrap");
  const data = d.trend || [];
  if (data.length === 0) {
    wrap.innerHTML = `<div class="empty">Trend will populate once we have at least one reviewed call.</div>`;
    return;
  }
  // SVG layout
  const W = 600, H = 220, PAD_L = 32, PAD_R = 16, PAD_T = 16, PAD_B = 28;
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;
  const xs = data.map((_, i) => PAD_L + (data.length === 1 ? innerW/2 : (i / (data.length - 1)) * innerW));
  const ys = data.map(p => PAD_T + innerH - ((p.avg_score || 0) / 100) * innerH);
  const linePts = xs.map((x, i) => `${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  const areaPts = `${PAD_L},${PAD_T+innerH} ${linePts} ${xs[xs.length-1].toFixed(1)},${PAD_T+innerH}`;
  const yTicks = [0, 50, 80, 100];
  const gridLines = yTicks.map(t => {
    const y = PAD_T + innerH - (t/100) * innerH;
    return `<line class="trend-grid" x1="${PAD_L}" y1="${y}" x2="${W-PAD_R}" y2="${y}"/>
            <text class="trend-axis" x="${PAD_L-6}" y="${y+3}" text-anchor="end">${t}</text>`;
  }).join("");
  const xLabels = data.map((p, i) => {
    if (data.length > 7 && i % 2 !== 0 && i !== data.length - 1) return "";
    const day = (p.day || "").slice(5).replace("-", "/");
    return `<text class="trend-axis" x="${xs[i].toFixed(1)}" y="${H-8}" text-anchor="middle">${day}</text>`;
  }).join("");
  const dots = xs.map((x, i) => `<circle class="trend-dot" cx="${x.toFixed(1)}" cy="${ys[i].toFixed(1)}" r="3"/>`).join("");
  wrap.innerHTML = `<svg class="trend-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    ${gridLines}
    <polygon class="trend-area" points="${areaPts}"/>
    <polyline class="trend-line" points="${linePts}"/>
    ${dots}
    ${xLabels}
  </svg>`;
}

function renderFixes(d) {
  document.getElementById("fix-window").textContent = currentDays;
  const wrap = document.getElementById("fix-list");
  const recent = d.recent || [];
  // Aggregate specific_fixes by similar text (simple: dedupe + count)
  const byCat = {};
  for (const r of recent) {
    if (r.category === "success") continue;
    if (!r.specific_fixes_json) continue;
    let fixes = [];
    try { fixes = JSON.parse(r.specific_fixes_json) || []; } catch { fixes = []; }
    if (!fixes.length) continue;
    if (!byCat[r.category]) byCat[r.category] = { count: 0, examples: [], fixes: {} };
    byCat[r.category].count += 1;
    byCat[r.category].examples.push({ id: r.call_id, phone: r.from_number, summary: r.one_line_summary });
    for (const f of fixes) {
      const key = (f || "").slice(0, 200);
      byCat[r.category].fixes[key] = (byCat[r.category].fixes[key] || 0) + 1;
    }
  }
  const sorted = Object.entries(byCat).sort((a, b) => b[1].count - a[1].count);
  if (sorted.length === 0) {
    wrap.innerHTML = `<div class="empty"><strong>Nothing to fix in this window.</strong>The agent's been clean — keep an eye on it.</div>`;
    return;
  }
  wrap.innerHTML = sorted.slice(0, 6).map(([cat, info]) => {
    const topFixes = Object.entries(info.fixes).sort((a, b) => b[1] - a[1]).slice(0, 3);
    const example = info.examples[0];
    const fixHtml = topFixes.map(([f, n]) => `<li>${escapeHtml(f)} <span style="color:var(--ink-dim);">·${n}×</span></li>`).join("");
    return `<div class="issue-card">
      <div class="head">
        <span class="badge ${categoryBadge(cat)}">${escapeHtml(CAT_LABEL[cat] || cat)}</span>
        <h4 style="margin:0;">${info.count} call${info.count===1?"":"s"} affected</h4>
      </div>
      <ul style="margin: 6px 0 8px 18px; font-size: 13px; color: var(--ink-soft); line-height: 1.55;">
        ${fixHtml}
      </ul>
      <div class="examples">e.g. <strong>${escapeHtml(fmtPhone(example.phone))}</strong> — ${escapeHtml(example.summary || "—")}</div>
    </div>`;
  }).join("");
}

function renderReviews(d) {
  const wrap = document.getElementById("reviews-list");
  const list = d.recent || [];
  if (list.length === 0) {
    wrap.innerHTML = `<div class="empty"><strong>No reviewed calls yet.</strong>Calls become reviewable a couple minutes after they end.</div>`;
    return;
  }
  wrap.innerHTML = list.map(r => {
    const score = r.success_score;
    const cat = r.category || "unknown";
    const sev = r.severity || "low";
    const phone = fmtPhone(r.from_number);
    const summary = r.one_line_summary || "—";
    return `<div class="review-row">
      <div class="score-pill ${scoreClass(score)}">${score ?? "—"}</div>
      <div class="review-body">
        <strong>${escapeHtml(phone)} — ${escapeHtml(summary)}</strong>
        <div class="review-meta">
          <span class="badge ${categoryBadge(cat)}">${escapeHtml(CAT_LABEL[cat] || cat)}</span>
          <span class="badge ${SEV_BADGE[sev] || "b-neutral"}">${escapeHtml(sev)}</span>
          <span>·</span>
          <span>${escapeHtml(timeAgo(r.created_at))}</span>
          <span>·</span>
          <span>${escapeHtml(fmtDuration(r.duration_ms))}</span>
        </div>
      </div>
      <div></div>
    </div>`;
  }).join("");
}

async function loadAnalytics(days) {
  currentDays = days;
  document.getElementById("page-title").textContent = "Call quality, last " + days + (days === 1 ? " day" : " days");
  document.getElementById("page-sub").textContent = "Updating…";
  try {
    const r = await fetch(`/api/analytics?key=${encodeURIComponent(KEY)}&days=${days}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    document.getElementById("page-sub").textContent =
      `${d.kpi.reviewed || 0} reviews · ${d.lifetime_reviewed} lifetime · last update ${new Date().toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'})}`;
    renderKpis(d);
    renderCategories(d);
    renderTrend(d);
    renderFixes(d);
    renderReviews(d);
  } catch (e) {
    document.getElementById("page-sub").textContent = "Failed to load: " + e.message;
  }
}

// Range picker
document.querySelectorAll("#range-group button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#range-group button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    loadAnalytics(parseInt(btn.dataset.days, 10));
  });
});

// ───── RECOMMENDATIONS ─────────────────────────────────────────
function recCardHTML(r) {
  const applied  = !!r.applied_at;
  const reverted = !!r.reverted_at;
  const cls = reverted ? "reverted" : (applied ? "applied" : "");
  const stateBadge = reverted
    ? `<span class="badge b-neutral">Reverted</span>`
    : applied
      ? `<span class="badge b-success">Applied · ${escapeHtml(timeAgo(r.applied_at))}</span>`
      : `<span class="badge b-warning">Awaiting apply</span>`;
  const issueChips = (r.top_issues || []).slice(0, 4).map(i => {
    const cat = i.category || "unknown";
    return `<span class="badge ${categoryBadge(cat)}">${escapeHtml(CAT_LABEL[cat] || cat)} · ${i.count || 0}</span>`;
  }).join("");
  // Strip markdown-style emphasis for the inline preview
  const preview = (r.summary_md || "").replace(/[#*_`]/g, "").slice(0, 280);
  return `<div class="rec-card ${cls}" data-id="${r.id}">
    <div class="rec-head">
      <h3>Recommendation #${r.id} · ${r.calls_reviewed || 0} calls · avg ${r.avg_success_score ?? "—"}</h3>
      ${stateBadge}
    </div>
    <div class="rec-meta">
      <span>${escapeHtml(timeAgo(r.created_at))}</span>
      <span>·</span>
      <span>${escapeHtml(r.model || "")}</span>
    </div>
    <div class="rec-summary">${escapeHtml(preview)}${preview.length === 280 ? "…" : ""}</div>
    <div class="rec-issues">${issueChips}</div>
    <div class="rec-actions">
      <button class="btn btn-primary" onclick="openRec(${r.id})">
        <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
        Review &amp; ${applied && !reverted ? "revert" : "apply"}
      </button>
    </div>
  </div>`;
}

async function loadRecommendations() {
  try {
    const r = await fetch(`/api/recommendations?key=${encodeURIComponent(KEY)}&limit=20`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const list = await r.json();
    const wrap = document.getElementById("recs-list");
    if (!list.length) {
      wrap.innerHTML = `<div class="empty"><strong>No recommendations yet.</strong>Click <em>Run synthesis</em> in the header once you have ≥3 reviewed calls.</div>`;
      return;
    }
    wrap.innerHTML = list.map(recCardHTML).join("");
  } catch (e) {
    console.error("loadRecommendations failed", e);
  }
}

function colorizeDiff(diffText) {
  if (!diffText) return `<div class="empty"><strong>No textual diff.</strong>The synthesizer returned the prompt unchanged.</div>`;
  const lines = diffText.split("\n").map(line => {
    if (line.startsWith("+++") || line.startsWith("---")) return `<span class="hunk">${escapeHtml(line)}</span>`;
    if (line.startsWith("@@")) return `<span class="hunk">${escapeHtml(line)}</span>`;
    if (line.startsWith("+"))  return `<span class="add">${escapeHtml(line)}</span>`;
    if (line.startsWith("-"))  return `<span class="del">${escapeHtml(line)}</span>`;
    return escapeHtml(line);
  });
  return `<pre class="diff-pre">${lines.join("\n")}</pre>`;
}

function showToastMsg(text, error=false) {
  const t = document.createElement("div");
  t.className = "toast" + (error ? " error" : "");
  t.textContent = text;
  document.body.appendChild(t);
  setTimeout(() => t.style.opacity = "0", 4500);
  setTimeout(() => t.remove(), 5200);
}

async function openRec(id) {
  const bg = document.getElementById("rec-modal");
  const body = document.getElementById("rec-modal-body");
  const foot = document.getElementById("rec-modal-foot");
  document.getElementById("rec-modal-title").textContent = "Loading recommendation…";
  body.innerHTML = `<div class="empty">Loading…</div>`;
  foot.innerHTML = "";
  bg.classList.add("open");
  try {
    const r = await fetch(`/api/recommendations/${id}?key=${encodeURIComponent(KEY)}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const rec = await r.json();
    const applied  = !!rec.applied_at;
    const reverted = !!rec.reverted_at;
    document.getElementById("rec-modal-title").textContent =
      `Recommendation #${rec.id} · ${rec.calls_reviewed || 0} calls in window`;
    body.innerHTML = `
      ${rec.summary_md ? `<div class="summary-box">${escapeHtml(rec.summary_md)}</div>` : ""}
      <div style="font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--ink-muted); text-transform: uppercase; margin-bottom: 8px;">DIFF — current vs proposed global_prompt</div>
      ${colorizeDiff(rec.proposed_prompt_diff || "")}
    `;
    let buttons = `<button class="btn btn-quiet" onclick="closeRec()">Close</button>`;
    if (reverted) {
      buttons += `<button class="btn btn-success" disabled>Reverted</button>`;
    } else if (applied) {
      buttons += `<button class="btn btn-ghost" onclick="revertRec(${rec.id})">Revert</button>`;
    } else {
      buttons += `<button class="btn btn-primary" onclick="applyRec(${rec.id})">
        <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        Apply to Retell agent
      </button>`;
    }
    foot.innerHTML = buttons;
  } catch (e) {
    body.innerHTML = `<div class="empty"><strong>Failed to load.</strong>${escapeHtml(e.message || "")}</div>`;
    foot.innerHTML = `<button class="btn btn-quiet" onclick="closeRec()">Close</button>`;
  }
}

function closeRec() {
  document.getElementById("rec-modal").classList.remove("open");
}

async function applyRec(id) {
  if (!confirm("Apply this recommendation? The Retell agent's global_prompt will be updated immediately.")) return;
  try {
    const r = await fetch(`/api/recommendations/${id}/apply?key=${encodeURIComponent(KEY)}`, { method: "POST" });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || j.detail || "apply failed");
    showToastMsg("Applied — global_prompt is now live on Retell.");
    closeRec();
    await loadRecommendations();
  } catch (e) {
    showToastMsg("Apply failed: " + (e.message || ""), true);
  }
}

async function revertRec(id) {
  if (!confirm("Revert this recommendation? The Retell agent's global_prompt will be restored to the previous version.")) return;
  try {
    const r = await fetch(`/api/recommendations/${id}/revert?key=${encodeURIComponent(KEY)}`, { method: "POST" });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || j.detail || "revert failed");
    showToastMsg("Reverted — global_prompt restored.");
    closeRec();
    await loadRecommendations();
  } catch (e) {
    showToastMsg("Revert failed: " + (e.message || ""), true);
  }
}

document.getElementById("rec-modal-close").addEventListener("click", closeRec);
document.getElementById("rec-modal").addEventListener("click", (e) => {
  if (e.target.id === "rec-modal") closeRec();
});

// Run synthesis button
const runBtn = document.getElementById("run-synth-btn");
const runLabel = document.getElementById("run-synth-label");
runBtn.addEventListener("click", async () => {
  const force = window.event && window.event.shiftKey; // shift+click forces with <3 reviews
  if (!confirm(force
    ? "Force-run synthesis on the last 24h, even with <3 reviews?"
    : "Run a synthesis pass on the last 24h of reviewed calls?")) return;
  runBtn.disabled = true;
  runLabel.textContent = "Synthesizing…";
  try {
    const url = `/api/synth/run?key=${encodeURIComponent(KEY)}&hours=24` + (force ? "&force=true" : "");
    const r = await fetch(url, { method: "POST" });
    const j = await r.json();
    if (!j.ok) {
      showToastMsg(j.reason || "No recommendation produced.", true);
    } else {
      showToastMsg(`Recommendation #${j.recommendation_id} ready.`);
    }
  } catch (e) {
    showToastMsg("Failed: " + (e.message || ""), true);
  } finally {
    runBtn.disabled = false;
    runLabel.textContent = "Run synthesis";
    await loadRecommendations();
  }
});

// Initial load + auto-refresh every 60s
loadAnalytics(7);
loadRecommendations();
setInterval(() => { loadAnalytics(currentDays); loadRecommendations(); }, 60000);
</script>
</body>
</html>"""


@app.route("/analytics", methods=["GET"])
def analytics_page():
    """Call quality analytics. Same auth as /dashboard."""
    key = request.args.get("key", "")
    if key != DASHBOARD_PASSWORD:
        return Response("Unauthorized — append ?key=YOUR_PASSWORD to the URL", status=401)
    return Response(
        render_template_string(
            ANALYTICS_HTML,
            logo_data_uri=LOGO_DATA_URI,
            key=key,
            category_labels=CATEGORY_LABEL,
        ),
        mimetype="text/html",
    )


# ============================================================
# PRIVACY POLICY (public, for general compliance)
# ============================================================

PRIVACY_POLICY_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Policy — High Tech Air Conditioning</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;color:#1a1a1a;line-height:1.6}
h1{color:#C4080C;border-bottom:2px solid #C4080C;padding-bottom:8px}
h2{color:#C4080C;margin-top:36px}
.meta{color:#666;font-size:14px;margin-bottom:32px}
a{color:#C4080C}
ul{padding-left:22px}
li{margin-bottom:6px}
.footer{margin-top:48px;padding-top:20px;border-top:1px solid #eee;color:#666;font-size:13px}
</style></head><body>

<h1>Privacy Policy</h1>
<p class="meta"><strong>High Tech Air Conditioning</strong> &middot; Last updated: May 11, 2026</p>

<p>High Tech Air Conditioning ("we," "us," "our") respects your privacy. This policy explains what information we collect when you contact us by phone, SMS, or our website, how we use it, and your rights.</p>

<h2>1. Information We Collect</h2>
<ul>
  <li><strong>Contact information:</strong> name, phone number, email address, service address — collected when you book a service appointment.</li>
  <li><strong>Service details:</strong> description of the HVAC issue, appointment date/time, service type.</li>
  <li><strong>Call recordings and transcripts:</strong> incoming calls to our published numbers may be answered by an AI voice assistant ("Anna"). Calls may be recorded and transcribed for quality, training, and recordkeeping purposes.</li>
  <li><strong>Marketing source:</strong> how you heard about us (Google, Yelp, referral, etc.), if you choose to share it.</li>
</ul>

<h2>2. How We Use Your Information</h2>
<ul>
  <li>To schedule, confirm, and service your HVAC appointment.</li>
  <li>To send appointment confirmations and operational updates via SMS or email.</li>
  <li>To contact you about your service request, follow up on quotes, or respond to questions.</li>
  <li>To improve our service quality (call review, transcript analysis).</li>
  <li>For legal, regulatory, billing, and warranty recordkeeping.</li>
</ul>

<h2>3. SMS / Text Message Communication</h2>
<p>We send SMS messages only for transactional and operational purposes — appointment confirmations, ETA updates, and internal staff alerts. We do not send marketing or promotional SMS to customers. Message frequency varies based on your service interactions. Message and data rates may apply. Reply <strong>STOP</strong> to any text to opt out of further SMS communication. Reply <strong>HELP</strong> for assistance.</p>

<h2>4. AI Voice Assistant</h2>
<p>Our phone line may be answered by an AI virtual assistant. The assistant will identify itself as such if directly asked. Calls handled by the AI are recorded and transcribed to deliver service, dispatch technicians, and improve accuracy. By continuing the call, you consent to this recording.</p>

<h2>5. Third-Party Service Providers</h2>
<p>We share limited information with trusted third parties only as needed to deliver service:</p>
<ul>
  <li><strong>Housecall Pro</strong> — our scheduling and dispatch platform. Receives your name, contact info, address, and appointment details to assign a technician.</li>
  <li><strong>Retell AI</strong> — provides the voice AI infrastructure that answers and transcribes calls.</li>
</ul>
<p>We do not sell your personal information to anyone, ever.</p>

<h2>6. Data Retention</h2>
<p>We retain customer records (contact info, service history, call transcripts) for as long as your account is active and for a reasonable period afterward to support warranty, billing, and regulatory obligations. You can request deletion at any time (see Section 9).</p>

<h2>7. Security</h2>
<p>We use industry-standard safeguards to protect your information, including encrypted connections (HTTPS) for our web services and API integrations, and access controls on internal tools. No method of transmission over the internet is 100% secure, but we work to protect your data.</p>

<h2>8. Children's Privacy</h2>
<p>Our services are intended for adults seeking HVAC services. We do not knowingly collect information from children under 13.</p>

<h2>9. Your Rights</h2>
<p>You may request to:</p>
<ul>
  <li>See the information we have about you.</li>
  <li>Correct or update your information.</li>
  <li>Delete your records (subject to legal retention requirements).</li>
  <li>Opt out of SMS communication (reply STOP to any text).</li>
</ul>
<p>To exercise any of these rights, contact us using the information below.</p>

<h2>10. Changes to This Policy</h2>
<p>We may update this policy from time to time. The "Last updated" date at the top of this page reflects the most recent change. Material changes will be communicated through our website or by direct notice when reasonable.</p>

<h2>11. Contact Us</h2>
<p>If you have questions about this policy or how we handle your information, contact us:</p>
<ul>
  <li><strong>High Tech Air Conditioning</strong></li>
  <li>6148 Hanging Moss Rd, Orlando, FL 32807</li>
  <li>Phone: (407) 837-7332</li>
  <li>Website: <a href="https://www.hightechacfl.com">www.hightechacfl.com</a></li>
  <li>Email: info@frassinogroup.com</li>
</ul>

<div class="footer">&copy; 2026 High Tech Air Conditioning. All rights reserved.</div>
</body></html>"""

@app.route("/privacy", methods=["GET"])
@app.route("/privacy-policy", methods=["GET"])
def privacy_policy():
    return Response(PRIVACY_POLICY_HTML, mimetype="text/html")


TERMS_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terms & Conditions — High Tech Air Conditioning</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;color:#1a1a1a;line-height:1.6}
h1{color:#C4080C;border-bottom:2px solid #C4080C;padding-bottom:8px}
h2{color:#C4080C;margin-top:36px}
.meta{color:#666;font-size:14px;margin-bottom:32px}
a{color:#C4080C}
ul{padding-left:22px}
li{margin-bottom:6px}
.footer{margin-top:48px;padding-top:20px;border-top:1px solid #eee;color:#666;font-size:13px}
</style></head><body>

<h1>Terms & Conditions</h1>
<p class="meta"><strong>High Tech Air Conditioning</strong> &middot; Last updated: May 11, 2026</p>

<p>These Terms & Conditions ("Terms") govern your use of services provided by High Tech Air Conditioning ("we," "us," "our"), including phone-based booking, our AI voice assistant, SMS communications, and on-site HVAC service. By contacting us, scheduling service, or receiving messages from us, you agree to these Terms.</p>

<h2>1. Services Offered</h2>
<p>We provide residential and commercial heating, ventilation, and air conditioning (HVAC) services in Central Florida, including:</p>
<ul>
  <li>AC and heating repair, installation, replacement, and maintenance</li>
  <li>Thermostat, ductwork, mini-split, and indoor air quality services</li>
  <li>New construction and commercial HVAC</li>
</ul>
<p>Service availability is limited to our published service area. We reserve the right to refuse service that is outside our area or scope.</p>

<h2>2. Appointments & Diagnostic Fees</h2>
<ul>
  <li><strong>$80 regular diagnostic fee</strong> applies to repair calls during regular business hours. If you approve the repair, the $80 is applied toward the repair cost. If you decline, the $80 is owed for the visit and assessment.</li>
  <li><strong>$120 emergency fee</strong> applies to all calls placed during emergency / after-hours periods. This dispatch fee is separate from the cost of repairs, which are quoted on-site.</li>
  <li><strong>Free consultations</strong> are offered for AC replacement and new installation, scheduled with our owner directly.</li>
</ul>
<p>Repair, parts, and installation pricing is provided by the technician on-site before any work begins. No work is performed without your written or verbal approval.</p>

<h2>3. Parts Policy</h2>
<p>For warranty, insurance, and quality-control reasons, we do not install customer-supplied parts. All parts used in our repairs must be sourced by High Tech Air Conditioning. We will gladly provide a quote for any repair using parts we supply.</p>

<h2>4. Cancellations & Rescheduling</h2>
<p>Appointments may be cancelled or rescheduled by contacting us during business hours. We ask for as much advance notice as possible so we can offer the slot to another customer. Same-day cancellations for confirmed emergency dispatches may still be subject to the dispatch fee.</p>

<h2>5. Payment Terms</h2>
<ul>
  <li>Payment is due upon completion of service unless prior written arrangements have been made.</li>
  <li>We accept standard forms of payment as communicated at the time of booking.</li>
  <li>Unpaid balances may be subject to late fees, collection costs, and interest as allowed by law.</li>
</ul>

<h2>6. Warranties</h2>
<p>Warranty terms for parts and labor will be provided on your invoice or service estimate. Warranties cover normal use and original installation by our technicians; they do not cover damage from misuse, modifications, third-party repairs, customer-supplied parts, or acts of nature. Manufacturer parts warranties are subject to the terms set by the manufacturer.</p>

<h2>7. SMS Communications</h2>
<p>By providing us with your phone number, you consent to receive transactional SMS messages from us related to your service appointment (confirmations, ETAs, follow-ups). Message frequency varies based on your service interactions. Standard message and data rates may apply. You can opt out at any time by replying <strong>STOP</strong> to any text. Reply <strong>HELP</strong> for assistance. We do not send marketing SMS without separate explicit consent.</p>

<h2>8. AI Voice Assistant</h2>
<p>Our phone line may be answered by an AI virtual assistant. The assistant will identify itself as such if directly asked. Calls handled by the AI may be recorded and transcribed for service delivery, dispatch coordination, and quality improvement. By continuing the call, you consent to recording and transcription.</p>

<h2>9. Limitation of Liability</h2>
<p>To the maximum extent permitted by law, High Tech Air Conditioning's total liability for any claim arising out of or related to our services is limited to the amount you paid for the specific service giving rise to the claim. We are not liable for indirect, incidental, special, consequential, or punitive damages, including lost profits, lost data, or damage to property not directly caused by our work.</p>

<h2>10. Indemnification</h2>
<p>You agree to indemnify and hold harmless High Tech Air Conditioning, its owners, employees, and contractors from any claim, loss, or expense arising out of your breach of these Terms, your provision of inaccurate information, or your unauthorized use of our services.</p>

<h2>11. Dispute Resolution</h2>
<p>Any dispute arising out of or related to these Terms or our services will first be addressed through good-faith negotiation between the parties. If unresolved, disputes will be governed by the laws of the State of Florida and resolved in the courts of Orange County, Florida.</p>

<h2>12. Changes to These Terms</h2>
<p>We may update these Terms from time to time. The "Last updated" date reflects the most recent revision. Continued use of our services after changes are posted constitutes acceptance of the updated Terms.</p>

<h2>13. Contact</h2>
<p>Questions about these Terms? Contact us:</p>
<ul>
  <li><strong>High Tech Air Conditioning</strong></li>
  <li>6148 Hanging Moss Rd, Orlando, FL 32807</li>
  <li>Phone: (407) 837-7332</li>
  <li>Website: <a href="https://www.hightechacfl.com">www.hightechacfl.com</a></li>
  <li>Email: info@frassinogroup.com</li>
</ul>

<div class="footer">&copy; 2026 High Tech Air Conditioning. All rights reserved.</div>
</body></html>"""

@app.route("/terms", methods=["GET"])
@app.route("/terms-and-conditions", methods=["GET"])
def terms_page():
    return Response(TERMS_HTML, mimetype="text/html")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "high-tech-ac-voice-agent",
        "tools": ["check-availability", "create-appointment", "transfer-emergency"],
        "dashboard": "/dashboard?key=YOUR_PASSWORD",
        "webhook": "/webhook/retell",
    })


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
