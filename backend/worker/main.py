import asyncio
import json
import sys
from datetime import UTC, datetime

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.config import settings
from core.redis import close_redis, get_redis, init_redis
from pipeline.graph import build_graph
from pipeline.state import OmniBrandState

log = structlog.get_logger()

QUEUE = "campaigns:queue"
DLQ = "campaigns:dead_letter"


def _initial_state(task_payload: dict) -> OmniBrandState:
    return OmniBrandState(
        campaign_id=task_payload["campaign_id"],
        org_id=task_payload["org_id"],
        brand_id=task_payload["brand_id"],
        user_id=task_payload.get("user_id", ""),
        started_at=datetime.now(UTC).isoformat(),
        org_config={},
        brand_config={},
        model_aliases={},
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


async def process_campaign(task_payload: dict) -> None:
    campaign_id = task_payload["campaign_id"]
    initial_state = _initial_state(task_payload)

    # AsyncPostgresSaver uses psycopg, which doesn't understand SQLAlchemy's
    # "+asyncpg" driver suffix in the DSN.
    psycopg_dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
    async with AsyncPostgresSaver.from_conn_string(psycopg_dsn) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = {"configurable": {"thread_id": campaign_id}}
        await graph.ainvoke(initial_state, config=config)


async def main() -> None:
    await init_redis()
    redis = get_redis()
    log.info("worker_started", queue=QUEUE)
    try:
        while True:
            # Finite timeout + loop instead of timeout=0 (block forever) —
            # an indefinite BLPOP outlives redis-py's client socket_timeout
            # and raises spuriously on some platforms/transports.
            item = await redis.blpop(QUEUE, timeout=5)
            if item is None:
                continue
            _, payload = item
            task = json.loads(payload)
            try:
                await process_campaign(task)
                log.info("campaign_processed", campaign_id=task.get("campaign_id"))
            except Exception as exc:
                log.error("campaign_failed", campaign_id=task.get("campaign_id"), error=str(exc))
                await redis.rpush(DLQ, json.dumps({**task, "error": str(exc)}))
    finally:
        await close_redis()


if __name__ == "__main__":
    # psycopg's async mode (used by AsyncPostgresSaver) is incompatible with
    # Windows' default ProactorEventLoop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
