"""Airtable review sync: config-gated + best-effort (non-fatal)."""

import json

from core.config import settings
from services import airtable_service


def _enable(monkeypatch):
    monkeypatch.setattr(settings, "AIRTABLE_API_KEY", "key123")
    monkeypatch.setattr(settings, "AIRTABLE_BASE_ID", "base123")
    monkeypatch.setattr(settings, "AIRTABLE_TABLE", "Reviews")


def _fields() -> dict:
    return {
        "review_request_id": "r1", "campaign_id": "c1", "variant_id": "t1",
        "Decision": "Pending", "Sync Status": "Not Synced", "routing_reason": "flagged",
    }


def test_disabled_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "AIRTABLE_API_KEY", "")
    assert airtable_service.airtable_enabled() is False


def test_enabled_when_all_configured(monkeypatch):
    _enable(monkeypatch)
    assert airtable_service.airtable_enabled() is True


async def test_sync_review_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AIRTABLE_API_KEY", "")
    # Must not raise and must not attempt any HTTP (no httpx_mock registered).
    assert await airtable_service.sync_review(_fields()) is False


async def test_sync_review_upserts_with_auth_when_enabled(monkeypatch, httpx_mock):
    _enable(monkeypatch)
    httpx_mock.add_response(status_code=200, json={"records": [{"id": "rec1"}]})
    assert await airtable_service.sync_review(_fields()) is True
    req = httpx_mock.get_request()
    assert req is not None
    assert req.method == "PATCH"
    assert "base123" in str(req.url) and "Reviews" in str(req.url)
    assert req.headers["Authorization"] == "Bearer key123"
    payload = json.loads(req.content)
    assert payload["performUpsert"] == {"fieldsToMergeOn": ["review_request_id"]}
    assert payload["records"] == [{"fields": _fields()}]


async def test_sync_review_swallows_http_errors(monkeypatch, httpx_mock):
    _enable(monkeypatch)
    httpx_mock.add_response(status_code=500)
    # best-effort: a mirror failure returns False, never raises
    assert await airtable_service.sync_review(_fields()) is False


async def test_mark_synced_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AIRTABLE_API_KEY", "")
    assert await airtable_service.mark_synced("rec1", status="Synced") is False


async def test_mark_synced_patches_specific_record(monkeypatch, httpx_mock):
    _enable(monkeypatch)
    httpx_mock.add_response(status_code=200, json={"id": "rec1"})
    assert await airtable_service.mark_synced("rec1", status="Error", error="boom") is True
    req = httpx_mock.get_request()
    assert req is not None
    assert req.method == "PATCH"
    assert str(req.url).endswith("/base123/Reviews/rec1")
    payload = json.loads(req.content)
    assert payload == {"fields": {"Sync Status": "Error", "Sync Error": "boom"}}


async def test_mark_synced_swallows_http_errors(monkeypatch, httpx_mock):
    _enable(monkeypatch)
    httpx_mock.add_response(status_code=500)
    assert await airtable_service.mark_synced("rec1", status="Synced") is False
