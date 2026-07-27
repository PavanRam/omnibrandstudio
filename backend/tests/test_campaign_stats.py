from __future__ import annotations

from contextlib import asynccontextmanager
import pytest
from api.deps import UserContext
from api.routers.campaigns import get_campaign_stats


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.last_query = None
        self.last_params = None

    async def execute(self, query, params):
        self.last_query = query
        self.last_params = params
        return _FakeResult(self._rows)


@pytest.mark.asyncio
async def test_get_campaign_stats_admin_scopes_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"status": "draft", "count": 5},
        {"status": "awaiting_review", "count": 2},
        {"status": "published", "count": 10},
        {"status": "failed", "count": 3},
        {"status": "queued", "count": 1},
    ]

    fake_conn = _FakeConn(rows)

    @asynccontextmanager
    async def _fake_get_db():
        yield fake_conn

    from api.routers import campaigns
    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["admin"],
    )

    result = await get_campaign_stats(user)

    assert result["total"] == 21
    assert result["draft"] == 5
    assert result["pending"] == 2
    assert result["published"] == 10
    assert result["failed"] == 3

    assert fake_conn.last_params["created_by"] is None
    assert fake_conn.last_params["org_id"] == "00000000-0000-0000-0000-000000000001"
    assert fake_conn.last_params["brand_ids"] == ["00000000-0000-0000-0000-000000000002"]


@pytest.mark.asyncio
async def test_get_campaign_stats_user_scopes_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"status": "draft", "count": 2},
        {"status": "published", "count": 4},
    ]

    fake_conn = _FakeConn(rows)

    @asynccontextmanager
    async def _fake_get_db():
        yield fake_conn

    from api.routers import campaigns
    monkeypatch.setattr(campaigns, "get_db", _fake_get_db)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["user"],
    )

    result = await get_campaign_stats(user)

    assert result["total"] == 6
    assert result["draft"] == 2
    assert result["pending"] == 0
    assert result["published"] == 4
    assert result["failed"] == 0

    assert fake_conn.last_params["created_by"] == "019f76e9-c299-7756-a483-761aa106ba11"
