import json
import secrets
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename


def load_content():
    with Path(current_app.config["CONTENT_PATH"]).open(encoding="utf-8") as handle:
        return json.load(handle)


def save_content(content):
    path = Path(current_app.config["CONTENT_PATH"])
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(content, indent=2), encoding="utf-8")
    temporary.replace(path)


def save_image(upload):
    signatures = {
        "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
        "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
        "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
        "gif": ("image/gif", (b"GIF87a", b"GIF89a")),
    }
    name = secure_filename(upload.filename or "")
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    specification = signatures.get(extension)
    header = upload.stream.read(8)
    upload.stream.seek(0)
    if (
        not specification
        or upload.mimetype != specification[0]
        or not any(header.startswith(s) for s in specification[1])
    ):
        raise ValueError("Invalid image")
    stored_name = f"{Path(name).stem}-{secrets.token_hex(8)}.{extension}"
    destination = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name
    upload.save(destination)
    return stored_name
