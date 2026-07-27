"""Canonical locale normalization — single source of truth.

Brief extraction (LLM or regex fallback) can hand back a locale in any of
several shapes depending on how the user phrased it or how the model echoed
it back: a full BCP-47 tag ("en-US"), a bare short code ("en"), a regional
variant ("en-CA"), or a plain language name ("English"). Every downstream
consumer (RAG retrieval, translation's SUPPORTED_LOCALES gate, channel
prompts) needs a consistent form to compare against — normalizing once here,
at brief-capture time, means no consumer has to guess at the caller's
phrasing. See next_tasks.md 2026-07-26 (campaign 019f9ee0-6bb1-7ec2-
bc6d-2bdb877f6b4f: brief.locales came back as literally ["English", "French"],
which matched nothing anywhere downstream).
"""
from __future__ import annotations

_LANGUAGE_NAME_TO_LOCALE: dict[str, str] = {
    "english": "en-US",
    "french": "fr-FR",
    "spanish": "es-ES",
    "german": "de-DE",
    "hindi": "hi-IN",
    "italian": "it-IT",
    "portuguese": "pt-PT",
    "japanese": "ja-JP",
    "korean": "ko-KR",
    "chinese": "zh-CN",
    "mandarin": "zh-CN",
    "dutch": "nl-NL",
}

_SHORT_CODE_TO_LOCALE: dict[str, str] = {
    "en": "en-US",
    "fr": "fr-FR",
    "es": "es-ES",
    "de": "de-DE",
    "it": "it-IT",
    "pt": "pt-PT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh": "zh-CN",
    "nl": "nl-NL",
    "hi": "hi-IN",
}


def normalize_locale(value: str) -> str:
    """Best-effort normalization to a canonical "xx-XX" BCP-47 tag.

    Returns the input unchanged (stripped) if it doesn't match a known
    language name or short code and isn't already hyphenated — better to
    pass through something unrecognized than silently mangle it.
    """
    raw = (value or "").strip()
    if not raw:
        return raw

    lowered = raw.lower()
    if lowered in _LANGUAGE_NAME_TO_LOCALE:
        return _LANGUAGE_NAME_TO_LOCALE[lowered]

    if "-" in raw:
        lang, _, region = raw.partition("-")
        return f"{lang.lower()}-{region.upper()}" if region else raw

    return _SHORT_CODE_TO_LOCALE.get(lowered, raw)


def base_locale(locale: str | None) -> str:
    """Strip a region suffix and lowercase: "en-US" -> "en", "fr-CA" -> "fr"."""
    return (locale or "").split("-")[0].strip().lower()


# The brief's source-of-truth language — content is generated in this locale
# first, then translation_agent fans out to every other requested locale.
# translation_agent skips this one entirely (nothing to translate).
SOURCE_LOCALE_BASE = "en"

# Full-tag form of the above — content_generator's task fan-out is
# channel x segment ONLY (2026-07-27 fix: locale used to be part of the
# generation task itself, which meant content_generator's prompt received
# "Locale: fr-FR" and had no instruction to write in English anyway, so it
# just wrote the content directly in French — defeating the whole point of
# having a separate translation_agent). Every generation/personalization
# task now always targets this one fixed locale; translation_agent is the
# only place locale fan-out happens, expanding one English master into one
# variant per requested locale.
SOURCE_LOCALE = "en-US"

# Short (base_locale-form) codes translation_agent can actually translate
# into today (see pipeline/agents/translation.py's HF/quality-gate setup).
# Shared here — not just by translation_agent — so intake_agent can reject
# unsupported locales *before* spending generation/personalization cost on
# tasks that were always going to fail at the translation gate. See
# next_tasks.md 2026-07-26 ("these things need to be checked before we
# start the actual job" — content was generated + personalized for an
# unsupported locale, then discovered unsupported only at translation).
SUPPORTED_LOCALES: set[str] = {"es", "fr", "de", "hi"}


def is_locale_supported(locale: str | None) -> bool:
    """True if content can actually be produced for this locale — either it's
    the source locale (no translation needed) or translation_agent supports
    translating into it."""
    base = base_locale(locale)
    return base == SOURCE_LOCALE_BASE or base in SUPPORTED_LOCALES
