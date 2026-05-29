# Deploy checklist — returning-caller profile lookup & dedupe

**Status:** built + tested in root workspace, **deploy held** (waiting on voice-agent worktree to be clear).
Built 2026-05-23. Touches `/retell/inbound` + `create_appointment` — the voice-agent worktree's lane, and that worktree is actively editing inbound (transfer-contacts modal, DATA_DIR on-call). Reconcile, don't clobber.

## What this feature does
On a returning caller, look up their HCP customer **by the calling phone number**, have Sarah confirm identity + house number ("Are you Miguel Barbosa, house number 1-3-1-9-9?"), ask for any missing field (email), then **book against that existing customer** instead of creating a new duplicate every call. If the caller says the on-file address is wrong, she collects a fresh street+city and attaches it to the same customer.

## Changes staged in ROOT (source of truth)
- `server.py`
  - `_digits10()` + `hcp_find_customer_by_phone()` — new helpers (after `hcp_post`).
  - `_customer_dynamic_vars()` + `_lookup_last_retell_call()` — new helpers (near `_inbound_empty_response`).
  - `/retell/inbound` — runs the Retell last-call lookup and the HCP customer lookup **concurrently** via `ThreadPoolExecutor` (2.5s deadline; works under both gunicorn-gevent and the dev server), emits `customer_found / customer_first_name / customer_last_name / customer_street_number / customer_city / customer_has_email`.
  - `_inbound_empty_response()` — now includes the customer_* defaults.
  - `create_appointment` — new `use_address_on_file` arg; find-or-create customer by phone (reuse → dedupe), reuse on-file address or attach a corrected one, backfill missing email.
- `retell_agent_prompt_v2.md` — Section 1 new vars; Section 5 returning-caller confirm step; Section 11 `use_address_on_file` note.
- `retell_tool_definitions.json` — added `use_address_on_file`; trimmed `required` to `[first_name,last_name,phone,date,start_time,end_time,service_type]` (street/city/state/zip no longer required).

## Local test done
`POST /retell/inbound` with `+14072897535` → `customer_found:true`, name/house-number/city populated; unknown number → `customer_found:false`. Latency 0.5–1.4s (well under Retell's ~3s). `create_appointment` reuse path reviewed (not run live to avoid more HCP junk).

## Deploy steps (when voice-agent worktree is CLEAR)
1. **Confirm no other session** is mid `railway up` or `publish-agent`, and that the voice-agent worktree isn't editing inbound/create_appointment.
2. **Port surgically into `deploy/server.py`** (it has diverged — Telegram, transfer-contacts, DATA_DIR; do NOT blind-cp from root). Graft the customer lookup onto deploy's inbound (keep its caller_phone/transfer-contact vars), and add the helper + create_appointment reuse block. Syntax-check.
3. **Deploy** via the clean-staging recipe (avoids the `railway up` indexing hang): `railway up --detach --service "HVAC Retell Alfredo"`.
4. **Verify prod inbound:** `curl -X POST https://hvac-retell-alfredo-production.up.railway.app/retell/inbound -d '{"call_inbound":{"from_number":"+14072897535"}}'` → expect the customer_* vars.
5. **Publish Retell (coupled — only AFTER step 4 passes):** create draft from live (v15) → update LLM `general_prompt` to match `retell_agent_prompt_v2.md` (Section 1 vars, Section 5 confirm step, Section 11 note) → **also update the `create_appointment` tool in the LLM's `general_tools`** to add `use_address_on_file` and trim `required` → `publish-agent`. (Do not publish before the server is live, or the prompt references undefined `{{customer_found}}`.)
6. **Live test:** returning call → she confirms name + house number → say "no, wrong" → she collects fresh address → book → verify **one** HCP job against the **reused** customer (no new duplicate).

## Deferred
- Clean up the 9 duplicate `+14072897535` profiles in HCP (user said leave for now). Until then the lookup picks the most-recent record (the bad office-address one) — the confirm step catches it.
