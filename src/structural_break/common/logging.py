"""JSON run logs with an allowlisted context and credential redaction."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import TextIO
from uuid import uuid4

CONTEXT_FIELDS = (
    "run_id",
    "job",
    "config_hash",
    "dataset_version",
    "stage",
    "record_count",
    "duration_seconds",
    "status",
    "error_type",
)


def new_run_id() -> str:
    return uuid4().hex


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            **{key: getattr(record, key) for key in CONTEXT_FIELDS if hasattr(record, key)},
        }
        # Exception messages may contain request bodies; emit only their class.
        if record.exc_info and record.exc_info[0]:
            payload["error_type"] = record.exc_info[0].__name__
        output = json.dumps(payload, default=str)
        for secret in self.secrets:
            output = output.replace(json.dumps(secret)[1:-1], "[REDACTED]")
        return re.sub(
            r"(?i)(bearer\s+|(?:api[_-]?key|token|password)=)[^\s\"&]+",
            r"\1[REDACTED]",
            output,
        )


def configure_logging(
    stream: TextIO | None = None, secrets: tuple[str, ...] = ()
) -> logging.Logger:
    logger = logging.getLogger("structural_break")
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter(secrets))
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger
