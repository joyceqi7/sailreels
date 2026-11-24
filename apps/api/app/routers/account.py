"""Personal data is always scoped to the session. History metadata contains no playback credentials."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import current_open_id
from app.models import BeansOrder, Drama, Episode, SubscriptionPayment, WatchProgress
from app.services.entitlement import episode_access

router = APIRouter(tags=["account"])


class ProgressIn(BaseModel):
    seq: int = Field(gt=0, strict=True)
    position_seconds: int = Field(ge=0, le=86400, strict=True)


class ProgressOut(BaseModel):
    drama_id: int
    last_seq: int
    position_seconds: int
    updated_at: datetime


class HistoryItemOut(ProgressOut):
    title: str
    cover_url: str
    available: bool


class HistoryOut(BaseModel):
    items: list[HistoryItemOut]
    has_more: bool


@router.get("/me/progress/{drama_id}", response_model=ProgressOut | None)
async def get_progress(drama_id: int, open_id: str = Depends(current_open_id),
                       session: AsyncSession = Depends(get_session)):
    row = await session.get(WatchProgress, (open_id, drama_id))
    return ProgressOut.model_validate(row, from_attributes=True) if row else None


@router.put("/me/progress/{drama_id}", response_model=ProgressOut)
async def save_progress(drama_id: int, body: ProgressIn, open_id: str = Depends(current_open_id),
                        session: AsyncSession = Depends(get_session)):
    drama = await session.get(Drama, drama_id)
    ep = await session.scalar(select(Episode.id).where(Episode.drama_id == drama_id, Episode.seq == body.seq))
    if drama is None or drama.publish_status != 1 or ep is None:
        raise HTTPException(404)
    if (await episode_access(session, open_id, drama, body.seq)).access == "locked":
        raise HTTPException(403, "episode_locked")
    # Do not use max(position): deliberately seeking backward must be remembered too.
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    values = {"open_id": open_id, "drama_id": drama_id, "last_seq": body.seq,
              "position_seconds": body.position_seconds, "updated_at": datetime.now(UTC)}
    await session.execute(insert(WatchProgress).values(**values).on_conflict_do_update(
        index_elements=["open_id", "drama_id"], set_={k: v for k, v in values.items()
                                                   if k not in {"open_id", "drama_id"}}))
    await session.commit()
    row = await session.get(WatchProgress, (open_id, drama_id), populate_existing=True)
    return ProgressOut.model_validate(row, from_attributes=True)


@router.get("/me/history", response_model=HistoryOut)
async def watch_history(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000),
                        open_id: str = Depends(current_open_id), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(WatchProgress, Drama).join(Drama, WatchProgress.drama_id == Drama.id)
        .where(WatchProgress.open_id == open_id).order_by(WatchProgress.updated_at.desc(), WatchProgress.drama_id)
        .offset(offset).limit(limit + 1))).all()
    return HistoryOut(has_more=len(rows) > limit, items=[HistoryItemOut(
        **ProgressOut.model_validate(progress, from_attributes=True).model_dump(), title=drama.title,
        cover_url=drama.cover_url, available=drama.publish_status == 1) for progress, drama in rows[:limit]])


class WalletEntryOut(BaseModel):
    id: str
    kind: Literal["beans", "subscription"]
    title: str
    status: str
    is_sandbox: bool
    created_at: datetime
    token_amount: int | None = None
    actual_price: str | None = None
    currency: str | None = None
    refund_price: str | None = None
    refund_currency: str | None = None


class WalletOut(BaseModel):
    # TikTok owns the Beans wallet. A sum of purchases is not an available balance.
    beans_balance: int | None = None
    items: list[WalletEntryOut]
    has_more: bool


@router.get("/me/wallet", response_model=WalletOut)
async def wallet(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000),
                 open_id: str = Depends(current_open_id), session: AsyncSession = Depends(get_session)):
    # Bounded reads from each ledger then stable merge; avoids loading a user's entire purchase history.
    count = offset + limit + 1
    beans = (await session.execute(select(BeansOrder, Drama.title).join(Drama, BeansOrder.drama_id == Drama.id)
        .where(BeansOrder.open_id == open_id).order_by(BeansOrder.created_at.desc(), BeansOrder.order_id)
        .limit(count))).all()
    payments = list(await session.scalars(select(SubscriptionPayment).where(SubscriptionPayment.open_id == open_id)
        .order_by(SubscriptionPayment.created_at.desc(), SubscriptionPayment.trade_order_id).limit(count)))
    items = [WalletEntryOut(id=o.order_id, kind="beans", title=title, status=o.status, is_sandbox=o.is_sandbox,
                           created_at=o.created_at, token_amount=o.token_amount) for o, title in beans]
    items += [WalletEntryOut(id=p.trade_order_id, kind="subscription", title="SailReels VIP", status=p.status,
        is_sandbox=p.is_sandbox, created_at=p.created_at, actual_price=p.actual_price, currency=p.currency,
        refund_price=p.refund_price, refund_currency=p.refund_currency) for p in payments]
    items.sort(key=lambda item: (-item.created_at.replace(tzinfo=UTC).timestamp(), item.id))
    return WalletOut(items=items[offset:offset + limit], has_more=len(items) > offset + limit)
