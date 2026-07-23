"""review_gate node + post-gate router tests (offline, pure state transforms)."""
from core.config import settings
from pipeline.agents.base import AGENT_WRITE_PERMISSIONS
from pipeline.agents.review import review_gate, review_router


def _variant(task_id: str = "t1", content: str = "Subject: Hi\n\nBody. https://x.io",
             status: str = "personalized") -> dict:
    return {
        "task_id": task_id, "locale": "en-US", "channel": "email", "segment": "core",
        "generated_content": content, "personalized_content": content,
        "translated_content": None, "final_content": None, "status": status,
        "generation_model": "gen-free", "prompt_version": "v1", "brand_guide_version": None,
        "translation_engine": None, "back_translation_score": None, "retry_count": 0,
        "reflexion_applied": False, "failure_reason": None,
    }


def _state(variants: list[dict], decisions: dict | None = None, review_round: int = 0) -> dict:
    return {
        "campaign_id": "c1", "variants": variants, "review_decisions": decisions or {},
        "review_round": review_round, "current_phase": "awaiting_review", "errors": [],
    }


async def test_approved_sets_final_content_and_status():
    v = _variant()
    result = await review_gate(_state([v], {"t1": {"decision": "approved"}}))
    assert v["status"] == "approved"
    assert v["final_content"] == v["personalized_content"]
    assert result["current_phase"] == "review_complete"


async def test_edited_uses_reviewer_content():
    v = _variant()
    await review_gate(_state([v], {"t1": {"decision": "edited", "edited_content": "REWRITTEN"}}))
    assert v["status"] == "edited"
    assert v["final_content"] == "REWRITTEN"


async def test_rejected_marks_variant_and_increments_round():
    v = _variant()
    result = await review_gate(_state([v], {"t1": {"decision": "rejected"}}, review_round=0))
    assert v["status"] == "rejected"
    assert result["review_round"] == 1


async def test_undecided_variant_passes_through_as_final():
    v = _variant()
    await review_gate(_state([v], decisions={}))
    assert v["final_content"] == v["personalized_content"]


async def test_review_gate_only_writes_permitted_keys():
    v = _variant()
    result = await review_gate(_state([v], {"t1": {"decision": "approved"}}))
    assert set(result) <= AGENT_WRITE_PERMISSIONS["review_gate"]


def test_router_reruns_on_reject_under_cap():
    state = _state([_variant(status="rejected")], review_round=1)
    assert review_router(state) == "content_generator"


def test_router_publishes_when_nothing_rejected():
    state = _state([_variant(status="approved")], review_round=0)
    assert review_router(state) == "publishing_agent"


def test_router_stops_rerunning_past_cap():
    state = _state([_variant(status="rejected")], review_round=settings.MAX_REVIEW_ROUNDS + 1)
    assert review_router(state) == "publishing_agent"
