"""No-Docker FastAPI entrypoint for quick pipeline evaluation.

Runs the real OmniBrandState graph end-to-end in-process with an in-memory
checkpointer. The code is still production grade, only execution is local and ephemeral.
Run with:
    uvicorn api.main_local:app --reload --port 8000

    uv run uvicorn api.main_local:app --reload --port 8000
"""
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.memory import MemorySaver
from pipeline.graph import build_graph
from pipeline.schemas import CreateCampaignRequest
from pipeline.state import OmniBrandState

GRAPH_STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer = MemorySaver()
    GRAPH_STATE["graph"] = build_graph(checkpointer)
    yield
    GRAPH_STATE.clear()


app = FastAPI(
    title="OmniBrand Studio API (local, no-Docker eval)",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health/live")
async def liveness() -> dict:
    return {"status": "alive"}


def _initial_state(
    campaign_id: str,
    org_id: str,
    brand_id: str,
    user_id: str,
    brief_request: CreateCampaignRequest | None = None,
) -> OmniBrandState:
    # Populate brief raw fields from the request so intake_agent can process them.
    brief_dict = (
        {
            "objective": brief_request.objective,
            "target_audience": brief_request.target_audience,
            "key_messages": brief_request.key_messages,
            "tone_override": brief_request.tone_override,
            "channels": brief_request.channels,
            "locales": brief_request.locales,
            "audience_segments": brief_request.audience_segments,
            "token_budget": brief_request.token_budget,
            "raw_text": brief_request.raw_text,
        }
        if brief_request is not None
        else None
    )
    return OmniBrandState(
        campaign_id=campaign_id,
        org_id=org_id,
        brand_id=brand_id,
        user_id=user_id,
        started_at=datetime.now(UTC).isoformat(),
        org_config={},
        brand_config={},
        model_aliases={},
        brief=brief_dict,  # type: ignore[arg-type]
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


@app.post("/campaigns/{campaign_id}/run")
async def run_campaign(campaign_id: str, body: CreateCampaignRequest) -> dict:
    graph = GRAPH_STATE.get("graph")
    if graph is None:
        raise HTTPException(500, "graph not initialized")

    initial_state = _initial_state(
        campaign_id=campaign_id,
        org_id="local-org",
        brand_id=body.brand_id,
        user_id="local-user",
        brief_request=body,
    )
    config = {"configurable": {"thread_id": campaign_id or str(uuid4())}}
    result = await graph.ainvoke(initial_state, config=config)
    return {"campaign_id": campaign_id, "state": result}
