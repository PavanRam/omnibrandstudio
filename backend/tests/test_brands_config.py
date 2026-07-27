"""Admin brand-profile config endpoints (next_tasks.md items 14/22/42,
2026-07-27) — GET/PATCH /brands/{id}/config. This is the actual UI-facing
surface for what pipeline/agents/intake.py's brand-entitlement/truthfulness
checks read from brands.config; admin-only, since it's org/brand
configuration, not something a regular campaign creator edits.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import json

import pytest
from fastapi import HTTPException

from api.deps import UserContext
from api.routers import brands


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeConn:
    def __init__(self, brand_row):
        self._brand_row = brand_row
        self.executed: list[tuple] = []

    async def execute(self, query, params):
        self.executed.append((str(query), params))
        return _FakeResult(self._brand_row)


def _mock_get_db(monkeypatch: pytest.MonkeyPatch, brand_row: dict | None):
    fake_conn = _FakeConn(brand_row)

    @asynccontextmanager
    async def _fake_get_db():
        yield fake_conn

    monkeypatch.setattr(brands, "get_db", _fake_get_db)
    return fake_conn


def _admin_user(org_id: str = "org-1") -> UserContext:
    return UserContext(user_id="u1", org_id=org_id, brand_ids=[], roles=["admin"])


def _non_admin_user() -> UserContext:
    return UserContext(user_id="u2", org_id="org-1", brand_ids=[], roles=["editor"])


BRAND_ID = "00000000-0000-0000-0000-000000000002"


@pytest.mark.asyncio
async def test_get_config_rejects_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, {"id": BRAND_ID, "name": "Demo", "config": {}})

    with pytest.raises(HTTPException) as exc:
        await brands.get_brand_config(BRAND_ID, _non_admin_user())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_config_404_when_brand_not_in_org(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, None)

    with pytest.raises(HTTPException) as exc:
        await brands.get_brand_config(BRAND_ID, _admin_user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_config_returns_defaults_for_unconfigured_brand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_get_db(monkeypatch, {"id": BRAND_ID, "name": "Demo Brand", "config": {}})

    result = await brands.get_brand_config(BRAND_ID, _admin_user())

    assert result["industry"] == ""
    assert result["key_claims"] == []
    assert result["channels"] is None
    assert result["locales"] is None
    assert "email" in result["available_channels"]
    assert "rcs" not in result["available_channels"]
    assert "fr" in result["available_locales"]


@pytest.mark.asyncio
async def test_get_config_returns_existing_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = {
        "industry": "telecom",
        "key_claims": ["unlimited 5G"],
        "channels": ["email", "sms"],
        "locales": ["fr"],
    }
    _mock_get_db(monkeypatch, {"id": BRAND_ID, "name": "Demo Brand", "config": existing})

    result = await brands.get_brand_config(BRAND_ID, _admin_user())

    assert result["industry"] == "telecom"
    assert result["channels"] == ["email", "sms"]
    assert result["locales"] == ["fr"]


@pytest.mark.asyncio
async def test_update_config_rejects_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, {"id": BRAND_ID, "name": "Demo", "config": {}})
    body = brands.BrandConfigRequest(name="Demo", industry="telecom")

    with pytest.raises(HTTPException) as exc:
        await brands.update_brand_config(BRAND_ID, body, _non_admin_user())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_config_rejects_unsupported_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, {"id": BRAND_ID, "name": "Demo", "config": {}})
    body = brands.BrandConfigRequest(name="Demo", channels=["email", "google-ads"])

    with pytest.raises(HTTPException) as exc:
        await brands.update_brand_config(BRAND_ID, body, _admin_user())
    assert exc.value.status_code == 422
    assert "google-ads" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_update_config_rejects_unsupported_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, {"id": BRAND_ID, "name": "Demo", "config": {}})
    body = brands.BrandConfigRequest(name="Demo", locales=["fr", "ja"])

    with pytest.raises(HTTPException) as exc:
        await brands.update_brand_config(BRAND_ID, body, _admin_user())
    assert exc.value.status_code == 422
    assert "ja" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_update_config_persists_and_returns_new_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = _mock_get_db(monkeypatch, {"id": BRAND_ID, "name": "Demo", "config": {}})
    body = brands.BrandConfigRequest(
        name="Renamed Brand",
        industry="telecom",
        key_claims=["unlimited 5G data", "  ", "no contract"],
        channels=["email", "sms"],
        locales=["fr", "de"],
    )

    result = await brands.update_brand_config(BRAND_ID, body, _admin_user())

    assert result["name"] == "Renamed Brand"
    assert result["industry"] == "telecom"
    assert result["key_claims"] == ["unlimited 5G data", "no contract"]
    assert result["channels"] == ["email", "sms"]
    assert result["locales"] == ["fr", "de"]

    update_call = next(q for q, _ in fake_conn.executed if "UPDATE brands" in q)
    assert update_call
    params = next(p for q, p in fake_conn.executed if "UPDATE brands" in q)
    persisted = json.loads(params["config"])
    assert persisted["industry"] == "telecom"
    assert persisted["channels"] == ["email", "sms"]
    assert params["name"] == "Renamed Brand"


@pytest.mark.asyncio
async def test_update_config_404_when_brand_not_in_org(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db(monkeypatch, None)
    body = brands.BrandConfigRequest(name="Demo", industry="telecom")

    with pytest.raises(HTTPException) as exc:
        await brands.update_brand_config(BRAND_ID, body, _admin_user())
    assert exc.value.status_code == 404


class _FakeRowsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


def _mock_get_db_rows(monkeypatch: pytest.MonkeyPatch, rows: list[dict]):
    class _FakeConnRows:
        def __init__(self):
            self.executed: list[tuple] = []

        async def execute(self, query, params):
            self.executed.append((str(query), params))
            return _FakeRowsResult(rows)

    fake_conn = _FakeConnRows()

    @asynccontextmanager
    async def _fake_get_db():
        yield fake_conn

    monkeypatch.setattr(brands, "get_db", _fake_get_db)
    return fake_conn


@pytest.mark.asyncio
async def test_list_brands_scoped_to_users_explicit_brand_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """A multi-brand user (explicit brand_ids) must only ever see those
    brands — this is the exact list the 'pick a brand before starting a
    conversation' picker renders from."""
    _mock_get_db_rows(
        monkeypatch, [{"id": BRAND_ID, "name": "Demo Brand", "source_locale": "en-US"}]
    )
    user = UserContext(user_id="u1", org_id="org-1", brand_ids=[BRAND_ID], roles=["editor"])

    result = await brands.list_brands(user)

    assert len(result["brands"]) == 1
    assert result["brands"][0]["name"] == "Demo Brand"


@pytest.mark.asyncio
async def test_list_brands_org_wide_when_no_explicit_brand_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No explicit brand_ids (org-wide admin) sees every brand in the org —
    same convention _assert_brand_access already uses elsewhere."""
    fake_conn = _mock_get_db_rows(
        monkeypatch,
        [
            {"id": "b1", "name": "Brand One", "source_locale": "en-US"},
            {"id": "b2", "name": "Brand Two", "source_locale": "en-US"},
        ],
    )
    user = _admin_user()

    result = await brands.list_brands(user)

    assert len(result["brands"]) == 2
    query, params = fake_conn.executed[0]
    assert "org_id" in params


@pytest.mark.asyncio
async def test_create_brand_rejects_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get_db_rows(monkeypatch, [])
    body = brands.CreateBrandRequest(name="New Brand")

    with pytest.raises(HTTPException) as exc:
        await brands.create_brand(body, _non_admin_user())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_brand_persists_and_returns_new_brand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = _mock_get_db_rows(
        monkeypatch, [{"id": "new-brand-id", "name": "New Brand", "source_locale": "en-US"}]
    )
    body = brands.CreateBrandRequest(name="New Brand")

    result = await brands.create_brand(body, _admin_user())

    assert result["name"] == "New Brand"
    query, params = fake_conn.executed[0]
    assert "INSERT INTO brands" in query
    assert params["name"] == "New Brand"
