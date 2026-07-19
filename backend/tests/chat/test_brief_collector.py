from services.chat.brief_collector import brief_collector


def test_fallback_patch_parses_required_brief_fields() -> None:
    patch = brief_collector._fallback_patch_from_text(
        "Objective: Launch ESG report v6. Channels: linkedin,email. "
        "Locales: en-US,fr-FR. Audience segments: enterprise,sme. Token budget: 4000."
    )

    assert patch["objective"] == "Launch ESG report v6"
    assert patch["channels"] == ["linkedin", "email"]
    assert patch["locales"] == ["en-US", "fr-FR"]
    assert patch["audience_segments"] == ["enterprise", "sme"]
    assert patch["token_budget"] == 4000


def test_fallback_patch_parses_objective_phrase_form() -> None:
    patch = brief_collector._fallback_patch_from_text(
        "Our primary campaign objective is to launch ESG report v6 for investors."
    )

    assert patch["objective"] == "launch ESG report v6 for investors"


def test_non_brief_turn_detects_greeting() -> None:
    assert brief_collector._is_non_brief_turn("hi") is True


def test_non_brief_turn_detects_control_prompt() -> None:
    assert brief_collector._is_non_brief_turn("What is the current campaign status?") is True


def test_non_brief_turn_allows_real_brief_input() -> None:
    assert brief_collector._is_non_brief_turn("Objective: launch ESG report v6 for enterprise buyers") is False


def test_parse_patch_with_meta_extracts_field_confidence() -> None:
    patch, meta = brief_collector._parse_patch_with_meta(
        '{"objective":"Launch AI assistant","field_confidence":{"objective":0.88}}'
    )

    assert patch["objective"] == "Launch AI assistant"
    assert meta.field_confidence["objective"] == 0.88
    assert meta.source == "llm"


def test_parse_patch_with_meta_handles_invalid_payload() -> None:
    patch, meta = brief_collector._parse_patch_with_meta("not-json")

    assert patch == {}
    assert meta.field_confidence == {}