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


def test_fallback_patch_parses_natural_language_outcome_answer() -> None:
    patch = brief_collector._fallback_patch_from_text(
        "The absolute first concrete outcome this campaign must drive is customer acquisition cost (CAC) efficiency through immediate conversion volume."
    )

    assert patch["objective"] == (
        "customer acquisition cost (CAC) efficiency through immediate conversion volume"
    )


def test_fallback_patch_parses_natural_language_audience_answer() -> None:
    patch = brief_collector._fallback_patch_from_text(
        "We want to reach enterprise IT leaders and security buyers first."
    )

    assert patch["audience_segments"] == ["enterprise IT leaders and security buyers first"]


def test_non_brief_turn_detects_greeting() -> None:
    assert brief_collector._is_non_brief_turn("hi") is True


def test_non_brief_turn_detects_control_prompt() -> None:
    assert brief_collector._is_non_brief_turn("What is the current campaign status?") is True


def test_non_brief_turn_allows_real_brief_input() -> None:
    assert brief_collector._is_non_brief_turn("Objective: launch ESG report v6 for enterprise buyers") is False


def test_non_brief_turn_allows_run_campaign_with_brief_fields() -> None:
    assert (
        brief_collector._is_non_brief_turn(
            "Objective: launch ESG report v6. Channels: linkedin,email. Run campaign"
        )
        is False
    )


def test_non_brief_turn_still_detects_run_campaign_alone() -> None:
    assert brief_collector._is_non_brief_turn("run campaign") is True


def test_merge_missing_patch_fields_uses_fallback_for_uncaptured_fields() -> None:
    merged = brief_collector._merge_missing_patch_fields(
        {"objective": "Launch AI assistant"},
        {
            "objective": "Launch AI assistant",
            "channels": ["linkedin", "email"],
            "locales": ["en-US", "fr-FR"],
            "audience_segments": ["enterprise", "sme"],
            "token_budget": 4000,
        },
    )

    assert merged["objective"] == "Launch AI assistant"
    assert merged["channels"] == ["linkedin", "email"]
    assert merged["locales"] == ["en-US", "fr-FR"]
    assert merged["audience_segments"] == ["enterprise", "sme"]
    assert merged["token_budget"] == 4000