"""T11 — Airtable outbound mirror: config-gated + best-effort (non-fatal)."""

from core.config import settings
from services import airtable_service


def _enable(monkeypatch):
    monkeypatch.setattr(settings, "AIRTABLE_API_KEY", "key123")
    monkeypatch.setattr(settings, "AIRTABLE_BASE_ID", "base123")
    monkeypatch.setattr(settings, "AIRTABLE_TABLE", "Reviews")


def _review() -> dict:
    return {
        "review_request_id": "r1", "campaign_id": "c1", "variant_id": "t1",
        "status": "pending", "routing_reason": "flagged",
    }


def test_disabled_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "AIRTABLE_API_KEY", "")
    assert airtable_service.airtable_enabled() is False


def test_enabled_when_all_configured(monkeypatch):
    _enable(monkeypatch)
    assert airtable_service.airtable_enabled() is True


async def test_upsert_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AIRTABLE_API_KEY", "")
    # Must not raise and must not attempt any HTTP (no httpx_mock registered).
    assert await airtable_service.upsert_review(_review()) is False


async def test_upsert_posts_with_auth_when_enabled(monkeypatch, httpx_mock):
    _enable(monkeypatch)
    httpx_mock.add_response(status_code=200, json={"id": "rec1"})
    assert await airtable_service.upsert_review(_review()) is True
    req = httpx_mock.get_request()
    assert req is not None
    assert "base123" in str(req.url) and "Reviews" in str(req.url)
    assert req.headers["Authorization"] == "Bearer key123"


async def test_upsert_swallows_http_errors(monkeypatch, httpx_mock):
    _enable(monkeypatch)
    httpx_mock.add_response(status_code=500)
    # best-effort: a mirror failure returns False, never raises
    assert await airtable_service.upsert_review(_review()) is False


async def test_patch_decision_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AIRTABLE_API_KEY", "")
    assert await airtable_service.patch_decision("r1", "approved", "approved") is False
