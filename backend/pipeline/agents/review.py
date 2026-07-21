"""T11 — real ``review_gate`` node + post-gate router.

The graph pauses (``interrupt_before=["review_gate"]``) until a reviewer decision
is injected into state via ``graph.aupdate_state``. On resume this node runs and
*applies* those decisions to the variants, then the router decides whether to
publish or loop back to regenerate rejected variants (capped by
``MAX_REVIEW_ROUNDS``).

Decisions arrive in the non-reducer ``review_decisions`` channel, keyed by the
variant ``task_id``::

    {"en-US_email_core": {"decision": "approved"|"rejected"|"edited",
                          "edited_content": "...", "reviewer_note": "..."}}
"""
from __future__ import annotations

import structlog
from core.config import settings

from pipeline.agents.base import safe_agent_run
from pipeline.state import OmniBrandState

log = structlog.get_logger()


def _variant_content(variant: dict) -> str | None:
    return (
        variant.get("translated_content")
        or variant.get("personalized_content")
        or variant.get("generated_content")
    )


async def review_gate(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        decisions: dict = state.get("review_decisions") or {}
        review_round = int(state.get("review_round", 0) or 0)
        any_rejected = False

        for variant in state.get("variants", []):
            content = _variant_content(variant)
            decision = decisions.get(variant["task_id"])

            if decision is None:
                # Not flagged for review (or no decision yet): pass through unchanged,
                # ensuring publishing has final_content to work with.
                if content and not variant.get("final_content"):
                    variant["final_content"] = content
                continue

            verdict = str(decision.get("decision", "approved"))
            if verdict == "edited":
                variant["final_content"] = decision.get("edited_content") or content
                variant["status"] = "edited"
            elif verdict == "rejected":
                variant["status"] = "rejected"
                variant["retry_count"] = int(variant.get("retry_count", 0) or 0) + 1
                any_rejected = True
            else:  # approved
                variant["final_content"] = content
                variant["status"] = "approved"

        if any_rejected:
            review_round += 1

        log.info(
            "agent_complete",
            agent="review_gate",
            campaign_id=state.get("campaign_id"),
            decided=len(decisions),
            any_rejected=any_rejected,
            review_round=review_round,
        )
        return {"current_phase": "review_complete", "review_round": review_round}

    return await safe_agent_run(_impl, state)


def review_router(state: OmniBrandState) -> str:
    """Conditional edge after review_gate: regenerate rejected variants (under the
    rerun cap) or proceed to publishing."""
    review_round = int(state.get("review_round", 0) or 0)
    any_rejected = any(v.get("status") == "rejected" for v in state.get("variants", []))
    if any_rejected and review_round <= settings.MAX_REVIEW_ROUNDS:
        return "content_generator"
    return "publishing_agent"
