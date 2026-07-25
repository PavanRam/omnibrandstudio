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
async def test_list_sets_backfills_from_guides_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    list_sets_mock = AsyncMock(
        side_effect=[
            [],
            [
                {
                    "id": "set-1",
                    "locale": "en-US",
                    "guide_version": "datasets-v1",
                    "status": "draft",
                    "source": "llm_generated",
                    "example_count": 0,
                    "golden_count": 0,
                }
            ],
        ]
    )
    backfill_mock = AsyncMock(return_value=1)

    monkeypatch.setattr(golden_dataset, "get_db", _fake_get_db)
    monkeypatch.setattr(golden_dataset, "_assert_brand_access", AsyncMock(return_value=None))
    monkeypatch.setattr(golden_dataset.svc, "list_sets", list_sets_mock)
    monkeypatch.setattr(golden_dataset.svc, "backfill_sets_from_guide_versions", backfill_mock)

    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=["admin"])
    result = await golden_dataset.list_sets("brand-a", user)

    assert result["count"] == 1
    assert result["items"][0]["id"] == "set-1"
    assert conn.committed is True
    assert list_sets_mock.await_count == 2
    backfill_mock.assert_awaited_once()


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
