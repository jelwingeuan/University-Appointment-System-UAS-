"""Image storage boundary. Provider implementations expose save/delete/open/url."""

import importlib
from pathlib import Path


class LocalImageStorage:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, key, content, content_type):
        del content_type
        (self.root / key).write_bytes(content)

    def delete(self, key):
        (self.root / key).unlink(missing_ok=True)

    def open(self, key):
        path = self.root / key
        return path if path.is_file() else None

    def url(self, key):
        del key


def create_image_storage(app):
    factory_path = app.config.get("IMAGE_STORAGE_FACTORY")
    if not factory_path:
        return LocalImageStorage(app.config["UPLOAD_FOLDER"])
    module_name, separator, factory_name = factory_path.partition(":")
    if not separator or not module_name or not factory_name:
        raise RuntimeError("IMAGE_STORAGE_FACTORY must use module:factory syntax")
    factory = getattr(importlib.import_module(module_name), factory_name)
    storage = factory(app)
    if not all(callable(getattr(storage, name, None)) for name in ("save", "delete", "open", "url")):
        raise RuntimeError("Image storage must implement save, delete, open and url")
    return storage
