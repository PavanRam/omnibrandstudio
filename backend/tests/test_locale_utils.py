"""normalize_locale — canonical locale normalization.

Regression (2026-07-26, campaign 019f9ee0-6bb1-7ec2-bc6d-2bdb877f6b4f): brief
extraction captured `locales` as literally ["English", "French"] (full
language names, not codes), which matched nothing anywhere downstream —
translation_agent's SUPPORTED_LOCALES gate rejected every variant as
"locale not supported" since it's a bare short-code set, and RAG retrieval
found no guideline chunks either.
"""
from pipeline.locale_utils import normalize_locale


def test_language_names_map_to_canonical_bcp47():
    assert normalize_locale("English") == "en-US"
    assert normalize_locale("french") == "fr-FR"
    assert normalize_locale("SPANISH") == "es-ES"


def test_short_codes_map_to_canonical_bcp47():
    assert normalize_locale("en") == "en-US"
    assert normalize_locale("FR") == "fr-FR"


def test_regional_codes_pass_through_with_normalized_casing():
    assert normalize_locale("en-CA") == "en-CA"
    assert normalize_locale("fr-ca") == "fr-CA"
    assert normalize_locale("en-US") == "en-US"


def test_unrecognized_value_passes_through_unchanged():
    assert normalize_locale("Klingon") == "Klingon"


def test_empty_or_blank_returns_as_is():
    assert normalize_locale("") == ""
    assert normalize_locale("   ") == ""
