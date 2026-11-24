from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.core.security import issue_session
from app.models import BeansOrder, Drama, User
from tests.test_core_flows import auth, seed
from tests.test_w3_subscriptions import created


async def test_progress_roundtrip_backward_seek_history_and_user_isolation(client, sessionmaker):
    await seed(sessionmaker)
    assert (await client.get("/api/v1/me/progress/1", headers=auth())).json() is None
    # Existing seed episode 6 is locked until an entitlement is provided.
    assert (
        await client.put("/api/v1/me/progress/1", json={"seq": 6, "position_seconds": 40}, headers=auth())
    ).status_code == 403
    await created(client, sessionmaker)
    for pos in (40, 12):
        response = await client.put("/api/v1/me/progress/1", json={"seq": 6, "position_seconds": pos}, headers=auth())
        assert response.status_code == 200 and response.json()["position_seconds"] == pos
    assert (await client.get("/api/v1/me/progress/1", headers=auth())).json()["position_seconds"] == 12
    history = (await client.get("/api/v1/me/history", headers=auth())).json()
    assert len(history["items"]) == 1 and history["items"][0]["last_seq"] == 6
    assert "vid" not in str(history) and "episode_id" not in str(history)
    other = {"Authorization": f"Bearer {issue_session('other', get_settings())}"}
    assert (await client.get("/api/v1/me/history", headers=other)).json()["items"] == []
    assert (await client.get("/api/v1/me/progress/1", headers=other)).json() is None
    async with sessionmaker() as session:
        drama = await session.get(Drama, 1)
        drama.publish_status = 2
        await session.commit()
    assert not (await client.get("/api/v1/me/history", headers=auth())).json()["items"][0]["available"]
    assert (
        await client.put("/api/v1/me/progress/1", json={"seq": 6, "position_seconds": 50}, headers=auth())
    ).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"seq": 6, "position_seconds": -1},
        {"seq": 6, "position_seconds": 86401},
        {"seq": True, "position_seconds": 1},
        {"seq": 6, "position_seconds": 1.2},
    ],
)
async def test_progress_rejects_invalid_input(client, sessionmaker, body):
    await seed(sessionmaker)
    assert (await client.put("/api/v1/me/progress/1", json=body, headers=auth())).status_code == 422


async def test_wallet_ledger_scope_test_labels_and_pagination(client, sessionmaker):
    await seed(sessionmaker)
    await created(client, sessionmaker)
    async with sessionmaker() as s:
        now = datetime.now(UTC)
        s.add(
            User(
                open_id="u2",
                access_token="a",
                refresh_token="r",
                access_expires_at=now + timedelta(days=1),
                refresh_expires_at=now + timedelta(days=2),
            )
        )
        await s.flush()
        s.add(BeansOrder(order_id="b1", open_id="u1", drama_id=1, seq=6, token_amount=100, is_sandbox=True))
        s.add(BeansOrder(order_id="private", open_id="u2", drama_id=1, seq=6, token_amount=900))
        await s.commit()
    wallet = (await client.get("/api/v1/me/wallet?limit=1", headers=auth())).json()
    assert wallet["beans_balance"] is None and wallet["has_more"] and len(wallet["items"]) == 1
    second = (await client.get("/api/v1/me/wallet?limit=1&offset=1", headers=auth())).json()
    assert not second["has_more"] and second["items"][0]["id"] != wallet["items"][0]["id"]
    combined = (await client.get("/api/v1/me/wallet", headers=auth())).json()
    assert "private" not in str(combined) and all(i["is_sandbox"] for i in combined["items"])
    assert any(i["actual_price"] == "3.99" for i in combined["items"])


@pytest.mark.parametrize("path", ["/me/wallet", "/me/history", "/me/progress/1"])
async def test_account_requires_session(client, path):
    assert (await client.get("/api/v1" + path)).status_code == 401
