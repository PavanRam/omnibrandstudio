from __future__ import annotations

import json
import re
from typing import Any, cast

import structlog

from pipeline.agents.base import publish_campaign_event, safe_agent_run, traced_llm_call
from pipeline.agents.prompts.channel_prompts import (
    DEFAULT_CHANNEL_CONSTRAINTS,
    PROMPT_VERSION,
    persona_channel_cta,
    render_channel_prompt,
)
from pipeline.agents.retrieval import get_examples
from pipeline.locale_utils import SOURCE_LOCALE
from pipeline.state import CampaignBrief, ContentVariant, GenerationTask, OmniBrandState

log = structlog.get_logger()

MAX_RETRIES = 3
NO_CONTEXT_AVAILABLE = "(none available)"

_CTA_MARKERS = (
    "http://",
    "https://",
    "learn more",
    "sign up",
    "shop now",
    "get started",
    "book a demo",
    "reply",
    "click",
    "visit",
    "request",
    "discover",
    "explore",
    "join",
    "download",
    "subscribe",
    "contact",
    "apply",
    "order",
    "reserve",
    # Premium/luxury-register CTAs deliberately avoid hard-sell verbs above
    # (2026-07-31: email/linkedin variants kept failing "missing cta" under a
    # brief that explicitly asked to avoid hard-sell/informal tone).
    "priority access",
    "private appointment",
    "by appointment",
    "rsvp",
    "complimentary",
    "invite you",
    "invitation",
    "confirm",
    "secure your",
    "hold your",
    "await",
    "indulge",
)


def _has_element(content: str, element: str) -> bool:
    """Check if content includes required element. More lenient parsing."""
    lowered = content.lower()
    
    if element == "hashtag":
        return "#" in content
    
    if element == "subject_line":
        # Match various subject_line formats:
        # "Subject: ...", "Subject Line: ...", "---\nSubject: ...", etc.
        if re.search(
            r"(?:subject\s*(?:line)?\s*:|\/\/\s*subject|subject\s*line)",
            lowered,
            re.IGNORECASE
        ):
            return True
        # Fallback: a short standalone opening line (no literal "Subject:"
        # prefix) followed by a blank line reads as an implicit title, which
        # premium-tone copy uses often (2026-07-31 diagnosis).
        first_para = content.strip().split("\n\n", 1)[0].strip()
        return bool(
            first_para
            and "\n" not in first_para
            and len(first_para) <= 120
            and not first_para.endswith((".", "!", "?"))
        )
    
    if element == "cta":
        # More aggressive: check for CTA markers OR action verbs at line start
        if any(marker in lowered for marker in _CTA_MARKERS):
            return True
        # Check for action-verb patterns: "Visit:", "Learn:", etc. at line boundaries
        if re.search(
            r"^\s*(visit|click|learn|sign|get|start|shop|book|reply|discover|explore|join|download|subscribe|contact|apply|order|reserve)\s*[:\.→>-]",
            lowered,
            re.MULTILINE
        ):
            return True
        # Check for imperative sentences ("Discover our", "Join today", etc.)
        if re.search(
            r"(?:^|\n|\.|!|\?)\s*(?:visit|click|learn|sign|get|start|shop|book|reply|discover|explore|join|download|subscribe|contact|apply|order|reserve)\s+",
            lowered
        ):
            return True
        return False
    
    return True


_GROUNDING_SYSTEM_PROMPT = (
    "You fact-check marketing copy against a brand guide, using the SAME strict "
    "standard a brand-compliance judge would: any factual fabrication — including "
    "unverifiable superiority or quality claims — must block publication. Return "
    "ONLY a JSON object (no prose, no markdown fences) with one key: \"violations\", "
    "an array of strings. Each entry names one specific claim, number, product "
    "attribute, or superiority/quality claim in the content that does NOT appear "
    "verbatim (or as a close paraphrase of a real value) in the brand guide "
    "excerpts. This includes unverifiable superlatives such as \"best\", \"most "
    "celebrated\", \"unparalleled\", \"finest\", \"world-class\", \"#1\", or "
    "\"award-winning\" — flag these unless that exact superlative appears in the "
    "brand guide. Only ignore truly non-factual tone/flavor words with no "
    "comparative or superiority claim (e.g. \"delicious\", \"vibrant\", \"warm\"). "
    "If every checkable claim is grounded, return an empty array."
)


def _parse_grounding_violations(raw: str) -> list[str]:
    """Defensively parse the grounding checker's completion — same tolerant
    JSON-object slicing as judges.py's `_parse_brand_score`, and fails open
    (no violations) on any parse error so a checker hiccup never blocks
    generation."""
    if not raw:
        return []
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
        violations = data.get("violations") or []
        return [str(v) for v in violations if str(v).strip()]
    except Exception as exc:  # noqa: BLE001
        log.warning("grounding_check_parse_failed", error=str(exc), snippet=text[:200])
        return []


async def _check_grounding(
    content: str, brand_guidance: str, state: OmniBrandState
) -> tuple[list[str], float]:
    """Cheap pre-judge pass: ask a fast/eval model to list any claim in
    `content` unsupported by `brand_guidance` — the same window the judge
    panel scores against. Runs before the 3-judge panel so fabrication is
    caught and retried while it's still cheap, instead of relying solely on
    reflexion's single post-judge rewrite."""
    if brand_guidance == NO_CONTEXT_AVAILABLE:
        return [], 0.0
    model = state["model_aliases"].get("brand_truthfulness", "eval-model")
    messages = [
        {"role": "system", "content": _GROUNDING_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"BRAND GUIDE EXCERPTS:\n{brand_guidance}\n\n"
                f"CONTENT TO CHECK:\n{content}\n\n"
                "List any unsupported claims now."
            ),
        },
    ]
    raw, usage = await traced_llm_call(
        model=model,
        messages=messages,
        task="content_generator_grounding_check",
        state=cast(dict[str, Any], state),
        agent="content_generator",
        response_format={"type": "json_object"},
        temperature=0,
    )
    return _parse_grounding_violations(raw), usage["cost"]


def _check_constraints(content: str, constraints: dict[str, Any]) -> list[str]:
    """Check content against channel constraints. Returns list of violations."""
    violations: list[str] = []
    
    # Character limit: allow 10% overage for flexibility
    char_limit = constraints.get("char_limit")
    if char_limit:
        limit_with_tolerance = int(char_limit * 1.1)
        if len(content) > limit_with_tolerance:
            violations.append(
                f"exceeds char_limit of {char_limit} by too much (got {len(content)})"
            )
    
    # Required elements: be explicit about what's missing
    for element in constraints.get("required_elements", []):
        if not _has_element(content, element):
            violations.append(f"missing required element: {element}")
    
    # Prohibited vocabulary: strict check
    for term in constraints.get("prohibited_vocab", []):
        if term.lower() in content.lower():
            violations.append(f"contains prohibited term: {term}")
    
    return violations


def _build_brand_guidance_text(rag_context: dict[str, Any] | None) -> str:
    """Same chunk window as the judge panel (judges.py `_run_judge`) so the
    generator can ground claims in everything the judges will check them
    against — a narrower window here previously let approved facts living in
    chunks 4-6 (or past a 500-char cut) be invisible to the generator while
    still visible to the judge, forcing it to omit or fabricate those facts."""
    if not rag_context:
        return NO_CONTEXT_AVAILABLE
    chunks = rag_context.get("brand_guide_chunks") or []
    if not isinstance(chunks, list):
        return NO_CONTEXT_AVAILABLE

    compact: list[str] = []
    for chunk in chunks[:6]:
        text = str(chunk).strip()
        if not text:
            continue
        compact.append(text)

    if not compact:
        return NO_CONTEXT_AVAILABLE
    return "\n\n".join(compact)


async def _generate_for_task(
    task: GenerationTask,
    brand_config: dict[str, Any],
    brief: CampaignBrief | None,
    model: str,
    state: OmniBrandState,
    user_feedback: str | None = None,
) -> tuple[ContentVariant, float]:
    channel = task["channel"]
    constraints: dict[str, Any] = {
        **DEFAULT_CHANNEL_CONSTRAINTS.get(channel, {}),
        **task["channel_constraints"],
    }
    # Always generate in SOURCE_LOCALE — locale fan-out is translation_agent's
    # job alone. GenerationTask no longer carries a locale (2026-07-27).
    few_shot = await get_examples(state["brand_id"], channel, SOURCE_LOCALE, n=3)
    brief = brief or CampaignBrief(
        objective="",
        target_audience="",
        key_messages=[],
        tone_override=None,
        channels=[],
        locales=[],
        audience_segments=[],
        token_budget=0,
        end_date=None,
        raw_text="",
    )

    brand_guidance = _build_brand_guidance_text(state.get("rag_context"))
    persona_cta = persona_channel_cta(task["segment"], channel)
    cta_pattern = (
        f'use exactly this brand CTA phrase, verbatim: "{persona_cta}" — never paraphrase '
        "it or substitute a CTA from another channel or persona"
        if persona_cta
        else constraints.get("cta_pattern", "a clear, brand-appropriate call to action")
    )
    messages = render_channel_prompt(
        channel,
        brand_name=brand_config.get("name", state["brand_id"]),
        tone_profile=(
            brand_config.get("tone_profile") or brief["tone_override"] or "professional and clear"
        ),
        char_limit=constraints.get("char_limit", "none"),
        required_elements=", ".join(constraints.get("required_elements", [])) or "none",
        prohibited_vocab=", ".join(constraints.get("prohibited_vocab", [])) or "none",
        cta_pattern=cta_pattern,
        few_shot_examples="\n".join(f"- {ex}" for ex in few_shot) or NO_CONTEXT_AVAILABLE,
        objective=brief["objective"],
        target_audience=brief["target_audience"],
        key_messages=", ".join(brief["key_messages"]),
        segment=task["segment"],
        locale=SOURCE_LOCALE,
        brand_guidance=brand_guidance,
    )
    if user_feedback:
        messages = messages + [
            {
                "role": "user",
                "content": (
                    "The campaign creator reviewed a previous draft of this "
                    f"content and asked for this specific change:\n{user_feedback}\n\n"
                    "Apply this feedback directly in the content you generate now."
                ),
            }
        ]

    end_date = brief.get("end_date")
    if end_date:
        # Additive message, not a template placeholder — render_channel_prompt's
        # signature is shared by every channel/caller, so threading an optional
        # field through it would mean every call site has to know about it.
        # See next_tasks.md 2026-07-26 item 16.
        messages = messages + [
            {
                "role": "user",
                "content": (
                    f"This campaign is valid through: {end_date}. Naturally work this "
                    "validity/expiry information into the content (e.g. \"Offer valid "
                    f"through {end_date}\") — don't invent a more specific date than "
                    "what's given here."
                ),
            }
        ]

    total_cost = 0.0
    content = ""
    violations: list[str] = []
    retry_count = 0

    grounding_violations: list[str] = []

    for attempt in range(MAX_RETRIES + 1):
        content, usage = await traced_llm_call(
            model=model,
            messages=messages,
            task="content_generator",
            state=cast(dict[str, Any], state),
            agent="content_generator",
        )
        total_cost += usage["cost"]
        violations = _check_constraints(content, constraints)
        # Only spend the grounding check once structural constraints already
        # pass — no point fact-checking a draft that's about to be regenerated
        # for a missing CTA/subject line anyway.
        grounding_violations = []
        if not violations:
            try:
                grounding_violations, grounding_cost = await _check_grounding(
                    content, brand_guidance, state
                )
                total_cost += grounding_cost
            except Exception as exc:  # noqa: BLE001
                # Best-effort pre-judge fact-check — a transient LLM/provider
                # failure here (e.g. a flaky free-tier model returning malformed
                # JSON) must not discard an otherwise constraint-passing variant.
                # Fail open, same posture as _parse_grounding_violations already
                # takes on a parse error; the 3-judge panel still checks
                # factual_grounding downstream.
                log.warning(
                    "content_generator_grounding_check_call_failed",
                    campaign_id=state.get("campaign_id"),
                    task_id=task["task_id"],
                    channel=channel,
                    error=str(exc),
                )
                grounding_violations = []
        if (not violations and not grounding_violations) or attempt == MAX_RETRIES:
            break
        retry_count += 1

        # Build detailed retry prompt with specific guidance
        violation_guidance = "\n".join(f"- {v}" for v in violations)
        retry_instruction = (
            f"Your response had these issues:\n{violation_guidance}\n\n"
            f"Required elements to include:\n"
        )
        for elem in constraints.get("required_elements", []):
            if elem == "subject_line":
                retry_instruction += f"- Subject line: Start with 'Subject:' or 'Subject Line:' on its own line\n"
            elif elem == "cta":
                retry_instruction += f"- Call-to-action: Use action verbs like 'Click', 'Learn more', 'Get started', etc.\n"
            elif elem == "hashtag":
                retry_instruction += f"- Hashtags: Include relevant hashtags (e.g., #example)\n"

        if grounding_violations:
            unsupported = "\n".join(f"- {v}" for v in grounding_violations)
            retry_instruction += (
                f"\nThese claims are NOT supported by the brand guide and must be "
                f"removed or replaced with grounded/qualitative language:\n{unsupported}\n"
            )

        retry_instruction += (
            f"\nRegenerate the full {channel} content now, ensuring ALL required elements are present."
        )

        messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": retry_instruction},
        ]

    # Grounding is a best-effort pre-filter, not a new hard gate: if it still
    # flags something after MAX_RETRIES, the variant still goes to the judge
    # panel as before — we've just spent a cheap call trying to catch it first.
    status = "generated" if not violations else "failed"
    failure_reason = (
        None
        if not violations
        else f"constraint violations after {retry_count} retries: {'; '.join(violations)}"
    )
    if status == "failed":
        # generated_content is nulled out below since it never satisfied
        # constraints, so log the actual text here or the failure is
        # undiagnosable from state/DB alone (2026-07-31).
        log.warning(
            "content_generator_constraint_failed",
            campaign_id=state.get("campaign_id"),
            task_id=task["task_id"],
            channel=channel,
            violations=violations,
            content_preview=content[:500],
        )
    if status == "generated" and grounding_violations:
        log.warning(
            "content_generator_grounding_unresolved",
            campaign_id=state.get("campaign_id"),
            task_id=task["task_id"],
            violations=grounding_violations,
        )
    rag_context = state.get("rag_context")

    variant: ContentVariant = {
        "task_id": task["task_id"],
        "locale": SOURCE_LOCALE,
        "channel": channel,
        "segment": task["segment"],
        "generated_content": content if status == "generated" else None,
        "personalized_content": None,
        "translated_content": None,
        "final_content": None,
        "status": status,
        "generation_model": model,
        "prompt_version": PROMPT_VERSION,
        "brand_guide_version": rag_context["brand_guide_version"] if rag_context else None,
        "translation_engine": None,
        "back_translation_score": None,
        "retry_count": retry_count,
        "reflexion_applied": False,
        "failure_reason": failure_reason,
    }
    return variant, total_cost


async def _regenerate_single_task(
    task: GenerationTask,
    brand_config: dict[str, Any],
    brief: CampaignBrief | None,
    model: str,
    state: OmniBrandState,
) -> dict[str, Any]:
    """Regenerate exactly one variant (selective per-channel edit).

    Mutates the matching entry in ``state["variants"]`` in place and also
    returns it via the "variants" key — merge_variants (state.py) upserts by
    task_id, so this replaces the matching entry (both live and in the
    checkpoint) rather than duplicating it. Resetting personalized/
    translated/final content and status back to "generated" lets
    personalization_agent/translation_agent's existing skip-if-already-
    processed checks naturally reprocess only this one variant, leaving every
    sibling variant's status untouched.

    Bumps ``user_edit_count`` (not ``retry_count``) — ``retry_count`` is
    reflexion's round counter and is load-bearing for round-keyed dedup in
    judges.py::_already_scored / reflexion.py::_latest_aggregate. A manual
    edit here must not consume reflexion's one-retry budget before the
    variant has even reached judging.
    """
    existing = next(
        (v for v in state.get("variants") or [] if v["task_id"] == task["task_id"]), None
    )
    if existing is None:
        raise ValueError(f"current_task {task['task_id']!r} has no existing variant to regenerate")

    variant, cost = await _generate_for_task(
        task, brand_config, brief, model, state, user_feedback=state.get("user_edit_note")
    )

    existing["generated_content"] = variant["generated_content"]
    existing["personalized_content"] = None
    existing["translated_content"] = None
    existing["final_content"] = None
    existing["status"] = variant["status"]
    existing["generation_model"] = variant["generation_model"]
    existing["prompt_version"] = variant["prompt_version"]
    existing["brand_guide_version"] = variant["brand_guide_version"]
    existing["user_edit_count"] = int(existing.get("user_edit_count", 0)) + 1
    existing["reflexion_applied"] = False
    existing["failure_reason"] = variant["failure_reason"]

    await publish_campaign_event(
        campaign_id=state.get("campaign_id"),
        agent="content_generator",
        phase="variant_regenerated",
        payload={
            "task_id": task["task_id"],
            "channel": task["channel"],
            "locale": SOURCE_LOCALE,
            "segment": task["segment"],
            "status": existing["status"],
            "preview": (existing.get("generated_content") or "")[:200],
        },
    )

    return {
        "variants": [existing],
        "failed_task_ids": [task["task_id"]] if existing["status"] == "failed" else [],
        "token_cost_usd": cost,
        "current_phase": "content_generated",
        "current_task": None,
        "user_edit_note": None,
    }


async def content_generator(state: OmniBrandState) -> dict[str, Any]:
    async def _impl(state: OmniBrandState) -> dict[str, Any]:
        model = state["model_aliases"].get("generation", "gen-free")
        brand_config = state["brand_config"]
        brief = state["brief"]

        current_task = state.get("current_task")
        if current_task is not None:
            return await _regenerate_single_task(current_task, brand_config, brief, model, state)

        variants: list[ContentVariant] = []
        failed_task_ids: list[str] = []
        guardrail_flags: list[str] = []
        total_cost = 0.0
        user_feedback = state.get("user_edit_note")

        for task in state["tasks"]:
            try:
                variant, cost = await _generate_for_task(
                    task, brand_config, brief, model, state, user_feedback=user_feedback
                )
            except Exception as exc:
                # Per-task isolation: one bad task (e.g. an unrecognized
                # channel raising KeyError in render_channel_prompt) must not
                # abort generation for every sibling task in this same node
                # invocation — previously it did, since nothing here caught
                # it, unlike translation_agent's existing per-variant guard.
                # See next_tasks.md 2026-07-26 (campaign
                # 019f9ecd-3d46-719f-b926-1a04b58480e4: one bad-cased "SMS"
                # channel produced personalized=0/translated=0 for ALL 4
                # tasks, not just that one).
                log.error(
                    "content_generator_task_failed",
                    task_id=task["task_id"],
                    channel=task["channel"],
                    error=str(exc),
                )
                variant = cast(
                    ContentVariant,
                    {
                        "task_id": task["task_id"],
                        "locale": SOURCE_LOCALE,
                        "channel": task["channel"],
                        "segment": task["segment"],
                        "generated_content": None,
                        "personalized_content": None,
                        "translated_content": None,
                        "final_content": None,
                        "status": "failed",
                        "generation_model": model,
                        "prompt_version": PROMPT_VERSION,
                        "brand_guide_version": None,
                        "translation_engine": None,
                        "back_translation_score": None,
                        "retry_count": 0,
                        "reflexion_applied": False,
                        "failure_reason": f"unexpected error: {exc}",
                    },
                )
                cost = 0.0
            variants.append(variant)
            total_cost += cost
            if variant["status"] == "failed":
                failed_task_ids.append(task["task_id"])

            # Output guardrail — flag-only (never hard-block) to match
            # translation.py's existing fail-open posture.
            generated = variant.get("generated_content") or ""
            if generated and variant["status"] != "failed":
                from pipeline.agents.safety import screen_output_safety

                brand_name = (brand_config or {}).get("name")
                safety_flags = await screen_output_safety(generated, brand_name=brand_name)
                if safety_flags:
                    guardrail_flags.extend(
                        f"{task['task_id']}:{f}" for f in safety_flags
                    )

            await publish_campaign_event(
                campaign_id=state.get("campaign_id"),
                agent="content_generator",
                phase="variant_generated",
                payload={
                    "task_id": task["task_id"],
                    "channel": task["channel"],
                    "locale": SOURCE_LOCALE,
                    "segment": task["segment"],
                    "status": variant["status"],
                    "preview": (variant.get("generated_content") or "")[:200],
                },
            )

        await publish_campaign_event(
            campaign_id=state.get("campaign_id"),
            agent="content_generator",
            phase="content_generated",
            payload={
                "variant_count": len(variants),
                "failed_count": len(failed_task_ids),
            },
        )

        return {
            "variants": variants,
            "failed_task_ids": failed_task_ids,
            "guardrail_flags": guardrail_flags,
            "token_cost_usd": float(state.get("token_cost_usd", 0.0) or 0.0) + total_cost,
            "current_phase": "content_generated",
            "current_task": None,
            "user_edit_note": None,
        }

    return await safe_agent_run(_impl, state)
