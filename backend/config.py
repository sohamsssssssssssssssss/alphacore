"""Application configuration for the AlphaCore backend."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from environment variables and `.env`."""

    DATABASE_URL: str = Field(..., description="Async PostgreSQL connection URL.")
    NSE_FETCH_INTERVAL_SECONDS: int = Field(
        default=30,
        description="Polling interval for NSE market data fetches.",
    )
    ORDERBOOK_HISTORY_MINUTES: int = Field(
        default=60,
        description="In-memory order book history retention window in minutes.",
    )
    LOG_LEVEL: str = Field(default="INFO", description="Application log level.")
    CORS_ORIGINS: str = Field(
        default="http://localhost:5173",
        description="Comma-separated list of allowed CORS origins.",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
