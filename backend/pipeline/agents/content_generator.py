from __future__ import annotations

import re
from typing import Any, cast

from pipeline.agents.base import publish_campaign_event, safe_agent_run, traced_llm_call
from pipeline.agents.prompts.channel_prompts import (
    DEFAULT_CHANNEL_CONSTRAINTS,
    PROMPT_VERSION,
    render_channel_prompt,
)
from pipeline.agents.retrieval import get_examples
from pipeline.state import CampaignBrief, ContentVariant, GenerationTask, OmniBrandState

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
)


def _has_element(content: str, element: str) -> bool:
    """Check if content includes required element. More lenient parsing."""
    lowered = content.lower()
    
    if element == "hashtag":
        return "#" in content
    
    if element == "subject_line":
        # Match various subject_line formats:
        # "Subject: ...", "Subject Line: ...", "---\nSubject: ...", etc.
        return bool(
            re.search(
                r"(?:subject\s*(?:line)?\s*:|\/\/\s*subject|subject\s*line)",
                lowered,
                re.IGNORECASE
            )
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
    if not rag_context:
        return NO_CONTEXT_AVAILABLE
    chunks = rag_context.get("brand_guide_chunks") or []
    if not isinstance(chunks, list):
        return NO_CONTEXT_AVAILABLE

    compact: list[str] = []
    for chunk in chunks[:3]:
        text = str(chunk).strip()
        if not text:
            continue
        compact.append(text[:500])

    if not compact:
        return NO_CONTEXT_AVAILABLE
    return "\n\n".join(compact)


async def _generate_for_task(
    task: GenerationTask,
    brand_config: dict[str, Any],
    brief: CampaignBrief | None,
    model: str,
    state: OmniBrandState,
) -> tuple[ContentVariant, float]:
    channel = task["channel"]
    constraints: dict[str, Any] = {
        **DEFAULT_CHANNEL_CONSTRAINTS.get(channel, {}),
        **task["channel_constraints"],
    }
    few_shot = await get_examples(state["brand_id"], channel, task["locale"], n=3)
    brief = brief or CampaignBrief(
        objective="",
        target_audience="",
        key_messages=[],
        tone_override=None,
        channels=[],
        locales=[],
        audience_segments=[],
        token_budget=0,
        raw_text="",
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
        cta_pattern=constraints.get("cta_pattern", "a clear, brand-appropriate call to action"),
        few_shot_examples="\n".join(f"- {ex}" for ex in few_shot) or NO_CONTEXT_AVAILABLE,
        objective=brief["objective"],
        target_audience=brief["target_audience"],
        key_messages=", ".join(brief["key_messages"]),
        segment=task["segment"],
        locale=task["locale"],
        brand_guidance=_build_brand_guidance_text(state.get("rag_context")),
    )

    total_cost = 0.0
    content = ""
    violations: list[str] = []
    retry_count = 0

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
        if not violations or attempt == MAX_RETRIES:
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
        
        retry_instruction += (
            f"\nRegenerate the full {channel} content now, ensuring ALL required elements are present."
        )
        
        messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": retry_instruction},
        ]

    status = "generated" if not violations else "failed"
    failure_reason = (
        None
        if not violations
        else f"constraint violations after {retry_count} retries: {'; '.join(violations)}"
    )
    rag_context = state.get("rag_context")

    variant: ContentVariant = {
        "task_id": task["task_id"],
        "locale": task["locale"],
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


async def content_generator(state: OmniBrandState) -> dict[str, Any]:
    async def _impl(state: OmniBrandState) -> dict[str, Any]:
        model = state["model_aliases"].get("generation", "gen-free")
        brand_config = state["brand_config"]
        brief = state["brief"]

        variants: list[ContentVariant] = []
        failed_task_ids: list[str] = []
        total_cost = 0.0

        for task in state["tasks"]:
            variant, cost = await _generate_for_task(task, brand_config, brief, model, state)
            variants.append(variant)
            total_cost += cost
            if variant["status"] == "failed":
                failed_task_ids.append(task["task_id"])
            await publish_campaign_event(
                campaign_id=state.get("campaign_id"),
                agent="content_generator",
                phase="variant_generated",
                payload={
                    "task_id": task["task_id"],
                    "channel": task["channel"],
                    "locale": task["locale"],
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
            "token_cost_usd": float(state.get("token_cost_usd", 0.0) or 0.0) + total_cost,
            "current_phase": "content_generated",
        }

    return await safe_agent_run(_impl, state)
