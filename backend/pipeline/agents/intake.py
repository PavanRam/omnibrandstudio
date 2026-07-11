"""Intake Agent — first node in the OmniBrand pipeline.

Turns a raw campaign brief into a validated CampaignBrief and a fan-out
list[GenerationTask] for content_generator to execute against.
Pure validation + planning — no LLM call, token_cost_usd = 0.0.
"""
from __future__ import annotations

import re
from itertools import product

import structlog

from pipeline.agents.base import safe_agent_run
from pipeline.state import CampaignBrief, GenerationTask, OmniBrandState

log = structlog.get_logger()

# Rough token estimate per generation task — used for budget pre-check.
# No LLM call is made here; this is a conservative planning heuristic.
ROUGH_TOKENS_PER_TASK = 500

# ---------------------------------------------------------------------------
# Injection-screening patterns (fail-closed, step 1)
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous\s+)?instructions?", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+are|a\s+)", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"override\s+(system|previous)\s+(prompt|instructions?)", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?(system\s+prompt|instructions?)", re.IGNORECASE),
    re.compile(r"print\s+(the\s+)?(system\s+prompt|instructions?)", re.IGNORECASE),
    re.compile(r"repeat\s+(the\s+)?(above|system|prompt)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
]


def _screen_for_injection(texts: list[str]) -> list[str]:
    """Return a list of violation descriptions if any injection pattern is found.
    Checks are applied across all provided text fields combined."""
    violations: list[str] = []
    for text in texts:
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                violations.append(
                    f"Potential instruction-injection detected "
                    f"(pattern: {pattern.pattern!r})"
                )
                # One hit per pattern is enough — don't spam errors
                break
    return violations


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------


async def intake_agent(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        errors: list[str] = []
        brief_valid = True

        raw_brief: dict = state.get("brief") or {}  # type: ignore[assignment]

        # ------------------------------------------------------------------
        # 1. Injection screening (fail-closed)
        # ------------------------------------------------------------------
        raw_text: str = raw_brief.get("raw_text", "") or ""
        key_messages: list[str] = raw_brief.get("key_messages", []) or []
        texts_to_screen = [raw_text] + key_messages
        injection_hits = _screen_for_injection(texts_to_screen)
        if injection_hits:
            brief_valid = False
            errors.extend(injection_hits)
            log.warning(
                "intake_injection_detected",
                campaign_id=state.get("campaign_id"),
                hits=injection_hits,
            )

        # ------------------------------------------------------------------
        # 2. Field validation
        # ------------------------------------------------------------------
        channels: list[str] = raw_brief.get("channels", []) or []
        locales: list[str] = raw_brief.get("locales", []) or []
        audience_segments: list[str] = raw_brief.get("audience_segments", []) or []
        token_budget: int = raw_brief.get("token_budget", 0) or 0

        if not channels:
            brief_valid = False
            errors.append("brief.channels must be non-empty")
        if not locales:
            brief_valid = False
            errors.append("brief.locales must be non-empty")
        if not audience_segments:
            brief_valid = False
            errors.append("brief.audience_segments must be non-empty")
        if token_budget <= 0:
            brief_valid = False
            errors.append("brief.token_budget must be > 0")

        # ------------------------------------------------------------------
        # 3. Build CampaignBrief
        # ------------------------------------------------------------------
        campaign_brief: CampaignBrief | None = None
        if brief_valid:
            campaign_brief = CampaignBrief(
                objective=raw_brief.get("objective", ""),
                target_audience=raw_brief.get("target_audience", ""),
                key_messages=key_messages,
                tone_override=raw_brief.get("tone_override"),
                channels=channels,
                locales=locales,
                audience_segments=audience_segments,
                token_budget=token_budget,
                raw_text=raw_text,
            )

        # ------------------------------------------------------------------
        # 4. Budget check (deterministic, no LLM)
        # ------------------------------------------------------------------
        budget_ok = False
        if brief_valid and campaign_brief is not None:
            estimated_task_count = len(channels) * len(locales) * len(audience_segments)
            estimated_tokens = estimated_task_count * ROUGH_TOKENS_PER_TASK
            if estimated_tokens > token_budget:
                budget_ok = False
                errors.append(
                    f"token_budget {token_budget} is insufficient for "
                    f"{estimated_task_count} tasks × {ROUGH_TOKENS_PER_TASK} tokens "
                    f"(estimated {estimated_tokens} needed)"
                )
            else:
                budget_ok = True

        # ------------------------------------------------------------------
        # 5. RAG context / prior campaigns — explicit no-ops on this branch
        # ------------------------------------------------------------------
        rag_context = None
        prior_campaigns: list = []

        # ------------------------------------------------------------------
        # 6. Task fan-out (Cartesian product) — only if valid
        # ------------------------------------------------------------------
        tasks: list[GenerationTask] = []
        if brief_valid and budget_ok and campaign_brief is not None:
            for locale, channel, segment in product(
                campaign_brief["locales"],
                campaign_brief["channels"],
                campaign_brief["audience_segments"],
            ):
                tasks.append(
                    GenerationTask(
                        task_id=f"{locale}_{channel}_{segment}",
                        locale=locale,
                        channel=channel,
                        segment=segment,
                        channel_constraints={},  # no channel-rules source on this branch
                    )
                )

        log.info(
            "intake_complete",
            campaign_id=state.get("campaign_id"),
            brief_valid=brief_valid,
            budget_ok=budget_ok,
            task_count=len(tasks),
            errors=errors,
        )

        # ------------------------------------------------------------------
        # 7 & 8. Phase marker + cost
        # ------------------------------------------------------------------
        return {
            "brief": campaign_brief,
            "brief_valid": brief_valid,
            "brief_validation_errors": errors,
            "budget_check_passed": budget_ok,
            "rag_context": rag_context,
            "prior_campaigns": prior_campaigns,
            "tasks": tasks if (brief_valid and budget_ok) else [],
            "current_phase": "intake_complete",
            "token_cost_usd": 0.0,
        }

    return await safe_agent_run(_impl, state)
