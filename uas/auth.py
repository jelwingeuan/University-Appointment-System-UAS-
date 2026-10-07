from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user
from sqlalchemy import func, select

from .account_service import check_password, consume_account_token, deliver_account_token, issue_account_token
from .common import safe_next_url, utc_now
from .extensions import db, limiter
from .models import User
from .validation import InputValidationError, validate_password

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).where(func.lower(User.email) == email))
        valid = bool(
            user
            and user.active
            and (not current_app.config.get("REQUIRE_EMAIL_VERIFICATION") or user.email_verified_at)
            and check_password(password, user.password_hash)
        )
        if not valid:
            flash("Invalid email or password", "error")
            return redirect(url_for("auth.login"))
        user.last_login_at = utc_now()
        db.session.commit()
        session.permanent = True
        login_user(user, remember=False)
        destination = safe_next_url(request.args.get("next"))
        if destination:
            return redirect(destination)
        if user.role == "admin":
            return redirect(url_for("admin.admin_dashboard"))
        if user.role == "student":
            return redirect(url_for("appointments.appointment"))
        return redirect(url_for("public.home"))
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.home"))


@bp.route("/password-reset", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def password_reset_request():
    if request.method == "GET":
        return render_template("password_reset_request.html")
    email = request.form.get("email", "").strip().lower()
    user = db.session.scalar(select(User).where(func.lower(User.email) == email, User.active.is_(True)))
    if user:
        token = issue_account_token(user.id, "password_reset")
        deliver_account_token(user.email, "password_reset", token)
    flash("If that account can receive mail, password reset instructions have been sent.", "success")
    return redirect(url_for("auth.login"))


@bp.get("/password-reset/complete")
def password_reset_complete_form():
    return render_template("account_token.html", title="Reset password", endpoint="auth.password_reset_complete")


@bp.post("/password-reset/complete")
@limiter.limit("10 per hour")
def password_reset_complete():
    token = request.form.get("token", "")
    password = request.form.get("password", "")
    if password != request.form.get("confirm_password", ""):
        flash("Password reset could not be completed.", "error")
        return redirect(url_for("auth.password_reset_complete_form"))
    try:
        validate_password(password)
        complete = consume_account_token(token, "password_reset", new_password=password)
    except (InputValidationError, ValueError):
        complete = False
    if complete:
        flash("Password updated. Sign in with your new password.", "success")
        return redirect(url_for("auth.login"))
    flash("Password reset link is invalid or expired.", "error")
    return redirect(url_for("auth.password_reset_complete_form"))


@bp.get("/email-verification/complete")
def email_verification_form():
    return render_template("account_token.html", title="Verify email", endpoint="auth.email_verification_complete")


@bp.post("/email-verification/complete")
@limiter.limit("10 per hour")
def email_verification_complete():
    if consume_account_token(request.form.get("token", ""), "email_verification"):
        flash("Email address verified.", "success")
    else:
        flash("Verification link is invalid or expired.", "error")
    return redirect(url_for("auth.login"))


@bp.post("/email-verification")
@limiter.limit("5 per hour")
def email_verification_request():
    email = request.form.get("email", "").strip().lower()
    user = db.session.scalar(select(User).where(func.lower(User.email) == email, User.active.is_(True)))
    if user and not user.email_verified_at:
        token = issue_account_token(user.id, "email_verification")
        deliver_account_token(user.email, "email_verification", token)
    flash("If that account needs verification, instructions have been sent.", "success")
    return redirect(url_for("auth.login"))
