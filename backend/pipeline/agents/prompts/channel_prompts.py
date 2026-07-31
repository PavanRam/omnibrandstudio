from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger()

PROMPT_VERSION = "v1.0.0"

# Persona-specific CTA phrases, loaded once from the same brand-guideline file
# personalization.py already reads. Content generation previously only had a
# generic per-CHANNEL cta_pattern example below (not persona-aware), which
# competed with whatever the RAG-retrieved brand guide excerpt said for that
# persona — a real contributor to judges' CTA critical_violations. Grounding
# the system prompt itself in the exact brand-guide phrase removes that
# ambiguity for every campaign matching a known persona, not just ones whose
# brief happens to spell out the CTA in its key_messages.
_CTA_LIBRARY_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "datasets"
    / "processed"
    / "brand_guidelines"
    / "cta_library.json"
)


def _load_cta_library() -> dict:
    try:
        return json.loads(_CTA_LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # missing/unreadable file — degrade gracefully
        log.warning("cta_library_unavailable", error=str(exc))
        return {}


CTA_LIBRARY: dict = _load_cta_library()

# cta_library.json's channel_specific keys only cover Email/Instagram/Facebook/
# Web/Catalog/Store — these pipeline channels have no dedicated brand-guide
# entry, so each persona's closest-fit CTA is hand-picked here, mirroring
# docs/sample-campaign-briefs.md's per-persona "CTA guidance" notes exactly.
_CHANNEL_TO_CTA_KEY = {"email": "Email", "instagram": "Instagram", "facebook": "Facebook"}
_CTA_CHANNEL_FALLBACK: dict[str, dict[str, str]] = {
    "High-Income Store Spender": {"linkedin": "View Exclusive Pieces"},
    "Budget-Conscious Low Spender": {"sms": "Find Your Savings"},
    "Web-Savvy Mid-Tier Buyer": {"twitter": "See What's New"},
    "Deal-Seeking Value Hunter": {"sms": "Grab This Deal", "whatsapp": "Unlock Your Offer"},
    "Highly Engaged Campaign Responder": {"linkedin": "See What We've Saved for You"},
}


def persona_channel_cta(segment: str, channel: str) -> str | None:
    """Exact brand-guide CTA phrase for this persona+channel, or ``None`` if
    the segment isn't a known persona (falls back to the generic per-channel
    ``cta_pattern`` in ``DEFAULT_CHANNEL_CONSTRAINTS``)."""
    entry = CTA_LIBRARY.get(segment)
    if not entry:
        return None
    cta_key = _CHANNEL_TO_CTA_KEY.get(channel)
    if cta_key:
        exact = (entry.get("channel_specific") or {}).get(cta_key)
        if exact:
            return exact
    fallback = _CTA_CHANNEL_FALLBACK.get(segment, {}).get(channel)
    if fallback:
        return fallback
    primary = entry.get("primary_ctas") or []
    return primary[0] if primary else None

# Seeded here in-code. In the full system this should move to the DB-backed
# prompt_registry (see services/prompt_service.py) — render_channel_prompt()
# below has the same "name/variables in, OpenAI messages out" shape as
# PromptService.render(), so swapping the backing store is a one-file change.
DEFAULT_CHANNEL_CONSTRAINTS: dict[str, dict[str, object]] = {
    "linkedin": {
        "char_limit": 3000,
        "required_elements": ["cta"],
        "cta_pattern": "a professional CTA, e.g. 'Learn more at {link}' or 'Book a demo'",
    },
    "email": {
        "char_limit": 2000,
        "required_elements": ["subject_line", "cta"],
        "cta_pattern": "a single clear CTA button text plus URL, e.g. 'Get started -> {link}'",
    },
    "instagram": {
        "char_limit": 2200,
        "required_elements": ["hashtag"],
        "cta_pattern": "a short CTA followed by relevant hashtags",
    },
    "facebook": {
        "char_limit": 3000,
        "required_elements": ["cta"],
        "cta_pattern": "a conversational CTA inviting comments or shares",
    },
    "twitter": {
        "char_limit": 280,
        "required_elements": [],
        "cta_pattern": "a concise CTA with a link, fitting the character limit",
    },
    "whatsapp": {
        "char_limit": 1024,
        "required_elements": [],
        "cta_pattern": "a direct, personal CTA, e.g. 'Reply YES to claim your offer'",
    },
    "sms": {
        "char_limit": 160,
        "required_elements": [],
        "cta_pattern": "a short, direct CTA with a link, e.g. 'Click here: {link} Reply STOP to opt out'",
    },
}

_SYSTEM_TEMPLATE = (
    "You are a brand content writer for {brand_name}. Tone: {tone_profile}. "
    "Always write this content in English, regardless of the Locale shown "
    "below — translation into other languages happens in a separate step, "
    "never here.\n"
    "Channel: {channel}. Hard character limit: {char_limit}. "
    "Required elements: {required_elements}. "
    "Never use these prohibited words or phrases: {prohibited_vocab}. "
    "Call-to-action style: {cta_pattern}.\n\n"
    "CRITICAL FORMATTING RULES:\n"
    "- If 'subject_line' is required: Include a line that starts with 'Subject:' or 'Subject Line:'\n"
    "- If 'cta' (call-to-action) is required: Include action verbs like 'Click', 'Learn more', 'Get started', 'Book a demo', 'Discover', 'Join', etc.\n"
    "- If 'hashtag' is required: Include hashtags prefixed with # (e.g., #SustainableInnovation)\n"
    "Ensure ALL required elements are present in your output.\n\n"
    "HARD CONSTRAINT — CHARACTER LIMIT:\n"
    "Your entire output MUST be at most {char_limit} characters. Count carefully. "
    "Do NOT include preamble, notes, or commentary — return the content only. "
    "If you approach the limit, trim, but never drop a required element.\n\n"
    "LOCALE & CULTURAL REGISTER:\n"
    "The locale for this content is {{locale}}. "
    "For non-English locales (anything other than en-US / en-GB), adapt idioms, units, "
    "date formats, and cultural references to be natural for that market. "
    "For formal markets (e.g. de-DE, fr-FR) use the formal register (Sie/vous). "
    "Do not simply translate English idioms literally.\n\n"
    "GROUNDING — NO INVENTED CLAIMS:\n"
    "Only include claims, statistics, product features, or offers that are explicitly "
    "present in the campaign objective, key messages, or brand guide excerpts below. "
    "Do not invent discounts, deadlines, URLs, or endorsements.\n"
    "ABSOLUTELY NO FABRICATED NUMBERS: never invent quantified performance claims — "
    "no percentages, multipliers, dollar amounts, time savings, ratings, user counts, "
    "or ROI figures (e.g. 'cut costs by 30%', 'boost speed by 25%', '10x faster', "
    "'trusted by 5,000 teams') unless that exact figure appears verbatim in the brief "
    "or brand guide excerpts. Unsubstantiated statistics are treated as factual "
    "fabrication and will cause the content to be auto-rejected by the compliance "
    "judges. When you have no sourced number, describe the benefit qualitatively "
    "instead (e.g. 'reduce costs', 'work faster') — never attach a made-up figure.\n"
    "NO INVENTED PRODUCT ATTRIBUTES: never invent product specifics — aging or vintage "
    "periods (e.g. 'aged 12 months', 'vieilli 12 mois'), scarcity or availability status "
    "(e.g. 'limited edition', 'édition limitée', 'only 100 left'), awards, certifications, "
    "origin/provenance, materials, or ingredients — unless that exact detail appears "
    "verbatim in the brief or brand guide excerpts. These are factual fabrication and are "
    "auto-rejected just like fabricated numbers. When a detail is not sourced, omit it "
    "rather than inventing one."
)

_USER_TEMPLATE = (
    "Campaign objective: {objective}\n"
    "Target audience: {target_audience}\n"
    "Key messages: {key_messages}\n"
    "Audience segment: {segment}\n"
    "Locale: {locale}\n\n"
    "Brand guide excerpts to follow (highest priority):\n{brand_guidance}\n\n"
    "Examples of strong past {channel} content for this brand:\n{few_shot_examples}\n\n"
    "Write one new {channel} post that follows the system instructions exactly.\n"
    "Ensure the output includes ALL required elements with proper formatting.\n"
    "Stay within {char_limit} characters — this is a HARD LIMIT, not a guideline.\n"
    "Only include claims and offers present in the brief above. Do not invent any.\n"
    "Do NOT attach any percentage, multiplier, dollar amount, or other statistic "
    "unless it appears verbatim in the brief or brand guide — fabricated numbers are "
    "auto-rejected. Prefer qualitative benefit language when you have no sourced figure.\n"
    "Do NOT invent product attributes (aging/vintage period, 'limited edition' or other "
    "scarcity, awards, certifications, origin, materials, ingredients) unless stated in "
    "the brief or brand guide — omit the detail instead of inventing it."
)


def render_channel_prompt(channel: str, **variables: object) -> list[dict[str, str]]:
    """Renders the seeded system/user prompt pair for a channel into
    OpenAI-format messages. Raises KeyError for an unknown channel."""
    if channel not in DEFAULT_CHANNEL_CONSTRAINTS:
        raise KeyError(f"No prompt template seeded for channel '{channel}'")
    fmt_vars = {**variables, "channel": channel}
    return [
        {"role": "system", "content": _SYSTEM_TEMPLATE.format(**fmt_vars)},
        {"role": "user", "content": _USER_TEMPLATE.format(**fmt_vars)},
    ]
