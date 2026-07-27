from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

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
        self.state = SimpleNamespace(
            request_id="req-1",
            org_id="00000000-0000-0000-0000-000000000001",
            user_id="",
        )


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

    class _FakeResult:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

    class _FakeConn:
        async def execute(self, stmt, *_args, **_kwargs):
            sql_text = str(getattr(stmt, "text", stmt))
            if "FROM brands" in sql_text:
                return _FakeResult(
                    {
                        "id": "00000000-0000-0000-0000-000000000002",
                        "org_id": "00000000-0000-0000-0000-000000000001",
                    }
                )
            return _FakeResult(None)

        async def commit(self) -> None:
            return None

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)

    request = CreateCampaignRequest(
        brand_id="00000000-0000-0000-0000-000000000002",
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
    assert task["brand_id"] == "00000000-0000-0000-0000-000000000002"
    assert task["org_id"] == "00000000-0000-0000-0000-000000000001"
    assert task["user_id"] == ""
    assert task["brief"]["objective"] == "Launch new feature"
    assert task["brief"]["channels"] == ["email"]


@pytest.mark.asyncio
async def test_create_campaign_returns_404_for_missing_brand(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(campaigns, "get_redis", lambda: redis)

    class _FakeResult:
        def mappings(self):
            return self

        def first(self):
            return None

    class _FakeConn:
        async def execute(self, *_args, **_kwargs):
            return _FakeResult()

        async def commit(self) -> None:
            return None

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)

    request = CreateCampaignRequest(
        brand_id="00000000-0000-0000-0000-000000000003",
        objective="Launch new feature",
        target_audience="Developers",
        key_messages=["Fast", "Reliable"],
        channels=["email"],
        locales=["en-US"],
        audience_segments=["enterprise"],
        token_budget=200,
        raw_text="launch brief",
    )

    with pytest.raises(HTTPException) as exc_info:
        await campaigns.create_campaign(request, _FakeRequest())

    err = exc_info.value
    assert getattr(err, "status_code", None) == 404
    assert getattr(err, "detail", "") == "brand not found"
    assert len(redis.payloads) == 0


@pytest.mark.asyncio
async def test_get_campaign_status_returns_campaign_row(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)

    class _FakeResult:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

    class _FakeConn:
        async def execute(self, *_args, **_kwargs):
            return _FakeResult(
                {
                    "id": "019f76e9-c299-7756-a483-761aa106ba33",
                    "status": "queued",
                    "started_at": None,
                    "completed_at": None,
                    "token_cost_usd": 0,
                    "created_at": now,
                }
            )

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)

    result = await campaigns.get_campaign_status("019f76e9-c299-7756-a483-761aa106ba33")

    assert result["campaign_id"] == "019f76e9-c299-7756-a483-761aa106ba33"
    assert result["status"] == "queued"
    assert result["token_cost_usd"] == 0.0
    assert result["created_at"] == now


@pytest.mark.asyncio
async def test_get_campaign_returns_campaign_with_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)

    class _FakeResult:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

        def all(self):
            return self._row

        def fetchall(self):
            return self._row or []

    class _FakeConn:
        async def execute(self, stmt, *_args, **_kwargs):
            sql_text = str(getattr(stmt, "text", stmt))
            if "FROM campaigns" in sql_text:
                return _FakeResult(
                    {
                        "id": "019f76e9-c299-7756-a483-761aa106ba33",
                        "org_id": "00000000-0000-0000-0000-000000000001",
                        "brand_id": "00000000-0000-0000-0000-000000000002",
                        "status": "running",
                        "token_cost_usd": 1.25,
                        "created_at": now,
                        "started_at": now,
                        "completed_at": None,
                        "brief": {"objective": "Launch"},
                        "created_by": None,
                        "creator_email": None,
                    }
                )
            if "FROM conversations" in sql_text:
                return _FakeResult(None)
            if "FROM brand_scores" in sql_text:
                return _FakeResult([])
            if "FROM campaign_cost_attribution" in sql_text:
                return _FakeResult([])
            return _FakeResult(
                [
                    {
                        "id": "019f9000-0000-7000-8000-000000000001",
                        "task_id": "en-US_email_enterprise",
                        "locale": "en-US",
                        "channel": "email",
                        "segment": "enterprise",
                        "status": "published",
                        "final_content": "Done",
                        "composite_score": 8.7,
                        "translation_engine": None,
                        "back_translation_score": None,
                        "failure_reason": None,
                        "translation_checks": None,
                    }
                ]
            )

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)
    monkeypatch.setattr(
        campaigns,
        "_load_in_memory_trace",
        AsyncMock(
            return_value=[
                {
                    "step": 2,
                    "source": "loop",
                    "created_at": "2026-07-18T20:51:12Z",
                    "agents": ["personalization_agent"],
                    "next": ["translation_agent"],
                    "state": {"current_phase": "content_generated", "variants": []},
                }
            ]
        ),
    )

    result = await campaigns.get_campaign("019f76e9-c299-7756-a483-761aa106ba33")

    assert result["id"] == "019f76e9-c299-7756-a483-761aa106ba33"
    assert result["status"] == "running"
    assert result["brief"]["objective"] == "Launch"
    assert len(result["variants"]) == 1
    assert result["variants"][0]["task_id"] == "en-US_email_enterprise"
    assert result["variants"][0]["composite_score"] == 8.7
    assert result["in_memory_trace"][0]["agents"] == ["personalization_agent"]


@pytest.mark.asyncio
async def test_approve_campaign_transitions_status(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResult:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

    class _FakeConn:
        async def execute(self, stmt, *_args, **_kwargs):
            sql_text = str(getattr(stmt, "text", stmt))
            if "SELECT id, status" in sql_text:
                return _FakeResult(
                    {
                        "id": "019f76e9-c299-7756-a483-761aa106ba33",
                        "status": "awaiting_review",
                    }
                )
            return _FakeResult(None)

        async def commit(self):
            return None

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)

    result = await campaigns.approve_campaign(
        "019f76e9-c299-7756-a483-761aa106ba33",
        campaigns.ReviewDecision(decision="approved", reviewer_note="looks good"),
    )
    assert result["status"] == "published"
    assert result["decision"] == "approved"


@pytest.mark.asyncio
async def test_approve_campaign_rejects_non_reviewable_state(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResult:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

    class _FakeConn:
        async def execute(self, *_args, **_kwargs):
            return _FakeResult(
                {
                    "id": "019f76e9-c299-7756-a483-761aa106ba33",
                    "status": "failed",
                }
            )

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)

    with pytest.raises(HTTPException) as exc_info:
        await campaigns.approve_campaign(
            "019f76e9-c299-7756-a483-761aa106ba33",
            campaigns.ReviewDecision(decision="approved"),
        )

    assert exc_info.value.status_code == 409


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
