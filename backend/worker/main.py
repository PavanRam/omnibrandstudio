import asyncio
import json
import sys
from datetime import UTC, datetime

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from prometheus_client import start_http_server as _prom_start_http_server

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

log = structlog.get_logger()

QUEUE = "campaigns:queue"
DLQ = "campaigns:dead_letter"


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
    initial_state = build_initial_state(
        campaign_id=campaign_id,
        org_id=org_id,
        brand_id=task_payload["brand_id"],
        user_id=task_payload.get("user_id", ""),
        request_id=request_id,
    )

    # Propagate W3C trace context injected by the API at enqueue time
    from opentelemetry.propagate import extract
    from opentelemetry import trace, context as otel_context
    ctx = extract(task_payload.get("_trace_context", {}))
    token = otel_context.attach(ctx)

    tracer = trace.get_tracer("omnibrand.worker")
    start = datetime.now(UTC)
    campaigns_started_total.labels(org_id=org_id).inc()

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

            # AsyncPostgresSaver uses psycopg — strip the asyncpg driver suffix
            psycopg_dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
            async with AsyncPostgresSaver.from_conn_string(psycopg_dsn) as checkpointer:
                await checkpointer.setup()
                graph = build_graph(checkpointer)
                config = {"configurable": {"thread_id": campaign_id}}
                await graph.ainvoke(initial_state, config=config)

        elapsed = (datetime.now(UTC) - start).total_seconds()
        campaign_duration.labels(org_id=org_id, status="completed").observe(elapsed)
        campaigns_completed_total.labels(org_id=org_id, status="completed").inc()

    except Exception:
        elapsed = (datetime.now(UTC) - start).total_seconds()
        campaign_duration.labels(org_id=org_id, status="failed").observe(elapsed)
        campaigns_completed_total.labels(org_id=org_id, status="failed").inc()
        raise
    finally:
        otel_context.detach(token)


async def main() -> None:
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


if __name__ == "__main__":
    # psycopg async mode is incompatible with Windows ProactorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    setup_observability("omnibrand-worker")
    _start_metrics_server()
    asyncio.run(main())
