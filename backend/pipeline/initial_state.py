from __future__ import annotations

from datetime import UTC, datetime

from core.config import settings

from pipeline.schemas import CreateCampaignRequest
from pipeline.state import CampaignBrief, OmniBrandState


# Maps each resolve_model_aliases() key to the Settings field that can
# override it independent of LLM_COST_TIER (empty string = no override).
_OVERRIDE_SETTINGS: dict[str, str] = {
    "generation": "GENERATION_MODEL_ALIAS",
    "personalization": "PERSONALIZATION_MODEL_ALIAS",
    "translation": "TRANSLATION_MODEL_ALIAS",
    "translation_validator": "TRANSLATION_VALIDATOR_MODEL_ALIAS",
    "brand_truthfulness": "BRAND_TRUTHFULNESS_MODEL_ALIAS",
    "judge-1": "JUDGE_1_MODEL_ALIAS",
    "judge-2": "JUDGE_2_MODEL_ALIAS",
    "judge-3": "JUDGE_3_MODEL_ALIAS",
    "util-fast": "UTIL_FAST_MODEL_ALIAS",
    "eval": "EVAL_MODEL_ALIAS",
}


def resolve_model_aliases(tier: str | None = None) -> dict[str, str]:
    """Map logical model roles to LiteLLM aliases for the selected cost tier.

    ``free`` (default) uses the Groq cross-family panel and free-tier generation
    so campaigns validate without paid spend; ``paid`` uses the pinned
    Claude/GPT-4o/Groq panel and premium generation. Switching tiers is a config
    flip (``LLM_COST_TIER``) — no agent code reads raw model names. Any
    ``*_MODEL_ALIAS`` setting in ``_OVERRIDE_SETTINGS`` pins that one role
    regardless of tier.
    """
    resolved = (tier or settings.LLM_COST_TIER or "free").lower()
    if resolved == "paid":
        # Paid aliases unchanged. brand_truthfulness / translation /
        # translation_validator are made explicit here (agents previously fell
        # back to these same defaults) so both tiers stay symmetric.
        aliases = {
            "generation": "gen-premium",
            "personalization": "gen-premium",
            "judge-1": "judge-1",
            "judge-2": "judge-2",
            "judge-3": "judge-3",
            "util-fast": "util-fast",
            "eval": "eval-model",
            "brand_truthfulness": "eval-model",
            "translation": "translation-primary",
            "translation_validator": "translation-validator",
        }
    else:
        # Free tier — every role routes to a Groq (*-free) alias for $0 spend.
        aliases = {
            "generation": "gen-free",
            "personalization": "gen-free",
            "judge-1": "judge-1-free",
            "judge-2": "judge-2-free",
            "judge-3": "judge-3-free",
            "util-fast": "util-fast-free",
            "eval": "eval-model-free",
            "brand_truthfulness": "eval-model-free",
            "translation": "translation-primary-free",
            "translation_validator": "translation-validator-free",
        }
    for key, setting_name in _OVERRIDE_SETTINGS.items():
        override = getattr(settings, setting_name, "")
        if override:
            aliases[key] = override
    return aliases


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
            end_date=brief.end_date,
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
        user_edit_note=None,
        variants=[],
        brand_scores=[],
        aggregated_scores=[],
        review_requests=[],
        publication_receipts=[],
        failed_task_ids=[],
        errors=[],
        current_phase="starting",
        human_review_requested=False,
        publishing_paused=False,
        judge_mode="full",
        review_round=0,
        review_decisions={},
        token_cost_usd=0.0,
    )
