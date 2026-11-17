import enum
from typing import TypeVar

from sqlalchemy import Enum

E = TypeVar("E", bound=enum.Enum)


def pg_enum(enum_cls: type[E], name: str) -> Enum:
    """PostgreSQL enums are lowercase values; persist enum.value not enum.name."""
    return Enum(enum_cls, name=name, values_callable=lambda members: [m.value for m in members])