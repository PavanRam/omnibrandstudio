from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.routers import campaigns
from pipeline.agents import content_generator as cg
from pipeline.agents import intake
from pipeline.schemas import CreateCampaignRequest
from pipeline.state import OmniBrandState


class _FakeRedis:
    def __init__(self) -> None:
        self.payloads: list[str] = []

    async def lpush(self, _queue: str, payload: str) -> None:
        self.payloads.append(payload)


class _FakeRequest:
    def __init__(self) -> None:
        self.state = SimpleNamespace(request_id="req-1", org_id="org-1", user_id="user-1")


def _base_state(**overrides) -> OmniBrandState:
    state = OmniBrandState(
        campaign_id="camp-1",
        org_id="org-1",
        brand_id="brand-1",
        user_id="user-1",
        request_id="req-1",
        started_at="2026-07-05T00:00:00",
        org_config={},
        brand_config={},
        model_aliases={"generation": "gen-free"},
        brief=None,
        rag_context=None,
        prior_campaigns=[],
        brief_valid=None,
        brief_validation_errors=[],
        budget_check_passed=None,
        tasks=[],
        current_task=None,
        variants=[],
        brand_scores=[],
        aggregated_scores=[],
        review_requests=[],
        publication_receipts=[],
        failed_task_ids=[],
        errors=[],
        current_phase="starting",
        human_review_requested=False,
        publishing_paused=False,
        token_cost_usd=0.0,
    )
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_create_campaign_enqueues_brief_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(campaigns, "get_redis", lambda: redis)

    request = CreateCampaignRequest(
        brand_id="brand-1",
        objective="Launch new feature",
        target_audience="Developers",
        key_messages=["Fast", "Reliable"],
        channels=["email"],
        locales=["en-US"],
        audience_segments=["enterprise"],
        token_budget=200,
        raw_text="launch brief",
    )

    await campaigns.create_campaign(request, _FakeRequest())

    assert len(redis.payloads) == 1
    task = json.loads(redis.payloads[0])
    assert task["brand_id"] == "brand-1"
    assert task["org_id"] == "org-1"
    assert task["user_id"] == "user-1"
    assert task["brief"]["objective"] == "Launch new feature"
    assert task["brief"]["channels"] == ["email"]


@pytest.mark.asyncio
async def test_intake_populates_rag_context_when_retrieval_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Chunk:
        def __init__(self, content: str, section_type: str, version: str, score: float) -> None:
            self.content = content
            self.section_type = section_type
            self.version = version
            self.score = score

    class _Retriever:
        async def retrieve(self, **_kwargs):
            return [
                _Chunk("Tone: confident", "tone", "v1", 0.9),
                _Chunk("CTA: direct", "cta", "v2", 0.8),
            ]

    monkeypatch.setattr(intake, "get_retriever", lambda: _Retriever())

    brief = {
        "objective": "Launch",
        "target_audience": "Developers",
        "key_messages": ["Fast"],
        "tone_override": None,
        "channels": ["email"],
        "locales": ["en-US"],
        "audience_segments": ["enterprise"],
        "token_budget": 2000,
        "raw_text": "launch brief",
    }
    result = await intake.intake_agent(_base_state(brief=brief))

    assert result["brief_valid"] is True
    assert result["budget_check_passed"] is True
    assert len(result["tasks"]) == 1
    assert result["rag_context"] is not None
    assert result["rag_context"]["brand_guide_chunks"]


@pytest.mark.asyncio
async def test_content_generator_includes_rag_guidance_in_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_examples(_brand_id: str, _channel: str, _locale: str, n: int = 3) -> list[str]:
        assert n == 3
        return []

    async def _fake_llm_call(*, model: str, messages: list[dict], task: str, state: dict, **_kwargs):
        captured["messages"] = messages
        assert model == "gen-free"
        assert task == "content_generator"
        assert state["brand_id"] == "brand-1"
        return "Generated copy", {"cost": 0.01}

    monkeypatch.setattr(cg, "get_examples", _fake_examples)
    monkeypatch.setattr(cg, "traced_llm_call", _fake_llm_call)

    task = {
        "task_id": "en-US_email_enterprise",
        "locale": "en-US",
        "channel": "email",
        "segment": "enterprise",
        "channel_constraints": {},
    }
    state = _base_state(
        brand_config={"name": "Acme"},
        tasks=[task],
        brief={
            "objective": "Launch",
            "target_audience": "Developers",
            "key_messages": ["Fast"],
            "tone_override": None,
            "channels": ["email"],
            "locales": ["en-US"],
            "audience_segments": ["enterprise"],
            "token_budget": 200,
            "raw_text": "launch brief",
        },
        rag_context={
            "brand_guide_chunks": ["Use confident tone.", "Prefer active voice."],
            "section_types": ["tone", "style"],
            "brand_guide_version": "v2",
            "retrieval_scores": [0.9, 0.8],
        },
    )

    result = await cg.content_generator(state)

    assert result["variants"]
    messages = captured["messages"]
    assert isinstance(messages, list)
    user_prompt = messages[1]["content"]
    assert "Brand guide excerpts to follow" in user_prompt
    assert "Use confident tone." in user_prompt
