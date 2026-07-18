from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "changeme_app_secret_32chars_min"
    # TEMP_LOCAL_EVAL: Local-only mode to run API and local eval without infra services.
    LOCAL_DEV_MODE: bool = False
    # TEMP_LOCAL_EVAL: Explicit opt-in switch for /eval/local-eval endpoint registration.
    ENABLE_LOCAL_EVAL: bool = False

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
    # Hugging Face Inference Providers — used directly by translation_agent for
    # mBART/Helsinki-NLP MT models and MPNet embeddings (not proxied via LiteLLM).
    HF_TOKEN: str = ""

    # Auth
    JWT_PRIVATE_KEY_PATH: str = "./certs/private_key.pem"
    JWT_PUBLIC_KEY_PATH: str = "./certs/public_key.pem"
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
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

    # Runtime
    MAX_CONCURRENT_CAMPAIGNS: int = 5
    CAMPAIGN_TIMEOUT_SECONDS: int = 300
    # Placeholder toggle for translation_agent's gate-failure escalation path.
    # Inert today: translation_agent has no AGENT_WRITE_PERMISSIONS entry for
    # human_review_requested/review_requests, so flipping this doesn't yet do
    # anything beyond logging intent — wired for real once confidence_aggregator
    # reads ContentVariant.translation_gate_status.
    TRANSLATION_HUMAN_ESCALATION_ENABLED: bool = False

    @property
    def private_key(self) -> str:
        with open(self.JWT_PRIVATE_KEY_PATH) as f:
            return f.read()

    @property
    def public_key(self) -> str:
        with open(self.JWT_PUBLIC_KEY_PATH) as f:
            return f.read()


settings = Settings()
