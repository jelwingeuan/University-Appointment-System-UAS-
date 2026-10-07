"""Local-only appointment mail sink for development."""

import json
import os
from pathlib import Path


def create_sender(app):
    mailbox = Path(app.config.get("DEVELOPMENT_MAILBOX_PATH") or Path(app.instance_path) / "dev-mailbox.jsonl")

    def send(message):
        mailbox.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "to": message.to_address,
                "subject": message.subject,
                "text": message.text_body,
                "html": message.html_body,
                "idempotency_key": message.idempotency_key,
            },
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"
        descriptor = os.open(mailbox, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)

    return send
