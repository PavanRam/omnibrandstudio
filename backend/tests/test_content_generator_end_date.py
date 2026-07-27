"""content_generator threads brief.end_date into the generation prompt.

See next_tasks.md 2026-07-26 item 16 — optional campaign validity/expiry
date, extracted during brief collection, should actually show up in
generated copy ("Offer valid through...") rather than just sitting unused
in the brief.
"""
import pytest

from pipeline.agents import content_generator as cg


def _state(end_date: str | None) -> dict:
    return {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "brand_id": "brand-1",
        "model_aliases": {},
        "brand_config": {},
        "brief": {
            "objective": "drive signups",
            "target_audience": "professionals",
            "key_messages": [],
            "tone_override": None,
            "channels": ["twitter"],
            "locales": ["en-US"],
            "audience_segments": ["consumer"],
            "token_budget": 1000,
            "end_date": end_date,
            "raw_text": "",
        },
        "tasks": [
            {
                "task_id": "en-US_twitter_consumer",
                "locale": "en-US",
                "channel": "twitter",  # no required_elements -> passes first attempt
                "segment": "consumer",
                "channel_constraints": {},
            }
        ],
        "rag_context": None,
        "errors": [],
    }


@pytest.fixture
def stub_llm(monkeypatch):
    calls: list[list[dict]] = []

    async def fake(model, messages, task, state, **kwargs):
        calls.append(messages)
        return "Some generated content", {"cost": 0.001}

    async def fake_get_examples(brand_id, channel, locale, n=3):
        return []

    monkeypatch.setattr(cg, "traced_llm_call", fake)
    monkeypatch.setattr(cg, "get_examples", fake_get_examples)
    return calls


@pytest.mark.asyncio
async def test_end_date_appears_in_generation_prompt_when_present(stub_llm) -> None:
    await cg.content_generator(_state("March 31"))

    all_content = " ".join(m["content"] for m in stub_llm[0])
    assert "March 31" in all_content
    assert "valid through" in all_content.lower()


@pytest.mark.asyncio
async def test_no_end_date_message_when_absent(stub_llm) -> None:
    await cg.content_generator(_state(None))

    all_content = " ".join(m["content"] for m in stub_llm[0])
    assert "valid through" not in all_content.lower()
