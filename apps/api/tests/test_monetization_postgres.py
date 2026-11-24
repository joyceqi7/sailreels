"""Run against an isolated PostgreSQL schema, including real row locks and ON CONFLICT."""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import Base, get_session
from app.main import app
from app.models import AdReward, BeansOrder, Entitlement, Episode, Subscription, SubscriptionOrder, WebhookEvent
from app.services.entitlement import grant_episode
from app.services.webhooks import record_event, retry_event
from tests.test_core_flows import post
from tests.test_monetization_integration import auth, deliver, insert_order, seed


@pytest.fixture
async def postgres_sessions(client):
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL not set; CI provides a disposable PostgreSQL service")
    schema = f"zt_test_{uuid.uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "lock_timeout": "10000"}})
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def pg_session():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = pg_session
        await seed(sessions)
        yield sessions
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_same_nonce_concurrent_claim_is_consumed_once(client, postgres_sessions):
    nonce = (await client.post("/api/v1/ads/rewarded/nonce", json={"drama_id": 1, "seq": 2},
                               headers=auth())).json()["nonce"]
    results = await asyncio.gather(*[client.post("/api/v1/ads/rewarded/claim", json={"nonce": nonce},
                                                headers=auth()) for _ in range(2)])
    assert sorted(r.status_code for r in results) == [200, 400]
    async with postgres_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 1


async def test_subscription_renew_and_revoke_serialize_without_resurrection(client, postgres_sessions):
    import time

    from tests.test_w3_subscriptions import created
    await created(client, postgres_sessions)
    await asyncio.gather(
        post(client, "minis.subscription.renew", {"subscription_id": "SUB", "trade_order_id": "TN",
            "is_sandbox": True, "benefit_end_time": int(time.time()) + 7200}, 20),
        post(client, "minis.subscription.revoke", {"subscription_id": "SUB", "trade_order_id": "TS1"}, 30),
    )
    async with postgres_sessions() as session:
        sub = await session.get(Subscription, "SUB")
        assert sub.state == "revoked" and not sub.rights_valid
        assert all(e.processed_at is not None for e in await session.scalars(select(WebhookEvent)))


async def test_subscription_create_is_single_flight_per_user(client, postgres_sessions, monkeypatch):
    from unittest.mock import AsyncMock

    from app.core.config import get_settings
    from app.routers.deps import get_tiktok
    from app.tiktok.client import TikTokClient
    monkeypatch.setattr(get_settings(), "subscription_sandbox_enabled", True)
    tiktok = AsyncMock(spec=TikTokClient)
    tiktok.get_active_subscriptions.return_value = []
    tiktok.create_subscription.return_value = "TS1"
    app.dependency_overrides[get_tiktok] = lambda: tiktok
    responses = await asyncio.gather(*[client.post("/api/v1/subscriptions",
        json={"tier_id": "sandbox_499_1M"}, headers=auth()) for _ in range(2)])
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert tiktok.create_subscription.await_count == 1
    async with postgres_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SubscriptionOrder)) == 1


async def test_watch_progress_concurrent_upsert_keeps_one_row(client, postgres_sessions):
    from app.models import WatchProgress
    responses = await asyncio.gather(*[client.put("/api/v1/me/progress/1",
        json={"seq": 1, "position_seconds": pos}, headers=auth()) for pos in (12, 24)])
    assert all(r.status_code == 200 for r in responses)
    async with postgres_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WatchProgress)) == 1


async def test_different_nonces_cannot_race_past_daily_limit(client, postgres_sessions, monkeypatch):
    from app.routers import monetization
    monkeypatch.setattr(monetization, "AD_DAILY_LIMIT", 1)
    nonces = [(await client.post("/api/v1/ads/rewarded/nonce", json={"drama_id": 1, "seq": seq},
                                 headers=auth())).json()["nonce"] for seq in (2, 3)]
    results = await asyncio.gather(*[client.post("/api/v1/ads/rewarded/claim", json={"nonce": nonce},
                                                headers=auth()) for nonce in nonces])
    assert sorted(r.status_code for r in results) == [200, 429]
    async with postgres_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 1
        assert await session.scalar(select(func.count()).select_from(AdReward)
                                    .where(AdReward.status == "claimed")) == 1


async def test_distinct_webhook_deliveries_for_same_order_are_serialized(client, postgres_sessions):
    await insert_order(postgres_sessions)
    content = {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": True}
    await asyncio.gather(deliver(client, content, ct=1), deliver(client, content, ct=2))
    async with postgres_sessions() as session:
        assert (await session.get(BeansOrder, "b1")).status == "paid"
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 1
        rows = list(await session.scalars(select(WebhookEvent)))
        assert len(rows) == 2 and all(row.processed_at is not None and row.error is None for row in rows)


async def test_simultaneous_ad_and_payment_grants_share_one_entitlement(postgres_sessions):
    await insert_order(postgres_sessions)

    async def grant(source, ref):
        async with postgres_sessions() as session:
            inserted = await grant_episode(session, "u1", 1, 2, source, ref)
            await session.commit()
            return inserted

    results = await asyncio.gather(grant("ad", "n1"), grant("beans", "b1"))
    assert sorted(results) == [False, True]
    async with postgres_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 1


async def test_real_grant_replaces_old_sandbox_grant_on_postgres(client, postgres_sessions, monkeypatch):
    from app.core.config import get_settings
    await insert_order(postgres_sessions)
    await deliver(client, {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": True})
    monkeypatch.setattr(get_settings(), "allow_sandbox_entitlements", False)
    await insert_order(postgres_sessions, order_id="b2", trade_id="T2")
    await deliver(client, {"trade_order_id": "T2", "order_id": "b2", "is_sandbox": False}, ct=2)
    access = (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()
    assert access["access"] == "unlocked"


async def test_two_workers_cannot_apply_same_stored_event_twice(postgres_sessions):
    import json
    await insert_order(postgres_sessions)
    async with postgres_sessions() as session:
        row, _ = await record_event(session, {"event": "minis.trade_order.redeem.success", "create_time": 1,
            "content": json.dumps({"order_id": "b1", "trade_order_id": "T1", "is_sandbox": True})})
        event_id = row.id

    async def retry():
        async with postgres_sessions() as session:
            return await retry_event(session, event_id)

    assert sorted(await asyncio.gather(retry(), retry())) == ["missing", "processed"]
    async with postgres_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 1
        row = await session.get(WebhookEvent, event_id)
        assert row.error is None and row.processed_at is not None


async def test_bundle_fulfillment_rolls_back_every_episode_on_failure(client, postgres_sessions, monkeypatch):
    from app.services import webhooks
    await insert_order(postgres_sessions)
    async with postgres_sessions() as session:
        session.add(Episode(drama_id=1, seq=4, episode_id="e4", vid="v4"))
        (await session.get(BeansOrder, "b1")).episode_seqs = [2, 3, 4]
        await session.commit()
    original = webhooks.grant_episode

    async def fail_last(session, open_id, drama_id, seq, source, ref_id):
        if seq == 4:
            raise RuntimeError("simulated final-episode failure")
        return await original(session, open_id, drama_id, seq, source, ref_id)

    monkeypatch.setattr(webhooks, "grant_episode", fail_last)
    await deliver(client, {"order_id": "b1", "trade_order_id": "T1", "is_sandbox": True})
    async with postgres_sessions() as session:
        assert (await session.get(BeansOrder, "b1")).status == "created"
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 0
        row = await session.scalar(select(WebhookEvent))
        event_id = row.id
    monkeypatch.setattr(webhooks, "grant_episode", original)
    async with postgres_sessions() as session:
        assert await retry_event(session, event_id) == "processed"
        assert list(await session.scalars(select(Entitlement.seq).order_by(Entitlement.seq))) == [2, 3, 4]
