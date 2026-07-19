# T11 — Review Gate & Human Review — Design

- **Date:** 2026-07-19
- **Task:** T11 (Track: Review · Effort ~2d · Deps: T9, T7 · Checkpoint: CP4 — full pipeline)
- **Status:** Approved design, pending implementation plan
- **Source spec:** `docs/OmniBrand_Capstone_Tasks_1.xlsx` → tab "Phase 3 — Output & Review"

## 1. Goal

Implement the human-in-the-loop review gate: when the pipeline flags content for
human review, pause the LangGraph run (durably, survives worker restarts),
persist review requests with judge-score snapshots, expose a brand-scoped REST
API for reviewers, and resume the graph with the reviewer's decision — publishing
approved/edited content or regenerating rejected content.

### Subtasks (from the source spec)

- **T11.1** — `interrupt_before` on the `review_gate` node; state survives worker
  restarts; checkpoint holds a full variant + scores snapshot.
- **T11.2** — `review_requests[]`: snapshot all 3 judge `BrandScore`s, SLA
  deadline 4h from creation, reviewer assignment from `org_config`.
- **T11.3** — Review API: `GET /reviews` (pending, paginated, brand-scoped),
  `POST /reviews/{id}/decide` `{decision, reviewer_note, edited_content?}`.
- **T11.4** — Resume: `graph.aupdate_state()` with the decision; pipeline
  continues; `write_audit` for the decision; update `variant.status`.

## 2. Decisions (from brainstorming)

1. **Airtable = outbound mirror.** Postgres `review_requests` is the source of
   truth; decisions come through our REST API. Airtable is a best-effort mirror
   for reviewer visibility (config-gated, non-fatal — no-op when unconfigured).
2. **Decision outcomes:** `approved` → publish as-is; `edited` → publish with the
   reviewer's `edited_content`; `rejected` → loop back to regenerate the variant
   (another review round), capped by `MAX_REVIEW_ROUNDS`.
3. **Scope = full T11 machinery + a minimal trigger.** Build the gate, Postgres
   persistence, Airtable mirror, REST API, and resume/rerun wiring, PLUS a
   lightweight `confidence_aggregator` that flags review and emits placeholder
   `BrandScore` snapshots so the gate is demoable end-to-end. Real 3-judge
   scoring (T8) and full aggregation (T9) remain separate tasks and will replace
   the minimal `confidence_aggregator` wholesale.
4. **Resume executes API-direct.** `POST /reviews/{id}/decide` resumes inline via
   `aupdate_state` + `ainvoke(None)`, reusing the checkpointer plumbing already in
   `api/routers/campaigns.py`.
5. **Endpoints:** add `GET /reviews` + `POST /reviews/{id}/decide`; retire the
   existing placeholder `POST /campaigns/{id}/approval` (campaign-level, DB-status
   only) in favour of the per-variant `/reviews` model.
6. **Variant persistence happens at the review gate:** persist
   `content_variants` + `aggregated_scores` + `review_requests` together when the
   campaign pauses for review (scoped to T11).

## 3. Non-goals / scope boundaries

- Real 3-judge LLM scoring (T8) and full confidence aggregation / routing policy
  (T9) — the minimal `confidence_aggregator` is a placeholder trigger only.
- Publishing adapters (T12) — the resume routes to the existing
  `publishing_agent` stub.
- Persisting variants for **non-reviewed** campaigns (only reviewed campaigns
  persist `content_variants` in this task).
- Populating `org_config` from the DB — reviewer assignment reads whatever is in
  `org_config`, defaulting to unassigned when empty.
- Authn changes — reuse the existing `get_current_user` / `require(...)` deps.

## 4. Architecture & flow

```text
worker: graph.ainvoke(interrupt_before=["review_gate"])
  intake → generate → personalize → translate → 3 judges
      → confidence_aggregator  (minimal trigger: sets human_review_requested + review_requests[])
      → router:  needs_review? → review_gate   |   else → publishing_agent
  ── INTERRUPT fires before review_gate ──►  ainvoke returns (paused, checkpointed)
worker: sees paused state → persist content_variants + aggregated_scores + review_requests
        (Postgres) → mirror to Airtable → set campaigns.status = 'awaiting_review'
                        │
reviewer: GET /reviews                 (pending, brand-scoped, paginated, with content + scores)
reviewer: POST /reviews/{id}/decide    {decision, reviewer_note, edited_content?}
  API: update review_requests row + content_variants + Airtable + write_audit
       when ALL reviews for the campaign are decided →
         aupdate_state(decisions) → ainvoke(None)
                        │
  review_gate node runs: apply decisions to variants (status / final_content) →
       router:  any rejected? → content_generator (rerun, capped)  |  else → publishing_agent
```

`interrupt_before=["review_gate"]` is already wired in `build_graph`. `review_gate`
therefore runs **on resume** and is where decisions are *applied*; review requests
are *created* upstream by the minimal `confidence_aggregator` and *persisted* by
the worker at the pause — keeping the spec's "interrupt_before review_gate"
literally true.

### Conditional routing

- After `confidence_aggregator`, the router returns one of:
  `validation_subgraph` (existing reflexion loop) · `review_gate`
  (`human_review_requested` true) · `publishing_agent` (no review needed).
  This extends the current `reflexion_router` mapping (which today always sends
  the non-reflexion path to `review_gate`).
- After `review_gate`, a new router returns `content_generator` (any `rejected`
  and under the rerun cap) or `publishing_agent`.

## 5. Components

| File | Change |
|---|---|
| `backend/pipeline/agents/aggregation.py` (new) | Minimal `confidence_aggregator`: emit placeholder 3-judge `BrandScore` snapshots + `AggregatedScore`, set `human_review_requested`, build `review_requests[]` |
| `backend/pipeline/agents/review.py` (new) | Real `review_gate` node (apply decisions → variant status/final_content) + post-gate router (publish vs rerun) |
| `backend/pipeline/graph.py` | Swap `confidence_aggregator_stub`/`review_gate_stub` for real nodes; conditional routing; rerun cap |
| `backend/services/review_service.py` (new) | Persist variants + aggregated_scores + review_requests (Postgres); resume orchestration (`aupdate_state` + `ainvoke`); decision application |
| `backend/services/airtable_service.py` (new) | Best-effort outbound mirror (config-gated, non-fatal) |
| `backend/api/routers/reviews.py` (new) | `GET /reviews`, `POST /reviews/{id}/decide` |
| `backend/api/main.py` | Register `reviews` router |
| `backend/api/routers/campaigns.py` | Remove placeholder `POST /campaigns/{id}/approval` |
| `backend/worker/main.py` | Detect interrupt → persist review batch → set `awaiting_review`; leave completed campaigns as `published` |
| `backend/core/config.py` | `AIRTABLE_API_KEY` / `AIRTABLE_BASE_ID` / `AIRTABLE_TABLE`, `REVIEW_SLA_HOURS=4`, `MAX_REVIEW_ROUNDS=2` |
| `backend/pipeline/agents/base.py` | Extend `AGENT_WRITE_PERMISSIONS` only if new fields are written (none expected) |

No DB migration required — `review_requests`, `content_variants`, `aggregated_scores`
tables and the `awaiting_review` campaign status already exist (migrations 001, 002).

## 6. State & write-permissions

- `confidence_aggregator` writes `aggregated_scores`, `review_requests`,
  `human_review_requested` (its existing permitted set).
- `review_gate` writes `variants`, `current_phase` (its existing permitted set).
- No `state.py` schema change: `ReviewRequest`, `AggregatedScore`, `BrandScore`
  TypedDicts already exist. **SLA deadline and reviewer are DB-only columns**,
  set at persistence time (not part of the in-state `ReviewRequest`).
- A `review_round` counter is tracked in state (or via `variant.retry_count`) to
  enforce `MAX_REVIEW_ROUNDS`.

## 7. Minimal trigger — `confidence_aggregator`

For each content-bearing variant:
- Synthesize 3 placeholder `BrandScore`s (`judge_model` = claude / gpt4o / llama)
  with a `composite_score` and a `routing_decision`.
- Compute one `AggregatedScore` (weighted_mean, variance, consensus_level,
  routing_decision, routing_reason).
- **Routing** is threshold-based and **defaults to `flag`** so review triggers
  out-of-the-box (demoable). Honors `org_config["review_policy"]` when present:
  `always` (always flag) · `threshold` (flag when weighted_mean < threshold) ·
  `never` (auto-approve).
- On `flag`: set `human_review_requested = True` and append one `ReviewRequest`
  per flagged variant, carrying the 3-score snapshot and a `routing_reason`.

This node is a deliberate placeholder — T8/T9 will replace it with real judges +
aggregation. Its output contract (the state fields above) is what T11 depends on.

## 8. Persistence at the gate — `review_service.persist_review_batch`

Triggered by the worker when the paused state has `human_review_requested = True`.
In one transaction:
1. INSERT `content_variants` rows (uuid per `task_id`), mapping state variants
   (keyed by `task_id`) to DB variant ids.
2. INSERT `aggregated_scores` rows (FK `variant_id`).
3. INSERT `review_requests` rows: FK-valid (`variant_id`, `campaign_id`,
   `org_id`, `brand_id`), `scores_snapshot` JSONB (the 3 `BrandScore`s),
   `sla_deadline = now + REVIEW_SLA_HOURS`, `reviewed_by` from
   `org_config` (nullable), `routing_reason`, `status = 'pending'`.
4. Set `campaigns.status = 'awaiting_review'`.

FKs resolve because the `/campaigns` path already inserts the `campaigns` row
(and validates the `brands` row → `orgs` exists). Postgres persistence is the
source of truth: a failure marks the campaign `failed`. The Airtable mirror is a
separate, best-effort step.

## 9. API — `api/routers/reviews.py`

### `GET /reviews`
- Auth: `get_current_user` + `require("reviews:read")` (default scope name;
  reconciled against existing scopes during planning).
- **Brand-scoped:** `brand_id IN user.brand_ids` (org fallback for org-wide roles).
- `status=pending` default; paginated via `limit` (default 20) + `offset`.
- Each item includes enough to decide: `review_request_id`, `variant_id`,
  `campaign_id`, `routing_reason`, `status`, `sla_deadline`, the variant's
  channel/locale/segment + current content, `composite_score`, and the
  `scores_snapshot`.

### `POST /reviews/{id}/decide`
- Auth: `require("reviews:decide")`.
- Body: existing `ReviewDecision` `{decision: approved|rejected|edited,
  reviewer_note?, edited_content?}` (validated: `edited_content` required iff
  `edited`).
- Steps: validate review exists + `pending` + in brand scope (else 404/403/409) →
  update `review_requests` (status/decision/note/edited_content/reviewed_by/
  reviewed_at) → update `content_variants.status` and `final_content`
  (`edited_content` for `edited`, else the approved content) →
  `write_audit(entity_type="review_request", action="decide", …)` →
  mirror to Airtable.
- **Resume trigger:** if all `review_requests` for the campaign are decided →
  `aupdate_state(config, {decisions})` + `ainvoke(None, config)` → `review_gate`
  applies + routes → publish or rerun; update `campaigns.status`. Otherwise
  return `202 Accepted` (awaiting other reviews).

## 10. Airtable mirror — `services/airtable_service.py`

- Config-gated on `AIRTABLE_API_KEY` / `AIRTABLE_BASE_ID` / `AIRTABLE_TABLE`;
  **no-op** when any is unset.
- `upsert_review(...)` on creation (persist step); `patch_decision(...)` on
  decision. Uses `httpx` to the Airtable REST API.
- Best-effort: wrapped in try/except with a warning log; never fails the
  request or the pipeline (same policy as cost-attribution / Langfuse writes).

## 11. Rerun loop & error handling

- `review_gate` → router: any `rejected` and `review_round < MAX_REVIEW_ROUNDS`
  → `content_generator` (regenerate); else → `publishing_agent`. Exceeding the
  cap forces the rejected variant to a terminal `failed`/`rejected` status
  (no infinite loop).
- Airtable + audit failures: non-fatal (warning).
- Postgres persistence failure: campaign → `failed` (source of truth).
- Resume / `ainvoke` failure: caught, campaign → `failed`, logged.
- Deciding an already-decided review → `409`; review outside the caller's brand
  scope → `403`/`404`.

## 12. Config additions (`core/config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `AIRTABLE_API_KEY` | `""` | Airtable mirror (no-op when empty) |
| `AIRTABLE_BASE_ID` | `""` | Airtable base |
| `AIRTABLE_TABLE` | `"Reviews"` | Airtable table name |
| `REVIEW_SLA_HOURS` | `4` | SLA deadline offset |
| `MAX_REVIEW_ROUNDS` | `2` | Rerun cap |

## 13. Testing

- **Unit:** minimal `confidence_aggregator` (flags review, builds `review_requests`,
  3-score snapshot; honors `review_policy`); `review_gate` (applies decisions,
  publish-vs-rerun routing, rerun cap); `airtable_service` no-op when unconfigured;
  `ReviewDecision` validation.
- **Integration:** graph interrupts (`aget_state().next == ("review_gate",)` and
  state survives a fresh checkpointer connection); `persist_review_batch` writes
  FK-valid rows (seeded org/brand/campaign); `GET /reviews` returns pending,
  brand-scoped; `POST /reviews/{id}/decide` → resume → `published` (approve) /
  regenerate (reject) / cap-terminates; audit row written; multi-variant campaign
  stays paused until the last decision.
- Uses the `LOCAL_DEV_MODE` LLM-stub harness for graph runs; DB tests seed
  `orgs`/`brands`/`campaigns` rows so FKs resolve.

## 14. Acceptance criteria (maps to CP4)

- [ ] T11.1 — Campaign flagged for review pauses at `review_gate`; the checkpoint
  holds full variant + score state; a fresh process can read the paused state
  and resume it.
- [ ] T11.2 — `review_requests` persisted with all 3 judge `BrandScore`s,
  `sla_deadline = created + 4h`, reviewer from `org_config`.
- [ ] T11.3 — `GET /reviews` returns pending, paginated, brand-scoped reviews;
  `POST /reviews/{id}/decide` accepts `{decision, reviewer_note, edited_content?}`.
- [ ] T11.4 — Decision resumes the graph via `aupdate_state`; `write_audit`
  records the decision; `variant.status` updated; approved/edited publishes,
  rejected regenerates (capped).
- [ ] Airtable mirror reflects pending + decided reviews when configured; no-op
  and non-fatal when not.

## 15. Open items to finalize in the plan

- Exact RBAC scope names (`reviews:read` / `reviews:decide`) vs. existing scopes.
- Whether `review_round` lives on state or is derived from `variant.retry_count`.
- Airtable field mapping (column names in the base).
