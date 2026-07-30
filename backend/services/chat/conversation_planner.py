from __future__ import annotations

import re

from pipeline.conversation_models import (
    BriefFieldState,
    ConversationObjective,
    ConversationPlannerInput,
    ConversationPlannerOutput,
    IntentClassification,
    PartialBrief,
)

CLARIFY_CONFIDENCE_THRESHOLD = 0.55


def _has_brief_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, int):
        return value > 0
    return True


def compute_brief_field_states(
    brief: PartialBrief,
    *,
    field_confidence: dict[str, float] | None = None,
    corrected_fields: set[str] | None = None,
    changed_fields: set[str] | None = None,
) -> list[BriefFieldState]:
    """Shared field-status computation — used both for the full chat-turn
    planner output and for structured picker updates (set_brief_field),
    which set a field directly without going through a planner turn but
    still need the panel to reflect the change immediately rather than
    waiting for the next websocket message (2026-07-30 fix: picker updates
    previously left the panel showing stale 'missing' status until the
    next chat turn recomputed it). token_budget is intentionally excluded —
    it's no longer collected from users (2026-07-29), so it would show as
    permanently 'missing' with no way for a user to resolve it."""
    field_confidence = field_confidence or {}
    corrected_fields = corrected_fields or set()
    changed_fields = changed_fields or set()

    states: list[BriefFieldState] = []
    for field in (
        "objective",
        "target_audience",
        "key_messages",
        "tone_override",
        "channels",
        "locales",
        "audience_segments",
    ):
        value = getattr(brief, field)
        confidence = field_confidence.get(field)
        has_value = _has_brief_value(value)

        status = "missing"
        if field in corrected_fields:
            status = "corrected"
        elif (
            field in changed_fields
            and confidence is not None
            and confidence < CLARIFY_CONFIDENCE_THRESHOLD
        ):
            status = "needs_confirmation"
        elif has_value and confidence is not None and confidence < 0.75:
            status = "inferred"
        elif has_value:
            status = "captured"

        states.append(
            BriefFieldState(field=field, status=status, value=value, confidence=confidence)
        )

    return states


class ConversationPlanner:
    def plan(self, payload: ConversationPlannerInput) -> ConversationPlannerOutput:
        stage = self._derive_stage(payload)
        correction_detected = self._detect_correction(payload)
        turn_type = self._classify_turn_type(payload, correction_detected)
        needs_clarification, clarification_target, clarification_reason = self._needs_clarification(payload)
        primary_objective = self._select_primary_objective(payload, stage, correction_detected, needs_clarification)
        secondary_objectives = self._secondary_objectives(payload.intent_classification)
        objective = self._objective_text(primary_objective)

        reply_strategy = "complete_brief_followup"
        if stage == "greeting":
            reply_strategy = "greeting"
        elif stage == "general_assistance":
            reply_strategy = "witty_redirect"
        elif payload.intent in {"check_status", "explain_progress", "show_agent_output", "view_history"}:
            reply_strategy = "campaign_copilot"
        elif not payload.brief.is_complete() and needs_clarification:
            reply_strategy = "clarification_followup"
        elif not payload.brief.is_complete():
            reply_strategy = "high_value_followup"

        return ConversationPlannerOutput(
            stage=stage,
            objective=objective,
            reply_strategy=reply_strategy,
            primary_objective=primary_objective,
            secondary_objectives=secondary_objectives,
            turn_type=turn_type,
            suggested_prompts=self._suggest_prompts(payload),
            next_question=self._next_high_value_question(payload),
            needs_clarification=needs_clarification,
            clarification_target=clarification_target,
            clarification_reason=clarification_reason,
            brief_field_states=self._compute_field_states(payload),
            summarize=stage in {"pipeline_monitoring", "artifact_exploration"},
            confirm_submission=stage == "campaign_submission",
            correction_detected=correction_detected,
        )

    def _derive_stage(self, payload: ConversationPlannerInput) -> str:
        if payload.active_campaign_id:
            if payload.intent in {"show_agent_output", "view_history"}:
                return "artifact_exploration"
            if payload.intent in {"rerun_campaign", "iterate_campaign"}:
                return "campaign_iteration"
            return "pipeline_monitoring"

        if payload.intent == "greeting" or self._is_greeting(payload.user_message):
            return "greeting"

        # Off-topic / general chit-chat (e.g. "what's the weather?") that carries
        # no campaign signal is handled by a short witty redirect rather than being
        # forced into brief collection. Greetings are handled above and take
        # priority, so this only catches genuine off-topic questions.
        if payload.intent == "other" and not self._is_greeting(payload.user_message):
            return "general_assistance"

        if payload.brief.is_complete() and not payload.active_campaign_id:
            return "campaign_submission"

        missing = set(payload.brief.missing_slots())
        if "objective" in missing:
            return "objective_discovery"
        if "audience_segments" in missing:
            return "audience_discovery"
        if "channels" in missing:
            return "channel_discovery"
        if "token_budget" in missing:
            return "constraint_discovery"
        if "locales" in missing:
            return "messaging_discovery"
        return "campaign_discovery"

    def _classify_turn_type(self, payload: ConversationPlannerInput, correction_detected: bool) -> str:
        normalized = " ".join(payload.user_message.lower().strip().split())
        if payload.intent == "greeting" or self._is_greeting(payload.user_message):
            return "greeting"
        if correction_detected:
            return "correcting"
        if payload.intent in {"check_status", "explain_progress", "show_agent_output", "view_history", "rerun_campaign", "submit_campaign"}:
            return "control_command"
        if payload.intent_classification and payload.intent_classification.secondary:
            return "mixed"
        if "?" in payload.user_message:
            return "asking_question"
        if normalized in {"thanks", "thank you", "ok", "okay", "cool", "sounds good"}:
            return "smalltalk"
        if len(normalized.split()) >= 12:
            return "elaborating"
        return "providing_info"

    def _select_primary_objective(
        self,
        payload: ConversationPlannerInput,
        stage: str,
        correction_detected: bool,
        needs_clarification: bool,
    ) -> ConversationObjective:
        if stage == "greeting":
            return "build_rapport"

        if stage == "general_assistance":
            # Off-topic turn: acknowledge briefly, then steer back to planning.
            return "answer_product_question"

        if needs_clarification:
            return "resolve_ambiguity"

        if payload.active_campaign_id:
            return self._objective_for_active_campaign(payload.intent)

        missing = set(payload.brief.missing_slots())
        missing_objective = self._objective_for_missing_slots(missing)
        if missing_objective:
            return missing_objective
        if correction_detected:
            return "confirm_correction"

        if payload.brief.is_complete():
            return "confirm_submission"
        return "summarize_progress"

    def _objective_for_active_campaign(self, intent: str) -> ConversationObjective:
        if intent in {"check_status", "explain_progress"}:
            return "explain_pipeline"
        if intent == "show_agent_output":
            return "retrieve_artifact"
        if intent == "view_history":
            return "historical_lookup"
        if intent in {"rerun_campaign", "iterate_campaign"}:
            return "iterate_campaign"
        if intent == "modify_brief":
            return "modify_brief"
        return "summarize_progress"

    def _objective_for_missing_slots(self, missing: set[str]) -> ConversationObjective | None:
        if "objective" in missing:
            return "clarify_launch_type"
        if "audience_segments" in missing:
            return "understand_audience"
        if "channels" in missing:
            return "understand_channels"
        if {"locales", "token_budget"} & missing:
            return "capture_constraints"
        return None

    def _secondary_objectives(self, classification: IntentClassification | None) -> list[ConversationObjective]:
        if classification is None:
            return []

        mapped: list[ConversationObjective] = []
        for intent in classification.secondary:
            objective = self._intent_to_objective(intent)
            if objective and objective not in mapped:
                mapped.append(objective)
        return mapped

    def _intent_to_objective(self, intent: str) -> ConversationObjective | None:
        mapping: dict[str, ConversationObjective] = {
            "collect_brief": "clarify_launch_type",
            "greeting": "build_rapport",
            "check_status": "explain_pipeline",
            "explain_progress": "explain_pipeline",
            "show_agent_output": "retrieve_artifact",
            "rerun_campaign": "iterate_campaign",
            "iterate_campaign": "iterate_campaign",
            "view_history": "historical_lookup",
            "modify_brief": "modify_brief",
            "submit_campaign": "confirm_submission",
            "ask_product": "answer_product_question",
        }
        return mapping.get(intent)

    def _objective_text(self, objective: ConversationObjective) -> str:
        objective_copy: dict[ConversationObjective, str] = {
            "build_rapport": "Open with a collaborative kickoff before collecting details.",
            "clarify_launch_type": "Clarify the launch context to improve downstream campaign quality.",
            "understand_audience": "Understand who the campaign should prioritize.",
            "understand_channels": "Identify where the audience will discover the campaign.",
            "capture_constraints": "Capture constraints and delivery requirements for generation.",
            "resolve_ambiguity": "Clarify ambiguous brief details before committing updates.",
            "confirm_correction": "Confirm and acknowledge the latest correction to the brief.",
            "summarize_progress": "Summarize progress and guide the next action.",
            "confirm_submission": "Guide the user to submit the complete brief.",
            "explain_pipeline": "Answer campaign progress and execution questions.",
            "retrieve_artifact": "Help the user inspect campaign artifacts and trace history.",
            "iterate_campaign": "Support campaign iteration and selective reruns.",
            "modify_brief": "Apply brief modifications while preserving campaign context.",
            "historical_lookup": "Retrieve campaign and conversation history context.",
            "answer_product_question": "Answer product capability questions and steer back to planning.",
        }
        return objective_copy.get(objective, "Collect the highest-value information for the brief.")

    def _next_high_value_question(self, payload: ConversationPlannerInput) -> str | None:
        if self._is_greeting(payload.user_message):
            return (
                "Hey, great to collaborate on this. "
                "What are you launching, and who do you most want to reach first?"
            )

        if payload.brief.is_complete() and not payload.active_campaign_id:
            return None

        needs_clarification, target, _ = self._needs_clarification(payload)
        if needs_clarification and target:
            return f"Quick check before we lock this in: could you clarify the {target.replace('_', ' ')}?"

        missing = set(payload.brief.missing_slots())
        if {"channels", "audience_segments"} & missing:
            return (
                "Great direction so far. Tell me more about who you want to reach "
                "and where they are most likely to discover this campaign."
            )
        if "objective" in missing:
            return "What concrete outcome should this campaign drive first?"
        if "locales" in missing:
            return "Which markets or locales should we prioritize for this launch?"
        if "token_budget" in missing:
            return "What budget guardrail should I use for generation and scoring?"

        return "What is the most important detail you want me to capture next?"

    def _suggest_prompts(self, payload: ConversationPlannerInput) -> list[str]:
        if self._is_greeting(payload.user_message):
            return [
                "We are launching a new offer next month",
                "Our primary audience is enterprise IT buyers",
                "Help me shape the campaign brief step by step",
            ]

        # Off-topic turns get a witty redirect, not brief prompts. Returning
        # missing-slot example utterances here previously let the responder model
        # render them as if the user had actually supplied those campaign facts.
        if payload.intent == "other" and not self._is_greeting(payload.user_message):
            return []

        if payload.brief.is_complete() and not payload.active_campaign_id:
            return ["Run campaign", "Recap my brief", "Adjust channels"]

        if payload.active_campaign_id:
            return ["What is the current campaign status?", "Show outputs from content_generator", "Show campaign history"]

        missing = set(payload.brief.missing_slots())
        prompts: list[str] = []
        if "objective" in missing:
            prompts.append("Our objective is to drive qualified demo requests")
        if "channels" in missing:
            prompts.append("Use LinkedIn, email, and landing page")
        if "audience_segments" in missing:
            prompts.append("Target enterprise IT leaders and security buyers")
        if "locales" in missing:
            prompts.append("Focus on en-US and en-GB")
        # token_budget removed (2026-07-29): no longer collected from users, so no suggestion chip.
        if payload.intent_classification and "check_status" in payload.intent_classification.secondary:
            prompts.append("After this, also check my latest campaign status")
        return prompts[:3]

    def _detect_correction(self, payload: ConversationPlannerInput) -> bool:
        return any(str(change.get("change_type")) == "replaced" for change in payload.brief_changes)

    def _needs_clarification(self, payload: ConversationPlannerInput) -> tuple[bool, str | None, str | None]:
        for field, confidence in payload.field_confidence.items():
            if confidence < CLARIFY_CONFIDENCE_THRESHOLD:
                return True, field, "low_confidence"
        return False, None, None

    def _compute_field_states(self, payload: ConversationPlannerInput) -> list[BriefFieldState]:
        corrected_fields = {
            str(change.get("field"))
            for change in payload.brief_changes
            if str(change.get("change_type")) == "replaced" and change.get("field")
        }
        changed_fields = {
            str(change.get("field"))
            for change in payload.brief_changes
            if change.get("field")
        }
        return compute_brief_field_states(
            payload.brief,
            field_confidence=payload.field_confidence,
            corrected_fields=corrected_fields,
            changed_fields=changed_fields,
        )

    def _is_greeting(self, message: str) -> bool:
        normalized = re.sub(r"[^a-z\s]", " ", message.lower())
        normalized = " ".join(normalized.split())
        if not normalized:
            return False

        direct_greetings = {
            "hi",
            "hello",
            "hey",
            "yo",
            "hiya",
            "good morning",
            "good afternoon",
            "good evening",
        }
        if normalized in direct_greetings:
            return True

        return normalized.startswith(("hi ", "hello ", "hey ", "good morning ", "good afternoon ", "good evening "))


conversation_planner = ConversationPlanner()
