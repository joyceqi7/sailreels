import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.security import issue_session, verify_tiktok_signature
from app.models import (
    AdReward,
    BeansOrder,
    Drama,
    Entitlement,
    Episode,
    Subscription,
    SubscriptionOrder,
    User,
)

SECRET = "test_secret"


def sign(body: bytes, t: int | None = None) -> str:
    t = t or int(time.time())
    s = hmac.new(SECRET.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},s={s}"


def envelope(event: str, content: dict, create_time: int = 1749646727) -> bytes:
    return json.dumps({"client_key": "test_key", "event": event, "create_time": create_time,
                       "user_openid": "", "content": json.dumps(content)}).encode()


async def seed(sm) -> None:
    async with sm() as s:
        now = datetime.now(UTC)
        s.add(User(open_id="u1", access_token="a", refresh_token="r",
                   access_expires_at=now + timedelta(days=1), refresh_expires_at=now + timedelta(days=300)))
        s.add(Drama(id=1, album_id="7667061213232384021", title="Demo", total_episodes=60, free_episodes=5,
                    unlock_price_beans=100, publish_status=1))
        s.add(Episode(drama_id=1, seq=6, episode_id="e6", vid="v6"))
        await s.commit()


def auth() -> dict:
    return {"Authorization": f"Bearer {issue_session('u1', get_settings())}"}


# ---------- signature ----------

def test_signature_ok_and_tampered():
    body = b'{"a":1}'
    header = sign(body)
    assert verify_tiktok_signature(body, header, SECRET, 300)
    assert not verify_tiktok_signature(b'{"a":2}', header, SECRET, 300)
    assert not verify_tiktok_signature(body, sign(body, int(time.time()) - 3600), SECRET, 300)
    assert not verify_tiktok_signature(body, "garbage", SECRET, 300)


async def test_webhook_rejects_bad_signature(client):
    r = await client.post("/api/v1/webhooks/tiktok", content=b"{}", headers={"TikTok-Signature": "t=1,s=x"})
    assert r.status_code == 401


# ---------- beans ----------

async def test_beans_webhook_grants_once(client, sessionmaker):
    await seed(sessionmaker)
    async with sessionmaker() as s:
        s.add(BeansOrder(order_id="b1", trade_order_id="T1", open_id="u1", drama_id=1, seq=6, token_amount=100))
        await s.commit()

    r = await client.get("/api/v1/dramas/1/episodes/6/access", headers=auth())
    assert r.json()["access"] == "locked" and r.json()["episode"] is None

    body = envelope("minis.trade_order.redeem.success", {"trade_order_id": "T1", "order_id": "b1"})
    for _ in range(2):  # redelivery must be a no-op
        r = await client.post("/api/v1/webhooks/tiktok", content=body, headers={"TikTok-Signature": sign(body)})
        assert r.status_code == 200

    async with sessionmaker() as s:
        assert (await s.get(BeansOrder, "b1")).status == "paid"
        from sqlalchemy import func, select
        assert await s.scalar(select(func.count()).select_from(Entitlement)) == 1

    r = await client.get("/api/v1/dramas/1/episodes/6/access", headers=auth())
    assert r.json()["access"] == "unlocked" and r.json()["episode"]["vid"] == "v6"


# ---------- subscription lifecycle ----------

async def post(client, event, content, ct):
    body = envelope(event, content, ct)
    r = await client.post("/api/v1/webhooks/tiktok", content=body, headers={"TikTok-Signature": sign(body)})
    assert r.status_code == 200


async def test_subscription_lifecycle(client, sessionmaker):
    await seed(sessionmaker)
    async with sessionmaker() as s:
        s.add(SubscriptionOrder(order_id="s1", trade_order_id="TS1", open_id="u1", tier_id="sandbox_499_1M"))
        await s.commit()
    end1 = int(time.time()) + 300
    await post(client, "minis.subscription.create",
               {"subscription_id": "SUB", "trade_order_id": "TS1", "order_id": "s1", "is_sandbox": True,
                "benefit_end_time": end1}, 1)
    me = (await client.get("/api/v1/subscriptions/me", headers=auth())).json()
    assert me["active"] and me["state"] == "active"
    assert (await client.get("/api/v1/dramas/1/episodes/6/access", headers=auth())).json()["access"] == "subscribed"

    # renew uses a new trade_order_id; must not be deduped against create
    await post(client, "minis.subscription.renew",
               {"subscription_id": "SUB", "trade_order_id": "TS2", "is_sandbox": True,
                "benefit_end_time": end1 + 300}, 2)
    # cancel keeps rights until end
    await post(client, "minis.subscription.cancel", {"subscription_id": "SUB", "trade_order_id": "TS3",
                                                     "is_sandbox": True}, 3)
    me = (await client.get("/api/v1/subscriptions/me", headers=auth())).json()
    assert me["active"] and me["state"] == "cancel"

    # onhold carries only subscription_id; rights unaffected
    await post(client, "minis.subscription.onhold", {"subscription_id": "SUB", "is_sandbox": True}, 4)
    assert (await client.get("/api/v1/subscriptions/me", headers=auth())).json()["state"] == "onhold"

    await post(client, "minis.subscription.expire", {"subscription_id": "SUB", "is_sandbox": True}, 5)
    me = (await client.get("/api/v1/subscriptions/me", headers=auth())).json()
    assert not me["active"] and me["state"] == "expired"
    assert (await client.get("/api/v1/dramas/1/episodes/6/access", headers=auth())).json()["access"] == "locked"


async def test_sandbox_blocked_in_prod(client, sessionmaker, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_sandbox_entitlements", False)
    await seed(sessionmaker)
    async with sessionmaker() as s:
        s.add(SubscriptionOrder(order_id="s1", trade_order_id="TS1", open_id="u1", tier_id="sandbox_499_1M"))
        await s.commit()
    await post(client, "minis.subscription.create",
               {"subscription_id": "SUB", "trade_order_id": "TS1", "order_id": "s1", "is_sandbox": True,
                "benefit_end_time": int(time.time()) + 300}, 1)
    async with sessionmaker() as s:
        assert (await s.get(Subscription, "SUB")).rights_valid is False


# ---------- rewarded ad ----------

async def test_ad_nonce_single_use(client, sessionmaker):
    await seed(sessionmaker)
    nonce = (await client.post("/api/v1/ads/rewarded/nonce", json={"drama_id": 1, "seq": 6},
                               headers=auth())).json()["nonce"]
    assert (await client.post("/api/v1/ads/rewarded/claim", json={"nonce": nonce}, headers=auth())).status_code == 200
    assert (await client.post("/api/v1/ads/rewarded/claim", json={"nonce": nonce}, headers=auth())).status_code == 400
    assert (await client.get("/api/v1/dramas/1/episodes/6/access", headers=auth())).json()["access"] == "unlocked"


async def test_ad_nonce_expires(client, sessionmaker):
    await seed(sessionmaker)
    async with sessionmaker() as s:
        s.add(AdReward(nonce="old", open_id="u1", drama_id=1, seq=6,
                       created_at=datetime.now(UTC) - timedelta(hours=1)))
        await s.commit()
    r = await client.post("/api/v1/ads/rewarded/claim", json={"nonce": "old"}, headers=auth())
    assert r.status_code == 400 and r.json()["detail"] == "nonce_expired"


async def test_requires_login(client):
    assert (await client.get("/api/v1/subscriptions/me")).status_code == 401
