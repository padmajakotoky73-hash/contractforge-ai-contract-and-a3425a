from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str = Field("postgresql+asyncpg://app:app@localhost:5432/app")
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    app_secret: str = "change-me"
    log_level: str = "INFO"
    cors_origins: list[str] = ["*"]

    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    # Accept both Doppler names (LEMON_SQUEEZY_* / LS_*) and legacy names
    lemonsqueezy_api_key: str = Field(
        "",
        validation_alias=AliasChoices("LEMON_SQUEEZY_API_KEY", "LEMONSQUEEZY_API_KEY"),
    )
    lemonsqueezy_webhook_secret: str = Field(
        "",
        validation_alias=AliasChoices(
            "LEMON_SQUEEZY_WEBHOOK_SECRET",
            "LEMONSQUEEZY_WEBHOOK_SECRET",
            "LEMONSQUEEZY_SIGNING_SECRET",
        ),
    )
    lemonsqueezy_store_id: str = ""
    lemonsqueezy_checkout_per_contract: str = Field(
        "",
        validation_alias=AliasChoices(
            "LS_CHECKOUT_PER_CONTRACT",
            "LEMONSQUEEZY_CHECKOUT_PER_CONTRACT",
            "LS_SINGLE_URL",
        ),
    )
    lemonsqueezy_checkout_monthly: str = Field(
        "",
        validation_alias=AliasChoices(
            "LS_CHECKOUT_MONTHLY",
            "LEMONSQUEEZY_CHECKOUT_MONTHLY",
            "LS_MONTHLY_URL",
        ),
    )
    lemonsqueezy_test_mode: str = "true"

    anthropic_api_key: str = ""
    glm_api_key: str = ""
    sentry_dsn_backend: str = ""
    agent_trigger_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
