import asyncio
import json
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
    "traced_llm_call_stream",
    "write_audit",
    "safe_agent_run",
    "publish_campaign_event",
    "AGENT_WRITE_PERMISSIONS",
    "LLMCallError",
]


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


class LLMCallError(RuntimeError):
    """A traced_llm_call attempt exhausted its retries (or hit a
    non-retriable error) without a real model response. Deliberately a real
    exception, not a fabricated string — see traced_llm_call's docstring
    for why this replaced the old silent-fallback behavior (2026-07-27).
    Propagates to safe_agent_run, the existing, already-in-place mechanism
    every agent already relies on to turn a raised exception into a clean
    per-task/per-variant failure — this class doesn't change how that
    happens, only ensures a real failure actually reaches it instead of
    being disguised as a successful (fabricated) response."""


# HTTP statuses worth retrying — genuinely transient (rate limit, upstream
# provider hiccup). Everything else (400/401/403/404/422/...) is a
# permanent/configuration problem retrying can't fix.
_RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.0, 2.0)  # delay before attempt 2, then before attempt 3


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
            payload = None
            last_exc: httpx.HTTPError | None = None
            last_status = 0
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(
                        "/chat/completions",
                        json={"model": model, "messages": messages, **kwargs},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    span.set_attribute("http.status_code", response.status_code)
                    span.set_attribute("llm.attempts", attempt)
                    break
                except httpx.HTTPError as exc:
                    last_exc = exc
                    last_status = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
                    retriable = last_status in _RETRIABLE_STATUS_CODES
                    if not retriable or attempt == _MAX_ATTEMPTS:
                        break
                    delay = _BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)]
                    log.warning(
                        "llm_call_http_failed_retrying",
                        agent=agent,
                        task=task,
                        model=model,
                        status_code=last_status,
                        attempt=attempt,
                        delay_seconds=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)

            if payload is None:
                # Every attempt failed (or the first failure was non-retriable) —
                # raise a real error instead of fabricating content that would
                # silently look like a genuine model response to the caller and
                # anything downstream (quality gates, judges, truthfulness
                # checks). safe_agent_run — already wrapping every agent body,
                # unchanged here — turns this into a clean per-task/per-variant
                # failure, exactly as it already does for any other exception.
                span.set_attribute("http.status_code", last_status)
                span.set_attribute("llm.failed", True)
                log.error(
                    "llm_call_failed",
                    agent=agent,
                    task=task,
                    model=model,
                    status_code=last_status,
                    error=str(last_exc),
                )
                raise LLMCallError(
                    f"{task}: LLM call to {model} failed after retries (status={last_status}): {last_exc}"
                ) from last_exc

    latency_ms = int((time.perf_counter() - start) * 1000)
    content = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    cost = float(payload.get("_hidden_params", {}).get("response_cost", 0.0) or 0.0)
    resolved_model = str(payload.get("model") or model)
    provider = resolved_model.split("/")[0]

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


async def traced_llm_call_stream(
    model: str,
    messages: list[dict],
    task: str,
    state: dict,
    **kwargs: Any,
):
    """Compatibility streaming wrapper.

    Some callers expect a chunked async iterator. When upstream streaming is
    unavailable, we still preserve behavior by yielding one full chunk.
    """
    content, _ = await traced_llm_call(
        model=model,
        messages=messages,
        task=task,
        state=state,
        **kwargs,
    )
    if content:
        yield content


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
        "current_task",
        "user_edit_note",
        "errors",
    },
    "personalization_agent": {"variants", "token_cost_usd", "current_phase", "errors"},
    "translation_agent": {"variants", "token_cost_usd", "current_phase", "errors"},
    "judge_gate": {"judge_mode", "current_phase"},
    "judge_claude": {"brand_scores", "errors"},
    "judge_gpt4o": {"brand_scores", "errors"},
    "judge_llama": {"brand_scores", "errors"},
    "confidence_aggregator": {
        "aggregated_scores",
        "review_requests",
        "human_review_requested",
        "current_phase",
    },
    "reflexion": {"variants", "brand_scores", "aggregated_scores", "current_phase", "errors"},
    "review_gate": {"variants", "current_phase", "review_round"},
    "publishing_agent": {"publication_receipts", "variants", "current_phase", "errors"},
}
