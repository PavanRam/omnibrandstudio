import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.middleware.request_id import RequestIDMiddleware
from core.metrics import REGISTRY, http_request_duration, http_requests_total
from core.tracing import instrument_fastapi, setup_observability


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.database import close_db, init_db
    from core.qdrant import close_qdrant, init_qdrant
    from core.redis import close_redis, init_redis

    setup_observability("omnibrand-api")
    instrument_fastapi(app)

    await init_db()
    await init_redis()
    await init_qdrant()
    yield
    await close_db()
    await close_redis()
    await close_qdrant()


app = FastAPI(
    title="OmniBrand Studio API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware stack (order matters: outermost first) ────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestIDMiddleware)


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

from api.routers import auth, campaigns, health, knowledge, orgs  # noqa: E402

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(orgs.router, prefix="/orgs", tags=["orgs"])
app.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
