# 🎧 Sarah v2 — Test Plan v2 (4 scripts for the new features)

Converged from a proposer ↔ red-team debate. Targets the four things the original 5-script plan didn't cover: the **profile-confirm "NO" branch**, the **dashboard Emergency transfer contact**, **email backfill / text-only confirmation**, and a **regression sweep of the merged "Review fixes" (468d822)**.

Ground truth = **Housecall Pro** (Customers + Jobs, newest first) and the **Retell transcript** (`transcript_object` → tool args). The dashboard shows what Sarah *claims*; HCP/transcript show what *happened*.

## Before you start (one-time)
- Tabs: dashboard `…/dashboard?key=<PW>` (Transfer modal), HCP Customers, HCP Jobs.
- Note today's date/weekday + the Orlando clock (after 2pm Sat / all Sun / before 7am / ≥5pm weekday = after-hours = $120).
- **Test number +14072897535 is skip-listed:** no "welcome back" greeting (correct, not a bug), but the **HCP profile lookup still runs**, so Sarah finds the on-file profile. The lookup returns the most-recent record *with an address* — currently **"6148 Hanging Moss Rd"** (wrong; real is 13199 Winter Garden). Scripts exploit this.
- **Baseline the duplicates** so you can prove "no NEW customer," and note which `customer_id` holds the 6148 address (the anchor the lookup returns):
  ```bash
  curl -s "https://api.housecallpro.com/customers?q=4072897535&page_size=30" -H "Authorization: Token $HCP_API_KEY" \
  | python3 -c 'import sys,json;cs=json.load(sys.stdin)["customers"];print("TOTAL",len(cs));[print(c["id"],c.get("first_name"),c.get("last_name"),c.get("email"),[a.get("street") for a in (c.get("addresses") or [])]) for c in cs]'
  ```
- Pull transcript + tool args after each call:
  ```bash
  curl -s https://api.retellai.com/v2/list-calls -H "Authorization: Bearer $RETELL_API_KEY" -H "Content-Type: application/json" -d '{"limit":5,"sort_order":"descending"}' | python3 -m json.tool
  curl -s https://api.retellai.com/v2/get-call/<CALL_ID> -H "Authorization: Bearer $RETELL_API_KEY" | python3 -m json.tool
  # read transcript_object → tool_call_invocation args: profile_confirmed, use_address_on_file, street, city, phone, transfer_to
  ```
- Transfers fail on **web** calls. S1 & S2 = **real phone** (S1 needs the inbound profile lookup, which needs a real caller number). S3 = web ok. S4 = curl/browser, no call.

---

## Script 1 — Profile-confirm "NO" branch → corrected address, same customer, no new duplicate
**Place:** real phone. **Targets:** the server gate (`profile_confirmed`) · the caller rejects the wrong on-file profile → gives a corrected address → books under the **same** customer (dedupe), **not** a new duplicate · text-only confirmation.

**You open:** *"Hi, my AC isn't cooling — what's the soonest you can get someone out?"*

**Branch tree:**
- ✅ She calls `check_availability` first (no PII demanded), offers 2–3 slots → *"Let's take the earliest regular-hours one."*
  - 🐞 Demands name/address before checking availability → FAIL flag, then continue.
- She must confirm the profile out loud (because `customer_found=true`): *"I found your profile — am I right you're [Name], at house number **6148**, best number 407-289-7535? Can I book it under that?"*
  - 🐞 She books WITHOUT asking this → **FAIL** (the whole point).
- **THE NO PROBE:** *"No — that's wrong. It's **13199 Winter Garden Vineland Road, Orlando**."* (street + city only; no ZIP/state.)
  - ✅ She accepts it, doesn't re-argue, books, and reads back **13199 Winter Garden** + "someone will **text** you a confirmation."
  - 🐞 She re-books/insists on **6148**, or says 13199 aloud but the tool args still carry 6148 → FAIL.
  - 🐞 She says she'll **email** the confirmation → FAIL.
- **Idempotency probe** (after read-back): *"Can you re-confirm the whole thing one more time?"*
  - ✅ Re-reads the same confirmation, no second booking. 🐞 Fires `create_appointment` again → double-book FAIL.

**PASS:**
- She asked the profile-confirm out loud before booking.
- The **successful** `create_appointment` args carry `profile_confirmed: true`, `street`≈"13199 Winter Garden Vineland Road", `city:"Orlando"`, and **no** `use_address_on_file:true`. *(Either a single call with the flag, OR a `needs_profile_confirmation` bounce then a second call with it — both pass.)*
- HCP: exactly **one new job**, attached to the **same `customer_id`** that held the 6148 address (anchor from setup), now with a 13199 address added.
- **No NEW customer row** was created at call time (check the anchor's `created_at` is old).
- Promised **text**, never email; `date` arg has the correct year + weekday.

**FAIL (any):** booked under 6148 / wrong address in args · `profile_confirmed` absent/false on the successful call · a brand-new customer created for this number · said she'd email · second `create_appointment` on the re-read.

**Verify:** transcript args (above); HCP job → its `customer_id` == anchor; anchor now has a 13199 service address; tag `ai-booked`, real tech, window matches (UTC→Eastern).
**Cleanup:** delete the **one new job**. Do NOT delete the customer. (Leave the 13199 address unless you want it gone.)

---

## Script 2 — Dashboard Emergency transfer contact (dials the assigned number, not Keivin)
**Place:** real phone (mandatory). **Targets:** the new Transfer-modal **Emergency** role drives `transfer_emergency` · same name+number in the bridge **and** Telegram · safe to run.

**Safe setup (bridge rings YOU, not a real tech) — two steps:**
```bash
B=https://hvac-retell-alfredo-production.up.railway.app
# 1) create a contact pointing at YOUR cell, capture its id:
curl -s -X POST "$B/api/transfer-contacts?key=<PW>" -H "Content-Type: application/json" -d '{"name":"ZZTEST-ME","phone":"+1YOURCELL"}'
# 2) assign it to the emergency role:
curl -s -X POST "$B/api/transfer-contacts/assign?key=<PW>" -H "Content-Type: application/json" -d '{"role":"emergency","id":"<ID_FROM_STEP_1>"}'
# 3) verify it stuck:
curl -s "$B/api/transfer-contacts?key=<PW>" | python3 -m json.tool   # emergency_id == new id
```
⚠️ **While assigned, a real emergency caller would be bridged to your cell.** Do this in a quiet window, keep it short, and restore immediately after (cleanup below). If you'd rather not retarget, skip setup and **warn Keivin (786-532-8419)**, hang up the instant it bridges.

**You open:** *"My AC is completely dead, the house is baking, I need someone out right now — I can't wait for a scheduled slot."*

**Branch tree:**
- ✅ She names **$120** and asks for a yes → bait: *"How much? I thought it was eighty."* → ✅ holds $120 → *"Yes, go ahead with the $120."* (🐞 says $80 → FAIL; say yes anyway to keep testing.)
- ✅ She offers schedule-vs-transfer (§6) → *"Connect me now."* Give name + confirm your calling number + "no cooling at all."
  - 🐞 Transfers before the yes · transfers without stating $120 · books a slot instead of transferring → FAIL.
- ✅ She says "connecting you right now," `transfer_emergency` fires, **your cell rings**. Note it, hang up.

**PASS:** $120 stated + held; explicit yes before transfer; transcript `transfer_emergency` result `transfer_to` == **your cell** and `tech_name` == "ZZTEST-ME" (**not** 786-532-8419 / Keivin); your cell actually rang; **Telegram** "Emergency transfer" shows `Transferring to: ZZTEST-ME (<your cell>)` and a populated `Phone:`.
**FAIL (any):** `transfer_to` = Keivin despite the assignment · Telegram number ≠ `transfer_to` (drift) · transfer before yes · phone blank/"unknown" · booked a slot instead.

**Verify:** transcript `transfer_emergency` args (`phone` present) + result (`transfer_to`, `tech_name`); Telegram body; HCP emergency lead under your contact with "$120 acknowledged… Transferred to ZZTEST-ME".
**(Optional) fallback half-check:** clear the role (`assign` with `"id":null`), verify `emergency_id:null`, place a 2nd emergency call → `transfer_to` must be Keivin 786-532-8419 + Telegram says Keivin. **Warn Keivin / hang up instantly.**
**Cleanup (MANDATORY — most dangerous leftover):**
```bash
# restore emergency role to its prior value (or null = env Keivin fallback), then VERIFY:
curl -s -X POST "$B/api/transfer-contacts/assign?key=<PW>" -H "Content-Type: application/json" -d '{"role":"emergency","id":null}'
curl -s "$B/api/transfer-contacts?key=<PW>" | python3 -m json.tool   # confirm emergency_id back to Keivin/null
curl -s -X DELETE "$B/api/transfer-contacts/<ZZTEST-ME_id>?key=<PW>"
```
Delete the test emergency lead/customer in HCP. **Do not leave the live emergency line pointed at your personal number.**

---

## Script 3 — Email backfill + text-only confirmation
**Place:** web ok. **Targets:** email asked **only** when not on file · phrasing "for our records" (NOT "to send confirmation") · backfilled email PATCHes onto the **existing** customer · confirmation by **text**.

**⚠️ Precondition (read first):** the lookup picks the 6148 record, which **currently HAS an email** (`info@frassinogroup.com`) → `customer_has_email=true` → **Sarah won't ask, and backfill won't fire.** To actually test it you must first clear the email on that anchor record:
```bash
# find the anchor id (the 6148 record) from setup, then:
curl -s -X PATCH "https://api.housecallpro.com/customers/<ANCHOR_ID>" -H "Authorization: Token $HCP_API_KEY" -H "Content-Type: application/json" -d '{"email":""}'
# re-run the setup query to confirm that record's email is now empty
```
*(No-mutation alternative: skip the call and ask me to verify the backfill server-side via curl — I can confirm `create_appointment` PATCHes the email onto the existing customer without touching prod data.)*

**You open:** *"Hey, I need to book an AC tune-up — when can someone come?"*
- ✅ She offers slots; pick the earliest regular-hours one.
- Profile-confirm (house number 6148) → **say YES this time:** *"Yep, that's me, book it under that."* (→ `profile_confirmed:true` + `use_address_on_file:true`.)
- ✅ **The email ask:** because there's no email on file, she asks for one **"for our records / to have on file."**
  - 🐞 "to send you a confirmation" / "we'll email you the details" → **FAIL** (wrong framing).
  - Give `zztest+backfill@example.com`; she reads it back.
- ✅ On success: "someone will **text** you a confirmation." (🐞 "I've emailed you…" → FAIL.)

**PASS:** email asked with "for our records"-type framing; successful `create_appointment` args carry `email:zztest+backfill@example.com` + `profile_confirmed:true`; HCP shows the email **on the anchor `customer_id`** (not a new record); confirmation promised by **text**.
**FAIL (any):** email framed as "to send confirmation" · email missing from args · email saved to a new customer · said she'd email the confirmation.
**Verify:** transcript (quote the exact email-ask wording + args); HCP anchor record now shows the test email; closing turns say text.
**Cleanup:** delete the new job; **PATCH the anchor email back to empty** (or to its prior value) so the record is unchanged.

---

## Script 4 — Regression sweep of merged commit `468d822` ("Review fixes")
**What shipped:** (A) **security** — `/api/active-calls`, `/api/techs`, `/api/oncall`(GET), `/api/how-found-stats`, `/api/end-call`(POST), `/stream` now key-gated (dashboard JS appends `?key=`). (B) **correctness** — HCP `/jobs` pagination (double-book fix) + `check_availability` catches request timeouts. (C) **UX/visual.** Mostly curl/browser-verifiable.
**Place:** curl + browser; no call needed.

### A — security gates (expect 401 without key, 200 with key)
```bash
B=https://hvac-retell-alfredo-production.up.railway.app
for p in api/active-calls api/techs api/oncall api/how-found-stats; do
  echo -n "$p nokey="; curl -s -o /dev/null -w "%{http_code}" "$B/$p"
  echo    " key=$(curl -s -o /dev/null -w '%{http_code}' "$B/$p?key=<PW>")"; done
echo -n "stream nokey=";   curl -s -o /dev/null -w "%{http_code}\n" "$B/stream"
echo -n "dashboard nokey=";curl -s -o /dev/null -w "%{http_code}\n" "$B/dashboard"
echo -n "end-call nokey=";  curl -s -o /dev/null -w "%{http_code}\n" -X POST "$B/api/end-call/fake"
echo -n "health (open)=";   curl -s -o /dev/null -w "%{http_code}\n" "$B/health"          # expect 200 (intentionally open)
echo -n "check-avail {}=";  curl -s -o /dev/null -w "%{http_code}\n" -X POST "$B/check-availability" -H "Content-Type: application/json" -d '{}'  # expect 200, NOT gated (Retell calls it unauthenticated)
```
- ✅ PASS: the 4 GETs + `/stream` + `/dashboard` + `end-call` = **401 without key**, **200 with key**; `/health` = **200**; `/check-availability` with `{}` = **200** (and stays un-gated).
- 🐞 FAIL: any gated endpoint returns **200 without a key** (PII regression) · `/health` returns 401 · `/check-availability` requires a key or 5xx's on `{}`.
- **Live dashboard:** load `…/dashboard?key=<PW>` — status pill = **"Connected"** (proves `EventSource('/stream?key=…')` works with the gate). DevTools→Network: `active-calls`/`oncall`/`how-found-stats`/`stream` all carry `?key=` and return 200.

### B — no false "fully booked" (one web call, optional)
*"What's the soonest you can get someone out for an AC repair this week?"* → ✅ real slots offered. 🐞 "fully booked all week" with open hours → possible pagination/date regression; probe *"nothing tomorrow?"* and log dates. *(Note: truly proving the >200-job pagination needs a packed schedule we can't fake live — this asserts the observable behavior only.)*

### C — visual spot-checks (browser, ≤720px)
- Calls bottom-tab shows a **live-call count badge** while a call is active.
- On-call modal: **dark text on cyan** chips; "has-assignments" days render **green** (distinct from cyan "today").
- `/analytics?key=<PW>` at ≤720px → **single-column** layout, no horizontal overflow.
- Switch bottom tabs after opening a call detail → page is **not** scroll-locked.

**PASS:** A all correct + dashboard "Connected"; B real slots, no false "fully booked"; C all four render right.
**FAIL:** any unauthenticated 200 on a gated endpoint · dashboard can't connect with a valid key · false "fully booked" · any C item regressed.
**Cleanup:** none unless B led you to book (then delete that job).

---

## Global cleanup
Delete every test **job** and **lead** you created. Delete only **ZZTEST** customers — never the shared real customer behind the test number. **Re-verify the emergency transfer contact is restored** (`GET /api/transfer-contacts?key=…` → `emergency_id` back to Keivin/null) — a personal number left wired to the live emergency line is the single most dangerous leftover. If you cleared the anchor's email for S3, set it back.
