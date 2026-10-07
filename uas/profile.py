from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy.exc import IntegrityError

from .account_service import check_password, deliver_account_token, hash_password, issue_account_token
from .common import record_audit, require_actor, role_required, transaction, utc_now
from .extensions import db, limiter
from .notification_service import preferences_for, update_preferences
from .validation import InputValidationError, validate_account, validate_password

bp = Blueprint("profile", __name__)


def _profile_context(*, form_values=None, form_errors=None):
    preferences = preferences_for(db.session, current_user.id)
    return {
        "username": current_user.username,
        "email": current_user.email,
        "faculty": current_user.faculty,
        "phone_number": current_user.phone_number,
        "role": current_user.role,
        "email_verified": bool(current_user.email_verified_at),
        "verification_required": current_app.config.get("REQUIRE_EMAIL_VERIFICATION", False),
        "form_values": form_values or {},
        "form_errors": form_errors or {},
        "notification_preferences": preferences,
        "appointment_email_available": bool(current_app.config.get("APPOINTMENT_MAIL_DELIVERY_FACTORY")),
    }


@bp.get("/profile")
@login_required
def profile():
    return render_template("profile.html", **_profile_context())


@bp.post("/update_user_info")
@login_required
def update_user():
    form_values = {key: request.form.get(key, "") for key in ("username", "email", "phone_number")}
    try:
        fields = validate_account(role=current_user.role, **form_values)
    except InputValidationError as exc:
        return render_template(
            "profile.html",
            **_profile_context(form_values=form_values, form_errors=exc.errors),
        ), 400
    try:
        with transaction() as session:
            user = require_actor(session, current_user.id, current_user.role)
            email_changed = user.email.lower() != fields["email"].lower()
            user.username, user.email, user.phone_number = fields["username"], fields["email"], fields["phone_number"]
            if email_changed:
                user.email_verified_at = None if current_app.config.get("REQUIRE_EMAIL_VERIFICATION") else utc_now()
            record_audit(session, current_user.id, "account.profile_updated", "User", current_user.id)
        if email_changed and current_app.config.get("REQUIRE_EMAIL_VERIFICATION"):
            token = issue_account_token(current_user.id, "email_verification")
            deliver_account_token(fields["email"], "email_verification", token)
        flash("User information updated successfully", "success")
    except IntegrityError:
        flash("Those account details are already in use", "error")
    return redirect(url_for("profile.profile"))


@bp.post("/profile/notification-preferences")
@role_required("student", "teacher")
@limiter.limit("10 per hour")
def update_notification_preferences():
    with transaction() as session:
        require_actor(session, current_user.id, current_user.role)
        update_preferences(
            session,
            current_user.id,
            email_updates=request.form.get("email_updates") == "1",
            reminder_24h=request.form.get("reminder_24h") == "1",
            reminder_1h=request.form.get("reminder_1h") == "1",
        )
    flash("Notification preferences saved.", "success")
    return redirect(url_for("profile.profile"))


@bp.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template("changepassword.html", role=current_user.role)
    current_password, new_password = request.form.get("current_password", ""), request.form.get("new_password", "")
    if new_password != request.form.get("confirm_password", ""):
        flash("Password change could not be completed", "error")
        return redirect(url_for("profile.change_password"))
    try:
        validate_password(new_password)
    except InputValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("profile.change_password"))
    with transaction() as session:
        user = require_actor(session, current_user.id, current_user.role)
        if not check_password(current_password, user.password_hash):
            flash("Password change could not be completed", "error")
            return redirect(url_for("profile.change_password"))
        user.password_hash = hash_password(new_password)
        user.session_version += 1
        record_audit(session, current_user.id, "account.password_changed", "User", current_user.id)
    logout_user()
    flash("Password updated. Sign in again.", "success")
    return redirect(url_for("auth.login"))


@bp.get("/changepassword")
@login_required
def changepassword():
    return redirect(url_for("profile.change_password"))
