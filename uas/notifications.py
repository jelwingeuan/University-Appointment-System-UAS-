from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

from .common import page_number, pagination, role_required, transaction, university_zone, utc_now
from .extensions import db, limiter
from .models import Notification
from .notification_service import notification_for_display

bp = Blueprint("notifications", __name__)


@bp.get("/notifications")
@role_required("student", "teacher")
def index():
    view = request.args.get("view", "all")
    if view not in {"all", "unread"}:
        abort(400)
    conditions = [Notification.user_id == int(current_user.id)]
    if view == "unread":
        conditions.append(Notification.read_at.is_(None))
    total = db.session.scalar(
        select(func.count()).select_from(Notification).where(*conditions)
    ) or 0
    unread_count = db.session.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == int(current_user.id),
            Notification.read_at.is_(None),
        )
    ) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    rows = db.session.scalars(
        select(Notification)
        .options(joinedload(Notification.appointment))
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(pages["per_page"])
        .offset((pages["page"] - 1) * pages["per_page"])
    ).all()
    return render_template(
        "notifications.html",
        notifications=[notification_for_display(row, current_user.role) for row in rows],
        pagination=pages,
        view=view,
        unread_count=unread_count,
        local_timezone=university_zone(),
    )


@bp.post("/notifications/<int:notification_id>/read")
@role_required("student", "teacher")
@limiter.limit("30 per minute")
def mark_read(notification_id):
    with transaction() as session:
        result = session.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == int(current_user.id),
                Notification.read_at.is_(None),
            )
            .values(read_at=utc_now())
        )
        owned = session.scalar(
            select(Notification.id).where(
                Notification.id == notification_id,
                Notification.user_id == int(current_user.id),
            )
        )
        if not owned:
            abort(404)
    if result.rowcount:
        flash("Notification marked as read.", "success")
    return redirect(url_for("notifications.index"))


@bp.post("/notifications/read-all")
@role_required("student", "teacher")
@limiter.limit("10 per minute")
def mark_all_read():
    with transaction() as session:
        session.execute(
            update(Notification)
            .where(
                Notification.user_id == int(current_user.id),
                Notification.read_at.is_(None),
            )
            .values(read_at=utc_now())
        )
    flash("Notifications marked as read.", "success")
    return redirect(url_for("notifications.index"))


@bp.post("/notifications/<int:notification_id>/open")
@role_required("student", "teacher")
@limiter.limit("30 per minute")
def open_notification(notification_id):
    target = None
    with transaction() as session:
        row = session.scalar(
            select(Notification)
            .options(joinedload(Notification.appointment))
            .where(
                Notification.id == notification_id,
                Notification.user_id == int(current_user.id),
            )
            .with_for_update()
        )
        if not row:
            abort(404)
        row.read_at = row.read_at or utc_now()
        appointment = row.appointment
        if appointment:
            if current_user.role == "student" and appointment.student_id == int(current_user.id):
                target = url_for("appointments.invoice", reference=appointment.public_reference)
            elif current_user.role == "teacher" and appointment.lecturer_id == int(current_user.id):
                target = url_for(
                    "appointments.lecturer_detail",
                    public_reference=appointment.public_reference,
                )
    return redirect(target or url_for("notifications.index"))
