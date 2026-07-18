"""Intake Agent — first node in the OmniBrand pipeline.

Turns a raw campaign brief into a validated CampaignBrief and a fan-out
list[GenerationTask] for content_generator to execute against.
Pure validation + planning — no LLM call, token_cost_usd = 0.0.
"""
from __future__ import annotations

from itertools import product
import re

import structlog

from pipeline.agents.base import safe_agent_run
from pipeline.intake_validation import check_budget, screen_for_injection
from services.rag import get_retriever
from pipeline.state import CampaignBrief, GenerationTask, OmniBrandState

log = structlog.get_logger()


def _version_key(version: str) -> tuple[int, str]:
    match = re.search(r"(\d+)", version)
    if match:
        return (int(match.group(1)), version)
    return (0, version)


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
        injection_hits = screen_for_injection(texts_to_screen)
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
            budget_errors = check_budget(token_budget, channels, locales, audience_segments)
            if budget_errors:
                errors.extend(budget_errors)
            else:
                budget_ok = True

        # ------------------------------------------------------------------
        # 5. RAG context / prior campaigns
        # ------------------------------------------------------------------
        rag_context = None
        prior_campaigns: list = []
        if brief_valid and budget_ok and campaign_brief is not None:
            query = campaign_brief["objective"].strip() or campaign_brief["raw_text"].strip()
            if query:
                try:
                    chunks = await get_retriever().retrieve(
                        query=query,
                        brand_id=state["brand_id"],
                        locale=campaign_brief["locales"][0],
                        n_results=5,
                    )
                    if chunks:
                        versions = [c.version for c in chunks if c.version]
                        rag_context = {
                            "brand_guide_chunks": [c.content for c in chunks],
                            "section_types": [c.section_type for c in chunks if c.section_type],
                            "brand_guide_version": (
                                max(versions, key=_version_key) if versions else "unknown"
                            ),
                            "retrieval_scores": [float(c.score) for c in chunks],
                        }
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "intake_rag_context_failed",
                        campaign_id=state.get("campaign_id"),
                        brand_id=state.get("brand_id"),
                        error=str(exc),
                    )

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
