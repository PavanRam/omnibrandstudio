from __future__ import annotations

from datetime import UTC, datetime

from core.config import settings

from pipeline.schemas import CreateCampaignRequest
from pipeline.state import CampaignBrief, OmniBrandState


def resolve_model_aliases(tier: str | None = None) -> dict[str, str]:
    """Map logical model roles to LiteLLM aliases for the selected judge tier.

    ``free`` (default) uses the Groq cross-family panel and free-tier generation
    so campaigns validate without paid spend; ``paid`` uses the pinned
    Claude/GPT-4o/Groq panel and premium generation. Switching tiers is a config
    flip (``JUDGE_TIER``) — no agent code reads raw model names.
    """
    resolved = (tier or settings.JUDGE_TIER or "free").lower()
    if resolved == "paid":
        return {
            "generation": "gen-premium",
            "judge-1": "judge-1",
            "judge-2": "judge-2",
            "judge-3": "judge-3",
            "util-fast": "util-fast",
            "eval": "eval-model",
        }
    return {
        "generation": "gen-free",
        "judge-1": "judge-1-free",
        "judge-2": "judge-2-free",
        "judge-3": "judge-3-free",
        "util-fast": "util-fast",
        "eval": "eval-model",
    }


def build_initial_state(
    *,
    campaign_id: str,
    org_id: str,
    brand_id: str,
    user_id: str,
    request_id: str,
    brief: CreateCampaignRequest | None = None,
) -> OmniBrandState:
    campaign_brief: CampaignBrief | None = None
    if brief is not None:
        campaign_brief = CampaignBrief(
            objective=brief.objective,
            target_audience=brief.target_audience,
            key_messages=brief.key_messages,
            tone_override=brief.tone_override,
            channels=brief.channels,
            locales=brief.locales,
            audience_segments=brief.audience_segments,
            token_budget=brief.token_budget,
            raw_text=brief.raw_text,
        )

    return OmniBrandState(
        campaign_id=campaign_id,
        org_id=org_id,
        brand_id=brand_id,
        user_id=user_id,
        request_id=request_id,
        started_at=datetime.now(UTC).isoformat(),
        org_config={},
        brand_config={},
        model_aliases=resolve_model_aliases(),
        brief=campaign_brief,
        rag_context=None,
        prior_campaigns=[],
        brief_valid=None,
        brief_validation_errors=[],
        budget_check_passed=None,
        tasks=[],
        current_task=None,
        variants=[],
        brand_scores=[],
        aggregated_scores=[],
        review_requests=[],
        publication_receipts=[],
        failed_task_ids=[],
        errors=[],
        guardrail_flags=[],
        current_phase="starting",
        human_review_requested=False,
        publishing_paused=False,
        judge_mode="full",
        review_round=0,
        review_decisions={},
        token_cost_usd=0.0,
    )
