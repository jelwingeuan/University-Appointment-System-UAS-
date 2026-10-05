from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .common import page_number, pagination, record_audit, require_actor, role_required, transaction
from .content_service import remove_uploaded_image, save_image
from .extensions import db
from .models import Faculty, User
from .validation import InputValidationError, clean_text

bp = Blueprint("faculty", __name__)


@bp.get("/faculty")
@role_required("admin")
def faculty():
    faculties = db.session.scalars(select(Faculty).order_by(Faculty.faculty_name)).all()
    selected_id = request.args.get("faculty_id", type=int) or (faculties[0].id if faculties else None)
    selected = db.session.get(Faculty, selected_id) if selected_id else None
    if selected_id and not selected:
        selected = faculties[0] if faculties else None
    total = (
        db.session.scalar(select(func.count()).select_from(User).where(User.faculty_id == selected.id)) if selected else 0
    ) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    members = (
        db.session.scalars(
            select(User).where(User.faculty_id == selected.id).order_by(User.role, User.username)
            .limit(pages["per_page"]).offset((pages["page"] - 1) * pages["per_page"])
        ).all()
        if selected else []
    )
    return render_template(
        "Faculty.html",
        faculties=faculties,
        selected_faculty=selected,
        lecturers=[user for user in members if user.role == "teacher"],
        students=[user for user in members if user.role == "student"],
        pagination=pages,
    )


@bp.route("/createfacultyhub", methods=["GET", "POST"])
@role_required("admin")
def create_faculty_hub():
    if request.method == "POST":
        uploaded = request.files.get("faculty_image")
        form_values = {"faculty_name": request.form.get("faculty_name", "")}
        form_errors = {}
        try:
            name = clean_text(form_values["faculty_name"], "faculty_name", maximum=255)
        except InputValidationError as exc:
            form_errors.update(exc.errors)
            name = ""
        if not uploaded or not uploaded.filename:
            form_errors["faculty_image"] = "Choose a JPEG, PNG, or WebP image."
        if name and db.session.scalar(select(Faculty.id).where(Faculty.faculty_name == name)):
            form_errors["faculty_name"] = "That faculty already exists."
        if form_errors:
            return render_template("createfacultyhub.html", form_values=form_values, form_errors=form_errors), 400
        filename = ""
        try:
            filename = save_image(uploaded)
            with transaction() as session:
                require_actor(session, current_user.id, "admin")
                row = Faculty(faculty_name=name, faculty_image=filename)
                session.add(row)
                session.flush()
                record_audit(session, current_user.id, "faculty.created", "Faculty", row.id)
        except ValueError:
            form_errors["faculty_image"] = "The file is not a valid supported image."
            return render_template("createfacultyhub.html", form_values=form_values, form_errors=form_errors), 400
        except IntegrityError:
            remove_uploaded_image(filename)
            form_errors["faculty_name"] = "That faculty already exists."
            return render_template("createfacultyhub.html", form_values=form_values, form_errors=form_errors), 409
        return redirect(url_for("faculty.faculty"))
    return render_template("createfacultyhub.html", form_values={}, form_errors={})
