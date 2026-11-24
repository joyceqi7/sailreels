"""Real HTTP/DB flows; only TikTok transport is simulated. No real credentials or payment calls."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import issue_session
from app.main import app
from app.models import AdReward, BeansOrder, Drama, Entitlement, Episode, Subscription, User, WebhookEvent
from app.routers.deps import get_tiktok
from app.services.webhooks import retry_event
from app.tiktok.client import TikTokClient
from tests.test_core_flows import envelope, sign

CREATE_URL = "https://open.tiktokapis.com/v2/minis/trade_order/create/"
PRICE_URL = "https://open.tiktokapis.com/v2/minis/utility/check_redeem_amounts/"
EVENT = "minis.trade_order.redeem.success"


def auth(user="u1"):
    return {"Authorization": f"Bearer {issue_session(user, get_settings())}"}


async def seed(sessions):
    async with sessions() as session:
        now = datetime.now(UTC)
        session.add_all([User(open_id=user, access_token=f"access-{user}", refresh_token="refresh",
                              access_expires_at=now + timedelta(days=1),
                              refresh_expires_at=now + timedelta(days=300)) for user in ("u1", "u2")])
        session.add(Drama(id=1, title="Demo", album_id="7667061213232384021", total_episodes=4,
                          free_episodes=1, unlock_price_beans=100, publish_status=1))
        await session.flush()
        session.add_all([Episode(drama_id=1, seq=i, vid=f"v{i}", episode_id=f"e{i}") for i in (1, 2, 3)])
        await session.commit()


@pytest.fixture
async def tiktok(client, respx_mock):
    t = TikTokClient(get_settings())
    respx_mock.post(PRICE_URL).respond(200, json={"data": {"valid": True}})
    app.dependency_overrides[get_tiktok] = lambda: t
    yield t
    await t.http.aclose()


async def deliver(client, content, *, event=EVENT, ct=1):
    body = envelope(event, content, ct)
    response = await client.post("/api/v1/webhooks/tiktok", content=body,
                                 headers={"TikTok-Signature": sign(body)})
    assert response.status_code == 200
    return response.json()


async def insert_order(sessions, *, order_id="b1", trade_id="T1", seq=2):
    async with sessions() as session:
        session.add(BeansOrder(order_id=order_id, trade_order_id=trade_id, open_id="u1", drama_id=1,
                               seq=seq, token_amount=100))
        await session.commit()


async def test_beans_order_webhook_poll_access_closed_loop(client, tiktok, sessionmaker, respx_mock):
    await seed(sessionmaker)
    route = respx_mock.post(CREATE_URL).respond(200, json={"data": {"trade_order_id": "T1"}})
    response = await client.post("/api/v1/orders/beans", json={"drama_id": 1, "seq": 2, "token_amount": 1},
                                 headers=auth())
    assert response.status_code == 200
    order_id = response.json()["order_id"]
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer access-u1"
    assert json.loads(request.content) == {
        "token_type": "BEANS", "token_amount": 100,
        "order_info": {"order_id": order_id, "product_name": "Demo EP2", "quantity": 1,
                       "quantity_unit": "episode"},
    }
    url = f"/api/v1/orders/beans/{order_id}"
    assert (await client.get(url, headers=auth())).json()["status"] == "created"
    assert (await client.get(url, headers=auth("u2"))).status_code == 404
    assert (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()["episode"] is None
    content = {"trade_order_id": "T1", "order_id": order_id, "is_sandbox": True}
    assert (await deliver(client, content))["duplicate"] is False
    assert (await deliver(client, content))["duplicate"] is True
    await deliver(client, content, ct=2)  # Different envelope, same order: still exactly one grant.
    assert (await client.get(url, headers=auth())).json()["status"] == "paid"
    access = (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()
    assert access["access"] == "unlocked" and access["episode"]["vid"] == "v2"
    listing = (await client.get("/api/v1/dramas/1/episodes", headers=auth())).json()
    assert listing["next_locked_seq"] == 3
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 1
        assert (await session.get(BeansOrder, order_id)).is_sandbox
    assert route.call_count == 1


@pytest.mark.parametrize("target,status", [
    ({"drama_id": 99, "seq": 2}, 400), ({"drama_id": 1, "seq": 1}, 400),
    ({"drama_id": 1, "seq": 4}, 400), ({"drama_id": 1, "seq": 5}, 400),
    ({"drama_id": 1, "seq": 0}, 422), ({"drama_id": 1, "seq": True}, 422),
    ({"drama_id": "1", "seq": 2}, 422),
])
async def test_invalid_targets_cannot_create_order_or_nonce(client, tiktok, sessionmaker, respx_mock, target, status):
    await seed(sessionmaker)
    route = respx_mock.post(CREATE_URL).respond(200, json={"data": {"trade_order_id": "T1"}})
    for path in ("orders/beans", "ads/rewarded/nonce"):
        assert (await client.post(f"/api/v1/{path}", json=target, headers=auth())).status_code == status
    assert not route.called
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(AdReward)) == 0
        assert await session.scalar(select(func.count()).select_from(BeansOrder)) == 0


async def test_offline_or_already_owned_target_is_not_sold_again(client, tiktok, sessionmaker):
    await seed(sessionmaker)
    async with sessionmaker() as session:
        (await session.get(Drama, 1)).publish_status = 2
        await session.commit()
    for path in ("orders/beans", "ads/rewarded/nonce"):
        assert (await client.post(f"/api/v1/{path}", json={"drama_id": 1, "seq": 2},
                                  headers=auth())).status_code == 400
    async with sessionmaker() as session:
        (await session.get(Drama, 1)).publish_status = 1
        session.add(Entitlement(open_id="u1", drama_id=1, seq=2, source="ad", ref_id="prior"))
        await session.commit()
    for path in ("orders/beans", "ads/rewarded/nonce"):
        assert (await client.post(f"/api/v1/{path}", json={"drama_id": 1, "seq": 2},
                                  headers=auth())).status_code == 409


async def test_platform_price_validation_prevents_invalid_order(client, tiktok, sessionmaker, respx_mock):
    await seed(sessionmaker)
    price = respx_mock.post(PRICE_URL).respond(200, json={"data": {"valid": False}})
    create = respx_mock.post(CREATE_URL).respond(200, json={"data": {"trade_order_id": "T1"}})
    response = await client.post("/api/v1/orders/beans", json={"drama_id": 1, "seq": 2}, headers=auth())
    assert response.status_code == 400 and response.json()["detail"] == "invalid_beans_price"
    assert json.loads(price.calls[0].request.content) == {"token_type": "BEANS", "token_amounts": [100]}
    assert not create.called
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(BeansOrder)) == 0


@pytest.mark.parametrize("failure,status", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)])
async def test_uncertain_order_creation_is_not_replayed(client, tiktok, sessionmaker, respx_mock, failure, status):
    await seed(sessionmaker)
    route = respx_mock.post(CREATE_URL).mock(side_effect=failure("private provider detail"))
    response = await client.post("/api/v1/orders/beans", json={"drama_id": 1, "seq": 2}, headers=auth())
    assert response.status_code == status and "private" not in response.text
    assert route.call_count == 1
    async with sessionmaker() as session:
        order = await session.scalar(select(BeansOrder))
        assert order is not None and order.trade_order_id is None
        order_id = order.order_id
        assert response.json()["order_id"] == order_id
    # If TikTok accepted the request, its later signed callback recovers the saved mapping.
    await deliver(client, {"trade_order_id": "T1", "order_id": order_id, "is_sandbox": True})
    assert (await client.get(f"/api/v1/orders/beans/{order_id}", headers=auth())).json()["status"] == "paid"


@pytest.mark.parametrize("body", [None, [], {}, {"data": {}}, {"data": {"trade_order_id": 123}},
                                      {"data": {"trade_order_id": ""}},
                                      {"error": {"code": "provider_failure", "message": "private-token"}}])
async def test_provider_order_errors_are_sanitized(client, tiktok, sessionmaker, respx_mock, body):
    await seed(sessionmaker)
    route = respx_mock.post(CREATE_URL).respond(200, json=body)
    response = await client.post("/api/v1/orders/beans", json={"drama_id": 1, "seq": 2}, headers=auth())
    assert response.status_code == 502 and "private-token" not in response.text
    assert route.call_count == 1


async def test_callback_before_create_response_preserves_paid_state(client, tiktok, sessionmaker, respx_mock):
    await seed(sessionmaker)

    async def early_callback(request):
        order_id = json.loads(request.content)["order_info"]["order_id"]
        await deliver(client, {"order_id": order_id, "trade_order_id": "T1", "is_sandbox": True})
        return httpx.Response(200, json={"data": {"trade_order_id": "T1"}})

    respx_mock.post(CREATE_URL).mock(side_effect=early_callback)
    order = (await client.post("/api/v1/orders/beans", json={"drama_id": 1, "seq": 2}, headers=auth())).json()
    assert (await client.get(f"/api/v1/orders/beans/{order['order_id']}", headers=auth())).json()["status"] == "paid"


@pytest.mark.parametrize("content", [
    {"trade_order_id": "WRONG", "order_id": "b1"},
    {"trade_order_id": "T1", "order_id": "wrong"},
    {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": "false"},
    {"order_id": "b1"},
])
async def test_mismatched_or_invalid_callback_cannot_grant(client, sessionmaker, content):
    await seed(sessionmaker)
    await insert_order(sessionmaker)
    await deliver(client, content)
    async with sessionmaker() as session:
        assert (await session.get(BeansOrder, "b1")).status == "created"
        row = await session.scalar(select(WebhookEvent))
        assert row.processed_at is None and row.error
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 0


async def test_refund_before_success_does_not_resurrect_order(client, sessionmaker):
    await seed(sessionmaker)
    await insert_order(sessionmaker)
    content = {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": True}
    await deliver(client, content, event="minis.trade_order.redeem.refund_success")
    await deliver(client, content, ct=2)
    assert (await client.get("/api/v1/orders/beans/b1", headers=auth())).json()["status"] == "refunded"
    assert (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()["access"] == "locked"


async def test_refund_after_payment_keeps_existing_entitlement_policy(client, sessionmaker):
    await seed(sessionmaker)
    await insert_order(sessionmaker)
    content = {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": False}
    await deliver(client, content)
    await deliver(client, content, event="minis.trade_order.redeem.refund_success", ct=2)
    assert (await client.get("/api/v1/orders/beans/b1", headers=auth())).json()["status"] == "refunded"
    assert (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()["access"] == "unlocked"


@pytest.mark.parametrize("production", [False, True])
async def test_sandbox_gate_also_hides_previous_grants_and_allows_real_unlock(client, sessionmaker,
                                                                           monkeypatch, production):
    await seed(sessionmaker)
    await insert_order(sessionmaker)
    await deliver(client, {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": True})
    if production:
        monkeypatch.setattr(get_settings(), "env", "prod")  # Even with ALLOW_SANDBOX_ENTITLEMENTS=true.
    else:
        monkeypatch.setattr(get_settings(), "allow_sandbox_entitlements", False)
    access_url = "/api/v1/dramas/1/episodes/2/access"
    assert (await client.get(access_url, headers=auth())).json()["access"] == "locked"
    listing = (await client.get("/api/v1/dramas/1/episodes", headers=auth())).json()
    assert listing["episodes"][1]["locked"] and listing["episodes"][1]["vid"] is None
    # A real purchase must replace the old test grant, not get lost on the unique constraint.
    await insert_order(sessionmaker, order_id="b2", trade_id="T2")
    await deliver(client, {"trade_order_id": "T2", "order_id": "b2", "is_sandbox": False}, ct=2)
    assert (await client.get(access_url, headers=auth())).json()["access"] == "unlocked"


async def test_blocked_sandbox_payment_is_paid_but_does_not_unlock(client, sessionmaker, monkeypatch):
    await seed(sessionmaker)
    await insert_order(sessionmaker)
    monkeypatch.setattr(get_settings(), "allow_sandbox_entitlements", False)
    await deliver(client, {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": True})
    assert (await client.get("/api/v1/orders/beans/b1", headers=auth())).json()["status"] == "paid"
    assert (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()["access"] == "locked"


async def test_nonce_is_bound_to_user_and_target_and_not_replayable(client, sessionmaker):
    await seed(sessionmaker)
    nonce = (await client.post("/api/v1/ads/rewarded/nonce", json={"drama_id": 1, "seq": 2},
                               headers=auth())).json()["nonce"]
    claim_url = "/api/v1/ads/rewarded/claim"
    assert (await client.post(claim_url, json={"nonce": nonce}, headers=auth("u2"))).status_code == 400
    assert (await client.post(claim_url, json={"nonce": nonce}, headers=auth())).status_code == 200
    assert (await client.post(claim_url, json={"nonce": nonce}, headers=auth())).status_code == 400
    assert (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()["access"] == "unlocked"
    assert (await client.get("/api/v1/dramas/1/episodes/3/access", headers=auth())).json()["access"] == "locked"


async def test_daily_limit_is_rechecked_when_claiming_old_nonce(client, sessionmaker, monkeypatch):
    from app.routers import monetization
    monkeypatch.setattr(monetization, "AD_DAILY_LIMIT", 1)
    await seed(sessionmaker)
    nonces = []
    for seq in (2, 3):
        nonces.append((await client.post("/api/v1/ads/rewarded/nonce", json={"drama_id": 1, "seq": seq},
                                         headers=auth())).json()["nonce"])
    url = "/api/v1/ads/rewarded/claim"
    assert (await client.post(url, json={"nonce": nonces[0]}, headers=auth())).status_code == 200
    assert (await client.post(url, json={"nonce": nonces[1]}, headers=auth())).status_code == 429
    async with sessionmaker() as session:
        assert (await session.get(AdReward, nonces[1])).status == "issued"
        assert await session.scalar(select(func.count()).select_from(Entitlement)) == 1


async def test_retry_clears_error_after_order_becomes_visible(client, sessionmaker):
    await seed(sessionmaker)
    await deliver(client, {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": True})
    await insert_order(sessionmaker)
    async with sessionmaker() as session:
        row = await session.scalar(select(WebhookEvent))
        assert await retry_event(session, row.id) == "processed"
        assert row.error is None and row.processed_at is not None


async def test_existing_sandbox_subscription_is_hidden_when_production_gate_turns_on(client, sessionmaker, monkeypatch):
    await seed(sessionmaker)
    async with sessionmaker() as session:
        session.add(Subscription(subscription_id="s1", open_id="u1", tier_id="sandbox", rights_valid=True,
                                  state="active", is_sandbox=True,
                                  benefit_end_time=datetime.now(UTC) + timedelta(days=1)))
        await session.commit()
    monkeypatch.setattr(get_settings(), "env", "prod")
    assert (await client.get("/api/v1/subscriptions/me", headers=auth())).json()["active"] is False
    assert (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()["access"] == "locked"
