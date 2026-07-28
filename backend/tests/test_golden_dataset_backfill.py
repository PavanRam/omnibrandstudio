from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from api.deps import UserContext
from api.routers import golden_dataset


@dataclass
class _FakeConn:
    committed: bool = False

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_backfill_sets_from_guides_is_explicit_post(monkeypatch: pytest.MonkeyPatch) -> None:
    # Backfill is a deliberate admin action via POST /backfill; GET never writes
    # (see golden_dataset.backfill_sets docstring). This exercises that POST path.
    conn = _FakeConn()

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    backfill_mock = AsyncMock(return_value=1)

    monkeypatch.setattr(golden_dataset, "get_db", _fake_get_db)
    monkeypatch.setattr(golden_dataset, "_assert_brand_access", AsyncMock(return_value=None))
    monkeypatch.setattr(golden_dataset.svc, "backfill_sets_from_guide_versions", backfill_mock)

    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=["admin"])
    result = await golden_dataset.backfill_sets("brand-a", user)

    assert result["sets_created"] == 1
    assert conn.committed is True
    backfill_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_sets_does_not_write(monkeypatch: pytest.MonkeyPatch) -> None:
    # GET list_sets is read-only: it never backfills or commits.
    conn = _FakeConn()

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    backfill_mock = AsyncMock(return_value=1)

    monkeypatch.setattr(golden_dataset, "get_db", _fake_get_db)
    monkeypatch.setattr(golden_dataset, "_assert_brand_access", AsyncMock(return_value=None))
    monkeypatch.setattr(golden_dataset.svc, "list_sets", AsyncMock(return_value=[]))
    monkeypatch.setattr(golden_dataset.svc, "backfill_sets_from_guide_versions", backfill_mock)

    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=["admin"])
    result = await golden_dataset.list_sets("brand-a", user)

    assert result["count"] == 0
    assert conn.committed is False
    backfill_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_draft_set_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(golden_dataset, "get_db", _fake_get_db)
    monkeypatch.setattr(golden_dataset, "_assert_brand_access", AsyncMock(return_value=None))
    monkeypatch.setattr(golden_dataset.svc, "open_draft_set", AsyncMock(return_value="set-2"))

    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=["admin"])
    body = golden_dataset.OpenSetRequest(brand_id="brand-a", locale="en-US", guide_version="datasets-v1")

    result = await golden_dataset.open_draft_set(body, user)

    assert result["status"] == "created"
    assert result["set_id"] == "set-2"
    assert conn.committed is True
