from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


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
    token_budget: int | None = None
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
        if self.token_budget is None or self.token_budget <= 0:
            missing.append("token_budget")
        return missing

    def is_complete(self) -> bool:
        return len(self.missing_slots()) == 0


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


class RecentConversation(BaseModel):
    conversation_id: str
    brand_id: str
    status: str
    active_campaign_id: str | None = None
    partial_brief: PartialBrief = Field(default_factory=PartialBrief)
    updated_at: datetime
