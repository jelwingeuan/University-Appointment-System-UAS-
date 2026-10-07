"""Add notification preferences, inbox and email outbox.

Revision ID: 0004_notifications
Revises: 0003_audit_log_ordering
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_notifications"
down_revision = "0003_audit_log_ordering"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade():
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("email_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reminder_24h", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reminder_1h", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.execute(
        "INSERT INTO notification_preferences (user_id, email_updates, reminder_24h, reminder_1h) "
        "SELECT id, TRUE, TRUE, TRUE FROM users"
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=True),
        sa.Column("deduplication_key", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("reminder_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "type IN ('appointment_requested', 'appointment_accepted', 'appointment_rejected', "
            "'appointment_cancelled', 'appointment_reminder')",
            name="ck_notifications_notification_type",
        ),
        sa.CheckConstraint(
            "reminder_offset_minutes IS NULL OR reminder_offset_minutes IN (60, 1440)",
            name="ck_notifications_reminder_offset",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deduplication_key", name="uq_notifications_deduplication_key"),
    )
    op.create_index(
        "ix_notifications_user_read_created",
        "notifications",
        ["user_id", "read_at", "created_at", "id"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="email"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("channel IN ('email')", name="ck_notification_deliveries_delivery_channel"),
        sa.CheckConstraint(
            "status IN ('Pending', 'Processing', 'Sent', 'Failed', 'Skipped')",
            name="ck_notification_deliveries_delivery_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_notification_deliveries_delivery_attempts"),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notification_id", "channel", name="uq_notification_delivery_channel"
        ),
    )
    op.create_index(
        "ix_notification_deliveries_due",
        "notification_deliveries",
        ["status", "next_attempt_at", "id"],
    )
    op.create_index(
        "ix_notification_deliveries_lease",
        "notification_deliveries",
        ["status", "claim_expires_at", "id"],
    )


def downgrade():
    op.drop_index("ix_notification_deliveries_lease", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_due", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
