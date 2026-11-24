"""The approved W2 offers: 1/3/10 consecutive locked episodes, no discount."""
import json

import pytest
from sqlalchemy import select

from app.models import BeansOrder, Drama, Entitlement, Episode
from tests.test_monetization_integration import CREATE_URL, PRICE_URL, auth, deliver, seed, tiktok  # noqa: F401

pytestmark = pytest.mark.usefixtures("tiktok")


async def seed_season(sessions):
    await seed(sessions)
    async with sessions() as session:
        (await session.get(Drama, 1)).total_episodes = 12
        session.add_all([Episode(drama_id=1, seq=seq, episode_id=f"e{seq}", vid=f"v{seq}")
                         for seq in range(4, 13)])
        await session.commit()


async def test_offers_are_server_priced_metadata_without_playback_identity(client, sessionmaker):
    await seed_season(sessionmaker)
    result = await client.get("/api/v1/dramas/1/episodes/2/unlock-options", headers=auth())
    assert result.status_code == 200
    offers = result.json()["offers"]
    assert [(o["quantity"], o["token_amount"], o["available"]) for o in offers] == [
        (1, 100, True), (3, 300, True), (10, 1000, True)]
    assert offers[-1]["episode_seqs"] == list(range(2, 12))
    assert "episode_id" not in result.text and '"vid"' not in result.text
    assert (await client.get("/api/v1/dramas/1/episodes/2/unlock-options")).status_code == 401


@pytest.mark.parametrize("quantity", [1, 3, 10])
async def test_one_payment_fulfills_exact_bundle_once(client, sessionmaker, respx_mock, quantity):
    await seed_season(sessionmaker)
    price = respx_mock.post(PRICE_URL).respond(200, json={"data": {"valid": True}})
    create = respx_mock.post(CREATE_URL).respond(200, json={"data": {"trade_order_id": "T1"}})
    response = await client.post("/api/v1/orders/beans", headers=auth(), json={
        "drama_id": 1, "seq": 2, "quantity": quantity, "expected_token_amount": 100 * quantity})
    assert response.status_code == 200
    order_id = response.json()["order_id"]
    assert json.loads(price.calls[0].request.content)["token_amounts"] == [quantity * 100]
    payload = json.loads(create.calls[0].request.content)
    assert payload["order_info"]["quantity"] == quantity and payload["token_amount"] == quantity * 100
    # Price changes after purchase must not change how many episodes this order fulfills.
    async with sessionmaker() as session:
        order = await session.get(BeansOrder, order_id)
        assert order.episode_seqs == list(range(2, 2 + quantity))
        (await session.get(Drama, 1)).unlock_price_beans = 999
        await session.commit()
    content = {"order_id": order_id, "trade_order_id": "T1", "is_sandbox": True}
    await deliver(client, content)
    await deliver(client, content, ct=2)
    async with sessionmaker() as session:
        assert list(await session.scalars(select(Entitlement.seq).order_by(Entitlement.seq))) == list(
            range(2, 2 + quantity))
    assert (await client.get("/api/v1/dramas/1/episodes/12/access", headers=auth())).json()["access"] == "locked"


async def test_owned_or_missing_episode_disables_bundle_and_rejects_stale_offer(client,
                                                                             sessionmaker, respx_mock):
    await seed_season(sessionmaker)
    create = respx_mock.post(CREATE_URL).respond(200, json={"data": {"trade_order_id": "T1"}})
    async with sessionmaker() as session:
        session.add(Entitlement(open_id="u1", drama_id=1, seq=3, source="ad", ref_id="prior"))
        await session.commit()
    options = (await client.get("/api/v1/dramas/1/episodes/2/unlock-options", headers=auth())).json()
    assert [o["available"] for o in options["offers"]] == [True, False, False]
    response = await client.post("/api/v1/orders/beans", headers=auth(), json={"drama_id": 1, "seq": 2, "quantity": 3})
    assert response.status_code == 409 and not create.called


async def test_changed_price_is_rejected_before_tiktok_order(client, sessionmaker, respx_mock):
    await seed_season(sessionmaker)
    create = respx_mock.post(CREATE_URL).respond(200, json={"data": {"trade_order_id": "T1"}})
    response = await client.post("/api/v1/orders/beans", headers=auth(), json={
        "drama_id": 1, "seq": 2, "quantity": 3, "expected_token_amount": 100})
    assert response.status_code == 409 and response.json()["detail"] == "price_changed" and not create.called


@pytest.mark.parametrize("quantity", [0, 2, 11, True, "3"])
async def test_arbitrary_bundle_quantities_are_rejected(client, sessionmaker, quantity):
    await seed_season(sessionmaker)
    assert (await client.post("/api/v1/orders/beans", headers=auth(), json={
        "drama_id": 1, "seq": 2, "quantity": quantity})).status_code == 422


async def test_near_end_only_available_packages_can_be_bought(client, sessionmaker):
    await seed_season(sessionmaker)
    result = (await client.get("/api/v1/dramas/1/episodes/12/unlock-options", headers=auth())).json()
    assert [o["available"] for o in result["offers"]] == [True, False, False]
    assert (await client.post("/api/v1/orders/beans", headers=auth(), json={
        "drama_id": 1, "seq": 12, "quantity": 3})).status_code == 409
