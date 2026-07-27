"""Campaign archiving — permission split (2026-07-26).

Admins can archive any campaign regardless of status. Regular users can
only archive genuinely stuck/failed campaigns — never one that's
awaiting_review or published.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.campaign.archive_service import _regular_user_can_archive


def _row(status: str, *, started_at=None, created_at=None) -> dict:
    return {"status": status, "started_at": started_at, "created_at": created_at}


def test_regular_user_can_always_archive_failed():
    assert _regular_user_can_archive(_row("failed")) is True


def test_regular_user_cannot_archive_awaiting_review():
    assert _regular_user_can_archive(_row("awaiting_review")) is False


def test_regular_user_cannot_archive_published():
    assert _regular_user_can_archive(_row("published")) is False


def test_regular_user_cannot_archive_recently_queued():
    now = datetime.now(UTC)
    row = _row("queued", started_at=now - timedelta(minutes=10), created_at=now - timedelta(minutes=10))
    assert _regular_user_can_archive(row) is False


def test_regular_user_can_archive_stuck_running_past_threshold():
    now = datetime.now(UTC)
    row = _row("running", started_at=now - timedelta(hours=2), created_at=now - timedelta(hours=2))
    assert _regular_user_can_archive(row) is True


def test_regular_user_cannot_archive_recent_draft():
    now = datetime.now(UTC)
    row = _row("draft", created_at=now - timedelta(hours=1))
    assert _regular_user_can_archive(row) is False


def test_regular_user_can_archive_abandoned_draft_past_threshold():
    now = datetime.now(UTC)
    row = _row("draft", created_at=now - timedelta(hours=30))
    assert _regular_user_can_archive(row) is True


@pytest.mark.asyncio
async def test_archive_campaign_route_admin_bypasses_status_check(monkeypatch):
    from unittest.mock import AsyncMock

    from api.deps import UserContext
    from api.routers import campaigns

    archive_mock = AsyncMock()
    monkeypatch.setattr(campaigns.archive_service, "archive_campaign", archive_mock)

    user = UserContext(
        user_id="019f0000-0000-7000-8000-000000000099",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["admin"],
        auth_method="jwt",
    )

    result = await campaigns.archive_campaign_route("019f76e9-c299-7756-a483-761aa106ba33", user)

    assert result["status"] == "archived"
    archive_mock.assert_awaited_once_with(
        "019f76e9-c299-7756-a483-761aa106ba33", is_admin=True
    )


@pytest.mark.asyncio
async def test_archive_campaign_route_regular_user_forbidden(monkeypatch):
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from api.deps import UserContext
    from api.routers import campaigns

    archive_mock = AsyncMock(side_effect=PermissionError("campaign status 'published' cannot be archived"))
    monkeypatch.setattr(campaigns.archive_service, "archive_campaign", archive_mock)

    user = UserContext(
        user_id="019f0000-0000-7000-8000-000000000099",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["editor"],
        auth_method="jwt",
    )

    with pytest.raises(HTTPException) as exc:
        await campaigns.archive_campaign_route("019f76e9-c299-7756-a483-761aa106ba33", user)

    assert exc.value.status_code == 403
    archive_mock.assert_awaited_once_with(
        "019f76e9-c299-7756-a483-761aa106ba33", is_admin=False
    )
