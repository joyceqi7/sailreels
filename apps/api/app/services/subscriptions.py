"""Subscription state is written only by signed webhooks; queries never manufacture benefits."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Subscription, SubscriptionOrder, SubscriptionPayment, User, WebhookEvent

# Same-second ambiguity resolves conservatively: revoke/expire win. Equal priority is a no-op.
PRIORITY = {"create": 10, "reactivate": 20, "renew": 30, "cancel": 40, "onhold": 50,
            "expire": 60, "revoke": 70}
DEBUG_TIERS = {
    "sandbox_499_1M": ("4.99", "MONTHLY"), "sandbox_1347_3M": ("13.47", "QUARTERLY"),
    "sandbox_699_1M": ("6.99", "MONTHLY"), "sandbox_1887_3M": ("18.87", "QUARTERLY"),
}


def utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def has_rights(sub: Subscription) -> bool:
    end = utc(sub.benefit_end_time)
    return bool(sub.rights_valid and end and end > datetime.now(UTC)
                and (not sub.is_sandbox or get_settings().sandbox_entitlements_allowed))


def checked_id(c: dict, key: str, limit: int = 64) -> str:
    value = c.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {key}")
    return value


def timestamp(value) -> int:
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError("invalid event timestamp")
    result = int(value)
    if result < 0 or result > 253402300799:
        raise ValueError("invalid event timestamp")
    return result


async def lock_user(session: AsyncSession, open_id: str) -> None:
    # All subscription writers use this lock, including concurrent create/reactivate requests.
    user = await session.scalar(select(User).where(User.open_id == open_id).with_for_update())
    if user is None:
        raise LookupError("unknown subscription user")


async def current_subscription(session: AsyncSession, open_id: str) -> Subscription | None:
    subs = list(await session.scalars(select(Subscription).where(Subscription.open_id == open_id)
                                    .order_by(Subscription.updated_at.desc(), Subscription.subscription_id)))
    # A later historical refund must never hide another still-valid subscription.
    return next((s for s in subs if has_rights(s)), next((s for s in subs if s.state == "onhold"),
                                                     subs[0] if subs else None))


def configured_tiers() -> list[str]:
    s = get_settings()
    tiers = [t for t in s.subscription_tier_ids if not t.startswith(("sandbox_", "testdeveloper_"))]
    if s.env != "prod" and s.subscription_sandbox_enabled:
        tiers += list(DEBUG_TIERS)
    return list(dict.fromkeys(tiers))


def _money(c: dict, key: str) -> str | None:
    value = c.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid monetary value")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0:
            raise ValueError("invalid monetary value")
    except InvalidOperation as e:
        raise ValueError("invalid monetary value") from e
    return value


async def _payment(session: AsyncSession, sub: Subscription, c: dict, kind: str) -> None:
    if kind not in {"create", "renew", "refund", "revoke"}:
        return
    trade = checked_id(c, "trade_order_id")
    payment = await session.get(SubscriptionPayment, trade)
    if payment is not None and (payment.subscription_id != sub.subscription_id or payment.open_id != sub.open_id):
        raise ValueError("subscription payment mapping mismatch")
    if payment is None:
        payment = SubscriptionPayment(trade_order_id=trade, subscription_id=sub.subscription_id,
                                      open_id=sub.open_id, status="paid", is_sandbox=sub.is_sandbox, discounts=[])
        session.add(payment)
    payment.is_sandbox = sub.is_sandbox
    # Financial terminal states survive delayed create/renew deliveries.
    if kind == "revoke" or (kind == "refund" and payment.status != "revoked"):
        payment.status = "revoked" if kind == "revoke" else "refunded"
    for key in ("original_price", "actual_price", "refund_price"):
        value = _money(c, key)
        if value is not None:
            setattr(payment, key, value)
    for key in ("currency", "refund_currency"):
        if key in c:
            value = c[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 8:
                raise ValueError("invalid currency")
            setattr(payment, key, value)
    if "discounts" in c:
        if not isinstance(c["discounts"], list) or len(c["discounts"]) > 1:
            raise ValueError("invalid discounts")
        payment.discounts = c["discounts"]


async def apply_subscription_event(session: AsyncSession, row: WebhookEvent, c: dict) -> None:
    kind = row.event.removeprefix("minis.subscription.")
    sid = checked_id(c, "subscription_id")
    if "is_sandbox" in c and type(c["is_sandbox"]) is not bool:
        raise ValueError("invalid sandbox flag")
    if kind == "create" and type(c.get("is_sandbox")) is not bool:
        raise ValueError("missing sandbox classification")
    event_time = timestamp(row.raw.get("create_time"))
    order = None
    if kind in {"create", "reactivate"}:
        trade = checked_id(c, "trade_order_id")
        predicate = (SubscriptionOrder.order_id == checked_id(c, "order_id") if c.get("order_id")
                     else SubscriptionOrder.trade_order_id == trade)
        order = await session.scalar(select(SubscriptionOrder).where(predicate))
        if order is None:
            raise LookupError("unknown subscription order")
        open_id = order.open_id
    else:
        known = await session.get(Subscription, sid)
        if known is None:
            # Out-of-order onhold/expire must be retried after create, never silently acknowledged as applied.
            raise LookupError("unknown subscription")
        open_id = known.open_id
    await lock_user(session, open_id)
    sub = await session.scalar(select(Subscription).where(Subscription.subscription_id == sid)
                               .with_for_update().execution_options(populate_existing=True))
    if kind == "create" and sub is None:
        sub = Subscription(subscription_id=sid, open_id=open_id, tier_id=order.tier_id,
                           is_sandbox=bool(c.get("is_sandbox")), rights_valid=False, renewal_normal=False,
                           last_event_time=0, last_event_priority=0)
        session.add(sub)
        await session.flush()
    if sub is None:
        raise LookupError("unknown subscription")
    if sub.open_id != open_id:
        raise ValueError("subscription owner mismatch")
    if "is_sandbox" in c and c["is_sandbox"] != sub.is_sandbox:
        raise ValueError("subscription sandbox mismatch")
    if order is not None:
        order = await session.scalar(select(SubscriptionOrder).where(SubscriptionOrder.order_id == order.order_id)
                                     .with_for_update().execution_options(populate_existing=True))
        if order.trade_order_id not in (None, trade) or order.subscription_id not in (None, sid):
            raise ValueError("subscription order mapping mismatch")
        if order.kind != kind or (kind == "create" and order.tier_id != sub.tier_id):
            raise ValueError("subscription order kind mismatch")
        order.trade_order_id, order.subscription_id = trade, sid
        order.status = "confirmed"
    await _payment(session, sub, c, kind)
    if kind == "refund":
        # A historical refund never changes current rights or the lifecycle cursor.
        return
    rank = PRIORITY[kind]
    if (event_time, rank) <= (sub.last_event_time, sub.last_event_priority):
        return
    # A revoked contract cannot be resurrected by an older period arriving with a newer envelope.
    if sub.state in {"revoked", "expired"} and kind not in {"expire", "revoke"}:
        return
    if kind in {"create", "renew"}:
        end = datetime.fromtimestamp(timestamp(c.get("benefit_end_time")), UTC)
        if utc(sub.benefit_end_time) and end < utc(sub.benefit_end_time):
            return
        sub.benefit_end_time = end
        sub.rights_valid = not (sub.is_sandbox and not get_settings().sandbox_entitlements_allowed)
        sub.renewal_normal, sub.state = True, "active"
    elif kind == "reactivate":
        # Only renew/create can extend benefits. Reactivate restores auto-renew, not expired rights.
        if sub.state in {"expired", "onhold"}:
            raise ValueError("invalid reactivate transition")
        sub.renewal_normal, sub.state = True, "active"
    elif kind in {"cancel", "onhold"}:
        sub.renewal_normal, sub.state = False, kind
    elif kind in {"expire", "revoke"}:
        sub.rights_valid, sub.renewal_normal = False, False
        sub.state = "expired" if kind == "expire" else "revoked"
    sub.last_event_time, sub.last_event_priority = event_time, rank
