"""intake retrieves a segment-specific brand-guide chunk in addition to the
objective-based query.

Regression (campaign 019fb455-46f3-7b86-8c5d-14ce28089692, 2026-07-30): the
objective-based RAG query for a "holiday gourmet gift box" brief was
outranked by a *different* segment's persona chunk ("Budget-Conscious Low
Spender"), so the actual target segment ("High-Income Store Spender") never
got its own CTA/tone guidance into rag_context. Both content_generator and
the judges then worked from the wrong segment's chunks; the generator's CTAs
had no textual basis in what the judges considered ground truth, and got
flagged as fabrication. A small supplementary per-segment retrieval closes
that gap.
"""
from __future__ import annotations

import pytest
from pipeline.agents import intake
from pipeline.state import OmniBrandState


def _base_state(**overrides) -> OmniBrandState:
    state = OmniBrandState(
        campaign_id="camp-1",
        org_id="org-1",
        brand_id="brand-1",
        user_id="user-1",
        request_id="req-1",
        started_at="2026-07-05T00:00:00",
        org_config={},
        brand_config={},
        model_aliases={"generation": "gen-free"},
        brief=None,
        rag_context=None,
        prior_campaigns=[],
        brief_valid=None,
        brief_validation_errors=[],
        budget_check_passed=None,
        tasks=[],
        current_task=None,
        variants=[],
        brand_scores=[],
        aggregated_scores=[],
        review_requests=[],
        publication_receipts=[],
        failed_task_ids=[],
        errors=[],
        current_phase="starting",
        human_review_requested=False,
        publishing_paused=False,
        token_cost_usd=0.0,
    )
    state.update(overrides)
    return state


class _Chunk:
    def __init__(
        self, content: str, section_type: str = "tone", version: str = "v1", score: float = 0.9
    ) -> None:
        self.content = content
        self.section_type = section_type
        self.version = version
        self.score = score


@pytest.mark.asyncio
async def test_segment_chunk_included_even_when_objective_query_misses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The objective query returns an unrelated segment's chunk; the
    supplementary per-segment query still surfaces the target segment's
    chunk into the merged rag_context."""

    calls: list[dict] = []

    class _Retriever:
        async def retrieve(self, *, query, brand_id, locale, n_results):
            calls.append({"query": query, "n_results": n_results})
            if "High-Income Store Spender" in query:
                return [_Chunk("High-Income Store Spender: primary_ctas=[Reserve Yours Today]")]
            # objective-based query surfaces an unrelated segment instead
            return [_Chunk("Budget-Conscious Low Spender: primary_ctas=[See Today's Deals]")]

    monkeypatch.setattr(intake, "get_retriever", lambda: _Retriever())

    brief = {
        "objective": "holiday gourmet gift box",
        "target_audience": "gift buyers",
        "key_messages": ["premium selection"],
        "tone_override": None,
        "channels": ["email"],
        "locales": ["en-US"],
        "audience_segments": ["High-Income Store Spender"],
        "token_budget": 2000,
        "raw_text": "holiday gourmet gift box brief",
    }
    result = await intake.intake_agent(_base_state(brief=brief))

    chunks = result["rag_context"]["brand_guide_chunks"]
    assert any("High-Income Store Spender" in c for c in chunks)
    assert any("Budget-Conscious Low Spender" in c for c in chunks)

    segment_calls = [c for c in calls if "High-Income Store Spender" in c["query"]]
    assert len(segment_calls) == 1
    assert segment_calls[0]["n_results"] == 2


@pytest.mark.asyncio
async def test_segment_retrieval_failure_does_not_break_intake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing segment-specific retrieval must not abort intake — same
    fail-open posture as the existing objective-query retrieval."""

    class _Retriever:
        async def retrieve(self, *, query, brand_id, locale, n_results):
            if "enterprise" in query:
                raise RuntimeError("chroma unavailable")
            return [_Chunk("General brand tone guidance")]

    monkeypatch.setattr(intake, "get_retriever", lambda: _Retriever())

    brief = {
        "objective": "Launch",
        "target_audience": "Developers",
        "key_messages": ["Fast"],
        "tone_override": None,
        "channels": ["email"],
        "locales": ["en-US"],
        "audience_segments": ["enterprise"],
        "token_budget": 2000,
        "raw_text": "launch brief",
    }
    result = await intake.intake_agent(_base_state(brief=brief))

    assert result["brief_valid"] is True
    assert result["rag_context"] is not None
    assert result["rag_context"]["brand_guide_chunks"] == ["General brand tone guidance"]
