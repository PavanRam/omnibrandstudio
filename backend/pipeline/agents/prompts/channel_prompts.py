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
}

_SYSTEM_TEMPLATE = (
    "You are a brand content writer for {brand_name}. Tone: {tone_profile}. "
    "Channel: {channel}. Hard character limit: {char_limit}. "
    "Required elements: {required_elements}. "
    "Never use these prohibited words or phrases: {prohibited_vocab}. "
    "Call-to-action style: {cta_pattern}."
)

_USER_TEMPLATE = (
    "Campaign objective: {objective}\n"
    "Target audience: {target_audience}\n"
    "Key messages: {key_messages}\n"
    "Audience segment: {segment}\n"
    "Locale: {locale}\n\n"
    "Examples of strong past {channel} content for this brand:\n{few_shot_examples}\n\n"
    "Write one new {channel} post that follows the system instructions exactly."
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
