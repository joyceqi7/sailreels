"""MONETIZATION_MODE=iaa: rewarded ads are the only unlock. Orders are refused before reaching TikTok,
while settlement of earlier orders and existing entitlements keep working."""
import pytest
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.models import BeansOrder, Entitlement, SubscriptionOrder
from tests.test_monetization_integration import CREATE_URL, auth, deliver, insert_order, seed, tiktok  # noqa: F401

pytestmark = pytest.mark.usefixtures("tiktok")


@pytest.fixture(autouse=True)
def iaa(monkeypatch):
    monkeypatch.setattr(get_settings(), "monetization_mode", "iaa")


def test_unset_variable_means_iaa(monkeypatch):
    monkeypatch.delenv("MONETIZATION_MODE", raising=False)
    assert Settings(_env_file=None).monetization_mode == "iaa"


async def test_unlock_options_offer_only_the_ad(client, sessionmaker):
    await seed(sessionmaker)
    options = (await client.get("/api/v1/dramas/1/episodes/2/unlock-options", headers=auth())).json()
    assert options["offers"] == [] and options["rewarded_ad"] is True


async def test_beans_and_subscription_orders_are_refused_without_calling_tiktok(client, sessionmaker, respx_mock):
    await seed(sessionmaker)
    create = respx_mock.post(CREATE_URL).respond(200, json={"data": {"trade_order_id": "T1"}})
    beans = await client.post("/api/v1/orders/beans", headers=auth(), json={"drama_id": 1, "seq": 2, "quantity": 1})
    subscribe = await client.post("/api/v1/subscriptions", headers=auth(), json={"tier_id": "tier"})
    reactivate = await client.post("/api/v1/subscriptions/S1/reactivate", headers=auth())
    for response in (beans, subscribe, reactivate):
        assert response.status_code == 403 and response.json()["detail"] == "iap_disabled"
    assert not create.called
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(BeansOrder)) == 0
        assert await session.scalar(select(func.count()).select_from(SubscriptionOrder)) == 0


async def test_ad_unlock_still_works(client, sessionmaker):
    await seed(sessionmaker)
    nonce = (await client.post("/api/v1/ads/rewarded/nonce", json={"drama_id": 1, "seq": 2},
                               headers=auth())).json()["nonce"]
    assert (await client.post("/api/v1/ads/rewarded/claim", json={"nonce": nonce}, headers=auth())).status_code == 200
    assert (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()["access"] == "unlocked"


async def test_order_placed_before_the_switch_still_settles(client, sessionmaker):
    await seed(sessionmaker)
    await insert_order(sessionmaker)
    await deliver(client, {"trade_order_id": "T1", "order_id": "b1", "is_sandbox": True})
    assert (await client.get("/api/v1/orders/beans/b1", headers=auth())).json()["status"] == "paid"
    async with sessionmaker() as session:
        assert list(await session.scalars(select(Entitlement.seq))) == [2]
    assert (await client.get("/api/v1/dramas/1/episodes/2/access", headers=auth())).json()["access"] == "unlocked"
