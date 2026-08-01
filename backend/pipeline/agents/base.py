import json
import re
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
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
    "traced_embedding_call",
    "traced_llm_call",
    "traced_llm_call_stream",
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


def _scrub_messages_pii(messages: list[dict], *, agent: str, task: str) -> None:
    """Redact PII from user message content in place before it is sent to the LLM."""
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


def _scrub_output_pii(content: str, *, agent: str, task: str) -> str:
    """Redact PII from assistant output before it leaves the wrapper."""
    redacted, pii_types = _scrub_pii(content)
    if pii_types:
        log.warning(
            "guardrail_pii_redacted",
            agent=agent,
            task=task,
            pii_types=pii_types,
            direction="output",
        )
        return redacted
    return content


async def traced_embedding_call(
    model: str,
    texts: list[str],
    task: str,
    state: dict[str, Any] | None = None,
    *,
    dimensions: int,
) -> tuple[list[list[float]], dict[str, Any]]:
    """Call LiteLLM's embedding endpoint with standard tracing signals.

    The caller owns fallback behavior so a semantic embedding failure cannot
    be mistaken for a successful hosted response.
    """
    if not texts:
        return [], {
            "cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": 0,
            "model_resolved": model,
        }

    context = state or {}
    campaign_id = context.get("campaign_id")
    request_id = str(context.get("request_id", ""))
    scrubbed_texts = [_scrub_pii(text)[0] for text in texts]
    tracer = get_tracer("omnibrand.embeddings")
    trace = start_langfuse_trace(
        name=task,
        session_id=campaign_id,
        metadata={
            "model": model,
            "request_id": request_id,
            "org_id": context.get("org_id"),
            "input_count": len(scrubbed_texts),
            "dimensions": dimensions,
        },
    )

    start = time.perf_counter()
    with tracer.start_as_current_span("embeddings.call") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.task", task)
        span.set_attribute("embedding.input_count", len(scrubbed_texts))
        span.set_attribute("embedding.dimensions", dimensions)
        async with httpx.AsyncClient(base_url=settings.LITELLM_BASE_URL, timeout=60) as client:
            response = await client.post(
                "/embeddings",
                json={
                    "model": model,
                    "input": scrubbed_texts,
                    "dimensions": dimensions,
                },
            )
            response.raise_for_status()
            payload = response.json()
            span.set_attribute("http.status_code", response.status_code)

    ordered = sorted(payload.get("data", []), key=lambda item: int(item.get("index", 0)))
    vectors = [[float(value) for value in item["embedding"]] for item in ordered]
    if len(vectors) != len(scrubbed_texts):
        raise ValueError(
            f"embedding response count mismatch: expected {len(scrubbed_texts)}, got {len(vectors)}"
        )
    if any(len(vector) != dimensions for vector in vectors):
        lengths = sorted({len(vector) for vector in vectors})
        raise ValueError(f"embedding dimension mismatch: expected {dimensions}, got {lengths}")

    latency_ms = int((time.perf_counter() - start) * 1000)
    usage = payload.get("usage", {})
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    cost = float(payload.get("_hidden_params", {}).get("response_cost", 0.0) or 0.0)
    resolved_model = str(payload.get("model") or model)

    llm_call_duration.labels(agent="embeddings", model=model, task=task).observe(
        latency_ms / 1000
    )
    llm_tokens_total.labels(agent="embeddings", model=model, type="input").inc(input_tokens)
    llm_cost_usd_total.labels(agent="embeddings", model=model).inc(cost)

    try:
        trace.update(
            output={
                "vector_count": len(vectors),
                "dimensions": dimensions,
                "model_resolved": resolved_model,
            }
        )
        end_fn = getattr(trace, "end", None)
        if callable(end_fn):
            end_fn()
    finally:
        get_langfuse().flush()

    return vectors, {
        "cost": cost,
        "input_tokens": input_tokens,
        "output_tokens": 0,
        "latency_ms": latency_ms,
        "model_resolved": resolved_model,
    }


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


async def _finalize_llm_call(
    *,
    content: str,
    payload: dict[str, Any],
    usage: dict[str, Any],
    latency_ms: int,
    model: str,
    task: str,
    agent: str,
    state: dict,
    campaign_id: str | None,
    trace: Any,
) -> dict[str, Any]:
    """Shared post-response accounting for LLM calls (streaming and not).

    Records Prometheus metrics, finalizes the Langfuse trace, writes the
    per-agent ``campaign_cost_attribution`` row, and pushes a live cost delta to
    the campaign SSE stream. Returns the usage metadata dict. Extracted so that
    ``traced_llm_call`` and ``traced_llm_call_stream`` share one accounting path
    (never bypass it — see the CLAUDE.md invariant on ``traced_llm_call``).
    """
    input_tokens = usage.get("prompt_tokens", 0) or 0
    output_tokens = usage.get("completion_tokens", 0) or 0
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
            else:
                # Push a live cost delta to the campaign SSE stream so the
                # workspace cost/token banner updates as the pipeline runs,
                # without the user having to send a chat turn. Deltas are
                # additive on the client; the WS turn response reconciles the
                # authoritative cumulative total (e.g. after a page refresh).
                await publish_campaign_event(
                    campaign_id=campaign_id,
                    agent=agent,
                    phase="cost_update",
                    payload={
                        "delta_cost_usd": cost,
                        "delta_input_tokens": input_tokens,
                        "delta_output_tokens": output_tokens,
                    },
                )

    return {
        "cost": cost,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
    }


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
    campaign_id = state.get("campaign_id")
    request_id = state.get("request_id", "")
    agent = kwargs.pop("agent", task)
    tracer = get_tracer(f"omnibrand.{agent}")

    _scrub_messages_pii(messages, agent=agent, task=task)

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
                # LiteLLM proxy always adds x-litellm-response-cost to the
                # response headers. The JSON body does not include it (that's
                # a Python-SDK-only field). Inject it so _extract_response_cost
                # finds it without any changes to that helper.
                _cost_hdr = response.headers.get("x-litellm-response-cost")
                if _cost_hdr:
                    try:
                        payload.setdefault("_hidden_params", {})["response_cost"] = float(_cost_hdr)
                    except (ValueError, TypeError):
                        pass
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
    content = _scrub_output_pii(content, agent=agent, task=task)
    usage = payload.get("usage", {})

    return content, await _finalize_llm_call(
        content=content,
        payload=payload,
        usage=usage,
        latency_ms=latency_ms,
        model=model,
        task=task,
        agent=agent,
        state=state,
        campaign_id=campaign_id,
        trace=trace,
    )


async def traced_llm_call_stream(
    model: str,
    messages: list[dict],
    task: str,
    state: dict,
    **kwargs: Any,
) -> AsyncGenerator[str, None]:
    """Streaming sibling of ``traced_llm_call``.

    Yields assistant content deltas as they arrive from the LiteLLM proxy, then
    performs the SAME cost accounting as ``traced_llm_call`` via the shared
    ``_finalize_llm_call`` helper (in a ``finally`` so accounting runs even if the
    consumer stops iterating early, e.g. a WebSocket disconnect). On a transport
    error it falls back to a single non-streaming chunk. This does not bypass the
    ``traced_llm_call`` invariant — it is a peer in the same module with identical
    accounting.
    """
    campaign_id = state.get("campaign_id")
    request_id = state.get("request_id", "")
    agent = kwargs.pop("agent", task)
    tracer = get_tracer(f"omnibrand.{agent}")

    _scrub_messages_pii(messages, agent=agent, task=task)

    trace = start_langfuse_trace(
        name=task,
        session_id=campaign_id,
        metadata={"model": model, "request_id": request_id, "org_id": state.get("org_id")},
    )

    start = time.perf_counter()
    content_parts: list[str] = []
    usage: dict[str, Any] = {}
    resolved_model: str | None = None
    _stream_cost_hdr: str | None = None
    accounted = False

    with tracer.start_as_current_span(f"{agent}.llm_call_stream") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.task", task)
        span.set_attribute("campaign_id", campaign_id or "")
        span.set_attribute("request_id", request_id)
        span.set_attribute("llm.stream", True)

        request_body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            **kwargs,
        }

        try:
            async with httpx.AsyncClient(base_url=settings.LITELLM_BASE_URL, timeout=120) as client:
                async with client.stream("POST", "/chat/completions", json=request_body) as response:
                    response.raise_for_status()
                    _stream_cost_hdr = response.headers.get("x-litellm-response-cost")
                    span.set_attribute("http.status_code", response.status_code)
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("model"):
                            resolved_model = str(chunk["model"])
                        # Usage arrives on the final chunk when include_usage is set.
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        for choice in chunk.get("choices", []):
                            delta = (choice.get("delta") or {}).get("content")
                            if delta:
                                content_parts.append(delta)
                                yield delta

            # Successful stream — account for it exactly once.
            latency_ms = int((time.perf_counter() - start) * 1000)
            content = _scrub_output_pii("".join(content_parts), agent=agent, task=task)
            payload = {"model": resolved_model or model, "usage": usage}
            # Inject the response-cost header (same as the non-streaming path).
            if _stream_cost_hdr:
                try:
                    payload.setdefault("_hidden_params", {})["response_cost"] = float(_stream_cost_hdr)
                except (ValueError, TypeError):
                    pass
            accounted = True
            await _finalize_llm_call(
                content=content,
                payload=payload,
                usage=usage,
                latency_ms=latency_ms,
                model=model,
                task=task,
                agent=agent,
                state=state,
                campaign_id=campaign_id,
                trace=trace,
            )
        except httpx.HTTPError as exc:
            # Transport failure: emit a single fallback chunk so the consumer
            # always sees at least one delta, and still account (zero-cost).
            status_code = getattr(getattr(exc, "response", None), "status_code", 0)
            span.set_attribute("http.status_code", int(status_code or 0))
            span.set_attribute("llm.fallback", True)
            log.warning(
                "llm_stream_http_failed_using_fallback",
                agent=agent,
                task=task,
                model=model,
                status_code=status_code,
                error=str(exc),
            )
            if not content_parts:
                fallback = _fallback_content_from_messages(messages)
                content_parts.append(fallback)
                yield fallback
        finally:
            if not accounted:
                latency_ms = int((time.perf_counter() - start) * 1000)
                content = _scrub_output_pii("".join(content_parts), agent=agent, task=task)
                payload = {
                    "model": resolved_model or f"fallback/{model}",
                    "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0},
                    "_hidden_params": {"response_cost": 0.0},
                }
                await _finalize_llm_call(
                    content=content,
                    payload=payload,
                    usage=payload["usage"],
                    latency_ms=latency_ms,
                    model=model,
                    task=task,
                    agent=agent,
                    state=state,
                    campaign_id=campaign_id,
                    trace=trace,
                )


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
        "guardrail_flags",
    },
    "personalization_agent": {"variants", "token_cost_usd", "errors", "guardrail_flags"},
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
