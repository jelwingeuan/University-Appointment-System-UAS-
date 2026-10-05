import hmac

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select
from werkzeug.exceptions import NotFound

from .account_service import (
    deliver_account_token,
    hash_password,
    issue_account_token,
    use_lecturer_invitation,
)
from .common import transaction, utc_now
from .content_service import uploaded_image
from .extensions import db, limiter
from .models import Faculty, User
from .validation import InputValidationError, clean_text, validate_account, validate_password

bp = Blueprint("public", __name__)


@bp.get("/uploads/<filename>")
def uploaded_image_route(filename):
    response = uploaded_image(filename)
    if not response:
        raise NotFound()
    return response


@bp.get("/")
def home():
    from .content_service import load_content

    content = load_content()
    return render_template("home.html", **content)


@bp.get("/about")
def about():
    return render_template("about.html")


@bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def signup():
    faculties = db.session.scalars(select(Faculty.faculty_name).order_by(Faculty.faculty_name)).all()
    if request.method == "POST":
        role = request.form.get("role", "")
        form_values = {
            key: request.form.get(key, "")
            for key in ("role", "faculty", "username", "email", "phone_number", "invitation")
        }
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        errors = {}
        if role not in {"student", "teacher"}:
            errors["role"] = "Select Student or Teacher."
        try:
            if not errors:
                fields = validate_account(
                    role=role,
                    username=form_values["username"],
                    email=form_values["email"],
                    phone_number=form_values["phone_number"],
                )
                faculty_name = clean_text(form_values["faculty"], "faculty", maximum=255)
                faculty = db.session.scalar(select(Faculty).where(Faculty.faculty_name == faculty_name))
                if not faculty:
                    errors["faculty"] = "Select a faculty from the list."
                if password != confirmation:
                    errors["password"] = "Passwords must match."
                else:
                    try:
                        validate_password(password)
                    except InputValidationError as exc:
                        errors.update(exc.errors)
            else:
                fields, faculty = {}, None
        except InputValidationError as exc:
            errors.update(exc.errors)
            fields, faculty = {}, None
        if role == "teacher" and not errors:
            expected = current_app.config.get("LECTURER_REGISTRATION_SECRET", "")
            provided = form_values["invitation"] or request.form.get("pin", "")
            legacy_allowed = current_app.config["APP_ENV"] != "production" and expected and hmac.compare_digest(
                provided.encode(), expected.encode()
            )
            if not provided or not legacy_allowed:
                if current_app.config["APP_ENV"] == "production":
                    # A one-time invitation is consumed below in the account transaction.
                    from .models import LecturerInvitation

                    invitation = db.session.scalar(
                        select(LecturerInvitation.id).where(
                            LecturerInvitation.token_hash == LecturerInvitation.hash_token(provided)
                        )
                    )
                    if not invitation:
                        errors["invitation"] = "A valid lecturer invitation is required."
                elif not provided:
                    errors["invitation"] = "A lecturer invitation is required."
        if errors:
            return render_template("signup.html", faculties=faculties, form_values=form_values, form_errors=errors), 400
        try:
            with transaction() as session:
                if role == "teacher":
                    provided = form_values["invitation"] or request.form.get("pin", "")
                    expected = current_app.config.get("LECTURER_REGISTRATION_SECRET", "")
                    legacy_allowed = current_app.config["APP_ENV"] != "production" and expected and hmac.compare_digest(
                        provided.encode(), expected.encode()
                    )
                    if not legacy_allowed:
                        use_lecturer_invitation(session, provided, fields["email"])
                user = User(
                    role=role,
                    faculty_id=faculty.id,
                    username=fields["username"],
                    email=fields["email"],
                    phone_number=fields["phone_number"],
                    password_hash=hash_password(password),
                    email_verified_at=None if current_app.config.get("REQUIRE_EMAIL_VERIFICATION") else utc_now(),
                )
                session.add(user)
                session.flush()
                created_user_id, created_email = user.id, user.email
            if current_app.config.get("REQUIRE_EMAIL_VERIFICATION"):
                token = issue_account_token(created_user_id, "email_verification")
                deliver_account_token(created_email, "email_verification", token)
            return redirect(url_for("auth.login"))
        except ValueError:
            errors["invitation"] = "Lecturer registration could not be verified."
            return render_template("signup.html", faculties=faculties, form_values=form_values, form_errors=errors), 400
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                flash("An account with those details already exists", "error")
                return redirect(url_for("public.signup"))
            raise
    return render_template("signup.html", faculties=faculties, form_values={}, form_errors={})
