"""Subscription order lifecycle. Panel callbacks and platform queries never grant rights."""

import uuid
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import current_open_id
from app.models import Subscription, SubscriptionOrder
from app.routers.auth_errors import AUTH_RESPONSES, auth_failure
from app.routers.deps import get_tiktok, require_iap
from app.routers.monetization import _user_token
from app.services.subscriptions import DEBUG_TIERS, configured_tiers, current_subscription, has_rights, lock_user, utc
from app.tiktok.client import TikTokAPIError, TikTokClient

router = APIRouter(tags=["subscriptions"], responses=AUTH_RESPONSES)


class SubscribeIn(BaseModel):
    tier_id: str = Field(min_length=1, max_length=128, strict=True)


class SubscriptionOrderOut(BaseModel):
    order_id: str
    trade_order_id: str


class SubscriptionPendingErrorOut(BaseModel):
    detail: str
    order_id: str | None = None


ORDER_ERRORS = {code: {"model": SubscriptionPendingErrorOut,
    "description": "Check returned order_id before attempting another purchase"} for code in (409, 502, 503, 504)}


class SubscriptionOrderStatusOut(BaseModel):
    order_id: str
    trade_order_id: str | None
    kind: Literal["create", "reactivate"]
    status: Literal["created", "confirmed", "failed"]
    subscription_id: str | None


class SubscriptionStatusOut(BaseModel):
    active: bool
    state: Literal["none", "active", "cancel", "onhold", "expired", "revoked"]
    subscription_id: str | None = None
    benefit_end_time: datetime | None = None
    renewal_normal: bool = False
    is_sandbox: bool = False
    pending_order: SubscriptionOrderStatusOut | None = None


class SubscriptionTierOut(BaseModel):
    tier_id: str
    price: str
    currency: str
    deduct_cycle: str
    is_sandbox: bool


class PlatformSubscriptionOut(BaseModel):
    subscription_id: str
    tier_id: str
    state: Literal["active", "cancel", "onhold"]
    rights_valid: bool
    renewal_normal: bool
    end_time: datetime | None
    is_sandbox: bool


def order_out(order: SubscriptionOrder) -> SubscriptionOrderStatusOut:
    return SubscriptionOrderStatusOut(order_id=order.order_id, trade_order_id=order.trade_order_id,
        kind=order.kind, status=order.status, subscription_id=order.subscription_id)


def platform_out(item: dict) -> PlatformSubscriptionOut:
    rights, renewal = item["is_subscription_rights_valid"], item["is_renewal_normal"]
    end = item.get("end_time")
    return PlatformSubscriptionOut(subscription_id=item["subscription_id"], tier_id=item["tier_id"],
        state="active" if renewal else "cancel" if rights else "onhold", rights_valid=rights,
        renewal_normal=renewal, is_sandbox=item["is_sandbox"],
        end_time=datetime.fromtimestamp(int(end), UTC) if end is not None else None)


async def pending_order(session: AsyncSession, open_id: str) -> SubscriptionOrder | None:
    return await session.scalar(select(SubscriptionOrder).where(SubscriptionOrder.open_id == open_id,
        SubscriptionOrder.status == "created").order_by(SubscriptionOrder.created_at.desc()))


@router.get("/subscriptions/me", response_model=SubscriptionStatusOut)
async def my_subscription(open_id: str = Depends(current_open_id), session: AsyncSession = Depends(get_session)):
    sub = await current_subscription(session, open_id)
    pending = await pending_order(session, open_id)
    result = SubscriptionStatusOut(active=False, state="none", pending_order=order_out(pending) if pending else None)
    if sub:
        result.active = has_rights(sub)
        result.state = sub.state
        result.subscription_id = sub.subscription_id
        result.benefit_end_time = utc(sub.benefit_end_time)
        result.renewal_normal, result.is_sandbox = sub.renewal_normal, sub.is_sandbox
    return result


@router.get("/subscriptions/platform", response_model=list[PlatformSubscriptionOut])
async def platform_subscriptions(open_id: str = Depends(current_open_id), session: AsyncSession = Depends(get_session),
                                  tiktok: TikTokClient = Depends(get_tiktok)):
    token = await _user_token(session, tiktok, open_id)
    try:
        return [platform_out(item) for item in await tiktok.get_active_subscriptions(token)]
    except (TikTokAPIError, httpx.HTTPError) as e:
        raise auth_failure(e) from e


@router.get("/subscriptions/tiers", response_model=list[SubscriptionTierOut])
async def subscription_tiers(device_platform: Literal["android", "iphone"] = "android",
                              open_id: str = Depends(current_open_id), session: AsyncSession = Depends(get_session),
                              tiktok: TikTokClient = Depends(get_tiktok)):
    ids = configured_tiers()
    if not ids:
        return []
    debug = [SubscriptionTierOut(tier_id=i, price=DEBUG_TIERS[i][0], currency="USD",
                                deduct_cycle=DEBUG_TIERS[i][1], is_sandbox=True) for i in ids if i in DEBUG_TIERS]
    real_ids = [i for i in ids if i not in DEBUG_TIERS]
    if not real_ids:
        return debug
    token = await _user_token(session, tiktok, open_id)
    try:
        data = await tiktok.get_subscription_tiers(token, real_ids, device_platform)
    except (TikTokAPIError, httpx.HTTPError) as e:
        raise auth_failure(e) from e
    # TODO(confirm): local guide says sandbox tier queries unsupported, public API lists them.
    # Debug prices above are explicitly labeled test fixtures; real prices always come from TikTok.
    return debug + [SubscriptionTierOut(tier_id=i, price=data[i]["price"], currency=data[i]["currency"],
        deduct_cycle=data[i]["deduct_cycle"], is_sandbox=False) for i in real_ids if i in data]


async def _create_order(session: AsyncSession, tiktok: TikTokClient, open_id: str,
                        tier_id: str | None = None, subscription_id: str | None = None):
    token = await _user_token(session, tiktok, open_id)
    await lock_user(session, open_id)
    existing = await pending_order(session, open_id)
    if existing:
        return JSONResponse(status_code=409, content={"detail": "subscription_order_pending",
                                                     "order_id": existing.order_id})
    # Check before either action, even if the local webhook projection is missing or delayed.
    try:
        platform = await tiktok.get_active_subscriptions(token)
    except (TikTokAPIError, httpx.HTTPError) as e:
        raise auth_failure(e) from e
    if subscription_id:
        sub = await session.get(Subscription, subscription_id)
        if sub is None or sub.open_id != open_id:
            raise HTTPException(404, "subscription_not_found")
        current = next((p for p in platform if p["subscription_id"] == subscription_id), None)
        if (sub.state != "cancel" or not has_rights(sub) or current is None
                or platform_out(current).state != "cancel"):
            raise HTTPException(409, "subscription_state_conflict")
        end = platform_out(current).end_time
        # Renewal may occur before benefits end. Prefer the actual next deduction timestamp.
        if current.get("next_duduct_time") is not None:
            end = datetime.fromtimestamp(int(current["next_duduct_time"]), UTC)
        block = 120 if current["is_sandbox"] else 86400
        if end is None or (end - datetime.now(UTC)).total_seconds() <= block:
            raise HTTPException(409, "subscription_reactivation_blocked")
        tier_id = sub.tier_id
    elif platform or any(s.state in {"active", "cancel", "onhold"} and (has_rights(s) or s.state == "onhold")
                        for s in await session.scalars(select(Subscription).where(Subscription.open_id == open_id))):
        raise HTTPException(409, "active_subscription_exists")
    kind = "reactivate" if subscription_id else "create"
    order = SubscriptionOrder(order_id=f"s_{uuid.uuid4().hex}", open_id=open_id, tier_id=tier_id,
                              subscription_id=subscription_id, kind=kind)
    session.add(order)
    # The mapping MUST be visible before the upstream call can deliver an early webhook.
    await session.commit()
    order_id = order.order_id
    try:
        if subscription_id:
            trade = await tiktok.reactivate_subscription(token, subscription_id=subscription_id, order_id=order_id,
                                                        product_name="SailReels VIP")
        else:
            trade = await tiktok.create_subscription(token, tier_id=tier_id, order_id=order_id,
                                                    product_name="SailReels VIP")
    except (TikTokAPIError, httpx.HTTPError) as e:
        error = auth_failure(e)
        # No blind retry after an uncertain response. A later signed event can resolve this order.
        if isinstance(e, TikTokAPIError) and (400 <= e.status < 500 or e.code in {
            "tier_not_found", "active_subscription_exists", "subscription_state_conflict", "20001003",
            "20021101", "20021102", "20021103", "20021111",
        }):
            error = HTTPException(409, "subscription_state_conflict")
            order = await session.scalar(select(SubscriptionOrder).where(SubscriptionOrder.order_id == order_id)
                                         .with_for_update().execution_options(populate_existing=True))
            if order.status == "created":
                order.status = "failed"
            await session.commit()
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail, "order_id": order_id})
    order = await session.scalar(select(SubscriptionOrder).where(SubscriptionOrder.order_id == order_id)
                                 .with_for_update().execution_options(populate_existing=True))
    if order.trade_order_id not in (None, trade):
        raise HTTPException(502, "trade_order_mismatch")
    order.trade_order_id = trade
    await session.commit()
    return SubscriptionOrderOut(order_id=order_id, trade_order_id=trade)


@router.post("/subscriptions", response_model=SubscriptionOrderOut, responses=ORDER_ERRORS,
             dependencies=[Depends(require_iap)])
async def create_subscription(body: SubscribeIn, open_id: str = Depends(current_open_id),
                              session: AsyncSession = Depends(get_session),
                              tiktok: TikTokClient = Depends(get_tiktok)):
    if body.tier_id not in configured_tiers():
        raise HTTPException(400, "subscription_tier_unavailable")
    return await _create_order(session, tiktok, open_id, tier_id=body.tier_id)


@router.post("/subscriptions/{subscription_id}/reactivate", response_model=SubscriptionOrderOut, responses=ORDER_ERRORS,
             dependencies=[Depends(require_iap)])
async def reactivate_subscription(subscription_id: str, open_id: str = Depends(current_open_id),
                                  session: AsyncSession = Depends(get_session),
                                  tiktok: TikTokClient = Depends(get_tiktok)):
    return await _create_order(session, tiktok, open_id, subscription_id=subscription_id)


@router.get("/orders/subscriptions/{order_id}", response_model=SubscriptionOrderStatusOut)
async def subscription_order_status(order_id: str, open_id: str = Depends(current_open_id),
                                     session: AsyncSession = Depends(get_session)):
    order = await session.get(SubscriptionOrder, order_id)
    if order is None or order.open_id != open_id:
        raise HTTPException(404)
    return order_out(order)


class SubscriptionOrderQueryOut(BaseModel):
    order: SubscriptionOrderStatusOut
    platform_status: str | None = None
    awaiting_webhook: bool


@router.post("/orders/subscriptions/{order_id}/query", response_model=SubscriptionOrderQueryOut)
async def query_subscription_order(order_id: str, open_id: str = Depends(current_open_id),
                                    session: AsyncSession = Depends(get_session),
                                    tiktok: TikTokClient = Depends(get_tiktok)):
    order = await session.get(SubscriptionOrder, order_id)
    if order is None or order.open_id != open_id:
        raise HTTPException(404)
    platform_status = None
    if order.trade_order_id:
        token = await _user_token(session, tiktok, open_id)
        try:
            data = await tiktok.get_subscription_trade_order(token, order.trade_order_id)
        except (TikTokAPIError, httpx.HTTPError) as e:
            raise auth_failure(e) from e
        if data.get("trade_order_id") != order.trade_order_id:
            raise HTTPException(502, "trade_order_mismatch")
        platform_status = data.get("trade_order_status")
    return SubscriptionOrderQueryOut(order=order_out(order), platform_status=platform_status,
                                     awaiting_webhook=order.status == "created")
