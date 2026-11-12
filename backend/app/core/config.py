"""Application settings: the single source of configuration (12-factor, env vars prefixed QL_)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QL_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres@localhost:5433/queueless"
    redis_url: str = "redis://localhost:6379/0"

    # Secrets. The defaults are for local development only; override them in every deployment.
    jwt_secret: str = "dev-jwt-secret-change-me-0123456789"
    token_secret: str = "dev-token-secret-change-me-0123456789"
    jwt_ttl_minutes: int = 60

    # Public URL that QR codes point to (the React app).
    public_base_url: str = "http://localhost:5173"

    # ETA estimation (ADR-0007)
    eta_strategy: str = "ewma"  # "ewma" | "fixed"
    eta_alpha: float = 0.2
    eta_error_min_wait_sec: float = 5.0

    # Abuse controls (ADR-0004). 0 disables the join rate limit (used for single-IP load tests).
    join_rate_limit_per_min: int = 30
    counter_nonce_window_sec: int = 30

    # Background work and realtime (ADR-0005, ADR-0008)
    sweeper_interval_sec: float = 10.0
    ws_ping_interval_sec: float = 25.0
    enable_background_tasks: bool = True
    event_transport: str = "redis"  # "redis" | "memory" (single process, tests)

    db_pool_size: int = 20
    db_max_overflow: int = 30
    cors_origins: list[str] = ["http://localhost:5173"]
    static_dir: str | None = None  # built React app, served by the API in Docker


@lru_cache
def get_settings() -> Settings:
    return Settings()
