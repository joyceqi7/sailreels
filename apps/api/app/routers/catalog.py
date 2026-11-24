from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import current_open_id
from app.models import Drama, Entitlement, Episode
from app.routers.auth_errors import AUTH_RESPONSES
from app.services.entitlement import episode_access, has_active_subscription, visible_entitlements

router = APIRouter(tags=["catalog"])


class EpisodeOut(BaseModel):
    seq: int
    title: str
    locked: bool = False
    # Playback identity is only returned when locked is false.
    album_id: str | None = None
    episode_id: str | None = None
    vid: str | None = None
    poster_url: str | None = None


class DramaOut(BaseModel):
    id: int
    title: str
    description: str
    cover_url: str
    total_episodes: int
    free_episodes: int
    unlock_price_beans: int


class AccessOut(BaseModel):
    access: Literal["free", "unlocked", "subscribed", "locked"]
    unlock_price_beans: int | None = None
    episode: EpisodeOut | None = None


class EpisodeListOut(BaseModel):
    """Everything the theater needs in one call: episode list + per-episode access + resume point."""

    drama_id: int
    free_episodes: int
    unlock_price_beans: int
    subscribed: bool
    # First locked episode — the point the theater should offer to unlock next.
    next_locked_seq: int | None = None
    episodes: list[EpisodeOut] = []


def _online(stmt):
    # Only approved + online albums are playable (player errors 9303-9310 otherwise).
    return stmt.where(Drama.publish_status == 1)


def _episode_out(ep: Episode, album_id: str | None, unlocked: bool) -> EpisodeOut:
    out = EpisodeOut(seq=ep.seq, title=ep.title, locked=not unlocked)
    if unlocked:
        out.album_id = album_id
        out.episode_id = ep.episode_id
        out.vid = ep.vid
        out.poster_url = ep.cover_url or None
    return out


@router.get("/dramas", response_model=list[DramaOut])
async def list_dramas(session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(_online(select(Drama)).order_by(Drama.id.desc()))).all()
    return [DramaOut.model_validate(d, from_attributes=True) for d in rows]


@router.get("/dramas/{drama_id}", response_model=DramaOut)
async def get_drama(drama_id: int, session: AsyncSession = Depends(get_session)):
    drama = await session.scalar(_online(select(Drama).where(Drama.id == drama_id)))
    if drama is None:
        raise HTTPException(404)
    return DramaOut.model_validate(drama, from_attributes=True)


@router.get("/dramas/{drama_id}/episodes", response_model=EpisodeListOut,
            responses={401: AUTH_RESPONSES[401]})
async def list_episodes(drama_id: int, open_id: str = Depends(current_open_id),
                        session: AsyncSession = Depends(get_session)):
    """Locked episodes come back without vid/episode_id, so an entitlement check can't be bypassed."""
    drama = await session.scalar(_online(select(Drama).where(Drama.id == drama_id)))
    if drama is None:
        raise HTTPException(404)
    episodes = list(await session.scalars(
        select(Episode).where(Episode.drama_id == drama_id).order_by(Episode.seq)))
    subscribed = await has_active_subscription(session, open_id)
    owned = set((await session.scalars(
        visible_entitlements().with_only_columns(Entitlement.seq).where(
            Entitlement.open_id == open_id, Entitlement.drama_id == drama_id)
    )).all()) if not subscribed else set()

    out: list[EpisodeOut] = []
    locked: list[int] = []
    for ep in episodes:
        unlocked = subscribed or ep.seq <= drama.free_episodes or ep.seq in owned
        if not unlocked:
            locked.append(ep.seq)
        out.append(_episode_out(ep, drama.album_id, unlocked))
    return EpisodeListOut(
        drama_id=drama.id, free_episodes=drama.free_episodes,
        unlock_price_beans=drama.unlock_price_beans, subscribed=subscribed,
        next_locked_seq=min(locked) if locked else None, episodes=out,
    )


@router.get("/dramas/{drama_id}/episodes/{seq}/access", response_model=AccessOut,
            responses={401: AUTH_RESPONSES[401]})
async def get_episode_access(drama_id: int, seq: int, open_id: str = Depends(current_open_id),
                             session: AsyncSession = Depends(get_session)):
    drama = await session.scalar(_online(select(Drama).where(Drama.id == drama_id)))
    ep = await session.scalar(select(Episode).where(Episode.drama_id == drama_id, Episode.seq == seq))
    if drama is None or ep is None:
        raise HTTPException(404)
    acc = await episode_access(session, open_id, drama, seq)
    out = AccessOut(access=acc.access, unlock_price_beans=acc.unlock_price_beans)
    if acc.access != "locked":
        out.episode = _episode_out(ep, drama.album_id, unlocked=True)
    return out
