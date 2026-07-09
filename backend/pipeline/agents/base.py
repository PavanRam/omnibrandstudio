import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog
from core.config import settings

from pipeline.state import OmniBrandState

log = structlog.get_logger()

__all__ = [
    "traced_llm_call",
    "safe_agent_run",
    "AGENT_WRITE_PERMISSIONS",
]


async def traced_llm_call(
    model: str,
    messages: list[dict],
    task: str,
    state: dict,
    **kwargs: Any,
) -> tuple[str, dict]:
    """Wrapper for every LLM call in the system.

    Calls LiteLLM via httpx and returns (content, usage_metadata).
    """
    agent = kwargs.pop("agent", task)

    start = time.perf_counter()
    async with httpx.AsyncClient(base_url=settings.LITELLM_BASE_URL, timeout=60) as client:
        response = await client.post(
            "/chat/completions",
            json={"model": model, "messages": messages, **kwargs},
        )
        response.raise_for_status()
        payload = response.json()

    latency_ms = int((time.perf_counter() - start) * 1000)
    content = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    cost = payload.get("_hidden_params", {}).get("response_cost", 0.0)

    log.info(
        "llm_call",
        agent=agent,
        model=model,
        task=task,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
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
