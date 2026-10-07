import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from flask_login import UserMixin
from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.types import DateTime, TypeDecorator

from .extensions import db


class Status(StrEnum):
    PENDING = "Pending"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"
    COMPLETED = "Completed"
    NO_SHOW = "No Show"


BLOCKING_STATUSES = (Status.PENDING.value, Status.ACCEPTED.value)


def _utc_now():
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """SQLite stores naive UTC; every Python value is timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=dialect.name != "sqlite"))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime must include a timezone")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Faculty(db.Model):
    __tablename__ = "faculties"
    id = db.Column(db.Integer, primary_key=True)
    faculty_name = db.Column(db.String(255), nullable=False, unique=True)
    faculty_image = db.Column(db.String(255))
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    updated_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, onupdate=_utc_now, server_default=func.now())
    members = db.relationship("User", back_populates="faculty_record", passive_deletes="all")


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculties.id", ondelete="RESTRICT"), nullable=False)
    username = db.Column(db.String(255), nullable=False, unique=True)
    email = db.Column(db.String(255), nullable=False)
    phone_number = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    updated_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, onupdate=_utc_now, server_default=func.now())
    last_login_at = db.Column(UTCDateTime())
    email_verified_at = db.Column(UTCDateTime())
    session_version = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    faculty_record = db.relationship("Faculty", back_populates="members")
    __table_args__ = (
        CheckConstraint("role IN ('student', 'teacher', 'admin')", name="role"),
        Index("uq_users_email_lower", func.lower(email), unique=True),
    )

    @property
    def faculty(self):
        return self.faculty_record.faculty_name

    @property
    def is_active(self):
        return self.active

    def get_id(self):
        return f"{self.id}:{self.session_version}"


class Availability(db.Model):
    __tablename__ = "availability"
    id = db.Column(db.Integer, primary_key=True)
    lecturer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    starts_at = db.Column(UTCDateTime(), nullable=False)
    ends_at = db.Column(UTCDateTime(), nullable=False)
    slot_minutes = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    updated_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, onupdate=_utc_now, server_default=func.now())
    lecturer = db.relationship("User")
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="time_range"),
        CheckConstraint("slot_minutes > 0", name="slot_minutes"),
        UniqueConstraint("lecturer_id", "starts_at", "ends_at", name="uq_availability_window"),
        UniqueConstraint("id", "lecturer_id", name="uq_availability_owner"),
        Index("ix_availability_lecturer_start", "lecturer_id", "starts_at"),
    )


class Appointment(db.Model):
    __tablename__ = "appointments"
    id = db.Column(db.Integer, primary_key=True)
    public_reference = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    lecturer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    availability_id = db.Column(db.Integer, nullable=False)
    starts_at = db.Column(UTCDateTime(), nullable=False)
    ends_at = db.Column(UTCDateTime(), nullable=False)
    purpose = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=Status.PENDING.value, server_default=Status.PENDING.value)
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    updated_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, onupdate=_utc_now, server_default=func.now())
    accepted_at = db.Column(UTCDateTime())
    cancelled_at = db.Column(UTCDateTime())
    completed_at = db.Column(UTCDateTime())
    no_show_at = db.Column(UTCDateTime())
    cancel_reason = db.Column(db.String(500))
    cancelled_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"))
    student = db.relationship("User", foreign_keys=[student_id])
    lecturer = db.relationship("User", foreign_keys=[lecturer_id])
    cancelled_by = db.relationship("User", foreign_keys=[cancelled_by_user_id])
    availability = db.relationship("Availability", viewonly=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["availability_id", "lecturer_id"],
            ["availability.id", "availability.lecturer_id"],
            ondelete="RESTRICT",
            name="fk_appointments_availability_owner",
        ),
        CheckConstraint("ends_at > starts_at", name="time_range"),
        CheckConstraint("length(trim(purpose)) BETWEEN 1 AND 500", name="purpose"),
        CheckConstraint("status IN ('Pending', 'Accepted', 'Rejected', 'Cancelled', 'Completed', 'No Show')", name="status"),
        Index("ix_appointments_lecturer_start", "lecturer_id", "starts_at"),
        Index("ix_appointments_student_start", "student_id", "starts_at"),
        Index("ix_appointments_status", "status"),
    )


class SiteSettings(db.Model):
    __tablename__ = "site_settings"
    id = db.Column(db.Integer, primary_key=True)
    home_content = db.Column(Text, nullable=False, default="")
    school_name = db.Column(db.String(200), nullable=False, default="Multimedia University")
    school_tel = db.Column(db.String(35), nullable=False, default="")
    school_email = db.Column(db.String(254), nullable=False, default="")
    school_logo = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    updated_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, onupdate=_utc_now, server_default=func.now())


class AccountToken(db.Model):
    __tablename__ = "account_tokens"
    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    purpose = db.Column(db.String(30), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    expires_at = db.Column(UTCDateTime(), nullable=False)
    used_at = db.Column(UTCDateTime())
    user = db.relationship("User")
    __table_args__ = (
        CheckConstraint("purpose IN ('email_verification', 'password_reset')", name="purpose"),
        Index("ix_account_tokens_user_purpose", "user_id", "purpose"),
    )

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LecturerInvitation(db.Model):
    __tablename__ = "lecturer_invitations"
    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    email = db.Column(db.String(254))
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    expires_at = db.Column(UTCDateTime(), nullable=False)
    used_at = db.Column(UTCDateTime())
    revoked_at = db.Column(UTCDateTime())
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    creator = db.relationship("User", foreign_keys=[created_by_id])
    __table_args__ = (Index("ix_lecturer_invitations_email_expires", "email", "expires_at"),)

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AppointmentStatusHistory(db.Model):
    __tablename__ = "appointment_status_history"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=False)
    from_status = db.Column(db.String(20), nullable=False)
    to_status = db.Column(db.String(20), nullable=False)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    reason = db.Column(db.String(500))
    appointment = db.relationship("Appointment")
    actor = db.relationship("User")
    __table_args__ = (
        CheckConstraint("from_status IN ('Pending', 'Accepted', 'Rejected', 'Cancelled', 'Completed', 'No Show')", name="from_status"),
        CheckConstraint("to_status IN ('Pending', 'Accepted', 'Rejected', 'Cancelled', 'Completed', 'No Show')", name="to_status"),
        Index("ix_appointment_status_history_appointment", "appointment_id", "created_at"),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    target_type = db.Column(db.String(80), nullable=False)
    target_id = db.Column(db.String(80), nullable=False)
    created_at = db.Column(UTCDateTime(), nullable=False, default=_utc_now, server_default=func.now())
    metadata_json = db.Column(JSON, nullable=False, default=dict)
    actor = db.relationship("User")
    __table_args__ = (
        Index("ix_audit_logs_target", "target_type", "target_id", "created_at"),
        Index("ix_audit_logs_created_id", "created_at", "id"),
    )
