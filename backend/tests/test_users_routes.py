from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.deps import UserContext
from api.routers import users


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        if not self._rows:
            raise RuntimeError("Expected one row")
        return self._rows[0]

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, responses):
        self._responses = responses
        self._index = 0
        self.committed = False

    async def execute(self, *_args, **_kwargs):
        rows = self._responses[self._index] if self._index < len(self._responses) else []
        self._index += 1
        return _FakeResult(rows)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_list_users_returns_org_users(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    conn = _FakeConn(
        [
            [
                {
                    "id": "019f76e9-c299-7756-a483-761aa106ba21",
                    "email": "editor@example.com",
                    "roles": ["editor"],
                    "brand_ids": ["00000000-0000-0000-0000-000000000002"],
                    "status": "active",
                    "created_at": now,
                    "last_login_at": None,
                }
            ]
        ]
    )

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(users, "get_db", _fake_get_db)

    current_user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["admin"],
        auth_method="jwt",
    )

    result = await users.list_users(current_user=current_user)

    assert result.count == 1
    assert result.items[0].email == "editor@example.com"
    assert result.items[0].roles == ["editor"]


@pytest.mark.asyncio
async def test_create_user_generates_temporary_password(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    conn = _FakeConn(
        [
            [
                {
                    "id": "019f76e9-c299-7756-a483-761aa106ba31",
                    "email": "viewer@example.com",
                    "roles": ["viewer"],
                    "brand_ids": ["00000000-0000-0000-0000-000000000002"],
                    "status": "active",
                    "created_at": now,
                    "last_login_at": None,
                }
            ]
        ]
    )

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(users, "get_db", _fake_get_db)
    monkeypatch.setattr(users, "hash_password", lambda _raw: "hashed-value")
    monkeypatch.setattr(users, "_new_temporary_password", lambda: "TmpPass!123")
    monkeypatch.setattr(users, "write_audit", AsyncMock())

    current_user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["admin"],
        auth_method="jwt",
    )

    result = await users.create_user(
        users.CreateUserRequest(name="Jane Doe", email="viewer@example.com", role="viewer"),
        current_user=current_user,
    )

    assert result.user.email == "viewer@example.com"
    assert result.temporary_password == "TmpPass!123"
    assert conn.committed is True


@pytest.mark.asyncio
async def test_create_user_with_explicit_password_hides_temporary_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    conn = _FakeConn(
        [
            [
                {
                    "id": "019f76e9-c299-7756-a483-761aa106ba41",
                    "email": "admin2@example.com",
                    "roles": ["admin"],
                    "brand_ids": ["00000000-0000-0000-0000-000000000002"],
                    "status": "active",
                    "created_at": now,
                    "last_login_at": None,
                }
            ]
        ]
    )

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(users, "get_db", _fake_get_db)
    monkeypatch.setattr(users, "hash_password", lambda _raw: "hashed-value")
    monkeypatch.setattr(users, "write_audit", AsyncMock())

    current_user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        roles=["admin"],
        auth_method="jwt",
    )

    result = await users.create_user(
        users.CreateUserRequest(
            name="Admin Two",
            email="admin2@example.com",
            role="admin",
            password="StrongPass!234",
        ),
        current_user=current_user,
    )

    assert result.user.roles == ["admin"]
    assert result.temporary_password is None
    assert conn.committed is True


BRAND_A = "00000000-0000-0000-0000-000000000002"
BRAND_B = "00000000-0000-0000-0000-0000000000ab"


@pytest.mark.asyncio
async def test_create_user_with_explicit_brand_ids_overrides_inherited_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit brand_ids (item 44 fast-follow, 2026-07-27) must be used
    exactly as given, not silently replaced by the creating admin's own
    brand_ids (the old default-inherit behavior, kept only when the field
    is omitted entirely)."""
    now = datetime.now(timezone.utc)
    conn = _FakeConn(
        [
            [{"id": BRAND_B}],  # _validate_brand_ids_in_org lookup
            [
                {
                    "id": "019f76e9-c299-7756-a483-761aa106ba51",
                    "email": "newuser@example.com",
                    "roles": ["editor"],
                    "brand_ids": [BRAND_B],
                    "status": "active",
                    "created_at": now,
                    "last_login_at": None,
                }
            ],
        ]
    )

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(users, "get_db", _fake_get_db)
    monkeypatch.setattr(users, "hash_password", lambda _raw: "hashed-value")
    monkeypatch.setattr(users, "_new_temporary_password", lambda: "TmpPass!123")
    monkeypatch.setattr(users, "write_audit", AsyncMock())

    current_user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=[BRAND_A],  # the creator's own brand — must NOT be used
        roles=["admin"],
        auth_method="jwt",
    )

    result = await users.create_user(
        users.CreateUserRequest(
            name="New User", email="newuser@example.com", role="editor", brand_ids=[BRAND_B]
        ),
        current_user=current_user,
    )

    assert result.user.brand_ids == [BRAND_B]


@pytest.mark.asyncio
async def test_create_user_rejects_brand_id_not_in_org(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn([[]])  # _validate_brand_ids_in_org finds nothing

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(users, "get_db", _fake_get_db)
    monkeypatch.setattr(users, "hash_password", lambda _raw: "hashed-value")

    current_user = UserContext(
        user_id="u1", org_id="org-1", brand_ids=[], roles=["admin"], auth_method="jwt"
    )

    with pytest.raises(HTTPException) as exc:
        await users.create_user(
            users.CreateUserRequest(
                name="New User", email="newuser@example.com", role="editor", brand_ids=[BRAND_B]
            ),
            current_user=current_user,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_update_user_brands_persists_new_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(
        [
            [{"id": BRAND_B}],  # _validate_brand_ids_in_org
            [
                {
                    "id": "019f76e9-c299-7756-a483-761aa106ba51",
                    "email": "user@example.com",
                    "roles": ["editor"],
                    "brand_ids": [BRAND_B],
                    "status": "active",
                    "created_at": datetime.now(timezone.utc),
                    "last_login_at": None,
                }
            ],
        ]
    )

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(users, "get_db", _fake_get_db)
    monkeypatch.setattr(users, "write_audit", AsyncMock())

    current_user = UserContext(
        user_id="u1", org_id="org-1", brand_ids=[], roles=["admin"], auth_method="jwt"
    )

    result = await users.update_user_brands(
        "019f76e9-c299-7756-a483-761aa106ba51",
        users.UpdateUserBrandsRequest(brand_ids=[BRAND_B]),
        current_user=current_user,
    )

    assert result.brand_ids == [BRAND_B]
    assert conn.committed is True


@pytest.mark.asyncio
async def test_update_user_brands_404_when_user_not_in_org(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn([[{"id": BRAND_B}], []])  # validate ok, then UPDATE finds no matching row

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(users, "get_db", _fake_get_db)

    current_user = UserContext(
        user_id="u1", org_id="org-1", brand_ids=[], roles=["admin"], auth_method="jwt"
    )

    with pytest.raises(HTTPException) as exc:
        await users.update_user_brands(
            "no-such-user",
            users.UpdateUserBrandsRequest(brand_ids=[BRAND_B]),
            current_user=current_user,
        )
    assert exc.value.status_code == 404
