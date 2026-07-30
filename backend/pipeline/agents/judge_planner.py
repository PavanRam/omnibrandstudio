"""Intelligent judge gating — decides how much scrutiny a campaign needs.

The gate runs after translation and before the judge panel. It sets
``state["judge_mode"]`` to one of:

  • ``"full"`` — fan out to all three cross-family judges (default, highest
    assurance). Always used for a brand's first campaign and for any regulated /
    high-risk content, so the aggregator has a full disagreement signal.
  • ``"lite"`` — a single judge (``judge_claude``); the aggregator then runs in
    degraded mode and flags for human review — cheaper, for low-risk content
    that still warrants a look.
  • ``"skip"`` — bypass judging entirely and go straight to the human review
    gate. Only reachable via explicit org/brand configuration for trusted,
    low-stakes content — never auto-selected.

The decision is a cheap deterministic heuristic (no LLM call): explicit
config override → first-campaign guard → regulated-keyword / channel risk →
default ``full``. Calibration data can later tighten these bands without any
change to agent code.
"""
from __future__ import annotations

import structlog

from pipeline.agents.base import publish_campaign_event, safe_agent_run
from pipeline.state import OmniBrandState

log = structlog.get_logger()

_VALID_MODES = {"skip", "lite", "full"}

# Content touching these areas always gets the full panel — the cost of a
# brand-damaging or non-compliant claim dwarfs three judge calls.
_HIGH_RISK_KEYWORDS = frozenset(
    {
        "health",
        "medical",
        "medicine",
        "cure",
        "treatment",
        "clinical",
        "financial",
        "investment",
        "returns",
        "guarantee",
        "guaranteed",
        "legal",
        "compliance",
        "regulated",
        "insurance",
        "loan",
        "credit",
        "tax",
        "pharma",
        "supplement",
    }
)


def _resolve_override(state: OmniBrandState) -> str | None:
    for cfg_key in ("brand_config", "org_config"):
        mode = (state.get(cfg_key) or {}).get("judge_mode")
        if isinstance(mode, str) and mode in _VALID_MODES:
            return mode
    return None


def _is_first_campaign(state: OmniBrandState) -> bool:
    return not (state.get("prior_campaigns") or [])


def _brief_is_high_risk(state: OmniBrandState) -> bool:
    brief = state.get("brief") or {}
    haystack_parts: list[str] = [brief.get("raw_text", "") or ""]
    haystack_parts.extend(brief.get("key_messages", []) or [])
    haystack = " ".join(haystack_parts).lower()
    return any(keyword in haystack for keyword in _HIGH_RISK_KEYWORDS)


def _resolve_mode(state: OmniBrandState) -> tuple[str, str]:
    """Return ``(judge_mode, reason)``."""
    # First campaign for a brand: no calibration history yet — always full.
    if _is_first_campaign(state):
        return "full", "first campaign for brand"

    if _brief_is_high_risk(state):
        return "full", "regulated / high-risk content"

    override = _resolve_override(state)
    if override is not None:
        return override, f"config override ({override})"

    # Established brand, low-risk brief, no override → single-judge lite pass.
    return "lite", "established brand, low-risk brief"


async def judge_gate(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        mode, reason = _resolve_mode(state)
        log.info(
            "judge_gate",
            campaign_id=state.get("campaign_id"),
            judge_mode=mode,
            reason=reason,
        )
        await publish_campaign_event(
            campaign_id=state.get("campaign_id"),
            agent="judge_gate",
            phase="judge_gate_complete",
            payload={"judge_mode": mode, "reason": reason},
        )
        return {"judge_mode": mode, "current_phase": "judge_gate_complete"}

    return await safe_agent_run(_impl, state)


def judge_gate_router(state: OmniBrandState) -> list[str] | str:
    """Conditional-edge selector after the judge gate.

    ``full`` fans out to all three judges, ``lite`` runs a single judge, and
    ``skip`` bypasses judging entirely for the human review gate.
    """
    mode = state.get("judge_mode", "full")
    if mode == "skip":
        return "review_gate"
    if mode == "lite":
        return ["judge_1"]
    return ["judge_1", "judge_2", "judge_3"]
