import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from core.config import settings
from core.database import get_db
from core.langfuse import get_langfuse, start_langfuse_trace
from core.metrics import llm_call_duration, llm_cost_usd_total, llm_tokens_total
from core.redis import get_redis
from core.tracing import get_tracer
from services.audit_service import write_audit  # re-exported for agent use

from pipeline.state import OmniBrandState

log = structlog.get_logger()

__all__ = [
    "traced_llm_call",
    "write_audit",
    "safe_agent_run",
    "publish_campaign_event",
    "AGENT_WRITE_PERMISSIONS",
]

_MODEL_PRICING_CACHE: dict[str, tuple[float, float] | None] = {}

# PII guardrail — enforced centrally here so every agent gets protection simply
# by calling traced_llm_call, rather than each agent needing to remember to scrub
# itself. Independent copy of personalization.py's patterns (not imported from
# there) to avoid a circular import: personalization.py already imports from
# this module.
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}


def _scrub_pii(text: str | None) -> tuple[str, list[str]]:
    """Redact PII from `text`; return (redacted_text, found_types)."""
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


async def publish_campaign_event(
    *,
    campaign_id: str | None,
    agent: str,
    phase: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if not campaign_id:
        return

    event_payload = {
        "campaign_id": campaign_id,
        "agent": agent,
        "phase": phase,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }

    try:
        channel = f"campaign:{campaign_id}:events"
        await get_redis().publish(channel, json.dumps(event_payload))
    except Exception as exc:
        log.warning(
            "campaign_event_publish_failed",
            campaign_id=campaign_id,
            agent=agent,
            phase=phase,
            error=str(exc),
        )


def _fallback_content_from_messages(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if str(msg.get("role", "")).lower() == "user":
            text = str(msg.get("content", "")).strip()
            if text:
                snippet = text[:220]
                return f"[fallback-generated] {snippet}"
    return "[fallback-generated]"


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_response_cost(payload: dict[str, Any], usage: dict[str, Any]) -> float:
    candidates = (
        payload.get("_hidden_params", {}).get("response_cost"),
        payload.get("response_cost"),
        payload.get("cost"),
        usage.get("total_cost"),
        usage.get("cost"),
    )
    for candidate in candidates:
        parsed = _to_float_or_none(candidate)
        if parsed is not None:
            return parsed
    return 0.0


def _extract_pricing_from_model_info(
    model_info: dict[str, Any] | None,
) -> tuple[float, float] | None:
    if not model_info:
        return None
    input_rate = _to_float_or_none(model_info.get("input_cost_per_token"))
    output_rate = _to_float_or_none(model_info.get("output_cost_per_token"))
    if input_rate is None or output_rate is None:
        return None
    return input_rate, output_rate


def _parse_model_info_candidates(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data") or payload.get("model_list") or []
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _candidate_pricing(item: dict[str, Any]) -> tuple[float, float] | None:
    info = item.get("model_info") if isinstance(item.get("model_info"), dict) else None
    return _extract_pricing_from_model_info(info)


def _candidate_matches_model(item: dict[str, Any], model_alias: str, resolved_model: str) -> bool:
    info = item.get("model_info") if isinstance(item.get("model_info"), dict) else {}
    item_alias = str(item.get("model_name") or "")
    item_resolved = str((item.get("litellm_params") or {}).get("model") or info.get("key") or "")
    return item_alias == model_alias or item_resolved == resolved_model


def _select_pricing_candidate(
    candidates: list[dict[str, Any]], model_alias: str, resolved_model: str
) -> tuple[float, float] | None:
    for item in candidates:
        if not _candidate_matches_model(item, model_alias, resolved_model):
            continue
        pricing = _candidate_pricing(item)
        if pricing is not None:
            return pricing

    for item in candidates:
        pricing = _candidate_pricing(item)
        if pricing is not None:
            return pricing

    return None


async def _fetch_pricing_per_token(model_alias: str, resolved_model: str) -> tuple[float, float] | None:
    cache_key = f"{model_alias}|{resolved_model}"
    if cache_key in _MODEL_PRICING_CACHE:
        return _MODEL_PRICING_CACHE[cache_key]

    try:
        async with httpx.AsyncClient(base_url=settings.LITELLM_BASE_URL, timeout=20) as client:
            response = await client.get("/model/info", params={"model": model_alias})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        log.warning(
            "llm_model_info_unavailable",
            model_alias=model_alias,
            resolved_model=resolved_model,
            error=str(exc),
        )
        _MODEL_PRICING_CACHE[cache_key] = None
        return None

    candidates = _parse_model_info_candidates(payload)
    pricing = _select_pricing_candidate(candidates, model_alias, resolved_model)
    if pricing is not None:
        _MODEL_PRICING_CACHE[cache_key] = pricing
        return pricing

    _MODEL_PRICING_CACHE[cache_key] = None
    return None


async def _estimate_missing_cost(
    *,
    cost: float,
    input_tokens: int,
    output_tokens: int,
    model: str,
    resolved_model: str,
    agent: str,
    task: str,
) -> float:
    if not settings.ENABLE_COST_ESTIMATION_FALLBACK:
        return cost

    if cost or (not input_tokens and not output_tokens) or resolved_model.startswith("fallback/"):
        return cost

    pricing = await _fetch_pricing_per_token(model_alias=model, resolved_model=resolved_model)
    if pricing is None:
        return cost

    input_rate, output_rate = pricing
    estimated_cost = (input_tokens * input_rate) + (output_tokens * output_rate)
    log.info(
        "llm_cost_estimated_from_model_info",
        agent=agent,
        task=task,
        model=model,
        resolved_model=resolved_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost,
    )
    return estimated_cost


async def traced_llm_call(
    model: str,
    messages: list[dict],
    task: str,
    state: dict,
    **kwargs: Any,
) -> tuple[str, dict]:
    """Wrapper for every LLM call in the system.

    Calls LiteLLM via httpx, records a Langfuse trace, records Prometheus
    metrics, creates an OTel span, and returns (content, usage_metadata).
    """
    agent = kwargs.pop("agent", task)

    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            redacted, pii_types = _scrub_pii(msg["content"])
            if pii_types:
                msg["content"] = redacted
                log.warning(
                    "guardrail_pii_redacted",
                    agent=agent,
                    task=task,
                    pii_types=pii_types,
                    direction="input",
                )

    campaign_id = state.get("campaign_id")
    request_id = state.get("request_id", "")
    tracer = get_tracer(f"omnibrand.{agent}")

    trace = start_langfuse_trace(
        name=task,
        session_id=campaign_id,
        metadata={"model": model, "request_id": request_id, "org_id": state.get("org_id")},
    )

    start = time.perf_counter()
    with tracer.start_as_current_span(f"{agent}.llm_call") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.task", task)
        span.set_attribute("campaign_id", campaign_id or "")
        span.set_attribute("request_id", request_id)

        async with httpx.AsyncClient(base_url=settings.LITELLM_BASE_URL, timeout=60) as client:
            try:
                response = await client.post(
                    "/chat/completions",
                    json={"model": model, "messages": messages, **kwargs},
                )
                response.raise_for_status()
                payload = response.json()
                span.set_attribute("http.status_code", response.status_code)
            except httpx.HTTPError as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", 0)
                span.set_attribute("http.status_code", int(status_code or 0))
                span.set_attribute("llm.fallback", True)
                log.warning(
                    "llm_call_http_failed_using_fallback",
                    agent=agent,
                    task=task,
                    model=model,
                    status_code=status_code,
                    error=str(exc),
                )
                payload = {
                    "choices": [
                        {
                            "message": {
                                "content": _fallback_content_from_messages(messages),
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                    "model": f"fallback/{model}",
                    "_hidden_params": {"response_cost": 0.0},
                }

    latency_ms = int((time.perf_counter() - start) * 1000)
    content = payload["choices"][0]["message"]["content"]

    redacted_content, output_pii_types = _scrub_pii(content)
    if output_pii_types:
        log.warning(
            "guardrail_pii_redacted",
            agent=agent,
            task=task,
            pii_types=output_pii_types,
            direction="output",
        )
        content = redacted_content

    usage = payload.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    cost = _extract_response_cost(payload, usage)
    resolved_model = str(payload.get("model") or model)
    provider = resolved_model.split("/")[0]

    cost = await _estimate_missing_cost(
        cost=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        resolved_model=resolved_model,
        agent=agent,
        task=task,
    )

    if (not cost) and (input_tokens or output_tokens):
        log.info(
            "llm_cost_missing_from_response",
            agent=agent,
            task=task,
            model=model,
            resolved_model=resolved_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    llm_call_duration.labels(agent=agent, model=model, task=task).observe(latency_ms / 1000)
    llm_tokens_total.labels(agent=agent, model=model, type="input").inc(input_tokens)
    llm_tokens_total.labels(agent=agent, model=model, type="output").inc(output_tokens)
    llm_cost_usd_total.labels(agent=agent, model=model).inc(cost)

    try:
        trace.update(output=content)
        end_fn = getattr(trace, "end", None)
        if callable(end_fn):
            end_fn()
    except Exception as exc:
        log.warning("langfuse_trace_finalize_failed", task=task, error=str(exc))
    finally:
        try:
            get_langfuse().flush()
        except Exception as exc:
            log.warning("langfuse_flush_failed", task=task, error=str(exc))

    if campaign_id:
        async with get_db() as conn:
            from sqlalchemy import text

            try:
                await conn.execute(
                    text(
                        """
                        INSERT INTO campaign_cost_attribution
                            (campaign_id, org_id, brand_id, agent_name, model_alias,
                             model_resolved, provider, input_tokens, output_tokens,
                             total_cost_usd, latency_ms)
                        VALUES
                            (:campaign_id, :org_id, :brand_id, :agent_name, :model_alias,
                             :model_resolved, :provider, :input_tokens, :output_tokens,
                             :total_cost_usd, :latency_ms)
                        """
                    ),
                    {
                        "campaign_id": campaign_id,
                        "org_id": state.get("org_id"),
                        "brand_id": state.get("brand_id"),
                        "agent_name": agent,
                        "model_alias": model,
                        "model_resolved": resolved_model,
                        "provider": provider,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_cost_usd": cost,
                        "latency_ms": latency_ms,
                    },
                )
                await conn.commit()
            except Exception as exc:
                await conn.rollback()
                log.warning(
                    "campaign_cost_attribution_write_failed",
                    campaign_id=campaign_id,
                    agent=agent,
                    error=str(exc),
                )

    return content, {
        "cost": cost,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
    }


async def safe_agent_run(
    agent_fn: Callable[[OmniBrandState], Awaitable[dict]],
    state: OmniBrandState,
    task_id: str | None = None,
) -> dict:
    """Wraps every agent call. Catches all exceptions, writes error to state,
    and allows the pipeline to continue with degraded output. Never lets an
    exception propagate to LangGraph."""
    agent_name = getattr(agent_fn, "__name__", str(agent_fn))
    try:
        return await agent_fn(state)
    except Exception as exc:
        log.error("agent_failed", agent=agent_name, task_id=task_id, error=str(exc))
        error_msg = f"{agent_name} failed"
        if task_id:
            error_msg += f" (task_id={task_id})"
        error_msg += f": {exc}"
        result: dict = {"errors": [error_msg]}
        if task_id:
            result["failed_task_ids"] = [task_id]
        return result


AGENT_WRITE_PERMISSIONS: dict[str, set[str]] = {
    "intake_agent": {
        "brief",
        "rag_context",
        "prior_campaigns",
        "brief_valid",
        "brief_validation_errors",
        "budget_check_passed",
        "tasks",
        "current_phase",
        "token_cost_usd",
        "errors",
    },
    "content_generator": {
        "variants",
        "failed_task_ids",
        "token_cost_usd",
        "current_phase",
        "errors",
    },
    "personalization_agent": {"variants", "token_cost_usd", "errors"},
    "translation_agent": {"variants", "token_cost_usd", "errors"},
    "judge_gate": {"judge_mode"},
    "judge_claude": {"brand_scores", "errors"},
    "judge_gpt4o": {"brand_scores", "errors"},
    "judge_llama": {"brand_scores", "errors"},
    "confidence_aggregator": {
        "aggregated_scores",
        "review_requests",
        "human_review_requested",
    },
    "reflexion": {"variants", "brand_scores", "aggregated_scores", "errors"},
    "review_gate": {"variants", "current_phase", "review_round"},
    "publishing_agent": {"publication_receipts", "variants", "current_phase", "errors"},
}
