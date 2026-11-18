"""Small helpers for API serialization and DB-safe actor labels."""

import uuid

# Safe on DBs that have not yet applied migration 004 (varchar 32).
CREATED_BY_DB_MAX = 32


def enum_value(v: object) -> str:
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(getattr(v, "value"))
    return str(v)


def clamp_str(value: str, max_len: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]


def normalize_created_by(actor: str, *, max_len: int = CREATED_BY_DB_MAX) -> str:
    """Persist user-facing actors without violating varchar limits."""
    label = (actor or "system").strip() or "system"
    if len(label) <= max_len:
        return label
    if "@" in label:
        local, domain = label.split("@", 1)
        compact = f"{local}@{domain[: max(1, max_len - len(local) - 1)]}"
        if len(compact) <= max_len:
            return compact
        if len(local) <= max_len:
            return local
    return label[:max_len]


def provisional_reproducibility_id() -> str:
    """Unique placeholder until execute_backtest_run computes the real id."""
    return f"p-{uuid.uuid4().hex[:30]}"


def integrity_hint(exc: Exception) -> str | None:
    text = str(getattr(exc, "orig", None) or exc).lower()
    if "created_by" in text or "value too long" in text or "character varying" in text:
        return "A label was too long for the database column (usually created_by)."
    if "reproducibility" in text and "unique" in text:
        return "Duplicate provisional backtest id."
    if "duplicate key" in text or "unique constraint" in text:
        return "Duplicate key conflict."
    if "foreign key" in text or "job_id" in text:
        return "Search job row was not saved before its activity feed row."
    if "diskfull" in text or "no space left" in text:
        return "Postgres ran out of disk. Press Restart search after extra bar copies are cleared."
    return None