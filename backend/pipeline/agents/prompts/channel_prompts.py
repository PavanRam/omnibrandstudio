from __future__ import annotations

PROMPT_VERSION = "v1.0.0"

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
    "instead (e.g. 'reduce costs', 'work faster') — never attach a made-up figure."
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
    "auto-rejected. Prefer qualitative benefit language when you have no sourced figure."
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
