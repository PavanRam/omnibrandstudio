from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class CampaignBrief(TypedDict):
    objective: str
    target_audience: str
    key_messages: list[str]
    tone_override: str | None
    channels: list[str]
    locales: list[str]
    audience_segments: list[str]
    token_budget: int
    raw_text: str


class GenerationTask(TypedDict):
    task_id: str  # format: "{locale}_{channel}_{segment}"
    locale: str
    channel: str
    segment: str
    channel_constraints: dict


class ContentVariant(TypedDict):
    task_id: str
    locale: str
    channel: str
    segment: str
    generated_content: str | None
    personalized_content: str | None
    translated_content: str | None
    final_content: str | None
    status: str
    generation_model: str | None
    prompt_version: str | None
    brand_guide_version: str | None
    translation_engine: str | None
    back_translation_score: float | None
    retry_count: int
    reflexion_applied: bool
    failure_reason: str | None


class CriterionScore(TypedDict):
    score: float
    reasoning: str
    violations: list[str]
    citations: list[str]


class BrandScore(TypedDict):
    variant_id: str
    judge_model: str
    composite_score: float
    scores: dict[str, CriterionScore]
    critical_violations: list[str]
    routing_decision: str
    evaluation_latency_ms: int


class AggregatedScore(TypedDict):
    variant_id: str
    judge_scores: list[float]
    weighted_mean: float
    variance: float
    consensus_level: str
    any_critical_violation: bool
    critical_violations: list[str]
    routing_decision: str
    routing_reason: str
    degraded_mode: bool


class ReviewRequest(TypedDict):
    review_request_id: str
    variant_id: str
    campaign_id: str
    routing_reason: str
    scores_snapshot: list[BrandScore]
    status: str


class PublicationReceipt(TypedDict):
    variant_id: str
    channel: str
    locale: str
    platform_publication_id: str | None
    public_url: str | None
    adapter_used: str
    publish_status: str
    published_at: str | None
    error_message: str | None


class RAGContext(TypedDict):
    brand_guide_chunks: list[str]
    section_types: list[str]
    brand_guide_version: str
    retrieval_scores: list[float]


class PriorCampaignContext(TypedDict):
    campaign_id: str
    brief_summary: str
    top_performing_channel: str | None
    avg_brand_score: float | None


class OmniBrandState(TypedDict):
    # Identity
    campaign_id: str
    org_id: str
    brand_id: str
    user_id: str
    request_id: str   # HTTP X-Request-ID that triggered the campaign; empty string for CLI runs
    started_at: str

    # Configuration (immutable after intake)
    org_config: dict
    brand_config: dict
    model_aliases: dict[str, str]

    # Brief (set by Intake Agent)
    brief: CampaignBrief | None

    # Context (set by Intake Agent)
    rag_context: RAGContext | None
    prior_campaigns: list[PriorCampaignContext]
    brief_valid: bool | None
    brief_validation_errors: list[str]
    budget_check_passed: bool | None

    # Task plan
    tasks: list[GenerationTask]
    current_task: GenerationTask | None

    # Accumulated results (operator.add fan-in)
    variants: Annotated[list[ContentVariant], operator.add]
    brand_scores: Annotated[list[BrandScore], operator.add]
    aggregated_scores: Annotated[list[AggregatedScore], operator.add]
    review_requests: Annotated[list[ReviewRequest], operator.add]
    publication_receipts: Annotated[list[PublicationReceipt], operator.add]
    failed_task_ids: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]

    # Pipeline control
    current_phase: str
    human_review_requested: bool
    publishing_paused: bool
    # T11 — human review: reviewer decisions injected on resume (keyed by task_id),
    # and a counter capping reject→regenerate loops. Both are plain (non-reducer)
    # channels so aupdate_state replaces rather than appends.
    review_round: int
    review_decisions: dict

    # Cost tracking
    token_cost_usd: float
