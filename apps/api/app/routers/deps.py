from functools import lru_cache

from fastapi import HTTPException

from app.core.config import get_settings
from app.tiktok.client import TikTokClient


@lru_cache
def get_tiktok() -> TikTokClient:
    return TikTokClient(get_settings())


def iap_enabled() -> bool:
    return get_settings().monetization_mode == "hybrid"


def require_iap() -> None:
    """Guards order creation only. Status queries, webhooks and existing entitlements keep working, so an
    order placed before switching to IAA still settles and anything already granted stays watchable."""
    if not iap_enabled():
        raise HTTPException(403, "iap_disabled")
