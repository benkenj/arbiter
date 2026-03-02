import logging
import sys

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # === Database ===
    database_url: str = Field(
        ...,
        description="PostgreSQL async connection string: postgresql+asyncpg://user:pass@host/dbname",
    )
    db_timeout_seconds: float = Field(
        default=30.0,
        description="DB query timeout in seconds",
    )

    # === Notifications ===
    discord_webhook_url: str = Field(
        ...,
        description="Discord webhook URL: https://discord.com/api/webhooks/ID/TOKEN",
    )

    # === Logging ===
    log_level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR",
    )

    # === Market Discovery Filters ===
    market_binary_only: bool = Field(
        default=True,
        description="Only track binary (Yes/No) markets. Default: true.",
    )
    market_min_volume: float = Field(
        default=1000.0,
        description="Minimum trading volume in USDC to track a market. Default: 1000.",
    )
    market_min_liquidity: float = Field(
        default=1000.0,
        description="Minimum open-interest liquidity in USDC to track a market. Default: 1000.",
    )

    # === Discovery Loop ===
    discovery_interval_seconds: int = Field(
        default=300,
        description="Seconds between market discovery cycles. Default: 300 (5 minutes).",
    )

    @field_validator("database_url")
    @classmethod
    def validate_asyncpg_dialect(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "Must use asyncpg dialect: postgresql+asyncpg://user:pass@host/dbname"
            )
        return v


def load_settings() -> Settings:
    from pydantic import ValidationError

    try:
        return Settings()
    except ValidationError as exc:
        print("Configuration errors — fix all before starting:\n", file=sys.stderr)
        for err in exc.errors():
            field = str(err["loc"][0])
            env_var = field.upper()
            msg = err["msg"]
            field_info = Settings.model_fields.get(field)
            hint = field_info.description if field_info and field_info.description else ""
            print(f"  {env_var}: {msg}", file=sys.stderr)
            if hint:
                print(f"    Hint: {hint}", file=sys.stderr)
        sys.exit(1)


def print_config_summary(settings: Settings) -> None:
    masked_url = (
        settings.database_url[:30] + "..."
        if len(settings.database_url) > 30
        else settings.database_url
    )

    logger.info("=== Database ===")
    logger.info("  DATABASE_URL: %s", masked_url)
    logger.info("  DB_TIMEOUT_SECONDS: %s", settings.db_timeout_seconds)

    logger.info("=== Market Filters ===")
    logger.info("  MARKET_BINARY_ONLY: %s", settings.market_binary_only)
    logger.info("  MARKET_MIN_VOLUME: %s", settings.market_min_volume)
    logger.info("  MARKET_MIN_LIQUIDITY: %s", settings.market_min_liquidity)
    logger.info("  DISCOVERY_INTERVAL_SECONDS: %s", settings.discovery_interval_seconds)

    logger.info("=== Logging ===")
    logger.info("  LOG_LEVEL: %s", settings.log_level)
