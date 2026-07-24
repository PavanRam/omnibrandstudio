# Airtable-Driven Human Review — Design & End-to-End Testing Guide

Status: implemented and verified end-to-end (this session)
Supersedes the delivery-mechanism section of
`docs/superpowers/specs/2026-07-23-airtable-human-review-design.md` — that spec designed an
Airtable Automation ("Send webhook"/"Run script") as the inbound delivery path. In practice,
both of those Automation actions require Airtable's **Team plan**; on the Free plan they're
blocked outright (confirmed via the in-app upgrade prompt during testing). This guide documents
what's actually implemented and running: the same backend route, fed by a **polling script**
instead of a push-based Automation.

## 1. What this is

Airtable is a real reviewer action surface, not just a passive mirror. A reviewer opens the
`Reviews` table, reads the generated content, and sets `Decision` to `Approved`/`Rejected`
directly in the grid — no Postman, no app UI required. Postgres (`review_requests`) remains the
system of record throughout; Airtable never bypasses it.

## 2. Architecture

### 2.1 Outbound — system → Airtable (unchanged from original design)

When a campaign pauses for human review, `review_service.persist_review_batch()`:

1. Looks up the campaign creator's email (`campaigns.created_by → users.email`).
2. For each flagged variant, calls `airtable_service.sync_review()` — an **upsert** (Airtable
   `performUpsert`, keyed on `review_request_id`) so each review gets exactly one durable row,
   not a new row per event.

`review_service.apply_decision()` calls `sync_review()` again after any decision (from any
channel — Postman, app UI, or Airtable) so the grid always reflects the current outcome and sets
`Sync Status = "Synced"`.

### 2.2 Inbound — Airtable → system

**Design intent (blocked in practice):** an Airtable Automation ("When record matches
conditions": `Decision` is Approved/Rejected/Edited AND `Sync Status ≠ Synced") calling
`POST /reviews/{review_request_id}/airtable-decide` via "Send webhook" or "Run script". Both
actions are Team-plan-gated; clicking either on a Free-plan base immediately shows an upgrade
modal. **Not usable as designed without paying.**

**What's actually running:** `scripts/airtable_poll_reviews.py` — a standalone loop that:

1. Every 15s (configurable), queries Airtable's plain REST API (not an Automation, so it isn't
   plan-gated) with `filterByFormula` for rows where `Decision` is Approved/Rejected/Edited and
   `Sync Status ≠ Synced`.
2. For each match, calls the **exact same** `POST /reviews/{id}/airtable-decide` route the
   Automation would have called, with `airtable_record_id` taken natively from the API response
   (no `RECORD_ID()` formula field needed for this path).

The backend route itself doesn't know or care which mechanism called it — this design is
delivery-mechanism-agnostic by construction. If this project ever upgrades to Airtable Team, the
original Automation can be turned on with zero backend changes; the poller would just become
redundant (or could stay as a fallback).

### 2.3 The `/airtable-decide` route (`api/routers/reviews.py`)

Guarded by a **dedicated, narrow** permission scope — `require("airtable:sync")` — not the
broader `admin`/`editor`/`reviews:decide` set the human `/decide` route uses. Given
`{airtable_record_id, decision, reviewer_note, reviewer_email}`:

1. Normalizes `decision` casing (Airtable sends `"Approved"`, not `"approved"`).
2. Rejects `decision == "edited"` outright — a dropdown can't carry rewritten content; editing
   stays an app/Postman-only capability.
3. Validates via the same `ReviewDecision` Pydantic model the human route uses —
   `reviewer_note` is **required** when `decision == "rejected"` (one rule, enforced uniformly
   for every caller).
4. If `reviewer_email` is present, resolves it to a `users.id`
   (`review_service.resolve_reviewer_email`) and uses that as the decision's actor. If it
   **doesn't** resolve, the request is **rejected** (422) — never silently defaulted to the
   calling service key's identity. See §4 for why this matters.
5. Delegates to the existing `review_service.apply_decision()` / `resume_campaign()` — the exact
   same calls the human `/decide` route makes. No duplicated business logic.
6. **Always** — success, validation failure, or already-decided — writes the outcome back onto
   the *same* Airtable record via `airtable_service.mark_synced()`, so a reviewer sees the result
   in the grid within one poll interval, without checking logs.

### 2.4 Airtable field schema (as actually built)

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `Generated At` | Date (with time) | system | when the content was generated |
| `Requester Email` | Email | system | who requested the campaign that generated this content |
| `campaign_id` | Single line text | system | cross-reference |
| `variant_id` | Single line text | system | cross-reference |
| `Generated Content` | Long text | system | raw output of the content generator agent |
| `Personalized Content` | Long text | system | output of the personalization agent (blank if that stage didn't run/apply) |
| `Translated Content` | Long text | system | output of the translation agent (blank for the source locale) |
| `routing_reason` | Long text | system | why this was flagged for review |
| `Decision` | Single select: `Pending/Approved/Rejected/Edited` | **reviewer** | the actionable dropdown |
| `Reviewer Note` | Long text | reviewer | required when `Decision = Rejected` |
| `Reviewer Email` | Email | reviewer | attributes the decision to a real user account |
| `Sync Status` | Single select: `Not Synced/Synced/Error` | system | bookkeeping; lets the poller/Automation skip already-applied rows |
| `Sync Error` | Long text | system | human-readable reason when a decision couldn't be applied |
| `review_request_id` | Single line text | system | correlation key back to Postgres |
| `Record ID` | Formula `RECORD_ID()` | system | only needed for the (currently unused) Automation path; harmless to keep |

## 3. Security fix folded into this design

An earlier draft let *any* caller of the human `/decide` route pass a `reviewer_email` and have
the decision attributed to a different, real user in the audit log — an impersonation vector.
Fixed by: `apply_decision()` no longer accepts `reviewer_email` at all (the human route never
reads it); only the narrowly-scoped `/airtable-decide` route can resolve an actor override, and
only for an email that actually resolves to a real user (unresolvable → rejected, never a silent
fallback). Regression-tested in `test_reviews_decide_route.py` and
`test_reviews_airtable_decide.py`.

## 4. Backend change list (files touched)

- `backend/pipeline/schemas.py` — `ReviewDecision`: `reviewer_note` required when rejected; added `reviewer_email`, `airtable_record_id`.
- `backend/services/airtable_service.py` — `sync_review()` (upsert) + `mark_synced()` (record-id write-back), replacing the old append-only `upsert_review`/`patch_decision`.
- `backend/services/review_service.py` — `persist_review_batch()` mirrors content/timestamp/requester email; `resolve_reviewer_email()` added; `apply_decision()` unchanged in signature (no `reviewer_email` param — see §3).
- `backend/api/routers/reviews.py` — new `POST /{review_request_id}/airtable-decide` route + `airtable:sync` scope.
- `scripts/airtable_poll_reviews.py` — new standalone polling script (Free-plan-compatible delivery mechanism).
- `Makefile` — `make poll-reviews` target.
- Tests: `test_airtable_service.py` (extended), `test_review_decision_schema.py`, `test_reviews_airtable_decide.py`, `test_reviews_decide_route.py` (all new). 33 tests, all passing; full suite otherwise unaffected (3 pre-existing, unrelated failures in RAG/conversation-brief tests).

## 5. Local setup — from zero to testing

1. `.env` (repo root) needs, at minimum: `POSTGRES_PASSWORD`, `MINIO_PASSWORD`, `LANGFUSE_SECRET`, `LANGFUSE_SALT`, `GROQ_API_KEY` (free tier, powers both generation and the free judge panel), and — for the Airtable pieces — `AIRTABLE_API_KEY` (Airtable PAT), `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE=Reviews`, and `AIRTABLE_SYNC_API_KEY` (see step 3).
2. `make setup` — installs deps, generates JWT certs, brings up Docker, migrates, seeds prompts/org/brand.
3. Seed two API keys once (PowerShell, from repo root):
   ```powershell
   @'
   INSERT INTO api_keys (org_id, brand_id, name, key_hash, key_prefix, scopes)
   VALUES ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002','demo-key',
           encode(digest('omnibrand-demo-key','sha256'),'hex'),'omnibrand',
           ARRAY['campaigns:read','campaigns:write','reviews:read','reviews:decide']) ON CONFLICT (key_hash) DO NOTHING;

   INSERT INTO api_keys (org_id, brand_id, name, key_hash, key_prefix, scopes)
   VALUES ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002','airtable-integration',
           encode(digest('omnibrand-airtable-key','sha256'),'hex'),'omnibrand',
           ARRAY['airtable:sync']) ON CONFLICT (key_hash) DO NOTHING;
   '@ | docker compose exec -T postgres psql -U omnibrand -d omnibrand
   ```
   Add `AIRTABLE_SYNC_API_KEY=omnibrand-airtable-key` to `.env` — the poller sends this as
   `X-API-Key` when calling our own `/airtable-decide` route.
4. **Confirm the dev admin user actually exists** — `make up` is supposed to seed it, but if you
   ever bypass that chain (e.g. `docker compose up -d --force-recreate api` directly, as happened
   during this session's debugging), it won't. Check:
   ```bash
   docker compose exec -T postgres psql -U omnibrand -d omnibrand -c "SELECT email FROM users;"
   ```
   If empty: `docker compose exec -T api python scripts/seed_dev_admin.py`.
5. Build the Airtable base's `Reviews` table with the fields in §2.4 (exact names, case-sensitive).

## 6. Testing — Tier 1: Postman only (no Airtable needed)

### Postman variables

| Variable | Value |
|---|---|
| `base_url` | `http://localhost:8000` |
| `api_key` | `omnibrand-demo-key` (scopes: `campaigns:read`, `campaigns:write`, `reviews:read`, `reviews:decide`) |
| `airtable_key` | `omnibrand-airtable-key` (scope: `airtable:sync` only) |
| `campaign_id` | filled from Request 1's response |
| `review_request_id` | filled from Request 3's response |

### Request 1 — Create a campaign

```http
POST {{base_url}}/campaigns
Auth: none
Content-Type: application/json
```

```json
{
  "brand_id": "00000000-0000-0000-0000-000000000002",
  "objective": "Launch our new API",
  "target_audience": "Developers",
  "key_messages": ["Fast", "Reliable"],
  "channels": ["email"],
  "locales": ["en-US"],
  "audience_segments": ["core"],
  "token_budget": 2000,
  "raw_text": ""
}
```

Expected `202`: `{ "campaign_id": "019f...", "status": "queued", "poll_url": "/campaigns/019f.../status" }`
— copy `campaign_id` into the `{{campaign_id}}` variable.

### Request 2 — Poll until it pauses

```http
GET {{base_url}}/campaigns/{{campaign_id}}/status
Auth: none
```

Send every few seconds until `status` becomes `"awaiting_review"` (~10-45s). Note: it may
instead go straight to `"published"`/`"failed"` without ever pausing — see §8 on non-deterministic
judge routing. If that happens, retry with Request 1 again, or use the manual-row recipe in §7.

### Request 3 — List pending reviews

```http
GET {{base_url}}/reviews?status=pending&limit=20&offset=0
Auth: X-API-Key: {{api_key}}
```

Expected `200`:

```json
{
  "reviews": [{
    "review_request_id": "11cf88d6-...",
    "variant_id": "...", "campaign_id": "019f...", "task_id": "en-US_email_core",
    "locale": "en-US", "channel": "email", "segment": "core",
    "status": "pending", "routing_reason": "...", "sla_deadline": "...",
    "content": "...", "composite_score": 6.5, "scores_snapshot": [...]
  }],
  "limit": 20, "offset": 0, "count": 1
}
```

Copy `review_request_id` into the `{{review_request_id}}` variable.

### Request 4 — Decide via the human/Postman path

```http
POST {{base_url}}/reviews/{{review_request_id}}/decide
Auth: X-API-Key: {{api_key}}
Content-Type: application/json
```

Body — pick one:

```json
{ "decision": "approved", "reviewer_note": "ship it" }
```

```json
{ "decision": "edited", "edited_content": "Subject: Final copy\n\n...", "reviewer_note": "tightened CTA" }
```

```json
{ "decision": "rejected", "reviewer_note": "too generic, redo" }
```

Expected `200` (last pending review for the campaign):
`{ "review_request_id":"...", "decision":"approved", "status":"resumed", "campaign_status":"published" }`
Expected `202` (other reviews still pending):
`{ "review_request_id":"...", "decision":"approved", "status":"recorded", "campaign_status":"awaiting_review", "detail":"awaiting remaining reviews for this campaign" }`

### Request 5 — Verify the outcome

```http
GET {{base_url}}/campaigns/{{campaign_id}}
Auth: none
```

Expected: `"status": "published"` (or `"edited"` for an edit decision), `final_content` populated.

### Request 6 — `/airtable-decide` (the new route), all five outcomes

All five use the **same URL**: `POST {{base_url}}/reviews/{{review_request_id}}/airtable-decide`,
`Content-Type: application/json`. Use a **real, still-pending** `review_request_id` from Request
3 for 6b/6c/6d/6e (validation failures don't consume it, so the same id can be reused across
6b→6c→6d, but 6e will finally decide it — do 6e last). `airtable_record_id` can be any placeholder
string for Postman-only testing (`"recFAKE123"`) since the Airtable write-back silently no-ops
when Airtable isn't configured for the current caller/session — it's only exercised for real in §7.

#### 6a — Wrong scope → `403`

Proves the security fix: a general-purpose key can't call this route.

```http
Auth: X-API-Key: {{api_key}}     <-- the demo key, deliberately wrong
```

```json
{ "airtable_record_id": "recFAKE123", "decision": "Approved" }
```

Expected `403`: `{"detail":"Requires one of: airtable:sync"}`

#### 6b — Reject without a note → `422`

```http
Auth: X-API-Key: {{airtable_key}}
```

```json
{ "airtable_record_id": "recFAKE123", "decision": "Rejected", "reviewer_note": "" }
```

Expected `422`: detail contains `reviewer_note is required when decision is 'rejected'`

#### 6c — Unresolvable `reviewer_email` → `422`

Proves it rejects instead of silently falling back.

```json
{ "airtable_record_id": "recFAKE123", "decision": "Approved", "reviewer_email": "not-a-real-user@example.com" }
```

Expected `422`: `{"detail":"reviewer_email 'not-a-real-user@example.com' does not match any known user"}`

#### 6d — `Edited` decision → `422`

Editing isn't supported from this route.

```json
{ "airtable_record_id": "recFAKE123", "decision": "Edited", "reviewer_note": "rewrite it" }
```

Expected `422`: `{"detail":"Editing must be done via the app; use Approved or Rejected here."}`

#### 6e — Approve, attributed to a real reviewer → success

```json
{ "airtable_record_id": "recFAKE123", "decision": "Approved", "reviewer_email": "admin@omnibrand.local" }
```

Expected `200`: `{ "review_request_id":"...", "decision":"approved", "status":"resumed", "campaign_status":"published" }`
(or `"status":"recorded"`/`"awaiting_review"` if other reviews for the campaign are still pending)

## 7. Testing — Tier 2: real Airtable, end-to-end (verified working)

1. `make poll-reviews` (or `uv run python scripts/airtable_poll_reviews.py`) in its own terminal.
2. Create a campaign (`POST /campaigns`) and poll until `awaiting_review`.
3. **Caveat (see §8):** whether a review row actually appears depends on the judges' routing
   decision, which is non-deterministic — a single-channel campaign is not guaranteed to be
   flagged for human review; it may auto-approve/auto-reject instead. If `GET /reviews` shows
   nothing for your campaign, retry with a new one, or use the manual-row recipe below to test
   the Airtable integration in isolation from judge-routing randomness.
4. In the Airtable grid: set `Decision = Approved` (and optionally `Reviewer Email`) → within one
   poll interval, `Sync Status` flips to `Synced` and the campaign publishes.
5. For the reject path: set `Decision = Rejected` with no `Reviewer Note` → `Sync Status` flips
   to `Error` with the exact validation message in `Sync Error`. Fill in the note → next poll
   tick applies it, flips to `Synced`, and the campaign regenerates/re-pauses.

### Manual-row recipe (bypasses judge-routing randomness)

Useful when you specifically want to test the Airtable integration without waiting on judges to
flag something:

```sql
-- pick an existing content_variants row from any recent campaign, then:
INSERT INTO review_requests (id, variant_id, campaign_id, org_id, brand_id, routing_reason, status, sla_deadline)
VALUES (gen_random_uuid(), '<content_variants.id>', '<campaign_id>',
        '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002',
        'manual test row', 'pending', NOW() + INTERVAL '4 hours');
```

Then mirror it for real:

```python
# uv run python, from backend/
import asyncio
from services import airtable_service
asyncio.run(airtable_service.sync_review({
    "review_request_id": "<the id just inserted>",
    "campaign_id": "<campaign_id>", "variant_id": "<content_variants.id>",
    "routing_reason": "manual test row",
    "Generated Content": "...", "Personalized Content": "...", "Translated Content": "...",
    "Generated At": "...Z",
    "Requester Email": "admin@omnibrand.local", "Decision": "Pending", "Sync Status": "Not Synced",
}))
```

## 8. Real gotchas hit during this session's testing (worth knowing before you repeat this)

- **Docker bind-mount can serve stale files.** After a long-running dev session with many host
  edits, the `api` container's live-reload crashed on a leftover git conflict marker that had
  *already been fixed on the host* — the container's mount was stale. `docker compose restart`
  does **not** fix this (same mount, same process). `docker compose up -d --force-recreate api`
  does.
- **`.env` changes need a container recreate, not a restart** — env vars are read once at
  container creation.
- **Airtable's "Send webhook"/"Run script" Automation actions require the Team plan** — even
  during a trial, if the trial doesn't cover that tier. Confirmed by the in-app upgrade modal.
  This is why the polling script exists.
- **`ngrok` needs `winget install --id Ngrok.Ngrok`** (not `ngrok.ngrok` — case/naming differs
  from what you'd guess) **plus a one-time `ngrok config add-authtoken <token>`** before its
  first real run — `command not found` and `ERR_NGROK_4018` are two different, sequential
  problems, not the same one. (Turned out unnecessary once we switched to polling, since nothing
  needs to reach *into* your laptop — the poller only makes outbound calls.)
- **Judge routing to "flag" (human review) is non-deterministic.** It depends on judge
  disagreement / mean-score band, not a fixed policy — a single-channel test campaign is not
  guaranteed to produce a review row. Don't assume "awaiting_review" status means a review
  exists; check `review_requests` directly. Use the manual-row recipe (§7) to test the Airtable
  integration deterministically.
- **A backgrounded `uv run python script.py &` followed by `kill $PID` may not actually kill the
  process** — `uv run` doesn't always exec-replace itself with the child Python process, so the
  shell's PID and the real worker PID can differ, leaving an orphaned poller quietly running (and
  correctly doing its job) in the background. Harmless here since the route is idempotent, but
  confusing when you're trying to reproduce a "why did this seem to do nothing" moment. Prefer
  `timeout <n> uv run ...` for one-shot test runs instead of background+kill.
- **`seed_dev_admin.py` must actually run** — don't assume the dev admin user exists just because
  `make up`'s target chain includes it. If any container was recreated outside of `make up` (e.g.
  a targeted `--force-recreate` for an unrelated fix), that seeding step was skipped. Symptom:
  every `reviewer_email` you try comes back `422 does not match any known user`. Check
  `SELECT email FROM users;` directly.
