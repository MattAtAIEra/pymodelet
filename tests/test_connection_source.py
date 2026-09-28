"""Connection sources, ContextVar-bound transactions and thread / task safety.

A shared ``Model`` must behave like a Spring singleton bean: every thread or
asyncio task gets its own transaction on its own connection, nested
``txn()`` blocks reuse the bound connection, and work outside ``txn()``
borrows a connection for exactly one short transaction.

The fakes here wrap real sqlite3 connections so the SQL actually runs, while
recording which thread touched which connection and when.
"""

from __future__ import annotations

import asyncio
import contextvars
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from modelet import Entity, Model, ModelException, SqliteDialect
from modelet.model import _bound


@dataclass
class Item(Entity):
    txn_tag: str | None = None
    seq: int | None = None

    table_name = "item"


ITEM_DDL = (
    "CREATE TABLE IF NOT EXISTS item ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, txn_tag TEXT, seq INTEGER)"
)


# ------------------------------------------------------------------ fakes


class RecordingCursor:
    def __init__(self, owner: RecordingConnection, real):
        self._owner = owner
        self._real = real

    def execute(self, sql, params=()):
        self._owner.touch("execute", (sql, tuple(params)))
        return self._real.execute(sql, params)

    def fetchall(self):
        self._owner.touch("fetchall")
        return self._real.fetchall()

    def fetchone(self):
        self._owner.touch("fetchone")
        return self._real.fetchone()

    def close(self):
        self._real.close()

    @property
    def description(self):
        return self._real.description

    @property
    def rowcount(self):
        return self._real.rowcount

    @property
    def lastrowid(self):
        return self._real.lastrowid


class RecordingConnection:
    """DB-API connection proxy that logs every use with the calling thread
    and flags any use by a thread other than the current borrower."""

    def __init__(self, real: sqlite3.Connection, name: str):
        self.real = real
        self.name = name
        self.borrower: int | None = None
        self.log: list[tuple[int, str, object]] = []
        self.violations: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self._lock = threading.Lock()

    def touch(self, op, detail=None):
        me = threading.get_ident()
        with self._lock:
            if self.borrower != me:
                self.violations.append(
                    f"{self.name}: {op} by thread {me} while borrowed by {self.borrower}"
                )
            self.log.append((me, op, detail))

    def cursor(self):
        self.touch("cursor")
        return RecordingCursor(self, self.real.cursor())

    def commit(self):
        self.touch("commit")
        self.commits += 1
        if self.fail_commit:
            raise sqlite3.OperationalError("simulated commit failure")
        self.real.commit()

    def rollback(self):
        self.touch("rollback")
        self.rollbacks += 1
        self.real.rollback()


class FakePool:
    """Thread-safe LIFO pool of RecordingConnections exposing the
    ``psycopg_pool.ConnectionPool.connection`` shape: ``pool.connection()``
    is a context manager that borrows and returns."""

    def __init__(self, connections: list[RecordingConnection]):
        self.all = list(connections)
        self._idle: queue.LifoQueue[RecordingConnection] = queue.LifoQueue()
        for cn in connections:
            self._idle.put(cn)
        self._lock = threading.Lock()
        self.borrows = 0
        self.returns = 0
        self.violations: list[str] = []

    @property
    def in_use(self) -> int:
        return self.borrows - self.returns

    @contextmanager
    def connection(self):
        cn = self._idle.get(timeout=10)
        me = threading.get_ident()
        with self._lock:
            self.borrows += 1
            if cn.borrower is not None:
                self.violations.append(f"{cn.name} handed out while borrowed")
            cn.borrower = me
        cn.log.append((me, "borrow", None))
        try:
            yield cn
        finally:
            with self._lock:
                if cn.borrower != me:
                    self.violations.append(
                        f"{cn.name} returned by {me}, borrowed by {cn.borrower}"
                    )
                if cn.real.in_transaction:
                    self.violations.append(f"{cn.name} returned inside a transaction")
                cn.log.append((me, "return", None))
                cn.borrower = None
                self.returns += 1
            self._idle.put(cn)

    def cn(self, name: str) -> RecordingConnection:
        return next(c for c in self.all if c.name == name)

    def violations_all(self) -> list[str]:
        return self.violations + [v for cn in self.all for v in cn.violations]


def memory_pool(size: int) -> FakePool:
    """Each connection is its own :memory: database carrying a ``whoami``
    row, so a query tells which physical connection answered it."""
    conns = []
    for i in reversed(range(size)):  # LIFO: cn0 is handed out first
        real = sqlite3.connect(":memory:", check_same_thread=False)
        real.execute("CREATE TABLE whoami (name TEXT)")
        real.execute("INSERT INTO whoami VALUES (?)", (f"cn{i}",))
        real.execute(ITEM_DDL)
        real.commit()
        conns.append(RecordingConnection(real, f"cn{i}"))
    return FakePool(conns)  # pool.all[-1] is cn0


def file_pool(path, size: int) -> FakePool:
    """Connections to one shared file database, like a real server pool."""
    setup = sqlite3.connect(path)
    setup.execute(ITEM_DDL)
    setup.commit()
    setup.close()
    return FakePool(
        [
            RecordingConnection(
                sqlite3.connect(path, timeout=30, check_same_thread=False), f"cn{i}"
            )
            for i in range(size)
        ]
    )


def whoami(model: Model) -> str:
    return model.find_one("select name from whoami")["name"]


def bound_keys() -> list:
    return list(_bound.get())


# ------------------------------------------------ construction / Model(cn)


def test_sqlite_connection_is_callable_but_treated_as_connection():
    # the reason Model() cannot rely on callable() alone
    cn = sqlite3.connect(":memory:")
    assert callable(cn)
    model = Model(cn, SqliteDialect())
    model.execute_sql(ITEM_DDL)
    model.save(Item(txn_tag="x", seq=1))
    assert model.find("select txn_tag from item") == [{"txn_tag": "x"}]
    # Model(cn) never closes the connection it was given
    assert cn.execute("select count(*) from item").fetchone() == (1,)
    cn.close()


def test_model_rejects_non_connection_non_callable():
    with pytest.raises(TypeError):
        Model(object())


def test_model_cn_nested_txn_commits_once():
    real = sqlite3.connect(":memory:")
    real.execute(ITEM_DDL)
    real.commit()
    cn = RecordingConnection(real, "single")
    cn.borrower = threading.get_ident()  # no pool: this thread owns it
    model = Model(cn, SqliteDialect())

    with model.txn():
        model.save(Item(txn_tag="a", seq=1))
        with model.txn():
            model.save(Item(txn_tag="a", seq=2))
        assert cn.commits == 0
    assert cn.commits == 1
    assert len(model.find("select * from item")) == 2


def test_two_models_on_same_connection_join_one_transaction():
    # previously the second Model committed the first one's partial work
    cn = sqlite3.connect(":memory:")
    cn.execute(ITEM_DDL)
    m1 = Model(cn, SqliteDialect())
    m2 = Model(cn, SqliteDialect())
    with pytest.raises(RuntimeError):
        with m1.txn():
            m1.save(Item(txn_tag="m1", seq=1))
            m2.save(Item(txn_tag="m2", seq=1))
            raise RuntimeError("boom")
    assert m1.find("select * from item") == []


def test_model_cn_rejects_concurrent_transaction_from_other_thread():
    cn = sqlite3.connect(":memory:", check_same_thread=False)
    cn.execute(ITEM_DDL)
    model = Model(cn, SqliteDialect())
    inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def holder():
        with model.txn():
            model.save(Item(txn_tag="holder", seq=1))
            inside.set()
            release.wait(10)

    def intruder():
        try:
            model.save(Item(txn_tag="intruder", seq=1))
        except BaseException as e:
            errors.append(e)

    t1 = threading.Thread(target=holder)
    t1.start()
    assert inside.wait(10)
    t2 = threading.Thread(target=intruder)
    t2.start()
    t2.join(10)
    release.set()
    t1.join(10)

    assert len(errors) == 1
    assert isinstance(errors[0], ModelException)
    assert "single-thread only" in str(errors[0])
    assert [r["txn_tag"] for r in model.find("select txn_tag from item")] == ["holder"]
    # once the holder is done, the single connection is usable again
    model.save(Item(txn_tag="after", seq=1))


def test_model_cn_rejects_second_transaction_from_other_task():
    cn = sqlite3.connect(":memory:")
    cn.execute(ITEM_DDL)
    model = Model(cn, SqliteDialect())
    other = Model(cn, SqliteDialect())  # a second Model over the same cn

    async def holder(inside: asyncio.Event, release: asyncio.Event):
        with model.txn():
            model.save(Item(txn_tag="holder", seq=1))
            inside.set()
            await release.wait()

    async def main():
        inside, release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(holder(inside, release))
        await inside.wait()
        for m in (model, other):
            with pytest.raises(ModelException, match="single-thread only"):
                m.find("select * from item")
        release.set()
        await task

    asyncio.run(main())
    assert len(model.find("select * from item")) == 1


def test_unhashable_source_is_supported():
    pool = memory_pool(1)

    class Source:
        __hash__ = None  # type: ignore[assignment]

        def __call__(self):
            return pool.connection()

    model = Model(Source(), SqliteDialect())
    with model.txn():
        assert whoami(model) == "cn0"
        model.save(Item(txn_tag="u", seq=1))
    assert pool.in_use == 0


# -------------------------------------------------------- borrow / return


def test_each_call_outside_txn_borrows_and_returns():
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())

    model.save(Item(txn_tag="a", seq=1))
    assert (pool.borrows, pool.returns) == (1, 1)
    model.save([Item(txn_tag="a", seq=2), Item(txn_tag="a", seq=3)])
    assert (pool.borrows, pool.returns) == (2, 2)
    model.execute_sql("update item set seq = seq + 10")
    assert (pool.borrows, pool.returns) == (3, 3)

    rows = model.find("select * from item order by id")
    assert (pool.borrows, pool.returns) == (4, 4)
    assert len(rows) == 3  # fully fetched before the connection went back

    page = model.find_with_paging("select * from item order by id")
    # COUNT(*) + page query share one borrow
    assert (pool.borrows, pool.returns) == (5, 5)
    assert page.total_records == 3

    # every short transaction ended explicitly before the connection returned
    cn0 = pool.cn("cn0")
    assert cn0.commits == 5
    assert pool.violations_all() == []
    assert bound_keys() == []


def test_nested_txn_reuses_one_connection():
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())

    with model.txn() as m:
        assert m is model
        first = whoami(model)
        model.save(Item(txn_tag="n", seq=1))
        with model.txn():
            assert whoami(model) == first
            model.save(Item(txn_tag="n", seq=2))
            with model.txn():
                model.execute_sql("update item set seq = seq * 10")
        assert (pool.borrows, pool.returns) == (1, 0)
        assert pool.cn("cn0").commits == 0  # inner blocks never commit
        assert whoami(model) == first
    assert (pool.borrows, pool.returns) == (1, 1)
    assert pool.cn("cn0").commits == 1
    assert [r["seq"] for r in model.find("select seq from item order by id")] == [10, 20]


def test_ops_in_txn_see_uncommitted_writes_of_same_txn():
    pool = memory_pool(1)
    model = Model(pool.connection, SqliteDialect())
    with model.txn():
        model.save(Item(txn_tag="v", seq=1))
        assert model.find_one("select count(*) as n from item")["n"] == 1
        assert pool.cn("cn0").real.in_transaction


def test_error_outside_txn_rolls_back_and_returns_connection():
    pool = memory_pool(1)
    model = Model(pool.connection, SqliteDialect())
    with pytest.raises(ModelException):
        model.execute_sql("insert into no_such_table values (1)")
    assert (pool.borrows, pool.returns) == (1, 1)
    assert pool.cn("cn0").rollbacks == 1
    assert pool.violations_all() == []


def test_commit_failure_rolls_back_and_returns_connection():
    pool = memory_pool(1)
    model = Model(pool.connection, SqliteDialect())
    pool.cn("cn0").fail_commit = True
    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        model.save(Item(txn_tag="c", seq=1))
    assert pool.cn("cn0").rollbacks == 1
    assert (pool.borrows, pool.returns) == (1, 1)
    assert pool.violations_all() == []
    assert bound_keys() == []


# ------------------------------------------------------ ContextVar hygiene


def test_contextvar_cleared_after_txn():
    pool = memory_pool(1)
    model = Model(pool.connection, SqliteDialect())
    assert bound_keys() == []
    with model.txn():
        assert bound_keys() == [model._key]
        with model.txn():
            assert bound_keys() == [model._key]
        assert bound_keys() == [model._key]
    assert bound_keys() == []
    # a later call borrows afresh rather than reusing a stale binding
    model.find("select * from item")
    assert (pool.borrows, pool.returns) == (2, 2)


def test_contextvar_cleared_after_exception():
    pool = memory_pool(1)
    model = Model(pool.connection, SqliteDialect())
    with pytest.raises(RuntimeError):
        with model.txn():
            model.save(Item(txn_tag="e", seq=1))
            with model.txn():
                raise RuntimeError("boom")
    assert bound_keys() == []
    assert (pool.borrows, pool.returns) == (1, 1)
    assert pool.cn("cn0").rollbacks == 1
    assert model.find("select * from item") == []


def test_contextvar_cleared_when_source_enter_fails():
    @contextmanager
    def broken():
        raise ConnectionError("pool exhausted")
        yield  # pragma: no cover

    model = Model(broken, SqliteDialect())
    with pytest.raises(ConnectionError):
        model.find("select 1")
    assert bound_keys() == []


def test_models_on_different_sources_get_separate_transactions():
    pool_a, pool_b = memory_pool(1), memory_pool(1)
    a = Model(pool_a.connection, SqliteDialect())
    b = Model(pool_b.connection, SqliteDialect())
    with pytest.raises(RuntimeError):
        with a.txn():
            a.save(Item(txn_tag="a", seq=1))
            b.save(Item(txn_tag="b", seq=1))  # its own short txn, commits
            raise RuntimeError("boom")
    assert a.find("select * from item") == []
    assert len(b.find("select * from item")) == 1


def test_models_sharing_a_source_join_one_transaction():
    pool = memory_pool(2)
    a = Model(pool.connection, SqliteDialect())
    b = Model(pool.connection, SqliteDialect())  # a new but equal bound method
    with a.txn():
        a.save(Item(txn_tag="a", seq=1))
        b.save(Item(txn_tag="b", seq=1))
        assert pool.borrows == 1
    assert pool.cn("cn0").commits == 1


# --------------------------------------------------------------- threads


def test_shared_model_across_threads(tmp_path):
    """Regression test for the shared-``self._cn`` / ``self._txn_depth`` bug:
    many threads run interleaved transactions through ONE Model. Each
    transaction must stay on one connection, commit/rollback only its own
    work, and no connection may be touched by two threads at once."""
    n_threads, txns_per_thread, rows_per_txn = 8, 15, 3
    pool = file_pool(tmp_path / "shared.db", size=4)
    model = Model(pool.connection, SqliteDialect())
    start = threading.Barrier(n_threads)
    errors: list[BaseException] = []

    def worker(w: int):
        try:
            start.wait(10)
            for t in range(txns_per_thread):
                tag = f"w{w}-t{t}"
                fail = (w + t) % 3 == 0
                try:
                    with model.txn():
                        for seq in range(rows_per_txn):
                            model.save(Item(txn_tag=tag, seq=seq))
                            time.sleep(0.0005)  # invite interleaving
                        if fail:
                            raise RuntimeError(tag)
                except RuntimeError as e:
                    assert str(e) == tag
                # a single operation outside txn() on the same shared Model
                model.save(Item(txn_tag=f"{tag}-solo", seq=0))
        except BaseException as e:  # surface failures from worker threads
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    assert errors == []
    assert pool.violations_all() == []
    assert pool.in_use == 0

    # each transaction's statements ran on exactly one connection
    tag_to_conns: dict[str, set[str]] = {}
    tag_to_threads: dict[str, set[int]] = {}
    for cn in pool.all:
        for thread, op, detail in cn.log:
            if op == "execute" and detail[0].startswith("INSERT"):
                tag = detail[1][0]
                tag_to_conns.setdefault(tag, set()).add(cn.name)
                tag_to_threads.setdefault(tag, set()).add(thread)
    assert all(len(c) == 1 for c in tag_to_conns.values()), tag_to_conns
    assert all(len(t) == 1 for t in tag_to_threads.values())

    # every borrow..return span on a connection belongs to one thread and
    # ends with that thread's own commit or rollback
    for cn in pool.all:
        span_thread = None
        last_end = None
        for thread, op, _ in cn.log:
            if op == "borrow":
                span_thread, last_end = thread, None
            elif op == "return":
                assert thread == span_thread
                assert last_end in ("commit", "rollback")
                span_thread = None
            else:
                assert thread == span_thread
                if op in ("commit", "rollback"):
                    last_end = op

    # committed exactly the successful transactions, each complete
    rows = model.find("select txn_tag, count(*) as n from item group by txn_tag")
    counts = {r["txn_tag"]: r["n"] for r in rows}
    expected = {}
    for w in range(n_threads):
        for t in range(txns_per_thread):
            tag = f"w{w}-t{t}"
            if (w + t) % 3 != 0:
                expected[tag] = rows_per_txn
            expected[f"{tag}-solo"] = 1
    assert counts == expected


def test_plain_new_thread_inside_txn_gets_its_own_transaction():
    # threading.Thread does not copy the context on regular (GIL) builds,
    # so the new thread sees no binding and opens its own transaction
    import sys

    if getattr(sys.flags, "thread_inherit_context", False):
        pytest.skip("threads inherit context on this build")
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())
    seen = {}
    with model.txn():
        seen["outer"] = whoami(model)
        th = threading.Thread(target=lambda: seen.__setitem__("thread", whoami(model)))
        th.start()
        th.join(10)
    assert seen["outer"] != seen["thread"]
    assert pool.violations_all() == []


# ---------------------------------------------------------- owner guard


def test_inherited_context_in_new_thread_raises():
    # Python 3.14 free-threaded builds start threads with a copy of the
    # caller's context by default (sys.flags.thread_inherit_context)
    import sys

    if not getattr(sys.flags, "thread_inherit_context", False):
        pytest.skip("threads do not inherit context on this build")
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())
    errors: list[BaseException] = []
    with model.txn():
        th = threading.Thread(target=_capture, args=(errors, whoami, model))
        th.start()
        th.join(10)
    assert len(errors) == 1 and isinstance(errors[0], ModelException)
    assert pool.borrows == 1
    assert pool.violations_all() == []


def test_copied_context_in_other_thread_raises():
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())
    errors: list[BaseException] = []

    with model.txn():
        ctx = contextvars.copy_context()

        def run():
            try:
                ctx.run(model.find, "select * from item")
            except BaseException as e:
                errors.append(e)

        th = threading.Thread(target=run)
        th.start()
        th.join(10)
        assert pool.borrows == 1  # the other thread never touched the pool

    assert len(errors) == 1
    assert isinstance(errors[0], ModelException)
    assert "another thread" in str(errors[0])
    assert pool.violations_all() == []


def test_copied_context_txn_in_other_thread_raises():
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())
    errors: list[BaseException] = []

    def open_txn():
        with model.txn():
            pass  # pragma: no cover

    with model.txn():
        ctx = contextvars.copy_context()
        th = threading.Thread(target=lambda: _capture(errors, ctx.run, open_txn))
        th.start()
        th.join(10)
    assert isinstance(errors[0], ModelException)
    assert pool.violations_all() == []


def _capture(errors, fn, *args):
    try:
        fn(*args)
    except BaseException as e:
        errors.append(e)


def test_asyncio_to_thread_inside_txn_raises():
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())

    async def main():
        with model.txn():
            model.save(Item(txn_tag="loop", seq=1))
            with pytest.raises(ModelException, match="another thread"):
                await asyncio.to_thread(model.save, Item(txn_tag="thread", seq=1))
            # the owning transaction is unaffected and still usable
            model.save(Item(txn_tag="loop", seq=2))

    asyncio.run(main())
    assert [r["txn_tag"] for r in model.find("select txn_tag from item")] == [
        "loop",
        "loop",
    ]
    assert pool.violations_all() == []


def test_asyncio_to_thread_outside_txn_is_fine():
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())

    async def main():
        await asyncio.to_thread(model.save, Item(txn_tag="thread", seq=1))

    asyncio.run(main())
    assert len(model.find("select * from item")) == 1
    assert pool.violations_all() == []


def test_task_outliving_txn_raises():
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())

    async def late():
        await asyncio.sleep(0.01)
        model.find("select * from item")

    async def main():
        with model.txn():
            task = asyncio.create_task(late())  # copies the bound context
        with pytest.raises(ModelException, match="already ended"):
            await task

    asyncio.run(main())
    assert pool.violations_all() == []


# --------------------------------------------------------------- asyncio


def test_asyncio_tasks_each_get_their_own_connection():
    pool = memory_pool(2)
    model = Model(pool.connection, SqliteDialect())
    both_inside = asyncio.Barrier(2) if hasattr(asyncio, "Barrier") else None
    results: dict[str, list[str]] = {}

    async def job(name: str):
        with model.txn():
            names = [whoami(model)]
            model.save(Item(txn_tag=name, seq=1))
            if both_inside is not None:
                await both_inside.wait()  # both transactions open at once
            else:  # pragma: no cover - Python 3.10
                await asyncio.sleep(0.01)
            names.append(whoami(model))
            # sees its own uncommitted row only
            tags = model.find("select txn_tag from item")
            names.append(",".join(r["txn_tag"] for r in tags))
        results[name] = names

    async def main():
        await asyncio.gather(job("A"), job("B"))

    asyncio.run(main())
    a, b = results["A"], results["B"]
    assert a[0] == a[1] and b[0] == b[1]
    assert a[0] != b[0]
    assert a[2] == "A" and b[2] == "B"
    assert (pool.borrows, pool.returns) == (2, 2)
    assert pool.violations_all() == []
