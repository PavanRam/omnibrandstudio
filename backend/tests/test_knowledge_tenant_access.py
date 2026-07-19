from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from api.deps import UserContext
from api.routers import knowledge
from api.routers.knowledge import _assert_brand_access


@dataclass
class _Result:
    exists: bool

    def mappings(self) -> "_Result":
        return self

    def first(self):
        return {"ok": 1} if self.exists else None


@dataclass
class _FakeConn:
    exists: bool

    async def exec_driver_sql(self, query: str, params: dict):
        return _Result(self.exists)


@pytest.mark.asyncio
async def test_assert_brand_access_denies_brand_not_in_scoped_user_list() -> None:
    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=[])
    conn = _FakeConn(exists=True)

    with pytest.raises(HTTPException) as exc:
        await _assert_brand_access(conn, user, "brand-b")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_brand_access_allows_brand_in_scoped_user_list() -> None:
    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=[])
    conn = _FakeConn(exists=False)

    await _assert_brand_access(conn, user, "brand-a")


@pytest.mark.asyncio
async def test_assert_brand_access_checks_org_brand_when_user_has_no_brand_list() -> None:
    user = UserContext(user_id="u2", org_id="org-1", brand_ids=[], roles=[])
    conn = _FakeConn(exists=False)

    with pytest.raises(HTTPException) as exc:
        await _assert_brand_access(conn, user, "brand-a")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_upload_customer_segments_returns_indexed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn(exists=True)

    monkeypatch.setattr(knowledge, "get_db", _fake_get_db)
    monkeypatch.setattr(knowledge, "_assert_brand_access", AsyncMock(return_value=None))
    monkeypatch.setattr(
        knowledge,
        "ingest_customer_segments",
        AsyncMock(
            return_value={
                "brand_id": "brand-a",
                "locale": "en-US",
                "version": "v1",
                "records_indexed": 2,
                "chunks_indexed": 3,
                "collection": "brand_brand-a_segments",
            }
        ),
    )

    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=[])
    file = UploadFile(filename="segments.csv", file=BytesIO(b"segment,size\nSMB,120\n"))

    result = await knowledge.upload_customer_segments(
        brand_id="brand-a",
        locale="en-US",
        version="v1",
        segment_file=file,
        user=user,
    )

    assert result["status"] == "indexed"
    assert result["collection"] == "brand_brand-a_segments"


@pytest.mark.asyncio
async def test_upload_customer_segments_maps_validation_error_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn(exists=True)

    monkeypatch.setattr(knowledge, "get_db", _fake_get_db)
    monkeypatch.setattr(knowledge, "_assert_brand_access", AsyncMock(return_value=None))
    monkeypatch.setattr(
        knowledge,
        "ingest_customer_segments",
        AsyncMock(side_effect=ValueError("Unsupported segment format")),
    )

    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=[])
    file = UploadFile(filename="segments.bin", file=BytesIO(b"raw"))

    with pytest.raises(HTTPException) as exc:
        await knowledge.upload_customer_segments(
            brand_id="brand-a",
            locale="en-US",
            version="v1",
            segment_file=file,
            user=user,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_list_segments_returns_items(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn(exists=True)

    monkeypatch.setattr(knowledge, "get_db", _fake_get_db)
    monkeypatch.setattr(knowledge, "_assert_brand_access", AsyncMock(return_value=None))
    monkeypatch.setattr(
        knowledge,
        "list_customer_segments",
        AsyncMock(return_value=[{"id": "s1", "text": "segment: SMB", "metadata": {"segment": "SMB"}}]),
    )

    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-a"], roles=[])

    result = await knowledge.list_segments(
        brand_id="brand-a",
        user=user,
        locale="en-US",
        version="v1",
        limit=10,
    )

    assert result["count"] == 1
    assert result["items"][0]["id"] == "s1"


@pytest.mark.asyncio
async def test_list_segments_denies_access(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn(exists=False)

    monkeypatch.setattr(knowledge, "get_db", _fake_get_db)
    monkeypatch.setattr(
        knowledge,
        "_assert_brand_access",
        AsyncMock(side_effect=HTTPException(status_code=403, detail="Brand not in caller scope")),
    )

    user = UserContext(user_id="u1", org_id="org-1", brand_ids=["brand-b"], roles=[])

    with pytest.raises(HTTPException) as exc:
        await knowledge.list_segments(
            brand_id="brand-a",
            user=user,
            locale="en-US",
            version="v1",
            limit=10,
        )

    assert exc.value.status_code == 403
