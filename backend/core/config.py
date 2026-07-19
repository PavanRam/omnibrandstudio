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
    ENABLE_CONVERSATION_PLANNER: bool = False

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

    @property
    def private_key(self) -> str:
        with open(self.JWT_PRIVATE_KEY_PATH) as f:
            return f.read()

    @property
    def public_key(self) -> str:
        with open(self.JWT_PUBLIC_KEY_PATH) as f:
            return f.read()


settings = Settings()
