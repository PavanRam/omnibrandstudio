from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from api.deps import UserContext
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
