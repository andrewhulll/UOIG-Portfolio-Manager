"""JSON logging to stdout.

Render captures stdout and can forward it to a log drain — nothing here talks
to Datadog directly. Point Render's Log Stream at Datadog's HTTP log intake
and these JSON lines get faceted (service, env, level, logger, and any
`extra={...}` fields like `ticker`) without a custom parsing rule.
"""
from __future__ import annotations

import json
import logging
import os
import sys

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "message": record.getMessage(),
            "status": record.levelname.lower(),
            "logger": record.name,
            "ddsource": "python",
            "service": os.environ.get("DD_SERVICE", "uoig-terminal"),
            "env": os.environ.get("DD_ENV", "production"),
        }
        version = os.environ.get("DD_VERSION")
        if version:
            payload["version"] = version
        if record.exc_info and record.exc_info[0]:
            payload["error.kind"] = record.exc_info[0].__name__
            payload["error.message"] = str(record.exc_info[1])
            payload["error.stack"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in payload:
                continue
            try:
                json.dumps(value)
            except TypeError:
                value = str(value)
            payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None) -> None:
    """Call once at process startup, before other modules start logging."""
    root = logging.getLogger()
    if getattr(root, "_uoig_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel((level or os.environ.get("LOG_LEVEL", "INFO")).upper())
    root._uoig_configured = True
