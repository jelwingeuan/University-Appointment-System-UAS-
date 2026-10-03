import secrets

import bcrypt
from sqlalchemy import select

from .models import Faculty, User


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def bootstrap_admin(session, email, password):
    faculty = session.scalar(select(Faculty).where(Faculty.faculty_name == "Administration"))
    if not faculty:
        faculty = Faculty(faculty_name="Administration", faculty_image=None)
        session.add(faculty)
        session.flush()
    user = session.scalar(select(User).where(User.email.ilike(email)))
    password_hash = hash_password(password)
    if user:
        user.role, user.password, user.active = "admin", password_hash, True
        user.faculty_id = faculty.id
        return user
    user = User(
        role="admin",
        faculty_id=faculty.id,
        username=f"Administrator-{secrets.token_hex(4)}",
        email=email,
        phone_number=f"admin-{secrets.token_hex(6)}",
        password=password_hash,
    )
    session.add(user)
    return user
