"""Webhook processing for Beans payments and subscriptions.

Rules (docs/PLAN.md §2.3):
- Verify signature on the raw body, then persist to webhook_events with a dedup_key BEFORE side effects.
- `content` is a JSON *string* and must be parsed a second time.
- cancel/renew create new trade_order_ids, so dedup on (event, subscription_id, trade_order_id, create_time).
- onhold/expire carry only subscription_id -> resolve open_id via the subscriptions table.
- is_sandbox events never grant entitlements in prod.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import BeansOrder, WebhookEvent
from app.services.entitlement import grant_episode
from app.services.subscriptions import apply_subscription_event

log = logging.getLogger(__name__)


def dedup_key(event: str, create_time: int | str, content: dict) -> str:
    return "|".join([
        event,
        str(content.get("subscription_id", "")),
        str(content.get("trade_order_id", "")),
        str(content.get("order_id", "")),
        str(create_time),
    ])


def content_from_raw(envelope: dict) -> dict:
    """`content` arrives as a JSON *string*, so it needs a second parse. Shared with the retry worker."""
    content = envelope.get("content") or "{}"
    if isinstance(content, str):
        content = json.loads(content)
    return content if isinstance(content, dict) else {}


async def record_event(session: AsyncSession, envelope: dict) -> tuple[WebhookEvent | None, dict]:
    """Returns (row, content). row is None when this exact event was already stored (redelivery)."""
    content = content_from_raw(envelope)
    row = WebhookEvent(
        event=envelope["event"],
        dedup_key=dedup_key(envelope["event"], envelope.get("create_time", ""), content),
        raw=envelope,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None, content
    return row, content


async def handle_event(session: AsyncSession, row: WebhookEvent, content: dict) -> bool:
    # HTTP delivery and the retry worker can overlap. Lock and re-read before applying effects.
    row = await session.scalar(select(WebhookEvent).where(WebhookEvent.id == row.id)
                               .with_for_update().execution_options(populate_existing=True))
    if row.processed_at is not None:
        return False
    handler = HANDLERS.get(row.event)
    if row.event in SUBSCRIPTION_EVENTS:
        await apply_subscription_event(session, row, content)
    elif handler is None:
        log.warning("unhandled webhook event %s", row.event)
    else:
        await handler(session, content)
    row.processed_at = datetime.now(UTC)
    row.error = None
    await session.commit()
    return True


MAX_PROCESS_ATTEMPTS = 5


async def retry_event(session: AsyncSession, event_id: int) -> str:
    """Re-run one stored event. Returns processed | retry | exhausted | missing.

    Safe to repeat: every handler is keyed on trade_order_id/subscription_id and grant_episode
    is idempotent, so a double run cannot double-grant.
    """
    row = await session.scalar(select(WebhookEvent).where(WebhookEvent.id == event_id).with_for_update()
                               .execution_options(populate_existing=True))
    if row is None or row.processed_at is not None:
        return "missing"
    try:
        if row.retries >= MAX_PROCESS_ATTEMPTS:
            return "exhausted"
        applied = await handle_event(session, row, content_from_raw(row.raw))
        return "processed" if applied else "missing"
    except Exception as e:
        await session.rollback()
        # Re-read: the rollback discarded the in-memory object's identity.
        row = await session.scalar(select(WebhookEvent).where(WebhookEvent.id == event_id).with_for_update()
                                   .execution_options(populate_existing=True))
        if row is None:
            return "missing"
        if row.processed_at is not None:
            return "missing"
        row.retries += 1
        row.error = type(e).__name__  # Provider payloads / user identities must not enter error logs.
        await session.commit()
        if row.retries >= MAX_PROCESS_ATTEMPTS:
            # Needs a human: a payment/subscription event that will never apply on its own.
            log.error("webhook %s (id=%s) unprocessable after %s attempts: %s",
                      row.event, event_id, row.retries, row.error)
            return "exhausted"
        log.warning("webhook %s (id=%s) attempt %s failed: %s", row.event, event_id, row.retries, row.error)
        return "retry"


def _sandbox_blocked(content: dict) -> bool:
    return bool(content.get("is_sandbox")) and not get_settings().sandbox_entitlements_allowed


# ---------------- Beans (IAP) ----------------

async def _beans_order(session: AsyncSession, c: dict) -> BeansOrder:
    trade_id, order_id = c.get("trade_order_id"), c.get("order_id")
    if not isinstance(trade_id, str) or not trade_id.strip() or len(trade_id) > 64:
        raise ValueError("invalid beans trade ID")
    if order_id is not None and (not isinstance(order_id, str) or not order_id or len(order_id) > 64):
        raise ValueError("invalid beans order ID")
    if "is_sandbox" in c and not isinstance(c["is_sandbox"], bool):
        raise ValueError("invalid sandbox flag")
    # The business ID also resolves orders whose create response has not reached us yet.
    predicate = BeansOrder.order_id == order_id if order_id else BeansOrder.trade_order_id == trade_id
    order = await session.scalar(select(BeansOrder).where(predicate).with_for_update()
                                 .execution_options(populate_existing=True))
    if order is None:
        raise LookupError("unknown beans order")
    if order.trade_order_id not in (None, trade_id):
        raise ValueError("beans order mapping mismatch")
    order.trade_order_id = trade_id
    return order


async def _beans_success(session: AsyncSession, c: dict) -> None:
    order = await _beans_order(session, c)
    # A late success must not resurrect a refunded order. Different deliveries still converge.
    if order.status in {"paid", "refunded"}:
        return
    order.status = "paid"
    order.is_sandbox = bool(c.get("is_sandbox"))
    if not _sandbox_blocked(c):
        for seq in order.episode_seqs or [order.seq]:
            await grant_episode(session, order.open_id, order.drama_id, seq, "beans", order.order_id)


async def _beans_refund(session: AsyncSession, c: dict) -> None:
    order = await _beans_order(session, c)
    order.status = "refunded"
    order.is_sandbox = order.is_sandbox or bool(c.get("is_sandbox"))
    # Product decision pending: revoke the unlocked episode on refund? Currently kept.


# ---------------- Subscription ----------------

SUBSCRIPTION_EVENTS = {
    f"minis.subscription.{kind}" for kind in
    ("create", "reactivate", "renew", "cancel", "onhold", "expire", "refund", "revoke")
}

HANDLERS = {
    "minis.trade_order.redeem.success": _beans_success,
    "minis.trade_order.redeem.refund_success": _beans_refund,
}
