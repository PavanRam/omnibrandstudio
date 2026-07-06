from __future__ import annotations

from pydantic import ValidationError

from src.agents.state import WorkflowState
from src.schemas.campaign_brief import CampaignBrief, VALID_CHANNELS, VALID_LANGUAGES

_MIN_BRIEF_WORDS = 10
_MAX_BRIEF_CHARS = 2000
_REQUIRED_FIELDS = [
    "campaign_brief",
    "audience_segment",
    "target_channels",
    "target_languages",
    "brand_tone",
    "campaign_goal",
]


def system_validate(state: WorkflowState) -> WorkflowState:
    """LangGraph node: structural + format checks with no LLM call."""
    raw_brief = state["brief"]

    try:
        brief = CampaignBrief.model_validate(raw_brief)
    except ValidationError as exc:
        field = ".".join(str(part) for part in exc.errors()[0]["loc"])
        return _fail(state, f"Required field '{field}' is missing or empty.")

    for field in _REQUIRED_FIELDS:
        value = getattr(brief, field)
        if not value or (isinstance(value, list) and len(value) == 0):
            return _fail(state, f"Required field '{field}' is missing or empty.")

    words = len(brief.campaign_brief.split())
    if words < _MIN_BRIEF_WORDS:
        return _fail(state, f"Campaign brief too short ({words} words; minimum {_MIN_BRIEF_WORDS}).")

    if len(brief.campaign_brief) > _MAX_BRIEF_CHARS:
        return _fail(state, f"Campaign brief exceeds {_MAX_BRIEF_CHARS} characters.")

    bad_channels = [c for c in brief.target_channels if c not in VALID_CHANNELS]
    if bad_channels:
        return _fail(state, f"Unsupported channels: {bad_channels}. Valid: {sorted(VALID_CHANNELS)}.")

    bad_langs = [la for la in brief.target_languages if la not in VALID_LANGUAGES]
    if bad_langs:
        return _fail(state, f"Unsupported languages: {bad_langs}. Valid: {sorted(VALID_LANGUAGES)}.")

    return {**state, "system_valid": True}


def _fail(state: WorkflowState, reason: str) -> WorkflowState:
    return {**state, "system_valid": False, "validation_error": reason, "status": "system_failed"}
