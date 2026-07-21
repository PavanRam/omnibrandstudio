"""T11 — minimal confidence_aggregator (placeholder review trigger) tests.

Fully offline: the aggregator makes no LLM/DB calls, it only transforms state.
"""

from pipeline.agents.aggregation import confidence_aggregator
from pipeline.agents.base import AGENT_WRITE_PERMISSIONS


def _variant(task_id: str = "en-US_email_core", segment: str = "core",
             content: str | None = "Subject: Hi\n\nHello. Learn more: https://x.io") -> dict:
    return {
        "task_id": task_id, "locale": "en-US", "channel": "email", "segment": segment,
        "generated_content": content, "personalized_content": content,
        "translated_content": None, "final_content": None,
        "status": "personalized" if content else "generated",
        "generation_model": "gen-free", "prompt_version": "v1", "brand_guide_version": None,
        "translation_engine": None, "back_translation_score": None, "retry_count": 0,
        "reflexion_applied": False, "failure_reason": None,
    }


def _state(variants: list[dict], org_config: dict | None = None) -> dict:
    return {
        "campaign_id": "camp-1", "org_id": "org-1", "brand_id": "brand-1",
        "org_config": org_config or {}, "variants": variants,
        "aggregated_scores": [], "review_requests": [], "brand_scores": [],
        "human_review_requested": False, "errors": [], "token_cost_usd": 0.0,
    }


async def test_flags_review_by_default_and_snapshots_three_judges():
    result = await confidence_aggregator(_state([_variant()]))

    assert result["human_review_requested"] is True
    assert len(result["review_requests"]) == 1
    rr = result["review_requests"][0]
    assert rr["variant_id"] == "en-US_email_core"
    assert rr["campaign_id"] == "camp-1"
    assert rr["status"] == "pending"
    assert len(rr["scores_snapshot"]) == 3
    assert {s["judge_model"] for s in rr["scores_snapshot"]} == {"claude", "gpt4o", "llama"}
    assert len(result["aggregated_scores"]) == 1
    assert result["aggregated_scores"][0]["variant_id"] == "en-US_email_core"


async def test_review_policy_never_auto_approves_but_still_scores():
    result = await confidence_aggregator(_state([_variant()], {"review_policy": "never"}))
    assert result["human_review_requested"] is False
    assert result["review_requests"] == []
    assert len(result["aggregated_scores"]) == 1  # still produces scores


async def test_review_policy_threshold_flags_below_threshold():
    # placeholder composite (6.5) is below a high threshold -> flag
    flagged = await confidence_aggregator(
        _state([_variant()], {"review_policy": "threshold", "review_threshold": 8.0})
    )
    assert flagged["human_review_requested"] is True
    # ...and passes when threshold is below the placeholder score
    passed = await confidence_aggregator(
        _state([_variant()], {"review_policy": "threshold", "review_threshold": 5.0})
    )
    assert passed["human_review_requested"] is False


async def test_variants_without_content_are_skipped():
    empty = _variant(content=None)
    result = await confidence_aggregator(_state([empty]))
    assert result["human_review_requested"] is False
    assert result["review_requests"] == []
    assert result["aggregated_scores"] == []


async def test_unique_review_request_id_per_variant():
    result = await confidence_aggregator(_state([_variant("t1"), _variant("t2")]))
    ids = [r["review_request_id"] for r in result["review_requests"]]
    assert len(ids) == 2 and len(set(ids)) == 2


async def test_only_writes_permitted_state_keys():
    result = await confidence_aggregator(_state([_variant()]))
    assert set(result) <= AGENT_WRITE_PERMISSIONS["confidence_aggregator"]
