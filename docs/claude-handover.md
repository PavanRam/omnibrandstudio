# Claude Session Handover — OmniBrand Studio Phase 0

Paste this entire document into a fresh Claude session as the first message to resume work with full context. It is self-contained: no prior conversation history is assumed.

---

## 1. Concrete Codebase State

### Directory tree (repo root: `omnibrandstudio/`)

```
omnibrandstudio/
├── .env / .env.example
├── .gitignore
├── .python-version              (3.12)
├── LICENSE
├── Makefile
├── Procfile
├── README.md
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
├── docs/
│   ├── implementation-deep-dive.md
│   └── claude-handover.md       (this file)
├── certs/
│   ├── .gitkeep
│   ├── private_key.pem          (git-ignored, RSA 2048 JWT signing key)
│   └── public_key.pem           (git-ignored)
├── infra/
│   ├── litellm/litellm_config.yaml
│   ├── prometheus/prometheus.yml
│   ├── grafana/provisioning/{datasources,dashboards}/*.yml
│   └── nginx/nginx.conf         (currently unused — no nginx service in compose)
├── scripts/
│   ├── generate_certs.sh
│   ├── generate_certs.ps1
│   ├── make.ps1                 (PowerShell mirror of Makefile)
│   ├── seed_prompts.py
│   └── smoke_test.py
└── backend/
    ├── Dockerfile                (two-stage: builder / runtime)
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py                (async engine, dual-DSN resolution)
    │   ├── script.py.mako
    │   └── versions/001_core_schema.py   (single migration, ~22 tables)
    ├── api/
    │   ├── main.py                (FastAPI app + lifespan)
    │   ├── deps.py                (UserContext, get_current_user, require())
    │   ├── middleware/auth.py     (JWT RS256 + lockout + API-key hashing)
    │   └── routers/
    │       ├── health.py          (fully implemented — real DB/Redis/Qdrant checks)
    │       ├── auth.py            (501 stubs: /token, /refresh, /logout)
    │       ├── campaigns.py       (501 stubs: create/run/get/status)
    │       ├── orgs.py            (501 stubs: create/get)
    │       └── knowledge.py       (501 stubs: brand-guide upload/list)
    ├── core/
    │   ├── config.py              (Pydantic Settings — includes RSA/JWT fields)
    │   ├── database.py            (asyncpg engine singleton)
    │   ├── redis.py               (redis.asyncio singleton)
    │   ├── qdrant.py              (AsyncQdrantClient singleton)
    │   ├── metrics.py             (Prometheus CollectorRegistry + 4 metrics)
    │   └── langfuse.py            (NullLangfuse fallback)
    ├── pipeline/
    │   ├── state.py               (OmniBrandState TypedDict — THE core contract)
    │   ├── schemas.py             (Pydantic v2 request/response models)
    │   ├── graph.py                (StateGraph wiring)
    │   └── agents/
    │       ├── base.py            (traced_llm_call, safe_agent_run, AGENT_WRITE_PERMISSIONS)
    │       └── stubs.py           (10 stub agents + reflexion_router_stub)
    ├── services/
    │   ├── audit_service.py       (write_audit with field scrubbing)
    │   └── prompt_service.py      (PromptService: cache/render/record_performance)
    ├── worker/
    │   └── main.py                (Redis BLPOP loop + LangGraph invocation)
    └── tests/
        ├── conftest.py            (Windows event-loop-policy fix)
        └── test_pipeline_skeleton.py   (5 tests, all passing)
```

### Full file contents — `Makefile`

```makefile
.PHONY: install install-dev run worker dev test test-unit test-integration smoke lint format migrate migrate-down migrate-history seed up down logs certs setup

# ── Dependencies ─────────────────────────────────────────────────────────────
install:
	uv sync

install-dev:
	uv sync --dev

# ── Local development ─────────────────────────────────────────────────────────
run:
	cd backend && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	cd backend && uv run python -m worker.main

dev:
	honcho start

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	cd backend && uv run pytest tests/ -v --timeout=60

test-unit:
	cd backend && uv run pytest tests/unit/ -v

test-integration:
	cd backend && uv run pytest tests/integration/ -v --timeout=120

smoke:
	uv run python scripts/smoke_test.py

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	cd backend && uv run ruff check .
	cd backend && uv run mypy . --ignore-missing-imports

format:
	cd backend && uv run ruff format .
	cd backend && uv run ruff check . --fix

# ── Database ──────────────────────────────────────────────────────────────────
migrate:
	cd backend && uv run alembic upgrade head

migrate-down:
	cd backend && uv run alembic downgrade -1

migrate-history:
	cd backend && uv run alembic history

seed:
	cd backend && uv run python ../scripts/seed_prompts.py

# ── Infrastructure ────────────────────────────────────────────────────────────
up:
	docker compose up -d --wait

down:
	docker compose down -v

logs:
	docker compose logs -f api worker

# ── TLS / JWT keys ────────────────────────────────────────────────────────────
certs:
	mkdir -p certs
	openssl genrsa -out certs/private_key.pem 2048
	openssl rsa -in certs/private_key.pem -pubout -out certs/public_key.pem
	chmod 600 certs/private_key.pem
	@echo "JWT keys generated in certs/"

# ── Full local setup (run once after cloning) ────────────────────────────────
setup: install certs up migrate seed
	@echo ""
	@echo "Foundation ready. Run 'make smoke' to verify."
	@echo "Run 'make run' (API) + 'make worker' (worker) or 'make dev' (both)."
```

### Full file contents — `Procfile`

```
web:    uv run uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4
worker: uv run python -m worker.main
```

### Full file contents — `pyproject.toml`

```toml
[project]
name = "omnibrand"
version = "0.1.0"
description = "OmniBrand Studio — agentic content platform"
requires-python = ">=3.12"

dependencies = [
    # web
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "python-multipart>=0.0.12",

    # database
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "psycopg[binary]>=3.2",  # required by langgraph-checkpoint-postgres

    # cache / queue
    "redis[hiredis]>=5.2",

    # vector store
    "qdrant-client>=1.13",

    # auth
    "python-jose[cryptography]>=3.3",
    "bcrypt>=4.2",
    "passlib>=1.7",

    # ai / llm
    "langchain-core>=0.3",
    "langgraph>=0.2",
    "langgraph-checkpoint-postgres>=2.0",
    "litellm>=1.55",
    "langfuse>=2.0",
    "openai>=1.59",
    "anthropic>=0.42",

    # observability
    "prometheus-client>=0.21",
    "opentelemetry-sdk>=1.29",
    "opentelemetry-exporter-otlp>=1.29",

    # security / pii
    "presidio-analyzer>=2.2",
    "presidio-anonymizer>=2.2",

    # config
    "pydantic>=2.10",
    "pydantic-settings>=2.7",

    # utilities
    "python-dotenv>=1.0",
    "httpx>=0.28",
    "anyio>=4.7",
    "structlog>=24.4",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["backend"]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-httpx>=0.32",
    "ruff>=0.8",
    "mypy>=1.13",
    "types-redis>=4.6",
    "types-passlib>=1.7",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
```

### Full file contents — `backend/api/main.py`

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.database import close_db, init_db
    from core.qdrant import close_qdrant, init_qdrant
    from core.redis import close_redis, init_redis

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routers import auth, campaigns, health, knowledge, orgs  # noqa: E402

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(orgs.router, prefix="/orgs", tags=["orgs"])
app.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
```

### Full file contents — `backend/worker/main.py`

```python
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
```

### Full file contents — `backend/pipeline/state.py`

```python
from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class CampaignBrief(TypedDict):
    objective: str
    target_audience: str
    key_messages: list[str]
    tone_override: str | None
    channels: list[str]
    locales: list[str]
    audience_segments: list[str]
    token_budget: int
    raw_text: str


class GenerationTask(TypedDict):
    task_id: str  # format: "{locale}_{channel}_{segment}"
    locale: str
    channel: str
    segment: str
    channel_constraints: dict


class ContentVariant(TypedDict):
    task_id: str
    locale: str
    channel: str
    segment: str
    generated_content: str | None
    personalized_content: str | None
    translated_content: str | None
    final_content: str | None
    status: str
    generation_model: str | None
    prompt_version: str | None
    brand_guide_version: str | None
    translation_engine: str | None
    back_translation_score: float | None
    retry_count: int
    reflexion_applied: bool
    failure_reason: str | None


class CriterionScore(TypedDict):
    score: float
    reasoning: str
    violations: list[str]
    citations: list[str]


class BrandScore(TypedDict):
    variant_id: str
    judge_model: str
    composite_score: float
    scores: dict[str, CriterionScore]
    critical_violations: list[str]
    routing_decision: str
    evaluation_latency_ms: int


class AggregatedScore(TypedDict):
    variant_id: str
    judge_scores: list[float]
    weighted_mean: float
    variance: float
    consensus_level: str
    any_critical_violation: bool
    critical_violations: list[str]
    routing_decision: str
    routing_reason: str
    degraded_mode: bool


class ReviewRequest(TypedDict):
    review_request_id: str
    variant_id: str
    campaign_id: str
    routing_reason: str
    scores_snapshot: list[BrandScore]
    status: str


class PublicationReceipt(TypedDict):
    variant_id: str
    channel: str
    locale: str
    platform_publication_id: str | None
    public_url: str | None
    adapter_used: str
    publish_status: str
    published_at: str | None
    error_message: str | None


class RAGContext(TypedDict):
    brand_guide_chunks: list[str]
    section_types: list[str]
    brand_guide_version: str
    retrieval_scores: list[float]


class PriorCampaignContext(TypedDict):
    campaign_id: str
    brief_summary: str
    top_performing_channel: str | None
    avg_brand_score: float | None


class OmniBrandState(TypedDict):
    # Identity
    campaign_id: str
    org_id: str
    brand_id: str
    user_id: str
    started_at: str

    # Configuration (immutable after intake)
    org_config: dict
    brand_config: dict
    model_aliases: dict[str, str]

    # Brief (set by Intake Agent)
    brief: CampaignBrief | None

    # Context (set by Intake Agent)
    rag_context: RAGContext | None
    prior_campaigns: list[PriorCampaignContext]
    brief_valid: bool | None
    brief_validation_errors: list[str]
    budget_check_passed: bool | None

    # Task plan
    tasks: list[GenerationTask]
    current_task: GenerationTask | None

    # Accumulated results (operator.add fan-in)
    variants: Annotated[list[ContentVariant], operator.add]
    brand_scores: Annotated[list[BrandScore], operator.add]
    aggregated_scores: Annotated[list[AggregatedScore], operator.add]
    review_requests: Annotated[list[ReviewRequest], operator.add]
    publication_receipts: Annotated[list[PublicationReceipt], operator.add]
    failed_task_ids: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]

    # Pipeline control
    current_phase: str
    human_review_requested: bool
    publishing_paused: bool

    # Cost tracking
    token_cost_usd: float
```

### Full file contents — `backend/pipeline/graph.py`

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pipeline.agents.stubs import (
    confidence_aggregator_stub,
    content_generator_stub,
    intake_agent_stub,
    judge_claude_stub,
    judge_gpt4o_stub,
    judge_llama_stub,
    personalization_agent_stub,
    publishing_agent_stub,
    reflexion_router_stub,
    review_gate_stub,
    translation_agent_stub,
)
from pipeline.state import OmniBrandState


def build_graph(checkpointer: AsyncPostgresSaver) -> CompiledStateGraph:
    g = StateGraph(OmniBrandState)

    g.add_node("intake_agent", intake_agent_stub)
    g.add_node("content_generator", content_generator_stub)
    g.add_node("personalization_agent", personalization_agent_stub)
    g.add_node("translation_agent", translation_agent_stub)
    g.add_node("judge_claude", judge_claude_stub)
    g.add_node("judge_gpt4o", judge_gpt4o_stub)
    g.add_node("judge_llama", judge_llama_stub)
    g.add_node("confidence_aggregator", confidence_aggregator_stub)
    g.add_node("review_gate", review_gate_stub)
    g.add_node("publishing_agent", publishing_agent_stub)

    g.set_entry_point("intake_agent")
    g.add_edge("intake_agent", "content_generator")
    g.add_edge("content_generator", "personalization_agent")
    g.add_edge("personalization_agent", "translation_agent")
    g.add_edge("translation_agent", "judge_claude")
    g.add_edge("translation_agent", "judge_gpt4o")
    g.add_edge("translation_agent", "judge_llama")
    g.add_edge("judge_claude", "confidence_aggregator")
    g.add_edge("judge_gpt4o", "confidence_aggregator")
    g.add_edge("judge_llama", "confidence_aggregator")

    # reflexion_router_stub is a routing function, not a node — it is used
    # directly as the conditional-edge selector. "validation_subgraph" is a
    # logical label mapped to the real "judge_claude" node; END proceeds.
    g.add_conditional_edges(
        "confidence_aggregator",
        reflexion_router_stub,
        {"validation_subgraph": "judge_claude", END: "review_gate"},
    )

    g.add_edge("review_gate", "publishing_agent")
    g.add_edge("publishing_agent", END)

    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["review_gate"],
    )
```

### Full file contents — `backend/core/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "changeme_app_secret_32chars_min"

    # Database
    POSTGRES_DSN: str = "postgresql+asyncpg://omnibrand:changeme_local_32chars@localhost:5432/omnibrand"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Vector store
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    # LLM
    LITELLM_BASE_URL: str = "http://localhost:4000"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DEEPL_API_KEY: str = ""

    # Auth
    JWT_PRIVATE_KEY_PATH: str = "./certs/private_key.pem"
    JWT_PUBLIC_KEY_PATH: str = "./certs/public_key.pem"
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Observability
    LANGFUSE_HOST: str = "http://localhost:3001"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""

    # Storage
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "omnibrand"
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "brand-assets"

    # Runtime
    MAX_CONCURRENT_CAMPAIGNS: int = 5
    CAMPAIGN_TIMEOUT_SECONDS: int = 300

    @property
    def private_key(self) -> str:
        with open(self.JWT_PRIVATE_KEY_PATH) as f:
            return f.read()

    @property
    def public_key(self) -> str:
        with open(self.JWT_PUBLIC_KEY_PATH) as f:
            return f.read()


settings = Settings()
```

---

## 2. Immutable Architectural Constraints

These rules are non-negotiable unless the user explicitly instructs otherwise in a given session. Do not silently deviate.

1. **Dependency management is `uv`-only.** Never run `pip install`, `pip freeze`, or hand-edit `pyproject.toml`'s `dependencies` array without also running `uv sync` afterward to regenerate `uv.lock`. Never hand-edit `uv.lock` directly — it is a generated artifact.
2. **All commands route through `Makefile` (bash/CI) or `scripts/make.ps1` (native Windows).** If you add a new operational command (a new migration step, a new script), add corresponding targets to *both* files so they stay in parity. Do not introduce a third, undocumented way to run something.
3. **RS256 JWT authentication is intentional and must be preserved.** `backend/core/config.py`'s `JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`/`JWT_ALGORITHM`/`private_key`/`public_key`, `backend/api/middleware/auth.py`'s `create_access_token`/`decode_access_token`/`is_jti_revoked`/`revoke_jti`, and `backend/api/deps.py`'s dual JWT/API-key `get_current_user()` are current, correct, working code. Do not remove, "simplify to HS256," or otherwise alter this auth mechanism unless the user explicitly asks for that specific change in the current session — a past session considered removing it and the user reversed that decision.
4. **Async-only for agent/DB/Redis/Qdrant code paths.** Every function that touches `core/database.py`, `core/redis.py`, `core/qdrant.py`, or is registered as a LangGraph node must be `async def`. The one deliberate exception is `reflexion_router_stub` in `backend/pipeline/agents/stubs.py`, which is a synchronous conditional-edge routing function by LangGraph convention (routing functions are sync; node functions are async) — do not "fix" this by making it async, and do not make a future real router implementation async either.
5. **`AGENT_WRITE_PERMISSIONS` (in `backend/pipeline/agents/base.py`) must stay in sync with the graph's actual node names** (`intake_agent`, `content_generator`, `personalization_agent`, `translation_agent`, `judge_claude`, `judge_gpt4o`, `judge_llama`, `confidence_aggregator`, `review_gate`, `publishing_agent` — not the `_stub`-suffixed function names). `backend/tests/test_pipeline_skeleton.py::test_agent_write_permissions` enforces this; any new agent node must get a corresponding entry.
6. **Never let more than one parallel LangGraph branch write the same non-fan-in `OmniBrandState` field in the same super-step.** Only `variants`, `brand_scores`, `aggregated_scores`, `review_requests`, `publication_receipts`, `failed_task_ids`, `errors` are `Annotated[..., operator.add]` and safe for concurrent writes. All other fields (including `token_cost_usd`) are plain and will raise `INVALID_CONCURRENT_GRAPH_UPDATE` if two parallel nodes (e.g. the three judge nodes) both try to write them in the same step — this already happened once and was fixed by removing `token_cost_usd` from the judge stubs. Route per-call cost tracking through `campaign_cost_attribution` (a DB insert via `traced_llm_call`) instead of the in-memory state field when multiple parallel nodes need to record cost.
7. **The Windows event-loop-policy workaround must be preserved wherever `AsyncPostgresSaver` is constructed directly.** `psycopg`'s async mode is incompatible with Windows' default `ProactorEventLoop`. `backend/worker/main.py` and `backend/tests/conftest.py` both set `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` guarded by `sys.platform == "win32"`. Any new script or module that constructs `AsyncPostgresSaver` (e.g. a future `/campaigns/{id}/review` resume endpoint) needs this same guard, applied before any event loop is created.
8. **`AsyncPostgresSaver` needs a plain `postgresql://` DSN, not SQLAlchemy's `+asyncpg` variant.** Always strip the driver suffix (`settings.POSTGRES_DSN.replace("+asyncpg", "")`) before passing to `AsyncPostgresSaver.from_conn_string()`.
9. **`langgraph_checkpoints` is deliberately not a hand-authored table.** Do not add one back to a migration. `AsyncPostgresSaver.setup()` (called at the top of `process_campaign()` in `worker/main.py`) owns and manages the real checkpoint schema.
10. **`mypy strict = true` applies to the whole `backend/` tree.** Every new function needs full type annotations; do not introduce untyped or `Any`-typed public functions without a specific reason.
11. **Redis blocking calls must use a finite timeout, never `timeout=0`.** `BLPOP`/similar with an indefinite block conflicts with redis-py's client-side `socket_timeout`. The worker uses `timeout=5` in a `while True` loop; follow this pattern for any future Redis consumer.

---

## 3. Immediate Backlog Checklist

Concrete, file-scoped next steps building directly on the Phase 0 foundation described above. Ordered roughly by dependency (earlier items unblock later ones).

- [ ] **Implement real `/auth/token` issuance** in `backend/api/routers/auth.py`. Verify user credentials against the `users` table (`password_hash`, using `passlib`/`bcrypt`, both already a dependency), call the account-lockout helpers already implemented in `backend/api/middleware/auth.py` (`is_locked_out`, `record_failed_login`, `clear_failed_logins`), then call the already-implemented `create_access_token()` to issue a real JWT. Wire `/auth/refresh` against `user_sessions.token_hash` and `/auth/logout` to call `revoke_jti()`.
- [ ] **Implement `/campaigns` CRUD** in `backend/api/routers/campaigns.py` against the `campaigns` table (schema already exists — see `backend/alembic/versions/001_core_schema.py`). `POST /campaigns` should validate against `pipeline/schemas.py`'s `CreateCampaignRequest`, insert a `campaigns` row with `status='draft'`. `POST /campaigns/{id}/run` should transition to `status='queued'` and `rpush` onto `campaigns:queue` (the same queue `backend/worker/main.py` already consumes) — this replaces `scripts/smoke_test.py`'s current direct-Redis-enqueue workaround.
- [ ] **Implement the review-gate resume path.** Nothing currently resumes a LangGraph run past its `interrupt_before=["review_gate"]` pause (see deep-dive §9). Add an endpoint (e.g. `POST /campaigns/{id}/review`) that validates a `pipeline/schemas.py::ReviewDecision` payload, then calls `graph.ainvoke(None, config={"configurable": {"thread_id": campaign_id}})` against the same `AsyncPostgresSaver`-backed graph to continue from the last checkpoint into `publishing_agent`.
- [ ] **Replace stub agents with real LLM-calling implementations**, one at a time, starting with `intake_agent_stub` in `backend/pipeline/agents/stubs.py`. Each replacement must call `traced_llm_call()` (already implemented in `backend/pipeline/agents/base.py`) rather than hand-rolling an LLM call, and must wrap its body with `safe_agent_run()` (defined but not yet wired into `build_graph()` — this is the first real usage) so a failed LLM call degrades gracefully instead of crashing the whole graph run.
- [ ] **Wire Presidio PII scrubbing.** `presidio-analyzer`/`presidio-anonymizer` are already installed dependencies (§3 of the deep-dive) but have zero call sites anywhere in `backend/`. Likely integration point: `services/audit_service.py`'s `write_audit()` (currently only does exact-key-name scrubbing via `SENSITIVE_FIELDS`) or a new `services/pii_service.py` invoked before content ever reaches `content_variants.generated_content`.
- [ ] **Add integration tests for `backend/api/deps.py` and `backend/api/middleware/auth.py`.** Zero test coverage currently exists for `_authenticate_jwt`, `_authenticate_api_key`, `require()`, `create_access_token`/`decode_access_token`, or the lockout helpers — only the pipeline/graph layer has tests today (`backend/tests/test_pipeline_skeleton.py`).
- [ ] **Create the `backend/tests/unit/` and `backend/tests/integration/` directories** that `make test-unit`/`make test-integration` already reference but which don't exist yet — decide the split (likely: `unit/` for `core/`+`services/` with mocked DB/Redis, `integration/` for real-container-backed tests like the existing `test_pipeline_skeleton.py`, which could move there).
- [ ] **Add worker-side Prometheus metrics exposure.** `infra/prometheus/prometheus.yml` already scrapes `worker:9091` but no `/metrics` endpoint or HTTP server exists in `backend/worker/main.py` — this target currently shows as permanently down in Prometheus.
- [ ] **Decide on `infra/nginx/nginx.conf`'s fate** — either wire an `nginx` service into `docker-compose.yml` to actually use it as an ingress/reverse-proxy layer, or remove the file since it currently has no effect on the running stack.
- [ ] **Add a future-year `audit_log` partition** (e.g. `audit_log_2027`) via a new Alembic migration before 2027-01-01, or inserts into `audit_log` will start failing again with `no partition of relation "audit_log" found for row` — see the deep-dive's §5 bug writeup for the exact failure mode.
