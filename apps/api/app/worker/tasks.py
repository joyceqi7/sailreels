"""Sync Celery entry points with fresh async resources per task invocation."""

import asyncio
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.webhooks import MAX_PROCESS_ATTEMPTS, retry_event
from app.tiktok.client import TikTokClient
from app.worker.celery_app import celery_app
from app.worker.token_refresh import (
    TokenRefreshTemporaryError,
    disabled_reason,
    due_user_ids,
    refresh_one_user,
)


async def _with_resources[T](operation: Callable[[async_sessionmaker, TikTokClient], Awaitable[T]]) -> T:
    settings = get_settings()
    options = {}
    if settings.database_url.startswith("postgresql"):
        options["connect_args"] = {"server_settings": {"lock_timeout": "15000", "statement_timeout": "30000"}}
    # Never reuse the API engine or HTTP client across asyncio.run loops / prefork workers.
    engine = create_async_engine(settings.database_url, poolclass=NullPool, **options)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with httpx.AsyncClient(base_url=settings.tiktok_open_api, timeout=15) as http:
            return await operation(sessions, TikTokClient(settings, http))
    finally:
        await engine.dispose()


@celery_app.task(name="sailreels.auth.scan_due_tokens")
def scan_due_tokens() -> dict[str, str | int]:
    settings = get_settings()
    reason = disabled_reason(settings)
    if reason:
        return {"status": "skipped", "reason": reason, "queued": 0}

    async def scan(sessions, _tiktok):
        return await due_user_ids(sessions, settings)

    users = asyncio.run(_with_resources(scan))
    for open_id in users:
        refresh_user_token.apply_async(args=(open_id,), argsrepr="(<user>,)", queue="auth")
    return {"status": "queued", "queued": len(users)}


@celery_app.task(name="sailreels.auth.refresh_user", autoretry_for=(TokenRefreshTemporaryError,),
                 retry_backoff=30, retry_backoff_max=300, retry_jitter=True,
                 retry_kwargs={"max_retries": 3})
def refresh_user_token(open_id: str) -> dict[str, str]:
    settings = get_settings()
    reason = disabled_reason(settings)
    if reason:
        return {"status": "skipped", "reason": reason}

    async def refresh(sessions, tiktok):
        return await refresh_one_user(open_id, sessions, tiktok, settings)

    return asyncio.run(_with_resources(refresh))


@celery_app.task(name="sailreels.webhooks.retry_unprocessed")
def retry_unprocessed_webhooks() -> dict[str, int]:
    """Retry payment/subscription events that were stored but failed to apply.

    The HTTP handler intentionally returns 200 after a business failure so TikTok does not hammer us;
    this task is what actually finishes the job. Without it a paid order could stay unfulfilled.
    """
    settings = get_settings()

    async def retry_all(sessions, _tiktok):
        from sqlalchemy import select as _select

        from app.models import WebhookEvent

        counts = {"processed": 0, "retry": 0, "exhausted": 0, "missing": 0}
        async with sessions() as session:
            ids = list(await session.scalars(
                _select(WebhookEvent.id)
                .where(WebhookEvent.processed_at.is_(None),
                       WebhookEvent.retries < MAX_PROCESS_ATTEMPTS)
                .order_by(WebhookEvent.created_at, WebhookEvent.id)
                .limit(settings.webhook_retry_batch_size)
            ))
        # One session per event: a failure in one must not roll back another's progress.
        for event_id in ids:
            async with sessions() as session:
                counts[await retry_event(session, event_id)] += 1
        return counts

    return asyncio.run(_with_resources(retry_all))
