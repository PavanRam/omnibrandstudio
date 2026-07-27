"""Unit tests for reflexion (pipeline/agents/reflexion.py).

Covers the self-correction node (regenerates a rejected variant in place, at
most once) and the conditional-edge router (re-fans the corrected variant
through the judges exactly once, then proceeds to the review gate).
``traced_llm_call`` is mocked so no model access is needed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pipeline.agents import reflexion as reflexion_mod
from pipeline.agents.reflexion import reflexion, reflexion_router


def _variant(*, retry_count: int = 0, reflexion_applied: bool = False) -> dict:
    return {
        "task_id": "t1",
        "channel": "email",
        "locale": "en",
        "status": "generated",
        "generated_content": "Original content.",
        "personalized_content": "Personalized.",
        "translated_content": "Translated.",
        "final_content": "Final.",
        "retry_count": retry_count,
        "reflexion_applied": reflexion_applied,
    }


def _aggregate(decision: str, mean: float, *, round_: int = 0, critical=None) -> dict:
    return {
        "variant_id": "t1",
        "evaluation_round": round_,
        "routing_decision": decision,
        "weighted_mean": mean,
        "critical_violations": critical or [],
    }


def _state(variants, aggregates, *, brand_scores=None) -> dict:
    return {
        "campaign_id": "camp-1",
        "model_aliases": {},
        "variants": variants,
        "aggregated_scores": aggregates,
        "brand_scores": brand_scores or [],
    }


@pytest.mark.asyncio
async def test_reflexion_regenerates_rejected_variant(monkeypatch):
    mock = AsyncMock(return_value=("Corrected content.", {"cost": 0.0}))
    monkeypatch.setattr(reflexion_mod, "traced_llm_call", mock)

    variant = _variant()
    state = _state([variant], [_aggregate("auto_reject", 0.40)])
    result = await reflexion(state)

    # Mutated in place AND returned via "variants" — merge_variants (state.py)
    # upserts by task_id, so this durably replaces the entry rather than
    # duplicating it (see pipeline/state.py:merge_variants docstring).
    assert result == {"variants": [variant], "current_phase": "reflexion_complete"}
    assert variant["generated_content"] == "Corrected content."
    assert variant["personalized_content"] is None
    assert variant["translated_content"] is None
    assert variant["final_content"] is None
    assert variant["status"] == "generated"
    assert variant["retry_count"] == 1
    assert variant["reflexion_applied"] is True


@pytest.mark.asyncio
async def test_reflexion_fires_once_then_hard_stops(monkeypatch):
    mock = AsyncMock(return_value=("Corrected.", {"cost": 0.0}))
    monkeypatch.setattr(reflexion_mod, "traced_llm_call", mock)

    # Already retried once (retry_count=1): hard cap must prevent a second call.
    variant = _variant(retry_count=1, reflexion_applied=True)
    state = _state([variant], [_aggregate("auto_reject", 0.40, round_=1)])
    await reflexion(state)

    mock.assert_not_called()


@pytest.mark.asyncio
async def test_reflexion_triggers_on_low_flag(monkeypatch):
    mock = AsyncMock(return_value=("Corrected.", {"cost": 0.0}))
    monkeypatch.setattr(reflexion_mod, "traced_llm_call", mock)

    variant = _variant()
    state = _state([variant], [_aggregate("flag", 0.65)])  # < 0.72
    await reflexion(state)

    mock.assert_called_once()
    assert variant["retry_count"] == 1


@pytest.mark.asyncio
async def test_reflexion_skips_high_flag(monkeypatch):
    mock = AsyncMock(return_value=("Corrected.", {"cost": 0.0}))
    monkeypatch.setattr(reflexion_mod, "traced_llm_call", mock)

    variant = _variant()
    state = _state([variant], [_aggregate("flag", 0.80)])  # >= 0.72
    await reflexion(state)

    mock.assert_not_called()
    assert variant["retry_count"] == 0


@pytest.mark.asyncio
async def test_reflexion_skips_auto_approve(monkeypatch):
    mock = AsyncMock(return_value=("Corrected.", {"cost": 0.0}))
    monkeypatch.setattr(reflexion_mod, "traced_llm_call", mock)

    variant = _variant()
    state = _state([variant], [_aggregate("auto_approve", 0.95)])
    await reflexion(state)

    mock.assert_not_called()


def test_router_refans_when_reflexed_variant_lacks_new_aggregate():
    # Variant reflexed to round 1, but only a round-0 aggregate exists.
    variant = _variant(retry_count=1, reflexion_applied=True)
    state = _state([variant], [_aggregate("auto_reject", 0.40, round_=0)])

    assert reflexion_router(state) == ["judge_claude", "judge_gpt4o", "judge_llama"]


def test_router_proceeds_when_reflexed_variant_reaggregated():
    variant = _variant(retry_count=1, reflexion_applied=True)
    state = _state([variant], [_aggregate("auto_approve", 0.90, round_=1)])

    assert reflexion_router(state) == "review_gate"


def test_router_proceeds_when_no_reflexion():
    variant = _variant()
    state = _state([variant], [_aggregate("auto_approve", 0.90)])

    assert reflexion_router(state) == "review_gate"
