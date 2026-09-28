"""One JSON object per log line, for log collectors (DJANGO_LOG_FORMAT=json)."""

import json
import logging
from datetime import UTC, datetime

# Attributes every LogRecord has; anything else was passed with extra={...}.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request = getattr(record, "request", None)
        if request is not None and hasattr(request, "path"):
            entry["method"] = request.method
            entry["path"] = request.path
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                entry["user_id"] = user.pk
        for key, value in vars(record).items():
            if key not in _STANDARD and key not in entry and key != "request":
                entry[key] = value if isinstance(value, str | int | float | bool) else str(value)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)
