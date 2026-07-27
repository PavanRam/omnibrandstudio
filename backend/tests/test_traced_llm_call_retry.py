"""traced_llm_call retry/raise behavior (item 30 remainder, 2026-07-27).

Previously any HTTP error from LiteLLM — including an ordinary retriable
429 — was silently treated as "just fake it": a fabricated
"[fallback-generated] <prompt snippet>" string was returned as if it were
real model output, never retried, never raised. This was the confirmed
root cause of a real translation failure earlier this session (a
rate-limited call produced fabricated garbage that then failed every
quality-gate metric simultaneously against a real reference).

Fix: retriable statuses (429/500/502/503/504) get retried with backoff;
everything else — and a retriable status that's still failing after
retries are exhausted — now raises LLMCallError instead of fabricating
content. safe_agent_run (unchanged, already wraps every pipeline agent)
turns that into a clean per-task/per-variant failure, same as any other
exception; chat call sites already have their own try/except around
traced_llm_call (conversation_responder.py) or are protected by an outer
one (understanding_engine.py via conversations.py::_understand_turn).
"""
from __future__ import annotations

import pytest

from pipeline.agents.base import LLMCallError, traced_llm_call

pytestmark = pytest.mark.asyncio


def _state() -> dict:
    # No campaign_id -> traced_llm_call skips the campaign_cost_attribution
    # DB write entirely, keeping this test free of any DB dependency.
    return {"org_id": "org-1"}


async def test_succeeds_on_first_try_without_retry(httpx_mock) -> None:
    httpx_mock.add_response(
        json={
            "choices": [{"message": {"content": "real answer"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            "model": "gen-premium",
            "_hidden_params": {"response_cost": 0.001},
        }
    )

    content, usage = await traced_llm_call(
        model="gen-premium", messages=[{"role": "user", "content": "hi"}], task="test", state=_state()
    )

    assert content == "real answer"
    assert usage["cost"] == 0.001
    assert len(httpx_mock.get_requests()) == 1


async def test_retries_on_429_then_succeeds(httpx_mock) -> None:
    httpx_mock.add_response(status_code=429)
    httpx_mock.add_response(
        json={
            "choices": [{"message": {"content": "recovered"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "model": "gen-premium",
            "_hidden_params": {"response_cost": 0.0},
        }
    )

    content, _ = await traced_llm_call(
        model="gen-premium", messages=[{"role": "user", "content": "hi"}], task="test", state=_state()
    )

    assert content == "recovered"
    assert len(httpx_mock.get_requests()) == 2


async def test_raises_after_exhausting_retries_on_persistent_429(httpx_mock) -> None:
    for _ in range(3):
        httpx_mock.add_response(status_code=429)

    with pytest.raises(LLMCallError):
        await traced_llm_call(
            model="gen-premium", messages=[{"role": "user", "content": "hi"}], task="test", state=_state()
        )

    assert len(httpx_mock.get_requests()) == 3


async def test_raises_immediately_on_non_retriable_status_without_retrying(httpx_mock) -> None:
    httpx_mock.add_response(status_code=400)

    with pytest.raises(LLMCallError):
        await traced_llm_call(
            model="gen-premium", messages=[{"role": "user", "content": "hi"}], task="test", state=_state()
        )

    # A 400 is a permanent/config problem — must not burn retries on it.
    assert len(httpx_mock.get_requests()) == 1


async def test_never_fabricates_fallback_generated_content(httpx_mock) -> None:
    """The exact bug this fix closes: no HTTP failure of any kind should
    ever produce a '[fallback-generated] ...' string disguised as real
    output — it must raise instead."""
    httpx_mock.add_response(status_code=503)
    httpx_mock.add_response(status_code=503)
    httpx_mock.add_response(status_code=503)

    with pytest.raises(LLMCallError) as exc_info:
        await traced_llm_call(
            model="gen-premium",
            messages=[{"role": "user", "content": "sensitive prompt text"}],
            task="test",
            state=_state(),
        )

    assert "fallback-generated" not in str(exc_info.value)
