"""content_generator agent-label regression test.

Ensures the `agent` kwarg passed to traced_llm_call always identifies the
real agent ("content_generator"), independent of whatever task= string is
used for Langfuse/OTel tracing -- this is what makes per-agent Prometheus
and dashboard grouping (omnibrand_llm_tokens_total{agent=...}) trustworthy.
"""
import pytest
from pipeline.agents import content_generator as cg


def _task(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "locale": "en-US",
        "channel": "twitter",  # no required_elements -> first attempt always passes
        "segment": "consumer",
        "channel_constraints": {},
    }


def _state(tasks: list[dict]) -> dict:
    return {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "brand_id": "brand-1",
        "model_aliases": {},
        "brand_config": {},
        "brief": None,
        "tasks": tasks,
        "rag_context": None,
        "errors": [],
    }


@pytest.fixture
def stub_llm(monkeypatch):
    calls: list[dict] = []

    async def fake(model, messages, task, state, **kwargs):
        calls.append({"task": task, "agent": kwargs.get("agent")})
        return "Check out our new drop!", {"cost": 0.001}

    async def fake_get_examples(brand_id, channel, locale, n=3):
        return []

    monkeypatch.setattr(cg, "traced_llm_call", fake)
    monkeypatch.setattr(cg, "get_examples", fake_get_examples)
    return calls


async def test_traced_llm_call_receives_explicit_agent_label(stub_llm):
    await cg.content_generator(_state([_task("t-1")]))

    assert len(stub_llm) == 1
    assert stub_llm[0]["task"] == "content_generator"
    assert stub_llm[0]["agent"] == "content_generator"
