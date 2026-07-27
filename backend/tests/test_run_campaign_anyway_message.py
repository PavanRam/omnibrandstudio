"""POST /conversations/{id}/run-anyway now posts the same "Campaign queued
successfully" confirmation the normal chat-confirm path already sends.

Regression (2026-07-26): "Proceed anyway" bypasses _process_turn entirely (a
button click, not a chat message), so the campaign previously started with
zero trace in the conversation transcript — no acknowledgment at all.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.deps import UserContext
from api.routers import conversations
from pipeline.conversation_models import ConversationSession, PartialBrief


def _user() -> UserContext:
    return UserContext(
        user_id="019f0000-0000-7000-8000-000000000099",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="jwt",
    )


@pytest.mark.asyncio
async def test_run_campaign_anyway_posts_queued_message(monkeypatch: pytest.MonkeyPatch) -> None:
    session = ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_id="00000000-0000-0000-0000-000000000002",
        status="awaiting_confirmation",
        active_campaign_id=None,
        partial_brief=PartialBrief(
            objective="Launch",
            channels=["email"],
            locales=["en-US"],
            audience_segments=["enterprise"],
            token_budget=1000,
        ),
    )
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))
    attach_mock = AsyncMock()
    monkeypatch.setattr(conversations.session_manager, "attach_campaign", attach_mock)
    add_message_mock = AsyncMock()
    monkeypatch.setattr(conversations.session_manager, "add_message", add_message_mock)
    monkeypatch.setattr(
        conversations, "_enqueue_campaign", AsyncMock(return_value="019f7669-1111-7000-8000-000000000001")
    )

    result = await conversations.run_campaign_anyway(session.id, _user())

    assert result["campaign_id"] == "019f7669-1111-7000-8000-000000000001"
    assert "Campaign queued successfully" in result["message"]
    assert "019f7669-1111-7000-8000-000000000001" in result["message"]
    add_message_mock.assert_awaited_once_with(session.id, "assistant", result["message"])
    attach_mock.assert_awaited_once_with(session.id, "019f7669-1111-7000-8000-000000000001")
