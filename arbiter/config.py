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

    # === Detection Thresholds (Phase 3) ===
    longshot_price_min: float = Field(
        default=0.75,
        description="Minimum yes-price for longshot bias signal",
    )
    longshot_price_max: float = Field(
        default=0.95,
        description="Maximum yes-price for longshot bias signal",
    )
    longshot_liquidity_min: float = Field(
        default=1000.0,
        description="Minimum liquidity (USD) for longshot bias signal",
    )
    longshot_cooldown_hours: float = Field(
        default=24.0,
        description="Hours to wait before re-firing a longshot signal for the same market",
    )
    time_decay_price_min: float = Field(
        default=0.80,
        description="Minimum yes-price for time-decay signal",
    )
    time_decay_price_max: float = Field(
        default=0.97,
        description="Maximum yes-price for time-decay signal",
    )
    time_decay_liquidity_min: float = Field(
        default=500.0,
        description="Minimum liquidity (USD) for time-decay signal",
    )
    time_decay_hours_to_expiry_max: float = Field(
        default=72.0,
        description="Maximum hours to expiry for time-decay signal",
    )
    time_decay_cooldown_hours: float = Field(
        default=12.0,
        description="Hours to wait before re-firing a time-decay signal for the same market",
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

    logger.info("=== Detection Thresholds ===")
    logger.info("  LONGSHOT_PRICE_MIN: %s", settings.longshot_price_min)
    logger.info("  LONGSHOT_PRICE_MAX: %s", settings.longshot_price_max)
    logger.info("  LONGSHOT_LIQUIDITY_MIN: %s", settings.longshot_liquidity_min)
    logger.info("  LONGSHOT_COOLDOWN_HOURS: %s", settings.longshot_cooldown_hours)
    logger.info("  TIME_DECAY_PRICE_MIN: %s", settings.time_decay_price_min)
    logger.info("  TIME_DECAY_PRICE_MAX: %s", settings.time_decay_price_max)
    logger.info("  TIME_DECAY_LIQUIDITY_MIN: %s", settings.time_decay_liquidity_min)
    logger.info("  TIME_DECAY_HOURS_TO_EXPIRY_MAX: %s", settings.time_decay_hours_to_expiry_max)
    logger.info("  TIME_DECAY_COOLDOWN_HOURS: %s", settings.time_decay_cooldown_hours)

    logger.info("=== Logging ===")
    logger.info("  LOG_LEVEL: %s", settings.log_level)
