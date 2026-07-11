"""Jakarta Persistence annotation vocabulary for Python entities.

Only the VOCABULARY is borrowed — ``@Table``, ``@Id``, ``@Column``,
``@Transient``, ``@Enumerated``, ``@GeneratedValue`` — so a Modelet entity
reads the same in Java and Python. The engine stays SQL-first: no JPQL, no
EntityManager, no proxies.

Java                                        | Python
--------------------------------------------|----------------------------------------------
``@Table(name = "book")``                   | ``@Table("book")`` class decorator
``@Column(name = "bookName")``              | ``title: str | None = Column("bookName")``
``@Id``                                     | ``account_no: str | None = Id()``
``@Id @GeneratedValue``                     | ``id: int | None = Id(generated=True)``
``@Transient``                              | ``row_count: int | None = Transient()``
``@Enumerated(EnumType.ORDINAL)``           | ``grade: AEnum | None = Enumerated(EnumType.ORDINAL)``

Because a dataclass field takes a single ``field()`` call, the aspects that
Java stacks as separate annotations are keyword arguments of ``Column`` here;
``Id`` / ``Transient`` / ``Enumerated`` are sugar over ``Column``.

An ``@Id`` without ``generated=True`` means the application supplies the key
itself (the annotation-era ``SystemIncrementEntity`` / ``system_increment``).
Without any ``Id()`` markers, the class-level ``key_names`` / ``system_increment``
conventions apply unchanged.
"""

from __future__ import annotations

import dataclasses
from enum import Enum as PyEnum


class EnumType(PyEnum):
    STRING = "string"    # store Enum member name (Modelet's historical default)
    ORDINAL = "ordinal"  # store the member's position, 0-based


def Table(name: str):
    """Class decorator binding the entity to a table, like ``@Table(name=...)``."""

    def apply(cls):
        cls.table_name = name
        return cls

    return apply


def Column(
    name: str | None = None,
    *,
    id: bool = False,
    generated: bool = False,
    enumerated: EnumType | None = None,
    transient: bool = False,
    default=None,
):
    metadata = {}
    if name:
        metadata["column"] = name
    if id:
        metadata["id"] = True
    if generated:
        metadata["generated"] = True
    if enumerated is not None:
        metadata["enum_type"] = enumerated
    if transient:
        metadata["transient"] = True
    return dataclasses.field(default=default, metadata=metadata)


def Id(column: str | None = None, *, generated: bool = False, default=None):
    return Column(column, id=True, generated=generated, default=default)


def GeneratedValue(column: str | None = None, default=None):
    """``@Id @GeneratedValue`` in one call: a database-generated key."""
    return Id(column, generated=True, default=default)


def Transient(default=None):
    return Column(transient=True, default=default)


def Enumerated(
    enum_type: EnumType = EnumType.STRING,
    column: str | None = None,
    default=None,
):
    return Column(column, enumerated=enum_type, default=default)


# ---------------------------------------------------------- metadata lookup


def key_field_names(cls) -> tuple[str, ...]:
    """Key fields from ``Id()`` markers, falling back to ``cls.key_names``."""
    ids = tuple(f.name for f in dataclasses.fields(cls) if f.metadata.get("id"))
    return ids if ids else tuple(cls.key_names)


def id_is_generated(cls) -> bool:
    """Whether the database generates the key on insert. With ``Id()`` markers
    declared, only ``generated=True`` makes it database-generated; without
    markers the legacy ``system_increment`` convention decides."""
    ids = [f for f in dataclasses.fields(cls) if f.metadata.get("id")]
    if ids:
        return any(f.metadata.get("generated") for f in ids)
    return not cls.system_increment


def enum_to_column(f: dataclasses.Field, value):
    """Convert an Enum member for persistence according to the field's
    ``Enumerated`` declaration; STRING (name) is the default."""
    if f.metadata.get("enum_type") is EnumType.ORDINAL:
        return list(type(value)).index(value)
    return value.name


def enum_from_column(f: dataclasses.Field | None, enum_cls: type[PyEnum], value):
    """Restore a column value into an Enum member: ordinal position for
    ORDINAL fields, member-name lookup otherwise."""
    if (
        f is not None
        and f.metadata.get("enum_type") is EnumType.ORDINAL
        and isinstance(value, int)
        and not isinstance(value, bool)
    ):
        return list(enum_cls)[value]
    return enum_cls[str(value)]
