"""SQL statement builders — the analog of Java's ModelUtil.

All generated statements use ``?`` placeholders exclusively, including the
WHERE criteria built from key fields (the Java version concatenated key values
into the SQL text, which was an injection risk; this port binds everything).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from .entity import Entity, column_name, persistent_fields
from .exceptions import ModelException
from .persistence import enum_to_column, key_field_names


@dataclass
class Statement:
    sql: str
    params: list


def _field_value(entity: Entity, f: dataclasses.Field):
    value = getattr(entity, f.name)
    if isinstance(value, Enum):
        return enum_to_column(f, value)
    return value


def build_insert(entity: Entity) -> Statement:
    cols, marks, params = [], [], []
    for f in persistent_fields(entity):
        value = _field_value(entity, f)
        if f.name == "id" and value is None:
            continue  # let the database generate it
        if value is None and not entity.allow_null_value:
            continue
        cols.append(column_name(f))
        marks.append("?")
        params.append(value)
    if not cols:
        raise ModelException(
            f"Entity {type(entity).__name__} has no persistable values to insert."
        )
    sql = (
        f"INSERT INTO {entity.get_table_name()} "
        f"({', '.join(cols)}) VALUES ({', '.join(marks)})"
    )
    return Statement(sql, params)


def build_update(entity: Entity) -> Statement:
    keys = key_field_names(type(entity))
    sets, params = [], []
    for f in persistent_fields(entity):
        if f.name in keys:
            continue  # keys identify the row; they don't belong in SET
        value = _field_value(entity, f)
        if value is None and not entity.allow_null_value:
            continue
        sets.append(f"{column_name(f)}=?")
        params.append(value)
    if not sets:
        raise ModelException(
            f"Entity {type(entity).__name__} has no persistable values to update."
        )
    where, where_params = build_key_criteria(entity)
    sql = f"UPDATE {entity.get_table_name()} SET {', '.join(sets)} WHERE {where}"
    return Statement(sql, params + where_params)


def build_delete(entity: Entity) -> Statement:
    where, params = build_key_criteria(entity)
    return Statement(f"DELETE FROM {entity.get_table_name()} WHERE {where}", params)


def build_key_criteria(entity: Entity) -> tuple[str, list]:
    field_by_name = {f.name: f for f in dataclasses.fields(entity)}
    parts, params = [], []
    for key in key_field_names(type(entity)):
        f = field_by_name.get(key)
        col = column_name(f) if f else key
        value = _field_value(entity, f) if f else getattr(entity, key, None)
        if value is None:
            raise ModelException(
                f"Key field '{key}' of {type(entity).__name__} is None; "
                "refusing to build an unbounded WHERE clause."
            )
        parts.append(f"{col}=?")
        params.append(value)
    return " AND ".join(parts), params
