import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

from core.config import settings
from core.database import get_db
from core.langfuse import get_langfuse, start_langfuse_trace
from core.metrics import llm_call_duration, llm_cost_usd_total, llm_tokens_total
from core.tracing import get_tracer
from pipeline.state import OmniBrandState
from services.audit_service import write_audit  # re-exported for agent use

log = structlog.get_logger()

__all__ = [
    "traced_llm_call",
    "write_audit",
    "safe_agent_run",
    "AGENT_WRITE_PERMISSIONS",
]


def _fallback_content_from_messages(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if str(msg.get("role", "")).lower() == "user":
            text = str(msg.get("content", "")).strip()
            if text:
                snippet = text[:220]
                return f"[fallback-generated] {snippet}"
    return "[fallback-generated]"


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
    "judge_claude": {"brand_scores", "token_cost_usd", "errors"},
    "judge_gpt4o": {"brand_scores", "token_cost_usd", "errors"},
    "judge_llama": {"brand_scores", "token_cost_usd", "errors"},
    "confidence_aggregator": {
        "aggregated_scores",
        "review_requests",
        "human_review_requested",
    },
    "review_gate": {"variants", "current_phase"},
    "publishing_agent": {"publication_receipts", "variants", "current_phase", "errors"},
}
