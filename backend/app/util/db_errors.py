"""Compact database errors so we never write SQL bind params back into Postgres."""

from __future__ import annotations

JOB_MESSAGE_MAX = 240

DISK_FULL_MESSAGE = (
    "Postgres ran out of disk while loading market bars. Extra 1m/5m copies were cleared. "
    "Try again. If it happens again, increase the Railway Postgres volume."
)

RETRY_AFTER_DB_ERROR = "The last database write failed. Try again in a few seconds."


def is_disk_full(exc: BaseException) -> bool:
    text = f"{exc} {getattr(exc, 'orig', '')}".lower()
    return "diskfull" in text or "no space left" in text or "could not extend file" in text


def compact_error(exc: BaseException | str, *, limit: int = JOB_MESSAGE_MAX) -> str:
    if not isinstance(exc, str) and is_disk_full(exc):
        return DISK_FULL_MESSAGE
    text = str(getattr(exc, "orig", None) or exc)
    for marker in ("[SQL:", "[parameters:", "(Background on this error"):
        if marker in text:
            text = text.split(marker, 1)[0]
    text = " ".join(text.split()).strip()
    if is_disk_full_text(text):
        return DISK_FULL_MESSAGE
    return text[:limit]


def is_disk_full_text(text: str) -> bool:
    lower = (text or "").lower()
    return "diskfull" in lower or "no space left" in lower or "could not extend file" in lower


def set_job_message(job: object, message: str) -> None:
    text = compact_error(message) if is_disk_full_text(str(message)) else " ".join(str(message or "").split())
    setattr(job, "message", text[:JOB_MESSAGE_MAX])
