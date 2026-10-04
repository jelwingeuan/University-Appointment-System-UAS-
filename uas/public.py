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

from .account_service import hash_password
from .common import transaction
from .content_service import uploaded_image
from .extensions import db, limiter
from .models import Faculty, User
from .validation import InputValidationError, clean_text, validate_account

bp = Blueprint("public", __name__)


@bp.get("/uploads/<filename>")
def uploaded_image_route(filename):
    response = uploaded_image(filename)
    if not response:
        raise NotFound()
    return response


@bp.get("/")
def home():
    import json

    with open(current_app.config["CONTENT_PATH"], encoding="utf-8") as handle:
        content = json.load(handle)
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
        form_values = {key: request.form.get(key, "") for key in ("role", "faculty", "username", "email", "phone_number")}
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
                if password != confirmation or not 8 <= len(password.encode("utf-8")) <= 72:
                    errors["password"] = "Passwords must match and contain 8 to 72 UTF-8 bytes."
            else:
                fields, faculty = {}, None
        except InputValidationError as exc:
            errors.update(exc.errors)
            fields, faculty = {}, None
        if role == "teacher" and not errors:
            expected = current_app.config.get("LECTURER_REGISTRATION_SECRET", "")
            provided = request.form.get("pin", "")
            if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
                errors["pin"] = "Lecturer registration could not be verified."
        if errors:
            return render_template("signup.html", faculties=faculties, form_values=form_values, form_errors=errors), 400
        try:
            with transaction() as session:
                session.add(
                    User(
                        role=role,
                        faculty_id=faculty.id,
                        username=fields["username"],
                        email=fields["email"],
                        phone_number=fields["phone_number"],
                        password=hash_password(password),
                    )
                )
            return redirect(url_for("auth.login"))
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                flash("An account with those details already exists", "error")
                return redirect(url_for("public.signup"))
            raise
    return render_template("signup.html", faculties=faculties, form_values={}, form_errors={})
