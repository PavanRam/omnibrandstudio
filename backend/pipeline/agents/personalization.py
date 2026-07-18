"""T4 — Personalization agent (capstone: OmniBrand Studio, Team 13).

Conditions each generated content variant on its target audience segment —
adjusting tone, CTA style, and reading level for the persona — and writes the
result into ``variant["personalized_content"]``.

Subtasks (per the capstone task sheet):
  T4.1  Segment loading   — enterprise / sme / consumer profiles from org_config
  T4.2  PII scan          — redact PII from text before prompt construction
  T4.3  Personalization   — traced_llm_call() conditioned on the segment profile
  T4.4  Write + tests      — variants[].personalized_content; enterprise ≠ consumer

Write permissions (AGENT_WRITE_PERMISSIONS["personalization_agent"]):
    {"variants", "token_cost_usd", "errors"}

Enrichment model: ``variants`` is an ``operator.add`` fan-in field, so a node
cannot *replace* the list without duplicating it. Following the CP2 contract
(the same variant accumulates generated_content → personalized_content →
translated_content), this agent enriches the existing variant dicts **in place**
and returns only ``token_cost_usd`` — it appends nothing new to ``variants``.
"""
from __future__ import annotations

import re

import structlog

from pipeline.agents.base import safe_agent_run, traced_llm_call
from pipeline.state import OmniBrandState

try:
    # Same channel constraints the content generator (T3) uses — so a persona
    # rewrite stays within the channel's char limit and keeps required elements.
    from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS
except Exception:  # module may be absent on some branches — degrade gracefully
    DEFAULT_CHANNEL_CONSTRAINTS = {}

log = structlog.get_logger()


# ── T4.1 Segment profiles ─────────────────────────────────────────────────
# Personas derived by the data track's K-Means clustering surface here as
# fixed, auditable profiles. The agent reads them from org_config and falls
# back to these defaults when a campaign does not override them.
DEFAULT_SEGMENT_PROFILES: dict[str, dict[str, str]] = {
    "enterprise": {
        "reading_level": "Grade 12",
        "tone": "formal, authoritative, ROI-focused",
        "cta_style": "consultative (e.g. 'Request a strategic briefing')",
    },
    "sme": {
        "reading_level": "Grade 10",
        "tone": "clear, pragmatic, benefit-led",
        "cta_style": "direct (e.g. 'Start your free trial')",
    },
    "consumer": {
        "reading_level": "Grade 8",
        "tone": "accessible, friendly, energetic",
        "cta_style": "punchy (e.g. 'Get started today')",
    },
}

# Used when a variant's segment is unknown — never guess a persona silently.
_FALLBACK_PROFILE = DEFAULT_SEGMENT_PROFILES["consumer"]


def load_segment_profiles(org_config: dict) -> dict[str, dict[str, str]]:
    """T4.1 — merge org-supplied segment profiles over the built-in defaults."""
    profiles = {k: dict(v) for k, v in DEFAULT_SEGMENT_PROFILES.items()}
    for segment, overrides in (org_config or {}).get("segment_profiles", {}).items():
        profiles.setdefault(segment, {}).update(overrides)
    return profiles


# ── T4.2 PII scan ─────────────────────────────────────────────────────────
# Regex-lite scrubber for this no-Docker eval branch. On `develop` this is
# replaced by Presidio AnalyzerEngine with audit logging (no audit layer here).
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}


def scrub_pii(text: str | None) -> tuple[str, list[str]]:
    """T4.2 — redact PII from ``text``; return (redacted_text, found_types)."""
    if not text:
        return text or "", []
    found: list[str] = []
    redacted = text
    # SSN / card before PHONE so digit runs are not partially eaten.
    for label in ("EMAIL", "SSN", "CREDIT_CARD", "PHONE"):
        pattern = _PII_PATTERNS[label]
        if pattern.search(redacted):
            found.append(label)
            redacted = pattern.sub(f"[REDACTED_{label}]", redacted)
    return redacted, found


def _build_messages(profile: dict[str, str], channel: str, content: str) -> list[dict]:
    """T4.3 — segment-conditioned prompt (tone, CTA, reading level) that also
    respects the channel's format constraints (char limit, required elements)."""
    constraints = DEFAULT_CHANNEL_CONSTRAINTS.get(channel, {})
    char_limit = constraints.get("char_limit")
    required = constraints.get("required_elements") or []

    system = (
        "You are a brand personalization specialist. Rewrite marketing content "
        "for a specific audience segment while preserving factual claims, offers, "
        "brand voice, and the channel's format. Return only the rewritten content "
        "— no preamble."
    )
    lines = [
        f"Rewrite the following {channel} content for the target audience segment.",
        f"- Tone: {profile['tone']}",
        f"- Reading level: {profile['reading_level']}",
        f"- Call-to-action style: {profile['cta_style']}",
    ]
    if char_limit:
        lines.append(f"- Stay within {char_limit} characters (hard limit).")
    if required:
        lines.append(f"- Keep these required elements: {', '.join(required)}.")
    user = "\n".join(lines) + f"\n\nContent:\n{content}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def personalization_agent(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        profiles = load_segment_profiles(state.get("org_config", {}))
        # Default to the free-tier model (gen-free / Llama via Groq), matching
        # content_generator — keeps the pipeline within the free-tier budget.
        # The team can override per campaign via model_aliases["personalization"].
        model = (
            state["model_aliases"].get("personalization")
            or state["model_aliases"].get("generation", "gen-free")
        )

        # T4.2 — scan the brief up front (structlog only on this branch).
        brief = state.get("brief") or {}
        _, brief_pii = scrub_pii(brief.get("raw_text") if isinstance(brief, dict) else None)
        if brief_pii:
            log.warning(
                "pii_detected_in_brief",
                agent="personalization_agent",
                campaign_id=state.get("campaign_id"),
                pii_types=brief_pii,
            )

        total_cost = 0.0
        personalized = 0
        for variant in state.get("variants", []):
            source = variant.get("generated_content")
            if not source or variant.get("status") == "personalized":
                continue

            # T4.2 — redact PII from content before it enters the prompt.
            clean_source, pii_types = scrub_pii(source)
            if pii_types:
                log.warning(
                    "pii_redacted_before_personalization",
                    agent="personalization_agent",
                    campaign_id=state.get("campaign_id"),
                    task_id=variant.get("task_id"),
                    pii_types=pii_types,
                )

            segment = variant.get("segment") or "consumer"
            profile = profiles.get(segment, _FALLBACK_PROFILE)
            channel = variant.get("channel") or "generic"

            # T4.3 — segment-conditioned LLM call.
            content, usage = await traced_llm_call(
                model=model,
                messages=_build_messages(profile, channel, clean_source),
                task="personalization_agent",
                state=state,
            )

            # T4.4 — enrich the variant in place (append-only reducer contract).
            variant["personalized_content"] = content
            variant["status"] = "personalized"
            total_cost += usage.get("cost", 0.0)
            personalized += 1

        log.info(
            "agent_complete",
            agent="personalization_agent",
            campaign_id=state.get("campaign_id"),
            personalized=personalized,
        )
        return {"token_cost_usd": total_cost}

    return await safe_agent_run(_impl, state)
