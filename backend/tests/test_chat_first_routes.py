from __future__ import annotations

import json
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.deps import UserContext
from api.main import app
from api.routers import campaigns, conversations
from pipeline.conversation_models import (
    ConversationPlannerOutput,
    ConversationSession,
    ExtractionMeta,
    IntentClassification,
    PartialBrief,
    RecentCampaign,
    RecentConversation,
    UnderstandingResult,
)


@pytest.mark.asyncio
async def test_create_conversation_returns_session(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_id="00000000-0000-0000-0000-000000000002",
        created_by="019f76e9-c299-7756-a483-761aa106ba11",
        status="collecting",
    )
    create_mock = AsyncMock(return_value=expected)
    monkeypatch.setattr(conversations.session_manager, "create", create_mock)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
    )
    body = conversations.CreateConversationRequest(
        brand_id="00000000-0000-0000-0000-000000000002",
    )

    result = await conversations.create_conversation(body, user)

    assert result.id == expected.id
    create_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_recent_campaigns_returns_serialized_list(monkeypatch: pytest.MonkeyPatch) -> None:
    recent = [
        RecentCampaign(
            campaign_id="019f76e9-c299-7756-a483-761aa106ba33",
            brand_id="00000000-0000-0000-0000-000000000002",
            status="queued",
            created_at="2026-07-19T00:00:00Z",  # type: ignore[arg-type]
            variant_count=0,
            cost_usd=0,
        )
    ]
    recent_campaigns_mock = AsyncMock(return_value=recent)
    monkeypatch.setattr(conversations, "get_recent_campaigns", recent_campaigns_mock)

    user = UserContext(
        user_id="api_key",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )

    result = await conversations.recent_campaigns(user)

    assert len(result["campaigns"]) == 1
    assert result["campaigns"][0]["campaign_id"] == "019f76e9-c299-7756-a483-761aa106ba33"
    recent_campaigns_mock.assert_awaited_once_with(
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        created_by=None,
        include_archived=False,
        limit=12,
    )


@pytest.mark.asyncio
async def test_recent_campaigns_scopes_to_jwt_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    recent_campaigns_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(conversations, "get_recent_campaigns", recent_campaigns_mock)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="jwt",
    )

    await conversations.recent_campaigns(user)

    recent_campaigns_mock.assert_awaited_once_with(
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        created_by="019f76e9-c299-7756-a483-761aa106ba11",
        include_archived=False,
        limit=12,
    )


@pytest.mark.asyncio
async def test_recent_conversations_returns_serialized_list(monkeypatch: pytest.MonkeyPatch) -> None:
    recent = [
        RecentConversation(
            conversation_id="019f76e9-c299-7756-a483-761aa106ba33",
            brand_id="00000000-0000-0000-0000-000000000002",
            status="collecting",
            active_campaign_id=None,
            partial_brief=PartialBrief(objective="Launch sustainability report"),
            updated_at="2026-07-19T00:00:00Z",  # type: ignore[arg-type]
        )
    ]
    list_recent_mock = AsyncMock(return_value=recent)
    monkeypatch.setattr(conversations.session_manager, "list_recent", list_recent_mock)

    user = UserContext(
        user_id="api_key",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )

    result = await conversations.recent_conversations(user)

    assert len(result["conversations"]) == 1
    assert result["conversations"][0]["conversation_id"] == "019f76e9-c299-7756-a483-761aa106ba33"
    list_recent_mock.assert_awaited_once_with(
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        created_by=None,
        limit=12,
    )


@pytest.mark.asyncio
async def test_recent_conversations_by_user_returns_serialized_list(monkeypatch: pytest.MonkeyPatch) -> None:
    recent = [
        RecentConversation(
            conversation_id="019f76e9-c299-7756-a483-761aa106ba33",
            brand_id="00000000-0000-0000-0000-000000000002",
            status="collecting",
            active_campaign_id=None,
            partial_brief=PartialBrief(objective="Launch sustainability report"),
            updated_at="2026-07-19T00:00:00Z",  # type: ignore[arg-type]
        )
    ]
    list_recent_mock = AsyncMock(return_value=recent)
    monkeypatch.setattr(conversations.session_manager, "list_recent", list_recent_mock)

    user = UserContext(
        user_id="api_key",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )

    result = await conversations.recent_conversations_by_user("api_key", user)

    assert len(result["conversations"]) == 1
    assert result["conversations"][0]["conversation_id"] == "019f76e9-c299-7756-a483-761aa106ba33"
    list_recent_mock.assert_awaited_once_with(
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        created_by=None,
        limit=12,
    )


@pytest.mark.asyncio
async def test_recent_conversations_scopes_to_jwt_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    list_recent_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(conversations.session_manager, "list_recent", list_recent_mock)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="jwt",
    )

    await conversations.recent_conversations(user)

    list_recent_mock.assert_awaited_once_with(
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        created_by="019f76e9-c299-7756-a483-761aa106ba11",
        limit=12,
    )


@pytest.mark.asyncio
async def test_recent_conversations_by_user_denies_other_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversations.session_manager, "list_recent", AsyncMock(return_value=[]))

    user = UserContext(
        user_id="api_key",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )

    with pytest.raises(HTTPException) as exc_info:
        await conversations.recent_conversations_by_user("someone-else", user)

    assert "user access denied" in str(exc_info.value)


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._row = row

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._row)


@pytest.mark.asyncio
async def test_rerun_campaign_dispatches_service(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign_row = {
        "id": "019f76e9-c299-7756-a483-761aa106ba33",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "brand_id": "00000000-0000-0000-0000-000000000002",
    }

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn(campaign_row)

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)
    rerun_mock = AsyncMock(
        return_value={
            "campaign_id": "019f76e9-c299-7756-a483-761aa106ba33",
            "revision_number": 2,
            "resumed_from_node": "content_generator",
            "status": "content_generated",
        }
    )
    monkeypatch.setattr(campaigns.rerun_service, "rerun_campaign", rerun_mock)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
    )

    body = campaigns.RerunCampaignRequest(resume_from_node="content_generator")
    result = await campaigns.rerun_campaign(
        "019f76e9-c299-7756-a483-761aa106ba33",
        body,
        user,
    )

    assert result["revision_number"] == 2
    rerun_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_rerun_campaign_denies_brand_access(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign_row = {
        "id": "019f76e9-c299-7756-a483-761aa106ba33",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "brand_id": "00000000-0000-0000-0000-000000000002",
    }

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn(campaign_row)

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000099"],
    )

    body = campaigns.RerunCampaignRequest(resume_from_node="content_generator")

    with pytest.raises(HTTPException) as exc_info:
        await campaigns.rerun_campaign(
            "019f76e9-c299-7756-a483-761aa106ba33",
            body,
            user,
        )

    assert "brand access denied" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rerun_campaign_maps_value_error_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign_row = {
        "id": "019f76e9-c299-7756-a483-761aa106ba33",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "brand_id": "00000000-0000-0000-0000-000000000002",
    }

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn(campaign_row)

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)
    monkeypatch.setattr(
        campaigns.rerun_service,
        "rerun_campaign",
        AsyncMock(side_effect=ValueError("invalid rerun request")),
    )

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
    )

    body = campaigns.RerunCampaignRequest(resume_from_node="content_generator")

    with pytest.raises(HTTPException) as exc_info:
        await campaigns.rerun_campaign(
            "019f76e9-c299-7756-a483-761aa106ba33",
            body,
            user,
        )

    assert exc_info.value.status_code == 422
    assert "invalid rerun request" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rerun_campaign_maps_runtime_error_to_404(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign_row = {
        "id": "019f76e9-c299-7756-a483-761aa106ba33",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "brand_id": "00000000-0000-0000-0000-000000000002",
    }

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn(campaign_row)

    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)
    monkeypatch.setattr(
        campaigns.rerun_service,
        "rerun_campaign",
        AsyncMock(side_effect=RuntimeError("checkpoint not found")),
    )

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
    )

    body = campaigns.RerunCampaignRequest(resume_from_node="content_generator")

    with pytest.raises(HTTPException) as exc_info:
        await campaigns.rerun_campaign(
            "019f76e9-c299-7756-a483-761aa106ba33",
            body,
            user,
        )

    assert exc_info.value.status_code == 404
    assert "checkpoint not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_stream_campaign_events_yields_pubsub_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePubSub:
        def __init__(self):
            self._returned = False

        async def subscribe(self, _channel):
            return None

        async def get_message(self, ignore_subscribe_messages=True, timeout=15.0):
            _ = ignore_subscribe_messages, timeout
            if self._returned:
                await asyncio.sleep(0)
                return None
            self._returned = True
            return {
                "type": "message",
                "data": '{"agent":"content_generator","phase":"variant_generated"}',
            }

        async def unsubscribe(self, _channel):
            return None

        async def aclose(self):
            return None

    class _FakeRedis:
        def pubsub(self):
            return _FakePubSub()

    monkeypatch.setattr(campaigns, "get_redis", lambda: _FakeRedis())

    response = await campaigns.stream_campaign_events("019f76e9-c299-7756-a483-761aa106ba33")
    iterator = response.body_iterator
    first = await anext(iterator)
    second = await anext(iterator)

    assert first == ": connected\n\n"
    assert "variant_generated" in second
    payload_json = second.replace("data: ", "").strip()
    payload = json.loads(payload_json)
    assert payload["source"] == "live"
    assert payload["event_id"]

    if hasattr(iterator, "aclose"):
        await iterator.aclose()


@pytest.mark.asyncio
async def test_replay_campaign_events_returns_normalized_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = [
        {
            "step": 1,
            "created_at": "2026-07-19T10:00:00Z",
            "agents": ["content_generator"],
            "agent_output": {
                "content_generator": {
                    "variants": [{"task_id": "t-1", "channel": "linkedin"}],
                }
            },
            "state": {
                "current_phase": "content_generated",
                "variant_count": 1,
                "human_review_requested": False,
            },
        }
    ]
    monkeypatch.setattr(campaigns, "_load_in_memory_trace", AsyncMock(return_value=timeline))

    result = await campaigns.replay_campaign_events(
        "019f76e9-c299-7756-a483-761aa106ba33",
        limit=60,
    )

    assert result["campaign_id"] == "019f76e9-c299-7756-a483-761aa106ba33"
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert event["source"] == "replay"
    assert event["event_id"]
    assert event["agent"] == "content_generator"
    assert event["phase"] == "content_generated"
    assert event["payload"]["variant_count"] == 1
    assert result["cursor_found"] is True
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_replay_campaign_events_orders_oldest_to_newest(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = [
        {
            "step": 1,
            "created_at": "2026-07-19T10:00:00Z",
            "agents": ["intake_agent"],
            "agent_output": {"intake_agent": {"brief_valid": True}},
            "state": {"current_phase": "intake_validated", "variant_count": 0},
        },
        {
            "step": 2,
            "created_at": "2026-07-19T10:01:00Z",
            "agents": ["content_generator"],
            "agent_output": {"content_generator": {"variants": [{"task_id": "t-1"}]}},
            "state": {"current_phase": "content_generated", "variant_count": 1},
        },
        {
            "step": 3,
            "created_at": "2026-07-19T10:02:00Z",
            "agents": ["personalization_agent"],
            "agent_output": {"personalization_agent": {"variants": [{"task_id": "t-1", "segment": "a"}]}},
            "state": {"current_phase": "personalized", "variant_count": 1},
        },
    ]
    monkeypatch.setattr(campaigns, "_load_in_memory_trace", AsyncMock(return_value=timeline))

    result = await campaigns.replay_campaign_events(
        "019f76e9-c299-7756-a483-761aa106ba33",
        limit=10,
    )

    assert [event["agent"] for event in result["events"]] == [
        "intake_agent",
        "content_generator",
        "personalization_agent",
    ]


@pytest.mark.asyncio
async def test_replay_campaign_events_dedupes_duplicate_event_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = [
        {
            "step": 2,
            "created_at": "2026-07-19T10:01:00Z",
            "agents": ["content_generator"],
            "agent_output": {"content_generator": {"variants": [{"task_id": "t-1"}]}},
            "state": {"current_phase": "content_generated", "variant_count": 1},
        },
        {
            "step": 2,
            "created_at": "2026-07-19T10:01:05Z",
            "agents": ["content_generator"],
            "agent_output": {"content_generator": {"variants": [{"task_id": "t-1"}]}},
            "state": {"current_phase": "content_generated", "variant_count": 1},
        },
    ]
    monkeypatch.setattr(campaigns, "_load_in_memory_trace", AsyncMock(return_value=timeline))

    result = await campaigns.replay_campaign_events(
        "019f76e9-c299-7756-a483-761aa106ba33",
        limit=10,
    )

    assert len(result["events"]) == 1


@pytest.mark.asyncio
async def test_replay_campaign_events_cursor_window(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = [
        {
            "step": 1,
            "created_at": "2026-07-19T10:00:00Z",
            "agents": ["intake_agent"],
            "agent_output": {"intake_agent": {"brief_valid": True}},
            "state": {"current_phase": "intake_validated", "variant_count": 0},
        },
        {
            "step": 2,
            "created_at": "2026-07-19T10:01:00Z",
            "agents": ["content_generator"],
            "agent_output": {"content_generator": {"variants": [{"task_id": "t-1"}]}},
            "state": {"current_phase": "content_generated", "variant_count": 1},
        },
        {
            "step": 3,
            "created_at": "2026-07-19T10:02:00Z",
            "agents": ["personalization_agent"],
            "agent_output": {"personalization_agent": {"variants": [{"task_id": "t-1", "segment": "a"}]}},
            "state": {"current_phase": "personalized", "variant_count": 1},
        },
    ]
    monkeypatch.setattr(campaigns, "_load_in_memory_trace", AsyncMock(return_value=timeline))

    first_page = await campaigns.replay_campaign_events(
        "019f76e9-c299-7756-a483-761aa106ba33",
        limit=2,
    )

    assert len(first_page["events"]) == 2
    assert first_page["cursor_found"] is True
    assert first_page["has_more"] is True
    assert first_page["next_before_event_id"]

    second_page = await campaigns.replay_campaign_events(
        "019f76e9-c299-7756-a483-761aa106ba33",
        limit=2,
        before_event_id=first_page["next_before_event_id"],
    )

    assert len(second_page["events"]) == 1
    assert second_page["cursor_found"] is True
    assert second_page["has_more"] is False


@pytest.mark.asyncio
async def test_replay_campaign_events_unknown_cursor_returns_empty_window(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = [
        {
            "step": 1,
            "created_at": "2026-07-19T10:00:00Z",
            "agents": ["intake_agent"],
            "agent_output": {"intake_agent": {"brief_valid": True}},
            "state": {"current_phase": "intake_validated", "variant_count": 0},
        }
    ]
    monkeypatch.setattr(campaigns, "_load_in_memory_trace", AsyncMock(return_value=timeline))

    result = await campaigns.replay_campaign_events(
        "019f76e9-c299-7756-a483-761aa106ba33",
        limit=10,
        before_event_id="missing-cursor",
    )

    assert result["cursor_found"] is False
    assert result["events"] == []
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_campaign_agent_output_reply_uses_trace_data() -> None:
    trace = [
        {
            "agents": ["content_generator"],
            "agent_output": {"content_generator": {"variants": [{"task_id": "t-1"}, {"task_id": "t-2"}]}},
            "state": {"current_phase": "content_generated", "variant_count": 2},
        }
    ]

    summary = {
        "status": "running",
        "total_variants": 2,
        "variants_breakdown": "generated: 2",
    }

    message = await conversations._campaign_agent_output_reply(
        "019f76e9-c299-7756-a483-761aa106ba33",
        "show outputs from content generator",
        summary,
        trace,
        {},
    )

    assert "content_generator" in message
    assert "variants delta 2" in message


@pytest.mark.asyncio
async def test_campaign_agent_output_reply_resolves_all_via_llm(monkeypatch) -> None:
    """Regression: 'all of them' used to repeat the same canned clarifying
    question forever (see next_tasks.md item 8). The LLM-resolution fallback
    must recognize it and enumerate every known agent."""
    trace = [
        {
            "agents": ["content_generator"],
            "agent_output": {"content_generator": {"variants": [{"task_id": "t-1"}]}},
            "state": {"current_phase": "content_generated", "variant_count": 1},
        }
    ]
    summary = {"status": "running", "total_variants": 1, "variants_breakdown": "generated: 1"}

    monkeypatch.setattr(
        conversations,
        "traced_llm_call",
        AsyncMock(return_value=(json.dumps({"agents": list(conversations._KNOWN_AGENTS)}), {})),
    )

    message = await conversations._campaign_agent_output_reply(
        "019f76e9-c299-7756-a483-761aa106ba33",
        "All of them",
        summary,
        trace,
        {},
    )

    assert "content_generator" in message
    assert "publishing_agent" in message
    assert "Tell me which agent" not in message


@pytest.mark.asyncio
async def test_campaign_agent_output_reply_falls_back_when_llm_gives_no_signal(monkeypatch) -> None:
    monkeypatch.setattr(
        conversations,
        "traced_llm_call",
        AsyncMock(return_value=(json.dumps({"agents": []}), {})),
    )

    message = await conversations._campaign_agent_output_reply(
        "019f76e9-c299-7756-a483-761aa106ba33",
        "what's happening",
        {"status": "running", "total_variants": 0, "variants_breakdown": "none yet"},
        [],
        {},
    )

    assert "Tell me which agent" in message


def test_campaign_progress_reply_includes_trace_phase() -> None:
    summary = {
        "status": "running",
        "total_variants": 3,
        "variants_breakdown": "generated: 3",
        "trace_phase": "judge_scored",
    }

    message = conversations._campaign_progress_reply(
        "019f76e9-c299-7756-a483-761aa106ba33",
        summary,
    )

    assert "Latest trace phase: judge_scored" in message


def test_campaign_history_reply_includes_recent_agents() -> None:
    summary = {
        "status": "awaiting_review",
        "total_variants": 2,
        "variants_breakdown": "generated: 2",
        "recent_agents": ["content_generator", "judge_claude"],
    }

    message = conversations._campaign_history_reply(
        "019f76e9-c299-7756-a483-761aa106ba33",
        "019f76e9-c299-7756-a483-761aa106ba44",
        summary,
    )

    assert "Recent traced agents: content_generator, judge_claude" in message


def test_complete_brief_followup_is_conversational_for_greeting() -> None:
    message = conversations._complete_brief_followup("hi")

    assert "Hey." in message
    assert "run campaign" in message


def test_complete_brief_followup_offers_actions_for_help_prompt() -> None:
    message = conversations._complete_brief_followup("what can you do next?")

    assert "Your brief is complete." in message
    assert "run campaign" in message
    assert "show agent outputs" in message


def test_planner_followup_message_acknowledges_new_fields() -> None:
    previous = PartialBrief()
    current = PartialBrief(objective="Launch AI assistant", channels=["linkedin"]) 
    planner_output = ConversationPlannerOutput(
        stage="objective_discovery",
        objective="Collect next high-value detail",
        reply_strategy="high_value_followup",
        next_question="What audience should we focus on first?",
    )

    message = conversations._planner_followup_message(previous, current, planner_output)

    assert "captured the campaign objective" in message
    assert "and the channels" in message
    assert "What audience should we focus on first?" in message


def test_planner_followup_message_handles_correction_without_new_fields() -> None:
    previous = PartialBrief(objective="Launch AI assistant")
    current = PartialBrief(objective="Launch AI assistant")
    planner_output = ConversationPlannerOutput(
        stage="campaign_discovery",
        objective="Apply correction",
        reply_strategy="high_value_followup",
        next_question="What should we refine next?",
        correction_detected=True,
    )

    message = conversations._planner_followup_message(previous, current, planner_output)

    assert "applied that update" in message
    assert message.endswith("What should we refine next?")


def test_select_assistant_message_prefers_greeting_strategy() -> None:
    planner_output = ConversationPlannerOutput(
        stage="greeting",
        objective="Open collaboratively",
        reply_strategy="greeting",
        next_question="Hey, great to collaborate. What are you launching?",
    )

    message = conversations._select_assistant_message(
        campaign_id=None,
        campaign_copilot_message=None,
        brief=PartialBrief(),
        previous_brief=PartialBrief(),
        user_message="hi",
        planner_output=planner_output,
    )

    assert "what are you launching" in message.lower()


def test_brief_changes_reports_replacement_for_scalar() -> None:
    previous = PartialBrief(objective="Launch AI assistant")
    current = PartialBrief(objective="Drive enterprise pipeline")

    changes = conversations._brief_changes(previous, current)

    assert len(changes) == 1
    assert changes[0]["field"] == "objective"
    assert changes[0]["change_type"] == "replaced"
    assert changes[0]["before"] == "Launch AI assistant"
    assert changes[0]["after"] == "Drive enterprise pipeline"


def test_brief_changes_reports_added_for_list() -> None:
    previous = PartialBrief()
    current = PartialBrief(channels=["linkedin", "email"])

    changes = conversations._brief_changes(previous, current)

    channel_change = next(change for change in changes if change["field"] == "channels")
    assert channel_change["change_type"] == "added"
    assert channel_change["after"] == ["linkedin", "email"]


def test_conversation_websocket_turn_returns_campaign_id(monkeypatch: pytest.MonkeyPatch) -> None:
    session = ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_id="00000000-0000-0000-0000-000000000002",
        status="awaiting_confirmation",
        partial_brief=PartialBrief(),
    )

    monkeypatch.setattr(
        "api.deps._authenticate_api_key",
        AsyncMock(
            return_value=UserContext(
                user_id="api_key",
                org_id="00000000-0000-0000-0000-000000000001",
                brand_ids=["00000000-0000-0000-0000-000000000002"],
                auth_method="api_key",
            )
        ),
    )
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))
    monkeypatch.setattr(conversations.session_manager, "add_message", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "load_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(conversations.session_manager, "update_partial_brief", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "attach_campaign", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "set_status", AsyncMock())
    monkeypatch.setattr(
        conversations.understanding_engine,
        "understand",
        AsyncMock(
            return_value=UnderstandingResult(
                intent=IntentClassification(
                    primary="submit_campaign",
                    secondary=[],
                    confidence=1.0,
                    requires_action=True,
                ),
                brief=PartialBrief(
                    objective="Launch",
                    channels=["linkedin"],
                    locales=["en-US"],
                    audience_segments=["enterprise"],
                    token_budget=1000,
                ),
                extraction_meta=ExtractionMeta(field_confidence={}, source="llm"),
            )
        ),
    )
    monkeypatch.setattr(conversations, "_enqueue_campaign", AsyncMock(return_value="019f7669-1111-7000-8000-000000000001"))

    with TestClient(app) as client:
        with client.websocket_connect(
            "/conversations/019f76e9-c299-7756-a483-761aa106ba33?api_key=test-key"
        ) as websocket:
            websocket.send_json({"message": "run campaign now"})
            payload = websocket.receive_json()
            while payload.get("type") == "status":
                payload = websocket.receive_json()

    assert payload["campaign_id"] == "019f7669-1111-7000-8000-000000000001"
    assert payload["brief_complete"] is True
    assert isinstance(payload["brief_updates"], list)
    assert "the campaign objective" in payload["brief_updates"]
    assert isinstance(payload["brief_changes"], list)
    objective_change = next(change for change in payload["brief_changes"] if change["field"] == "objective")
    assert objective_change["change_type"] == "added"
    assert "primary_objective" in payload
    assert "secondary_objectives" in payload
    assert "turn_type" in payload
    assert "needs_clarification" in payload
    assert "clarification_target" in payload
    assert "brief_field_states" in payload


@pytest.mark.asyncio
async def test_process_turn_submit_intent_enqueues_without_run_phrase(monkeypatch: pytest.MonkeyPatch) -> None:
    session = ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_id="00000000-0000-0000-0000-000000000002",
        status="awaiting_confirmation",
        partial_brief=PartialBrief(),
    )
    user = UserContext(
        user_id="api_key",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )

    monkeypatch.setattr(conversations.session_manager, "add_message", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "load_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(conversations.session_manager, "update_partial_brief", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "attach_campaign", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "set_status", AsyncMock())
    monkeypatch.setattr(
        conversations.understanding_engine,
        "understand",
        AsyncMock(
            return_value=UnderstandingResult(
                intent=IntentClassification(
                    primary="submit_campaign",
                    secondary=[],
                    confidence=0.95,
                    requires_action=True,
                    mutation_intent=False,
                ),
                brief=PartialBrief(
                    objective="Launch",
                    channels=["linkedin"],
                    locales=["en-US"],
                    audience_segments=["enterprise"],
                    token_budget=1000,
                ),
                extraction_meta=ExtractionMeta(field_confidence={}, source="llm"),
            )
        ),
    )
    enqueue_mock = AsyncMock(return_value="019f7669-1111-7000-8000-000000000001")
    monkeypatch.setattr(conversations, "_enqueue_campaign", enqueue_mock)
    # DB-backed, mocked per this repo's convention (see test_review_service.py
    # docstring) — harmless no-op for tests that never reach this branch.
    monkeypatch.setattr(conversations, "find_similar_campaign", AsyncMock(return_value=None))
    monkeypatch.setattr(conversations.conversation_responder, "respond", AsyncMock(return_value="ignored"))

    result = await conversations._process_turn(
        session=session,
        conversation_id=session.id,
        user=user,
        user_message="please submit this",
    )

    assert result["intent"] == "submit_campaign"
    assert result["campaign_id"] == "019f7669-1111-7000-8000-000000000001"
    assert result["brief_complete"] is True
    enqueue_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_turn_complete_brief_plays_back_before_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_id="00000000-0000-0000-0000-000000000002",
        status="collecting",
        partial_brief=PartialBrief(),
    )
    user = UserContext(
        user_id="api_key",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )

    monkeypatch.setattr(conversations.session_manager, "add_message", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "load_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(conversations.session_manager, "update_partial_brief", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "attach_campaign", AsyncMock())
    set_status_mock = AsyncMock()
    monkeypatch.setattr(conversations.session_manager, "set_status", set_status_mock)
    monkeypatch.setattr(
        conversations.understanding_engine,
        "understand",
        AsyncMock(
            return_value=UnderstandingResult(
                intent=IntentClassification(primary="collect_brief", secondary=[], confidence=0.9),
                brief=PartialBrief(
                    objective="Launch",
                    channels=["linkedin"],
                    locales=["en-US"],
                    audience_segments=["enterprise"],
                    token_budget=1000,
                ),
                extraction_meta=ExtractionMeta(field_confidence={}, source="llm"),
            )
        ),
    )
    enqueue_mock = AsyncMock(return_value="019f7669-1111-7000-8000-000000000001")
    monkeypatch.setattr(conversations, "_enqueue_campaign", enqueue_mock)
    # DB-backed, mocked per this repo's convention (see test_review_service.py
    # docstring) — harmless no-op for tests that never reach this branch.
    monkeypatch.setattr(conversations, "find_similar_campaign", AsyncMock(return_value=None))
    monkeypatch.setattr(
        conversations.conversation_responder,
        "respond",
        AsyncMock(return_value="playback"),
    )

    result = await conversations._process_turn(
        session=session,
        conversation_id=session.id,
        user=user,
        user_message="here is the last detail",
    )

    assert result["campaign_id"] is None
    assert result["brief_complete"] is True
    assert result["awaiting_confirmation"] is True
    enqueue_mock.assert_not_awaited()
    set_status_mock.assert_awaited_once_with(session.id, "awaiting_confirmation")


@pytest.mark.asyncio
async def test_process_turn_submit_intent_does_not_enqueue_when_brief_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_id="00000000-0000-0000-0000-000000000002",
        status="collecting",
        partial_brief=PartialBrief(),
    )
    user = UserContext(
        user_id="api_key",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )

    monkeypatch.setattr(conversations.session_manager, "add_message", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "load_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(conversations.session_manager, "update_partial_brief", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "attach_campaign", AsyncMock())
    monkeypatch.setattr(conversations.session_manager, "set_status", AsyncMock())
    monkeypatch.setattr(
        conversations.understanding_engine,
        "understand",
        AsyncMock(
            return_value=UnderstandingResult(
                intent=IntentClassification(
                    primary="submit_campaign",
                    secondary=[],
                    confidence=0.91,
                    requires_action=True,
                    mutation_intent=False,
                ),
                brief=PartialBrief(objective="Launch"),
                extraction_meta=ExtractionMeta(field_confidence={}, source="llm"),
            )
        ),
    )
    enqueue_mock = AsyncMock(return_value="019f7669-1111-7000-8000-000000000001")
    monkeypatch.setattr(conversations, "_enqueue_campaign", enqueue_mock)
    # DB-backed, mocked per this repo's convention (see test_review_service.py
    # docstring) — harmless no-op for tests that never reach this branch.
    monkeypatch.setattr(conversations, "find_similar_campaign", AsyncMock(return_value=None))
    monkeypatch.setattr(
        conversations.conversation_responder,
        "respond",
        AsyncMock(
            return_value="Please add channels, locales, audience segments, and token budget.",
        ),
    )

    result = await conversations._process_turn(
        session=session,
        conversation_id=session.id,
        user=user,
        user_message="submit",
    )

    assert result["intent"] == "submit_campaign"
    assert result["campaign_id"] is None
    assert result["brief_complete"] is False
    enqueue_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_campaigns_admin_sees_all_and_can_include_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (2026-07-26, next_tasks.md item 15): admins can archive any
    campaign, which only means something if they can actually find it —
    admins see every campaign in their brand scope (not filtered to their
    own), and can opt into seeing archived ones."""
    recent_campaigns_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(conversations, "get_recent_campaigns", recent_campaigns_mock)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["admin"],
        auth_method="jwt",
    )

    await conversations.recent_campaigns(user, include_archived=True)

    recent_campaigns_mock.assert_awaited_once_with(
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        created_by=None,
        include_archived=True,
        limit=12,
    )


@pytest.mark.asyncio
async def test_recent_campaigns_regular_user_include_archived_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-admin passing include_archived=true must be ignored server-side
    — this is a permission boundary, not just a UI default."""
    recent_campaigns_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(conversations, "get_recent_campaigns", recent_campaigns_mock)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["editor"],
        auth_method="jwt",
    )

    await conversations.recent_campaigns(user, include_archived=True)

    recent_campaigns_mock.assert_awaited_once_with(
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        created_by="019f76e9-c299-7756-a483-761aa106ba11",
        include_archived=False,
        limit=12,
    )
