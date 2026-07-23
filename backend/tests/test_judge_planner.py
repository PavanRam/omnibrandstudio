"""Unit tests for intelligent judge gating (pipeline/agents/judge_planner.py)."""
from __future__ import annotations

import pytest
from pipeline.agents.judge_planner import judge_gate, judge_gate_router


def _state(**overrides) -> dict:
    base = {
        "campaign_id": "camp-1",
        "prior_campaigns": [{"campaign_id": "old-1"}],  # established brand
        "brief": {"raw_text": "Fun summer sale on shoes.", "key_messages": ["50% off"]},
        "org_config": {},
        "brand_config": {},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_first_campaign_forces_full():
    result = await judge_gate(_state(prior_campaigns=[]))
    assert result == {"judge_mode": "full"}


@pytest.mark.asyncio
async def test_high_risk_content_forces_full():
    state = _state(
        brief={"raw_text": "Our supplement is a guaranteed medical cure.", "key_messages": []}
    )
    result = await judge_gate(state)
    assert result["judge_mode"] == "full"


@pytest.mark.asyncio
async def test_established_low_risk_defaults_to_lite():
    result = await judge_gate(_state())
    assert result["judge_mode"] == "lite"


@pytest.mark.asyncio
async def test_config_override_respected_for_low_risk():
    result = await judge_gate(_state(brand_config={"judge_mode": "skip"}))
    assert result["judge_mode"] == "skip"


@pytest.mark.asyncio
async def test_first_campaign_overrides_config_skip():
    # First-campaign guard takes precedence over an explicit skip override.
    state = _state(prior_campaigns=[], brand_config={"judge_mode": "skip"})
    result = await judge_gate(state)
    assert result["judge_mode"] == "full"


def test_router_full_fans_out_all_three():
    assert judge_gate_router({"judge_mode": "full"}) == [
        "judge_claude",
        "judge_gpt4o",
        "judge_llama",
    ]


def test_router_lite_single_judge():
    assert judge_gate_router({"judge_mode": "lite"}) == ["judge_claude"]


def test_router_skip_bypasses_to_review_gate():
    assert judge_gate_router({"judge_mode": "skip"}) == "review_gate"


def test_router_defaults_to_full_when_unset():
    assert judge_gate_router({}) == ["judge_claude", "judge_gpt4o", "judge_llama"]
