"""content_generator's brand-guide window matches the judge panel's, and a
cheap pre-judge grounding check retries fabricated claims before the
expensive 3-judge panel ever sees them.

See docs/plans (aggregator repeated-failure investigation, 2026-07-30): the
generator previously saw only 3 brand-guide chunks truncated to 500 chars
while judges.py `_run_judge` scored `factual_grounding` against 6 full
chunks — a fact approved in chunk 4-6 was invisible to the generator, which
then either omitted it or invented something similar and got auto_rejected
by the judges for fabrication.
"""
import pytest
from pipeline.agents import content_generator as cg


def _task(task_id: str = "t-1", channel: str = "twitter") -> dict:
    return {
        "task_id": task_id,
        "locale": "en-US",
        "channel": channel,  # twitter has no required_elements -> passes constraints first try
        "segment": "consumer",
        "channel_constraints": {},
    }


def _state(rag_context: dict | None, tasks: list[dict] | None = None) -> dict:
    return {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "brand_id": "brand-1",
        "model_aliases": {},
        "brand_config": {},
        "brief": None,
        "tasks": tasks or [_task()],
        "rag_context": rag_context,
        "errors": [],
    }


def test_build_brand_guidance_text_uses_six_untruncated_chunks() -> None:
    chunks = [f"chunk-{i} " + ("x" * 600) for i in range(8)]
    rag_context = {"brand_guide_chunks": chunks, "brand_guide_version": "v1"}

    text = cg._build_brand_guidance_text(rag_context)

    # matches judges.py `_run_judge`'s window: first 6 chunks, no per-chunk cut
    for i in range(6):
        assert chunks[i] in text
    assert chunks[6] not in text
    assert chunks[7] not in text


def test_build_brand_guidance_text_no_context() -> None:
    assert cg._build_brand_guidance_text(None) == cg.NO_CONTEXT_AVAILABLE
    assert cg._build_brand_guidance_text({}) == cg.NO_CONTEXT_AVAILABLE


@pytest.fixture
def stub_llm_and_examples(monkeypatch):
    async def fake_get_examples(brand_id, channel, locale, n=3):
        return []

    monkeypatch.setattr(cg, "get_examples", fake_get_examples)


@pytest.mark.asyncio
async def test_grounding_violation_triggers_retry_and_clears(
    stub_llm_and_examples, monkeypatch
) -> None:
    """First draft fabricates a stat; the cheap grounding check flags it; the
    generator retries and the second draft is clean."""
    calls: list[dict] = []

    async def fake(model, messages, task, state, **kwargs):
        calls.append({"task": task, "model": model, "messages": messages})
        if task == "content_generator":
            if len(calls) == 1:
                return "Save 30% today!", {"cost": 0.001}
            return "Save on your order today!", {"cost": 0.001}
        # content_generator_grounding_check
        draft = messages[-1]["content"]
        if "Save 30%" in draft:
            return '{"violations": ["30% discount is not in the brand guide"]}', {"cost": 0.0001}
        return '{"violations": []}', {"cost": 0.0001}

    monkeypatch.setattr(cg, "traced_llm_call", fake)

    rag_context = {
        "brand_guide_chunks": ["Our products are reliable."],
        "brand_guide_version": "v1",
    }
    result = await cg.content_generator(_state(rag_context))

    variant = result["variants"][0]
    assert variant["status"] == "generated"
    assert variant["generated_content"] == "Save on your order today!"
    assert variant["retry_count"] == 1

    grounding_calls = [c for c in calls if c["task"] == "content_generator_grounding_check"]
    assert len(grounding_calls) == 2  # one per generation attempt


@pytest.mark.asyncio
async def test_no_grounding_check_when_no_brand_context(
    stub_llm_and_examples, monkeypatch
) -> None:
    """Grounding check is skipped entirely (no wasted call) when there's no
    brand guide to check against."""
    calls: list[dict] = []

    async def fake(model, messages, task, state, **kwargs):
        calls.append({"task": task})
        return "Some generated content", {"cost": 0.001}

    monkeypatch.setattr(cg, "traced_llm_call", fake)

    result = await cg.content_generator(_state(None))

    assert result["variants"][0]["status"] == "generated"
    assert all(c["task"] != "content_generator_grounding_check" for c in calls)


@pytest.mark.asyncio
async def test_grounding_check_call_failure_fails_open(
    stub_llm_and_examples, monkeypatch
) -> None:
    """A transient provider failure (e.g. a free-tier model returning
    malformed JSON, raised by traced_llm_call after its own retries) inside
    the cheap pre-judge grounding check must not discard an otherwise
    constraint-passing variant. Regression for 2026-07-30: an
    eval-model-free 400/json_validate_failed here previously bubbled up
    uncaught and marked the whole task 'failed' with generated content
    thrown away, even though it had already passed _check_constraints."""

    async def fake(model, messages, task, state, **kwargs):
        if task == "content_generator":
            return "A perfectly good, constraint-passing draft.", {"cost": 0.001}
        # content_generator_grounding_check — simulate the provider blowing up
        raise RuntimeError("LLM call to eval-model-free failed after retries (status=400)")

    monkeypatch.setattr(cg, "traced_llm_call", fake)

    rag_context = {
        "brand_guide_chunks": ["Our products are reliable."],
        "brand_guide_version": "v1",
    }
    result = await cg.content_generator(_state(rag_context))

    variant = result["variants"][0]
    assert variant["status"] == "generated"
    assert variant["generated_content"] == "A perfectly good, constraint-passing draft."
    assert result.get("failed_task_ids") in (None, [])


@pytest.mark.asyncio
async def test_grounding_check_fail_open_on_unparseable_response(
    stub_llm_and_examples, monkeypatch
) -> None:
    """A malformed grounding-check response must never block generation —
    fail open, same posture as judges.py's `_parse_brand_score`."""

    async def fake(model, messages, task, state, **kwargs):
        if task == "content_generator_grounding_check":
            return "not json at all", {"cost": 0.0001}
        return "Reliable products for everyone.", {"cost": 0.001}

    monkeypatch.setattr(cg, "traced_llm_call", fake)

    rag_context = {
        "brand_guide_chunks": ["Our products are reliable."],
        "brand_guide_version": "v1",
    }
    result = await cg.content_generator(_state(rag_context))

    variant = result["variants"][0]
    assert variant["status"] == "generated"
    assert variant["retry_count"] == 0


def test_grounding_prompt_flags_unverifiable_superlatives() -> None:
    """Regression (campaign 019fb455-46f3-7b86-8c5d-14ce28089692, 2026-07-30):
    the grounding-check prompt used to tell the checker model to wave through
    "generic marketing language" broadly enough that it also waved through
    unverifiable superiority claims ("most celebrated wines", "unparalleled
    culinary delights") that the judge panel's stricter rubric rejected as
    fabrication. The prompt must now call out unverifiable superlatives
    explicitly rather than lumping them in with true non-factual tone words.
    """
    prompt = cg._GROUNDING_SYSTEM_PROMPT
    assert "superlative" in prompt.lower() or "superiority" in prompt.lower()
    assert "most celebrated" in prompt.lower() or "unparalleled" in prompt.lower()
