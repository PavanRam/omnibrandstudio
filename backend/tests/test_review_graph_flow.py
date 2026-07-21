"""T11 — end-to-end graph flow: interrupt before review_gate, then resume.

Uses an in-memory checkpointer (MemorySaver) and a mocked LLM so the full
LangGraph pipeline runs offline (no Docker / Postgres / LiteLLM).
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from pipeline.graph import build_graph
from pipeline.initial_state import build_initial_state
from pipeline.schemas import CreateCampaignRequest

_GOOD_CONTENT = "Subject: Launch\n\nHello developers. Learn more: https://example.com"


@pytest.fixture
def mock_llm(monkeypatch):
    async def fake(model, messages, task, state, **kwargs):
        return _GOOD_CONTENT, {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    async def no_examples(*args, **kwargs):
        return []

    monkeypatch.setattr("pipeline.agents.content_generator.traced_llm_call", fake)
    monkeypatch.setattr("pipeline.agents.personalization.traced_llm_call", fake)
    # Avoid loading the real RAG / sentence-transformer models in a unit test.
    monkeypatch.setattr("pipeline.agents.content_generator.get_examples", no_examples)


def _brief() -> CreateCampaignRequest:
    return CreateCampaignRequest(
        brand_id="brand-1", objective="Launch", target_audience="developers",
        key_messages=["fast feedback"], channels=["email"], locales=["en-US"],
        audience_segments=["core"], token_budget=2000, raw_text="",
    )


def _initial(cid: str):
    return build_initial_state(
        campaign_id=cid, org_id="org-1", brand_id="brand-1",
        user_id="u1", request_id="r1", brief=_brief(),
    )


async def test_graph_pauses_before_review_gate(mock_llm):
    graph = build_graph(MemorySaver(), interrupt_before_review_gate=True)
    cfg = {"configurable": {"thread_id": "camp-pause"}}

    await graph.ainvoke(_initial("camp-pause"), cfg)

    snap = await graph.aget_state(cfg)
    assert snap.next == ("review_gate",)  # paused, not finished
    assert snap.values["human_review_requested"] is True
    assert len(snap.values["review_requests"]) >= 1


async def test_approved_decision_resumes_and_publishes(mock_llm):
    graph = build_graph(MemorySaver(), interrupt_before_review_gate=True)
    cfg = {"configurable": {"thread_id": "camp-approve"}}

    await graph.ainvoke(_initial("camp-approve"), cfg)
    snap = await graph.aget_state(cfg)
    task_ids = [r["variant_id"] for r in snap.values["review_requests"]]

    decisions = {t: {"decision": "approved"} for t in task_ids}
    await graph.aupdate_state(cfg, {"review_decisions": decisions})
    final = await graph.ainvoke(None, cfg)

    assert final["current_phase"] == "published"
    approved = [v for v in final["variants"] if v["status"] == "approved"]
    assert approved
    assert all(v["final_content"] for v in approved)


async def test_rejected_decision_resumes_and_reruns(mock_llm):
    graph = build_graph(MemorySaver(), interrupt_before_review_gate=True)
    cfg = {"configurable": {"thread_id": "camp-reject"}}

    await graph.ainvoke(_initial("camp-reject"), cfg)
    snap = await graph.aget_state(cfg)
    task_ids = [r["variant_id"] for r in snap.values["review_requests"]]

    decisions = {t: {"decision": "rejected"} for t in task_ids}
    await graph.aupdate_state(cfg, {"review_decisions": decisions})
    await graph.ainvoke(None, cfg)

    snap2 = await graph.aget_state(cfg)
    # rejected -> regenerated -> paused again at the gate for the next round
    assert snap2.next == ("review_gate",)
    assert snap2.values["review_round"] == 1
