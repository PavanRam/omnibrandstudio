from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

# ── Campaign lifecycle ────────────────────────────────────────────────────


class CreateCampaignRequest(BaseModel):
    brand_id: str
    objective: str
    target_audience: str
    key_messages: list[str] = Field(default_factory=list)
    tone_override: str | None = None
    channels: list[str] = Field(min_length=1)
    locales: list[str] = Field(min_length=1)
    audience_segments: list[str] = Field(min_length=1)
    token_budget: int = Field(gt=0)
    raw_text: str = ""


class RunCampaignRequest(BaseModel):
    campaign_id: str


class ReviewDecision(BaseModel):
    decision: Literal["approved", "rejected", "edited"]
    reviewer_note: str | None = None
    edited_content: str | None = None

    @model_validator(mode="after")
    def check_edited_content_present(self) -> "ReviewDecision":
        if self.decision == "edited" and not self.edited_content:
            raise ValueError("edited_content is required when decision is 'edited'")
        if self.decision != "edited" and self.edited_content:
            raise ValueError("edited_content may only be set when decision is 'edited'")
        return self


# ── Judge output ──────────────────────────────────────────────────────────


class CriterionScore(BaseModel):
    score: float = Field(ge=0.0, le=10.0)
    reasoning: str
    violations: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class BrandScoreOutput(BaseModel):
    tone_alignment: CriterionScore
    vocabulary_compliance: CriterionScore
    channel_format_adherence: CriterionScore
    cta_style: CriterionScore
    cultural_appropriateness: CriterionScore
    factual_grounding: CriterionScore  # 6th criterion — weight 0.25
    composite_score: float = Field(..., ge=0.0, le=10.0)
    critical_violations: list[str] = Field(default_factory=list)
    routing_decision: Literal["auto_approve", "flag", "auto_reject"]
    routing_explanation: str = Field(..., min_length=20)


# ── API responses ─────────────────────────────────────────────────────────


class VariantSummary(BaseModel):
    task_id: str
    locale: str
    channel: str
    segment: str
    status: str
    final_content: str | None = None
    composite_score: float | None = None


class CampaignResponse(BaseModel):
    id: str
    org_id: str
    brand_id: str
    status: str
    token_cost_usd: float
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CampaignDetailResponse(CampaignResponse):
    brief: dict
    variants: list[VariantSummary] = Field(default_factory=list)


class ReviewRequestResponse(BaseModel):
    review_request_id: str
    variant_id: str
    campaign_id: str
    routing_reason: str
    status: str
    sla_deadline: datetime | None = None


class PublicationReceiptResponse(BaseModel):
    variant_id: str
    channel: str
    locale: str
    public_url: str | None = None
    publish_status: str
    published_at: datetime | None = None
    error_message: str | None = None


# ── Worker / queue payloads ───────────────────────────────────────────────


class CampaignTask(BaseModel):
    campaign_id: str
    org_id: str
    brand_id: str
    user_id: str = ""


class WebhookPayload(BaseModel):
    event: str
    campaign_id: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Generic envelope ──────────────────────────────────────────────────────

T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ResponseEnvelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
