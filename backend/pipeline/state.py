from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict


def merge_variants(
    existing: list["ContentVariant"], updates: list["ContentVariant"]
) -> list["ContentVariant"]:
    """Upsert-by-task_id reducer for the ``variants`` fan-in channel.

    Plain ``operator.add`` concatenation duplicates an entry whenever a node
    re-emits a variant it already produced — which is also the only way an
    in-place mutation to a variant dict (reflexion, personalization,
    translation, a selective content_generator regen) survives a checkpoint
    resume, since LangGraph only persists a channel value that a node's
    return dict actually includes. Mutating in place and returning ``{}``
    looks correct within a single ``ainvoke()`` (everyone shares the same
    Python objects) but is silently lost on resume — the checkpoint still has
    the pre-mutation value. Nodes must therefore return the variant(s) they
    touched via the "variants" key; this reducer replaces the matching
    task_id entry instead of appending a duplicate.
    """
    by_task_id = {v["task_id"]: v for v in existing}
    order = [v["task_id"] for v in existing]
    for v in updates:
        if v["task_id"] not in by_task_id:
            order.append(v["task_id"])
        by_task_id[v["task_id"]] = v
    return [by_task_id[tid] for tid in order]


class CampaignBrief(TypedDict):
    objective: str
    target_audience: str
    key_messages: list[str]
    tone_override: str | None
    channels: list[str]
    locales: list[str]
    audience_segments: list[str]
    # token_budget no longer collected from users; tracked end-to-end per campaign (2026-07-29)
    token_budget: int
    # Optional campaign validity end-date, threaded into generated content
    # when present ("Offer valid until..."). See next_tasks.md 2026-07-26
    # item 16.
    end_date: str | None
    raw_text: str


class GenerationTask(TypedDict):
    # 2026-07-27: locale removed — generation/personalization always target
    # SOURCE_LOCALE (pipeline/locale_utils.py); translation_agent is the only
    # place per-locale fan-out happens, from this one channel x segment task.
    task_id: str  # format: "{channel}_{segment}"
    channel: str
    segment: str
    channel_constraints: dict


class TranslationCheckResult(TypedDict):
    name: str
    value: float
    threshold: float
    passed: bool


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
    translation_retry_count: NotRequired[int]
    translation_gate_status: NotRequired[str]
    translation_checks: NotRequired[list[TranslationCheckResult]]
    translation_content_safety_violations: NotRequired[list[str]]


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
    # Reflexion retry round this score belongs to (mirrors variant retry_count).
    # Lets judges/aggregator stay idempotent under operator.add fan-in, which
    # cannot delete stale entries when a variant is regenerated and re-scored.
    evaluation_round: int


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
    # Reflexion retry round this aggregate was computed for (see BrandScore).
    evaluation_round: int


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

    # Creator feedback for a rerun (set by rerun_service via aupdate_state,
    # consumed and cleared by content_generator). Plain field, not fan-in.
    user_edit_note: str | None

    # Accumulated results (operator.add fan-in, except variants — see
    # merge_variants above)
    variants: Annotated[list[ContentVariant], merge_variants]
    brand_scores: Annotated[list[BrandScore], operator.add]
    aggregated_scores: Annotated[list[AggregatedScore], operator.add]
    review_requests: Annotated[list[ReviewRequest], operator.add]
    publication_receipts: Annotated[list[PublicationReceipt], operator.add]
    failed_task_ids: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    # Output guardrail flags from content_generator / personalization_agent.
    # Accumulated via operator.add so both agents can write concurrently.
    guardrail_flags: Annotated[list[str], operator.add]

    # Pipeline control
    current_phase: str
    human_review_requested: bool
    publishing_paused: bool
    judge_mode: str  # set by judge_gate: "skip" | "lite" | "full"

    # Human review gate (plain channels, not fan-in — review_round is replaced
    # on each aupdate_state resume; review_decisions is injected by the
    # reviewer API/chat before resuming, keyed by variant task_id)
    review_round: int
    review_decisions: dict

    # Cost tracking
    token_cost_usd: float
