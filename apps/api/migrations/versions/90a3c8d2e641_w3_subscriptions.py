"""订阅状态顺序、订单恢复和账单记录。

Revision ID: 90a3c8d2e641
Revises: 673a789fcd7d
"""
from alembic import op
import sqlalchemy as sa

revision = "90a3c8d2e641"
down_revision = "673a789fcd7d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subscriptions", sa.Column("last_event_time", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("subscriptions", sa.Column("last_event_priority", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("subscription_orders", sa.Column("status", sa.String(16), nullable=False, server_default="created"))
    op.execute("UPDATE subscription_orders SET status = 'confirmed' WHERE subscription_id IS NOT NULL AND kind = 'create'")
    op.create_table("subscription_payments",
        sa.Column("trade_order_id", sa.String(64), primary_key=True),
        sa.Column("subscription_id", sa.String(64), sa.ForeignKey("subscriptions.subscription_id"), nullable=False),
        sa.Column("open_id", sa.String(128), sa.ForeignKey("users.open_id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_sandbox", sa.Boolean(), nullable=False),
        sa.Column("original_price", sa.String(64)), sa.Column("actual_price", sa.String(64)),
        sa.Column("currency", sa.String(8)), sa.Column("refund_price", sa.String(64)),
        sa.Column("refund_currency", sa.String(8)), sa.Column("discounts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_subscription_payments_subscription_id", "subscription_payments", ["subscription_id"])
    op.create_index("ix_subscription_payments_open_id", "subscription_payments", ["open_id"])


def downgrade():
    op.drop_table("subscription_payments")
    op.drop_column("subscription_orders", "status")
    op.drop_column("subscriptions", "last_event_priority")
    op.drop_column("subscriptions", "last_event_time")
