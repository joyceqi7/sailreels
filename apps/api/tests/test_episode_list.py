"""Episode list is what the theater renders from. The critical property: a locked episode must not
hand out its vid/episode_id, or paying would become optional."""

from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.security import issue_session
from app.models import Drama, Entitlement, Episode, Subscription, User

AUTH = {"Authorization": f"Bearer {issue_session('u1', get_settings())}"}


async def seed(sessionmaker, *, free_episodes=2, total=4):
    async with sessionmaker() as s:
        now = datetime.now(UTC)
        s.add(User(open_id="u1", access_token="a", refresh_token="r",
                   access_expires_at=now + timedelta(days=1), refresh_expires_at=now + timedelta(days=300)))
        s.add(Drama(id=1, album_id="777", title="D", total_episodes=total, free_episodes=free_episodes,
                    unlock_price_beans=100, publish_status=1))
        for seq in range(1, total + 1):
            s.add(Episode(drama_id=1, seq=seq, title=f"EP{seq}", episode_id=f"e{seq}", vid=f"v{seq}"))
        await s.commit()


async def test_locked_episodes_hide_playback_identity(client, sessionmaker):
    await seed(sessionmaker)
    body = (await client.get("/api/v1/dramas/1/episodes", headers=AUTH)).json()
    assert body["free_episodes"] == 2 and body["next_locked_seq"] == 3
    by_seq = {e["seq"]: e for e in body["episodes"]}
    for seq in (1, 2):
        assert by_seq[seq]["locked"] is False
        assert by_seq[seq]["vid"] == f"v{seq}" and by_seq[seq]["episode_id"] == f"e{seq}"
    for seq in (3, 4):
        assert by_seq[seq]["locked"] is True
        # The whole point: no vid for episodes the user has not unlocked.
        assert by_seq[seq]["vid"] is None and by_seq[seq]["episode_id"] is None


async def test_unlocked_episode_is_exposed(client, sessionmaker):
    await seed(sessionmaker)
    async with sessionmaker() as s:
        s.add(Entitlement(open_id="u1", drama_id=1, seq=3, source="beans", ref_id="b1"))
        await s.commit()
    body = (await client.get("/api/v1/dramas/1/episodes", headers=AUTH)).json()
    by_seq = {e["seq"]: e for e in body["episodes"]}
    assert by_seq[3]["locked"] is False and by_seq[3]["vid"] == "v3"
    assert by_seq[4]["locked"] is True and by_seq[4]["vid"] is None
    assert body["next_locked_seq"] == 4


async def test_subscriber_sees_every_episode(client, sessionmaker):
    await seed(sessionmaker)
    async with sessionmaker() as s:
        s.add(Subscription(subscription_id="SUB", open_id="u1", tier_id="t", rights_valid=True,
                           renewal_normal=True, state="active",
                           benefit_end_time=datetime.now(UTC) + timedelta(days=3)))
        await s.commit()
    body = (await client.get("/api/v1/dramas/1/episodes", headers=AUTH)).json()
    assert body["subscribed"] is True and body["next_locked_seq"] is None
    assert all(e["locked"] is False and e["vid"] for e in body["episodes"])


async def test_offline_drama_is_not_playable(client, sessionmaker):
    await seed(sessionmaker)
    async with sessionmaker() as s:
        (await s.get(Drama, 1)).publish_status = 2
        await s.commit()
    assert (await client.get("/api/v1/dramas/1/episodes", headers=AUTH)).status_code == 404
    assert (await client.get("/api/v1/dramas", headers=AUTH)).json() == []


async def test_episodes_require_login(client, sessionmaker):
    await seed(sessionmaker)
    assert (await client.get("/api/v1/dramas/1/episodes")).status_code == 401
