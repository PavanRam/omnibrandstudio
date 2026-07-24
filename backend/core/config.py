from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root, but Makefile targets `cd backend` before running
# (e.g. `cd backend && uv run python ../scripts/seed_prompts.py`), so a plain
# relative "env_file" only resolves when the process CWD happens to be the
# repo root. Anchor it to this file's location instead so every entrypoint
# (host-side `make seed`/`migrate`/`run`, pytest, scripts/) loads the same
# values regardless of CWD — the api/worker Docker containers are unaffected
# since docker-compose injects POSTGRES_DSN etc. as real env vars directly.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT_ENV, extra="ignore")

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "changeme_app_secret_32chars_min"
    # TEMP_LOCAL_EVAL: Local-only mode to run API and local eval without infra services.
    LOCAL_DEV_MODE: bool = False
    # TEMP_LOCAL_EVAL: Explicit opt-in switch for /eval/local-eval endpoint registration.
    ENABLE_LOCAL_EVAL: bool = False
    ENABLE_CONVERSATION_PLANNER: bool = False
    # When true, the conversation WebSocket streams the assistant reply token by
    # token (delta frames) instead of sending it as one turn_complete frame.
    ENABLE_STREAMING_RESPONDER: bool = False
    # When true, chat input is screened for injection patterns + lightweight
    # toxicity before any LLM processing. Defaults False (ship dark) — matches
    # the Phase 1 flag-gated pattern.
    ENABLE_CHAT_INPUT_GUARDRAIL: bool = False
    DEV_BOOTSTRAP_ADMIN_ENABLED: bool = False
    DEV_ADMIN_ORG_ID: str = "00000000-0000-0000-0000-000000000001"
    DEV_ADMIN_BRAND_ID: str = "00000000-0000-0000-0000-000000000002"
    DEV_ADMIN_EMAIL: str = "admin@omnibrand.local"
    DEV_ADMIN_PASSWORD: str = ""

    # Database
    POSTGRES_DSN: str = "postgresql+asyncpg://omnibrand:changeme_local_32chars@localhost:5432/omnibrand"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Vector store
    VECTOR_STORE_BACKEND: str = "chroma"
    CHROMA_PERSIST_PATH: str = "./data/chroma"
    BM25_CACHE_PATH: str = "./data/bm25_cache"
    PINECONE_API_KEY: str = ""
    PINECONE_ENVIRONMENT: str = ""
    PINECONE_INDEX: str = "omnibrand-guides"
    HYBRID_FETCH_K: int = 20
    RRF_K: int = 60
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    MMR_LAMBDA: float = 0.7

    # MCP integration (optional interoperability layer)
    RAG_MCP_ENABLED: bool = False
    RAG_MCP_HOST: str = "0.0.0.0"
    RAG_MCP_PORT: int = 8001

    # RAG ingestion controls
    RAG_MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024

    # LLM
    LITELLM_BASE_URL: str = "http://localhost:4000"
    # If true, estimate cost from LiteLLM model pricing when response cost is
    # missing but tokens are present. Defaults to false so provider-reported
    # cost remains the single source of truth.
    ENABLE_COST_ESTIMATION_FALLBACK: bool = False
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DEEPL_API_KEY: str = ""
    HF_TOKEN: str = ""
    TRANSLATION_HUMAN_ESCALATION_ENABLED: bool = False

    # Judge panel tier. "free" -> Groq cross-family panel (judge-*-free), no
    # paid spend; "paid" -> pinned Claude/GPT-4o/Groq panel (judge-1/2/3).
    # Switching tiers is a config flip; it requires re-running judge
    # calibration but no agent-code changes. See docs pre-deploy checklist.
    JUDGE_TIER: str = "free"

    # Auth
    JWT_PRIVATE_KEY_PATH: str = "./certs/private_key.pem"
    JWT_PUBLIC_KEY_PATH: str = "./certs/public_key.pem"
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Observability — Langfuse
    LANGFUSE_HOST: str = "http://localhost:3001"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""

    # Observability — OpenTelemetry / Jaeger
    OTEL_ENABLED: bool = True
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"

    # Worker Prometheus metrics port (separate from API /metrics)
    PROMETHEUS_METRICS_PORT: int = 9091

    # Storage
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "omnibrand"
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "brand-assets"

    # Publishing — SMTP demo delivery via MailHog
    PUBLISH_SMTP_HOST: str = "mailhog"          # use "localhost" when running outside Docker
    PUBLISH_SMTP_PORT: int = 1025               # MailHog SMTP port; no auth, no TLS
    PUBLISH_RECIPIENT_EMAILS: str = ""          # comma-separated: "demo@acme.com,qa@acme.com"

    # Runtime
    MAX_CONCURRENT_CAMPAIGNS: int = 5
    CAMPAIGN_TIMEOUT_SECONDS: int = 300

    # Human review gate
    REVIEW_SLA_HOURS: int = 4
    MAX_REVIEW_ROUNDS: int = 2
    # Airtable outbound mirror (best-effort; no-op when any is unset)
    AIRTABLE_API_KEY: str = ""
    AIRTABLE_BASE_ID: str = ""
    AIRTABLE_TABLE: str = "Reviews"

    @property
    def private_key(self) -> str:
        with open(self.JWT_PRIVATE_KEY_PATH) as f:
            return f.read()

    @property
    def public_key(self) -> str:
        with open(self.JWT_PUBLIC_KEY_PATH) as f:
            return f.read()


settings = Settings()
