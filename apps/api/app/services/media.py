"""Media library pipeline: local metadata -> BytePlus upload -> album -> review -> live.

Docs: docs/official/12-media-library-api.md (API), 11-media-player-overview.md (flow).
Hard rules this file enforces:
- Only a vid returned by GET /video (upload_status == 2) is valid. A vid that only exists in the
  BytePlus console is NOT acceptable.
- Any single rejected episode blocks the entire album version from playing, so review is per-version.
- album/update always creates a new version and may renumber episode_id, so episode_id_map must be
  written back or the frontend will request a stale episode_id.
"""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Drama, Episode, MediaJob
from app.tiktok.client import TikTokClient

log = logging.getLogger(__name__)

# album/review/status codes (12-media-library-api.md)
REVIEW_NONE, REVIEWING, REVIEW_PASSED, REVIEW_REJECTED, REVIEW_WITHDRAWN = 0, 1, 2, 3, 4
# album publish_status
PUBLISH_NONE, PUBLISH_ONLINE, PUBLISH_OFFLINE = 0, 1, 2
# GET /video upload_status
UPLOAD_PROCESSING, UPLOAD_OK, UPLOAD_FAILED = 1, 2, 3
# album edit status (operation_type=2)
EDIT_UNPUBLISHED, EDIT_UPDATING, EDIT_DONE = 1, 2, 3

VALID_TAGS = set(range(1, 47)) - {32}  # doc's tag_list table has no 32
MAX_TAGS = 3
# album/review/appeal item types
APPEAL_ALBUM, APPEAL_EPISODE = 1, 2


class MediaPipelineError(Exception):
    pass


@dataclass
class VideoResult:
    status: int
    vid: str | None = None
    error: str | None = None


# ---------------------------------------------------------------- covers

async def upload_image(session: AsyncSession, tiktok: TikTokClient, image_url: str) -> str:
    """Public image URL -> open_pic_id, usable as album or episode cover."""
    job = MediaJob(kind="image", source_url=image_url, status="processing")
    session.add(job)
    await session.flush()
    try:
        job.result_id = await tiktok.media_upload_image(image_url)
        job.status = "done"
    except Exception as e:
        job.status, job.error = "failed", str(e)[:1000]
        await session.commit()
        raise
    await session.commit()
    return job.result_id


# ---------------------------------------------------------------- videos

async def upload_episode_video(session: AsyncSession, tiktok: TikTokClient, episode: Episode,
                               drama: Drama) -> str:
    """Accepts an async upload job. Returns the job_id to poll with poll_video()."""
    if not episode.source_url:
        raise MediaPipelineError(f"episode {drama.title} #{episode.seq} has no source_url")
    job = MediaJob(kind="video", episode_id=episode.id, source_url=episode.source_url, status="processing")
    session.add(job)
    await session.flush()
    try:
        data = await tiktok.media_upload_video(episode.source_url,
                                               episode.title or f"{drama.title} EP{episode.seq}")
    except Exception as e:
        job.status, job.error = "failed", str(e)[:1000]
        await session.commit()
        raise
    job.job_id = data.get("job_id")
    # Synchronous acceptance (result_type 1) can already carry the vid.
    if data.get("byteplus_vid"):
        _apply_vid(episode, job, data["byteplus_vid"])
    await session.commit()
    return job.job_id or ""


def _apply_vid(episode: Episode, job: MediaJob, vid: str) -> None:
    episode.vid = vid
    job.result_id = vid
    job.status = "done"


async def poll_video(session: AsyncSession, tiktok: TikTokClient, job: MediaJob) -> VideoResult:
    """One poll of an in-flight upload. Caller decides whether to keep polling."""
    if job.status == "done" and job.result_id:
        return VideoResult(UPLOAD_OK, job.result_id)
    if not job.job_id:
        return VideoResult(UPLOAD_FAILED, error="job has no job_id")
    data = await tiktok.media_query_video(job_id=job.job_id)
    status = data.get("upload_status")
    episode = await session.get(Episode, job.episode_id) if job.episode_id else None
    if status == UPLOAD_OK:
        vid = data.get("vid")
        if not vid:
            # Successful status without a vid means the asset is not usable for an episode.
            job.status, job.error = "failed", "upload succeeded but no vid returned"
            await session.commit()
            return VideoResult(UPLOAD_FAILED, error=job.error)
        if episode:
            _apply_vid(episode, job, vid)
        await session.commit()
        return VideoResult(UPLOAD_OK, vid)
    if status == UPLOAD_FAILED:
        job.status, job.error = "failed", (data.get("raw_video_info_json") or "")[:1000]
        await session.commit()
        return VideoResult(UPLOAD_FAILED, error=job.error)
    return VideoResult(UPLOAD_PROCESSING)


async def wait_for_videos(session: AsyncSession, tiktok: TikTokClient, drama: Drama,
                          *, timeout_seconds: int = 3600, interval: float = 10.0) -> dict[int, str]:
    """Poll every pending video job of this drama. Returns {seq: vid}."""
    seqs = {e.id: e.seq for e in await list_episodes(session, drama)}
    pending = (await session.scalars(
        select(MediaJob).where(MediaJob.kind == "video", MediaJob.status.in_(("pending", "processing")),
                               MediaJob.episode_id.in_(seqs))
    )).all()
    remaining = {j.id: j for j in pending}
    vids: dict[int, str] = {}
    elapsed = 0.0
    while remaining and elapsed < timeout_seconds:
        for job_id, job in list(remaining.items()):
            result = await poll_video(session, tiktok, job)
            if result.status == UPLOAD_OK:
                vids[seqs[job.episode_id]] = result.vid
                remaining.pop(job_id)
            elif result.status == UPLOAD_FAILED:
                remaining.pop(job_id)
        if remaining:
            await asyncio.sleep(interval)
            elapsed += interval
    return vids


async def list_episodes(session: AsyncSession, drama: Drama) -> list[Episode]:
    return list(await session.scalars(
        select(Episode).where(Episode.drama_id == drama.id).order_by(Episode.seq)
    ))


# ---------------------------------------------------------------- album

def build_album_info(drama: Drama) -> dict:
    if not drama.cover_pic_ids:
        raise MediaPipelineError(f"drama {drama.id} has no cover_pic_ids (upload a cover first)")
    if not drama.tags or len(drama.tags) > MAX_TAGS:
        raise MediaPipelineError(f"drama {drama.id} needs 1-{MAX_TAGS} tags")
    bad = [t for t in drama.tags if t not in VALID_TAGS]
    if bad:
        raise MediaPipelineError(f"invalid tag_list values {bad}; allowed 1-46 excluding 32")
    return {
        "language": drama.language,
        "title": drama.title,
        "seq_num": drama.total_episodes,
        "cover_list": list(drama.cover_pic_ids),
        "year": drama.year,
        "album_status": EDIT_DONE,
        "desp": drama.description,
        "drama_type": drama.drama_type,
        "tag_list": list(drama.tags),
    }


def build_episode_list(episodes: list[Episode]) -> list[dict]:
    """Omit episode_id only for brand-new episodes; otherwise the previous version's id is required.

    cover_list is required on EVERY episode, including ones carried over from the previous version.
    Verified against the live API on 2026-10-22: omitting it fails with
    `4001 episode cover_list is required`, even when episode_id is supplied.
    """
    out = []
    for ep in episodes:
        if not ep.vid:
            raise MediaPipelineError(f"episode #{ep.seq} has no vid; upload the video first")
        if not ep.cover_pic_id:
            raise MediaPipelineError(f"episode #{ep.seq} has no cover_pic_id; upload a cover first")
        item: dict = {
            "title": ep.title or f"EP{ep.seq}",
            "seq": ep.seq,
            "byteplus_vid": ep.vid,
            "cover_list": [ep.cover_pic_id],
        }
        if ep.episode_id:
            item["episode_id"] = ep.episode_id
        out.append(item)
    return out


async def create_album(session: AsyncSession, tiktok: TikTokClient, drama: Drama) -> str:
    album_id = await tiktok.album_create()
    drama.album_id = album_id
    await session.commit()
    return album_id


async def push_album(session: AsyncSession, tiktok: TikTokClient, drama: Drama) -> str:
    """Create a new album version from current DB state and write episode_id_map back. Returns the version."""
    if not drama.album_id:
        await create_album(session, tiktok, drama)
    episodes = await list_episodes(session, drama)
    data = await tiktok.album_update(
        drama.album_id, build_album_info(drama), build_episode_list(episodes),
        version=drama.current_version,
    )
    version = str(data["version"])
    id_map: dict = data.get("episode_id_map") or {}
    written = _write_back_episode_ids(episodes, id_map)
    missing = [ep.seq for ep in episodes if not ep.episode_id]
    # A carried-over episode keeps its id, so only rows that never had one can be missing. Losing an
    # id silently means the next version can't reference the episode and the frontend 404s.
    if missing:
        raise MediaPipelineError(
            f"version {version} returned no episode_id for seqs {missing} "
            f"(map keys: {sorted(id_map)}); refusing to save a version we can't address"
        )
    if written != len(episodes):
        log.warning("version %s: wrote back %s of %s episode ids", version, written, len(episodes))
    drama.current_version = version
    await session.commit()
    return version


def _write_back_episode_ids(episodes: list[Episode], id_map: dict) -> int:
    """Map the response's keys onto our rows. Returns how many were updated.

    Key shape verified against the live API on 2026-10-22 (the doc's example is wrong):
    a brand-new episode comes back keyed `seq:<n>` with a COLON, not the `seq_<n>` the doc shows.
    A carried-over episode is keyed by the episode_id we sent. Both are accepted here.
    """
    updated = 0
    for ep in episodes:
        candidates = [f"seq:{ep.seq}", f"seq_{ep.seq}"]
        if ep.episode_id:
            candidates.append(str(ep.episode_id))
        for key in candidates:
            if key in id_map:
                ep.episode_id = str(id_map[key])
                updated += 1
                break
    return updated


async def submit_review(session: AsyncSession, tiktok: TikTokClient, drama: Drama) -> str:
    if not drama.album_id or not drama.current_version:
        raise MediaPipelineError("push the album before submitting for review")
    data = await tiktok.album_review_submit(drama.album_id, drama.current_version)
    review_id = str(data.get("review_id", ""))
    if not review_id:
        # Without it album/review/appeal cannot be called, and an appeal only works on a rejected
        # item — there is no way to recover this later.
        raise MediaPipelineError(
            f"album/review/submit for version {drama.current_version} returned no review_id"
        )
    drama.review_id = review_id
    drama.review_status = REVIEWING
    await session.commit()
    return review_id


async def sync_status(session: AsyncSession, tiktok: TikTokClient, drama: Drama) -> dict:
    """Mirror album/query review + publish state onto the drama row."""
    if not drama.album_id:
        raise MediaPipelineError("drama has no album_id")
    data = await tiktok.album_query(drama.album_id)
    versions = data.get("album_version_list") or []
    target = next((v for v in versions if str(v.get("version")) == str(drama.current_version)), None)
    target = target or (versions[-1] if versions else None)
    if target is None:
        raise MediaPipelineError(f"album {drama.album_id} returned no versions")
    # `current_version` in the response is the album's current DRAFT version, which is not the same
    # as this version object's own `version`. The per-version field is authoritative for "which
    # version am I looking at", so only fall back to current_version when `version` is absent.
    drama.current_version = str(target.get("version") or target.get("current_version")
                                or drama.current_version)
    if target.get("online_version"):
        drama.online_version = str(target["online_version"])
    drama.review_status = int(target.get("review_status", drama.review_status))
    drama.publish_status = int(target.get("publish_status", drama.publish_status))
    await session.commit()
    # Episode-level rejections are what actually block a version, and they carry per-episode ids.
    # Returning only album-level reasons leaves no way to tell which episode to re-cut.
    episode_reviews = [
        {
            "episode_id": str(ep.get("episode_id", "")),
            "seq": ep.get("seq"),
            "title": ep.get("title"),
            "review_status": (ep.get("review_result") or {}).get("overall_review_status"),
            "fail_reasons": ep.get("review_fail_reasons") or [],
            "exception_reason": ep.get("exception_reason"),
        }
        for ep in (target.get("episode_info_list") or [])
        if ep.get("review_fail_reasons") or ep.get("exception_reason")
        or (ep.get("review_result") or {}).get("overall_review_status") in (3, 7)
    ]
    return {
        "version": drama.current_version,
        "review_status": drama.review_status,
        "publish_status": drama.publish_status,
        "online_version": drama.online_version,
        "review_fail_reasons": target.get("review_fail_reasons") or [],
        "album_review": (target.get("album_info") or {}).get("review_result"),
        "problem_episodes": episode_reviews,
    }


async def go_live(session: AsyncSession, tiktok: TikTokClient, drama: Drama) -> None:
    """Set the reviewed version live, then publish the album. Review status must be passed."""
    status = await sync_status(session, tiktok, drama)
    if status["review_status"] != REVIEW_PASSED:
        raise MediaPipelineError(
            f"version {status['version']} is not approved (review_status={status['review_status']})"
        )
    await tiktok.album_online_version(drama.album_id, drama.current_version)
    drama.online_version = drama.current_version
    await tiktok.album_set_status(drama.album_id, online=True)
    drama.publish_status = PUBLISH_ONLINE
    await session.commit()


# ---------------------------------------------------------------- cross-app reuse
#
# Two apps under one entity can share one reviewed album instead of uploading and reviewing the
# same episodes twice: app A uploads + submits, then album/authorize lends it to app B.
# Docs: 11-media-player-overview.md §1.2.3 "同主体小程序之间", 12-media-library-api.md 「剧集授权」.
# Preconditions the platform checks: identical content, ownership verified. Anything else —
# changed content, ownership that doesn't line up — still has to go through a normal new review.

async def authorize_to_apps(session: AsyncSession, tiktok: TikTokClient, drama: Drama,
                            target_client_keys: list[str], *, operate_type: int = 1) -> dict:
    """operate_type 1 grants, 2 revokes. Raises if any target failed; the batch is not atomic."""
    if not drama.album_id:
        raise MediaPipelineError(f"drama {drama.id} has no album_id; push it before authorising")
    data = await tiktok.album_authorize(drama.album_id, operate_type, target_client_keys)
    log.info("album %s authorise operate_type=%s targets=%s",
             drama.album_id, operate_type, target_client_keys)
    return data


async def appeal_rejection(session: AsyncSession, tiktok: TikTokClient, drama: Drama,
                           *, reason: str, seq: int | None = None,
                           attachment_urls: list[str] | None = None) -> None:
    """Appeal a rejected album (seq=None) or one rejected episode. Needs the stored review_id."""
    if not drama.album_id or not drama.review_id:
        raise MediaPipelineError(
            "appeal needs album_id and the review_id from album/review/submit; "
            "re-submit this version first if it was submitted before review_id was stored"
        )
    if drama.review_status not in (REVIEW_REJECTED,):
        raise MediaPipelineError(
            f"only a rejected album can be appealed (review_status={drama.review_status})"
        )
    if seq is None:
        item_id, item_type = drama.album_id, APPEAL_ALBUM
    else:
        ep = await session.scalar(
            select(Episode).where(Episode.drama_id == drama.id, Episode.seq == seq)
        )
        if ep is None or not ep.episode_id:
            raise MediaPipelineError(f"episode #{seq} has no episode_id; push the album first")
        item_id, item_type = ep.episode_id, APPEAL_EPISODE
    await tiktok.album_review_appeal(
        album_id=drama.album_id, review_id=drama.review_id, appeal_item_type=item_type,
        item_id=item_id, appeal_reason=reason, attachment_urls=attachment_urls,
    )
