from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "changeme_app_secret_32chars_min"

    # LLM
    LITELLM_BASE_URL: str = "http://localhost:4000"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DEEPL_API_KEY: str = ""

    # Runtime
    MAX_CONCURRENT_CAMPAIGNS: int = 5
    CAMPAIGN_TIMEOUT_SECONDS: int = 300


settings = Settings()
