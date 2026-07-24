from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.deps import UserContext
from api.routers import auth


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self._index = 0
        self.committed = False

    async def execute(self, *_args, **_kwargs):
        row = self._rows[self._index] if self._index < len(self._rows) else None
        self._index += 1
        return _FakeResult(row)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_login_returns_tokens_and_user(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {
        "id": "019f76e9-c299-7756-a483-761aa106ba11",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "email": "user@example.com",
        "password_hash": "hashed",
        "roles": ["editor"],
        "brand_ids": ["00000000-0000-0000-0000-000000000002"],
        "status": "active",
    }
    conn = _FakeConn([row, None])

    @asynccontextmanager
    async def _fake_get_db():
        yield conn

    monkeypatch.setattr(auth, "get_db", _fake_get_db)
    monkeypatch.setattr(auth, "is_locked_out", AsyncMock(return_value=False))
    monkeypatch.setattr(auth, "verify_password", lambda _pw, _hash: True)
    monkeypatch.setattr(auth, "clear_failed_logins", AsyncMock())
    monkeypatch.setattr(auth, "record_failed_login", AsyncMock())
    monkeypatch.setattr(auth, "create_access_token", lambda **_kwargs: "access-token")
    monkeypatch.setattr(auth, "create_refresh_token", lambda **_kwargs: "refresh-token")

    result = await auth.login(auth.LoginRequest(email="user@example.com", password="passw0rd!"))

    assert result.access_token == "access-token"
    assert result.refresh_token == "refresh-token"
    assert result.user.user_id == "019f76e9-c299-7756-a483-761aa106ba11"
    assert conn.committed is True


@pytest.mark.asyncio
async def test_login_invalid_credentials_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {
        "id": "019f76e9-c299-7756-a483-761aa106ba11",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "email": "user@example.com",
        "password_hash": "hashed",
        "roles": ["editor"],
        "brand_ids": ["00000000-0000-0000-0000-000000000002"],
        "status": "active",
    }

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn([row])

    record_failed = AsyncMock()
    monkeypatch.setattr(auth, "get_db", _fake_get_db)
    monkeypatch.setattr(auth, "is_locked_out", AsyncMock(return_value=False))
    monkeypatch.setattr(auth, "verify_password", lambda _pw, _hash: False)
    monkeypatch.setattr(auth, "record_failed_login", record_failed)

    with pytest.raises(HTTPException) as exc_info:
        await auth.login(auth.LoginRequest(email="user@example.com", password="passw0rd!"))

    assert exc_info.value.status_code == 401
    record_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "sub": "019f76e9-c299-7756-a483-761aa106ba11",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "jti": "refresh-jti",
        "exp": 9999999999,
    }
    row = {
        "id": "019f76e9-c299-7756-a483-761aa106ba11",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "email": "user@example.com",
        "roles": ["editor"],
        "brand_ids": ["00000000-0000-0000-0000-000000000002"],
        "status": "active",
    }

    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeConn([row])

    monkeypatch.setattr(auth, "get_db", _fake_get_db)
    monkeypatch.setattr(auth, "decode_refresh_token", lambda _token: payload)
    monkeypatch.setattr(auth, "is_jti_revoked", AsyncMock(return_value=False))
    monkeypatch.setattr(auth, "revoke_jti", AsyncMock())
    monkeypatch.setattr(auth, "create_access_token", lambda **_kwargs: "new-access")
    monkeypatch.setattr(auth, "create_refresh_token", lambda **_kwargs: "new-refresh")

    result = await auth.refresh(auth.RefreshRequest(refresh_token="refresh-token-1234567890"))

    assert result.access_token == "new-access"
    assert result.refresh_token == "new-refresh"


@pytest.mark.asyncio
async def test_logout_revokes_access_and_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth,
        "decode_access_token",
        lambda _token: {"jti": "access-jti", "exp": 9999999999, "token_type": "access"},
    )
    monkeypatch.setattr(
        auth,
        "decode_refresh_token",
        lambda _token: {"jti": "refresh-jti", "exp": 9999999999, "token_type": "refresh"},
    )
    revoke_jti = AsyncMock()
    monkeypatch.setattr(auth, "revoke_jti", revoke_jti)

    user = UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="jwt",
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="access-token")

    result = await auth.logout(
        auth.LogoutRequest(refresh_token="refresh-token"),
        user=user,
        credentials=credentials,
    )

    assert result["status"] == "logged_out"
    assert revoke_jti.await_count == 2
