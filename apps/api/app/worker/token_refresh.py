"""Token-only jobs: task messages/results never contain platform credentials."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.models import User
from app.services.auth import LoginRequired, ensure_fresh_token
from app.tiktok.client import TikTokAPIError, TikTokClient


class TokenRefreshTemporaryError(Exception):
    """Sanitized retry signal; never wrap a provider payload in the Celery result."""


def disabled_reason(settings: Settings) -> str | None:
    if not settings.token_refresh_enabled:
        return "paused"
    if not settings.tiktok_client_key.strip() or not settings.tiktok_client_secret.strip():
        return "credentials_missing"
    return None


async def due_user_ids(sessions: async_sessionmaker, settings: Settings) -> list[str]:
    if disabled_reason(settings):
        return []
    now = datetime.now(UTC)
    async with sessions() as session:
        # Project only IDs. Expired/rejected refresh credentials require login, not a periodic retry.
        rows = await session.scalars(select(User.open_id).where(
            User.access_expires_at <= now + timedelta(seconds=settings.token_refresh_window_seconds),
            User.refresh_expires_at > now,
        ).order_by(User.access_expires_at, User.open_id).limit(settings.token_refresh_batch_size))
        return list(rows)


async def refresh_one_user(open_id: str, sessions: async_sessionmaker,
                           tiktok: TikTokClient, settings: Settings) -> dict[str, str]:
    reason = disabled_reason(settings)
    if reason:
        return {"status": "skipped", "reason": reason}
    async with sessions() as session:
        user = await session.get(User, open_id)
        if user is None:
            return {"status": "skipped", "reason": "user_missing"}
        old_token = user.access_token
        try:
            token = await ensure_fresh_token(session, tiktok, user)
        except LoginRequired:
            # ensure_fresh_token has re-read this row under the PostgreSQL lock.
            # Persist the rejection so beat doesn't keep refreshing an invalid credential.
            user.refresh_expires_at = datetime.now(UTC)
            await session.commit()
            return {"status": "login_required"}
        except TikTokAPIError as error:
            await session.rollback()
            if error.code in {"invalid_client", "unauthorized_client"}:
                return {"status": "configuration_error"}
            if error.status == 429 or error.status >= 500:
                raise TokenRefreshTemporaryError("TikTok refresh temporarily unavailable") from None
            return {"status": "provider_error"}
        except httpx.HTTPError:
            await session.rollback()
            raise TokenRefreshTemporaryError("TikTok refresh network failure") from None
        return {"status": "refreshed" if token != old_token else "already_fresh"}
