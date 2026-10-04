import bcrypt
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .common import require_actor, transaction
from .validation import InputValidationError, validate_account

bp = Blueprint("profile", __name__)


@bp.get("/profile")
@login_required
def profile():
    return render_template(
        "profile.html",
        username=current_user.username,
        email=current_user.email,
        faculty=current_user.faculty,
        phone_number=current_user.phone_number,
        role=current_user.role,
        form_values={},
        form_errors={},
    )


@bp.post("/update_user_info")
@login_required
def update_user():
    form_values = {key: request.form.get(key, "") for key in ("username", "email", "phone_number")}
    try:
        fields = validate_account(role=current_user.role, **form_values)
    except InputValidationError as exc:
        return render_template(
            "profile.html",
            username=current_user.username,
            email=current_user.email,
            faculty=current_user.faculty,
            phone_number=current_user.phone_number,
            role=current_user.role,
            form_values=form_values,
            form_errors=exc.errors,
        ), 400
    try:
        with transaction() as session:
            user = require_actor(session, current_user.id, current_user.role)
            user.username, user.email, user.phone_number = fields["username"], fields["email"], fields["phone_number"]
        flash("User information updated successfully", "success")
    except IntegrityError:
        flash("Those account details are already in use", "error")
    return redirect(url_for("profile.profile"))


@bp.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template("changepassword.html")
    current_password, new_password = request.form.get("current_password", ""), request.form.get("new_password", "")
    if new_password != request.form.get("confirm_password", "") or not 8 <= len(new_password.encode("utf-8")) <= 72:
        flash("Password change could not be completed", "error")
        return redirect(url_for("profile.change_password"))
    with transaction() as session:
        user = require_actor(session, current_user.id, current_user.role)
        if not bcrypt.checkpw(current_password.encode(), user.password.encode()):
            flash("Password change could not be completed", "error")
            return redirect(url_for("profile.change_password"))
        user.password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    flash("Password updated", "success")
    return redirect(url_for("profile.profile"))


@bp.get("/changepassword")
@login_required
def changepassword():
    return redirect(url_for("profile.change_password"))
