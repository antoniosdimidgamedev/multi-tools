"""Application logging.

Privacy rule: log *events and sizes*, never user content. No document text,
no chat prompts/responses, no torrent display names are written to logs.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from deskhub.settings import appdata_dir

_configured = False


def get_logger(name: str = "deskhub") -> logging.Logger:
    global _configured
    if not _configured:
        root = logging.getLogger("deskhub")
        root.setLevel(logging.INFO)
        try:
            handler = logging.handlers.RotatingFileHandler(
                Path(appdata_dir()) / "deskhub.log",
                maxBytes=512_000, backupCount=3, encoding="utf-8",
            )
        except OSError:
            handler = logging.NullHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        _configured = True
    # Create (and configure) lazily on every call so that modules which cached
    # a logger at import time still propagate into the current "deskhub" tree
    # after a settings/logging reload (e.g. in tests).
    full = name if name == "deskhub" or name.startswith("deskhub.") \
        else f"deskhub.{name}"
    logger = logging.getLogger(full)
    logger.propagate = True
    return logger
