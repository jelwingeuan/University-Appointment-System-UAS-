import bcrypt
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user
from sqlalchemy import func, select

from .common import safe_next_url
from .extensions import db, limiter
from .models import User

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).where(func.lower(User.email) == email))
        valid = bool(user and user.active and bcrypt.checkpw(password.encode(), user.password.encode()))
        if not valid:
            flash("Invalid email or password", "error")
            return redirect(url_for("auth.login"))
        login_user(user)
        destination = safe_next_url(request.args.get("next"))
        if destination:
            return redirect(destination)
        return redirect(url_for("admin.admin_dashboard") if user.role == "admin" else url_for("public.home"))
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.home"))
