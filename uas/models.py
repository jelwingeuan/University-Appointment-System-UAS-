from datetime import UTC
from enum import StrEnum
from uuid import uuid4

from flask_login import UserMixin
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
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


BLOCKING_STATUSES = (Status.PENDING.value, Status.ACCEPTED.value)


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
    members = db.relationship("User", back_populates="faculty_record", passive_deletes="all")


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculties.id", ondelete="RESTRICT"), nullable=False)
    username = db.Column(db.String(255), nullable=False, unique=True)
    email = db.Column(db.String(255), nullable=False)
    phone_number = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
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


class Availability(db.Model):
    __tablename__ = "availability"
    id = db.Column(db.Integer, primary_key=True)
    lecturer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    starts_at = db.Column(UTCDateTime(), nullable=False)
    ends_at = db.Column(UTCDateTime(), nullable=False)
    slot_minutes = db.Column(db.Integer, nullable=False)
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
    student = db.relationship("User", foreign_keys=[student_id])
    lecturer = db.relationship("User", foreign_keys=[lecturer_id])
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
        CheckConstraint("status IN ('Pending', 'Accepted', 'Rejected', 'Cancelled')", name="status"),
        Index("ix_appointments_lecturer_start", "lecturer_id", "starts_at"),
        Index("ix_appointments_student_start", "student_id", "starts_at"),
        Index("ix_appointments_status", "status"),
    )
