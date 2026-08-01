# Review Gate Agent

## Purpose
The human-in-the-loop node. LangGraph pauses execution before this node
(`interrupt_before=["review_gate"]` in `graph.py`) until a reviewer decision
is injected into state via `graph.aupdate_state()`. On resume, `review_gate`
applies those decisions to the variants; `review_router` (conditional edge)
then decides whether to publish or loop back for regeneration.

File: `backend/pipeline/agents/review.py`

## Write permissions (`AGENT_WRITE_PERMISSIONS["review_gate"]`)
`variants`, `current_phase`, `review_round`

## Decision channel
Decisions arrive in the non-reducer `review_decisions` state channel, keyed
by variant `task_id`:
```
{"en-US_email_core": {"decision": "approved" | "rejected" | "edited",
                       "edited_content": "...", "reviewer_note": "..."}}
```
Populated either by a direct human/API call
(`POST /reviews/{id}/decide`) or by the Airtable Automation webhook
(`POST /reviews/{id}/airtable-decide`) — both routes converge on the same
`apply_decision()`/`resume_campaign()` code path in
`backend/services/review_service.py`.

## Steps (`review_gate`)
1. For each variant, resolve its content (`translated_content` →
   `personalized_content` → `generated_content`) and look up its decision by
   `task_id`.
2. **No decision yet** — pass through unchanged; if the variant has no
   `final_content` set yet, populate it from resolved content anyway (so
   publishing always has something to work with even for
   never-flagged variants).
3. **`"edited"`** — `final_content` = reviewer's `edited_content` (falls back
   to resolved content if not supplied); `status="edited"`.
4. **`"rejected"`** — `status="rejected"`; `retry_count` incremented;
   `any_rejected=True`.
5. **`"approved"` (default)** — `final_content` = resolved content;
   `status="approved"`.
6. `review_round` is incremented only when at least one variant was
   rejected this pass.
7. Sets `current_phase="review_complete"`.

## Router (`review_router`, conditional edge)
- If any variant has `status == "rejected"` AND
  `review_round <= settings.MAX_REVIEW_ROUNDS` → route back to
  `"content_generator"` for regeneration.
- Otherwise → `"publishing_agent"`.

## Notable behaviors
- Variants never explicitly decided on (not flagged for review) still get a
  `final_content` populated in this node — meaning `review_gate` is also the
  place where "auto-approved" (never-flagged) variants get their final
  publish-ready content set, not just the reviewed ones.
- The rerun cap (`settings.MAX_REVIEW_ROUNDS`) prevents an infinite
  reject → regenerate → review loop.

## Wrapping
`review_gate(state)` → `safe_agent_run(_impl, state)`.
