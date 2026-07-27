"""Intake Agent — first node in the OmniBrand pipeline.

Turns a raw campaign brief into a validated CampaignBrief and a fan-out
list[GenerationTask] for content_generator to execute against. Mostly pure
validation + planning (token_cost_usd = 0.0), EXCEPT for one conditional LLM
call: the brand-truthfulness check (see _check_brand_truthfulness below),
which only fires when the brand actually has a profile configured.
"""
from __future__ import annotations

from itertools import product
import json
import re

import structlog
from sqlalchemy import text

from core.database import get_db
from pipeline.agents.base import publish_campaign_event, safe_agent_run, traced_llm_call
from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS
from pipeline.intake_validation import check_budget, screen_for_injection
from pipeline.locale_utils import (
    SOURCE_LOCALE,
    SOURCE_LOCALE_BASE,
    SUPPORTED_LOCALES,
    base_locale,
    is_locale_supported,
)
from services.rag import get_retriever
from pipeline.state import CampaignBrief, GenerationTask, OmniBrandState

log = structlog.get_logger()


async def _load_brand_profile(brand_id: str | None) -> dict:
    """brands.config — an empty JSONB blob until item 42's admin config UI
    started writing to it (2026-07-27). Missing keys all fall back to
    permissive defaults below, so brands with no profile configured yet
    (e.g. the seeded demo brand) are completely unaffected. Fails open (same
    as the RAG retrieval lookup below) — a DB hiccup here must never block
    an otherwise-valid campaign, just skip brand-specific entitlement."""
    if not brand_id:
        return {}
    try:
        async with get_db() as conn:
            result = await conn.execute(
                text("SELECT config FROM brands WHERE id = :brand_id"),
                {"brand_id": brand_id},
            )
            row = result.mappings().first()
            return dict(row["config"] or {}) if row and row["config"] else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("intake_brand_profile_load_failed", brand_id=brand_id, error=str(exc))
        return {}


async def _check_brand_truthfulness(
    *, objective: str, key_messages: list[str], industry: str, key_claims: list[str], state: OmniBrandState
) -> tuple[bool, str, float]:
    """One cheap LLM call comparing the brief against the brand's own
    profile — the actual fix for a real recurring bug: briefs that don't
    match what the brand does were previously only caught by judges AFTER
    a full generate/personalize/translate cycle already spent real money
    (see next_tasks.md items 14/22, found live twice). Fails OPEN on any
    parse/call error — a flaky check must never block a legitimate
    campaign, only a confidently-detected mismatch should."""
    model = state.get("model_aliases", {}).get("brand_truthfulness", "eval-model")
    prompt = (
        f"Brand industry: {industry or 'unspecified'}\n"
        f"Brand's known claims/offerings: {'; '.join(key_claims) or 'none listed'}\n\n"
        f"Campaign brief objective: {objective}\n"
        f"Campaign brief key messages: {'; '.join(key_messages) or 'none'}\n\n"
        "Does this brief plausibly belong to this brand, given its industry and "
        "known claims? Answer strict JSON only, no prose: "
        '{"plausible": true or false, "reason": "one short sentence"}'
    )
    content, usage = await traced_llm_call(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        task="intake_brand_truthfulness",
        state=state,
        temperature=0,
    )
    cost = float(usage.get("cost", 0.0))
    try:
        parsed = json.loads(content)
        return bool(parsed.get("plausible", True)), str(parsed.get("reason", "")), cost
    except Exception:  # noqa: BLE001
        return True, "", cost


def _version_key(version: str) -> tuple[int, str]:
    match = re.search(r"(\d+)", version)
    if match:
        return (int(match.group(1)), version)
    return (0, version)


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------


async def intake_agent(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        errors: list[str] = []
        brief_valid = True

        raw_brief: dict = state.get("brief") or {}  # type: ignore[assignment]

        # ------------------------------------------------------------------
        # 1. Injection screening (fail-closed)
        # ------------------------------------------------------------------
        raw_text: str = raw_brief.get("raw_text", "") or ""
        key_messages: list[str] = raw_brief.get("key_messages", []) or []
        # Previously only raw_text/key_messages were screened — an injection
        # attempt placed directly in objective/target_audience/tone_override
        # (rather than in free text) never got screened at all. See
        # next_tasks.md 2026-07-26 item 22.
        objective_text: str = raw_brief.get("objective", "") or ""
        target_audience_text: str = raw_brief.get("target_audience", "") or ""
        tone_override_text: str = raw_brief.get("tone_override", "") or ""
        texts_to_screen = [
            raw_text,
            objective_text,
            target_audience_text,
            tone_override_text,
        ] + key_messages
        injection_hits = screen_for_injection(texts_to_screen)
        if injection_hits:
            brief_valid = False
            errors.extend(injection_hits)
            log.warning(
                "intake_injection_detected",
                campaign_id=state.get("campaign_id"),
                hits=injection_hits,
            )

        # ------------------------------------------------------------------
        # 2. Field validation
        # ------------------------------------------------------------------
        channels: list[str] = raw_brief.get("channels", []) or []
        locales: list[str] = raw_brief.get("locales", []) or []
        audience_segments: list[str] = raw_brief.get("audience_segments", []) or []
        token_budget: int = raw_brief.get("token_budget", 0) or 0

        if not channels:
            brief_valid = False
            errors.append("brief.channels must be non-empty")
        if not locales:
            brief_valid = False
            errors.append("brief.locales must be non-empty")
        if not audience_segments:
            brief_valid = False
            errors.append("brief.audience_segments must be non-empty")
        if token_budget <= 0:
            brief_valid = False
            errors.append("brief.token_budget must be > 0")

        # ------------------------------------------------------------------
        # 2b. Brand entitlement — channel/locale allow-lists + truthfulness
        # ------------------------------------------------------------------
        # brands.config is an empty JSONB blob until a brand is configured via
        # the admin panel (item 42, 2026-07-27) — an unconfigured brand falls
        # back to every globally-supported channel, so nothing changes for
        # brands (like the seeded demo brand) that haven't set this up yet.
        brand_config = await _load_brand_profile(state.get("brand_id"))
        allowed_channels = brand_config.get("channels") or list(DEFAULT_CHANNEL_CONSTRAINTS.keys())
        allowed_channels_set = {str(c).strip().lower() for c in allowed_channels}
        unsupported_channels = sorted(
            {c.strip().lower() for c in channels if c.strip().lower() not in allowed_channels_set}
        )
        if unsupported_channels:
            brief_valid = False
            errors.append(f"channel(s) not supported for this brand: {unsupported_channels}")

        truthfulness_cost = 0.0
        industry = str(brand_config.get("industry") or "").strip()
        key_claims = [str(c) for c in (brand_config.get("key_claims") or [])]
        if brief_valid and (industry or key_claims):
            plausible, reason, truthfulness_cost = await _check_brand_truthfulness(
                objective=raw_brief.get("objective", "") or "",
                key_messages=key_messages,
                industry=industry,
                key_claims=key_claims,
                state=state,
            )
            if not plausible:
                brief_valid = False
                errors.append(f"brief doesn't match this brand's profile: {reason}" if reason else "brief doesn't match this brand's profile")

        # ------------------------------------------------------------------
        # 3. Build CampaignBrief
        # ------------------------------------------------------------------
        campaign_brief: CampaignBrief | None = None
        if brief_valid:
            campaign_brief = CampaignBrief(
                objective=raw_brief.get("objective", ""),
                target_audience=raw_brief.get("target_audience", ""),
                key_messages=key_messages,
                tone_override=raw_brief.get("tone_override"),
                channels=channels,
                locales=locales,
                audience_segments=audience_segments,
                token_budget=token_budget,
                end_date=raw_brief.get("end_date"),
                raw_text=raw_text,
            )

        # ------------------------------------------------------------------
        # 4. Budget check (deterministic, no LLM)
        # ------------------------------------------------------------------
        budget_ok = False
        if brief_valid and campaign_brief is not None:
            budget_errors = check_budget(token_budget, channels, locales, audience_segments)
            if budget_errors:
                errors.extend(budget_errors)
            else:
                budget_ok = True

        # ------------------------------------------------------------------
        # 5. RAG context / prior campaigns
        # ------------------------------------------------------------------
        rag_context = None
        prior_campaigns: list = []
        if brief_valid and budget_ok and campaign_brief is not None:
            query = campaign_brief["objective"].strip() or campaign_brief["raw_text"].strip()
            if query:
                # Retrieve per requested locale and merge — rag_context is a
                # single shared object consumed by every downstream agent
                # (content_generator, judges) for every task regardless of
                # that task's own locale, so retrieving only locales[0]
                # meant every non-first locale was judged/generated against
                # the WRONG brand guidance (or none) for its own language.
                # See next_tasks.md 2026-07-26 item 22.
                merged_chunks: list[str] = []
                merged_section_types: list[str] = []
                merged_scores: list[float] = []
                all_versions: list[str] = []
                seen_chunks: set[str] = set()
                for loc in campaign_brief["locales"]:
                    try:
                        chunks = await get_retriever().retrieve(
                            query=query,
                            brand_id=state["brand_id"],
                            locale=loc,
                            n_results=5,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "intake_rag_context_failed",
                            campaign_id=state.get("campaign_id"),
                            brand_id=state.get("brand_id"),
                            locale=loc,
                            error=str(exc),
                        )
                        continue
                    for c in chunks:
                        if c.content in seen_chunks:
                            continue
                        seen_chunks.add(c.content)
                        merged_chunks.append(c.content)
                        if c.section_type:
                            merged_section_types.append(c.section_type)
                        merged_scores.append(float(c.score))
                        if c.version:
                            all_versions.append(c.version)

                if merged_chunks:
                    rag_context = {
                        "brand_guide_chunks": merged_chunks,
                        "section_types": merged_section_types,
                        "brand_guide_version": (
                            max(all_versions, key=_version_key) if all_versions else "unknown"
                        ),
                        "retrieval_scores": merged_scores,
                    }

        # ------------------------------------------------------------------
        # 6. Task fan-out (Cartesian product) — only if valid
        # ------------------------------------------------------------------
        # 2026-07-27: fan-out is channel x segment ONLY — locale is no longer
        # a generation-task dimension. content_generator/personalization_agent
        # always produce one English master per channel x segment;
        # translation_agent is the sole place per-locale variants get created,
        # fanning that one master out into one variant per requested locale.
        # (Previously locale was baked into the task from here, which meant
        # content_generator's own prompt received "Locale: fr-FR" — with no
        # instruction anywhere to write in English regardless — so it just
        # wrote the content directly in French, defeating translation_agent
        # entirely. See next_tasks.md 2026-07-27.)
        tasks: list[GenerationTask] = []
        # Still validated/reported here, before any generation cost is spent,
        # even though generation itself no longer depends on locale — early
        # user-facing feedback that a requested locale can't be produced.
        fan_out_locales: list[str] = []
        if campaign_brief is not None:
            fan_out_locales = [
                loc for loc in campaign_brief["locales"] if is_locale_supported(loc)
            ]
            unsupported_locales = [
                loc for loc in campaign_brief["locales"] if not is_locale_supported(loc)
            ]
            for loc in unsupported_locales:
                errors.append(
                    f"locale '{loc}' is not supported for translation "
                    f"(supported: source locale + {sorted(SUPPORTED_LOCALES)}) — "
                    "will be skipped by translation_agent"
                )

            # Brand-level locale entitlement (item 42) — separate from the
            # global translation-support check above: a locale can be
            # globally supported but still not entitled for THIS brand. Hard
            # failure, same treatment as the channel entitlement check,
            # since generating for a non-entitled locale is exactly the kind
            # of spend this check exists to prevent.
            brand_allowed_locales = brand_config.get("locales")
            if brand_allowed_locales:
                allowed_locale_set = {SOURCE_LOCALE} | {str(loc) for loc in brand_allowed_locales}
                not_entitled = sorted(
                    {loc for loc in campaign_brief["locales"] if loc not in allowed_locale_set}
                )
                if not_entitled:
                    brief_valid = False
                    errors.append(f"locale(s) not entitled for this brand: {not_entitled}")

        if brief_valid and budget_ok and campaign_brief is not None:
            for raw_channel, segment in product(
                campaign_brief["channels"],
                campaign_brief["audience_segments"],
            ):
                # Brief extraction echoes back whatever casing the user typed
                # ("SMS", "Email", ...), but DEFAULT_CHANNEL_CONSTRAINTS keys
                # (channel_prompts.py) are all lowercase — an unnormalized
                # channel raised an unhandled KeyError deep in
                # render_channel_prompt and (before content_generator gained
                # per-task isolation) crashed generation for the entire
                # campaign, not just that channel. Normalizing once here,
                # same pattern as the locale fix in retriever.py.
                channel = raw_channel.strip().lower()
                tasks.append(
                    GenerationTask(
                        task_id=f"{channel}_{segment}",
                        channel=channel,
                        segment=segment,
                        channel_constraints={},  # no channel-rules source on this branch
                    )
                )

        log.info(
            "intake_complete",
            campaign_id=state.get("campaign_id"),
            brief_valid=brief_valid,
            budget_ok=budget_ok,
            task_count=len(tasks),
            errors=errors,
        )

        # Full intended DELIVERABLE matrix (channel x segment x locale) for the
        # frontend plan panel — deliberately separate from `tasks` above
        # (channel x segment only, what actually drives generation). task_id
        # here matches what translation_agent will eventually produce for
        # each locale, so the plan panel's rows line up with the real
        # per-task status events translation_agent publishes later.
        planned_deliverables = [
            {
                "task_id": t["task_id"] if base_locale(locale) == SOURCE_LOCALE_BASE
                else f"{t['task_id']}_{base_locale(locale)}",
                "locale": locale,
                "channel": t["channel"],
                "segment": t["segment"],
            }
            for t in tasks
            for locale in (fan_out_locales or [SOURCE_LOCALE])
        ]

        await publish_campaign_event(
            campaign_id=state.get("campaign_id"),
            agent="intake_agent",
            phase="intake_complete",
            payload={
                "brief_valid": brief_valid,
                "budget_ok": budget_ok,
                "task_count": len(planned_deliverables),
                # Full deliverable list (not just the count) so the frontend
                # can render one plan row per task_id up front, before any
                # content exists — see next_tasks.md "inline campaign plan"
                # (2026-07-26).
                "tasks": planned_deliverables,
            },
        )

        # ------------------------------------------------------------------
        # 7 & 8. Phase marker + cost
        # ------------------------------------------------------------------
        return {
            "brief": campaign_brief,
            "brief_valid": brief_valid,
            "brief_validation_errors": errors,
            "budget_check_passed": budget_ok,
            "rag_context": rag_context,
            "prior_campaigns": prior_campaigns,
            "tasks": tasks if (brief_valid and budget_ok) else [],
            "current_phase": "intake_complete",
            "token_cost_usd": truthfulness_cost,
        }

    return await safe_agent_run(_impl, state)
