# Telegram Bot — Context & Status

_Last updated: 2026-05-23. Written when closing the `notifications` worktree._

## What the Telegram bot does
The High Tech AC voice backend (`server.py`) sends Telegram alerts on two events:
- **`call_started`** (`/webhook/retell`) → "📞 Incoming call" with caller number, time, live dashboard link.
- **`/transfer-emergency`** → "🚨 Emergency transfer" with customer, address, problem, fee, tech.

Helper: `send_telegram_alert(message)` near top of `server.py` — fire-and-forget via `gevent.spawn`,
Markdown parse mode, failures logged not raised. Gated on `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.

This Telegram code **replaced** the old Twilio SMS alert (the `[sms] skipped - Twilio not configured`
log line is the OLD code). It is already merged into `deploy/main` (merge commit `b91afe0`).

## Bot identity
- Bot name: **High Tech AC Alerts**
- Username: **@hightechac_alerts_bot**
- Bot ID: `8926292605`
- Target chat ID: **`6227760301`** (Miguel)
- Token: stored in root `.env` as `TELEGRAM_BOT_TOKEN` (and in Railway). NOT committed here.

## Root cause of "alerts not arriving" (two separate bugs)
1. **Placeholder credentials.** Both `TELEGRAM_BOT_TOKEN` (truncated, 15-char secret vs valid 35)
   and `TELEGRAM_CHAT_ID` (`123456789`) were placeholders. `getMe` returned 404.
   → FIXED: real token + chat_id `6227760301` written to root `.env` and the worktree `.env`;
   user updated Railway vars. Direct API test (`sendMessage`) confirmed delivery works. ✅
2. **Stale production deployment.** Railway was running an OLD image that still had the Twilio
   SMS code and NO Telegram-on-`call_started` code. The merged Telegram code in `deploy/main`
   was never deployed. Updating env vars only redeployed the same stale image.
   → RESOLVED 2026-05-23: production now runs `ec24475` (Telegram alerts + Twilio removed +
   `_clean_summary` returning-caller fix). Verified live via `/retell/inbound` returning the
   CLEANED summary clause — and since `_clean_summary` and the Telegram code ship in the SAME
   commit, that confirms the Telegram code is live too.

## ✅ RESOLVED — last check needed: a real call
Production (service id `f019df56-b420-4f84-91b1-2df3090a6d99`) is on the correct commit.
The only remaining confirmation is a real inbound call logging `[telegram] sent` (not `[sms] skipped`):
```bash
PATH="$HOME/.npm-global/bin:$PATH" railway logs --service "HVAC Retell Alfredo" | grep "\[telegram\]\|\[sms\]" | tail -3
```

## ⚠️ Deploy gotcha — do NOT `railway up` from `deploy/`
`railway up` run from `deploy/` **hangs forever at `Indexing...`** because it chokes walking the
nested `.worktrees/` git worktree and `.git` (both gitignored, but it still tries). It burns CPU,
never uploads, never registers a build. `deploy/` also has **no linked service** (`Service: None`),
so a plain `railway up` prompts interactively.

**Working deploy recipe:**
1. Copy only runtime files to a clean dir (no `.git`, no `.worktrees`):
   `server.py Procfile requirements.txt logo.png assets/` → e.g. `/tmp/hvac-clean-deploy`
2. From `deploy/` (where the Railway project link lives in global config):
   `railway up "/tmp/hvac-clean-deploy" --path-as-root --service "HVAC Retell Alfredo" --ci`
3. `--ci` forces non-interactive, streams build logs, then exits. Build ~30-90s.

## Notes
- `deploy/` is its own git repo, separate from root. Edit in root, copy to `deploy/`, then deploy (see recipe).
- The `notifications` branch was fully merged into `deploy/main`; its worktree and the branch were removed. No unmerged work was lost.
- Deploy restarts the single gunicorn worker → clears in-memory `ACTIVE_CALLS`; deploy when no call active.
