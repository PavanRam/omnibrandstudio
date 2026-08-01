# Airtable-driven human review — design

Status: approved for implementation planning
Date: 2026-07-23
Related code: `backend/services/airtable_service.py`, `backend/services/review_service.py`,
`backend/api/routers/reviews.py`, `backend/pipeline/schemas.py` (`ReviewDecision`),
`docs/review-gate-testing-guide.md`

## 1. Problem

Airtable is currently an **outbound-only, best-effort mirror**: `persist_review_batch()`
pushes a row when a review is created, and a decision made through
`POST /reviews/{id}/decide` (Postman/API only) pushes a second, disconnected row. Reviewers
cannot act from Airtable at all — the only way to approve/reject/edit is to call the API
directly. Postgres (`review_requests`) remains the system of record throughout this design;
nothing here changes that.

This project wants three things:

1. The Airtable row a reviewer looks at should carry the generated content itself, the exact
   timestamp the content was generated, and the email of the user whose campaign/brief
   requested that content.
2. A reviewer should be able to approve or reject **directly in Airtable**, via a dropdown,
   instead of needing Postman.
3. When a reviewer rejects, they must supply a `Reviewer Note` — enforced, not optional.

## 2. Scope boundary

Approve/Reject become first-class Airtable actions. **Editing content is out of scope for
Airtable** — `edited` decisions (which require submitting rewritten `edited_content`) remain a
Postman/API/app-UI-only capability, because a single-select dropdown has nowhere to carry a
content rewrite. If a reviewer selects the `Edited` option from the Airtable dropdown anyway,
the sync rejects it with an explanatory `Sync Error` rather than silently ignoring it.

## 3. Architecture

### 3.1 Outbound: system → Airtable (on every review creation)

`persist_review_batch()` already inserts `review_requests` rows. It additionally:

- Looks up the campaign creator's email once per batch (`campaigns.created_by → users.email`).
- Captures `generated_at = datetime.now(UTC)` once (this is the same moment `content_variants`
  rows are inserted — no extra read-back query needed).
- For each review, calls a single `airtable_service.sync_review()` that **upserts** (Airtable
  `performUpsert`, keyed on `review_request_id`) a row with the content, the requester's email,
  the timestamp, `Decision = "Pending"`, and `Sync Status = "Not Synced"`.

Upserting on `review_request_id` (instead of always `POST`-ing a new record, as today) is what
makes a durable, reviewer-editable row possible — one row per review request, not one row per
event.

### 3.2 Reviewer acts in Airtable

The reviewer opens the grid, reads `Content`/`Routing Reason`, and sets `Decision` to
`Approved` or `Rejected`. For `Rejected` they should also fill `Reviewer Note` (enforced
server-side, see §3.4). They fill `Reviewer Email` with their own address so the decision is
attributable to their account.

### 3.3 Airtable Automation → webhook

Trigger: "record matches conditions" — `Decision` is `Approved`/`Rejected`/`Edited` **and**
`Sync Status ≠ Synced`. Action: **Send Webhook** to
`POST {api_base}/reviews/{review_request_id}/airtable-decide`, header
`X-API-Key: <dedicated integration key>`, JSON body built from the triggering record:
`{"airtable_record_id": RECORD_ID(), "decision": <Decision, lowercased>, "reviewer_note": <Reviewer Note>, "reviewer_email": <Reviewer Email>}`.

The integration key is a normal row in the existing `api_keys` table, but with a **dedicated,
narrow scope: `airtable:sync`** — not `reviews:decide`/`admin`/`editor`. No new auth mechanism
is introduced (still API-key only), but this route intentionally does *not* accept the same
broad set of credentials the human `/decide` route does. See §3.4 and §8 for why.

Firing on *any* Decision change (rather than gating the trigger on `Reviewer Note` being
non-empty) means a rejection with a missing note still reaches the backend, which can explain
the problem back into `Sync Error` — instead of the automation silently never firing and the
reviewer never learning why nothing happened.

### 3.4 New route: `POST /reviews/{review_request_id}/airtable-decide`

Guarded by a **new, narrower** dependency — `require("airtable:sync")` — not the
`_reviews_decide` set (`admin`/`editor`/`reviews:decide`/`campaigns:write`) the human route
uses. Body: `{airtable_record_id, decision, reviewer_note, reviewer_email}`.

1. Validate through the same `ReviewDecision` Pydantic model Postman uses. The model gains one
   rule, applied uniformly to **every** caller (Postman, app UI, Airtable): `reviewer_note` is
   required when `decision == "rejected"`. Also reject `decision == "edited"` from this route
   specifically with a clear message (see §2).
2. If `reviewer_email` is present, resolve it to `users.id`
   (`review_service.resolve_reviewer_email`, a plain `SELECT id FROM users WHERE email = :email`)
   and use that as the decision's actor **instead of** the calling credential's own identity —
   attributing the decision to the reviewer who actually set it in Airtable, not to the shared
   integration key. If it does **not** resolve, **reject the request** (422 + a `Sync Error`
   explaining why) rather than silently falling back to the service identity — see §8 for why
   this can't be a soft fallback. `apply_decision()` itself takes no `reviewer_email` parameter;
   only this narrowly-scoped route may compute an actor override, and only for a name that
   actually resolves.
3. On success, call the existing `review_service.apply_decision()` then
   `review_service.resume_campaign()` — the exact same calls `decide_review()` already makes.
   No new business logic is introduced; this route is a thin adapter in front of code that is
   already tested.
4. **Always**, success or failure, call
   `airtable_service.mark_synced(airtable_record_id, status=..., error=...)` to PATCH that
   Airtable record: `Sync Status = "Synced"` (clearing `Sync Error`) on success,
   or `Sync Status = "Error"` with a human-readable `Sync Error` message on failure. Respond
   `200` to the Automation either way — Airtable should not retry-storm a validation failure;
   the reviewer fixes it and re-triggers by editing the record again.

### 3.5 Loop prevention

The write-back in step 4 sets `Decision` and `Sync Status = "Synced"` in the **same** PATCH.
Because the Automation's trigger condition requires `Sync Status ≠ Synced`, that combined write
never re-fires the automation. The same mechanism covers Postman-originated decisions: when a
reviewer decides via the API instead of Airtable, `apply_decision()` calls
`airtable_service.sync_review()` directly with `Sync Status = "Synced"` already set, so the grid
reflects the outcome without ever triggering a webhook back to itself.

### 3.6 Dual-mode operation (local Docker/Postman *and* production)

The route in §3.4 is a plain, transport-agnostic FastAPI endpoint — there is no "local" vs
"production" branch anywhere in the backend. The only environment-specific detail is which URL
the Airtable Automation is configured to call, and that lives in Airtable's own UI, not in code:

- **Local, Postman-only** (no Airtable, no tunnel): call the new route directly with a
  hand-built body, to validate `apply_decision`/`resume_campaign`/write-back against a local
  `make up` stack. See §5, Tier 1.
- **Local, real Airtable**: expose the local API via a tunnel (ngrok / Cloudflare Tunnel) and
  point the Automation's webhook URL at the tunnel's HTTPS URL. See §5, Tier 2.
- **Production**: identical Automation configuration, pointed at the real deployed domain
  instead of the tunnel URL. No backend or Automation-logic changes between this and Tier 2.

## 4. Airtable field schema

Column order (left to right, as a reviewer scans the grid):

| # | Field | Type | Written by | Purpose |
|---|---|---|---|---|
| 1 | `Generated At` | Date (with time, ISO) | system | exact timestamp the content was generated |
| 2 | `Requester Email` | Email | system | email of the user whose campaign/brief generated this content |
| 3 | `campaign_id` | Single line text | system | cross-reference (existing field) |
| 4 | `variant_id` | Single line text | system | cross-reference (existing field) |
| 5 | `Content` | Long text | system | the generated content details (coalesced final → personalized → generated content) |
| 6 | `routing_reason` | Long text | system | why this variant was flagged for human review (existing field) |
| 7 | `Decision` | Single select: `Pending / Approved / Rejected / Edited` | **reviewer** | the actionable dropdown |
| 8 | `Reviewer Note` | Long text | reviewer | required when `Decision = Rejected` (server-enforced) |
| 9 | `Reviewer Email` | Email | reviewer | attributes the decision to a user account for the audit trail |
| 10 | `Sync Status` | Single select: `Not Synced / Synced / Error` | system | bookkeeping + Automation trigger guard (loop prevention) |
| 11 | `Sync Error` | Long text | system | human-readable reason when a decision couldn't be applied |
| 12 | `review_request_id` | Single line text | system | technical correlation key (existing field; kept last) |

The old free-text `status` and `decision` columns from the current mirror are superseded by the
`Decision` single-select — they represented the same concept across two fields in the old
append-only design.

## 5. Testing plan

**Tier 1 — Postman only** (extends `docs/review-gate-testing-guide.md` with a new numbered
request, same style as the existing Requests 1–5): call
`POST {{base_url}}/reviews/{{review_request_id}}/airtable-decide` with
`{"airtable_record_id": "recFAKE123", "decision": "rejected", "reviewer_note": ""}` → expect a
422 (missing note). Repeat with a real note → expect the same success/202 shape as today's
Request 4, proving this route exercises the identical `apply_decision`/`resume_campaign` path.
Airtable need not be configured for this tier; the write-back call simply no-ops, exactly as
`sync_review()` already no-ops today when Airtable isn't configured.

**Tier 2 — real Airtable, local backend via tunnel**: `make up`/`make run` locally, start a
tunnel (e.g. `ngrok http 8000`), configure the Airtable Automation's webhook URL to the tunnel's
HTTPS URL plus the dedicated `X-API-Key`, then drive the flow by hand: set `Decision = Rejected`
with no note → watch `Sync Error` populate within seconds; add the note → watch it flip to
`Synced` and the campaign regenerate/resume.

**Production**: identical Automation configuration, pointed at the real domain.

**Automated tests**: extend `backend/tests/test_airtable_service.py` for `sync_review()`'s
upsert semantics and `mark_synced()`; add `test_reviews_airtable_decide.py` covering approve,
reject-with-note, reject-without-note (422), already-decided (idempotent 200), a
`reviewer_email` that resolves (actor override applied), an unresolvable `reviewer_email`
(rejected — see §8), and `decision = "edited"` (rejected with an explanatory error) —
following the existing `httpx_mock` pattern already used in this repo. Also add
`test_reviews_decide_route.py` asserting the human `/decide` route never forwards a
caller-supplied `reviewer_email` anywhere (regression guard for §8).

## 6. Error handling summary

| Condition | Behavior |
|---|---|
| `Rejected` with empty `Reviewer Note` | Route rejects via `ReviewDecision` validation; `Sync Status="Error"`, `Sync Error="reviewer_note is required when rejecting"` written back; editing the note re-triggers the Automation. |
| `Decision = Edited` picked in Airtable | Rejected with `Sync Error="Editing must be done via the app; use Approved or Rejected here."` |
| `Reviewer Email` doesn't match any user | **Rejected** (422 + `Sync Error`) — not applied under the service identity. See §8: a silent fallback would let a typo (or a deliberate empty/garbage value) misattribute a real decision. |
| Review already decided (race between Postman and Airtable) | `apply_decision()`'s existing `ValueError` (409) is treated as idempotent success for write-back purposes — `Sync Status="Synced"`, no error surfaced, since the other channel's decision already stuck. |
| Airtable unreachable during outbound mirror | Unchanged — `sync_review()` stays best-effort/non-fatal, same policy as today's `_post`; Postgres remains source of truth. |
| Automation retries after a slow response | The route only performs the same DB writes and (when applicable) the same `resume_campaign()` call Postman's route already performs synchronously today — no new latency profile, no new timeout handling needed. |

## 7. Backend change list (for the implementation plan)

1. `pipeline/schemas.py` — `ReviewDecision`: add `reviewer_email: str | None` and
   `airtable_record_id: str | None`, extend the validator to require `reviewer_note` when
   `decision == "rejected"`.
2. `services/review_service.py` — new `resolve_reviewer_email(email) -> str | None` helper
   (plain `SELECT id FROM users WHERE email = :email`); `apply_decision()` itself is otherwise
   unchanged (it does **not** accept a `reviewer_email` parameter — see §8);
   `persist_review_batch()` looks up the requester email and passes
   `content`/`generated_at`/`requester_email` into the mirror call.
3. `services/airtable_service.py` — replace `upsert_review()` + `patch_decision()` with one
   `sync_review()` (Airtable `performUpsert` keyed on `review_request_id`) and a new
   `mark_synced(record_id, *, status, error=None)` for the webhook write-back.
4. `api/routers/reviews.py` — new route `POST /{review_request_id}/airtable-decide`, guarded by
   a **new, narrower** `require("airtable:sync")` dependency (not `_reviews_decide`). The route
   itself resolves `reviewer_email` (rejecting if unresolvable) *before* calling
   `apply_decision()`, passing the resolved id as a plain `actor_id` override. `decide_review()`
   (the human route) is otherwise unchanged and never reads `body.reviewer_email`.
5. `docs/review-gate-testing-guide.md` — new Postman request for the Tier-1 test, updated
   Airtable field table (§4), and a new "Automation + tunnel" setup section for Tier 2, including
   how to mint the `airtable:sync`-scoped integration key.
6. Tests per §5.

No `content_variants`/`review_requests` schema changes are required — every new mirrored value
(`generated_at`, `requester_email`) is derived from existing columns (`content_variants.created_at`,
`campaigns.created_by → users.email`).

## 8. Security: actor attribution must not be a spoofable field

An earlier draft of this design let `apply_decision()` accept a caller-supplied `reviewer_email`
directly, resolving it to a `users.id` and using that as the audit/`reviewed_by` actor — with a
silent fallback to the caller's own identity if it didn't resolve. That is an actor-impersonation
vector: **any** caller authenticated for `/reviews/{id}/decide` (any `admin`/`editor`/API key with
`reviews:decide`) could pass an arbitrary `reviewer_email` and have a decision recorded in the
audit log as having been made by a *different*, real user — without that user's knowledge or
consent. Two changes close this:

1. **Scope separation.** The webhook route is guarded by a dedicated `airtable:sync` scope, not
   `_reviews_decide`. Only a credential minted specifically for the Airtable integration can even
   reach the code path capable of overriding the actor — no admin/editor/human credential can.
   `apply_decision()` no longer has a `reviewer_email` parameter at all, so the human `/decide`
   route has no way to attribute a decision to anyone but its own authenticated caller, by
   construction (not by convention).
2. **Reject, don't fall back.** Within the webhook route, an unresolvable `reviewer_email` is a
   422 (with a `Sync Error` explaining why), not a silent pass-through under the service
   identity. A typo'd or garbage email must not result in an unattributed (or wrongly-attributed)
   decision being applied anyway.

Residual, accepted risk: **within** the Airtable grid itself, the `Reviewer Email` field is
self-reported free text — anyone with edit access to the base could type a coworker's address
into it. That's an inherent property of the feature as specified (attribution via a plain email
field a human types, rather than an Airtable paid-plan collaborator field with real identity) and
was an explicit, informed choice during design, not an oversight. What this section closes is the
*much* broader exposure of that same field being reachable — and actionable without any
resolution check — from every already-authenticated caller of the pre-existing human endpoint.
