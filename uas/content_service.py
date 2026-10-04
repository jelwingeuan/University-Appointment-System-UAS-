import io
import json
import re
import secrets
from pathlib import Path
from uuid import uuid4

from flask import current_app, send_from_directory


def load_content():
    with Path(current_app.config["CONTENT_PATH"]).open(encoding="utf-8") as handle:
        return json.load(handle)


def save_content(content):
    path = Path(current_app.config["CONTENT_PATH"])
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(content, indent=2), encoding="utf-8")
    temporary.replace(path)


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
    destination = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output.getvalue())
    return stored_name


def uploaded_image(filename):
    if not filename or not re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename):
        return ""
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, max_age=3600)


def remove_uploaded_image(filename):
    if filename and re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename):
        (Path(current_app.config["UPLOAD_FOLDER"]) / filename).unlink(missing_ok=True)
