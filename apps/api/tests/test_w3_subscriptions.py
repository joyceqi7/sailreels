"""HTTP/OpenAPI fixtures, signed eight-event lifecycle, and recovery boundaries (no platform claims)."""

import time
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import issue_session
from app.main import app
from app.models import SubscriptionOrder, SubscriptionPayment, WebhookEvent
from app.routers.deps import get_tiktok
from app.services.webhooks import retry_event
from app.tiktok.client import TikTokAPIError, TikTokClient
from tests.test_core_flows import auth, post, seed


@pytest.fixture
def tiktok(monkeypatch):
    monkeypatch.setattr(get_settings(), "subscription_sandbox_enabled", True)
    mock = AsyncMock(spec=TikTokClient)
    mock.get_active_subscriptions.return_value = []
    mock.create_subscription.return_value = "TS1"
    mock.reactivate_subscription.return_value = "TR1"
    app.dependency_overrides[get_tiktok] = lambda: mock
    return mock


async def create(client):
    return await client.post("/api/v1/subscriptions", json={"tier_id": "sandbox_499_1M"}, headers=auth())


async def created(client, sm, *, ct=10, sid="SUB", order="s1", trade="TS1", sandbox=True):
    async with sm() as s:
        s.add(SubscriptionOrder(order_id=order, trade_order_id=trade, open_id="u1", tier_id="sandbox_499_1M"))
        await s.commit()
    await post(
        client,
        "minis.subscription.create",
        {
            "order_id": order,
            "trade_order_id": trade,
            "subscription_id": sid,
            "is_sandbox": sandbox,
            "benefit_end_time": int(time.time()) + 3600,
            "original_price": "4.99",
            "actual_price": "3.99",
            "currency": "USD",
            "discounts": [{"party": "PLATFORM", "source": "QCPX", "discount_amount": "1.00"}],
        },
        ct,
    )


async def status(client):
    return (await client.get("/api/v1/subscriptions/me", headers=auth())).json()


async def test_order_survives_early_webhook_and_callback_is_not_authority(client, sessionmaker, tiktok):
    await seed(sessionmaker)

    async def upstream(*args, **kwargs):
        async with sessionmaker() as s:
            assert await s.get(SubscriptionOrder, kwargs["order_id"]) is not None
        await post(
            client,
            "minis.subscription.create",
            {
                "order_id": kwargs["order_id"],
                "trade_order_id": "TS1",
                "subscription_id": "SUB",
                "is_sandbox": True,
                "benefit_end_time": int(time.time()) + 3600,
            },
            10,
        )
        return "TS1"

    tiktok.create_subscription.side_effect = upstream
    response = await create(client)
    assert response.status_code == 200
    order_id = response.json()["order_id"]
    assert (await client.get(f"/api/v1/orders/subscriptions/{order_id}", headers=auth())).json()[
        "status"
    ] == "confirmed"
    assert (await status(client))["active"]


async def test_timeout_keeps_pending_order_and_blocks_duplicate_purchase(client, sessionmaker, tiktok):
    await seed(sessionmaker)
    tiktok.create_subscription.side_effect = httpx.ReadTimeout("private upstream info")
    response = await create(client)
    assert response.status_code == 504 and "private" not in response.text
    order_id = response.json()["order_id"]
    assert (await status(client))["pending_order"]["order_id"] == order_id
    assert (await create(client)).status_code == 409
    assert tiktok.create_subscription.await_count == 1
    await post(
        client,
        "minis.subscription.create",
        {
            "order_id": order_id,
            "trade_order_id": "TS1",
            "subscription_id": "SUB",
            "is_sandbox": True,
            "benefit_end_time": int(time.time()) + 3600,
        },
        10,
    )
    assert (await status(client))["active"]


@pytest.mark.parametrize("state", ["active", "cancel", "onhold"])
async def test_query_before_create_blocks_all_active_platform_states(client, sessionmaker, tiktok, state):
    await seed(sessionmaker)
    tiktok.get_active_subscriptions.return_value = [
        {
            "subscription_id": "S",
            "tier_id": "t",
            "is_subscription_rights_valid": state != "onhold",
            "is_renewal_normal": state == "active",
            "is_sandbox": True,
        }
    ]
    assert (await create(client)).status_code == 409
    tiktok.create_subscription.assert_not_awaited()


async def test_production_never_lists_or_accepts_debug_plans(client, sessionmaker, tiktok, monkeypatch):
    await seed(sessionmaker)
    monkeypatch.setattr(get_settings(), "env", "prod")
    monkeypatch.setattr(get_settings(), "subscription_tier_ids", ["sandbox_499_1M", "testdeveloper_x"])
    assert (await client.get("/api/v1/subscriptions/tiers", headers=auth())).json() == []
    assert (await create(client)).status_code == 400
    tiktok.create_subscription.assert_not_awaited()


async def test_eight_events_financial_ledger_and_rights(client, sessionmaker):
    await seed(sessionmaker)
    await created(client, sessionmaker)
    await post(client, "minis.subscription.cancel", {"subscription_id": "SUB", "trade_order_id": "TC"}, 20)
    assert (await status(client))["state"] == "cancel" and (await status(client))["active"]
    async with sessionmaker() as s:
        s.add(
            SubscriptionOrder(
                order_id="r1",
                trade_order_id="TR",
                open_id="u1",
                tier_id="sandbox_499_1M",
                subscription_id="SUB",
                kind="reactivate",
            )
        )
        await s.commit()
    await post(
        client,
        "minis.subscription.reactivate",
        {"order_id": "r1", "trade_order_id": "TR", "subscription_id": "SUB", "is_sandbox": True},
        30,
    )
    assert (await status(client))["renewal_normal"]
    await post(client, "minis.subscription.onhold", {"subscription_id": "SUB", "is_sandbox": True}, 40)
    assert (await status(client))["state"] == "onhold" and (await status(client))["active"]
    await post(
        client,
        "minis.subscription.renew",
        {
            "subscription_id": "SUB",
            "trade_order_id": "TN",
            "is_sandbox": True,
            "benefit_end_time": int(time.time()) + 7200,
            "actual_price": "4.99",
            "currency": "USD",
        },
        50,
    )
    assert (await status(client))["state"] == "active"
    await post(
        client,
        "minis.subscription.refund",
        {"subscription_id": "SUB", "trade_order_id": "TS1", "refund_price": "3.99", "refund_currency": "USD"},
        60,
    )
    assert (await status(client))["active"]
    await post(client, "minis.subscription.expire", {"subscription_id": "SUB"}, 70)
    assert not (await status(client))["active"]
    await post(client, "minis.subscription.revoke", {"subscription_id": "SUB", "trade_order_id": "TN"}, 80)
    assert (await status(client))["state"] == "revoked"
    async with sessionmaker() as s:
        assert (await s.get(SubscriptionPayment, "TS1")).status == "refunded"
        assert (await s.get(SubscriptionPayment, "TN")).status == "revoked"
        assert (await s.get(SubscriptionPayment, "TS1")).discounts[0]["source"] == "QCPX"
        assert all(e.processed_at for e in await s.scalars(select(WebhookEvent)))


async def test_late_success_and_same_second_renew_cannot_resurrect_revoke(client, sessionmaker):
    await seed(sessionmaker)
    await created(client, sessionmaker)
    await post(client, "minis.subscription.revoke", {"subscription_id": "SUB", "trade_order_id": "TS1"}, 30)
    for ct in (5, 30, 40):
        await post(
            client,
            "minis.subscription.renew",
            {
                "subscription_id": "SUB",
                "trade_order_id": "TS1",
                "is_sandbox": True,
                "benefit_end_time": int(time.time()) + 7200,
            },
            ct,
        )
    assert (await status(client))["state"] == "revoked" and not (await status(client))["active"]
    async with sessionmaker() as s:
        assert (await s.get(SubscriptionPayment, "TS1")).status == "revoked"


async def test_unknown_subscription_event_is_retryable_not_silently_processed(client, sessionmaker):
    await seed(sessionmaker)
    await post(client, "minis.subscription.onhold", {"subscription_id": "SUB", "is_sandbox": True}, 20)
    async with sessionmaker() as s:
        event = await s.scalar(select(WebhookEvent))
        event_id = event.id
        assert event.processed_at is None
    await created(client, sessionmaker)
    async with sessionmaker() as s:
        assert await retry_event(s, event_id) == "processed"
    assert (await status(client))["state"] == "onhold"


async def test_old_cancel_does_not_undo_newer_renew_and_duplicate_is_idempotent(client, sessionmaker):
    await seed(sessionmaker)
    await created(client, sessionmaker)
    for _ in range(2):
        await post(
            client,
            "minis.subscription.renew",
            {
                "subscription_id": "SUB",
                "trade_order_id": "TN",
                "is_sandbox": True,
                "benefit_end_time": int(time.time()) + 7200,
            },
            30,
        )
    await post(client, "minis.subscription.cancel", {"subscription_id": "SUB", "trade_order_id": "TC"}, 20)
    assert (await status(client))["state"] == "active"


async def test_query_success_without_webhook_never_grants_entitlement(client, sessionmaker, tiktok):
    await seed(sessionmaker)
    result = (await create(client)).json()
    tiktok.get_subscription_trade_order.return_value = {
        "trade_order_id": "TS1",
        "trade_order_status": "SUCCESS",
        "subscription_id": "SUB",
        "is_sandbox": True,
    }
    query = await client.post(f"/api/v1/orders/subscriptions/{result['order_id']}/query", headers=auth())
    assert query.json()["awaiting_webhook"] and query.json()["platform_status"] == "SUCCESS"
    assert not (await status(client))["active"]


async def test_other_account_cannot_query_or_reactivate_orders(client, sessionmaker, tiktok):
    await seed(sessionmaker)
    await created(client, sessionmaker)
    headers = {"Authorization": f"Bearer {issue_session('other', get_settings())}"}
    assert (await client.get("/api/v1/orders/subscriptions/s1", headers=headers)).status_code == 404
    assert (await client.post("/api/v1/orders/subscriptions/s1/query", headers=headers)).status_code == 404


async def test_reactivate_cancelled_uses_new_order_and_preserves_end(client, sessionmaker, tiktok):
    await seed(sessionmaker)
    await created(client, sessionmaker)
    await post(client, "minis.subscription.cancel", {"subscription_id": "SUB", "trade_order_id": "TC"}, 20)
    before = (await status(client))["benefit_end_time"]
    tiktok.get_active_subscriptions.return_value = [
        {
            "subscription_id": "SUB",
            "tier_id": "sandbox_499_1M",
            "is_subscription_rights_valid": True,
            "is_renewal_normal": False,
            "is_sandbox": True,
            "end_time": int(time.time()) + 3600,
        }
    ]
    response = await client.post("/api/v1/subscriptions/SUB/reactivate", headers=auth())
    assert response.status_code == 200
    await post(
        client, "minis.subscription.reactivate", {**response.json(), "subscription_id": "SUB", "is_sandbox": True}, 30
    )
    assert (await status(client))["state"] == "active" and (await status(client))["benefit_end_time"] == before


@pytest.mark.parametrize("end_seconds,next_deduct", [(60, None), (3600, 60)])
async def test_onhold_and_renewal_window_block_reactivation(client, sessionmaker, tiktok, end_seconds, next_deduct):
    await seed(sessionmaker)
    await created(client, sessionmaker)
    await post(client, "minis.subscription.cancel", {"subscription_id": "SUB", "trade_order_id": "TC"}, 20)
    tiktok.get_active_subscriptions.return_value = [
        {
            "subscription_id": "SUB",
            "tier_id": "sandbox_499_1M",
            "is_subscription_rights_valid": True,
            "is_renewal_normal": False,
            "is_sandbox": True,
            "end_time": int(time.time()) + end_seconds,
        }
    ]
    if next_deduct is not None:
        tiktok.get_active_subscriptions.return_value[0]["next_duduct_time"] = int(time.time()) + next_deduct
    assert (await client.post("/api/v1/subscriptions/SUB/reactivate", headers=auth())).json()[
        "detail"
    ] == "subscription_reactivation_blocked"
    await post(client, "minis.subscription.onhold", {"subscription_id": "SUB"}, 30)
    assert (await client.post("/api/v1/subscriptions/SUB/reactivate", headers=auth())).status_code == 409
    tiktok.reactivate_subscription.assert_not_awaited()


@pytest.mark.parametrize(
    "path, data",
    [
        ("get_active_list", {"subscriptions": "bad"}),
        ("create", {"trade_order_id": 123}),
        ("get_trade_order_info", {"trade_order_id": "TS1", "trade_order_status": "SUCCESS"}),
    ],
)
async def test_thin_client_rejects_malformed_success_responses(path, data):
    async def transport(request):
        return httpx.Response(200, json={"data": data, "error": {"code": "ok"}})

    async with httpx.AsyncClient(
        base_url="https://open.tiktokapis.com", transport=httpx.MockTransport(transport)
    ) as http:
        tt = TikTokClient(get_settings(), http)
        with pytest.raises(TikTokAPIError):
            if path == "get_active_list":
                await tt.get_active_subscriptions("a")
            elif path == "create":
                await tt.create_subscription("a", tier_id="t", order_id="o", product_name="VIP")
            else:
                await tt.get_subscription_trade_order("a", "TS1")


async def test_real_client_transport_create_reactivate_query_and_tier_contracts(client, sessionmaker, monkeypatch):
    """Only the provider HTTP transport is simulated; real routes, DB and signed webhooks run."""
    import json

    await seed(sessionmaker)
    monkeypatch.setattr(get_settings(), "subscription_sandbox_enabled", True)
    monkeypatch.setattr(get_settings(), "subscription_tier_ids", ["approved_monthly"])
    calls = []
    platform = []

    async def transport(request):
        data = json.loads(request.content)
        calls.append((request.url.path, data, request.headers["authorization"]))
        path = request.url.path
        if path.endswith("get_active_list/"):
            result = {"subscriptions": platform}
        elif path.endswith("get_trade_order_info/"):
            result = {"trade_order_id": data["trade_order_id"], "trade_order_status": "PENDING", "is_sandbox": True}
        elif path.endswith("get_subscription_info/"):
            result = {"subscription": {"subscription_id": "SUB"}}
        elif path.endswith("get_subscription_tier_info/"):
            result = {
                "subscription_tiers_info": {
                    "approved_monthly": {"price": "9.99", "currency": "USD", "deduct_cycle": "MONTHLY"}
                }
            }
        else:
            result = {"trade_order_id": "TR1" if path.endswith("reactivate/") else "TS1"}
        return httpx.Response(200, json={"data": result, "error": {"code": "ok"}})

    async with httpx.AsyncClient(
        base_url="https://open.tiktokapis.com", transport=httpx.MockTransport(transport)
    ) as http:
        tt = TikTokClient(get_settings(), http)
        app.dependency_overrides[get_tiktok] = lambda: tt
        response = await create(client)
        assert response.status_code == 200
        data = response.json()
        assert not (await status(client))["active"]
        query = await client.post(f"/api/v1/orders/subscriptions/{data['order_id']}/query", headers=auth())
        assert query.json()["platform_status"] == "PENDING"
        await post(
            client,
            "minis.subscription.create",
            {**data, "subscription_id": "SUB", "is_sandbox": True, "benefit_end_time": int(time.time()) + 3600},
            10,
        )
        await post(client, "minis.subscription.cancel", {"subscription_id": "SUB", "trade_order_id": "TC"}, 20)
        platform.append(
            {
                "subscription_id": "SUB",
                "tier_id": "sandbox_499_1M",
                "is_sandbox": True,
                "is_subscription_rights_valid": True,
                "is_renewal_normal": False,
                "end_time": int(time.time()) + 3600,
            }
        )
        assert (await client.get("/api/v1/subscriptions/platform", headers=auth())).json()[0]["state"] == "cancel"
        response = await client.post("/api/v1/subscriptions/SUB/reactivate", headers=auth())
        assert response.status_code == 200
        tiers = (await client.get("/api/v1/subscriptions/tiers?device_platform=android", headers=auth())).json()
        assert any(t["tier_id"] == "approved_monthly" and t["price"] == "9.99" for t in tiers)
        assert (await tt.get_subscription_info("a", "TS1"))["subscription_id"] == "SUB"
    create_call = next(c for c in calls if c[0].endswith("/create/"))
    assert create_call[1] == {
        "tier_id": "sandbox_499_1M",
        "order_info": {"order_id": data["order_id"], "product_name": "SailReels VIP"},
    }
    reactivate = next(c for c in calls if c[0].endswith("/reactivate/"))
    assert reactivate[1]["subscription_id"] == "SUB" and "tier_id" not in reactivate[1]
    assert all(c[2] == "Bearer a" for c in calls)
