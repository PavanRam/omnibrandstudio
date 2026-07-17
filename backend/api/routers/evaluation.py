from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.config import settings
from core.ids import new_campaign_id
from pipeline.graph import build_graph
from pipeline.initial_state import build_initial_state
from pipeline.schemas import CreateCampaignRequest

router = APIRouter()
log = structlog.get_logger()


@router.post("/local-eval", status_code=status.HTTP_200_OK)
async def local_eval(body: CreateCampaignRequest, request: Request) -> dict:
    campaign_id = new_campaign_id()
    request_id = getattr(request.state, "request_id", "")
    started_at = datetime.now(UTC)

    state = build_initial_state(
        campaign_id=campaign_id,
        org_id=body.brand_id,
        brand_id=body.brand_id,
        user_id="local-eval",
        request_id=request_id,
        brief=body,
    )

    try:
        if settings.LOCAL_DEV_MODE:
            # TEMP_LOCAL_EVAL: In local-dev mode run graph without Postgres checkpointer.
            graph = build_graph(interrupt_before_review_gate=False)
            final_state = await graph.ainvoke(
                state,
                config={"configurable": {"thread_id": campaign_id}},
            )
        else:
            psycopg_dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
            async with AsyncPostgresSaver.from_conn_string(psycopg_dsn) as checkpointer:
                await checkpointer.setup()
                graph = build_graph(
                    checkpointer,
                    interrupt_before_review_gate=False,
                )
                final_state = await graph.ainvoke(
                    state,
                    config={"configurable": {"thread_id": campaign_id}},
                )
    except Exception as exc:
        log.error(
            "local_eval_failed",
            campaign_id=campaign_id,
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "campaign_id": campaign_id,
                "status": "failed",
                "error": str(exc),
            },
        ) from exc

    elapsed_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
    log.info(
        "local_eval_completed",
        campaign_id=campaign_id,
        request_id=request_id,
        elapsed_ms=elapsed_ms,
    )

    return {
        "campaign_id": campaign_id,
        "status": "completed",
        "elapsed_ms": elapsed_ms,
        "final_state": final_state,
    }
