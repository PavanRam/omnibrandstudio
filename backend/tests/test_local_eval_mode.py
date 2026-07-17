from __future__ import annotations

import pytest

from core.config import settings
from core.database import check_db_health
from core.qdrant import check_qdrant_health
from core.redis import check_redis_health
from pipeline.graph import build_graph
from pipeline.initial_state import build_initial_state
from pipeline.schemas import CreateCampaignRequest


@pytest.mark.asyncio
async def test_local_graph_runs_to_end_without_checkpointer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "LOCAL_DEV_MODE", True)

    request = CreateCampaignRequest(
        brand_id="brand-1",
        objective="validate",
        target_audience="developers",
        key_messages=["fast feedback"],
        channels=["email"],
        locales=["en-US"],
        audience_segments=["core"],
        token_budget=100,
        raw_text="",
    )
    state = build_initial_state(
        campaign_id="camp-local-1",
        org_id=request.brand_id,
        brand_id=request.brand_id,
        user_id="local-eval",
        request_id="req-local-1",
        brief=request,
    )

    graph = build_graph(interrupt_before_review_gate=False)
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "camp-local-1"}})

    assert result["current_phase"] == "published"


def test_should_enable_local_eval_guard(monkeypatch: pytest.MonkeyPatch):
    from api.main import should_enable_local_eval

    monkeypatch.setattr(settings, "ENABLE_LOCAL_EVAL", True)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    assert should_enable_local_eval() is True

    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert should_enable_local_eval() is False

    monkeypatch.setattr(settings, "ENABLE_LOCAL_EVAL", False)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    assert should_enable_local_eval() is False


@pytest.mark.asyncio
async def test_local_dev_health_checks_are_deterministic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "LOCAL_DEV_MODE", True)

    assert await check_db_health() is True
    assert await check_redis_health() is True
    assert await check_qdrant_health() is True
