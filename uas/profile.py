import bcrypt
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .common import require_actor, transaction

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
    )


@bp.post("/update_user_info")
@login_required
def update_user():
    username, email = request.form.get("username", "").strip(), request.form.get("email", "").strip().lower()
    phone = request.form.get("phone_number", "").strip()
    valid_domain = (
        (current_user.role == "student" and email.endswith("@student.mmu.edu.my"))
        or (current_user.role == "teacher" and email.endswith("@mmu.edu.my"))
        or (current_user.role == "admin" and "@" in email and not any(x.isspace() for x in email))
    )
    if not all((username, email, phone)) or not valid_domain:
        flash("Enter valid account details", "error")
        return redirect(url_for("profile.profile"))
    try:
        with transaction() as session:
            user = require_actor(session, current_user.id, current_user.role)
            user.username, user.email, user.phone_number = username, email, phone
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
    if new_password != request.form.get("confirm_password", "") or len(new_password) < 8:
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
