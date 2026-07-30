from __future__ import annotations

from pipeline.conversation_models import ConversationPlannerInput, IntentClassification, PartialBrief
from services.chat.conversation_planner import conversation_planner


def test_planner_prefers_high_value_question_for_missing_audience_and_channels() -> None:
    brief = PartialBrief(objective="Launch AI assistant")
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="We are launching next month",
            intent="collect_brief",
            brief=brief,
            conversation_history=[],
            active_campaign_id=None,
        )
    )

    assert output.reply_strategy == "high_value_followup"
    assert output.stage in {"audience_discovery", "channel_discovery"}
    assert output.next_question is not None
    assert "who you want to reach" in output.next_question


def test_planner_detects_correction_from_brief_diff() -> None:
    brief = PartialBrief(objective="Launch AI assistant", channels=["linkedin"])
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="Actually, change channel focus to email first",
            intent="collect_brief",
            brief=brief,
            brief_changes=[
                {
                    "field": "channels",
                    "change_type": "replaced",
                    "before": ["linkedin"],
                    "after": ["email"],
                }
            ],
            conversation_history=[],
            active_campaign_id=None,
        )
    )

    assert output.correction_detected is True


def test_planner_routes_status_to_pipeline_monitoring() -> None:
    brief = PartialBrief(
        objective="Launch AI assistant",
        channels=["linkedin"],
        locales=["en-US"],
        audience_segments=["enterprise"],
        token_budget=1000,
    )

    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="What is the current campaign status?",
            intent="check_status",
            brief=brief,
            conversation_history=[],
            active_campaign_id="019f7669-1111-7000-8000-000000000001",
        )
    )

    assert output.stage == "pipeline_monitoring"
    assert output.reply_strategy == "campaign_copilot"


def test_planner_greeting_uses_conversational_strategy() -> None:
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="hi",
            intent="collect_brief",
            brief=PartialBrief(),
            conversation_history=[],
            active_campaign_id=None,
        )
    )

    assert output.stage == "greeting"
    assert output.reply_strategy == "greeting"
    assert output.next_question is not None
    assert "what are you launching" in output.next_question.lower()

def test_plan_treats_hi_with_punctuation_as_greeting() -> None:
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="hi!",
            intent="collect_brief",
            brief=PartialBrief(),
            conversation_history=[],
        )
    )

    assert output.stage == "greeting"
    assert output.reply_strategy == "greeting"

def test_plan_treats_hey_with_suffix_as_greeting() -> None:
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="hey there",
            intent="collect_brief",
            brief=PartialBrief(),
            conversation_history=[],
        )
    )

    assert output.stage == "greeting"
    assert output.reply_strategy == "greeting"


def test_planner_routes_off_topic_question_to_witty_redirect() -> None:
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="what's the weather today",
            intent="other",
            brief=PartialBrief(),
            conversation_history=[],
            active_campaign_id=None,
        )
    )

    assert output.stage == "general_assistance"
    assert output.reply_strategy == "witty_redirect"
    # Off-topic turns must not surface brief example utterances the responder
    # could otherwise render as user-provided campaign facts.
    assert output.suggested_prompts == []


def test_planner_asks_for_clarification_when_confidence_is_low() -> None:
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="Launch globally",
            intent="collect_brief",
            brief=PartialBrief(objective="Launch globally"),
            field_confidence={"objective": 0.4},
            brief_changes=[
                {
                    "field": "objective",
                    "change_type": "added",
                    "before": None,
                    "after": "Launch globally",
                }
            ],
            conversation_history=[],
        )
    )

    assert output.needs_clarification is True
    assert output.primary_objective == "resolve_ambiguity"
    assert output.reply_strategy == "clarification_followup"


def test_planner_maps_secondary_intent_to_secondary_objective() -> None:
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="Launch our AI assistant and also check campaign status",
            intent="collect_brief",
            brief=PartialBrief(),
            intent_classification=IntentClassification(
                primary="collect_brief",
                secondary=["check_status"],
                confidence=0.9,
            ),
            conversation_history=[],
        )
    )

    assert output.turn_type == "mixed"
    assert "explain_pipeline" in output.secondary_objectives


def test_planner_treats_submit_campaign_as_control_command() -> None:
    brief = PartialBrief(
        objective="Launch AI assistant",
        channels=["linkedin"],
        locales=["en-US"],
        audience_segments=["enterprise"],
        token_budget=1000,
    )

    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="submit this campaign",
            intent="submit_campaign",
            brief=brief,
            conversation_history=[],
            active_campaign_id=None,
        )
    )

    assert output.stage == "campaign_submission"
    assert output.turn_type == "control_command"
    assert output.primary_objective == "confirm_submission"


def test_planner_maps_secondary_submit_to_confirm_submission_objective() -> None:
    output = conversation_planner.plan(
        ConversationPlannerInput(
            user_message="Launch this and then submit campaign",
            intent="collect_brief",
            brief=PartialBrief(objective="Launch"),
            intent_classification=IntentClassification(
                primary="collect_brief",
                secondary=["submit_campaign"],
                confidence=0.88,
            ),
            conversation_history=[],
        )
    )

    assert "confirm_submission" in output.secondary_objectives
