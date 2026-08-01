# Confidence Aggregator Agent

## Purpose
Runs after the judge panel fan-in. Pure deterministic computation — no LLM
call. Groups the panel's `brand_scores` by variant for its current
reflexion round, computes a weighted composite per judge, derives
mean/variance/consensus, and applies a fixed routing precedence. Judge
disagreement is itself a signal: high variance or a critical violation
routes to human review rather than a confidently-wrong auto-decision.

File: `backend/pipeline/agents/aggregator.py`

## Write permissions (`AGENT_WRITE_PERMISSIONS["confidence_aggregator"]`)
`aggregated_scores`, `review_requests`, `human_review_requested`

Idempotent under `operator.add`: emits at most one `AggregatedScore` per
`(variant_id, evaluation_round)`, so re-running after a reflexion re-eval
appends only the new round's aggregate and never duplicates prior rounds.

## Steps (per variant, `_aggregate_variant`)
1. **Skip if already aggregated** for this variant's current
   `retry_count` round, or if it has no judge scores yet for that round
   (idempotency guard).
2. **Dedup by judge** — keeps the latest `BrandScore` per `judge_model` for
   the round (handles any accidental duplicate append under `operator.add`).
3. **Weighted composite** (`_weighted_composite_10`) — `CRITERION_WEIGHTS`
   (`prompts/judge_prompts.py`) applied to each judge's per-criterion scores,
   producing a 0–10 composite per judge; normalized to 0–1
   (`composites_01`).
4. **Consensus** — `mean_01`, `variance_01` across judges; `score_range_10`
   (max − min of the 0–10 composites) maps to a consensus label via
   `_consensus_level`: `<=0.5` high, `<=1.5` medium, `<=3.0` low, else
   `"disagreement"`.
5. **Routing** (`_route`, fixed precedence):
   1. any critical violation present → `auto_reject`
   2. consensus == `"disagreement"` → `flag`
   3. fewer than 2 judges responded → `flag` (insufficient/degraded)
   4. variance above threshold (`0.15` default) → `flag`
   5. mean >= `auto_approve` threshold (`0.85` default) → `auto_approve`
   6. mean < `auto_reject` threshold (`0.60` default) → `auto_reject`
   7. otherwise → `flag` (review band)
   - Thresholds are overridable per org/brand via
     `*_config["aggregator_thresholds"]`.
   - **Degraded-panel adjustment**: with fewer than 3 judges responding, both
     `auto_approve` and `auto_reject` thresholds shift by `+0.05` — more
     cautious in either direction.
   - `routing_decisions_total` Prometheus counter incremented per decision.
6. **Review request creation** — for `"flag"` or `"auto_reject"` decisions, a
   `ReviewRequest` is created (`review_request_id`, `variant_id`,
   `campaign_id`, `routing_reason`, `scores_snapshot`, `status="pending"`)
   and `human_review_requested` is set `True`.

## Notable behaviors
- This node has no LLM cost — no `token_cost_usd` write, by design.
- The disagreement-first routing precedence (checked before the mean
  threshold) means a confidently high mean score can still route to human
  review if judges disagree sharply — the design deliberately distrusts a
  single judge's high confidence when its peers diverge.

## Wrapping
`confidence_aggregator(state)` → `safe_agent_run(_impl, state)`.
