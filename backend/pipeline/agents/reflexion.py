"""Reflexion — one self-correction retry when the panel rejects/low-flags.

``reflexion`` (node) regenerates a failing variant's content from the judges'
specific criticism, then ``reflexion_router`` (conditional-edge function) re-fans
the corrected variant back through the judge panel exactly once.

Retry is hard-capped at one round (``retry_count > 0`` short-circuits) and the
router stops as soon as the reflexed variant has been re-aggregated for its new
round — together these guarantee termination under the ``operator.add`` fan-in,
which cannot delete the stale first-round scores.
"""
from __future__ import annotations

from typing import cast

import structlog

from pipeline.agents.base import safe_agent_run, traced_llm_call
from pipeline.agents.prompts.judge_prompts import build_reflexion_messages
from pipeline.state import AggregatedScore, OmniBrandState

log = structlog.get_logger()

_JUDGE_NODES = ["judge_claude", "judge_gpt4o", "judge_llama"]

# Reflexion fires on a hard reject, or on a flag whose confidence is low.
_FLAG_RETRY_MEAN = 0.72
# Criterion scores below this feed the correction prompt as problems to fix.
_LOW_CRITERION = 6.0


def _variant_content(variant: dict) -> str:
    return (
        variant.get("final_content")
        or variant.get("translated_content")
        or variant.get("personalized_content")
        or variant.get("generated_content")
        or ""
    )


def _latest_aggregate(
    aggregates: list, variant_id: str, round_: int
) -> AggregatedScore | None:
    match = [
        a
        for a in aggregates
        if a["variant_id"] == variant_id and int(a.get("evaluation_round", 0)) == round_
    ]
    return match[-1] if match else None


def _collect_reasons(brand_scores: list, variant_id: str, round_: int) -> list[str]:
    reasons: list[str] = []
    for bs in brand_scores:
        if bs["variant_id"] != variant_id or int(bs.get("evaluation_round", 0)) != round_:
            continue
        for criterion, cs in (bs.get("scores") or {}).items():
            if float(cs.get("score", 10.0)) < _LOW_CRITERION:
                reasoning = cs.get("reasoning", "").strip()
                reasons.append(f"{criterion} ({cs.get('score')}/10): {reasoning}")
        for violation in bs.get("critical_violations", []):
            reasons.append(f"critical: {violation}")
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


async def reflexion(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        aggregates = state.get("aggregated_scores") or []
        brand_scores = state.get("brand_scores") or []
        aliases = state.get("model_aliases") or {}
        model = aliases.get("generation", "gen-free")

        for variant in state.get("variants") or []:
            await _maybe_reflex_variant(state, variant, aggregates, brand_scores, model)
        return {}

    return await safe_agent_run(_impl, state)


async def _maybe_reflex_variant(
    state: OmniBrandState,
    variant: dict,
    aggregates: list,
    brand_scores: list,
    model: str,
) -> None:
    """Regenerate one variant in place if the panel rejected/low-flagged it.

    No-op when the variant has already been retried (hard cap), has no aggregate
    for its round, or its routing does not trigger reflexion.
    """
    round_ = int(variant.get("retry_count", 0))
    if round_ > 0:
        return  # hard cap: at most one reflexion retry per variant

    aggregate = _latest_aggregate(aggregates, variant["task_id"], round_)
    if aggregate is None:
        return

    decision = aggregate["routing_decision"]
    trigger = decision == "auto_reject" or (
        decision == "flag" and aggregate["weighted_mean"] < _FLAG_RETRY_MEAN
    )
    if not trigger:
        return

    reasons = _collect_reasons(brand_scores, variant["task_id"], round_)
    # Re-inject brand guide excerpts for grounding during reflexion revision.
    rag_context = state.get("rag_context") or {}
    brand_guide_chunks = rag_context.get("brand_guide_chunks") or []
    brand_guide_text = "\n---\n".join(brand_guide_chunks[:5]) or "(none available)"
    messages = build_reflexion_messages(
        content=_variant_content(variant),
        reasons=reasons,
        critical=aggregate.get("critical_violations", []),
        channel=variant.get("channel", "unknown"),
        locale=variant.get("locale", "en"),
        brand_guide=brand_guide_text,
    )
    new_content, _usage = await traced_llm_call(
        model=model,
        messages=messages,
        task="reflexion",
        state=cast(dict, state),
        agent="reflexion",
    )

    # Enrich the variant in place (variants is an operator.add fan-in field —
    # returning it would append a duplicate). Reset downstream content and bump
    # the round so the judges re-score at round+1.
    variant["generated_content"] = new_content
    variant["personalized_content"] = None
    variant["translated_content"] = None
    variant["final_content"] = None
    variant["status"] = "generated"
    variant["retry_count"] = round_ + 1
    variant["reflexion_applied"] = True

    log.info(
        "reflexion_applied",
        campaign_id=state.get("campaign_id"),
        variant_id=variant["task_id"],
        trigger=decision,
    )


def reflexion_router(state: OmniBrandState) -> list[str] | str:
    """Conditional-edge selector after the reflexion node.

    Returns the judge fan-out list to re-evaluate a just-reflexed variant, or
    ``"review_gate"`` to proceed. A reflexed variant needs re-evaluation exactly
    while it has no aggregate for its current round; once re-aggregated, routing
    proceeds — guaranteeing a single retry loop.
    """
    aggregates = state.get("aggregated_scores") or []
    for variant in state.get("variants") or []:
        if not variant.get("reflexion_applied"):
            continue
        round_ = int(variant.get("retry_count", 0))
        has_aggregate_this_round = any(
            a["variant_id"] == variant["task_id"] and int(a.get("evaluation_round", 0)) == round_
            for a in aggregates
        )
        if not has_aggregate_this_round:
            return list(_JUDGE_NODES)
    return "review_gate"
