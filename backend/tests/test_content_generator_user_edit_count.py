"""A manual per-channel variant edit must not consume reflexion's one-retry
budget.

Regression: `_regenerate_single_task` previously bumped `retry_count` on
every user-driven edit, even though `retry_count` is reflexion's round
counter and is load-bearing for round-keyed dedup in
judges.py::_already_scored / reflexion.py::_latest_aggregate. A variant
edited once via the UI before ever reaching judging would enter judging at
retry_count=1 and permanently forfeit its one legitimate reflexion retry if
later auto_rejected (reflexion.py's `if round_ > 0: return None` hard cap) —
sinking the whole campaign under the all-or-nothing gate for no reason
related to reflexion ever having run. Manual edits now bump a separate
`user_edit_count` field instead.
"""
from __future__ import annotations

import pytest
from pipeline.agents import content_generator as cg
from pipeline.agents import reflexion


def _existing_variant() -> dict:
    return {
        "task_id": "email_consumer",
        "locale": "en-US",
        "channel": "email",
        "segment": "consumer",
        "generated_content": "Old draft",
        "personalized_content": None,
        "translated_content": None,
        "final_content": None,
        "status": "generated",
        "generation_model": "gen-free",
        "prompt_version": "v1.0.0",
        "brand_guide_version": None,
        "translation_engine": None,
        "back_translation_score": None,
        "retry_count": 0,
        "reflexion_applied": False,
        "failure_reason": None,
    }


def _state(variant: dict, current_task: dict) -> dict:
    return {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "brand_id": "brand-1",
        "model_aliases": {},
        "brand_config": {},
        "brief": None,
        "tasks": [],
        "current_task": current_task,
        "variants": [variant],
        "rag_context": None,
        "user_edit_note": "Make it punchier",
        "errors": [],
    }


@pytest.fixture
def stub_llm(monkeypatch):
    async def fake(model, messages, task, state, **kwargs):
        if task == "content_generator_grounding_check":
            return '{"violations": []}', {"cost": 0.0}
        return "New punchier draft", {"cost": 0.001}

    async def fake_get_examples(brand_id, channel, locale, n=3):
        return []

    monkeypatch.setattr(cg, "traced_llm_call", fake)
    monkeypatch.setattr(cg, "get_examples", fake_get_examples)


@pytest.mark.asyncio
async def test_manual_edit_bumps_user_edit_count_not_retry_count(stub_llm) -> None:
    variant = _existing_variant()
    # channel_constraints overrides required_elements to [] below, so the
    # draft doesn't need a subject_line/cta to pass structural constraints.
    task = {
        "task_id": "email_consumer",
        "channel": "email",
        "segment": "consumer",
        "channel_constraints": {"required_elements": []},
    }

    result = await cg.content_generator(_state(variant, task))

    edited = result["variants"][0]
    assert edited["task_id"] == "email_consumer"
    assert edited["retry_count"] == 0
    assert edited["user_edit_count"] == 1
    assert edited["generated_content"] == "New punchier draft"


@pytest.mark.asyncio
async def test_two_manual_edits_still_leave_reflexion_eligible(stub_llm, monkeypatch) -> None:
    variant = _existing_variant()
    task = {
        "task_id": "email_consumer",
        "channel": "email",
        "segment": "consumer",
        "channel_constraints": {"required_elements": []},
    }

    result = await cg.content_generator(_state(variant, task))
    edited_once = result["variants"][0]
    result_2 = await cg.content_generator(_state(edited_once, task))
    edited_twice = result_2["variants"][0]

    assert edited_twice["retry_count"] == 0
    assert edited_twice["user_edit_count"] == 2

    # Reflexion keys eligibility off retry_count, not user_edit_count — two
    # manual edits must not have used up the one reflexion retry.
    async def fake_reflexion_llm(model, messages, task, state, **kwargs):
        return "Rewritten content", {"cost": 0.001}

    monkeypatch.setattr(reflexion, "traced_llm_call", fake_reflexion_llm)

    aggregate = {
        "variant_id": "email_consumer",
        "routing_decision": "auto_reject",
        "weighted_mean": 0.3,
        "critical_violations": ["fabricated claim"],
    }
    reflex_reason = await reflexion._maybe_reflex_variant(
        state={"model_aliases": {}, "rag_context": None, "campaign_id": "camp-1"},
        variant=edited_twice,
        aggregates=[aggregate],
        brand_scores=[],
        model="eval-model-free",
    )
    # None would mean "hard-capped" (round_ > 0) — the two manual edits must
    # not have triggered that cap, since it keys off retry_count.
    assert reflex_reason is not None
    assert edited_twice["retry_count"] == 1  # reflexion itself bumped it now
