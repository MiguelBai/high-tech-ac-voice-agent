# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A live, billable production deployment for **one specific customer**: High Tech Air Conditioning (Orlando, FL). It's a Flask backend that bridges a **Retell AI** voice agent named **"Sarah v2"** to **Housecall Pro** (HCP) for real job booking, plus a single-page live-call dashboard with alerting, a Message Center, and AI call-quality review. Not a template — field-tech IDs, service area, the emergency tech, transfer numbers, and the company prompt are all specific to High Tech AC.

The voice agent itself runs on Retell's platform; this repo is the webhook/tool backend + monitoring UI. The agent's prompt is edited via the Retell API (see *Editing the voice agent* below) and mirrored locally in `retell/planning/retell_agent_prompt_v2.md`.

## The voice agent: single-prompt "Sarah v2"

The current agent is **"Sarah v2 — High Tech AC (single-prompt)"** — a single `general_prompt` LLM agent, **not** a Retell conversation-flow graph.

- **It replaced an earlier conversation-flow (node-graph) agent that didn't work well** — the branching flow was brittle and hard to iterate. All current agent work means V2 / single-prompt. Do not touch or resurrect the old flow-based agent.
- Agent ID: `agent_0d457978dd795971fabfb1cdb6`
- LLM ID: `llm_3f1ab929b9b566f0a1a4be12ecfb` (this is where `general_prompt` lives)
- The user iterates by **placing live test calls** and reporting issues. When they say "the agent said X / it shouldn't do Y," assume Sarah v2 and fix it directly — usually a prompt edit, occasionally server logic.
- Local source-of-truth prompt: `retell/planning/retell_agent_prompt_v2.md` — keep it in sync with whatever is published to Retell so the file doesn't drift.

## Repo layout

The dev workspace was reorganized into folders; **operational files stay at the repo root** because the running server and deploy tooling read them relative to themselves — do not move these:

```
server.py            ← the dev-workspace app (see deploy note below — this is NOT what Railway runs)
logo.png             ← read by server.py relative to __file__ (_load_logo_data_uri)
.env / .env.example  ← creds loaded from cwd
Procfile, requirements.txt
CLAUDE.md            ← only auto-loaded by Claude Code from the repo root
deploy/              ← the canonical LIVE app + its own git repo (see below)
data/                ← local SQLite + json state (DATA_DIR fallback)

knowledge_base/      High_Tech_AC_Knowledge_Base.txt, KB_UPDATE_gas-CO-safety.txt
proposals/
  ├─ deliverables/   the 3 client PDFs (proposal, contract, intake form)
  └─ generators/     generate_proposal/contract/intake_form/proposals .py
retell/
  ├─ planning/       retell_agent_prompt_v2.md (+ v1), retell_tool_definitions.json,
  │                  flow PDFs, RETELL_SIMULATIONS.md
  └─ generators/     generate_retell_flow.py, generate_retell_flow_v2.py
docs/                market research, DEPLOY_profile_lookup.md, TELEGRAM_BOT_CONTEXT.md,
                     TEST_PLAN.md, TEST_PLAN_v2.md
```

Generators are one-off client-deliverable scripts (not deploy artifacts). Run them from the repo root so relative paths (e.g. `logo.png`) resolve, e.g. `python3 proposals/generators/generate_proposal.py`.

## ⚠️ Deploy model — read this before deploying

There are **two git repos in one tree, and `deploy/` is now AHEAD of root** (the relationship is the reverse of how this project started):

- **`deploy/server.py` is the canonical, live, feature-complete app** (~7.5k lines). It has: Telegram alerting, the unified `notify_event()` fan-out, the Message Center, web push, returning-caller HCP profile lookup + dedupe, the transfer-contact manager, Retell signature verification, and the dark/cyan dashboard redesign.
- **Root `server.py` is BEHIND** (~5.5k lines). It still uses the old **Twilio SMS** notification path (`send_sms_alert`) and lacks the transfer-contacts, Message Center, push, and signature-verification subsystems entirely.

**Therefore: do NOT `cp server.py deploy/server.py`.** A blind copy reverts production to Twilio and destroys the notification/transfer/push work. The old "edit root → copy to deploy" instruction is dead.

**To ship a change:** make the edit in **`deploy/server.py`** (and mirror to root only if you want to eventually reconcile them — they should be merged into one canonical source someday). For surgical ports, use string-replacement with `count == 1` assertions so drift fails loudly.

### Railway deploy recipe (the `railway up` indexing-hang workaround)

`railway up` run directly from `deploy/` **hangs forever at `Indexing...`** — it chokes walking the nested `.worktrees/` and `.git` pointer files even though they're gitignored. Deploy from a clean staging dir instead:

```bash
# 1. Copy only runtime files to a clean dir (no .git, no .worktrees)
mkdir -p /tmp/hvac-clean-deploy
cp deploy/server.py deploy/Procfile deploy/requirements.txt deploy/logo.png /tmp/hvac-clean-deploy/
cp -r deploy/assets /tmp/hvac-clean-deploy/

# 2. Commit in deploy/ for history (the Railway project link lives there)
cd deploy && git add -A && git commit -m "..."

# 3. Deploy the clean dir, non-interactive, streaming logs (~30–90s build)
PATH="$HOME/.npm-global/bin:$PATH" railway up "/tmp/hvac-clean-deploy" \
  --path-as-root --service "HVAC Retell Alfredo" --ci
```

- Railway service: **`HVAC Retell Alfredo`** — service id `f019df56-b420-4f84-91b1-2df3090a6d99`, project id `1080d269-c15c-44ee-adbb-dc42306f9166`.
- After deploy, sanity-check with `railway logs --service "HVAC Retell Alfredo"`.

## Architecture — why it's shaped this way

**Single-process, single-worker by design.** `Procfile` runs `gunicorn ... --worker-class gevent --workers 1`. State (`ACTIVE_CALLS` dict, `EVENT_QUEUES` list) lives in process memory. **Do not change to multiple workers** — it would break SSE broadcasts and the shared call store. Restarts intentionally clear in-memory state (persistent data lives in `DATA_DIR`, see below).

**One file, inline everything.** `server.py` contains the HCP integration, the Retell custom-tool endpoints, the Retell lifecycle webhook + inbound dynamic-vars webhook, the SSE stream, the AI call-quality reviewer, and the entire dashboard + analytics pages (HTML + CSS + JS as Python triple-quoted templates). Atomic deploys, no asset pipeline.

### Data flow

```
Caller phone ──▶ Retell AI (hosts "Sarah v2", single-prompt LLM)
                    │
                    ├── webhook ─────────▶ /retell/inbound        (returns dynamic vars:
                    │                       returning-caller recap + HCP profile lookup
                    │                       by phone, concurrent via ThreadPoolExecutor)
                    │
                    ├── tool_call ───────▶ /check-availability     (queries HCP /jobs)
                    ├── tool_call ───────▶ /create-appointment     (HCP customer dedupe + job)
                    ├── tool_call ───────▶ /transfer-emergency     (schedule-or-transfer, alerts)
                    │
                    └── webhook ─────────▶ /webhook/retell  (call_started | call_ended | call_analyzed)
                                              │
                                              ├─▶ ACTIVE_CALLS dict ──▶ broadcast_event() ──▶ SSE /stream ──▶ Browser
                                              │
                                              └─▶ notify_event() ──┬─▶ Telegram alert
                                                                   ├─▶ Message Center (DATA_DIR/messages.json + SSE)
                                                                   └─▶ iPhone/PWA web push
              poll_call_transcript() runs as a gevent greenlet for active calls,
              hitting Retell's API ~every 1.5s to stream live transcript to the dashboard.
```

All five Retell-facing POST endpoints (`/check-availability`, `/create-appointment`, `/transfer-emergency`, `/retell/inbound`, `/webhook/retell`) verify the **`X-Retell-Signature`** header (see *Signature verification* below).

### Retell tools (`retell/planning/retell_tool_definitions.json`)

Custom-tool definitions whose URLs point at production (`https://hvac-retell-alfredo-production.up.railway.app/...`). **Retell ignores this file at runtime** — it's a copy-source for re-pasting into the Retell dashboard, or a reference when editing tools via the API. Keep it in sync with the live tool schemas.

### Notifications — unified `notify_event()`

`notify_event(ico, title, body, tg_text, tg_parse, call_id, tag)` is the **single place** that fans one alert out to three channels with identical content:
1. **Telegram** — rich `tg_text` (HTML/Markdown) if given, else `*title*\nbody`. Bot **@hightechac_alerts_bot**, chat id `6227760301`, token in `.env`/Railway as `TELEGRAM_BOT_TOKEN`. (Full writeup: `docs/TELEGRAM_BOT_CONTEXT.md`.)
2. **Message Center** — persisted to `DATA_DIR/messages.json` (capped 100) + broadcast live as SSE `type:"message"`. Rendered as WhatsApp-style threads grouped by caller phone (`peer_key`). Endpoints `GET /api/messages`, `POST /api/messages/clear`.
3. **iPhone/PWA web push** — `send_web_push(...)`; subscribe/unsubscribe at `/api/push/subscribe` & `/api/push/unsubscribe`; `/api/push/test` exercises the whole loop.

Routed through it: `call_started`, `call_analyzed` (rich wrap-up — name, summary, outcome, sentiment, follow-up, lead source, booking + tap-to-copy confirmation text), and emergency transfers. The wrap-up fires at **`call_analyzed`** (a few seconds post-hangup, where Retell's analysis data exists), not `call_ended`. **Do not re-add client-side push on call_started/call_analyzed** — that path was removed; doing so produces duplicate alerts.

### Returning-caller profile lookup + HCP dedupe

On an inbound call, `/retell/inbound` looks up the HCP customer **by calling phone number** (concurrent with the call-history recap, 2.5s deadline) and returns dynamic vars (`customer_found`, `customer_first_name`, address fields, `customer_has_email`, …). Sarah confirms identity + house number (digit by digit, never reading the full street back), asks for email only if missing, then `create_appointment` **reuses that HCP customer** instead of creating a new record every call.

**`create_appointment` is server-enforced:** if a profile was found it refuses to book unless the agent passes `profile_confirmed: true`, returning `{needs_profile_confirmation, say_to_caller, message}` so the agent must ask and retry. This exists because prompt-only confirmation failed repeatedly (the agent kept booking silently), which had caused hallucinated office addresses, fake emails, and duplicate HCP profiles piling up for a single caller. `INBOUND_CONTEXT_SKIP_NUMBERS` suppresses only the "welcome back" recap (the profile lookup still runs) — used for the test number so repeat calls don't say "welcome back" but the confirm flow stays testable.

### Emergency flow (`/transfer-emergency`)

After the caller accepts the `$120` emergency fee, Sarah offers two paths: **(a) schedule** the soonest visit (`is_emergency: true`) or **(b) transfer now** to the on-call tech. On transfer she *offers* (doesn't force) to collect name/address/email first; the caller can decline and be transferred immediately (`transfer_emergency` has no required fields). The dialed destination is the dashboard-assigned **Emergency / on-call** transfer contact, falling back to the hardcoded `EMERGENCY_TECH_NAME` / `EMERGENCY_TECH_PHONE` (Keivin Rivero) when unassigned — the same name+number is used for both the actual `transfer_to` and the Telegram alert so they never drift.

### Time and scheduling rules (HCP integration)

- HCP returns UTC; Orlando is `America/New_York` (`LOCAL_TZ`). All slot math runs in local time.
- Service hours: 6 AM – 10 PM, 7 days, 2-hour arrival windows, 7 days lookahead.
- Non-emergency bookings require a **12-hour lead** (`MIN_BOOKING_LEAD_HOURS`, enforced in both `check_availability` and `create_appointment`).
- `FIELD_TECHS` is a hardcoded list of HCP employee IDs; `find_available_tech()` returns the first tech free for the entire requested slot.
- `DO_NOT_BOOK_SERVICES = ["duct cleaning"]` — collected as callbacks, not booked.
- `SERVICE_AREA` is hardcoded; out-of-area requests get a soft "we'll call you back."
- Email is required on bookings (unless already on file for a returning caller).

### Transfer-contact manager

Transfer destinations are dashboard-managed, persisted to `DATA_DIR/transfer_contacts.json`, assigned to roles **alfredo / human / emergency** via `/api/transfer-contacts` + `/assign`. `/retell/inbound` passes the assigned numbers as dynamic vars (`alfredo_transfer_number`, `human_transfer_number`), falling back to env (`ALFREDO_TRANSFER_PHONE` / `HUMAN_TRANSFER_PHONE`). Retell transfer tools: `transfer_to_alfredo`, `transfer_to_human` (replaced the old `transfer_to_office`).

### On-call scheduling

On-call picks are persisted to `DATA_DIR` (was `/tmp`, which got wiped on every redeploy — that wipe was why the agent ignored on-call selections). Managed via `/api/oncall` (GET/POST/DELETE by date).

### AI call-quality reviewer

A background subsystem reviews finished calls with Claude and surfaces recommendations:
- Per-call review (`REVIEW_MODEL`, default `claude-haiku-4-5`) every `REVIEW_INTERVAL_S` (~5 min): `/api/review/<call_id>`, `/api/review/<call_id>/run`.
- Daily synthesis (`SYNTH_MODEL`) at `SYNTH_HOUR_LOCAL` (8 AM ET): `/api/synth/run`.
- Recommendations: `/api/recommendations` (+ `/apply`, `/revert`), `/api/agent/global-prompt`, `/api/admin/backfill`.
- Stored in SQLite `calls.db` under `DATA_DIR`.

### Signature verification (`RETELL_VERIFY_MODE`)

The 5 Retell-facing endpoints verify `X-Retell-Signature` (`v={unix_ms},d={hex}`, `hex == HMAC-SHA256(RETELL_API_KEY, raw_body + unix_ms)`; helper `_retell_signature_valid()`, decorator `require_retell_signature`). Rollout env `RETELL_VERIFY_MODE` = `off | monitor | enforce` (default `monitor`):
- **monitor** — verifies + logs `[retell-verify] ok {path}` or a mismatch warning, but always processes (never breaks live traffic).
- **enforce** — rejects missing/invalid with 401.

**To finish hardening:** after a real call, check Railway logs — if all 5 endpoints log `ok`, set `RETELL_VERIFY_MODE=enforce`. Retell only documents the lifecycle webhook as signed; whether it signs tool calls + the inbound webhook is what monitor mode confirms. Any endpoint logging `missing` on real traffic must stay out of enforce or it'll 401 and break that path.

### Dashboard internals

- `DASHBOARD_HTML` / analytics are Python triple-quoted Jinja templates. Jinja interpolation is **only** `{{ logo_data_uri }}`. Don't introduce more `{{ }}` / `{% %}` without escaping the surrounding JS template literals.
- Inline SVG icons must carry a `class="icon|icon-sm|icon-xs"` attribute. A defensive `svg:not([class*="icon"])` CSS fallback exists because an unsized SVG renders at the browser default 300×150 (this bug already hit the transcript area once).
- Brand colors are intentional: **green = live/active**, **brand red `#C4080C` = brand identity** (logo, primary CTA). The current redesign layers a dark/cyan app shell with mobile bottom-tabs (Calls / Insights / On-Call / Messages). Don't conflate live-state green with brand red.
- SSE `snapshot` events replay existing calls on reconnect; toasts/chimes/push are gated behind a `snapshotReceived` flag so a reload doesn't fire 50 alerts.
- Logo loader (`_load_logo_data_uri`) checks four paths so the file works whether `server.py` runs at repo root or inside `deploy/`.

## Editing the voice agent (Retell API)

Prompt/tool edits go directly to Retell via API — no manual dashboard pasting. `RETELL_API_KEY` is in `.env`. **The agent + LLM are published**, so:

1. **You can't `PATCH` a published LLM** (returns 400 `Cannot update published LLM`). Use create-draft → edit → publish.
2. `POST create-agent-version/{agent_id}` with `{"base_version": <current published>}` → a new draft agent + editable LLM (non-destructive).
3. `GET get-retell-llm/{llm_id}` (now returns the draft) → targeted string-replace, asserting the old string exists first.
4. `PATCH update-retell-llm/{llm_id}` with `{"general_prompt": "..."}`. Prompt lives on the LLM; analysis fields / voice config live on the **agent** (`update-agent`) — both edited on the same draft.
5. `POST publish-agent/{agent_id}` with `{"version": <draft>, "version_description": "..."}`.
6. Mirror the edit into `retell/planning/retell_agent_prompt_v2.md`.

Gotchas: agent vN ↔ LLM vN are coupled 1:1; `get-*` returns the LATEST version (a fresh draft after publishing), not necessarily the live one — **verify with `get-agent-versions` (latest `is_published`)**, don't trust a passed version number. **Use `curl`, not Python urllib** (urllib hits `CERTIFICATE_VERIFY_FAILED` on this machine); don't use `-w "HTTP:%{http_code}"` on the JSON-returning calls (it corrupts the body).

Prompt-edit style: keep edits **tight and high-signal** — the prompt is large and billed per token on every call, so every word is paid for forever.

## Common commands

```bash
# Local dev (needs .env with HCP_API_KEY, RETELL_API_KEY, DASHBOARD_PASSWORD, …)
python3 server.py                          # Flask dev server on :8080

# Production deploy — see "Railway deploy recipe" above. NOT a blind cp to deploy/.

# One-off client-deliverable PDF generators (run from repo root)
python3 proposals/generators/generate_proposal.py
python3 proposals/generators/generate_contract.py
python3 proposals/generators/generate_intake_form.py
python3 retell/generators/generate_retell_flow_v2.py
```

There are no automated tests, lint config, or build step. Manual test plans live in `docs/TEST_PLAN_v2.md`; the LLM-simulation suite is in `retell/planning/RETELL_SIMULATIONS.md` (Retell's sim/test API mocks tools).

## Required environment variables

| Var | Used for |
|---|---|
| `HCP_API_KEY` | Housecall Pro REST API auth |
| `RETELL_API_KEY` | Retell REST API (transcript polling, force-end, signature verify) |
| `DASHBOARD_PASSWORD` | Required `?key=` to view `/dashboard` |
| `TELEGRAM_BOT_TOKEN` | Telegram alert bot (chat id `6227760301`) |
| `ANTHROPIC_API_KEY` | AI call-quality reviewer |
| `RETELL_AGENT_ID` | Reviewer / prompt-recommendation features |
| `RETELL_VERIFY_MODE` | `off`/`monitor`/`enforce` for signature checking (default `monitor`) |
| `MIN_BOOKING_LEAD_HOURS` | Min lead time for non-emergency bookings |
| `INBOUND_CONTEXT_SKIP_NUMBERS` | Numbers that skip the "welcome back" recap (e.g. test #) |
| `ALFREDO_TRANSFER_PHONE` / `HUMAN_TRANSFER_PHONE` | Fallback transfer destinations |
| `DATA_DIR` | Persistent state dir (Railway volume `/data`; falls back to `./data`) |
| `REVIEW_MODEL` / `SYNTH_MODEL` / `REVIEW_INTERVAL_S` / `SYNTH_HOUR_LOCAL` | Reviewer tuning |
| `DEFAULT_EMPLOYEE_ID`, `OWNER_PHONE` | Optional fallbacks |

`PORT` is set by Railway — don't override in production. All vars are already configured on the Railway service.

## Production URLs

- Dashboard: `https://hvac-retell-alfredo-production.up.railway.app/dashboard?key=<DASHBOARD_PASSWORD>`
- Analytics: `/analytics?key=<DASHBOARD_PASSWORD>`
- Retell webhooks: `/webhook/retell`, `/retell/inbound`
- Tool endpoints: `/check-availability`, `/create-appointment`, `/transfer-emergency`
- Health: `/health`
</content>
</invoke>
