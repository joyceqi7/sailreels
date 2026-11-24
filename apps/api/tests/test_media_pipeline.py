"""Media pipeline tests against a mocked TikTok OpenAPI (respx).

Covers the failure modes called out in docs/PLAN.md: a vid that never comes back from GET /video is
not usable, album/update renumbers episode_id, and go-live must refuse an unapproved version.
"""

import json

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Drama, Episode, MediaJob
from app.services import media
from app.tiktok.client import TikTokAPIError, TikTokClient

OPEN = "https://open.tiktokapis.com"
MEDIA = f"{OPEN}/v2/sg/shortdrama"


@pytest.fixture
def tiktok():
    s = get_settings()
    s.tiktok_client_key = "testkey"
    s.tiktok_client_secret = "test_secret"
    s.byteplus_account_id = "12345"
    s.byteplus_space_name = "sailreels-space"
    return TikTokClient(s)


@pytest.fixture
def api():
    with respx.mock(base_url=OPEN, assert_all_called=False) as mock:
        mock.post("/v2/oauth/token/").mock(
            return_value=httpx.Response(200, json={"access_token": "app_tok", "expires_in": 7200})
        )
        yield mock


async def _drama(session, **over):
    kw = {"title": "Test Drama", "description": "d", "total_episodes": 2, "free_episodes": 1,
          "tags": [13], "cover_pic_ids": ["pic1"], "language": "en", "drama_type": 4}
    kw.update(over)
    drama = Drama(**kw)
    session.add(drama)
    await session.flush()
    return drama


# ---------------------------------------------------------------- image

async def test_upload_image_records_job(api, tiktok, sessionmaker):
    api.post(f"{MEDIA}/image").mock(return_value=httpx.Response(200, json={"data": {"open_pic_id": "pic9"}}))
    async with sessionmaker() as s:
        pic = await media.upload_image(s, tiktok, "https://cdn.example.com/c.jpg")
        assert pic == "pic9"
        job = await s.scalar(select(MediaJob))
        assert job.kind == "image" and job.status == "done" and job.result_id == "pic9"


# ---------------------------------------------------------------- video upload

async def test_upload_video_polls_until_vid(api, tiktok, sessionmaker):
    api.post(f"{MEDIA}/video").mock(
        return_value=httpx.Response(200, json={"data": {"result_type": 2, "job_id": "vod:job:1"}})
    )
    # First poll still processing, second poll returns the vid.
    api.get(f"{MEDIA}/video").mock(side_effect=[
        httpx.Response(200, json={"data": {"upload_status": 1, "job_id": "vod:job:1"}}),
        httpx.Response(200, json={"data": {"upload_status": 2, "vid": "v-abc", "job_id": "vod:job:1"}}),
    ])
    async with sessionmaker() as s:
        drama = await _drama(s)
        ep = Episode(drama_id=drama.id, seq=1, title="EP1", source_url="https://cdn/1.mp4")
        s.add(ep)
        await s.commit()

        await media.upload_episode_video(s, tiktok, ep, drama)
        assert ep.vid is None  # async: not usable yet
        job = await s.scalar(select(MediaJob).where(MediaJob.kind == "video"))
        assert job.job_id == "vod:job:1"

        assert (await media.poll_video(s, tiktok, job)).status == media.UPLOAD_PROCESSING
        assert ep.vid is None  # still nothing to play

        result = await media.poll_video(s, tiktok, job)
        assert result.status == media.UPLOAD_OK and result.vid == "v-abc"
        assert ep.vid == "v-abc" and job.status == "done"


async def test_upload_success_without_vid_is_failed(api, tiktok, sessionmaker):
    """upload_status=2 with no vid must not be treated as usable."""
    api.post(f"{MEDIA}/video").mock(
        return_value=httpx.Response(200, json={"data": {"result_type": 2, "job_id": "vod:job:2"}})
    )
    api.get(f"{MEDIA}/video").mock(
        return_value=httpx.Response(200, json={"data": {"upload_status": 2, "raw_video_info_json": "{}"}})
    )
    async with sessionmaker() as s:
        drama = await _drama(s)
        ep = Episode(drama_id=drama.id, seq=1, source_url="https://cdn/1.mp4")
        s.add(ep)
        await s.commit()
        await media.upload_episode_video(s, tiktok, ep, drama)
        job = await s.scalar(select(MediaJob).where(MediaJob.kind == "video"))
        result = await media.poll_video(s, tiktok, job)
        assert result.status == media.UPLOAD_FAILED
        assert job.status == "failed" and ep.vid is None


# ---------------------------------------------------------------- album

def test_build_album_info_rejects_bad_tags(sessionmaker):
    import asyncio

    async def run():
        async with sessionmaker() as s:
            drama = await _drama(s, tags=[101])  # the value used in the doc's own (invalid) example
            with pytest.raises(media.MediaPipelineError, match="invalid tag_list"):
                media.build_album_info(drama)
            drama.tags = [1, 2, 3, 4]
            with pytest.raises(media.MediaPipelineError):
                media.build_album_info(drama)
            drama.tags = []
            with pytest.raises(media.MediaPipelineError, match="1-3 tags"):
                media.build_album_info(drama)
    asyncio.run(run())


def test_build_album_info_requires_cover(sessionmaker):
    import asyncio

    async def run():
        async with sessionmaker() as s:
            drama = await _drama(s, cover_pic_ids=[])
            with pytest.raises(media.MediaPipelineError, match="cover"):
                media.build_album_info(drama)
    asyncio.run(run())


async def test_push_album_writes_episode_id_map_back(api, tiktok, sessionmaker):
    """album/update renumbers episode_id; a stale id would make the frontend request a dead episode.

    The live API (verified 2026-10-22) keys a brand-new episode `seq:<n>` with a colon, while the
    doc's example shows `seq_<n>`. Both shapes must be accepted; a carried-over episode is keyed by
    the id we sent.
    """
    api.post(f"{MEDIA}/album/update/").mock(return_value=httpx.Response(200, json={"data": {
        "album_id": "777", "version": 2,
        "episode_id_map": {"seq:1": "e1-new", "e2-old": "e2-new"},
    }}))
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777")
        s.add_all([
            Episode(drama_id=drama.id, seq=1, title="EP1", vid="v1",
                    cover_pic_id="pic1", episode_id="e1-old"),
            Episode(drama_id=drama.id, seq=2, title="EP2", vid="v2",
                    cover_pic_id="pic2", episode_id="e2-old"),
        ])
        await s.commit()

        version = await media.push_album(s, tiktok, drama)
        assert version == "2" and drama.current_version == "2"
        eps = list(await s.scalars(select(Episode).order_by(Episode.seq)))
        assert [e.episode_id for e in eps] == ["e1-new", "e2-new"]


async def test_push_album_refuses_version_without_episode_ids(api, tiktok, sessionmaker):
    """A version whose episodes we can't address would 404 in the player; refuse to record it."""
    api.post(f"{MEDIA}/album/update/").mock(return_value=httpx.Response(200, json={"data": {
        "album_id": "777", "version": 2, "episode_id_map": {},
    }}))
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777")
        s.add(Episode(drama_id=drama.id, seq=1, title="EP1", vid="v1", cover_pic_id="pic1"))
        await s.commit()
        with pytest.raises(media.MediaPipelineError, match="no episode_id"):
            await media.push_album(s, tiktok, drama)


async def test_push_album_requires_vid(api, tiktok, sessionmaker):
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777")
        s.add(Episode(drama_id=drama.id, seq=1, title="EP1"))  # no vid
        await s.commit()
        with pytest.raises(media.MediaPipelineError, match="no vid"):
            await media.push_album(s, tiktok, drama)


async def test_push_album_requires_episode_cover(api, tiktok, sessionmaker):
    """cover_list is mandatory per episode, even for one carried over from the previous version."""
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777")
        s.add(Episode(drama_id=drama.id, seq=1, title="EP1", vid="v1"))  # no cover_pic_id
        await s.commit()
        with pytest.raises(media.MediaPipelineError, match="no cover_pic_id"):
            await media.push_album(s, tiktok, drama)


async def test_build_episode_list_sends_cover_list_and_previous_id():
    from app.models import Episode as EpisodeModel

    ep = EpisodeModel(drama_id=1, seq=3, title="EP3", vid="v3",
                      cover_pic_id="pic3", episode_id="old3")
    assert media.build_episode_list([ep]) == [{
        "title": "EP3", "seq": 3, "byteplus_vid": "v3",
        "cover_list": ["pic3"], "episode_id": "old3",
    }]


async def test_create_album_stores_id(api, tiktok, sessionmaker):
    api.post(f"{MEDIA}/album/create/").mock(
        return_value=httpx.Response(200, json={"data": {"album_id": 7637420375425239060}})
    )
    async with sessionmaker() as s:
        drama = await _drama(s)
        album_id = await media.create_album(s, tiktok, drama)
        # int64 kept as a string end to end.
        assert album_id == "7637420375425239060" and drama.album_id == album_id


# ---------------------------------------------------------------- review / go-live

async def test_sync_status_mirrors_review_and_publish(api, tiktok, sessionmaker):
    api.get(f"{MEDIA}/album/query/").mock(return_value=httpx.Response(200, json={"data": {
        "album_version_list": [{
            "album_id": "777", "version": 3, "review_status": 3, "publish_status": 0,
            "online_version": None, "review_fail_reasons": ["Episode (e2): Episode Video: Delete"],
        }],
    }}))
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="3")
        await s.commit()
        status = await media.sync_status(s, tiktok, drama)
        assert status["review_status"] == media.REVIEW_REJECTED
        assert status["review_fail_reasons"] == ["Episode (e2): Episode Video: Delete"]
        assert drama.review_status == 3


async def test_go_live_refuses_unapproved_version(api, tiktok, sessionmaker):
    api.get(f"{MEDIA}/album/query/").mock(return_value=httpx.Response(200, json={"data": {
        "album_version_list": [{"album_id": "777", "version": 1, "review_status": 1, "publish_status": 0}],
    }}))
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="1")
        await s.commit()
        with pytest.raises(media.MediaPipelineError, match="not approved"):
            await media.go_live(s, tiktok, drama)


async def test_go_live_sets_online_version_then_publishes(api, tiktok, sessionmaker):
    api.get(f"{MEDIA}/album/query/").mock(return_value=httpx.Response(200, json={"data": {
        "album_version_list": [{"album_id": "777", "version": 2, "review_status": 2, "publish_status": 0}],
    }}))
    online = api.post(f"{MEDIA}/album/online_version/").mock(
        return_value=httpx.Response(200, json={"data": {"album_id": "777", "online_version": 2}})
    )
    status = api.post(f"{MEDIA}/album/status/").mock(
        return_value=httpx.Response(200, json={"data": {"album_id": "777", "publish_status": 1}})
    )
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="2")
        await s.commit()
        await media.go_live(s, tiktok, drama)
        assert online.called and status.called
        assert drama.online_version == "2" and drama.publish_status == media.PUBLISH_ONLINE


async def test_submit_review_requires_pushed_album(tiktok, sessionmaker):
    async with sessionmaker() as s:
        drama = await _drama(s)
        with pytest.raises(media.MediaPipelineError, match="push the album"):
            await media.submit_review(s, tiktok, drama)


async def test_submit_review_stores_review_id(api, tiktok, sessionmaker):
    """The appeal endpoint needs review_id, and it can only be obtained at submit time."""
    api.post(f"{MEDIA}/album/review/submit/").mock(
        return_value=httpx.Response(200, json={"data": {"review_id": 7637437361307027000}})
    )
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="1")
        await s.commit()
        review_id = await media.submit_review(s, tiktok, drama)
        assert review_id == "7637437361307027000"
        assert drama.review_id == "7637437361307027000"
        assert drama.review_status == media.REVIEWING


async def test_submit_review_fails_when_no_review_id(api, tiktok, sessionmaker):
    """Without it an appeal is impossible later, so don't mark the album as submitted."""
    api.post(f"{MEDIA}/album/review/submit/").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="1")
        await s.commit()
        with pytest.raises(media.MediaPipelineError, match="no review_id"):
            await media.submit_review(s, tiktok, drama)


async def test_sync_status_surfaces_episode_rejections(api, tiktok, sessionmaker):
    """Episode-level reasons name the episode to re-cut; album-level ones don't."""
    api.get(f"{MEDIA}/album/query/").mock(return_value=httpx.Response(200, json={"data": {
        "album_version_list": [{
            "album_id": "777", "version": 2, "current_version": 2,
            "review_status": 3, "publish_status": 0,
            "review_fail_reasons": ["Album: Album Cover: Select a topic"],
            "episode_info_list": [
                {"episode_id": "e1", "seq": 1, "title": "EP1",
                 "review_result": {"overall_review_status": 2}},
                {"episode_id": "e2", "seq": 2, "title": "EP2",
                 "review_result": {"overall_review_status": 3},
                 "review_fail_reasons": ["Episode Video: Delete"]},
                {"episode_id": "e3", "seq": 3, "title": "EP3",
                 "exception_reason": "this video has already been removed"},
            ],
        }],
    }}))
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="2")
        await s.commit()
        out = await media.sync_status(s, tiktok, drama)
        assert drama.review_status == media.REVIEW_REJECTED
        assert out["review_fail_reasons"] == ["Album: Album Cover: Select a topic"]
        assert [e["seq"] for e in out["problem_episodes"]] == [2, 3]
        assert out["problem_episodes"][0]["fail_reasons"] == ["Episode Video: Delete"]
        assert out["problem_episodes"][1]["exception_reason"] == "this video has already been removed"


async def test_appeal_requires_stored_review_id(tiktok, sessionmaker):
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="1")
        drama.review_status = media.REVIEW_REJECTED
        await s.commit()
        with pytest.raises(media.MediaPipelineError, match="review_id"):
            await media.appeal_rejection(s, tiktok, drama, reason="n/a")


async def test_appeal_refuses_when_not_rejected(tiktok, sessionmaker):
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="1", review_status=media.REVIEWING)
        drama.review_id = "r1"
        await s.commit()
        with pytest.raises(media.MediaPipelineError, match="only a rejected album"):
            await media.appeal_rejection(s, tiktok, drama, reason="n/a")


async def test_appeal_sends_album_id_and_review_id(api, tiktok, sessionmaker):
    appeal = api.post(f"{MEDIA}/album/review/appeal/").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="1")
        drama.review_status = media.REVIEW_REJECTED
        drama.review_id = "7637437361307027000"
        await s.commit()
        await media.appeal_rejection(s, tiktok, drama, reason="cover art is compliant")
        body = json.loads(appeal.calls[0].request.content)
        assert body["album_id"] == "777"
        assert body["review_id"] == "7637437361307027000"
        assert body["appeal_item_type"] == media.APPEAL_ALBUM
        assert body["attachment_urls"] == []


async def test_appeal_episode_uses_episode_id(api, tiktok, sessionmaker):
    appeal = api.post(f"{MEDIA}/album/review/appeal/").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777", current_version="1")
        drama.review_status = media.REVIEW_REJECTED
        drama.review_id = "r1"
        s.add(Episode(drama_id=drama.id, seq=2, title="EP2", vid="v2",
                      cover_pic_id="p2", episode_id="e2"))
        await s.commit()
        await media.appeal_rejection(s, tiktok, drama, reason="recut", seq=2,
                                     attachment_urls=["https://cdn/x.jpg"])
        body = json.loads(appeal.calls[0].request.content)
        assert body["appeal_item_type"] == media.APPEAL_EPISODE
        assert body["item_id"] == "e2"
        assert body["attachment_urls"] == ["https://cdn/x.jpg"]


async def test_authorize_raises_when_a_target_fails(api, tiktok, sessionmaker):
    """A 200 here is not success per target; a silently failed grant means app B has no album."""
    api.post(f"{MEDIA}/album/authorize/").mock(return_value=httpx.Response(200, json={"data": {
        "client_key_result_list": [
            {"client_key": "mnok", "auth_status": 1},
            {"client_key": "mnbad", "auth_status": 0, "error_code": 22010,
             "error_message": "authorization already exists"},
        ],
    }}))
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777")
        await s.commit()
        with pytest.raises(TikTokAPIError, match="TikTok request failed"):
            await media.authorize_to_apps(s, tiktok, drama, ["mnok", "mnbad"])


async def test_authorize_sends_album_id(api, tiktok, sessionmaker):
    call = api.post(f"{MEDIA}/album/authorize/").mock(return_value=httpx.Response(200, json={"data": {
        "client_key_result_list": [{"client_key": "mnb", "auth_status": 1}],
    }}))
    async with sessionmaker() as s:
        drama = await _drama(s, album_id="777")
        await s.commit()
        await media.authorize_to_apps(s, tiktok, drama, ["mnb"])
        body = json.loads(call.calls[0].request.content)
        assert body["album_id"] == "777"
        assert body["operate_type"] == 1
        assert body["target_client_key_list"] == ["mnb"]
