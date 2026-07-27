"""notify_campaign_published (2026-07-27) — the notification pushed when
resume_campaign lands a campaign on 'published', regardless of whether the
decision that triggered the resume came from the in-app dialog or Airtable.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services import notification_service


@pytest.mark.asyncio
async def test_notify_campaign_published_calls_notify_with_expected_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notify_mock = AsyncMock()
    monkeypatch.setattr(notification_service, "notify", notify_mock)

    await notification_service.notify_campaign_published(
        org_id="org-1",
        brand_id="brand-1",
        campaign_id="camp-1",
        created_by="user-1",
        title="Spring sale",
    )

    notify_mock.assert_awaited_once()
    kwargs = notify_mock.await_args.kwargs
    assert kwargs["recipient_user_id"] == "user-1"
    assert kwargs["type"] == "campaign_published"
    assert kwargs["campaign_id"] == "camp-1"
    assert "Spring sale" in kwargs["title"]


@pytest.mark.asyncio
async def test_notify_campaign_published_noop_without_created_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notify_mock = AsyncMock()
    monkeypatch.setattr(notification_service, "notify", notify_mock)

    await notification_service.notify_campaign_published(
        org_id="org-1", brand_id="brand-1", campaign_id="camp-1", created_by=None, title="Spring sale"
    )

    notify_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_variants_rejected_calls_notify_with_count_in_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notify_mock = AsyncMock()
    monkeypatch.setattr(notification_service, "notify", notify_mock)

    await notification_service.notify_variants_rejected(
        org_id="org-1",
        brand_id="brand-1",
        campaign_id="camp-1",
        created_by="user-1",
        title="Spring sale",
        rejected_items=[{"task_id": "t1"}, {"task_id": "t2"}],
    )

    notify_mock.assert_awaited_once()
    kwargs = notify_mock.await_args.kwargs
    assert kwargs["recipient_user_id"] == "user-1"
    assert kwargs["type"] == "variants_rejected"
    assert "2 variants" in kwargs["title"]


@pytest.mark.asyncio
async def test_notify_variants_rejected_noop_without_rejected_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notify_mock = AsyncMock()
    monkeypatch.setattr(notification_service, "notify", notify_mock)

    await notification_service.notify_variants_rejected(
        org_id="org-1", brand_id="brand-1", campaign_id="camp-1", created_by="user-1",
        title="Spring sale", rejected_items=[],
    )

    notify_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_variants_rejected_noop_without_created_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notify_mock = AsyncMock()
    monkeypatch.setattr(notification_service, "notify", notify_mock)

    await notification_service.notify_variants_rejected(
        org_id="org-1", brand_id="brand-1", campaign_id="camp-1", created_by=None,
        title="Spring sale", rejected_items=[{"task_id": "t1"}],
    )

    notify_mock.assert_not_awaited()
