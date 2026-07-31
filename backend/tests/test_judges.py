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
from pipeline.agents.base import LLMCallError
from pipeline.agents.prompts.judge_prompts import CRITERIA, build_judge_messages


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
        (judges.judge_1, "judge-1-free"),
        (judges.judge_2, "judge-2-free"),
        (judges.judge_3, "judge-3-free"),
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
    result = await judges.judge_1(state)

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
    result = await judges.judge_1(_state(brand_scores=[existing]))

    assert result["brand_scores"] == []
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_judge_skips_non_scoreable_variant(monkeypatch):
    mock = AsyncMock(return_value=(_score_json(9.0), {"cost": 0.0}))
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    result = await judges.judge_1(_state(variants=[_variant(status="failed")]))

    assert result["brand_scores"] == []
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_judge_degrades_on_unparseable_output(monkeypatch):
    mock = AsyncMock(return_value=("not json at all", {"cost": 0.0}))
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    result = await judges.judge_1(_state())

    assert result["brand_scores"] == []


@pytest.mark.asyncio
async def test_judge_retries_without_json_mode_on_400(monkeypatch):
    """A strict-JSON-mode 400 retries once without response_format, then parses."""
    mock = AsyncMock(
        side_effect=[
            LLMCallError("judge-1-free json_validate_failed", status_code=400),
            (_score_json(8.0), {"cost": 0.0}),
        ]
    )
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    result = await judges.judge_1(_state())

    assert len(result["brand_scores"]) == 1
    assert result["brand_scores"][0]["composite_score"] == 8.0
    assert mock.call_count == 2
    # First attempt forces JSON mode; the recovery attempt drops it so the
    # model can emit a JSON object in prose instead of failing schema validation.
    _, first_kwargs = mock.call_args_list[0]
    _, retry_kwargs = mock.call_args_list[1]
    assert first_kwargs["response_format"] == {"type": "json_object"}
    assert "response_format" not in retry_kwargs
    assert retry_kwargs["temperature"] == 0


@pytest.mark.asyncio
async def test_judge_does_not_retry_non_400(monkeypatch):
    """A non-400 failure isolates the variant without a second call."""
    mock = AsyncMock(
        side_effect=LLMCallError("judge-1-free upstream 500", status_code=500)
    )
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    result = await judges.judge_1(_state())

    assert result["brand_scores"] == []
    assert mock.call_count == 1


# ── canonical-CTA grounding (locale-aware cta_style) ─────────────────────────


def test_build_judge_messages_omits_cta_block_when_no_canonical_cta():
    messages = build_judge_messages(
        brand_guide="Speak warmly.", channel="email", locale="en", content="Buy now."
    )
    user = messages[1]["content"]
    assert "APPROVED CALL-TO-ACTION" not in user
    assert "faithful translation" not in user.lower()


def test_build_judge_messages_injects_cta_block_for_non_english_locale():
    messages = build_judge_messages(
        brand_guide="Speak warmly.",
        channel="instagram",
        locale="fr-FR",
        content="Cliquez sur le lien dans notre bio",
        canonical_cta="Link in Bio",
    )
    user = messages[1]["content"]
    assert 'exactly: "Link in Bio"' in user
    assert "fr-FR" in user
    # The core instruction: a faithful translation of the approved CTA is
    # compliant and must not be penalised for being translated.
    assert "faithful translation" in user.lower()
    assert "do not penalize" in user.lower() or "do not penalise" in user.lower()


@pytest.mark.asyncio
async def test_judge_threads_persona_channel_cta_into_prompt(monkeypatch):
    """A known persona/channel variant carries its authoritative CTA into the
    judge prompt so a translated CTA isn't flagged as non-compliant."""
    mock = AsyncMock(return_value=(_score_json(9.0), {"cost": 0.0}))
    monkeypatch.setattr(judges, "traced_llm_call", mock)

    variant = _variant(task_id="instagram_Web-Savvy Mid-Tier Buyer_fr")
    variant["channel"] = "instagram"
    variant["segment"] = "Web-Savvy Mid-Tier Buyer"
    variant["locale"] = "fr-FR"

    await judges.judge_1(_state(variants=[variant]))

    _, kwargs = mock.call_args
    user_msg = kwargs["messages"][1]["content"]
    assert 'exactly: "Link in Bio"' in user_msg
    assert "faithful translation" in user_msg.lower()

