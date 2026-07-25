import asyncio
import json
import sys
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import ValidationError
from prometheus_client import start_http_server as _prom_start_http_server
from sqlalchemy import text

from core.config import settings
from core.metrics import (
    REGISTRY,
    campaign_duration,
    campaigns_completed_total,
    campaigns_started_total,
    dlq_messages_total,
    queue_depth,
)
from core.redis import close_redis, get_redis, init_redis
from core.tracing import setup_observability
from pipeline.graph import build_graph
from pipeline.initial_state import build_initial_state
from pipeline.schemas import CreateCampaignRequest
from services import review_service

log = structlog.get_logger()

QUEUE = "campaigns:queue"
DLQ = "campaigns:dead_letter"


def _to_psycopg_dsn(raw_dsn: str) -> str:
    """Return a psycopg-compatible DSN and escape bare percent signs in auth.

    Some local passwords include `%` and are not URL-encoded. psycopg's URL parser
    rejects these with `invalid percent-encoded token`. We only sanitize the
    netloc/userinfo portion and keep host/path/query untouched.
    """
    dsn = raw_dsn.replace("+asyncpg", "")
    parts = urlsplit(dsn)
    if "@" not in parts.netloc:
        return dsn

    userinfo, hostpart = parts.netloc.rsplit("@", 1)
    if "%" not in userinfo:
        return dsn

    # Escape bare '%' characters so URL parsing remains valid for psycopg.
    safe_userinfo = userinfo.replace("%", "%25")
    safe_netloc = f"{safe_userinfo}@{hostpart}"
    return urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))


def _start_metrics_server() -> None:
    """Start a Prometheus metrics HTTP server on PROMETHEUS_METRICS_PORT in a
    daemon thread.  Called once before the event loop starts."""
    try:
        _prom_start_http_server(settings.PROMETHEUS_METRICS_PORT, registry=REGISTRY)
        log.info(
            "worker_metrics_server_started",
            port=settings.PROMETHEUS_METRICS_PORT,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("worker_metrics_server_failed", error=str(exc))


async def process_campaign(task_payload: dict) -> None:
    campaign_id = task_payload["campaign_id"]
    org_id = task_payload.get("org_id", "unknown")
    request_id = task_payload.get("request_id", "")
    brief_payload = task_payload.get("brief")
    brief: CreateCampaignRequest | None = None
    if isinstance(brief_payload, dict):
        try:
            brief = CreateCampaignRequest.model_validate(brief_payload)
        except ValidationError as exc:
            log.warning(
                "campaign_brief_payload_invalid",
                campaign_id=campaign_id,
                error=str(exc),
            )
    initial_state = build_initial_state(
        campaign_id=campaign_id,
        org_id=org_id,
        brand_id=task_payload["brand_id"],
        user_id=task_payload.get("user_id", ""),
        request_id=request_id,
        brief=brief,
    )

    # Propagate W3C trace context injected by the API at enqueue time
    from opentelemetry.propagate import extract
    from opentelemetry import trace, context as otel_context
    ctx = extract(task_payload.get("_trace_context", {}))
    token = otel_context.attach(ctx)

    tracer = trace.get_tracer("omnibrand.worker")
    start = datetime.now(UTC)
    campaigns_started_total.labels(org_id=org_id).inc()

    # Persist dequeue transition so API status reflects that worker picked it up.
    from core.database import get_db

    async with get_db() as conn:
        await conn.execute(
            text(
                """
                UPDATE campaigns
                SET status = 'running',
                    started_at = COALESCE(started_at, NOW())
                WHERE id = CAST(:campaign_id AS UUID)
                """
            ),
            {"campaign_id": campaign_id},
        )
        await conn.commit()

    log.info(
        "campaign_processing",
        campaign_id=campaign_id,
        org_id=org_id,
        request_id=request_id,
    )

    try:
        with tracer.start_as_current_span("worker.process_campaign") as span:
            span.set_attribute("campaign_id", campaign_id)
            span.set_attribute("org_id", org_id)
            span.set_attribute("request_id", request_id)

            psycopg_dsn = _to_psycopg_dsn(settings.POSTGRES_DSN)
            async with AsyncPostgresSaver.from_conn_string(psycopg_dsn) as checkpointer:
                await checkpointer.setup()
                graph = build_graph(checkpointer)
                config = {"configurable": {"thread_id": campaign_id}}
                final_state = await graph.ainvoke(initial_state, config=config)

        final_status = "running"
        mark_completed = False
        paused_for_review = False
        if isinstance(final_state, dict):
            current_phase = str(final_state.get("current_phase") or "").lower()
            has_errors = bool(final_state.get("errors"))
            budget_failed = final_state.get("budget_check_passed") is False
            brief_invalid = final_state.get("brief_valid") is False

            if current_phase == "published":
                final_status = "published"
                mark_completed = True
            elif has_errors or budget_failed or brief_invalid:
                final_status = "failed"
                mark_completed = True
            else:
                # Successful non-terminal runs are paused for human review.
                final_status = "awaiting_review"
                paused_for_review = True

        if paused_for_review:
            # Persists variants/aggregated_scores/review_requests and sets
            # campaigns.status='awaiting_review' itself — skip the generic
            # status UPDATE below for this case.
            await review_service.persist_review_batch(final_state)
        else:
            async with get_db() as conn:
                await conn.execute(
                    text(
                        """
                        UPDATE campaigns
                        SET status = :status,
                            completed_at = CASE WHEN :mark_completed THEN NOW() ELSE completed_at END,
                            token_cost_usd = COALESCE((
                                SELECT SUM(total_cost_usd)
                                FROM campaign_cost_attribution
                                WHERE campaign_id = campaigns.id
                            ), 0)
                        WHERE id = CAST(:campaign_id AS UUID)
                        """
                    ),
                    {
                        "campaign_id": campaign_id,
                        "status": final_status,
                        "mark_completed": mark_completed,
                    },
                )
                await conn.commit()

        elapsed = (datetime.now(UTC) - start).total_seconds()
        campaign_duration.labels(org_id=org_id, status="completed").observe(elapsed)
        campaigns_completed_total.labels(org_id=org_id, status="completed").inc()

    except Exception:
        async with get_db() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE campaigns
                    SET status = 'failed',
                        completed_at = NOW(),
                        token_cost_usd = COALESCE((
                            SELECT SUM(total_cost_usd)
                            FROM campaign_cost_attribution
                            WHERE campaign_id = campaigns.id
                        ), 0)
                    WHERE id = CAST(:campaign_id AS UUID)
                    """
                ),
                {"campaign_id": campaign_id},
            )
            await conn.commit()

        elapsed = (datetime.now(UTC) - start).total_seconds()
        campaign_duration.labels(org_id=org_id, status="failed").observe(elapsed)
        campaigns_completed_total.labels(org_id=org_id, status="failed").inc()
        raise
    finally:
        otel_context.detach(token)


async def main() -> None:
    from core.database import close_db, init_db
    from core.langfuse import get_langfuse

    await init_db()
    await init_redis()
    redis = get_redis()
    log.info("worker_started", queue=QUEUE)
    try:
        while True:
            # Update queue-depth gauge on each iteration
            try:
                depth = await redis.llen(QUEUE)
                queue_depth.set(depth)
            except Exception:  # noqa: BLE001
                pass

            item = await redis.blpop(QUEUE, timeout=5)
            if item is None:
                continue
            _, payload = item
            task = json.loads(payload)
            try:
                await process_campaign(task)
                log.info("campaign_processed", campaign_id=task.get("campaign_id"))
            except Exception as exc:
                log.error(
                    "campaign_failed",
                    campaign_id=task.get("campaign_id"),
                    error=str(exc),
                )
                await redis.rpush(DLQ, json.dumps({**task, "error": str(exc)}))
                dlq_messages_total.inc()
    finally:
        await close_redis()
        get_langfuse().flush()
        await close_db()


if __name__ == "__main__":
    # psycopg async mode is incompatible with Windows ProactorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    setup_observability("omnibrand-worker")
    _start_metrics_server()
    asyncio.run(main())
