import io
import re
from pathlib import Path
from uuid import uuid4

from flask import current_app, redirect, send_file

from .common import record_audit
from .extensions import db
from .models import SiteSettings


def load_content():
    row = db.session.get(SiteSettings, 1)
    if row:
        return {
            "home_content": row.home_content,
            "school_name": row.school_name,
            "school_tel": row.school_tel,
            "school_email": row.school_email,
            "school_logo": row.school_logo,
        }
    # Legacy JSON is read-only bootstrap fallback for unmigrated local installations.
    if current_app.config["APP_ENV"] != "production":
        import json

        try:
            return json.loads(Path(current_app.config["CONTENT_PATH"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"home_content": "", "school_name": "Multimedia University", "school_tel": "", "school_email": "", "school_logo": ""}


def save_content(content, actor_id=None):
    row = db.session.get(SiteSettings, 1)
    if row is None:
        row = SiteSettings(id=1)
        db.session.add(row)
    for key in ("home_content", "school_name", "school_tel", "school_email", "school_logo"):
        setattr(row, key, content.get(key, ""))
    if actor_id is not None:
        record_audit(db.session, actor_id, "site_settings.updated", "SiteSettings", 1)
    db.session.commit()


def save_image(upload):
    from PIL import Image, UnidentifiedImageError

    suffix = Path(upload.filename or "").suffix.lower()
    expected = {".jpg": ("JPEG", ".jpg"), ".jpeg": ("JPEG", ".jpg"), ".png": ("PNG", ".png"), ".webp": ("WEBP", ".webp")}
    if suffix not in expected:
        raise ValueError("Unsupported image type")
    image_format, output_suffix = expected[suffix]
    try:
        with Image.open(upload.stream) as source:
            if source.format != image_format or source.width * source.height > current_app.config["MAX_IMAGE_PIXELS"]:
                raise ValueError("Invalid image")
            source.load()
            pixels = source.convert("RGBA" if image_format in {"PNG", "WEBP"} else "RGB")
            output = io.BytesIO()
            options = {"quality": 90, "method": 6} if image_format == "WEBP" else {}
            if image_format == "JPEG":
                options = {"quality": 90, "optimize": True}
            elif image_format == "PNG":
                options = {"optimize": True}
            pixels.save(output, format=image_format, **options)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid image") from exc
    stored_name = f"{uuid4().hex}{output_suffix}"
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[image_format]
    current_app.extensions["image_storage"].save(stored_name, output.getvalue(), mime)
    return stored_name


def uploaded_image(filename):
    if not filename or not re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename):
        return ""
    storage = current_app.extensions["image_storage"]
    stored = storage.open(filename)
    if stored is not None:
        mime = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[filename.rsplit(".", 1)[1]]
        return send_file(stored, mimetype=mime, max_age=3600)
    target = storage.url(filename)
    return redirect(target) if target else ""


def remove_uploaded_image(filename):
    if filename and re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename):
        current_app.extensions["image_storage"].delete(filename)


def stored_image_url(filename):
    if not filename or not re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename):
        return ""
    return current_app.extensions["image_storage"].url(filename) or ""
