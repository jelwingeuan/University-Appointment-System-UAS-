import secrets
from datetime import timedelta

import bcrypt
from sqlalchemy import select

from .common import record_audit, utc_now
from .models import Faculty, User
from .validation import validate_password


def hash_password(password):
    password = validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(password, password_hash):
    try:
        encoded = password.encode("utf-8")
        return len(encoded) <= 72 and bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except (AttributeError, TypeError, ValueError):
        return False


def bootstrap_admin(session, email, password):
    faculty = session.scalar(select(Faculty).where(Faculty.faculty_name == "Administration"))
    if not faculty:
        faculty = Faculty(faculty_name="Administration", faculty_image=None)
        session.add(faculty)
        session.flush()
    user = session.scalar(select(User).where(User.email.ilike(email)))
    password_hash = hash_password(password)
    if user:
        user.role, user.password_hash, user.active = "admin", password_hash, True
        user.faculty_id = faculty.id
        user.session_version += 1
        user.email_verified_at = user.email_verified_at or utc_now()
        return user
    user = User(
        role="admin",
        faculty_id=faculty.id,
        username=f"Administrator-{secrets.token_hex(4)}",
        email=email,
        phone_number=f"admin-{secrets.token_hex(6)}",
        password_hash=password_hash,
        email_verified_at=utc_now(),
    )
    session.add(user)
    return user


def issue_lecturer_invitation(actor_id, email=None, *, expires_in=timedelta(days=7)):
    from .common import transaction
    from .models import LecturerInvitation

    token = secrets.token_urlsafe(32)
    with transaction() as session:
        actor = session.get(User, int(actor_id))
        if not actor or actor.role != "admin" or not actor.active:
            raise PermissionError("Not authorized")
        invitation = LecturerInvitation(
            token_hash=LecturerInvitation.hash_token(token),
            email=email.strip().lower() if email else None,
            expires_at=utc_now() + expires_in,
            created_by_id=int(actor_id),
        )
        session.add(invitation)
        session.flush()
        record_audit(session, actor_id, "lecturer_invitation.created", "LecturerInvitation", invitation.id)
    return token


def use_lecturer_invitation(session, token, email):
    from sqlalchemy import select

    from .models import LecturerInvitation

    digest = LecturerInvitation.hash_token(token or "")
    invitation = session.scalar(
        select(LecturerInvitation).where(LecturerInvitation.token_hash == digest).with_for_update()
    )
    if (
        not invitation
        or invitation.used_at
        or invitation.revoked_at
        or invitation.expires_at <= utc_now()
        or (invitation.email and invitation.email.lower() != email.lower())
    ):
        raise ValueError("Lecturer invitation is invalid")
    invitation.used_at = utc_now()
    return invitation


def revoke_lecturer_invitation(actor_id, invitation_id):
    from .common import transaction
    from .models import LecturerInvitation

    with transaction() as session:
        actor = session.get(User, int(actor_id))
        invitation = session.scalar(
            select(LecturerInvitation).where(LecturerInvitation.id == invitation_id).with_for_update()
        )
        if not actor or actor.role != "admin" or not actor.active:
            raise PermissionError("Not authorized")
        if not invitation or invitation.used_at or invitation.revoked_at:
            raise ValueError("Invitation is unavailable")
        invitation.revoked_at = utc_now()
        record_audit(session, actor_id, "lecturer_invitation.revoked", "LecturerInvitation", invitation.id)


def deliver_account_token(email, purpose, token):
    """Use an optional application-supplied callable(email, purpose, token)."""
    from flask import current_app

    factory_path = current_app.config.get("MAIL_DELIVERY_FACTORY")
    if not factory_path:
        return False
    sender = current_app.extensions.get("mail_sender")
    if sender is None:
        import importlib

        module_name, separator, factory_name = factory_path.partition(":")
        if not separator:
            raise RuntimeError("MAIL_DELIVERY_FACTORY must use module:factory syntax")
        sender = getattr(importlib.import_module(module_name), factory_name)(current_app)
        if not callable(sender):
            raise RuntimeError("Mail delivery factory must return a callable")
        current_app.extensions["mail_sender"] = sender
    sender(email, purpose, token)
    return True


def issue_account_token(user_id, purpose, *, expires_in=timedelta(hours=1)):
    import secrets

    from .common import transaction
    from .models import AccountToken

    token = secrets.token_urlsafe(32)
    now = utc_now()
    with transaction() as session:
        user = session.get(User, int(user_id))
        if not user or not user.active:
            raise ValueError("Account unavailable")
        for old in session.scalars(
            select(AccountToken).where(
                AccountToken.user_id == user.id,
                AccountToken.purpose == purpose,
                AccountToken.used_at.is_(None),
            )
        ):
            old.used_at = now
        session.add(
            AccountToken(
                token_hash=AccountToken.hash_token(token),
                purpose=purpose,
                user_id=user.id,
                expires_at=now + expires_in,
            )
        )
    return token


def consume_account_token(token, purpose, *, new_password=None):
    from sqlalchemy import select

    from .common import transaction
    from .models import AccountToken

    digest = AccountToken.hash_token(token or "")
    now = utc_now()
    if purpose == "password_reset":
        from .validation import validate_password

        new_password = validate_password(new_password)
    with transaction() as session:
        record = session.scalar(
            select(AccountToken).where(AccountToken.token_hash == digest, AccountToken.purpose == purpose).with_for_update()
        )
        if not record or record.used_at or record.expires_at <= now or not record.user.active:
            return False
        record.used_at = now
        user = record.user
        if purpose == "email_verification":
            user.email_verified_at = now
        elif purpose == "password_reset":
            user.password_hash = hash_password(new_password)
            user.session_version += 1
            record_audit(session, user.id, "account.password_reset", "User", user.id)
            for pending in session.scalars(
                select(AccountToken).where(
                    AccountToken.user_id == user.id,
                    AccountToken.purpose == "password_reset",
                    AccountToken.used_at.is_(None),
                )
            ):
                pending.used_at = now
        else:
            return False
        return True
