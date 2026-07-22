"""Unit tests for the confidence aggregator (pipeline/agents/aggregator.py).

The aggregator is a pure computation node (no LLM), so these tests assert the
routing precedence directly: a critical violation overrides an otherwise high
mean, family disagreement flags for review, clean high scores auto-approve, and
aggregation is idempotent per (variant, round) under ``operator.add``.
"""
from __future__ import annotations

import pytest

from pipeline.agents.aggregator import confidence_aggregator
from pipeline.agents.prompts.judge_prompts import CRITERIA


def _bs(judge_model: str, value: float, *, critical=None, round_: int = 0, variant_id: str = "t1") -> dict:
    return {
        "variant_id": variant_id,
        "judge_model": judge_model,
        "composite_score": value,
        "scores": {
            c: {"score": value, "reasoning": "", "violations": [], "citations": []}
            for c in CRITERIA
        },
        "critical_violations": critical or [],
        "routing_decision": "auto_approve",
        "evaluation_latency_ms": 10,
        "evaluation_round": round_,
    }


def _variant(task_id: str = "t1", *, retry_count: int = 0) -> dict:
    return {"task_id": task_id, "channel": "email", "locale": "en", "retry_count": retry_count}


def _state(brand_scores, *, variants=None, aggregated_scores=None, **overrides) -> dict:
    base = {
        "campaign_id": "camp-1",
        "org_config": {},
        "brand_config": {},
        "variants": variants or [_variant()],
        "brand_scores": brand_scores,
        "aggregated_scores": aggregated_scores or [],
        "review_requests": [],
        "human_review_requested": False,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_high_mean_with_critical_violation_auto_rejects():
    scores = [
        _bs("judge-1-free", 9.5, critical=["fabricated statistic"]),
        _bs("judge-2-free", 9.5),
        _bs("judge-3-free", 9.5),
    ]
    result = await confidence_aggregator(_state(scores))

    agg = result["aggregated_scores"][0]
    assert agg["routing_decision"] == "auto_reject"
    assert agg["any_critical_violation"] is True
    assert result["human_review_requested"] is True
    assert len(result["review_requests"]) == 1


@pytest.mark.asyncio
async def test_disagreement_flags_for_review():
    scores = [
        _bs("judge-1-free", 9.5),
        _bs("judge-2-free", 5.0),  # range 4.5 > 3.0 → disagreement
        _bs("judge-3-free", 8.0),
    ]
    result = await confidence_aggregator(_state(scores))

    agg = result["aggregated_scores"][0]
    assert agg["consensus_level"] == "disagreement"
    assert agg["routing_decision"] == "flag"
    assert result["human_review_requested"] is True


@pytest.mark.asyncio
async def test_clean_high_scores_auto_approve():
    scores = [
        _bs("judge-1-free", 9.2),
        _bs("judge-2-free", 9.1),
        _bs("judge-3-free", 9.3),
    ]
    result = await confidence_aggregator(_state(scores))

    agg = result["aggregated_scores"][0]
    assert agg["routing_decision"] == "auto_approve"
    assert result["review_requests"] == []
    assert result["human_review_requested"] is False


@pytest.mark.asyncio
async def test_low_scores_auto_reject():
    scores = [
        _bs("judge-1-free", 4.0),
        _bs("judge-2-free", 4.2),
        _bs("judge-3-free", 3.9),
    ]
    result = await confidence_aggregator(_state(scores))

    assert result["aggregated_scores"][0]["routing_decision"] == "auto_reject"


@pytest.mark.asyncio
async def test_idempotent_per_variant_round():
    scores = [
        _bs("judge-1-free", 9.2),
        _bs("judge-2-free", 9.1),
        _bs("judge-3-free", 9.3),
    ]
    existing = [{"variant_id": "t1", "evaluation_round": 0}]
    result = await confidence_aggregator(_state(scores, aggregated_scores=existing))

    assert result["aggregated_scores"] == []


@pytest.mark.asyncio
async def test_dedups_scores_by_judge_keeping_last():
    scores = [
        _bs("judge-1-free", 2.0),
        _bs("judge-1-free", 9.2),  # same judge, later append wins
        _bs("judge-2-free", 9.1),
        _bs("judge-3-free", 9.3),
    ]
    result = await confidence_aggregator(_state(scores))

    agg = result["aggregated_scores"][0]
    assert len(agg["judge_scores"]) == 3
    assert agg["routing_decision"] == "auto_approve"


@pytest.mark.asyncio
async def test_degraded_mode_flag_when_two_judges():
    scores = [
        _bs("judge-1-free", 9.2),
        _bs("judge-2-free", 9.3),
    ]
    result = await confidence_aggregator(_state(scores))

    agg = result["aggregated_scores"][0]
    assert agg["degraded_mode"] is True
