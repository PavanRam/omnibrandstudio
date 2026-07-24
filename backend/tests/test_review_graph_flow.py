"""End-to-end graph flow: interrupt before review_gate, then resume.

Uses an in-memory checkpointer (MemorySaver) and mocks every LLM/retrieval call
so the full LangGraph pipeline (intake -> content_generator -> personalization
-> translation -> judge panel -> confidence_aggregator -> review_gate) runs
offline (no Docker / Postgres / LiteLLM / HF inference).

All tasks use the "en" locale so translation_agent's pass-through branch runs
(no HuggingFace/back-translation calls needed). Judge responses are pinned high
enough that the real aggregator routes every variant to "flag" (never
auto_approve), guaranteeing a review_requests entry and an interrupt.
"""
import json

import pytest
from langgraph.checkpoint.memory import MemorySaver
from pipeline.agents.prompts.judge_prompts import CRITERIA
from pipeline.graph import build_graph
from pipeline.initial_state import build_initial_state
from pipeline.schemas import CreateCampaignRequest

_GOOD_CONTENT = "Subject: Launch\n\nHello developers. Learn more: https://example.com"

# A composite ~7.0/10 (0.70 on the 0-1 scale) sits inside the aggregator's
# default review band (auto_reject=0.60, auto_approve=0.85) -> always "flag".
_JUDGE_SCORE = {
    criterion: {"score": 7.0, "reasoning": "adequate", "violations": [], "citations": []}
    for criterion in CRITERIA
}
_JUDGE_RESPONSE = json.dumps(
    {
        **_JUDGE_SCORE,
        "composite_score": 7.0,
        "critical_violations": [],
        "routing_decision": "flag",
        "routing_explanation": "mid-band composite score warrants a human review pass",
    }
)


class _FakeRetriever:
    async def retrieve(self, *args, **kwargs):
        return []

    async def get_examples(self, *args, **kwargs):
        return []


@pytest.fixture
def mock_llm(monkeypatch):
    async def fake_content(model, messages, task, state, **kwargs):
        return _GOOD_CONTENT, {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    async def fake_judge(model, messages, task, state, **kwargs):
        return _JUDGE_RESPONSE, {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    monkeypatch.setattr("pipeline.agents.content_generator.traced_llm_call", fake_content)
    monkeypatch.setattr("pipeline.agents.personalization.traced_llm_call", fake_content)
    monkeypatch.setattr("pipeline.agents.judges.traced_llm_call", fake_judge)
    monkeypatch.setattr("pipeline.agents.reflexion.traced_llm_call", fake_content)

    fake_retriever = _FakeRetriever()
    monkeypatch.setattr("pipeline.agents.intake.get_retriever", lambda: fake_retriever)
    monkeypatch.setattr("pipeline.agents.retrieval.get_retriever", lambda: fake_retriever)


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
