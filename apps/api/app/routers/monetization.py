"""Beans unlock + rewarded-ad unlock + subscription order creation."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import current_open_id
from app.models import AdReward, BeansOrder, Drama, Entitlement, Episode, User
from app.routers.auth_errors import AUTH_RESPONSES, auth_failure
from app.routers.deps import get_tiktok, iap_enabled, require_iap
from app.services.auth import LoginRequired, ensure_fresh_token
from app.services.entitlement import episode_access, grant_episode, visible_entitlements
from app.tiktok.client import TikTokAPIError, TikTokClient

router = APIRouter(tags=["monetization"], responses={c: AUTH_RESPONSES[c] for c in (401, 502, 503, 504)})

AD_NONCE_TTL = timedelta(minutes=10)
AD_DAILY_LIMIT = 50


class UnlockIn(BaseModel):
    drama_id: int = Field(gt=0, strict=True)
    seq: int = Field(gt=0, strict=True)


async def _unlock_target(session: AsyncSession, open_id: str, drama_id: int, seq: int) -> Drama:
    drama = await session.get(Drama, drama_id)
    episode = await session.scalar(select(Episode.id).where(Episode.drama_id == drama_id, Episode.seq == seq))
    if (drama is None or drama.publish_status != 1 or episode is None
            or seq <= drama.free_episodes or seq > drama.total_episodes):
        raise HTTPException(400, "not_unlockable")
    if (await episode_access(session, open_id, drama, seq)).access != "locked":
        raise HTTPException(409, "already_entitled")
    return drama


async def _user_token(session: AsyncSession, tiktok: TikTokClient, open_id: str) -> str:
    user = await session.get(User, open_id)
    if user is None:
        raise HTTPException(401, "login_required")
    try:
        return await ensure_fresh_token(session, tiktok, user)
    except (LoginRequired, TikTokAPIError, httpx.HTTPError) as e:
        raise auth_failure(e) from e


# ---------------- Beans ----------------

class BeansOrderOut(BaseModel):
    order_id: str
    trade_order_id: str


class BeansPendingErrorOut(BaseModel):
    detail: str
    order_id: str | None = None


class BeansUnlockIn(UnlockIn):
    quantity: Literal[1, 3, 10] = 1
    expected_token_amount: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("quantity", mode="before")
    @classmethod
    def strict_quantity(cls, value):
        if type(value) is not int:
            raise ValueError("quantity must be an integer")
        return value


class BeansOfferOut(BaseModel):
    quantity: Literal[1, 3, 10]
    episode_seqs: list[int]
    token_amount: int
    available: bool


class UnlockOptionsOut(BaseModel):
    drama_id: int
    seq: int
    rewarded_ad: bool = True
    offers: list[BeansOfferOut]


async def _beans_offers(session: AsyncSession, open_id: str, drama: Drama, seq: int) -> list[BeansOfferOut]:
    present = set(await session.scalars(select(Episode.seq).where(
        Episode.drama_id == drama.id, Episode.seq >= seq, Episode.seq < seq + 10)))
    owned = set(await session.scalars(visible_entitlements().with_only_columns(Entitlement.seq).where(
        Entitlement.open_id == open_id, Entitlement.drama_id == drama.id)))
    locked = {n for n in present - owned if drama.free_episodes < n <= drama.total_episodes}
    return [BeansOfferOut(quantity=q, episode_seqs=list(range(seq, seq + q)),
                          token_amount=drama.unlock_price_beans * q,
                          available=drama.unlock_price_beans > 0 and set(range(seq, seq + q)) <= locked)
            for q in (1, 3, 10)]


@router.get("/dramas/{drama_id}/episodes/{seq}/unlock-options", response_model=UnlockOptionsOut)
async def unlock_options(drama_id: int, seq: int,
                         open_id: Annotated[str, Depends(current_open_id)],
                         session: Annotated[AsyncSession, Depends(get_session)]) -> UnlockOptionsOut:
    drama = await _unlock_target(session, open_id, drama_id, seq)
    offers = await _beans_offers(session, open_id, drama, seq) if iap_enabled() else []
    return UnlockOptionsOut(drama_id=drama_id, seq=seq, offers=offers)


class OrderStatusOut(BaseModel):
    order_id: str
    status: Literal["created", "paid", "refunded", "failed"]


@router.post("/orders/beans", response_model=BeansOrderOut, responses={
    code: {
        "model": BeansPendingErrorOut,
        "description": "Upstream failure: check any returned order_id before repaying",
    }
    for code in (502, 503, 504)
}, dependencies=[Depends(require_iap)])
async def create_beans_order(body: BeansUnlockIn, open_id: str = Depends(current_open_id),
                             session: AsyncSession = Depends(get_session),
                             tiktok: TikTokClient = Depends(get_tiktok)):
    drama = await _unlock_target(session, open_id, body.drama_id, body.seq)
    if drama.unlock_price_beans <= 0:
        raise HTTPException(400, "invalid_beans_price")
    offer = next(o for o in await _beans_offers(session, open_id, drama, body.seq) if o.quantity == body.quantity)
    if not offer.available:
        raise HTTPException(409, "offer_unavailable")
    if body.expected_token_amount is not None and body.expected_token_amount != offer.token_amount:
        raise HTTPException(409, "price_changed")
    token = await _user_token(session, tiktok, open_id)
    try:
        valid_amount = await tiktok.check_redeem_amount(token, offer.token_amount)
    except (TikTokAPIError, httpx.HTTPError) as e:
        raise auth_failure(e) from e
    if not valid_amount:
        raise HTTPException(400, "invalid_beans_price")
    order_id = f"b_{uuid.uuid4().hex}"
    # Persist the mapping first: an early webhook or uncertain upstream response must be recoverable.
    order = BeansOrder(order_id=order_id, open_id=open_id, drama_id=drama.id, seq=body.seq,
                       token_amount=offer.token_amount, episode_seqs=offer.episode_seqs)
    session.add(order)
    await session.commit()
    # Price comes from our DB, never from the client.
    try:
        trade_order_id = await tiktok.create_trade_order(
            token, order_id=order_id, token_amount=offer.token_amount,
            product_name=f"{drama.title} EP{body.seq}" +
                         (f"–{offer.episode_seqs[-1]}" if body.quantity > 1 else ""),
            quantity=body.quantity,
        )
    except (TikTokAPIError, httpx.HTTPError) as e:
        # No replay: timeout does not prove that TikTok failed to create the order.
        error = auth_failure(e)
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail, "order_id": order_id})
    order = await session.scalar(select(BeansOrder).where(BeansOrder.order_id == order_id)
                                 .with_for_update().execution_options(populate_existing=True))
    if order.trade_order_id not in (None, trade_order_id):
        raise HTTPException(502, "trade_order_mismatch")
    order.trade_order_id = trade_order_id
    await session.commit()
    return BeansOrderOut(order_id=order_id, trade_order_id=trade_order_id)


@router.get("/orders/beans/{order_id}", response_model=OrderStatusOut)
async def beans_order_status(order_id: str, open_id: str = Depends(current_open_id),
                             session: AsyncSession = Depends(get_session)):
    """Frontend polls this every 1–2s after TTMinis.pay() closes; webhook flips status to paid."""
    order = await session.get(BeansOrder, order_id)
    if order is None or order.open_id != open_id:
        raise HTTPException(404)
    return OrderStatusOut(order_id=order_id, status=order.status)


# ---------------- Rewarded ad ----------------

class AdNonceOut(BaseModel):
    nonce: str


@router.post("/ads/rewarded/nonce", response_model=AdNonceOut)
async def issue_ad_nonce(body: UnlockIn, open_id: str = Depends(current_open_id),
                         session: AsyncSession = Depends(get_session)):
    """Issued right before rewardedVideoAd.show(). Claimed only if onClose reports isEnded === true."""
    await _lock_ad_user(session, open_id)
    await _unlock_target(session, open_id, body.drama_id, body.seq)
    await _check_ad_limit(session, open_id)
    nonce = secrets.token_urlsafe(24)
    session.add(AdReward(nonce=nonce, open_id=open_id, drama_id=body.drama_id, seq=body.seq))
    await session.commit()
    return AdNonceOut(nonce=nonce)


async def _lock_ad_user(session: AsyncSession, open_id: str) -> None:
    # Serializes claims of DIFFERENT nonces too, so they cannot overrun the daily cap.
    user = await session.scalar(select(User).where(User.open_id == open_id).with_for_update())
    if user is None:
        raise HTTPException(401, "login_required")


async def _check_ad_limit(session: AsyncSession, open_id: str) -> None:
    since = datetime.now(UTC) - timedelta(days=1)
    count = await session.scalar(select(func.count()).select_from(AdReward).where(
        AdReward.open_id == open_id, AdReward.status == "claimed", AdReward.created_at >= since))
    if (count or 0) >= AD_DAILY_LIMIT:
        raise HTTPException(429, "ad_daily_limit")


class AdClaimIn(BaseModel):
    nonce: str = Field(min_length=1, max_length=64, strict=True)


class AdClaimOut(BaseModel):
    ok: Literal[True]


@router.post("/ads/rewarded/claim", response_model=AdClaimOut)
async def claim_ad_reward(body: AdClaimIn, open_id: str = Depends(current_open_id),
                          session: AsyncSession = Depends(get_session)):
    await _lock_ad_user(session, open_id)
    reward = await session.scalar(select(AdReward).where(AdReward.nonce == body.nonce).with_for_update())
    if reward is None or reward.open_id != open_id or reward.status != "issued":
        raise HTTPException(400, "invalid_nonce")
    created = reward.created_at if reward.created_at.tzinfo else reward.created_at.replace(tzinfo=UTC)
    if datetime.now(UTC) - created > AD_NONCE_TTL:
        reward.status = "expired"
        await session.commit()
        raise HTTPException(400, "nonce_expired")
    await _check_ad_limit(session, open_id)
    await _unlock_target(session, open_id, reward.drama_id, reward.seq)
    reward.status = "claimed"
    await grant_episode(session, open_id, reward.drama_id, reward.seq, "ad", reward.nonce)
    await session.commit()
    return {"ok": True}
