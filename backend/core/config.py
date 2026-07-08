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
