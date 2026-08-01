# Reflexion Agent

## Purpose
Runs after `confidence_aggregator`. Performs exactly one self-correction
retry for a variant the panel rejected or low-confidence-flagged, then loops
the regenerated variant back through the judge panel for re-scoring. Named
`reflexion` (node function) + `reflexion_router` (conditional-edge function).

File: `backend/pipeline/agents/reflexion.py`

## Write permissions (`AGENT_WRITE_PERMISSIONS["reflexion"]`)
`variants`, `brand_scores`, `aggregated_scores`, `errors`

Enrichment model: mutates the variant dict **in place** (same contract as
`personalization_agent`/`translation_agent`) — the node itself returns `{}`,
since all changes are in-place mutations of objects already present in the
fan-in `variants` list.

## Trigger condition (per variant, `_maybe_reflex_variant`)
- **Hard cap**: no-op if `variant["retry_count"] > 0` — at most one
  reflexion retry per variant, ever.
- No-op if there's no `AggregatedScore` yet for this variant's current round
  (nothing to react to).
- Fires when the aggregate's `routing_decision == "auto_reject"`, OR
  `routing_decision == "flag"` AND `weighted_mean < 0.72` (`_FLAG_RETRY_MEAN`)
  — i.e., a low-confidence flag, not every flag.

## Steps
1. **Collect reasons** (`_collect_reasons`) — for every judge score at this
   variant's round, any criterion scored below `6.0` (`_LOW_CRITERION`)
   contributes its reasoning text as a correction target; all critical
   violations are also included. De-duplicated, order-preserved.
2. **Re-inject brand guide grounding** — up to 5 chunks from
   `rag_context["brand_guide_chunks"]` are re-included in the correction
   prompt (`build_reflexion_messages`, `prompts/judge_prompts.py`).
3. **Regenerate** — `traced_llm_call` using
   `state["model_aliases"].get("generation", "gen-free")` (same model as
   `content_generator`, not a dedicated "reflexion" alias).
4. **Reset downstream state on the variant** — `generated_content` is
   replaced, `personalized_content`/`translated_content`/`final_content` are
   cleared back to `None`, `status` reset to `"generated"`,
   `retry_count += 1`, `reflexion_applied = True`. This forces the variant
   back through translation/scoring as if freshly generated — but note
   `content_generator`/`personalization_agent`/`translation_agent` are NOT
   re-run by the graph; `reflexion_router` only re-fans to the three judge
   nodes directly (the "regeneration" is done here, in-node, not by
   re-invoking earlier pipeline stages).

## Router (`reflexion_router`, conditional edge)
For each variant with `reflexion_applied=True`: if it has no
`AggregatedScore` yet for its new (incremented) round, return
`["judge_claude", "judge_gpt4o", "judge_llama"]` to re-evaluate. Once every
reflexed variant has a fresh-round aggregate, return `"review_gate"` to
proceed. Termination is guaranteed by the combination of the hard
one-retry cap and this "has this round been aggregated yet" check — stale
first-round scores can never be deleted under `operator.add`, but the round
number distinguishes them.

## Wrapping
`reflexion(state)` → `safe_agent_run(_impl, state)`.
