import io
from pathlib import Path

import pytest
from PIL import Image

from tests.conftest import login
from uas.content_service import save_image
from uas.extensions import db
from uas.models import Faculty


def image_bytes(fmt, size=(8, 8)):
    stream = io.BytesIO()
    Image.new("RGBA" if fmt in {"PNG", "WEBP"} else "RGB", size, (20, 80, 140, 160)
              if fmt in {"PNG", "WEBP"} else (20, 80, 140)).save(stream, format=fmt)
    return stream.getvalue()


@pytest.mark.parametrize(("fmt", "filename"), [("JPEG", "profile.jpg"), ("PNG", "profile.png"), ("WEBP", "profile.webp")])
def test_valid_image_is_reencoded_to_random_private_storage(app, fmt, filename):
    from werkzeug.datastructures import FileStorage

    uploaded = FileStorage(stream=io.BytesIO(image_bytes(fmt)), filename=filename)
    stored = save_image(uploaded)
    assert Path(stored).name == stored
    assert stored != filename
    assert (Path(app.config["UPLOAD_FOLDER"]) / stored).is_file()
    with Image.open(Path(app.config["UPLOAD_FOLDER"]) / stored) as decoded:
        assert decoded.format == fmt


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("fake.jpg", b"plain text"),
        ("page.jpg", b"<html><script>alert(1)</script></html>"),
        ("vector.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        ("unsupported.gif", b"GIF89a"),
    ],
)
def test_fake_scriptable_and_unsupported_files_are_rejected(app, filename, payload):
    from werkzeug.datastructures import FileStorage

    with pytest.raises(ValueError):
        save_image(FileStorage(stream=io.BytesIO(payload), filename=filename))


def test_extension_must_match_decoded_format(app):
    from werkzeug.datastructures import FileStorage

    with pytest.raises(ValueError):
        save_image(FileStorage(stream=io.BytesIO(image_bytes("PNG")), filename="wrong.jpg"))


def test_oversized_dimensions_are_rejected(app):
    from werkzeug.datastructures import FileStorage

    payload = image_bytes("PNG", size=(4500, 4500))
    with pytest.raises(ValueError):
        save_image(FileStorage(stream=io.BytesIO(payload), filename="large.png"))


def test_path_filename_is_never_used_for_storage_name(app):
    from werkzeug.datastructures import FileStorage

    stored = save_image(FileStorage(stream=io.BytesIO(image_bytes("PNG")), filename="../../same.png"))
    assert "/" not in stored and "\\" not in stored
    assert (Path(app.config["UPLOAD_FOLDER"]) / stored).is_file()


def test_unauthorized_user_cannot_upload_and_missing_file_is_rejected(client):
    login(client, "student1@student.mmu.edu.my")
    assert client.post("/createfacultyhub", data={"faculty_name": "Blocked"}).status_code == 403
    login(client, "admin@mmu.edu.my")
    assert client.post("/createfacultyhub", data={"faculty_name": "No Image"}).status_code == 400
    assert db.session.query(Faculty).filter_by(faculty_name="No Image").count() == 0


def test_upload_request_size_limit_is_enforced(client, app):
    login(client, "admin@mmu.edu.my")
    response = client.post(
        "/createfacultyhub",
        data={"faculty_name": "Oversized", "faculty_image": (io.BytesIO(b"x" * (app.config["MAX_CONTENT_LENGTH"] + 1)), "x.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
    assert db.session.query(Faculty).filter_by(faculty_name="Oversized").count() == 0


def test_upload_route_only_serves_generated_names(client, app):
    from werkzeug.datastructures import FileStorage

    filename = save_image(FileStorage(stream=io.BytesIO(image_bytes("PNG")), filename="logo.png"))
    assert client.get(f"/uploads/{filename}").status_code == 200
    assert client.get("/uploads/../../content.json").status_code == 404
