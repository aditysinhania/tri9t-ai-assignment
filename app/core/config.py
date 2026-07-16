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

    # Prepared for Phase 7 (LLM storage). Not used in Phase 1.
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "ct200_generations"


@lru_cache
def get_settings() -> Settings:
    return Settings()
