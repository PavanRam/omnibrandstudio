"""Unit tests for the LLM-as-judge panel (pipeline/agents/judges.py).

The judges are exercised with ``traced_llm_call`` mocked so no network / API
keys are needed — the focus is the panel contract: three cross-family judges
each populate ``brand_scores`` (and only that field), tag the correct
``judge_model`` alias + ``evaluation_round``, honour idempotency, and degrade
to an empty list on unparseable output.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from pipeline.agents import judges
from pipeline.agents.prompts.judge_prompts import CRITERIA


def _score_json(value: float, *, routing: str = "auto_approve", critical=None) -> str:
    body = {
        c: {"score": value, "reasoning": f"{c} ok", "violations": [], "citations": []}
        for c in CRITERIA
    }
    body["composite_score"] = value
    body["critical_violations"] = critical or []
    body["routing_decision"] = routing
    body["routing_explanation"] = "This is a sufficiently long routing explanation."
    return json.dumps(body)


def _variant(task_id: str = "t1", *, retry_count: int = 0, status: str = "generated") -> dict:
    return {
        "task_id": task_id,
        "channel": "email",
        "locale": "en",
        "status": status,
        "generated_content": "Buy our product today.",
        "personalized_content": None,
        "translated_content": None,
        "final_content": None,
        "retry_count": retry_count,
    }


def _state(**overrides) -> dict:
    base = {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "brand_id": "brand-1",
        "model_aliases": {},
        "rag_context": {"brand_guide_chunks": ["Speak warmly and factually."]},
        "brand_scores": [],
        "variants": [_variant()],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "judge_fn, expected_alias",
    [
        (judges.judge_claude, "judge-1-free"),
        (judges.judge_gpt4o, "judge-2-free"),
        (judges.judge_llama, "judge-3-free"),
    ],
)
async def test_each_judge_populates_brand_scores(monkeypatch, judge_fn, expected_alias):
    mock = AsyncMock(return_value=(_score_json(9.0), {"cost": 0.0}))
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    result = await judge_fn(_state())

    assert set(result.keys()) == {"brand_scores"}
    assert len(result["brand_scores"]) == 1
    bs = result["brand_scores"][0]
    assert bs["variant_id"] == "t1"
    assert bs["judge_model"] == expected_alias
    assert bs["evaluation_round"] == 0
    assert bs["composite_score"] == 9.0
    # traced_llm_call must be told to force JSON + deterministic scoring.
    _, kwargs = mock.call_args
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0


@pytest.mark.asyncio
async def test_judge_uses_paid_alias_from_state(monkeypatch):
    mock = AsyncMock(return_value=(_score_json(8.0), {"cost": 0.0}))
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    state = _state(model_aliases={"judge-1": "judge-1"})
    result = await judges.judge_claude(state)

    assert result["brand_scores"][0]["judge_model"] == "judge-1"


@pytest.mark.asyncio
async def test_judge_skips_already_scored_round(monkeypatch):
    mock = AsyncMock(return_value=(_score_json(9.0), {"cost": 0.0}))
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    existing = {
        "variant_id": "t1",
        "judge_model": "judge-1-free",
        "evaluation_round": 0,
    }
    result = await judges.judge_claude(_state(brand_scores=[existing]))

    assert result["brand_scores"] == []
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_judge_skips_non_scoreable_variant(monkeypatch):
    mock = AsyncMock(return_value=(_score_json(9.0), {"cost": 0.0}))
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    result = await judges.judge_claude(_state(variants=[_variant(status="failed")]))

    assert result["brand_scores"] == []
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_judge_degrades_on_unparseable_output(monkeypatch):
    mock = AsyncMock(return_value=("not json at all", {"cost": 0.0}))
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    result = await judges.judge_claude(_state())

    assert result["brand_scores"] == []
