from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field

from pipeline.intake_validation import ROUGH_TOKENS_PER_TASK, check_budget, estimate_task_count


UserIntent = Literal[
    "collect_brief",
    "modify_brief",
    "submit_campaign",
    "check_status",
    "explain_progress",
    "show_agent_output",
    "rerun_campaign",
    "view_history",
    "iterate_campaign",
    "ask_product",
    "greeting",
    "other",
    "list_reviews",
    "decide_review",
]


ConversationObjective = Literal[
    "build_rapport",
    "clarify_launch_type",
    "understand_audience",
    "understand_channels",
    "capture_constraints",
    "resolve_ambiguity",
    "confirm_correction",
    "summarize_progress",
    "confirm_submission",
    "explain_pipeline",
    "retrieve_artifact",
    "iterate_campaign",
    "modify_brief",
    "historical_lookup",
    "answer_product_question",
]


TurnType = Literal[
    "greeting",
    "smalltalk",
    "providing_info",
    "elaborating",
    "correcting",
    "asking_question",
    "control_command",
    "mixed",
]


FieldStatus = Literal[
    "captured",
    "inferred",
    "needs_confirmation",
    "corrected",
    "missing",
]


ConversationStage = Literal[
    "greeting",
    "campaign_discovery",
    "objective_discovery",
    "audience_discovery",
    "messaging_discovery",
    "channel_discovery",
    "constraint_discovery",
    "brief_review",
    "campaign_submission",
    "pipeline_monitoring",
    "artifact_exploration",
    "campaign_iteration",
    "general_assistance",
]


class ConversationPlannerInput(BaseModel):
    user_message: str
    intent: UserIntent
    brief: "PartialBrief"
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    active_campaign_id: str | None = None
    previous_brief: "PartialBrief | None" = None
    brief_changes: list[dict[str, Any]] = Field(default_factory=list)
    intent_classification: "IntentClassification | None" = None
    field_confidence: dict[str, float] = Field(default_factory=dict)


class ConversationPlannerOutput(BaseModel):
    stage: ConversationStage
    objective: str
    reply_strategy: str
    primary_objective: ConversationObjective = "build_rapport"
    secondary_objectives: list[ConversationObjective] = Field(default_factory=list)
    turn_type: TurnType = "providing_info"
    suggested_prompts: list[str] = Field(default_factory=list)
    next_question: str | None = None
    needs_clarification: bool = False
    clarification_target: str | None = None
    clarification_reason: str | None = None
    brief_field_states: list["BriefFieldState"] = Field(default_factory=list)
    acknowledge: bool = True
    summarize: bool = False
    confirm_submission: bool = False
    correction_detected: bool = False


class IntentClassification(BaseModel):
    primary: UserIntent
    secondary: list[UserIntent] = Field(default_factory=list)
    confidence: float = 1.0
    requires_action: bool = False
    mutation_intent: bool = False


class ExtractionMeta(BaseModel):
    field_confidence: dict[str, float] = Field(default_factory=dict)
    source: str = "llm"
    # Values a free-text turn mentioned for channels/locales/audience_segments
    # that were dropped rather than written into the brief — either because
    # they aren't actually supported (channels/locales), or because that
    # field is picker-only now (audience_segments). Lets the chat turn tell
    # the user why nothing changed instead of silently ignoring them.
    # See next_tasks.md item 23d (2026-07-27).
    rejected: dict[str, list[str]] = Field(default_factory=dict)


class BriefFieldState(BaseModel):
    field: str
    status: FieldStatus
    value: Any | None = None
    confidence: float | None = None


class PartialBrief(BaseModel):
    objective: str | None = None
    target_audience: str | None = None
    key_messages: list[str] = Field(default_factory=list)
    tone_override: str | None = None
    channels: list[str] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=list)
    audience_segments: list[str] = Field(default_factory=list)
    # token_budget no longer collected from users; system tracks end-to-end consumption (2026-07-29)
    # Kept for backward compatibility but not required in brief collection
    token_budget: int | None = None
    # Optional campaign validity end-date ("this offer runs through March
    # 31") — deliberately NOT in missing_slots()/is_complete(), doesn't
    # block brief completion. Threaded into generated content when present.
    # See next_tasks.md 2026-07-26 item 16.
    end_date: str | None = None
    raw_text: str = ""

    def missing_slots(self) -> list[str]:
        missing: list[str] = []
        if not (self.objective or "").strip():
            missing.append("objective")
        if not self.channels:
            missing.append("channels")
        if not self.locales:
            missing.append("locales")
        if not self.audience_segments:
            missing.append("audience_segments")
        # token_budget no longer asked from users; auto-set to 200k on frontend (2026-07-29)
        # Removed from missing_slots() so conversation doesn't ask for budget guardrail
        return missing

    def budget_shortfall(self) -> str | None:
        """Return the same insufficient-budget message intake would raise, or
        None if the budget is sufficient (or not yet checkable — channels/
        locales/audience_segments still missing)."""
        if self.token_budget is None or self.token_budget <= 0:
            return None
        if not (self.channels and self.locales and self.audience_segments):
            return None
        errors = check_budget(
            self.token_budget, self.channels, self.locales, self.audience_segments
        )
        return errors[0] if errors else None

    def is_complete(self) -> bool:
        return len(self.missing_slots()) == 0


class UnderstandingResult(BaseModel):
    """Merged output of the single understanding LLM call.

    Combines intent classification and brief extraction so the two
    understanding passes share the same context (including history).
    """

    intent: IntentClassification
    brief: PartialBrief
    extraction_meta: ExtractionMeta = Field(default_factory=ExtractionMeta)


class ConversationSession(BaseModel):
    id: str
    brand_id: str
    org_id: str
    created_by: str | None = None
    status: str
    partial_brief: PartialBrief = Field(default_factory=PartialBrief)
    active_campaign_id: str | None = None
    campaign_ids: list[str] = Field(default_factory=list)
    summary: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RecentCampaign(BaseModel):
    campaign_id: str
    brand_id: str
    status: str
    created_at: datetime
    variant_count: int = 0
    cost_usd: float = 0.0
    objective: str | None = None
    target_audience: str | None = None


class RecentConversation(BaseModel):
    conversation_id: str
    brand_id: str
    # The conversation's own lifecycle status (collecting/awaiting_confirmation/
    # processing) reflects how the brief was gathered, but is never rewritten
    # once a campaign attaches — a campaign moving through
    # draft/awaiting_review/published/failed left the sidebar frozen at
    # "processing" for hours (see next_tasks.md item 10, 2026-07-26). Prefer
    # `campaign_status` for display whenever a campaign is attached.
    status: str
    campaign_status: str | None = None
    active_campaign_id: str | None = None
    partial_brief: PartialBrief = Field(default_factory=PartialBrief)
    # Fallback label for the sidebar when partial_brief has no objective yet
    # (conversation abandoned mid-brief-collection) — see next_tasks.md item 11.
    first_message: str | None = None
    updated_at: datetime


class SimilarCampaignMatch(BaseModel):
    """A likely-duplicate campaign found before enqueueing a new one — purely
    advisory (see services.campaign.similarity_service.find_similar_campaign).
    The caller decides whether to proceed; nothing is ever blocked."""

    campaign_id: str
    objective: str | None = None
    target_audience: str | None = None
    channels: list[str] = Field(default_factory=list)
    status: str
    score: float
