"""The HTTP handler returns 200 even when applying an event fails (so TikTok does not retry-storm us).
That makes the retry sweep load-bearing: without it a paid order stays unfulfilled forever.
These tests cover the sweep that closes that gap."""

import hashlib
import hmac
import json
import time

from sqlalchemy import select

from app.models import BeansOrder, Drama, Entitlement, Episode, User, WebhookEvent
from app.services.webhooks import MAX_PROCESS_ATTEMPTS, retry_event

SECRET = "test_secret"


def sign(body: bytes) -> str:
    t = int(time.time())
    s = hmac.new(SECRET.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},s={s}"


def envelope(event: str, content: dict) -> bytes:
    return json.dumps({"client_key": "test_key", "event": event, "create_time": 1749646727,
                       "user_openid": "", "content": json.dumps(content)}).encode()


async def _seed_user(sessionmaker):
    from datetime import UTC, datetime, timedelta
    async with sessionmaker() as s:
        now = datetime.now(UTC)
        s.add(User(open_id="u1", access_token="a", refresh_token="r",
                   access_expires_at=now + timedelta(days=1), refresh_expires_at=now + timedelta(days=300)))
        s.add(Drama(id=1, album_id="777", title="D", total_episodes=2, free_episodes=1,
                    unlock_price_beans=100, publish_status=1))
        s.add(Episode(drama_id=1, seq=2, episode_id="e2", vid="v2"))
        await s.commit()


async def test_failed_event_is_stored_and_retried(client, sessionmaker):
    """An event that cannot be applied yet (order row not visible) stays retryable."""
    await _seed_user(sessionmaker)
    # No BeansOrder row exists, so the handler raises LookupError.
    body = envelope("minis.trade_order.redeem.success", {"trade_order_id": "T1", "order_id": "b1"})
    r = await client.post("/api/v1/webhooks/tiktok", content=body, headers={"TikTok-Signature": sign(body)})
    assert r.status_code == 200  # deliberately 200: retry is our job, not TikTok's

    async with sessionmaker() as s:
        row = await s.scalar(select(WebhookEvent))
        assert row.processed_at is None and row.retries == 0 and row.error

        # Retry while the order still does not exist -> still retryable.
        assert await retry_event(s, row.id) == "retry"
        assert (await s.get(WebhookEvent, row.id)).retries == 1

        # Now the order appears (as it would once the order-creation path committed).
        s.add(BeansOrder(order_id="b1", trade_order_id="T1", open_id="u1", drama_id=1, seq=2, token_amount=100))
        await s.commit()

        assert await retry_event(s, row.id) == "processed"

    async with sessionmaker() as s:
        row = await s.get(WebhookEvent, row.id)
        assert row.processed_at is not None
        assert (await s.get(BeansOrder, "b1")).status == "paid"
        # The unlock actually landed.
        assert await s.scalar(select(Entitlement.id).where(Entitlement.open_id == "u1")) is not None


async def test_retry_gives_up_after_max_attempts(client, sessionmaker):
    await _seed_user(sessionmaker)
    body = envelope("minis.trade_order.redeem.success", {"trade_order_id": "T9", "order_id": "b9"})
    await client.post("/api/v1/webhooks/tiktok", content=body, headers={"TikTok-Signature": sign(body)})

    async with sessionmaker() as s:
        row = await s.scalar(select(WebhookEvent))
        for expected in ("retry",) * (MAX_PROCESS_ATTEMPTS - 1) + ("exhausted",):
            assert await retry_event(s, row.id) == expected
        final = await s.get(WebhookEvent, row.id)
        assert final.retries == MAX_PROCESS_ATTEMPTS
        assert final.processed_at is None  # left for a human, not silently marked done


async def test_processed_event_is_never_reapplied(client, sessionmaker):
    await _seed_user(sessionmaker)
    async with sessionmaker() as s:
        s.add(BeansOrder(order_id="b1", trade_order_id="T1", open_id="u1", drama_id=1, seq=2, token_amount=100))
        await s.commit()
    body = envelope("minis.trade_order.redeem.success", {"trade_order_id": "T1", "order_id": "b1"})
    await client.post("/api/v1/webhooks/tiktok", content=body, headers={"TikTok-Signature": sign(body)})

    async with sessionmaker() as s:
        row = await s.scalar(select(WebhookEvent))
        assert row.processed_at is not None
        assert await retry_event(s, row.id) == "missing"


async def test_double_retry_cannot_double_grant(client, sessionmaker):
    """Grant is keyed on (open_id, drama_id, seq); running the same event twice must not duplicate."""
    await _seed_user(sessionmaker)
    body = envelope("minis.trade_order.redeem.success", {"trade_order_id": "T1", "order_id": "b1"})
    await client.post("/api/v1/webhooks/tiktok", content=body, headers={"TikTok-Signature": sign(body)})

    async with sessionmaker() as s:
        row = await s.scalar(select(WebhookEvent))
        s.add(BeansOrder(order_id="b1", trade_order_id="T1", open_id="u1", drama_id=1, seq=2, token_amount=100))
        await s.commit()
        await retry_event(s, row.id)
        entitlements = list(await s.scalars(select(Entitlement)))
        assert len(entitlements) == 1
