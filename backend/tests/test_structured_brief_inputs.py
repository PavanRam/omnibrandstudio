"""Structured brief-input endpoints (next_tasks.md item 23, 2026-07-27).

Locale pills / segment dropdown / budget-tier picker selections bypass
understanding_engine/brief_collector's LLM extraction entirely — these
endpoints directly patch the brief (locales, audience_segments, token_budget)
or compute deterministic suggestions (budget tiers, supported locales).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.deps import UserContext
from api.routers import conversations, knowledge
from pipeline.conversation_models import ConversationSession, PartialBrief


def _user() -> UserContext:
    return UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["admin"],
        auth_method="jwt",
    )


def _session(**brief_kwargs) -> ConversationSession:
    return ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_id="00000000-0000-0000-0000-000000000002",
        status="collecting",
        partial_brief=PartialBrief(**brief_kwargs),
    )


@pytest.mark.asyncio
async def test_get_supported_locales_matches_locale_utils_source_of_truth():
    result = await conversations.get_supported_locales()
    codes = {loc["code"] for loc in result["locales"]}
    # Source locale + every SUPPORTED_LOCALES entry, nothing else — same set
    # translation_agent actually gates against, so a pill can never produce
    # a locale the pipeline doesn't support.
    assert codes == {"en-US", "es", "fr", "de", "hi"}
    assert all("label" in loc for loc in result["locales"])


class _FakeConfigResult:
    def __init__(self, config: dict):
        self._config = config

    def mappings(self):
        return self

    def first(self):
        return {"config": self._config}


def _mock_brand_config(monkeypatch: pytest.MonkeyPatch, config: dict) -> None:
    class _FakeConn:
        async def execute(self, *_args, **_kwargs):
            return _FakeConfigResult(config)

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr("core.database.get_db", _fake_get_db)


@pytest.mark.asyncio
async def test_get_supported_locales_narrowed_by_brand_allow_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 42 (2026-07-27): a brand with a configured locale allow-list
    should only ever offer that subset via the picker, same source of truth
    intake_agent enforces server-side."""
    _mock_brand_config(monkeypatch, {"locales": ["fr"]})

    result = await conversations.get_supported_locales(brand_id="brand-1")

    codes = {loc["code"] for loc in result["locales"]}
    assert codes == {"en-US", "fr"}


@pytest.mark.asyncio
async def test_get_supported_channels_narrowed_by_brand_allow_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_brand_config(monkeypatch, {"channels": ["email", "sms"]})

    result = await conversations.get_supported_channels(brand_id="brand-1")

    assert set(result["channels"]) == {"email", "sms"}


@pytest.mark.asyncio
async def test_get_supported_channels_unconfigured_brand_gets_full_default_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty config (no allow-list configured) must fall back to every
    globally-supported channel, same as no brand_id at all."""
    _mock_brand_config(monkeypatch, {})
    from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS

    result = await conversations.get_supported_channels(brand_id="brand-1")

    assert set(result["channels"]) == set(DEFAULT_CHANNEL_CONSTRAINTS.keys())


@pytest.mark.asyncio
async def test_estimate_budget_scales_tiers_off_real_task_count(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))

    body = conversations.EstimateBudgetRequest(
        channels=["email", "sms"], locales=["en-US", "fr"], audience_segments=["urban professionals"]
    )
    result = await conversations.estimate_budget(
        "019f76e9-c299-7756-a483-761aa106ba33", body, _user()
    )

    assert result["task_count"] == 4  # 2 channels x 2 locales x 1 segment
    assert result["estimated_tokens"] == 4 * 500
    assert len(result["tiers"]) == 4
    # Tiers strictly increase with the multiplier, not fixed round numbers.
    tokens = [t["tokens"] for t in result["tiers"]]
    assert tokens == sorted(tokens)
    assert tokens[0] >= result["estimated_tokens"]


@pytest.mark.asyncio
async def test_estimate_budget_falls_back_to_session_brief_when_body_omits_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(channels=["email"], locales=["en-US"], audience_segments=["enterprise"])
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))

    body = conversations.EstimateBudgetRequest()  # nothing passed explicitly
    result = await conversations.estimate_budget(
        "019f76e9-c299-7756-a483-761aa106ba33", body, _user()
    )
    assert result["task_count"] == 1


@pytest.mark.asyncio
async def test_set_brief_field_rejects_unknown_field(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))

    body = conversations.SetBriefFieldRequest(field="objective", value="something")
    with pytest.raises(HTTPException) as exc:
        await conversations.set_brief_field("019f76e9-c299-7756-a483-761aa106ba33", body, _user())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_supported_channels_matches_channel_prompts_source_of_truth():
    from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS

    result = await conversations.get_supported_channels()
    # Same set content_generator actually has a template for — RCS must
    # never appear here, since it has no template (the exact live failure
    # this endpoint exists to prevent at the source).
    assert set(result["channels"]) == set(DEFAULT_CHANNEL_CONSTRAINTS.keys())
    assert "rcs" not in result["channels"]


@pytest.mark.asyncio
async def test_set_brief_field_rejects_unsupported_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))

    body = conversations.SetBriefFieldRequest(field="channels", value=["email", "rcs"])
    with pytest.raises(HTTPException) as exc:
        await conversations.set_brief_field("019f76e9-c299-7756-a483-761aa106ba33", body, _user())
    assert exc.value.status_code == 422
    assert "rcs" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_set_brief_field_channels_patches_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))
    monkeypatch.setattr(conversations.session_manager, "update_partial_brief", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "add_message", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "set_status", AsyncMock())

    body = conversations.SetBriefFieldRequest(field="channels", value=["email", "sms"])
    result = await conversations.set_brief_field(
        "019f76e9-c299-7756-a483-761aa106ba33", body, _user()
    )
    assert result["brief"]["channels"] == ["email", "sms"]


@pytest.mark.asyncio
async def test_set_brief_field_rejects_unsupported_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))

    body = conversations.SetBriefFieldRequest(field="locales", value=["en-US", "ja-JP"])
    with pytest.raises(HTTPException) as exc:
        await conversations.set_brief_field("019f76e9-c299-7756-a483-761aa106ba33", body, _user())
    assert exc.value.status_code == 422
    assert "ja-JP" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_set_brief_field_locales_patches_brief_and_persists_ack_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(
        objective="Launch", channels=["email"], audience_segments=["enterprise"], token_budget=2000
    )
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))
    update_mock = AsyncMock()
    monkeypatch.setattr(conversations.session_manager, "update_partial_brief", update_mock)
    add_message_mock = AsyncMock()
    monkeypatch.setattr(conversations.session_manager, "add_message", add_message_mock)
    set_status_mock = AsyncMock()
    monkeypatch.setattr(conversations.session_manager, "set_status", set_status_mock)

    body = conversations.SetBriefFieldRequest(field="locales", value=["en-US", "fr"])
    result = await conversations.set_brief_field(
        "019f76e9-c299-7756-a483-761aa106ba33", body, _user()
    )

    assert result["brief"]["locales"] == ["en-US", "fr"]
    assert result["is_complete"] is True  # every other field was already set
    assert result["awaiting_confirmation"] is True
    update_mock.assert_awaited_once()
    # Persists both the user's pick and the assistant's ack as separate
    # messages (2026-07-27 persistence fix) — a reload/conversation-switch
    # re-fetches history from GET /conversations/{id}/messages, and previously
    # only the ack was saved, so the selection bubble the frontend showed
    # live (built client-side) silently disappeared on reload.
    assert add_message_mock.await_count == 2
    user_call, assistant_call = add_message_mock.await_args_list
    assert user_call.args[1] == "user"
    assert user_call.args[2] == "Locales: en-US, fr"
    assert assistant_call.args[1] == "assistant"
    set_status_mock.assert_awaited_once_with(
        "019f76e9-c299-7756-a483-761aa106ba33", "awaiting_confirmation"
    )


@pytest.mark.asyncio
async def test_set_brief_field_token_budget_rejects_non_positive_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))

    body = conversations.SetBriefFieldRequest(field="token_budget", value=0)
    with pytest.raises(HTTPException) as exc:
        await conversations.set_brief_field("019f76e9-c299-7756-a483-761aa106ba33", body, _user())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_set_brief_field_incomplete_brief_does_not_set_awaiting_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()  # nothing set yet
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))
    monkeypatch.setattr(conversations.session_manager, "update_partial_brief", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "add_message", AsyncMock())
    set_status_mock = AsyncMock()
    monkeypatch.setattr(conversations.session_manager, "set_status", set_status_mock)

    body = conversations.SetBriefFieldRequest(field="audience_segments", value=["enterprise"])
    result = await conversations.set_brief_field(
        "019f76e9-c299-7756-a483-761aa106ba33", body, _user()
    )
    assert result["is_complete"] is False
    assert result["awaiting_confirmation"] is False
    set_status_mock.assert_not_awaited()


class _FakeSegmentDoc:
    def __init__(self, persona: str | None):
        self.metadata = {"persona": persona} if persona else {}


@pytest.mark.asyncio
async def test_list_segment_options_dedupes_and_filters_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    docs = [
        _FakeSegmentDoc("Highly Engaged Campaign Responder"),
        _FakeSegmentDoc("Highly Engaged Campaign Responder"),
        _FakeSegmentDoc("Budget-Conscious Low Spender"),
        _FakeSegmentDoc(None),
    ]
    fake_store = AsyncMock()
    fake_store.get_documents = AsyncMock(return_value=docs)
    monkeypatch.setattr(knowledge, "get_vector_store", lambda: fake_store)

    async def _fake_assert_brand_access(conn, user, brand_id):
        return None

    monkeypatch.setattr(knowledge, "_assert_brand_access", _fake_assert_brand_access)

    class _FakeConn:
        pass

    @__import__("contextlib").asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr(knowledge, "get_db", _fake_get_db)

    result = await knowledge.list_segment_options("00000000-0000-0000-0000-000000000002", _user())
    assert result["options"] == ["Budget-Conscious Low Spender", "Highly Engaged Campaign Responder"]
