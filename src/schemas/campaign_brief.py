from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

VALID_CHANNELS: set[str] = {"Instagram", "Facebook", "LinkedIn", "Email", "Web", "Catalog"}
VALID_LANGUAGES: set[str] = {"English", "French", "Spanish"}


class CampaignBrief(BaseModel):
    campaign_brief: str
    audience_segment: str
    target_channels: List[str]
    target_languages: List[str]
    brand_tone: str
    campaign_goal: str
    restricted_words: List[str] = Field(default_factory=list)
    validation_attempts: int = 0
    human_approved: bool = False


class ValidationResult(BaseModel):
    valid: bool = False
    reason: str = "No reason provided."
    persona: Optional[str] = None
