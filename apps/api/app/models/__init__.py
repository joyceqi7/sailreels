"""Data model. See docs/PLAN.md §2.2–2.3 for the invariants these tables protect."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    open_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    access_token: Mapped[str] = mapped_column(String(512))
    refresh_token: Mapped[str] = mapped_column(String(512))
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str] = mapped_column(String(256), default="")
    nickname: Mapped[str | None] = mapped_column(String(128))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))


class Drama(TimestampMixin, Base):
    __tablename__ = "dramas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # TikTok album_id is int64 — always handle as string to avoid JS precision loss.
    album_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(String(2000), default="")
    cover_url: Mapped[str] = mapped_column(String(1024), default="")
    total_episodes: Mapped[int] = mapped_column(Integer, default=0)
    free_episodes: Mapped[int] = mapped_column(Integer, default=5)
    unlock_price_beans: Mapped[int] = mapped_column(Integer, default=100)
    # Metadata required by album/update album_info (all fields are mandatory there).
    language: Mapped[str] = mapped_column(String(16), default="en")
    year: Mapped[int] = mapped_column(Integer, default=2026)
    # 1 AIGC, 2 漫剧(anime), 3 真人配音(dubbed live action), 4 真人本地化(localised live action)
    drama_type: Mapped[int] = mapped_column(Integer, default=4)
    tags: Mapped[list] = mapped_column(JSON, default=list)  # tag_list, 1-3 values from 1..46 (32 unused)
    cover_pic_ids: Mapped[list] = mapped_column(JSON, default=list)  # open_pic_id from /image
    current_version: Mapped[str | None] = mapped_column(String(32))
    online_version: Mapped[str | None] = mapped_column(String(32))
    # album/review/submit returns this; album/review/appeal requires it. Losing it makes an appeal
    # impossible, so store it instead of only printing it in the CLI.
    review_id: Mapped[str | None] = mapped_column(String(32))
    # album/query review_status: 0 none, 1 reviewing, 2 approved, 3 rejected, 4 withdrawn
    review_status: Mapped[int] = mapped_column(Integer, default=0)
    # publish_status: 0 none, 1 online, 2 offline
    publish_status: Mapped[int] = mapped_column(Integer, default=0)


class Episode(TimestampMixin, Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("drama_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"))
    seq: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(256), default="")
    # Rewritten from album/update episode_id_map after every new version.
    episode_id: Mapped[str | None] = mapped_column(String(32))
    vid: Mapped[str | None] = mapped_column(String(64))
    cover_pic_id: Mapped[str | None] = mapped_column(String(128))  # open_pic_id from /image
    cover_url: Mapped[str] = mapped_column(String(1024), default="")
    source_url: Mapped[str] = mapped_column(String(1024), default="")


class MediaJob(TimestampMixin, Base):
    __tablename__ = "media_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # video | image | subtitle
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"))
    source_url: Mapped[str] = mapped_column(String(1024))
    job_id: Mapped[str | None] = mapped_column(String(64))
    result_id: Mapped[str | None] = mapped_column(String(64))  # vid / open_pic_id / mid
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|processing|done|failed
    retries: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(1024))


class Entitlement(Base):
    """One row per unlocked episode. Subscription access is checked separately, not materialised here."""

    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("open_id", "drama_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    open_id: Mapped[str] = mapped_column(ForeignKey("users.open_id"))
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"))
    seq: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))  # ad | beans
    ref_id: Mapped[str] = mapped_column(String(64))  # ad nonce / order_id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BeansOrder(TimestampMixin, Base):
    __tablename__ = "beans_orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    open_id: Mapped[str] = mapped_column(ForeignKey("users.open_id"))
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"))
    seq: Mapped[int] = mapped_column(Integer)
    # Immutable fulfillment snapshot; NULL on historical single-episode orders.
    episode_seqs: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    token_amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="created")  # created|paid|refunded|failed
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)


class Subscription(TimestampMixin, Base):
    """subscription_id -> open_id mapping is mandatory: onhold/expire webhooks carry only subscription_id."""

    __tablename__ = "subscriptions"

    subscription_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    open_id: Mapped[str] = mapped_column(ForeignKey("users.open_id"), index=True)
    tier_id: Mapped[str] = mapped_column(String(128))
    rights_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    renewal_normal: Mapped[bool] = mapped_column(Boolean, default=False)
    # Display only (active | cancel | onhold | expired | revoked). Access checks use rights_valid + end time.
    state: Mapped[str] = mapped_column(String(16), default="active")
    benefit_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)
    last_event_time: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    last_event_priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class SubscriptionOrder(TimestampMixin, Base):
    """Our order_id <-> trade_order_id, created before TTMinis.createSubscription()."""

    __tablename__ = "subscription_orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    open_id: Mapped[str] = mapped_column(ForeignKey("users.open_id"))
    tier_id: Mapped[str] = mapped_column(String(128))
    subscription_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="create")  # create | reactivate
    status: Mapped[str] = mapped_column(String(16), default="created", server_default="created")


class SubscriptionPayment(TimestampMixin, Base):
    """Verified subscription charges/refunds. No floats and no inferred wallet balance."""

    __tablename__ = "subscription_payments"
    trade_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("subscriptions.subscription_id"), index=True)
    open_id: Mapped[str] = mapped_column(ForeignKey("users.open_id"), index=True)
    status: Mapped[str] = mapped_column(String(16))  # paid | refunded | revoked
    is_sandbox: Mapped[bool] = mapped_column(Boolean)
    original_price: Mapped[str | None] = mapped_column(String(64))
    actual_price: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(8))
    refund_price: Mapped[str | None] = mapped_column(String(64))
    refund_currency: Mapped[str | None] = mapped_column(String(8))
    discounts: Mapped[list] = mapped_column(JSON, default=list)


class WebhookEvent(Base):
    """Every webhook is stored before processing; dedup_key makes redelivery a no-op."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    event: Mapped[str] = mapped_column(String(64))
    dedup_key: Mapped[str] = mapped_column(String(256), unique=True)
    raw: Mapped[dict] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped by the retry worker so a permanently-bad event stops being retried forever.
    retries: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdReward(Base):
    """Rewarded ads have no server callback. A one-time nonce limits replay of the client-side isEnded."""

    __tablename__ = "ad_rewards"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    open_id: Mapped[str] = mapped_column(ForeignKey("users.open_id"))
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"))
    seq: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="issued")  # issued | claimed | expired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchProgress(Base):
    __tablename__ = "watch_progress"

    open_id: Mapped[str] = mapped_column(ForeignKey("users.open_id"), primary_key=True)
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"), primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=1)
    position_seconds: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
