"""Compact database errors so we never write SQL bind params back into Postgres."""

from __future__ import annotations

JOB_MESSAGE_MAX = 240

DISK_FULL_MESSAGE = (
    "Postgres ran out of disk while loading market bars. Extra 1m/5m copies were cleared. "
    "Try again. If it happens again, increase the Railway Postgres volume."
)

RETRY_AFTER_DB_ERROR = "The last database write failed. Try again in a few seconds."

POSTGRES_RECOVERY_MESSAGE = (
    "Postgres is recovering after the disk filled with 1m bars. "
    "On Railway: open the Postgres service → Restart. Wait until it is Running, then sign in. "
    "Increase the Postgres volume so this cannot happen again."
)

RECOVERY_SNIPPETS = (
    "recovery mode",
    "the database system is starting up",
    "connection reset by peer",
    "server closed the connection",
    "connection was closed",
    "errno 104",
)


def exception_text(exc: BaseException | str) -> str:
    if isinstance(exc, str):
        return exc.lower()
    parts: list[str] = []
    current: BaseException | None = exc
    seen = 0
    while current is not None and seen < 8:
        parts.append(str(current))
        for attr in ("orig", "stderr", "stdout", "output"):
            val = getattr(current, attr, None)
            if val:
                parts.append(str(val))
        current = current.__cause__ or current.__context__
        seen += 1
    return " ".join(parts).lower()


def is_disk_full(exc: BaseException) -> bool:
    return is_disk_full_text(exception_text(exc))


def is_postgres_recovery(exc: BaseException | str) -> bool:
    text = exception_text(exc)
    return any(snippet in text for snippet in RECOVERY_SNIPPETS)


def compact_error(exc: BaseException | str, *, limit: int = JOB_MESSAGE_MAX) -> str:
    if not isinstance(exc, str) and is_disk_full(exc):
        return DISK_FULL_MESSAGE
    if is_postgres_recovery(exc):
        return POSTGRES_RECOVERY_MESSAGE
    text = str(getattr(exc, "orig", None) or exc)
    for marker in ("[SQL:", "[parameters:", "(Background on this error"):
        if marker in text:
            text = text.split(marker, 1)[0]
    text = " ".join(text.split()).strip()
    if is_disk_full_text(text):
        return DISK_FULL_MESSAGE
    if is_postgres_recovery(text):
        return POSTGRES_RECOVERY_MESSAGE
    return text[:limit]


def is_disk_full_text(text: str) -> bool:
    lower = (text or "").lower()
    return "diskfull" in lower or "no space left" in lower or "could not extend file" in lower


def set_job_message(job: object, message: str) -> None:
    text = compact_error(message) if is_disk_full_text(str(message)) else " ".join(str(message or "").split())
    setattr(job, "message", text[:JOB_MESSAGE_MAX])
