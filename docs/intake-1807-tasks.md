# Intake Agent — Required Tasks (2026-07-18)

## Context

`intake_agent` (`backend/pipeline/agents/intake.py`, on the `intake-agent`
branch) is functionally complete and correct as a node — see
`docs/intake_agent.md` for its responsibilities, inputs, and output
contract. **Do not re-derive or contradict that doc.** This file lists only
what's required *around* `intake_agent` so it actually receives real input
and its output is actually usable, in both run modes.

**Terminology (final — matches `docs/intake_agent.md`):**
- **Dev mode** = no Redis/Postgres/Docker required, `main_local.py`,
  in-process synchronous execution.
- **Demo mode** = Redis-backed queue + worker process, `develop` branch's
  `routers/campaigns.py` + `worker/main.py`, production-like.

If either mode's name is used the other way anywhere else in this repo's
docs, this mapping wins.

---

## Task 1 — Brief plumbing (demo mode only)

**Dev mode: already works.** `main_local.py`'s `/campaigns/{id}/run` takes
`CreateCampaignRequest` as the request body and threads it into
`_initial_state()` synchronously. No change needed here beyond Task 2.

**Demo mode: broken today — brief never reaches the worker.**
`routers/campaigns.py::create_campaign` enqueues only
`{campaign_id, org_id, brand_id, user_id, request_id}` to
`campaigns:queue`. `worker/main.py::process_campaign` then calls
`build_initial_state(...)` **without** `brief=`, even though
`pipeline/initial_state.py::build_initial_state` already accepts a
`brief: CreateCampaignRequest | None` parameter and knows how to convert it
to a `CampaignBrief`.

Changes:
- `backend/pipeline/schemas.py::CampaignTask` — add the brief fields (or
  embed the full `CreateCampaignRequest` as a nested field) so the queue
  payload can carry them.
- `backend/api/routers/campaigns.py::create_campaign` — include brief fields
  in the dict pushed to Redis (`redis.lpush(QUEUE, json.dumps(task))`).
- `backend/worker/main.py::process_campaign` — parse the brief fields back
  out of `task_payload` and pass them as `brief=` into `build_initial_state`.

Carrying the brief through the Redis payload is the minimal correct fix — do
not have the worker re-fetch the brief from a DB row unless a `campaigns`
table with persistence-on-create already exists.

---

## Task 2 — Resolve the dual-writer overlap on `state["brief"]`

Both entrypoints currently pre-seed `state["brief"]` *before* `intake_agent`
runs (dev mode: a raw dict; demo mode, once Task 1 lands: `build_initial_state`
converting `CreateCampaignRequest` into a `CampaignBrief`), and then
`intake_agent` re-validates and overwrites `brief` again. This works by
accident today because `CampaignBrief` and the raw request dict share field
names, but it's two writers on one field and should be cleaned up before
this ships.

Change:
- Add a new `OmniBrandState` field, `intake_request: CreateCampaignRequest |
  dict | None`, to `backend/pipeline/state.py` for the **unvalidated** raw
  input.
- `_initial_state()` (dev mode) and `build_initial_state()` (demo mode) set
  `intake_request`, not `brief`. `brief` stays `None` until `intake_agent`
  validates it.
- `backend/pipeline/agents/intake.py::intake_agent` reads
  `state.get("intake_request")` instead of `state.get("brief")` as its raw
  input, and is the **sole** writer of the validated `brief` field — no
  change to `AGENT_WRITE_PERMISSIONS["intake_agent"]` (already includes
  `brief`, not `intake_request`).
- Update `docs/intake_agent.md`'s "Inputs required" section to reference
  `intake_request` instead of the current raw-dict-in-`brief` description
  once this lands, so the two docs don't contradict each other.

This is a schema change — per `CLAUDE.md`'s batching convention, do
`state.py` + `intake.py` + both entrypoints + test fixtures
(`backend/tests/test_pipeline_skeleton.py::_empty_state`) in one pass.

---

## Task 3 — Audit the intake decision (demo mode only)

`intake_agent` currently never calls `write_audit()`, a `CLAUDE.md`
invariant gap once this runs on `develop` (dev mode has no audit service at
all, so this is demo-mode-only).

Change:
- After validation, call `write_audit(db, entity_type="campaign",
  action="intake_validated" | "intake_rejected", entity_id=campaign_id,
  brand_id=..., org_id=..., after_val={"brief_valid": ..., "brief_validation_errors":
  ..., "budget_check_passed": ...})`.
- Import path: `from services.audit_service import write_audit` (already
  re-exported via `pipeline/agents/base.py`'s `__all__` on `develop`).
- Dev mode has no `services/audit_service.py` and no DB — do **not** add a
  hard dependency on `write_audit` in a way that breaks dev mode. Guard the
  call so it only runs when a `db` handle is present/configured, or keep
  demo-mode-only auditing in a thin wrapper at the `develop` call site
  rather than inside the shared agent body.

---

## Task 4 — `org_id` must come from auth, never the request body (demo mode only)

Not an `intake_agent` change, but a prerequisite for Task 1 landing safely:
`routers/campaigns.py` currently does `"org_id": body.brand_id,  #
placeholder until auth provides real org_id` — explicitly marked as a
placeholder in the existing code. Without this fix, `intake_agent` (and
everything downstream) can silently run against the wrong tenant's
`org_config`/`brand_config` once those are wired up.

Change:
- `backend/api/deps.py`'s auth dependency must resolve `org_id` from the
  API key, not accept it from `CreateCampaignRequest`.
- `routers/campaigns.py::create_campaign` should take the resolved `org_id`
  from the auth dependency (e.g. a `UserContext` dependency injected via
  `Depends(...)`), and should validate that `body.brand_id` actually belongs
  to that `org_id` before enqueueing — reject with `403`/`404` otherwise,
  before anything reaches Redis/the worker/`intake_agent`.
- Dev mode has no auth layer by design (`docs/quick-eval-branch.md`) — leave
  its hardcoded `org_id="local-org"` as-is. Do not add an auth dependency to
  `main_local.py`.

---

## Task 5 — Surface `intake_agent`'s output to the caller

`intake_agent`'s output (`brief_valid`, `brief_validation_errors`,
`budget_check_passed`, `tasks`, `errors`) is only useful if a caller can
actually see it.

- **Dev mode:** `/campaigns/{id}/run` already returns the full state
  synchronously, so this data is present — but unfiltered (raw
  `OmniBrandState`, not a stable schema). Switch the response to
  `CampaignDetailResponse`/`VariantSummary` (already defined in
  `pipeline/schemas.py`, currently unused) so intake's validation fields are
  exposed deliberately rather than as a side effect of dumping internal
  state.
- **Demo mode:** `POST /campaigns` returns `202` before `intake_agent` even
  runs, and `GET /campaigns/{id}/status` / `GET /campaigns/{id}` are both
  `501` today — there is currently no way for a caller to learn
  `intake_agent`'s result at all in demo mode. Implement `status`/`get` for
  real, returning at minimum `current_phase`, `brief_valid`,
  `brief_validation_errors`, `budget_check_passed`, `errors` — read via the
  same `AsyncPostgresSaver`/`thread_id=campaign_id` the worker already uses
  in `worker/main.py::process_campaign`, read-only, from the API process.
- **Both modes:** the injection screen and budget-vs-task-count check inside
  `intake_agent` are pure/regex/arithmetic, no LLM call, no DB — cheap
  enough to also run synchronously at the point of accepting the request
  (`routers/campaigns.py::create_campaign` for demo mode), so a bad brief
  gets a `422` immediately instead of only surfacing after the async
  pipeline runs. `intake_agent` keeps running the same checks regardless
  (defense in depth for direct worker/graph invocations) — intentional
  duplication, not something to remove from the agent when adding it at the
  API layer. Extract `_screen_for_injection` and the budget-estimate
  arithmetic from `intake.py` into a small shared module (e.g.
  `backend/pipeline/intake_validation.py`) so both call sites use the same
  logic instead of duplicating it.

---

## File touch summary

| File | Change |
|---|---|
| `backend/pipeline/schemas.py` | `CampaignTask` carries brief fields (Task 1) |
| `backend/api/routers/campaigns.py` | enqueue brief fields; resolve `org_id` from auth, validate `brand_id` ownership; run sync injection/budget check pre-enqueue; implement `status`/`get` (Tasks 1, 4, 5) |
| `backend/worker/main.py` | pass `brief=` into `build_initial_state` (Task 1) |
| `backend/pipeline/initial_state.py` | seed `intake_request` instead of `brief` (Task 2) |
| `backend/api/main_local.py` | seed `intake_request` instead of `brief`; update response shape (Tasks 2, 5) |
| `backend/pipeline/state.py` | add `intake_request` field to `OmniBrandState` (Task 2) |
| `backend/pipeline/agents/intake.py` | read `intake_request` not `brief`; add guarded `write_audit` call (Tasks 2, 3) |
| `backend/pipeline/intake_validation.py` (new) | shared injection/budget-check logic (Task 5) |
| `backend/api/deps.py` | `org_id` resolution from API key (Task 4) |
| `docs/intake_agent.md` | update "Inputs required" section once Task 2 lands |
| `backend/tests/test_pipeline_skeleton.py` | update `_empty_state`/fixtures for `intake_request` field (Task 2) |

## Verification

- `uv run pytest backend/tests -v` — all existing + new tests green after
  each task, not just at the end.
- Dev mode: `uv run uvicorn api.main_local:app --reload --port 8000`, then
  `POST /campaigns/{id}/run` with a valid body → confirm `tasks` populated
  and response uses the new envelope; with an invalid body (empty channels,
  injection phrase in `raw_text`) → confirm `brief_valid=False` surfaces
  clearly in the response.
- Demo mode (on `develop`, after porting): `make up && make migrate && make
  seed`, `POST /campaigns` with a valid body → `202` + `poll_url`; poll
  `GET /campaigns/{id}/status` until `current_phase` progresses past
  `intake_complete`; repeat with an invalid body → confirm `422` at
  `POST /campaigns` time (Task 5) without ever reaching the queue.
