"""POST /conversations/{id}/archive and /conversations/archive-failed —
user-requested non-destructive cleanup of failed conversations (2026-07-26).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.deps import UserContext
from api.routers import conversations
from pipeline.conversation_models import ConversationSession, PartialBrief


def _user(**overrides) -> UserContext:
    defaults = dict(
        user_id="019f0000-0000-7000-8000-000000000099",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="jwt",
    )
    defaults.update(overrides)
    return UserContext(**defaults)


@pytest.mark.asyncio
async def test_archive_conversation_sets_archived_status(monkeypatch: pytest.MonkeyPatch) -> None:
    session = ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_id="00000000-0000-0000-0000-000000000002",
        status="processing",
        partial_brief=PartialBrief(),
    )
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))
    set_status_mock = AsyncMock()
    monkeypatch.setattr(conversations.session_manager, "set_status", set_status_mock)

    result = await conversations.archive_conversation(session.id, _user())

    assert result == {"status": "archived"}
    set_status_mock.assert_awaited_once_with(session.id, "archived")


@pytest.mark.asyncio
async def test_archive_conversation_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc:
        await conversations.archive_conversation("019f76e9-c299-7756-a483-761aa106ba33", _user())

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_archive_conversation_403_cross_org(monkeypatch: pytest.MonkeyPatch) -> None:
    session = ConversationSession(
        id="019f76e9-c299-7756-a483-761aa106ba33",
        org_id="00000000-0000-0000-0000-000000000999",
        brand_id="00000000-0000-0000-0000-000000000002",
        status="processing",
        partial_brief=PartialBrief(),
    )
    monkeypatch.setattr(conversations.session_manager, "get", AsyncMock(return_value=session))

    with pytest.raises(HTTPException) as exc:
        await conversations.archive_conversation(session.id, _user())

    assert exc.value.status_code == 403
