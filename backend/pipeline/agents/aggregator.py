"""Confidence aggregator — deterministic consensus + routing (no LLM).

Pure computation node. Groups the panel's ``brand_scores`` by variant for the
variant's current reflexion round, computes a weighted composite per judge,
derives mean / variance / consensus, and applies a fixed routing precedence.
The disagreement between families is itself the signal: high variance or a
critical violation routes to human review rather than a confidently-wrong
auto-decision.

Idempotent under ``operator.add``: emits at most one ``AggregatedScore`` per
(variant, round), so re-running after a reflexion re-eval appends only the
new round's aggregate and never duplicates prior rounds.
"""
from __future__ import annotations

import uuid

import structlog

from core.metrics import routing_decisions_total
from pipeline.agents.base import publish_campaign_event, safe_agent_run
from pipeline.agents.judges import _NON_SCOREABLE_STATUSES, _variant_content
from pipeline.agents.prompts.judge_prompts import CRITERION_WEIGHTS
from pipeline.state import AggregatedScore, BrandScore, OmniBrandState, ReviewRequest

log = structlog.get_logger()

# Routing thresholds on the 0-1 composite scale. Overridable per org/brand via
# ``*_config["aggregator_thresholds"]``; defaults apply when unset.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "auto_approve": 0.85,
    "auto_reject": 0.60,
    "variance": 0.15,
}
# Degraded-panel adjustment when fewer than 3 judges respond (more cautious).
_DEGRADED_DELTA = 0.05


def _weighted_composite_10(scores: dict) -> float:
    """Weighted composite on the 0-10 criterion scale."""
    total = 0.0
    for criterion, weight in CRITERION_WEIGHTS.items():
        cs = scores.get(criterion) or {}
        total += weight * float(cs.get("score", 0.0))
    return total


def _consensus_level(score_range_10: float) -> str:
    if score_range_10 <= 0.5:
        return "high"
    if score_range_10 <= 1.5:
        return "medium"
    if score_range_10 <= 3.0:
        return "low"
    return "disagreement"


def _resolve_thresholds(state: OmniBrandState) -> dict[str, float]:
    org_cfg = (state.get("org_config") or {}).get("aggregator_thresholds") or {}
    brand_cfg = (state.get("brand_config") or {}).get("aggregator_thresholds") or {}
    return {**DEFAULT_THRESHOLDS, **org_cfg, **brand_cfg}


def _route(
    *,
    mean_01: float,
    variance_01: float,
    consensus: str,
    any_critical: bool,
    critical_majority: bool,
    n_judges: int,
    thresholds: dict[str, float],
) -> tuple[str, str]:
    auto_approve = thresholds["auto_approve"]
    auto_reject = thresholds["auto_reject"]
    var_thr = thresholds["variance"]
    if n_judges < 3:
        # Degraded panel: harder to approve, easier to reject.
        auto_approve = min(1.0, auto_approve + _DEGRADED_DELTA)
        auto_reject = min(1.0, auto_reject + _DEGRADED_DELTA)

    if critical_majority:
        return "auto_reject", "critical violation present"
    if any_critical:
        # A lone judge's critical call, contradicted by the rest of the panel,
        # is exactly the disagreement case this module's docstring says should
        # go to human review rather than a confidently-wrong auto-decision —
        # the code previously auto-rejected on ANY single judge's critical
        # flag regardless of the other judges, making one strict/literal judge
        # call enough to fail an otherwise-approved variant (and, under the
        # worker's strict all-or-nothing policy, the whole campaign).
        return "flag", "critical violation flagged by a minority of judges — routed to human review"
    if consensus == "disagreement":
        return "flag", "judge disagreement (score range > 3.0)"
    if n_judges < 2:
        return "flag", "insufficient judges responded (degraded)"
    if variance_01 > var_thr:
        return "flag", f"high variance {variance_01:.3f} > {var_thr}"
    if mean_01 >= auto_approve:
        return "auto_approve", f"mean {mean_01:.3f} >= {auto_approve}"
    if mean_01 < auto_reject:
        return "auto_reject", f"mean {mean_01:.3f} < {auto_reject}"
    return "flag", f"mean {mean_01:.3f} in review band"


async def confidence_aggregator(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        brand_scores = state.get("brand_scores") or []
        existing_agg = state.get("aggregated_scores") or []
        thresholds = _resolve_thresholds(state)
        campaign_id = state.get("campaign_id", "")

        new_aggregates: list[AggregatedScore] = []
        new_reviews: list[ReviewRequest] = []
        human_review = bool(state.get("human_review_requested"))

        for variant in state.get("variants") or []:
            result = _aggregate_variant(
                variant, brand_scores, existing_agg, thresholds, campaign_id
            )
            if result is None:
                continue
            aggregate, review = result
            new_aggregates.append(aggregate)
            if review is not None:
                new_reviews.append(review)
                human_review = True

        await publish_campaign_event(
            campaign_id=campaign_id,
            agent="confidence_aggregator",
            phase="aggregation_complete",
            payload={
                "aggregated_count": len(new_aggregates),
                "review_requested": human_review,
                # Per-task routing outcome so the frontend plan can flag exactly
                # which row needs attention (any_critical_violation / "flag" /
                # "auto_reject") instead of just an aggregate count — see
                # next_tasks.md "inline campaign plan" (2026-07-26).
                "tasks": [
                    {
                        "task_id": a["variant_id"],
                        "routing_decision": a["routing_decision"],
                        "any_critical_violation": a["any_critical_violation"],
                    }
                    for a in new_aggregates
                ],
            },
        )
        return {
            "aggregated_scores": new_aggregates,
            "review_requests": new_reviews,
            "human_review_requested": human_review,
            "current_phase": "aggregation_complete",
        }

    return await safe_agent_run(_impl, state)


def _aggregate_variant(
    variant: dict,
    brand_scores: list,
    existing_agg: list,
    thresholds: dict,
    campaign_id: str,
) -> tuple[AggregatedScore, ReviewRequest | None] | None:
    """Aggregate one variant's judge scores for its current round.

    Returns ``(aggregate, review_or_None)``, or ``None`` when the variant is
    already aggregated for this round or has no scores yet (idempotency).
    """
    variant_id = variant["task_id"]
    round_ = int(variant.get("retry_count", 0))

    if any(
        a["variant_id"] == variant_id and int(a.get("evaluation_round", 0)) == round_
        for a in existing_agg
    ):
        return None

    # Dedup scores by judge for this round, keeping the latest append.
    per_judge: dict[str, BrandScore] = {}
    for bs in brand_scores:
        if bs["variant_id"] == variant_id and int(bs.get("evaluation_round", 0)) == round_:
            per_judge[bs["judge_model"]] = bs
    scores = list(per_judge.values())
    if not scores:
        # A variant with no content yet (still generating/translating) or in a
        # terminal failure state was never eligible for judging in the first
        # place — nothing to aggregate, same as before.
        if variant.get("status") in _NON_SCOREABLE_STATUSES or not _variant_content(variant):
            return None
        # A scoreable variant with ZERO scores means every judge in the panel
        # failed/errored/mis-parsed for this round (see judges.py's per-variant
        # try/except — it isolates one bad call but stays silent when ALL of
        # them fail). Previously this fell through to `return None` just like
        # the "not yet judged" case, which left `aggregated_scores` empty,
        # `human_review_requested` False, and the graph fell through
        # reflexion/review_gate straight to publishing — an unreviewed variant
        # silently "passing" because nobody actually judged it. Fail closed:
        # force human review instead of treating missing data as approval.
        return _judge_panel_failure(variant_id, round_, campaign_id)

    composites_10 = [_weighted_composite_10(bs["scores"]) for bs in scores]
    composites_01 = [c / 10.0 for c in composites_10]
    n = len(composites_01)
    mean_01 = sum(composites_01) / n
    variance_01 = sum((c - mean_01) ** 2 for c in composites_01) / n
    score_range_10 = max(composites_10) - min(composites_10)
    consensus = _consensus_level(score_range_10)

    critical_union = sorted({cv for bs in scores for cv in bs.get("critical_violations", [])})
    any_critical = bool(critical_union)
    judges_with_critical = sum(1 for bs in scores if bs.get("critical_violations"))
    critical_majority = judges_with_critical > n / 2

    decision, reason = _route(
        mean_01=mean_01,
        variance_01=variance_01,
        consensus=consensus,
        any_critical=any_critical,
        critical_majority=critical_majority,
        n_judges=n,
        thresholds=thresholds,
    )
    routing_decisions_total.labels(decision=decision).inc()

    aggregate: AggregatedScore = {
        "variant_id": variant_id,
        "judge_scores": [round(c, 4) for c in composites_10],
        "weighted_mean": round(mean_01, 4),
        "variance": round(variance_01, 4),
        "consensus_level": consensus,
        "any_critical_violation": any_critical,
        "critical_violations": critical_union,
        "routing_decision": decision,
        "routing_reason": reason,
        "degraded_mode": n < 3,
        "evaluation_round": round_,
    }

    review: ReviewRequest | None = None
    if decision in ("flag", "auto_reject"):
        review = {
            "review_request_id": f"rr_{uuid.uuid4().hex[:16]}",
            "variant_id": variant_id,
            "campaign_id": campaign_id,
            "routing_reason": reason,
            "scores_snapshot": scores,
            "status": "pending",
        }

    # 2026-07-27: the aggregator's routing decision is the single point that
    # combines every judge's score for a variant — logging it here (not just
    # publish_campaign_event's Redis-only, non-persisted broadcast) is what
    # makes "why did this get rejected" answerable after a failed campaign
    # without re-running the paid pipeline (see next_tasks.md — campaign
    # 019fa496 investigation, where this exact question had no answer).
    log_fn = log.warning if decision in ("flag", "auto_reject") else log.info
    log_fn(
        "aggregator_routing_decision",
        campaign_id=campaign_id,
        variant_id=variant_id,
        round=round_,
        routing_decision=decision,
        routing_reason=reason,
        judge_scores_10=aggregate["judge_scores"],
        weighted_mean_01=aggregate["weighted_mean"],
        consensus_level=consensus,
        any_critical_violation=any_critical,
        critical_violations=critical_union,
        degraded_mode=aggregate["degraded_mode"],
        n_judges=n,
    )

    return aggregate, review


def _judge_panel_failure(
    variant_id: str, round_: int, campaign_id: str
) -> tuple[AggregatedScore, ReviewRequest]:
    """Force human review when a scoreable variant got zero judge scores.

    Distinct from the normal "flag"/"auto_reject" paths above: there is no
    judge output at all to reason about, only the fact that the panel never
    produced one.
    """
    reason = "judge panel returned no scores for this round"
    routing_decisions_total.labels(decision="flag").inc()
    log.warning(
        "aggregator_judge_panel_failure",
        campaign_id=campaign_id,
        variant_id=variant_id,
        round=round_,
        routing_reason=reason,
    )
    aggregate: AggregatedScore = {
        "variant_id": variant_id,
        "judge_scores": [],
        "weighted_mean": 0.0,
        "variance": 0.0,
        "consensus_level": "disagreement",
        "any_critical_violation": False,
        "critical_violations": [],
        "routing_decision": "flag",
        "routing_reason": reason,
        "degraded_mode": True,
        "evaluation_round": round_,
    }
    review: ReviewRequest = {
        "review_request_id": f"rr_{uuid.uuid4().hex[:16]}",
        "variant_id": variant_id,
        "campaign_id": campaign_id,
        "routing_reason": reason,
        "scores_snapshot": [],
        "status": "pending",
    }
    return aggregate, review
