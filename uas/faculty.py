from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from .common import page_number, pagination, record_audit, require_actor, role_required, transaction
from .content_service import remove_uploaded_image, save_image
from .extensions import db
from .models import Faculty, User
from .validation import InputValidationError, clean_text, validate_search

bp = Blueprint("faculty", __name__)


@bp.get("/explore")
@role_required("student")
def student_explore():
    search = request.args.get("q", "")
    try:
        search = validate_search(search)
    except InputValidationError:
        abort(400)
    faculty_id = request.args.get("faculty_id", type=int)
    selected = db.session.get(Faculty, faculty_id) if faculty_id else None
    if faculty_id and not selected:
        abort(404)

    faculties = db.session.scalars(select(Faculty).order_by(Faculty.faculty_name)).all()
    counts = dict(
        db.session.execute(
            select(User.faculty_id, func.count(User.id))
            .where(User.role == "teacher", User.active.is_(True))
            .group_by(User.faculty_id)
        ).all()
    )
    filters = [User.role == "teacher", User.active.is_(True)]
    if faculty_id:
        filters.append(User.faculty_id == faculty_id)
    if search:
        filters.append(
            or_(
                User.username.contains(search, autoescape=True),
                Faculty.faculty_name.contains(search, autoescape=True),
            )
        )
    total = (
        db.session.scalar(
            select(func.count(User.id)).join(User.faculty_record).where(*filters)
        )
        or 0
    )
    pages = pagination(page_number(request.args.get("page")), total, per_page=12)
    lecturers = db.session.scalars(
        select(User)
        .join(User.faculty_record)
        .options(joinedload(User.faculty_record))
        .where(*filters)
        .order_by(Faculty.faculty_name, User.username)
        .limit(pages["per_page"])
        .offset((pages["page"] - 1) * pages["per_page"])
    ).all()
    return render_template(
        "directory.html",
        faculties=faculties,
        faculty_counts=counts,
        selected_faculty=selected,
        lecturers=lecturers,
        search=search,
        pagination=pages,
    )


@bp.get("/faculty")
@role_required("admin")
def faculty():
    try:
        search = validate_search(request.args.get("q", ""))
    except InputValidationError:
        abort(400)
    faculty_statement = select(Faculty).order_by(Faculty.faculty_name)
    if search:
        faculty_statement = faculty_statement.where(Faculty.faculty_name.ilike(f"%{search}%"))
    faculties = db.session.scalars(faculty_statement).all()
    selected_id = request.args.get("faculty_id", type=int) or (faculties[0].id if faculties else None)
    selected = db.session.get(Faculty, selected_id) if selected_id else None
    if selected_id and (not selected or selected not in faculties):
        selected = faculties[0] if faculties else None
    counts = dict(
        db.session.execute(
            select(User.faculty_id, func.count(User.id)).group_by(User.faculty_id)
        ).all()
    )
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
        faculty_counts=counts,
        selected_faculty=selected,
        lecturers=[user for user in members if user.role == "teacher"],
        students=[user for user in members if user.role == "student"],
        pagination=pages,
        search=search,
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


@bp.route("/faculty/<int:faculty_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_faculty(faculty_id):
    faculty = db.session.get(Faculty, faculty_id)
    if not faculty:
        abort(404)
    if request.method == "GET":
        return render_template("edit_faculty.html", faculty=faculty, form_values={}, form_errors={})

    uploaded = request.files.get("faculty_image")
    form_values = {"faculty_name": request.form.get("faculty_name", "")}
    form_errors = {}
    try:
        name = clean_text(form_values["faculty_name"], "faculty_name", maximum=255)
    except InputValidationError as exc:
        form_errors.update(exc.errors)
        name = ""
    status_code = 400
    if name and db.session.scalar(
        select(Faculty.id).where(Faculty.faculty_name == name, Faculty.id != faculty_id)
    ):
        form_errors["faculty_name"] = "That faculty already exists."
        status_code = 409
    if form_errors:
        return render_template("edit_faculty.html", faculty=faculty, form_values=form_values, form_errors=form_errors), status_code

    filename = ""
    try:
        if uploaded and uploaded.filename:
            filename = save_image(uploaded)
        with transaction() as session:
            require_actor(session, current_user.id, "admin")
            updated = session.get(Faculty, faculty_id)
            if not updated:
                abort(404)
            updated.faculty_name = name
            if filename:
                updated.faculty_image = filename
            record_audit(session, current_user.id, "faculty.updated", "Faculty", updated.id)
    except ValueError as exc:
        remove_uploaded_image(filename)
        form_errors["faculty_image"] = str(exc) if str(exc) else "Choose a valid JPEG, PNG, or WebP image."
        return render_template("edit_faculty.html", faculty=faculty, form_values=form_values, form_errors=form_errors), 400
    except IntegrityError:
        remove_uploaded_image(filename)
        form_errors["faculty_name"] = "That faculty already exists."
        return render_template("edit_faculty.html", faculty=faculty, form_values=form_values, form_errors=form_errors), 409
    flash("Faculty updated.", "success")
    return redirect(url_for("faculty.faculty", faculty_id=faculty_id))
