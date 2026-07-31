"""traced_llm_call must emit a Langfuse *generation* (model/usage/cost/timing),
not just a bare trace — otherwise every cost/usage/latency dashboard is empty.
Langfuse is stubbed here so no real ingestion traffic is involved.
"""
from __future__ import annotations

import pytest

from pipeline.agents import base
from pipeline.agents.base import traced_llm_call

pytestmark = pytest.mark.asyncio


class _FakeGen:
    def __init__(self) -> None:
        self.ended = False

    def end(self) -> None:
        self.ended = True


class _FakeTrace:
    id = "trace-abc"

    def __init__(self) -> None:
        self.generation_kwargs: dict | None = None
        self.gen = _FakeGen()

    def generation(self, **kwargs):
        self.generation_kwargs = kwargs
        return self.gen

    def update(self, **kwargs) -> None:
        pass

    def end(self) -> None:
        pass


class _FakeLangfuse:
    def flush(self) -> None:
        pass


async def test_traced_llm_call_emits_generation(httpx_mock, monkeypatch) -> None:
    fake_trace = _FakeTrace()
    monkeypatch.setattr(base, "start_langfuse_trace", lambda **_: fake_trace)
    monkeypatch.setattr(base, "get_langfuse", lambda: _FakeLangfuse())

    httpx_mock.add_response(
        headers={"x-litellm-response-cost": "0.002"},
        json={
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            "model": "groq/llama-3.3-70b",
        },
    )

    content, usage = await traced_llm_call(
        model="gen-free",
        messages=[{"role": "user", "content": "q"}],
        task="judge_1",
        state={"org_id": "org-1"},
    )

    assert content == "hi"
    assert usage["trace_id"] == "trace-abc"

    gk = fake_trace.generation_kwargs
    assert gk is not None
    assert gk["model"] == "groq/llama-3.3-70b"
    assert gk["usage"]["input"] == 5
    assert gk["usage"]["output"] == 3
    assert gk["usage"]["total"] == 8
    assert gk["usage"]["totalCost"] == 0.002
    assert gk["start_time"] is not None
    assert gk["end_time"] is not None
    assert fake_trace.gen.ended is True
