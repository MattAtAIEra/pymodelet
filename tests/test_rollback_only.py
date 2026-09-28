"""Rollback-only semantics, as in Spring's UnexpectedRollbackException.

A failure that leaves a nested ``txn()`` block (or a Model method joining the
transaction) marks the whole transaction rollback-only. Swallowing that
exception further out must not let the outermost ``txn()`` commit partial
work: it rolls back and raises ``ModelException`` instead.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from modelet import Entity, Model, ModelException, SqliteDialect
from modelet.model import _bound


@dataclass
class Book(Entity):
    book_name: str | None = None

    table_name = "book"


def make_book(name):
    return Book(book_name=name)


def book_names(model):
    return [r["book_name"] for r in model.find("select book_name from book order by id")]


def test_swallowed_inner_failure_rolls_back_outer(model):
    with pytest.raises(ModelException, match="rollback-only") as info:
        with model.txn():
            model.save(make_book(name="outer"))
            try:
                with model.txn():
                    model.save(make_book(name="inner"))
                    raise ValueError("inner failed")
            except ValueError:
                pass  # swallowed
            model.save(make_book(name="after"))
    assert isinstance(info.value.cause, ValueError)
    assert isinstance(info.value.__cause__, ValueError)
    assert book_names(model) == []


def test_swallowed_failing_model_call_rolls_back_outer(model):
    # a Model method inside txn() joins the transaction, so its failure
    # marks it just like a nested txn() block would
    with pytest.raises(ModelException, match="rollback-only") as info:
        with model.txn():
            model.save(make_book(name="kept?"))
            try:
                model.execute_sql("insert into no_such_table values (1)")
            except ModelException:
                pass
    assert isinstance(info.value.cause, ModelException)
    assert book_names(model) == []


def test_swallowed_failure_in_bulk_save_rolls_back_outer(model):
    books = [make_book(name="one"), make_book(name="two")]
    books[1].txn_mode = None
    with pytest.raises(ModelException, match="rollback-only"):
        with model.txn():
            try:
                model.save(books)
            except ModelException:
                pass
    assert book_names(model) == []


def test_deeply_nested_failure_swallowed_in_middle(model):
    with pytest.raises(ModelException, match="rollback-only"):
        with model.txn():
            model.save(make_book(name="outer"))
            with model.txn():
                try:
                    with model.txn():
                        raise KeyError("deep")
                except KeyError:
                    pass
                model.save(make_book(name="middle"))
    assert book_names(model) == []


def test_first_failure_is_the_reported_cause(model):
    with pytest.raises(ModelException) as info:
        with model.txn():
            for exc in (ValueError("first"), TypeError("second")):
                try:
                    with model.txn():
                        raise exc
                except (ValueError, TypeError):
                    pass
    assert str(info.value.cause) == "first"


def test_propagating_inner_failure_keeps_original_exception(model):
    # not swallowed: the caller sees the real error, not ModelException
    with pytest.raises(ValueError, match="inner"):
        with model.txn():
            model.save(make_book(name="outer"))
            with model.txn():
                raise ValueError("inner")
    assert book_names(model) == []


def test_exception_caught_inside_one_block_does_not_mark(model):
    # never crossed a txn() boundary, so the transaction stays committable
    with model.txn():
        model.save(make_book(name="kept"))
        try:
            raise ValueError("handled locally")
        except ValueError:
            pass
        with model.txn():
            try:
                raise ValueError("handled inside the nested block")
            except ValueError:
                pass
            model.save(make_book(name="also kept"))
    assert book_names(model) == ["kept", "also kept"]


def test_rollback_only_flag_does_not_leak_into_next_transaction():
    borrows = []

    cn = sqlite3.connect(":memory:")
    cn.execute("create table t (v text)")

    @contextmanager
    def source():
        borrows.append(1)
        yield cn

    model = Model(source, SqliteDialect())
    with pytest.raises(ModelException):
        with model.txn():
            try:
                with model.txn():
                    raise ValueError
            except ValueError:
                pass
    assert list(_bound.get()) == []
    assert not cn.in_transaction

    with model.txn():
        model.execute_sql("insert into t values ('ok')")
    assert model.find("select v from t") == [{"v": "ok"}]
    assert len(borrows) == 3
