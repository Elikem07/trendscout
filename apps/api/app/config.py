"""Application configuration.

Single source of runtime config. Values load from environment variables
(and a local .env in development). Startup fails fast on missing required
values rather than failing later mid request.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql://trendscout:trendscout@localhost:5432/trendscout"
    redis_url: str = "redis://localhost:6379/0"
    api_cors_origins: str = "http://localhost:3000"

    # Clerk (see DEPENDENCIES.md item 9 and DEPLOY.md).
    # Issuer = the instance frontend API URL, e.g.
    # https://your-instance.clerk.accounts.dev
    clerk_issuer: str = ""
    clerk_webhook_secret: str = ""
    # Comma separated allowed azp values (our app origins). When set,
    # tokens minted for other origins are rejected.
    clerk_authorized_parties: str = ""

    # Etsy (DEPENDENCIES.md item 1)
    etsy_api_key: str = "unset"
    etsy_daily_quota: int = 10000
    quota_spend_ratio: float = 0.8  # never spend more than 80% of any quota

    # LLM (labeling, explanations)
    anthropic_api_key: str = "unset"

    @property
    def clerk_authorized_party_list(self) -> list[str]:
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]

    @property
    def clerk_jwks_url(self) -> str:
        return f"{self.clerk_issuer.rstrip('/')}/.well-known/jwks.json"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
