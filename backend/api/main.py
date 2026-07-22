import time
from contextlib import asynccontextmanager

from core.config import settings
from core.metrics import REGISTRY, http_request_duration, http_requests_total
from core.tracing import instrument_fastapi, setup_observability
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.middleware.request_id import RequestIDMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.database import close_db, init_db
    from core.langfuse import get_langfuse
    from core.redis import close_redis, init_redis
    from services.dev.bootstrap import ensure_dev_bootstrap

    setup_observability("omnibrand-api")
    instrument_fastapi(app)

    await init_db()
    await ensure_dev_bootstrap()
    await init_redis()
    yield
    await close_db()
    await close_redis()
    get_langfuse().flush()


app = FastAPI(
    title="OmniBrand Studio API",
    version="1.0.0",
    lifespan=lifespan,
)


def should_enable_local_eval() -> bool:
    # TEMP_LOCAL_EVAL: Route is opt-in and blocked in production environments.
    return settings.ENABLE_LOCAL_EVAL and settings.APP_ENV.lower() != "production"

# ── Middleware stack (order matters: outermost first) ────────────────────────────

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


# ── HTTP metrics (lightweight inline middleware) ────────────────────────────────

@app.middleware("http")
async def _record_http_metrics(request: Request, call_next):
    route = request.url.path
    method = request.method
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    http_requests_total.labels(
        method=method, route=route, status_code=str(response.status_code)
    ).inc()
    http_request_duration.labels(method=method, route=route).observe(duration)
    return response


# ── Prometheus metrics endpoint ────────────────────────────────────────────────────

@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


# ── Routers ──────────────────────────────────────────────────────────────────────────

from api.routers import (  # noqa: E402
    auth,
    campaigns,
    conversations,
    golden_dataset,
    health,
    knowledge,
    orgs,
    users,
)

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(orgs.router, prefix="/orgs", tags=["orgs"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
app.include_router(golden_dataset.router, prefix="/knowledge", tags=["golden-dataset"])

if should_enable_local_eval():
    # TEMP_LOCAL_EVAL: Local eval endpoint is intentionally not registered by default.
    from api.routers import evaluation  # noqa: E402

    app.include_router(evaluation.router, prefix="/eval", tags=["evaluation"])
