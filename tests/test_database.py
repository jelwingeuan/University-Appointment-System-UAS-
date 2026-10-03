from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from uas.extensions import db as orm
from uas.models import Appointment, Availability, User


def test_foreign_keys_and_unique_reference_are_enforced(app):
    if orm.engine.dialect.name == "sqlite":
        assert orm.session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    else:
        assert orm.engine.dialect.name == "postgresql"
    start = orm.session.get(Availability, 1).starts_at
    orm.session.add(
        Appointment(
            public_reference="same-reference",
            student_id=1,
            lecturer_id=3,
            availability_id=1,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
            purpose="test",
        )
    )
    orm.session.commit()
    orm.session.add(
        Appointment(
            public_reference="same-reference",
            student_id=1,
            lecturer_id=3,
            availability_id=1,
            starts_at=start + timedelta(minutes=30),
            ends_at=start + timedelta(minutes=60),
            purpose="duplicate",
        )
    )
    with pytest.raises(IntegrityError):
        orm.session.commit()
    orm.session.rollback()


def test_composite_foreign_key_rejects_mismatched_lecturer(app):
    start = orm.session.get(Availability, 1).starts_at
    orm.session.add(
        Appointment(
            public_reference="mismatch-reference",
            student_id=1,
            lecturer_id=4,
            availability_id=1,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
            purpose="test",
        )
    )
    with pytest.raises(IntegrityError):
        orm.session.commit()
    orm.session.rollback()


def test_user_and_availability_deletions_are_restricted(app):
    with pytest.raises(IntegrityError):
        orm.session.delete(orm.session.get(User, 3))
        orm.session.commit()
    orm.session.rollback()
    start = orm.session.get(Availability, 1).starts_at
    orm.session.add(
        Appointment(
            public_reference="restrict-window",
            student_id=1,
            lecturer_id=3,
            availability_id=1,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
            purpose="test",
        )
    )
    orm.session.commit()
    with pytest.raises(IntegrityError):
        orm.session.delete(orm.session.get(Availability, 1))
        orm.session.commit()
    orm.session.rollback()
