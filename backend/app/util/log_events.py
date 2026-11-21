"""Structured log fields compatible with stdlib logging (not structlog)."""

from __future__ import annotations

import json
import logging
from typing import Any


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Emit an event name with optional fields — safe for logging.Logger."""
    if not fields:
        logger.log(level, event)
        return
    try:
        payload = json.dumps(fields, default=str, sort_keys=True)
    except TypeError:
        payload = str(fields)
    logger.log(level, "%s %s", event, payload)