"""Logging setup with secret redaction: known secret values are replaced by *** in every
message, argument and traceback that reaches the handler (spec 02, F11)."""

import logging
import sys
from collections.abc import Iterable
from typing import TextIO

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
REDACTED = "***"


class RedactSecrets(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if s)

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self._redact(record.exc_text)
        return True


def configure_logging(
    secrets: Iterable[str] = (), stream: TextIO = sys.stderr, level: int = logging.INFO
) -> None:
    """Send logs to `stream`, redacting `secrets`. Replaces a previous configure_logging setup."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_jobhunt", False)]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream)
    handler._jobhunt = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter(FORMAT))
    handler.addFilter(RedactSecrets(secrets))
    root.addHandler(handler)
    root.setLevel(level)
