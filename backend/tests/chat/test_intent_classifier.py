from __future__ import annotations

from services.chat.intent_classifier import intent_classifier


def test_parse_classification_supports_submit_campaign_flags() -> None:
    parsed = intent_classifier._parse_classification(
        '{"primary":"submit_campaign","secondary":["modify_brief"],"confidence":0.93,"requires_action":false,"mutation_intent":false}'
    )

    assert parsed.primary == "submit_campaign"
    assert parsed.secondary == ["modify_brief"]
    assert parsed.confidence == 0.93
    # submit_campaign is always an action intent.
    assert parsed.requires_action is True
    # mutation intent is elevated when mutation intents appear in primary/secondary.
    assert parsed.mutation_intent is True


def test_parse_classification_coerces_boolean_string_flags() -> None:
    parsed = intent_classifier._parse_classification(
        '{"primary":"iterate_campaign","secondary":[],"confidence":0.8,"requires_action":"true","mutation_intent":"false"}'
    )

    assert parsed.primary == "iterate_campaign"
    assert parsed.requires_action is True
    # iterate_campaign is always mutation intent even if model under-reports it.
    assert parsed.mutation_intent is True
