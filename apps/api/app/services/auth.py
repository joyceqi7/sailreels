from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User
from app.tiktok.client import TikTokAPIError, TikTokClient, TokenResult


class LoginRequired(Exception):
    """The stored refresh credential has expired or been rejected."""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _apply(user: User, t: TokenResult) -> None:
    now = datetime.now(UTC)
    user.access_token = t.access_token
    user.refresh_token = t.refresh_token
    user.access_expires_at = now + timedelta(seconds=t.expires_in)
    user.refresh_expires_at = now + timedelta(seconds=t.refresh_expires_in)
    user.scope = t.scope


async def login_with_code(session: AsyncSession, tiktok: TikTokClient, code: str) -> User:
    """code from TTMinis.login() is single-use and short-lived: exchange immediately, never retry it."""
    t = await tiktok.exchange_code(code)
    user = await session.get(User, t.open_id)
    if user is None:
        user = User(open_id=t.open_id)
        session.add(user)
    _apply(user, t)
    await session.commit()
    return user


async def ensure_fresh_token(session: AsyncSession, tiktok: TikTokClient, user: User, *, force: bool = False) -> str:
    """Refresh 30 min before expiry; serialize rotating credentials across PostgreSQL workers."""
    now = datetime.now(UTC)
    window = timedelta(seconds=get_settings().token_refresh_window_seconds)
    if not force and _aware(user.refresh_expires_at) > now and \
            _aware(user.access_expires_at) - now > window:
        return user.access_token
    previous_token = user.access_token
    # Re-read after taking the row lock: another API worker may already have refreshed it.
    locked = await session.scalar(select(User).where(User.open_id == user.open_id).with_for_update()
                                  .execution_options(populate_existing=True))
    if locked is None or _aware(locked.refresh_expires_at) <= datetime.now(UTC):
        raise LoginRequired()
    if (not force or locked.access_token != previous_token) and \
            _aware(locked.access_expires_at) - datetime.now(UTC) > window:
        return locked.access_token
    try:
        refreshed = await tiktok.refresh(locked.refresh_token)
    except TikTokAPIError as e:
        if e.code in {"invalid_grant", "invalid_token", "access_token_invalid"}:
            raise LoginRequired() from e
        raise
    if refreshed.open_id != locked.open_id:
        raise TikTokAPIError("/v2/oauth/token/", 502, None)
    _apply(locked, refreshed)
    await session.commit()
    return locked.access_token


async def fetch_profile(session: AsyncSession, tiktok: TikTokClient, user: User) -> dict:
    token = await ensure_fresh_token(session, tiktok, user)
    try:
        return await tiktok.user_info(token)
    except TikTokAPIError as e:
        if e.status != 401 and e.code not in {"access_token_invalid", "invalid_token"}:
            raise
    # Only a read-only profile request is retried. Never automatically replay a payment.
    token = await ensure_fresh_token(session, tiktok, user, force=True)
    try:
        return await tiktok.user_info(token)
    except TikTokAPIError as e:
        if e.status == 401 or e.code in {"access_token_invalid", "invalid_token"}:
            raise LoginRequired() from e
        raise
