"""
config.py — Application settings via pydantic-settings.

All environment variables are read here and nowhere else. Every other
module imports from this file rather than calling os.environ directly.

Set values in a .env file at the project root, or export them in your shell.
pydantic-settings will merge both sources, with env vars winning.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    # Full SQLAlchemy URL — override this in .env for production.
    # Default matches the docker-compose.yml credentials from Phase 1.
    database_url: str = (
        "postgresql+psycopg2://bball_user:bball_pass@localhost:5432/basketball_analytics"
    )

    # Connection pool tuning — sensible defaults for a dev/small-prod setup.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30

    # -------------------------------------------------------------------------
    # API
    # -------------------------------------------------------------------------
    api_title: str = "Basketball Analytics Engine"
    api_version: str = "0.2.0"
    debug: bool = False

    # -------------------------------------------------------------------------
    # pydantic-settings config
    # -------------------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",        # loads .env from the working directory
        env_file_encoding="utf-8",
        case_sensitive=False,   # DATABASE_URL and database_url both work
        extra="ignore",         # unknown env vars don't raise errors
    )


# Single shared instance — import this everywhere.
# Because it's module-level, Python only instantiates it once.
settings = Settings()
