"""T4 — Personalization agent (capstone: OmniBrand Studio, Team 13).

Conditions each generated content variant on its target audience segment —
adjusting tone, CTA style, and reading level for the persona — and writes the
result into ``variant["personalized_content"]``.

Subtasks (per the capstone task sheet):
  T4.1  Segment loading   — persona voice profiles from brand guidelines / org_config
  T4.2  PII scan          — redact PII from text before prompt construction
  T4.3  Personalization   — traced_llm_call() conditioned on the segment profile
  T4.4  Write + tests      — variants[].personalized_content; enterprise ≠ consumer

Write permissions (AGENT_WRITE_PERMISSIONS["personalization_agent"]):
    {"variants", "token_cost_usd", "errors"}

Enrichment model: ``variants`` uses the ``merge_variants`` reducer (upsert by
``task_id``). The same variant accumulates generated_content →
personalized_content → translated_content across stages. This agent fills
``personalized_content`` and **returns** the enriched variants so the write
persists through the checkpointer (a node's in-place mutation of a checkpointed
channel is discarded — it must return its updates).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

from pipeline.agents.base import publish_campaign_event, safe_agent_run, traced_llm_call
from pipeline.state import OmniBrandState

try:
    # Same channel constraints the content generator (T3) uses — so a persona
    # rewrite stays within the channel's char limit and keeps required elements.
    from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS
except Exception:  # module may be absent on some branches — degrade gracefully
    DEFAULT_CHANNEL_CONSTRAINTS = {}

# Shared constraint checker + retry budget — the same validation the Content
# Generator (T3) applies, so a persona rewrite is held to the channel's char
# limit and required elements before it is accepted (doc §4.4.3).
from pipeline.agents.content_generator import MAX_RETRIES, _check_constraints

log = structlog.get_logger()


# ── T4.1 Segment profiles ─────────────────────────────────────────────────
# The real personas come from the data track's K-Means output, expressed as
# brand-guideline files: tone_voice_per_persona.json (voice) + cta_library.json
# (CTA). The agent loads them as its default persona profiles. A campaign can
# still override any of them via org_config["segment_profiles"] (e.g. from RAG).
_BRAND_GUIDELINES_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "datasets" / "processed" / "brand_guidelines"
)

# Minimal placeholder profiles, used only if the brand-guideline files are absent.
_FALLBACK_PROFILES: dict[str, dict[str, str]] = {
    "enterprise": {
        "reading_level": "Grade 12",
        "tone": "formal, authoritative",
        "cta_style": "consultative",
    },
    "sme": {"reading_level": "Grade 10", "tone": "clear, pragmatic", "cta_style": "direct"},
    "consumer": {"reading_level": "Grade 8", "tone": "accessible, friendly", "cta_style": "punchy"},
}

# Used when a variant's segment isn't found in the loaded profiles.
_FALLBACK_PROFILE = {
    "tone": "clear, friendly, brand-appropriate",
    "reading_level": "general",
    "cta_style": "a clear call to action",
}


def _load_brand_personas() -> dict[str, dict[str, str]]:
    """Load real persona voice profiles from the brand-guideline files.

    Combines tone_voice_per_persona.json (tone, language style, sentence length)
    with cta_library.json (call-to-action) into one profile per persona:
    ``{tone, reading_level, cta_style}``. Returns {} if the files are unavailable,
    in which case the caller falls back to ``_FALLBACK_PROFILES``."""
    try:
        tone_voice = json.loads(
            (_BRAND_GUIDELINES_DIR / "tone_voice_per_persona.json").read_text(encoding="utf-8")
        )
        cta_lib = json.loads(
            (_BRAND_GUIDELINES_DIR / "cta_library.json").read_text(encoding="utf-8")
        )
    except Exception as exc:  # missing/unreadable files — degrade gracefully
        log.warning("brand_persona_files_unavailable", error=str(exc))
        return {}

    profiles: dict[str, dict[str, str]] = {}
    for persona, tv in tone_voice.items():
        cta_entry = cta_lib.get(persona, {})
        primary_cta = (cta_entry.get("primary_ctas") or ["a clear call to action"])[0]
        tone = f"{tv.get('tone', '')} | style: {tv.get('language_style', '')}".strip(" |")
        profiles[persona] = {
            "tone": tone,
            "reading_level": tv.get("sentence_length", "general"),
            "cta_style": primary_cta,
        }
    return profiles


# Real personas from the brand guidelines; placeholders only if files are absent.
DEFAULT_SEGMENT_PROFILES: dict[str, dict[str, str]] = _load_brand_personas() or _FALLBACK_PROFILES


def load_segment_profiles(org_config: dict) -> dict[str, dict[str, str]]:
    """T4.1 — merge org-supplied segment profiles over the loaded defaults."""
    profiles = {k: dict(v) for k, v in DEFAULT_SEGMENT_PROFILES.items()}
    for segment, overrides in (org_config or {}).get("segment_profiles", {}).items():
        profiles.setdefault(segment, {}).update(overrides)
    return profiles


def _normalize(text: str) -> str:
    """Lowercase and collapse non-alphanumerics to spaces for loose matching."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def resolve_segment_profile(
    segment: str | None,
    profiles: dict[str, dict[str, str]],
    aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    """T4.1 — resolve a variant's raw ``segment`` label to a persona profile.

    Upstream sets ``variant['segment']`` from the brief's free-text
    ``audience_segments`` (see intake.py), which rarely equals a persona name
    verbatim — so an exact-key lookup alone would drop almost every real brief
    to the generic fallback. Resolve in tiers, using the generic fallback only
    when nothing plausibly matches:

      1. exact key                        4. token overlap with a persona name
      2. explicit alias map (org_config)  5. generic fallback
      3. case-insensitive / normalized exact

    The chosen profile is always merged over ``_FALLBACK_PROFILE`` so ``tone``,
    ``reading_level`` and ``cta_style`` are guaranteed present — a partial
    org_config override can never raise ``KeyError`` in the prompt builder.
    """
    def _finish(prof: dict[str, str]) -> dict[str, str]:
        return {**_FALLBACK_PROFILE, **prof}

    if not segment:
        return dict(_FALLBACK_PROFILE)
    if segment in profiles:  # 1. exact
        return _finish(profiles[segment])
    aliased = (aliases or {}).get(segment)
    if aliased and aliased in profiles:  # 2. explicit alias
        return _finish(profiles[aliased])
    norm = _normalize(segment)
    for name, prof in profiles.items():  # 3. normalized exact
        if _normalize(name) == norm:
            return _finish(prof)
    seg_tokens = {t for t in norm.split() if len(t) > 2}  # 4. token overlap
    best_name, best_score = None, 0
    for name in profiles:
        score = len(seg_tokens & set(_normalize(name).split()))
        if score > best_score:
            best_name, best_score = name, score
    if best_name is not None:
        return _finish(profiles[best_name])
    return dict(_FALLBACK_PROFILE)  # 5. generic fallback


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
        segment_aliases = (state.get("org_config") or {}).get("segment_aliases", {})
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
        enriched: list = []  # variants we touched — returned so the write persists
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

            # T4.1 — resolve the raw segment label to the closest persona
            # profile (exact → alias → normalized → token overlap → generic),
            # so real briefs still receive persona conditioning.
            profile = resolve_segment_profile(
                variant.get("segment"), profiles, segment_aliases
            )
            channel = variant.get("channel") or "generic"
            constraints = {
                **DEFAULT_CHANNEL_CONSTRAINTS.get(channel, {}),
                **(variant.get("channel_constraints") or {}),
            }

            # T4.3 — segment-conditioned LLM call, validated against the same
            # channel constraints the Content Generator enforces. Retry with
            # violation feedback up to MAX_RETRIES; on persistent failure leave
            # personalized_content=None so downstream falls back to the original.
            messages = _build_messages(profile, channel, clean_source)
            content = ""
            violations: list[str] = []
            for attempt in range(MAX_RETRIES + 1):
                content, usage = await traced_llm_call(
                    model=model,
                    messages=messages,
                    task="personalization_agent",
                    state=state,
                    agent="personalization_agent",
                )
                total_cost += usage.get("cost", 0.0)
                violations = (
                    _check_constraints(content, constraints)
                    if content and content.strip()
                    else ["empty personalization output"]
                )
                if not violations or attempt == MAX_RETRIES:
                    break
                guidance = "\n".join(f"- {v}" for v in violations)
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"Your rewrite had these issues:\n{guidance}\n\n"
                            f"Regenerate the full {channel} content, fixing every "
                            "issue while keeping the persona tone and CTA style."
                        ),
                    },
                ]

            # T4.4 — enrich the variant, then RETURN it (see merge_variants):
            # a checkpointed graph drops in-place mutations, so the enrichment
            # only persists because we hand the variant back below.
            if violations:
                # Persistent constraint failure: keep the original as fallback
                # (status stays "generated" → downstream reads generated_content).
                variant["personalized_content"] = None
                log.warning(
                    "personalization_validation_failed",
                    agent="personalization_agent",
                    campaign_id=state.get("campaign_id"),
                    task_id=variant.get("task_id"),
                    violations=violations,
                )
                enriched.append(variant)
                continue
            variant["personalized_content"] = content
            variant["status"] = "personalized"
            personalized += 1
            enriched.append(variant)

        log.info(
            "agent_complete",
            agent="personalization_agent",
            campaign_id=state.get("campaign_id"),
            personalized=personalized,
        )
        await publish_campaign_event(
            campaign_id=state.get("campaign_id"),
            agent="personalization_agent",
            phase="personalization_complete",
            payload={
                "personalized": personalized,
            },
        )
        result: dict = {"token_cost_usd": total_cost}
        if enriched:
            result["variants"] = enriched
        return result

    return await safe_agent_run(_impl, state)
