from __future__ import annotations

import pytest

from pipeline.conversation_models import ConversationPlannerOutput, PartialBrief
from services.chat.conversation_responder import conversation_responder


def test_responder_fallback_uses_greeting_question() -> None:
    planner_output = ConversationPlannerOutput(
        stage="greeting",
        objective="Open collaboratively",
        reply_strategy="greeting",
        next_question="Hey, what are you launching?",
    )

    message = conversation_responder._fallback_message(
        planner_output,
        PartialBrief(),
        [],
        "hi",
    )

    assert message == "Hey, what are you launching?"


def test_responder_fallback_witty_redirect_deflects_and_nudges() -> None:
    planner_output = ConversationPlannerOutput(
        stage="general_assistance",
        objective="Steer back to planning",
        reply_strategy="witty_redirect",
        next_question=None,
    )

    message = conversation_responder._fallback_message(
        planner_output,
        PartialBrief(),
        [],
        "what's the weather today",
    )

    assert "wheelhouse" in message.lower()
    assert "launch" in message.lower()


@pytest.mark.asyncio
async def test_responder_witty_redirect_calls_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def _fake_traced_llm_call(**kwargs: object):
        called["hit"] = True
        return "Ha, no clouds in my forecast — but what campaign can I help you launch?", {}

    monkeypatch.setattr("services.chat.conversation_responder.traced_llm_call", _fake_traced_llm_call)

    planner_output = ConversationPlannerOutput(
        stage="general_assistance",
        objective="Steer back to planning",
        reply_strategy="witty_redirect",
        next_question=None,
    )

    message = await conversation_responder.respond(
        planner_output=planner_output,
        brief=PartialBrief(),
        brief_changes=[],
        user_message="what's the weather today",
        state={"model_aliases": {"responder": "eval-model"}},
    )

    # witty_redirect must NOT short-circuit to the grounded fallback; the LLM runs.
    assert called.get("hit") is True
    assert message == "Ha, no clouds in my forecast — but what campaign can I help you launch?"

    planner_output = ConversationPlannerOutput(
        stage="audience_discovery",
        objective="Understand audience",
        reply_strategy="high_value_followup",
        next_question="Who should we prioritize first?",
    )

    message = conversation_responder._fallback_message(
        planner_output,
        PartialBrief(objective="Launch"),
        [{"field": "objective", "change_type": "added", "before": None, "after": "Launch"}],
        "objective is launch",
    )

    assert "captured the campaign objective" in message
    assert message.endswith("Who should we prioritize first?")


@pytest.mark.asyncio
async def test_responder_ignores_fallback_generated_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_traced_llm_call(**_: object):
        return "[fallback-generated] {\"planner\": {\"stage\": \"greeting\"}}", {}

    monkeypatch.setattr("services.chat.conversation_responder.traced_llm_call", _fake_traced_llm_call)

    planner_output = ConversationPlannerOutput(
        stage="greeting",
        objective="Open collaboratively",
        reply_strategy="greeting",
        next_question="Hey, what are you launching?",
    )

    message = await conversation_responder.respond(
        planner_output=planner_output,
        brief=PartialBrief(),
        brief_changes=[],
        user_message="hi",
        state={"model_aliases": {"responder": "eval-model"}},
    )

    assert message == "Hey, what are you launching?"


@pytest.mark.asyncio
async def test_responder_greeting_uses_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_traced_llm_call(**kwargs: object):
        captured.update(kwargs)
        return "Hey there. What are you launching first?", {}

    monkeypatch.setattr("services.chat.conversation_responder.traced_llm_call", _fake_traced_llm_call)

    planner_output = ConversationPlannerOutput(
        stage="greeting",
        objective="Open collaboratively",
        reply_strategy="greeting",
        next_question="Hey, what are you launching?",
    )

    message = await conversation_responder.respond(
        planner_output=planner_output,
        brief=PartialBrief(),
        brief_changes=[],
        user_message="hello",
        state={"model_aliases": {"responder": "eval-model"}},
    )

    assert message == "Hey there. What are you launching first?"
    assert captured.get("task") == "conversation_responder"


@pytest.mark.asyncio
async def test_responder_filters_meta_reasoning_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_traced_llm_call(**_: object):
        return (
            "You've acknowledged the captured fields. Can you confirm the primary objective and secondary objectives?",
            {},
        )

    monkeypatch.setattr("services.chat.conversation_responder.traced_llm_call", _fake_traced_llm_call)

    planner_output = ConversationPlannerOutput(
        stage="objective_discovery",
        objective="Clarify launch context",
        reply_strategy="high_value_followup",
        next_question="What concrete outcome should this campaign drive first?",
    )

    message = await conversation_responder.respond(
        planner_output=planner_output,
        brief=PartialBrief(),
        brief_changes=[],
        user_message="we are launching a compliance copilot",
        state={"model_aliases": {"responder": "util-fast"}},
    )

    assert message == "Thanks, that helps. What concrete outcome should this campaign drive first?"


@pytest.mark.asyncio
async def test_responder_uses_grounded_fallback_for_incomplete_brief_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _should_not_call_llm(**_: object):
        raise AssertionError("LLM should not be called for grounded follow-up turns")

    monkeypatch.setattr("services.chat.conversation_responder.traced_llm_call", _should_not_call_llm)

    planner_output = ConversationPlannerOutput(
        stage="objective_discovery",
        objective="Clarify launch context",
        reply_strategy="high_value_followup",
        next_question="What concrete outcome should this campaign drive first?",
    )

    message = await conversation_responder.respond(
        planner_output=planner_output,
        brief=PartialBrief(),
        brief_changes=[
            {
                "field": "key_messages",
                "change_type": "added",
                "before": [],
                "after": ["A compelling opening line or mystery that draws the audience in."],
            }
        ],
        user_message="A compelling opening line or mystery that draws the audience in.",
        state={"model_aliases": {"responder": "util-fast"}},
    )

    assert message == "Great, I captured key messaging. What concrete outcome should this campaign drive first?"
