from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Origins allowed to call our API from a browser. The mini page is served by TikTok, so its origin
# is not ours and must be listed explicitly; docs/official/14-dev-debugging.md says the platform
# uses only these domains. Each is matched with any subdomain, since the page may sit on one.
DEFAULT_CORS_ORIGIN_REGEX = (
    r"https://([a-z0-9-]+\.)*(tiktok-minis\.(us|com|eu)|tiktokminis\.us)"
    r"|https://([a-z0-9-]+\.)*sailson\.com"
    r"|http://localhost(:\d+)?"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"  # local | staging | prod
    database_url: str = "postgresql+asyncpg://sailreels:sailreels@localhost:55440/sailreels"
    redis_url: str = "redis://localhost:56390/0"

    # Opt-in only: keep real token refresh paused until staging credentials are ready.
    token_refresh_enabled: bool = False
    token_refresh_interval_seconds: int = Field(default=300, ge=60)
    token_refresh_window_seconds: int = Field(default=1800, ge=60, le=3600)
    token_refresh_batch_size: int = Field(default=200, ge=1, le=2000)
    celery_broker_url: str = ""  # defaults to redis_url
    public_api_origin: str = ""  # public HTTPS origin for the platform handoff script

    # Webhook retry sweep. Always on: a failed payment event must be retried regardless of env.
    webhook_retry_interval_seconds: int = Field(default=60, ge=15)
    webhook_retry_batch_size: int = Field(default=100, ge=1, le=1000)

    # TikTok Minis app credentials. client_secret must never reach the frontend.
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_open_api: str = "https://open.tiktokapis.com"

    # Which app this deployment serves. One codebase, one deployment per app (each app has its own
    # credentials, users, reviewed media, ad units and tier IDs — see deploy/README.md).
    app_name: str = "SailReels"
    legal_entity: Literal["sailson_sg", "sailson_hk", "bang_us"] = "sailson_sg"  # keys of app.legal.ENTITIES
    legal_contact_email: str = "user1@example.com"  # public; users and privacy requests write here
    # "iaa": rewarded ads are the only way to unlock; Beans and subscription orders are refused (the web
    # build hides them via VITE_MONETIZATION). "hybrid": Beans + subscriptions + ads. Defaults to the
    # narrower mode so a deployment that forgets the variable cannot start taking payments.
    monetization_mode: Literal["iaa", "hybrid"] = "iaa"

    # BytePlus VOD (media library). AK/SK are bound in the TTOP console, not here.
    byteplus_account_id: str = ""
    byteplus_space_name: str = ""
    byteplus_region: str = "ap-southeast-1"

    # Webhook signature timestamp tolerance (TikTok does not document one).
    webhook_tolerance_seconds: int = 300
    # Sandbox orders/subscriptions grant entitlements only outside prod.
    allow_sandbox_entitlements: bool = True
    # Empty in production until Wayne supplies approved SKU IDs. Debug IDs are explicit and non-prod only.
    subscription_tier_ids: list[str] = []
    subscription_sandbox_enabled: bool = False

    # Session token signing for our own API (frontend <-> backend).
    session_secret: str = "change-me"
    session_ttl_seconds: int = 7 * 24 * 3600

    cors_origins: list[str] = ["http://localhost:5177"]
    # The mini page is served by TikTok, not by us, so calls to our API are cross-origin and the
    # page's own origin must be allowed. docs/official/14-dev-debugging.md: "the platform only uses
    # these 4 domains" — tiktok-minis.us/.com/.eu and tiktokminis.us — and the page may sit on a
    # subdomain, so match the domain and any subdomain. sailson.com covers staging and prod hosts.
    cors_origin_regex: str | None = None

    @property
    def sandbox_entitlements_allowed(self) -> bool:
        # A mistaken environment flag must never enable test fulfillment in production.
        return self.env != "prod" and self.allow_sandbox_entitlements

    @model_validator(mode="after")
    def validate_session_settings(self):
        if self.session_ttl_seconds <= 0:
            raise ValueError("SESSION_TTL_SECONDS must be positive")
        if self.env != "local" and (self.session_secret == "change-me" or len(self.session_secret) < 32):
            raise ValueError("Configure a random SESSION_SECRET of at least 32 characters outside local development")
        # An empty CORS_ORIGIN_REGEX in .env (the documented default) must mean "use the default",
        # not "allow nothing" — a silent empty allowlist would only surface on a real device.
        if not self.cors_origin_regex or not self.cors_origin_regex.strip():
            self.cors_origin_regex = DEFAULT_CORS_ORIGIN_REGEX
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
