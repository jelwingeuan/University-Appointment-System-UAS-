import json
import logging
from datetime import UTC, datetime

from flask import current_app, g, has_app_context, has_request_context, request


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.app_env = current_app.config.get("APP_ENV", "unknown") if has_app_context() else "unknown"
        record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        record.method = request.method if has_request_context() else "-"
        rule = request.url_rule if has_request_context() else None
        record.route = rule.rule if rule else "-"
        user = getattr(g, "_login_user", None) if has_request_context() else None
        record.user_id = user.id if user and getattr(user, "is_authenticated", False) else None
        return True


class ApplicationFormatter(logging.Formatter):
    def format(self, record):
        timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")
        fields = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "environment": getattr(record, "app_env", "unknown"),
            "request_id": getattr(record, "request_id", "-"),
            "method": getattr(record, "method", "-"),
            "route": getattr(record, "route", "-"),
            "user_id": getattr(record, "user_id", None),
        }
        for source, target in (("event", "event"), ("status_code", "status"), ("duration_ms", "duration_ms"), ("error_type", "error_type")):
            value = getattr(record, source, None)
            if value is not None:
                fields[target] = value
        if fields["environment"] == "production":
            return json.dumps(fields, separators=(",", ":"), ensure_ascii=True)
        context = (
            f"request_id={fields['request_id']} method={fields['method']} route={fields['route']} "
            f"status={fields.get('status', '-')} duration_ms={fields.get('duration_ms', '-')} "
            f"user_id={fields['user_id'] if fields['user_id'] is not None else '-'} "
            f"environment={fields['environment']}"
        )
        return f"{timestamp} {record.levelname} {record.getMessage()} [{context}]"


def configure_logging(app):
    logger = app.logger
    if not any(getattr(item, "_uas_context_filter", False) for item in logger.filters):
        context_filter = RequestContextFilter()
        context_filter._uas_context_filter = True
        logger.addFilter(context_filter)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    for handler in logger.handlers:
        handler.setFormatter(ApplicationFormatter())
    logger.setLevel(logging.INFO)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
