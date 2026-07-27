"""content_generator isolates a failing task from its siblings.

Regression (2026-07-26, campaign 019f9ecd-3d46-719f-b926-1a04b58480e4): an
unrecognized channel raised an unhandled KeyError inside render_channel_prompt,
and — since the fan-out loop had no per-task try/except, unlike
translation_agent's existing per-variant guard — that exception propagated
out of the whole node, producing zero variants for every task in the
campaign, not just the bad one.
"""
import pytest

from pipeline.agents import content_generator as cg


def _task(task_id: str, channel: str) -> dict:
    return {
        "task_id": task_id,
        "locale": "en-US",
        "channel": channel,
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
    async def fake(model, messages, task, state, **kwargs):
        return "Check out our new drop!", {"cost": 0.001}

    async def fake_get_examples(brand_id, channel, locale, n=3):
        return []

    monkeypatch.setattr(cg, "traced_llm_call", fake)
    monkeypatch.setattr(cg, "get_examples", fake_get_examples)


@pytest.mark.asyncio
async def test_one_bad_channel_does_not_kill_sibling_tasks(stub_llm) -> None:
    tasks = [
        _task("t-good", "twitter"),  # no required_elements -> passes first try
        _task("t-bad", "not_a_real_channel"),
    ]

    result = await cg.content_generator(_state(tasks))

    variants_by_id = {v["task_id"]: v for v in result["variants"]}
    assert len(result["variants"]) == 2
    assert variants_by_id["t-good"]["status"] == "generated"
    assert variants_by_id["t-good"]["generated_content"] is not None
    assert variants_by_id["t-bad"]["status"] == "failed"
    assert "not_a_real_channel" in variants_by_id["t-bad"]["failure_reason"]
    assert "t-bad" in result["failed_task_ids"]
    # safe_agent_run must not have swallowed the whole node as a hard error —
    # only the offending task is marked failed, everything else looks normal.
    assert result.get("errors") in (None, [])
