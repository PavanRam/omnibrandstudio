from services.chat.brief_collector import brief_collector
from pipeline.conversation_models import PartialBrief


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


async def test_update_partial_brief_with_meta_complements_partial_llm_patch(monkeypatch) -> None:
    async def _fake_traced_llm_call(**_: object):
        return '{"objective":"Launch ESG report v6"}', {}

    monkeypatch.setattr("services.chat.brief_collector.traced_llm_call", _fake_traced_llm_call)

    merged, meta = await brief_collector.update_partial_brief_with_meta(
        current=PartialBrief(),
        user_message=(
            "Objective: Launch ESG report v6. Channels: linkedin,email. "
            "Locales: en-US,fr-FR. Audience segments: enterprise,sme. "
            "Token budget: 4000. Run campaign"
        ),
        state={"model_aliases": {"brief_collector": "brief-collector"}},
    )

    assert merged.objective == "Launch ESG report v6"
    assert merged.channels == ["linkedin", "email"]
    assert merged.locales == ["en-US", "fr-FR"]
    # audience_segments is picker-only (2026-07-27) — even a confidently
    # extracted free-text value is dropped, not written into the brief, and
    # reported back via meta.rejected so the caller can point the user at
    # the picker instead.
    assert merged.audience_segments == []
    assert meta.rejected == {"audience_segments": ["enterprise", "sme"]}
    assert merged.token_budget == 4000
    assert meta.field_confidence["channels"] == 0.65

def test_merge_uses_raw_reply_as_segment_when_only_that_slot_is_missing() -> None:
    """Regression (2026-07-26): when audience_segments is the ONLY missing slot
    and the user answers with free text that doesn't match a known category
    (e.g. "regular weekday customers" instead of "enterprise"/"sme"/"consumer"),
    the bot used to re-ask the identical question forever since neither the LLM
    nor the regex fallback recognized the phrase as a segment value."""
    current = PartialBrief(
        objective="increase repeat visits",
        target_audience="regular weekday customers",
        channels=["email", "sms"],
        locales=["en", "fr"],
        key_messages=["earn a free drink after every 8 purchases"],
        audience_segments=[],
        token_budget=6000,
    )
    assert current.missing_slots() == ["audience_segments"]

    merged, rejected = brief_collector._merge(current, {}, "regular weekday customers")

    # audience_segments is picker-only now (2026-07-27) — the old backstop
    # that treated any raw reply as a segment label to escape the infinite
    # re-ask loop is retired, since the structured picker handles this slot
    # directly and validates against the brand's real seeded persona data.
    # A bare free-text turn with no patch produces nothing to reject either
    # (there's no explicit audience_segments value in this turn to flag).
    assert merged.audience_segments == []
    assert merged.missing_slots() == ["audience_segments"]
    assert rejected == {}


def test_merge_does_not_hijack_reply_when_other_slots_are_also_missing() -> None:
    """An unrelated free-text answer (e.g. answering the channels question)
    must never get wrongly captured as a segment."""
    current = PartialBrief(objective="increase repeat visits", channels=[])

    merged, _ = brief_collector._merge(current, {}, "email and sms")

    assert merged.audience_segments == []


def test_merge_rejects_audience_segments_from_free_text_even_when_extracted() -> None:
    """audience_segments must never be written into the brief from free text,
    even if the LLM/regex extraction confidently proposes one — only the
    structured picker (set_brief_field) may set it, since it's the only path
    that validates against the brand's real seeded persona data."""
    current = PartialBrief(objective="increase repeat visits")

    merged, rejected = brief_collector._merge(
        current, {"audience_segments": ["high-spenders"]}, "target high-spenders"
    )

    assert merged.audience_segments == []
    assert rejected == {"audience_segments": ["high-spenders"]}


def test_merge_rejects_unsupported_channels_and_locales_from_free_text() -> None:
    """Free-text channels/locales must be validated the same way the
    structured picker already validates them (item 23d, 2026-07-27) — an
    unsupported value is dropped, not silently written into the brief, and
    reported back so the caller can tell the user."""
    current = PartialBrief(objective="increase repeat visits")

    merged, rejected = brief_collector._merge(
        current,
        {"channels": ["email", "google ads"], "locales": ["fr", "ja"]},
        "email, google ads, French, Japanese",
    )

    assert merged.channels == ["email"]
    assert merged.locales == ["fr-FR"]
    assert rejected == {"channels": ["google ads"], "locales": ["ja"]}


def test_merge_normalizes_language_names_in_locales() -> None:
    """Regression (2026-07-26, campaign 019f9ee0-...): brief extraction
    captured locales as literal language names ("English", "French"), which
    matched nothing downstream (translation_agent's SUPPORTED_LOCALES gate,
    RAG retrieval). _merge must normalize every locales entry to a canonical
    BCP-47 tag regardless of source phrasing."""
    current = PartialBrief()

    merged, _ = brief_collector._merge(current, {"locales": ["English", "French"]}, "English and French")

    assert merged.locales == ["en-US", "fr-FR"]


def test_fallback_patch_extracts_end_date() -> None:
    patch = brief_collector._fallback_patch_from_text(
        "Objective: Launch spring sale. This offer runs through March 31."
    )

    assert patch["end_date"] == "March 31"


def test_end_date_extraction_returns_none_when_absent() -> None:
    assert brief_collector._extract_end_date("No expiry mentioned here at all.") is None


def test_merge_carries_end_date_into_partial_brief() -> None:
    current = PartialBrief()

    merged, _ = brief_collector._merge(current, {"end_date": "March 31"}, "runs through March 31")

    assert merged.end_date == "March 31"


def test_end_date_never_blocks_brief_completion() -> None:
    """end_date is optional — missing_slots()/is_complete() must not
    reference it at all."""
    complete_brief = PartialBrief(
        objective="increase repeat visits",
        channels=["email"],
        locales=["en-US"],
        audience_segments=["consumer"],
        token_budget=1000,
        end_date=None,
    )

    assert complete_brief.missing_slots() == []
    assert complete_brief.is_complete() is True
