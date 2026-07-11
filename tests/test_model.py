"""Port of the Java TestDefaultModel scenarios (persist / query / bulk /
paging), plus coverage for the Python-specific pieces: audit injection,
camelCase column matching, transactions, and type round-trips."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

import pytest

from modelet import (
    AppEntity,
    Entity,
    Login,
    ModelException,
    PagingElement,
    TxnMode,
    reset_login,
    set_login,
)


class AEnum(Enum):
    A = "A"
    B = "B"


@dataclass
class Book(Entity):
    book_name: str | None = None
    price: Decimal | None = None
    a_enum: AEnum | None = None
    create_date: datetime | None = None

    table_name = "book"


@dataclass
class Article(AppEntity):
    title: str | None = None

    table_name = "article"


def make_book(name="Java note book", price="150", a_enum=AEnum.A):
    return Book(
        book_name=name,
        price=Decimal(price),
        a_enum=a_enum,
        create_date=datetime(2026, 7, 10, 12, 0, 0),
    )


# --------------------------------------------------------------- testPersist


def test_persist_roundtrip(model):
    book = make_book()
    assert book.txn_mode is TxnMode.INSERT

    model.save(book)

    # DB-generated id written back; entity flips to UPDATE mode
    assert book.id is not None
    assert book.txn_mode is TxnMode.UPDATE

    loaded = model.get_entity_by_id(book.id, Book)
    assert loaded.book_name == "Java note book"
    assert loaded.price == Decimal("150")
    assert loaded.a_enum is AEnum.A
    assert loaded.create_date == datetime(2026, 7, 10, 12, 0, 0)
    assert loaded.txn_mode is TxnMode.UPDATE

    # update path
    loaded.book_name = "Python note book"
    model.save(loaded)
    again = model.get_entity_by_id(book.id, Book)
    assert again.book_name == "Python note book"

    # delete path
    again.txn_mode = TxnMode.DELETE
    model.save(again)
    assert model.get_entity_by_id(book.id, Book) is None


def test_save_requires_txn_mode(model):
    book = make_book()
    book.txn_mode = None
    with pytest.raises(ModelException):
        model.save(book)


def test_string_with_quotes_roundtrip(model):
    book = make_book(name="O'Reilly's \"guide\"; DROP TABLE book;--")
    model.save(book)
    loaded = model.get_entity_by_id(book.id, Book)
    assert loaded.book_name == "O'Reilly's \"guide\"; DROP TABLE book;--"

    # update and delete also go through placeholder-bound WHERE criteria
    loaded.book_name = "safe"
    model.save(loaded)
    loaded.txn_mode = TxnMode.DELETE
    model.save(loaded)
    assert model.find("select * from book") == []


# ---------------------------------------------------------------- testQuery


def test_query_returns_dicts(model):
    model.save([make_book(name=f"book {i}") for i in range(3)])
    rows = model.find("select * from book where id > ?", [1])
    assert len(rows) == 2
    assert isinstance(rows[0], dict)
    assert rows[0]["book_name"] == "book 1"


def test_find_one_returns_none_when_missing(model):
    assert model.find_one("select * from book where id = ?", [999], Book) is None


def test_get_entity_map_by_id(model):
    book = make_book()
    model.save(book)
    row = model.get_entity_map_by_id(book.id, "book")
    assert row["book_name"] == "Java note book"


# ----------------------------------------------------------- testBulkInsert


def test_bulk_insert(model):
    books = [make_book(name=f"Java note book edition {i}") for i in range(10)]
    model.save(books)
    assert all(b.id is not None for b in books)
    rows = model.find("select * from book", None, Book)
    assert len(rows) == 10


def test_bulk_insert_rolls_back_as_one_transaction(model):
    books = [make_book(), make_book()]
    books[1].txn_mode = None  # second entity fails validation
    with pytest.raises(ModelException):
        model.save(books)
    assert model.find("select * from book") == []


# --------------------------------------------------------------- testPaging


def test_paging(model):
    model.save([make_book(name=f"book {i}") for i in range(5)])

    paging = PagingElement(target_page=2, rows_per_page=2)
    page = model.find_with_paging("select * from book order by id", None, paging)

    assert page.total_records == 5
    assert page.total_pages == 3
    assert [r["book_name"] for r in page.rows] == ["book 2", "book 3"]
    assert page.generate_page_numbers() == ["1", "2", "3"]


def test_paging_overflow_falls_back_to_first_page(model):
    model.save([make_book(name=f"book {i}") for i in range(3)])

    paging = PagingElement(target_page=99, rows_per_page=2)
    page = model.find_with_paging(
        "select * from book order by id", None, paging, Book
    )

    assert paging.target_page == 1
    assert [b.book_name for b in page.rows] == ["book 0", "book 1"]


def test_paging_with_params(model):
    model.save([make_book(name=f"book {i}") for i in range(6)])
    paging = PagingElement(target_page=1, rows_per_page=10)
    page = model.find_with_paging(
        "select * from book where id > ?", [3], paging
    )
    assert page.total_records == 3


# ------------------------------------------------------------ audit fields


def test_audit_injection_on_insert_and_update(model):
    token = set_login(Login("matt"))
    try:
        article = Article(title="hello")
        model.save(article)
        row = model.get_entity_map_by_id(article.id, "article")
        assert row["creator"] == "matt"
        assert row["create_date"] is not None
        assert row["modifier"] is None

        article.title = "hello again"
        model.save(article)
        row = model.get_entity_map_by_id(article.id, "article")
        assert row["modifier"] == "matt"
        assert row["modify_date"] is not None
    finally:
        reset_login(token)


# ------------------------------------------------- mapping & entity config


def test_camelcase_columns_map_to_snake_case_fields(model):
    model.execute_sql(
        "CREATE TABLE legacy (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "bookName TEXT, createDate TIMESTAMP)"
    )

    @dataclass
    class Legacy(Entity):
        book_name: str | None = field(
            default=None, metadata={"column": "bookName"}
        )
        create_date: datetime | None = field(
            default=None, metadata={"column": "createDate"}
        )

        table_name = "legacy"

    legacy = Legacy(book_name="old data", create_date=datetime(2006, 1, 1))
    model.save(legacy)

    # write path used the mapped column names; read path matches
    # case-insensitively even without metadata
    loaded = model.find_one("select * from legacy", None, Legacy)
    assert loaded.book_name == "old data"
    assert loaded.create_date == datetime(2006, 1, 1)


def test_system_increment_keeps_app_generated_id(model):
    @dataclass
    class SysBook(Book):
        system_increment = True

    book = SysBook(id=777, book_name="fixed id")
    model.save(book)
    assert book.id == 777
    assert model.get_entity_map_by_id(777, "book")["book_name"] == "fixed id"


def test_transient_field_excluded_from_sql(model):
    @dataclass
    class JoinedBook(Book):
        author_count: int | None = field(default=None, metadata={"transient": True})

    book = JoinedBook(book_name="joined", price=Decimal("10"), a_enum=AEnum.B)
    model.save(book)  # would fail if author_count leaked into INSERT
    assert book.id is not None


# ------------------------------------------------------------- transactions


def test_txn_context_rolls_back(model):
    with pytest.raises(RuntimeError):
        with model.txn():
            model.save(make_book())
            raise RuntimeError("boom")
    assert model.find("select * from book") == []


def test_execute_sql(model):
    model.save([make_book(name=f"book {i}") for i in range(3)])
    count = model.execute_sql("update book set price = ? where id > ?", [Decimal("99"), 1])
    assert count == 2
