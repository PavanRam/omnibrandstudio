"""LLM-as-judge panel — three cross-family judges scoring brand compliance.

Each judge is an independent, blind, single-artifact scorer (no pairwise, no
cross-visibility) evaluating every scoreable variant against the retrieved brand
guide. Judges return ``{"brand_scores": [...]}`` ONLY — never ``token_cost_usd``
(that is a plain, non-fan-in field and three parallel branches writing it in the
same super-step is a concurrent-write error; cost is recorded by
``traced_llm_call`` into ``campaign_cost_attribution``).

The three judges differ only by the model alias they read from
``state["model_aliases"]`` (``judge-1/2/3``) — the family diversity that gives
the aggregator its disagreement signal lives entirely in configuration, so
switching free↔paid panels is a config flip with no code change.

Idempotency: a judge scores a variant only if it has no score yet at the
variant's current ``retry_count`` round, so a reflexion re-eval re-scores only
the regenerated variant without double-counting under ``operator.add``.
"""
from __future__ import annotations

import json
import time
from typing import Any, cast

import structlog

from core.metrics import judge_latency
from pipeline.agents.base import publish_campaign_event, safe_agent_run, traced_llm_call
from pipeline.agents.prompts.judge_prompts import CRITERIA, build_judge_messages
from pipeline.schemas import BrandScoreOutput
from pipeline.state import BrandScore, OmniBrandState

log = structlog.get_logger()

# Default alias when model_aliases is unpopulated (e.g. unit tests). Defaults to
# the free panel so validation works without paid keys; build_initial_state
# overrides these per JUDGE_TIER.
DEFAULT_JUDGE_ALIASES: dict[str, str] = {
    "judge-1": "judge-1-free",
    "judge-2": "judge-2-free",
    "judge-3": "judge-3-free",
}

# Variant statuses that carry no publishable content to score.
_NON_SCOREABLE_STATUSES = {
    "failed",
    "translation_failed",
    "translation_unsupported_locale",
    "translation_blocked_no_source",
}


def _variant_content(variant: dict) -> str | None:
    return (
        variant.get("final_content")
        or variant.get("translated_content")
        or variant.get("personalized_content")
        or variant.get("generated_content")
    )


def _already_scored(
    brand_scores: list, variant_id: str, judge_model: str, round_: int
) -> bool:
    return any(
        bs["variant_id"] == variant_id
        and bs["judge_model"] == judge_model
        and int(bs.get("evaluation_round", 0)) == round_
        for bs in brand_scores
    )


def _parse_brand_score(raw: str) -> BrandScoreOutput | None:
    """Defensively parse a judge's raw completion into ``BrandScoreOutput``.

    Tolerates ``<thinking>`` preambles / markdown fences by slicing to the
    outermost JSON object before validation. Returns ``None`` on any failure so
    the aggregator's degraded mode handles a missing judge.
    """
    if not raw:
        return None
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
        return BrandScoreOutput.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        # Degrade gracefully — a missing judge is handled by the aggregator.
        log.warning("judge_parse_failed", error=str(exc), snippet=candidate[:200])
        return None


def _to_brand_score(
    variant_id: str,
    judge_model: str,
    parsed: BrandScoreOutput,
    latency_ms: int,
    round_: int,
) -> BrandScore:
    scores: dict[str, Any] = {}
    for criterion in CRITERIA:
        cs = getattr(parsed, criterion)
        scores[criterion] = {
            "score": float(cs.score),
            "reasoning": cs.reasoning,
            "violations": list(cs.violations),
            "citations": list(cs.citations),
        }
    return {
        "variant_id": variant_id,
        "judge_model": judge_model,
        "composite_score": float(parsed.composite_score),
        "scores": scores,
        "critical_violations": list(parsed.critical_violations),
        "routing_decision": parsed.routing_decision,
        "evaluation_latency_ms": latency_ms,
        "evaluation_round": round_,
    }


async def _run_judge(
    state: OmniBrandState, alias_key: str, agent_name: str, judge_label: str
) -> dict:
    aliases = state.get("model_aliases") or {}
    model = aliases.get(alias_key, DEFAULT_JUDGE_ALIASES[alias_key])
    brand_scores = state.get("brand_scores") or []
    rag = state.get("rag_context") or {}
    brand_guide = "\n\n".join((rag.get("brand_guide_chunks") or [])[:6]).strip() or (
        "(no brand guide retrieved)"
    )

    produced: list[BrandScore] = []
    for variant in state.get("variants") or []:
        if variant.get("status") in _NON_SCOREABLE_STATUSES:
            continue
        content = _variant_content(variant)
        if not content:
            continue
        variant_id = variant["task_id"]
        round_ = int(variant.get("retry_count", 0))
        if _already_scored(brand_scores, variant_id, model, round_):
            continue

        messages = build_judge_messages(
            brand_guide=brand_guide,
            channel=variant.get("channel", "unknown"),
            locale=variant.get("locale", "en"),
            content=content,
        )
        start = time.perf_counter()
        # 2026-07-27: previously the traced_llm_call was unguarded, so a failure
        # on the Nth variant (e.g. a transient Groq 400/404 on one locale) raised
        # straight through _impl into safe_agent_run, which discarded this judge's
        # ENTIRE `produced` list — including variants already scored successfully.
        # That is exactly how campaign 4e644ce5 degraded to n_judges=1: judge_claude
        # scored the English variant, then hit a 400 on the Spanish variant and its
        # good English score was thrown away. Catch per-variant so partial scores
        # survive; the judge returns whatever it managed to score and the aggregator
        # degrades gracefully instead of losing a whole judge.
        try:
            raw, _usage = await traced_llm_call(
                model=model,
                messages=messages,
                task=agent_name,
                state=cast(dict, state),
                agent=agent_name,
                response_format={"type": "json_object"},
                temperature=0,
            )
        except Exception as exc:  # noqa: BLE001 — isolate one variant's failure
            log.warning(
                "judge_variant_failed",
                campaign_id=state.get("campaign_id"),
                judge=judge_label,
                variant_id=variant_id,
                round=round_,
                model=model,
                error=str(exc),
            )
            continue
        latency_ms = int((time.perf_counter() - start) * 1000)
        judge_latency.labels(judge=judge_label).observe(latency_ms / 1000)

        parsed = _parse_brand_score(raw)
        if parsed is None:
            continue
        score = _to_brand_score(variant_id, model, parsed, latency_ms, round_)
        produced.append(score)

        # 2026-07-27: judges previously never logged anything on a normal
        # score — routing_decision/critical_violations/per-criterion
        # reasoning only ever reached the frontend via a Redis pub/sub event
        # (aggregator.py's aggregation_complete), never Docker logs or the
        # DB, so a failed campaign's judge reasoning was unrecoverable after
        # the fact (see next_tasks.md — campaign 019fa496 investigation).
        log.info(
            "judge_scored",
            campaign_id=state.get("campaign_id"),
            judge=judge_label,
            variant_id=variant_id,
            round=round_,
            composite_score=score["composite_score"],
            routing_decision=score["routing_decision"],
            critical_violations=score["critical_violations"],
            criterion_scores={
                criterion: data["score"] for criterion, data in score["scores"].items()
            },
        )
        if score["critical_violations"] or score["routing_decision"] == "auto_reject":
            # Reasoning text is verbose (one paragraph per criterion) — only
            # logged in full when there's actually something to explain, kept
            # out of the always-on line above to avoid drowning normal runs.
            log.warning(
                "judge_rejected",
                campaign_id=state.get("campaign_id"),
                judge=judge_label,
                variant_id=variant_id,
                round=round_,
                routing_decision=score["routing_decision"],
                critical_violations=score["critical_violations"],
                reasoning={
                    criterion: data["reasoning"]
                    for criterion, data in score["scores"].items()
                    if data["violations"] or data["score"] < 7
                },
            )

    await publish_campaign_event(
        campaign_id=state.get("campaign_id"),
        agent=agent_name,
        phase="judge_complete",
        payload={"judge": judge_label, "scored": len(produced)},
    )
    return {"brand_scores": produced}


# Judge functions are named judge_1/2/3 (matching the alias keys judge-1/2/3)
# rather than model-specific names so they stay accurate when models rotate.
# Actual models come from state["model_aliases"]["judge-1/2/3"] which resolves
# to judge-1-free/judge-2-free/judge-3-free → gpt-oss-120b / llama-3.3-70b /
# gpt-oss-20b on the free tier.  The judge_label is logged in structlog and
# published via campaign events so the UI shows the real model family.
async def judge_1(state: OmniBrandState) -> dict:
    """Judge 1 — gpt-oss-120b family (alias judge-1 / judge-1-free)."""
    async def _impl(state: OmniBrandState) -> dict:
        return await _run_judge(state, "judge-1", "judge_1", "gptoss")

    return await safe_agent_run(_impl, state)


async def judge_2(state: OmniBrandState) -> dict:
    """Judge 2 — llama-3.3-70b family (alias judge-2 / judge-2-free)."""
    async def _impl(state: OmniBrandState) -> dict:
        return await _run_judge(state, "judge-2", "judge_2", "llama")

    return await safe_agent_run(_impl, state)


async def judge_3(state: OmniBrandState) -> dict:
    """Judge 3 — gpt-oss-20b family (alias judge-3 / judge-3-free)."""
    async def _impl(state: OmniBrandState) -> dict:
        return await _run_judge(state, "judge-3", "judge_3", "gptoss20b")

    return await safe_agent_run(_impl, state)
