"""intake_agent brand-entitlement + truthfulness checks (next_tasks.md
items 14/22/42, 2026-07-27).

brands.config is an empty JSONB blob until a brand is configured via the
admin panel — these tests cover both the "brand has a profile configured"
path (entitlement enforced, truthfulness checked) and confirm an
unconfigured brand (empty config, or a DB lookup failure) is completely
unaffected — fails open, never blocks a legitimate campaign.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from pipeline.agents import intake as intake_module
from pipeline.agents.intake import intake_agent


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


def _mock_brand_config(monkeypatch: pytest.MonkeyPatch, config: dict | None) -> None:
    @asynccontextmanager
    async def _fake_get_db():
        class _FakeConn:
            async def execute(self, *_args, **_kwargs):
                return _FakeResult({"config": config} if config is not None else None)

        yield _FakeConn()

    monkeypatch.setattr(intake_module, "get_db", _fake_get_db)


def _state(**brief_overrides) -> dict:
    brief = {
        "objective": "drive new plan signups",
        "target_audience": "young professionals",
        "key_messages": ["unlimited 5G data"],
        "tone_override": None,
        "channels": ["email"],
        "locales": ["en-US"],
        "audience_segments": ["consumer"],
        "token_budget": 100_000,
        "raw_text": "",
    }
    brief.update(brief_overrides)
    return {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "brand_id": "brand-1",
        "brief": brief,
        "model_aliases": {},
    }


@pytest.mark.asyncio
async def test_unconfigured_brand_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty brands.config (the default for every brand today) must change
    nothing — no channel restriction, no truthfulness check at all."""
    _mock_brand_config(monkeypatch, {})

    result = await intake_agent(_state(channels=["email", "rcs"]))

    # rcs isn't in DEFAULT_CHANNEL_CONSTRAINTS at all, so it's still rejected
    # by the global channel-template check — but NOT because of brand
    # entitlement, which is what this test is actually isolating.
    assert result["brief_valid"] is False
    assert any("channel(s) not supported for this brand" in e for e in result["brief_validation_errors"])


@pytest.mark.asyncio
async def test_brand_config_missing_row_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brand row not found (or config column NULL) — same fail-open
    behavior as an empty config, never a hard error."""
    _mock_brand_config(monkeypatch, None)

    result = await intake_agent(_state())

    assert result["brief_valid"] is True
    assert result["brief_validation_errors"] == []


@pytest.mark.asyncio
async def test_channel_not_in_brand_allow_list_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_brand_config(monkeypatch, {"channels": ["email", "sms"]})

    result = await intake_agent(_state(channels=["email", "linkedin"]))

    assert result["brief_valid"] is False
    assert any("linkedin" in e and "not supported for this brand" in e for e in result["brief_validation_errors"])


@pytest.mark.asyncio
async def test_channel_in_brand_allow_list_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_brand_config(monkeypatch, {"channels": ["email", "sms"]})

    result = await intake_agent(_state(channels=["email"]))

    assert result["brief_valid"] is True


@pytest.mark.asyncio
async def test_locale_not_entitled_for_brand_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_brand_config(monkeypatch, {"locales": ["fr"]})

    result = await intake_agent(_state(locales=["en-US", "de"]))

    assert result["brief_valid"] is False
    assert any("de" in e and "not entitled for this brand" in e for e in result["brief_validation_errors"])


@pytest.mark.asyncio
async def test_source_locale_always_entitled_even_with_restricted_allow_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The source locale (en-US) must never be blockable by brand config —
    it's not a translation target, it's the master content language."""
    _mock_brand_config(monkeypatch, {"locales": ["fr"]})

    result = await intake_agent(_state(locales=["en-US"]))

    assert result["brief_valid"] is True


@pytest.mark.asyncio
async def test_truthfulness_check_skipped_when_brand_has_no_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_brand_config(monkeypatch, {"channels": ["email"]})  # no industry/key_claims
    llm_mock = AsyncMock()
    monkeypatch.setattr(intake_module, "traced_llm_call", llm_mock)

    result = await intake_agent(_state())

    assert result["brief_valid"] is True
    llm_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_truthfulness_check_rejects_implausible_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_brand_config(
        monkeypatch,
        {"industry": "artisanal bakery", "key_claims": ["fresh sourdough", "local delivery"]},
    )
    llm_mock = AsyncMock(
        return_value=(
            '{"plausible": false, "reason": "brief is about 5G phone plans, not baked goods"}',
            {"cost": 0.001},
        )
    )
    monkeypatch.setattr(intake_module, "traced_llm_call", llm_mock)

    result = await intake_agent(_state())

    assert result["brief_valid"] is False
    assert any("doesn't match this brand's profile" in e for e in result["brief_validation_errors"])
    assert result["token_cost_usd"] == 0.001
    llm_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_truthfulness_check_accepts_plausible_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_brand_config(
        monkeypatch,
        {"industry": "telecom", "key_claims": ["unlimited 5G data plans"]},
    )
    llm_mock = AsyncMock(return_value=('{"plausible": true, "reason": ""}', {"cost": 0.001}))
    monkeypatch.setattr(intake_module, "traced_llm_call", llm_mock)

    result = await intake_agent(_state())

    assert result["brief_valid"] is True


@pytest.mark.asyncio
async def test_truthfulness_check_fails_open_on_malformed_llm_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flaky/malformed judge response must never block an otherwise-valid
    campaign — only a confidently-parsed 'implausible' verdict should."""
    _mock_brand_config(monkeypatch, {"industry": "telecom", "key_claims": ["5G"]})
    llm_mock = AsyncMock(return_value=("not json at all", {"cost": 0.001}))
    monkeypatch.setattr(intake_module, "traced_llm_call", llm_mock)

    result = await intake_agent(_state())

    assert result["brief_valid"] is True
    assert result["token_cost_usd"] == 0.001


@pytest.mark.asyncio
async def test_brand_profile_load_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DB error loading brands.config must never block generation — same
    fail-open treatment as the RAG retrieval lookup elsewhere in this file."""

    @asynccontextmanager
    async def _broken_get_db():
        raise RuntimeError("Database engine not initialized")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr(intake_module, "get_db", _broken_get_db)

    result = await intake_agent(_state())

    assert result["brief_valid"] is True
