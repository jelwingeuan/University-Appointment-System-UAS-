from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .common import role_required, transaction
from .content_service import save_image
from .extensions import db
from .models import Faculty, User

bp = Blueprint("faculty", __name__)


@bp.get("/faculty")
@role_required("admin")
def faculty():
    rows = db.session.scalars(select(Faculty).order_by(Faculty.faculty_name)).all()
    faculty_data = []
    for item in rows:
        members = db.session.scalars(select(User).where(User.faculty_id == item.id).order_by(User.username)).all()
        faculty_data.append(
            {
                "faculty_name": item.faculty_name,
                "faculty_image": item.faculty_image,
                "lecturers": [u for u in members if u.role == "teacher"],
                "students": [u for u in members if u.role == "student"],
            }
        )
    return render_template("Faculty.html", faculty_info=faculty_data)


@bp.route("/createfacultyhub", methods=["GET", "POST"])
@role_required("admin")
def create_faculty_hub():
    if request.method == "POST":
        name, uploaded = request.form.get("faculty_name", "").strip(), request.files.get("faculty_image")
        if not name or not uploaded or not uploaded.filename:
            flash("A faculty name and valid image are required", "error")
            return redirect(url_for("faculty.create_faculty_hub"))
        try:
            filename = save_image(uploaded)
            with transaction() as session:
                session.add(Faculty(faculty_name=name, faculty_image=filename))
        except ValueError:
            flash("A faculty name and valid image are required", "error")
            return redirect(url_for("faculty.create_faculty_hub"))
        except IntegrityError:
            flash("That faculty already exists", "error")
            return redirect(url_for("faculty.create_faculty_hub"))
        return redirect(url_for("faculty.faculty"))
    hubs = db.session.scalars(select(Faculty).order_by(Faculty.faculty_name)).all()
    faculty_hubs = [
        {"id": row.id, "faculty_name": row.faculty_name, "faculty_image": row.faculty_image} for row in hubs
    ]
    return render_template("createfacultyhub.html", faculty_hubs=faculty_hubs)
