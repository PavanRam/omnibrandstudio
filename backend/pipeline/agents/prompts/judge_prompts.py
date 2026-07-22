"""Canonical judge + reflexion prompt templates.

Single source of truth for the LLM-as-judge panel and the reflexion reviser.
The judges (``pipeline/agents/judges.py``) resolve their prompt from the DB
``prompt_registry`` first (name ``judge_panel`` / ``reflexion``) and fall back
to these templates when the registry has no active version — so the panel keeps
working whether or not ``scripts/seed_prompts.py`` has been run. The seed script
imports these same constants, so the DB copy and the code fallback never drift.

Structured output is enforced at call time via LiteLLM ``response_format`` +
defensive parsing in the judge; the prompt therefore describes the required JSON
shape in prose (no literal ``{`` braces — the templates are ``str.format``-ed,
so only the named placeholders below may appear unescaped).

Placeholders:
    system: ``{rubric}`` ``{channel}`` ``{locale}``
    user:   ``{brand_guide}`` ``{content}``
"""
from __future__ import annotations

# Six subjective, brand-relative criteria that survive to the LLM panel
# (objective dimensions are handled by deterministic checks upstream). Weights
# sum to 1.0 and are applied by the aggregator, not the judge.
CRITERIA: tuple[str, ...] = (
    "tone_alignment",
    "vocabulary_compliance",
    "channel_format_adherence",
    "cta_style",
    "cultural_appropriateness",
    "factual_grounding",
)

CRITERION_WEIGHTS: dict[str, float] = {
    "tone_alignment": 0.20,
    "vocabulary_compliance": 0.20,
    "channel_format_adherence": 0.15,
    "cta_style": 0.10,
    "cultural_appropriateness": 0.10,
    "factual_grounding": 0.25,
}

RUBRIC_TEXT = (
    "Score each criterion from 0 (severe failure) to 10 (exemplary):\n"
    "- tone_alignment: matches the brand's documented voice and register.\n"
    "- vocabulary_compliance: uses approved terms; avoids prohibited/off-brand wording.\n"
    "- channel_format_adherence: fits the channel's structure, length and required elements.\n"
    "- cta_style: the call-to-action matches the brand's CTA conventions.\n"
    "- cultural_appropriateness: appropriate and natural for the target locale/audience.\n"
    "- factual_grounding: every claim is supported by the brand guide; no fabrication.\n"
    "A critical_violation is any factual fabrication, compliance breach, or prohibited "
    "content that must block publication regardless of other scores."
)

JUDGE_SYSTEM_TEMPLATE = (
    "You are an impartial brand-compliance judge evaluating a SINGLE piece of "
    "marketing content for the {channel} channel, locale {locale}. Judge only "
    "the content provided against the brand guide provided — do not reward "
    "length or position. Be specific and cite the brand guide where possible.\n\n"
    "{rubric}\n\n"
    "Return ONLY a single JSON object (no prose, no markdown fences) with these keys:\n"
    "tone_alignment, vocabulary_compliance, channel_format_adherence, cta_style, "
    "cultural_appropriateness, factual_grounding — each an object with: "
    "score (number 0-10), reasoning (string), violations (array of strings), "
    "citations (array of strings). "
    "Also include: composite_score (number 0-10), critical_violations (array of "
    "strings), routing_decision (exactly one of: auto_approve, flag, auto_reject), "
    "and routing_explanation (string, at least 20 characters)."
)

JUDGE_USER_TEMPLATE = (
    "BRAND GUIDE (authoritative context):\n{brand_guide}\n\n"
    "CONTENT TO EVALUATE:\n{content}\n\n"
    "Evaluate the content now and return the JSON object."
)

REFLEXION_SYSTEM_TEMPLATE = (
    "You are a brand-content reviser. Rewrite the {channel} content for locale "
    "{locale} so it fixes the specific problems listed, while preserving the "
    "original intent, key messages and brand voice. Eliminate every critical "
    "violation. Return ONLY the revised content — no preamble, no explanation, "
    "no markdown fences."
)

REFLEXION_USER_TEMPLATE = (
    "ORIGINAL CONTENT:\n{content}\n\n"
    "PROBLEMS TO FIX:\n{reasons}\n\n"
    "CRITICAL VIOLATIONS (must be eliminated):\n{critical}\n\n"
    "Produce the corrected content now."
)


def build_judge_messages(
    *, brand_guide: str, channel: str, locale: str, content: str
) -> list[dict]:
    """Code fallback for judge prompts (used when the registry has no version).

    ``str.format`` only parses the template's own braces; brace characters that
    happen to appear inside ``content``/``brand_guide`` values are substituted
    literally and are therefore safe.
    """
    system = JUDGE_SYSTEM_TEMPLATE.format(rubric=RUBRIC_TEXT, channel=channel, locale=locale)
    user = JUDGE_USER_TEMPLATE.format(brand_guide=brand_guide, content=content)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_reflexion_messages(
    *,
    content: str,
    reasons: list[str],
    critical: list[str],
    channel: str,
    locale: str,
) -> list[dict]:
    """Code fallback for the reflexion reviser prompt."""
    reasons_text = "\n".join(f"- {r}" for r in reasons) or "- (no specific criterion feedback)"
    critical_text = "\n".join(f"- {c}" for c in critical) or "- (none)"
    system = REFLEXION_SYSTEM_TEMPLATE.format(channel=channel, locale=locale)
    user = REFLEXION_USER_TEMPLATE.format(
        content=content, reasons=reasons_text, critical=critical_text
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
