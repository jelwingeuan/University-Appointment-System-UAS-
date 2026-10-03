"""Create the portable, normalized UAS schema.

Revision ID: 0001_orm_schema
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_orm_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "faculties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("faculty_name", sa.String(255), nullable=False),
        sa.Column("faculty_image", sa.String(255)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faculties")),
        sa.UniqueConstraint("faculty_name", name=op.f("uq_faculties_faculty_name")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("faculty_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(100), nullable=False),
        sa.Column("password", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint("role IN ('student', 'teacher', 'admin')", name=op.f("ck_users_role")),
        sa.ForeignKeyConstraint(
            ["faculty_id"], ["faculties.id"], ondelete="RESTRICT", name=op.f("fk_users_faculty_id_faculties")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        sa.UniqueConstraint("phone_number", name=op.f("uq_users_phone_number")),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_table(
        "availability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecturer_id", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_availability_time_range")),
        sa.CheckConstraint("slot_minutes > 0", name=op.f("ck_availability_slot_minutes")),
        sa.ForeignKeyConstraint(
            ["lecturer_id"], ["users.id"], ondelete="RESTRICT", name=op.f("fk_availability_lecturer_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability")),
        sa.UniqueConstraint("lecturer_id", "starts_at", "ends_at", name="uq_availability_window"),
        sa.UniqueConstraint("id", "lecturer_id", name="uq_availability_owner"),
    )
    op.create_index("ix_availability_lecturer_start", "availability", ["lecturer_id", "starts_at"])
    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_reference", sa.String(36), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("lecturer_id", sa.Integer(), nullable=False),
        sa.Column("availability_id", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), server_default="Pending", nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_appointments_time_range")),
        sa.CheckConstraint("length(trim(purpose)) BETWEEN 1 AND 500", name=op.f("ck_appointments_purpose")),
        sa.CheckConstraint(
            "status IN ('Pending', 'Accepted', 'Rejected', 'Cancelled')", name=op.f("ck_appointments_status")
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], ondelete="RESTRICT", name=op.f("fk_appointments_student_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["lecturer_id"], ["users.id"], ondelete="RESTRICT", name=op.f("fk_appointments_lecturer_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["availability_id", "lecturer_id"],
            ["availability.id", "availability.lecturer_id"],
            ondelete="RESTRICT",
            name="fk_appointments_availability_owner",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
        sa.UniqueConstraint("public_reference", name=op.f("uq_appointments_public_reference")),
    )
    op.create_index("ix_appointments_lecturer_start", "appointments", ["lecturer_id", "starts_at"])
    op.create_index("ix_appointments_student_start", "appointments", ["student_id", "starts_at"])
    op.create_index("ix_appointments_status", "appointments", ["status"])


def downgrade():
    op.drop_table("appointments")
    op.drop_table("availability")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("faculties")
