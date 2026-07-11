"""Row mapping — the analog of Java's DataRoller hierarchy.

``rows_to_dicts`` is the MapDataRoller; ``dict_to_entity`` is the
EntityDataRoller. Column-to-field matching is case-insensitive and ignores
underscores, so a ``bookName`` column fills a ``book_name`` field without any
configuration, and explicit ``field(metadata={"column": ...})`` mappings are
honored first. Values are coerced back to the field's declared type
(Enum, Decimal, datetime, bool) using the dataclass type hints.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .entity import Entity, TxnMode, column_name
from .persistence import enum_from_column


def rows_to_dicts(cursor) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def dict_to_entity(cls: type[Entity], row: dict) -> Entity:
    entity = cls()
    hints = typing.get_type_hints(cls)
    fields_by_norm: dict[str, dataclasses.Field] = {}
    for f in dataclasses.fields(cls):
        fields_by_norm[_normalize(column_name(f))] = f
        fields_by_norm.setdefault(_normalize(f.name), f)

    for col, value in row.items():
        f = fields_by_norm.get(_normalize(col))
        if f is None or value is None:
            continue
        setattr(entity, f.name, _coerce(hints.get(f.name), value, f))

    entity.txn_mode = TxnMode.UPDATE
    return entity


def _normalize(name: str) -> str:
    return name.replace("_", "").lower()


def _coerce(hint, value, f: dataclasses.Field | None = None):
    target = _unwrap_optional(hint)
    if target is None or isinstance(target, str):
        return value
    if isinstance(target, type) and issubclass(target, Enum):
        return value if isinstance(value, target) else enum_from_column(f, target, value)
    if target is Decimal and not isinstance(value, Decimal):
        return Decimal(str(value))
    if target is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    if target is date and isinstance(value, str):
        return date.fromisoformat(value)
    if target is bool and not isinstance(value, bool):
        return value in (1, "1", "true", "True")
    return value


def _unwrap_optional(hint):
    """str | None -> str; Optional[str] -> str; anything else unchanged."""
    if hint is None:
        return None
    origin = typing.get_origin(hint)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return hint
