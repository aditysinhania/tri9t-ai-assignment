from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ct200-manual-api"
    app_env: str = "development"

    database_url: str = "sqlite:///./ct200.db"

    # MongoDB — used for LLM generation payloads (Phase 7+)
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "ct200_generations"

    # Gemini LLM
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    llm_max_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
