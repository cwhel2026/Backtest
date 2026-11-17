"""Small helpers for API serialization and DB-safe actor labels."""


def enum_value(v: object) -> str:
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(getattr(v, "value"))
    return str(v)


def normalize_created_by(actor: str, *, max_len: int = 128) -> str:
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