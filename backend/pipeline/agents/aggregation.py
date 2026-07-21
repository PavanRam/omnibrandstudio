"""T11 — minimal ``confidence_aggregator`` (placeholder review trigger).

For each content-bearing variant this emits placeholder 3-judge ``BrandScore``
snapshots + one ``AggregatedScore``, and flags human review according to
``org_config["review_policy"]`` (default ``always``). It is a deliberate
placeholder: the real 3-judge scoring (T8) and full aggregation/routing (T9)
replace this node wholesale. The state output contract
(``aggregated_scores`` / ``review_requests`` / ``human_review_requested``) is
what the T11 review gate depends on.
"""
from __future__ import annotations

import uuid
from statistics import mean, pvariance

import structlog

from pipeline.agents.base import safe_agent_run
from pipeline.state import (
    AggregatedScore,
    BrandScore,
    CriterionScore,
    OmniBrandState,
    ReviewRequest,
)

log = structlog.get_logger()

_JUDGES = ("claude", "gpt4o", "llama")
_PLACEHOLDER_COMPOSITE = 6.5
_DEFAULT_THRESHOLD = 8.0
_CRITERIA = (
    "tone_alignment",
    "vocabulary_compliance",
    "channel_format_adherence",
    "cta_style",
    "cultural_appropriateness",
    "factual_grounding",
)


def _variant_content(variant: dict) -> str | None:
    """The most-advanced content available on a variant (translated > personalized > generated)."""
    return (
        variant.get("translated_content")
        or variant.get("personalized_content")
        or variant.get("generated_content")
    )


def _placeholder_scores(variant_id: str) -> list[BrandScore]:
    criteria: dict[str, CriterionScore] = {
        c: CriterionScore(
            score=_PLACEHOLDER_COMPOSITE,
            reasoning="placeholder score (real judges are T8)",
            violations=[],
            citations=[],
        )
        for c in _CRITERIA
    }
    return [
        BrandScore(
            variant_id=variant_id,
            judge_model=judge,
            composite_score=_PLACEHOLDER_COMPOSITE,
            scores=criteria,
            critical_violations=[],
            routing_decision="flag",
            evaluation_latency_ms=0,
        )
        for judge in _JUDGES
    ]


def _should_flag(policy: str, weighted_mean: float, threshold: float) -> bool:
    if policy == "never":
        return False
    if policy == "threshold":
        return weighted_mean < threshold
    return True  # "always" (default)


async def confidence_aggregator(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        org_config = state.get("org_config") or {}
        policy = str(org_config.get("review_policy", "always")).lower()
        threshold = float(org_config.get("review_threshold", _DEFAULT_THRESHOLD))
        campaign_id = state.get("campaign_id", "")

        aggregated: list[AggregatedScore] = []
        reviews: list[ReviewRequest] = []
        flagged = False

        for variant in state.get("variants", []):
            if not _variant_content(variant) or variant.get("status") == "failed":
                continue

            variant_id = variant["task_id"]
            scores = _placeholder_scores(variant_id)
            composites = [s["composite_score"] for s in scores]
            weighted_mean = round(mean(composites), 2)

            aggregated.append(
                AggregatedScore(
                    variant_id=variant_id,
                    judge_scores=composites,
                    weighted_mean=weighted_mean,
                    variance=round(pvariance(composites), 4) if len(composites) > 1 else 0.0,
                    consensus_level="high",
                    any_critical_violation=False,
                    critical_violations=[],
                    routing_decision="flag",
                    routing_reason=f"review_policy={policy}",
                    degraded_mode=True,
                )
            )

            if _should_flag(policy, weighted_mean, threshold):
                flagged = True
                reviews.append(
                    ReviewRequest(
                        review_request_id=str(uuid.uuid4()),
                        variant_id=variant_id,
                        campaign_id=campaign_id,
                        routing_reason=f"flagged by review_policy={policy} (placeholder scoring)",
                        scores_snapshot=scores,
                        status="pending",
                    )
                )

        log.info(
            "agent_complete",
            agent="confidence_aggregator",
            campaign_id=campaign_id,
            scored=len(aggregated),
            flagged=len(reviews),
            policy=policy,
        )
        return {
            "aggregated_scores": aggregated,
            "review_requests": reviews,
            "human_review_requested": flagged,
        }

    return await safe_agent_run(_impl, state)
