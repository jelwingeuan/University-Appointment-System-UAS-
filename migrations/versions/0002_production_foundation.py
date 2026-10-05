"""Add lifecycle, settings, token and audit foundations.

Revision ID: 0002_production_foundation
Revises: 0001_orm_schema
"""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0002_production_foundation"
down_revision = "0001_orm_schema"
branch_labels = None
depends_on = None

STATUSES = "'Pending', 'Accepted', 'Rejected', 'Cancelled', 'Completed', 'No Show'"
NOW = sa.text("CURRENT_TIMESTAMP")


def _timestamp_column(name, *, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=NOW if not nullable else None)


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.alter_column("password", new_column_name="password_hash", existing_type=sa.String(255), nullable=False)
        batch.add_column(_timestamp_column("created_at"))
        batch.add_column(_timestamp_column("updated_at"))
        batch.add_column(_timestamp_column("last_login_at", nullable=True))
        batch.add_column(_timestamp_column("email_verified_at", nullable=True))
        batch.add_column(sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))
    if op.get_bind().dialect.name == "sqlite":
        op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    with op.batch_alter_table("faculties") as batch:
        batch.add_column(_timestamp_column("created_at"))
        batch.add_column(_timestamp_column("updated_at"))

    with op.batch_alter_table("availability") as batch:
        batch.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(_timestamp_column("created_at"))
        batch.add_column(_timestamp_column("updated_at"))

    with op.batch_alter_table("appointments") as batch:
        batch.drop_constraint(op.f("ck_appointments_status"), type_="check")
        batch.create_check_constraint(op.f("ck_appointments_status"), f"status IN ({STATUSES})")
        batch.add_column(_timestamp_column("created_at"))
        batch.add_column(_timestamp_column("updated_at"))
        batch.add_column(_timestamp_column("accepted_at", nullable=True))
        batch.add_column(_timestamp_column("cancelled_at", nullable=True))
        batch.add_column(_timestamp_column("completed_at", nullable=True))
        batch.add_column(_timestamp_column("no_show_at", nullable=True))
        batch.add_column(sa.Column("cancel_reason", sa.String(500), nullable=True))
        batch.add_column(sa.Column("cancelled_by_user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_appointments_cancelled_by_user_id_users"),
            "users",
            ["cancelled_by_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("home_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("school_name", sa.String(200), nullable=False, server_default="Multimedia University"),
        sa.Column("school_tel", sa.String(35), nullable=False, server_default=""),
        sa.Column("school_email", sa.String(254), nullable=False, server_default=""),
        sa.Column("school_logo", sa.String(255), nullable=False, server_default=""),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
    )
    content = {}
    root_content = Path(__file__).resolve().parents[2] / "content.json"
    try:
        content = json.loads(root_content.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    op.bulk_insert(
        sa.table(
            "site_settings",
            sa.column("id", sa.Integer()),
            sa.column("home_content", sa.Text()),
            sa.column("school_name", sa.String()),
            sa.column("school_tel", sa.String()),
            sa.column("school_email", sa.String()),
            sa.column("school_logo", sa.String()),
        ),
        [
            {
                "id": 1,
                "home_content": str(content.get("home_content", "")),
                "school_name": str(content.get("school_name", "Multimedia University")),
                "school_tel": str(content.get("school_tel", "")),
                "school_email": str(content.get("school_email", "")),
                "school_logo": str(content.get("school_logo", "")),
            }
        ],
    )

    op.create_table(
        "account_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("purpose IN ('email_verification', 'password_reset')", name=op.f("ck_account_tokens_purpose")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_account_tokens_user_purpose", "account_tokens", ["user_id", "purpose"])

    op.create_table(
        "lecturer_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(254)),
        _timestamp_column("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_lecturer_invitations_email_expires", "lecturer_invitations", ["email", "expires_at"])

    op.create_table(
        "appointment_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("reason", sa.String(500)),
        sa.CheckConstraint(f"from_status IN ({STATUSES})", name=op.f("ck_appointment_status_history_from_status")),
        sa.CheckConstraint(f"to_status IN ({STATUSES})", name=op.f("ck_appointment_status_history_to_status")),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_appointment_status_history_appointment", "appointment_status_history", ["appointment_id", "created_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(80), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id", "created_at"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM appointments WHERE status IN ('Completed', 'No Show')")).scalar_one():
        raise RuntimeError("Restore a pre-upgrade backup before downgrading after terminal appointment statuses exist")
    op.drop_table("audit_logs")
    op.drop_table("appointment_status_history")
    op.drop_table("lecturer_invitations")
    op.drop_table("account_tokens")
    op.drop_table("site_settings")
    with op.batch_alter_table("appointments") as batch:
        batch.drop_constraint(op.f("fk_appointments_cancelled_by_user_id_users"), type_="foreignkey")
        batch.drop_column("cancelled_by_user_id")
        batch.drop_column("cancel_reason")
        batch.drop_column("no_show_at")
        batch.drop_column("completed_at")
        batch.drop_column("cancelled_at")
        batch.drop_column("accepted_at")
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_constraint(op.f("ck_appointments_status"), type_="check")
        batch.create_check_constraint(
            op.f("ck_appointments_status"), "status IN ('Pending', 'Accepted', 'Rejected', 'Cancelled')"
        )
    with op.batch_alter_table("availability") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("active")
    with op.batch_alter_table("faculties") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("session_version")
        batch.drop_column("email_verified_at")
        batch.drop_column("last_login_at")
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.alter_column("password_hash", new_column_name="password", existing_type=sa.String(255), nullable=False)
    if op.get_bind().dialect.name == "sqlite":
        op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
