"""Jakarta Persistence vocabulary on the Python side — mirrors the Java
TestJpaAnnotations suite: @Table wins over convention, @Column mapping,
@Transient exclusion, @Id-driven WHERE criteria, application-supplied keys,
and @Enumerated(ORDINAL) round-trips."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import pytest

from modelet import (
    Column,
    Entity,
    Enumerated,
    EnumType,
    Id,
    ModelException,
    Table,
    Transient,
    TxnMode,
)
from modelet.statement import build_delete, build_insert, build_update


class AEnum(Enum):
    A = "A"
    B = "B"


@Table("book")
@dataclass
class JpaBook(Entity):
    title: str | None = Column("bookName")
    price: Decimal | None = None
    grade: AEnum | None = Enumerated(EnumType.ORDINAL, column="gradeOrdinal")
    joined_row_count: int | None = Transient()

    # deliberately wrong, to prove @Table wins over the convention
    table_name_convention = "WRONG"


@Table("account")
@dataclass
class JpaAccount(Entity):
    account_no: str | None = Id(column="account_no")
    owner: str | None = None


@Table("enrollment")
@dataclass
class Enrollment(Entity):
    student_id: int | None = Id()
    course_id: int | None = Id()
    grade: str | None = None


def test_table_decorator_binds_table_name():
    stmt = build_insert(JpaBook(title="annotated"))
    assert stmt.sql.startswith("INSERT INTO book ")


def test_column_mapping_and_transient_in_insert():
    book = JpaBook(title="annotated", price=Decimal("150"), joined_row_count=99)
    stmt = build_insert(book)
    assert "bookName" in stmt.sql
    assert "title" not in stmt.sql
    assert "joined_row_count" not in stmt.sql


def test_ordinal_enum_stored_as_integer():
    book = JpaBook(title="annotated", grade=AEnum.B)
    stmt = build_insert(book)
    cols = stmt.sql[stmt.sql.index("(") + 1 : stmt.sql.index(")")].split(", ")
    assert stmt.params[cols.index("gradeOrdinal")] == 1  # AEnum.B is position 1


def test_id_annotation_drives_where_criteria():
    account = JpaAccount(account_no="A-001", owner="matt")
    stmt = build_delete(account)
    assert stmt.sql == "DELETE FROM account WHERE account_no=?"
    assert stmt.params == ["A-001"]


def test_key_value_never_inlined_into_sql():
    account = JpaAccount(account_no="A'; DROP TABLE account;--", owner="mallory")
    stmt = build_update(account)
    assert stmt.sql.endswith("WHERE account_no=?")
    assert "DROP TABLE" not in stmt.sql
    assert stmt.params[-1] == "A'; DROP TABLE account;--"


def test_composite_key():
    enrollment = Enrollment(student_id=7, course_id=42, grade="A+")
    stmt = build_update(enrollment)
    assert stmt.sql.endswith("WHERE student_id=? AND course_id=?")
    assert stmt.params == ["A+", 7, 42]
    # key fields stay out of SET
    assert "student_id=?," not in stmt.sql.split("WHERE")[0]


def test_key_with_none_value_is_refused():
    with pytest.raises(ModelException):
        build_delete(JpaAccount(owner="matt"))


# ------------------------------------------------------- end-to-end on sqlite


def test_annotated_roundtrip_on_sqlite(model):
    model.execute_sql(
        "CREATE TABLE IF NOT EXISTS account "
        "(account_no TEXT PRIMARY KEY, owner TEXT)"
    )
    account = JpaAccount(account_no="A-001", owner="matt")
    model.save(account)

    # Id() without generated=True: application key untouched, no backfill
    assert account.id is None
    assert account.txn_mode is TxnMode.UPDATE

    loaded = model.find_one("select * from account where account_no=?", ["A-001"], JpaAccount)
    assert loaded.owner == "matt"

    loaded.owner = "matt jiang"
    model.save(loaded)
    loaded.txn_mode = TxnMode.DELETE
    model.save(loaded)
    assert model.find("select * from account") == []


def test_ordinal_enum_roundtrip_on_sqlite(model):
    model.execute_sql(
        "CREATE TABLE IF NOT EXISTS jpabook "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, bookName TEXT, price NUMERIC, "
        "gradeOrdinal INTEGER)"
    )

    @Table("jpabook")
    @dataclass
    class OrdinalBook(Entity):
        title: str | None = Column("bookName")
        grade: AEnum | None = Enumerated(EnumType.ORDINAL, column="gradeOrdinal")

    book = OrdinalBook(title="rolled", grade=AEnum.B)
    model.save(book)

    raw = model.get_entity_map_by_id(book.id, "jpabook")
    assert raw["gradeOrdinal"] == 1  # stored as ordinal

    loaded = model.get_entity_by_id(book.id, OrdinalBook)
    assert loaded.grade is AEnum.B  # restored from ordinal
    assert loaded.title == "rolled"
