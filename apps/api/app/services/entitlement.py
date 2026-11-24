"""Single source of truth for "can this user watch this episode". Frontend never decides this."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import BeansOrder, Drama, Entitlement, Subscription

Access = Literal["free", "unlocked", "subscribed", "locked"]


@dataclass
class EpisodeAccess:
    access: Access
    unlock_price_beans: int | None = None


async def has_active_subscription(session: AsyncSession, open_id: str) -> bool:
    """Rights depend only on is_subscription_rights_valid + benefit_end_time, never the status name."""
    allow_sandbox = get_settings().sandbox_entitlements_allowed
    rows = (await session.scalars(select(Subscription).where(Subscription.open_id == open_id))).all()
    now = datetime.now(UTC)
    for sub in rows:
        if sub.is_sandbox and not allow_sandbox:
            continue
        end = sub.benefit_end_time
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if sub.rights_valid and end is not None and end > now:
            return True
    return False


async def episode_access(session: AsyncSession, open_id: str, drama: Drama, seq: int) -> EpisodeAccess:
    if seq <= drama.free_episodes:
        return EpisodeAccess("free")
    if await has_active_subscription(session, open_id):
        return EpisodeAccess("subscribed")
    owned = await session.scalar(
        visible_entitlements().where(
            Entitlement.open_id == open_id, Entitlement.drama_id == drama.id, Entitlement.seq == seq
        )
    )
    if owned:
        return EpisodeAccess("unlocked")
    return EpisodeAccess("locked", unlock_price_beans=drama.unlock_price_beans)


def visible_entitlements():
    """Also hide test purchases already granted before the sandbox gate was disabled."""
    stmt = select(Entitlement)
    if not get_settings().sandbox_entitlements_allowed:
        sandbox_order = exists(select(BeansOrder.order_id).where(
            Entitlement.source == "beans", BeansOrder.order_id == Entitlement.ref_id,
            BeansOrder.is_sandbox.is_(True)))
        stmt = stmt.where(~sandbox_order)
    return stmt


async def grant_episode(session: AsyncSession, open_id: str, drama_id: int, seq: int,
                        source: str, ref_id: str) -> bool:
    """True for a new grant or promotion of test rights to real rights. Caller commits."""
    # Database conflict handling keeps simultaneous payment/ad grants in one healthy transaction.
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = insert(Entitlement).values(
        open_id=open_id, drama_id=drama_id, seq=seq, source=source, ref_id=ref_id,
    )
    incoming_sandbox = source == "beans" and bool(await session.scalar(
        select(BeansOrder.is_sandbox).where(BeansOrder.order_id == ref_id)))
    if incoming_sandbox:
        stmt = stmt.on_conflict_do_nothing(index_elements=["open_id", "drama_id", "seq"])
    else:
        # A real purchase/ad can replace an earlier TEST unlock, including when the gate is off.
        old_sandbox = exists(select(BeansOrder.order_id).where(
            Entitlement.source == "beans", BeansOrder.order_id == Entitlement.ref_id,
            BeansOrder.is_sandbox.is_(True)))
        stmt = stmt.on_conflict_do_update(
            index_elements=["open_id", "drama_id", "seq"],
            set_={"source": source, "ref_id": ref_id}, where=old_sandbox)
    result = await session.execute(stmt)
    return result.rowcount == 1
