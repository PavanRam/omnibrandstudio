"""publishing_agent recipient resolution (2026-07-27) — the campaign
creator's real email is now the primary recipient, resolved from
state["user_id"], falling back to the configured demo list
(PUBLISH_RECIPIENT_EMAILS) when there's no resolvable creator (e.g. an
API-key-created campaign, per CLAUDE.md's dual-auth note).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from core.config import settings
from pipeline.agents import publishing as publishing_module
from pipeline.agents.publishing import _resolve_creator_email, publishing_agent


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


def _mock_get_db(monkeypatch: pytest.MonkeyPatch, row: dict | None):
    class _FakeConn:
        async def execute(self, *_args, **_kwargs):
            return _FakeResult(row)

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr(publishing_module, "get_db", _fake_get_db)


@pytest.mark.asyncio
async def test_resolve_creator_email_returns_email_for_valid_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, {"email": "creator@example.com"})

    result = await _resolve_creator_email("019f76e9-c299-7756-a483-761aa106ba11")

    assert result == "creator@example.com"


@pytest.mark.asyncio
async def test_resolve_creator_email_none_for_non_uuid_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Server-to-server/API-key callers use a non-UUID actor sentinel — must
    fail open (None), not raise, so the caller falls back gracefully."""
    result = await _resolve_creator_email("api_key")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_creator_email_none_when_user_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, None)

    result = await _resolve_creator_email("019f76e9-c299-7756-a483-761aa106ba11")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_creator_email_fails_open_on_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _broken_get_db():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(publishing_module, "get_db", _broken_get_db)

    result = await _resolve_creator_email("019f76e9-c299-7756-a483-761aa106ba11")

    assert result is None


def _state(**overrides) -> dict:
    base = {
        "campaign_id": "camp-1",
        "user_id": "019f76e9-c299-7756-a483-761aa106ba11",
        "brief": {"objective": "Spring sale"},
        "variants": [
            {
                "task_id": "email_consumer",
                "channel": "email",
                "locale": "en-US",
                "segment": "consumer",
                "status": "approved",
                "final_content": "Hello!",
            }
        ],
        "aggregated_scores": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_publishing_agent_uses_creator_email_when_resolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, {"email": "creator@example.com"})
    monkeypatch.setattr(settings, "PUBLISH_RECIPIENT_EMAILS", "demo@example.com")
    send_mock = AsyncMock()
    monkeypatch.setattr(publishing_module.aiosmtplib, "send", send_mock)

    await publishing_agent(_state())

    send_mock.assert_awaited_once()
    sent_msg = send_mock.await_args.args[0]
    assert sent_msg["To"] == "creator@example.com"


@pytest.mark.asyncio
async def test_publishing_agent_falls_back_to_configured_list_when_no_creator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_get_db(monkeypatch, None)  # no resolvable user row
    monkeypatch.setattr(settings, "PUBLISH_RECIPIENT_EMAILS", "demo@example.com")
    send_mock = AsyncMock()
    monkeypatch.setattr(publishing_module.aiosmtplib, "send", send_mock)

    await publishing_agent(_state(user_id="api_key"))

    send_mock.assert_awaited_once()
    sent_msg = send_mock.await_args.args[0]
    assert sent_msg["To"] == "demo@example.com"


@pytest.mark.asyncio
async def test_publishing_agent_skips_when_no_creator_and_no_configured_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_get_db(monkeypatch, None)
    monkeypatch.setattr(settings, "PUBLISH_RECIPIENT_EMAILS", "")
    send_mock = AsyncMock()
    monkeypatch.setattr(publishing_module.aiosmtplib, "send", send_mock)

    result = await publishing_agent(_state(user_id="api_key"))

    send_mock.assert_not_awaited()
    assert result["publication_receipts"] == []
