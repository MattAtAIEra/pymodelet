"""The Model — Python port of modelet.model.DefaultModel.

Philosophy, inherited from the 2006 Java original: queries are written in
plain ANSI SQL by the developer; the framework only takes over the mechanical
INSERT / UPDATE / DELETE work driven by each entity's TxnMode state machine.

Differences from the Java version, on purpose:

- ``find_one`` returns ``None`` when nothing matches (Java returned a blank
  entity instance).
- Paging issues a ``COUNT(*)`` plus ``LIMIT/OFFSET`` instead of scanning the
  whole result set. The Java behavior of falling back to page 1 when the
  requested page exceeds the total is preserved.
- Transactions are explicit context managers (``with model.txn(): ...``)
  instead of Spring's declarative ``@Transactional``. Every public method
  behaves like ``PROPAGATION_REQUIRED``: inside a ``txn()`` block it joins
  that transaction; outside one it runs in its own short transaction
  (commit on success, rollback on error) and releases the connection before
  returning.

Connection management follows Spring's singleton bean +
``DataSourceUtils.getConnection`` + ``TransactionSynchronizationManager``:

- ``Model`` is built from a *connection source*: a zero-argument callable
  returning a context manager whose ``__enter__`` yields a DB-API connection
  and whose ``__exit__`` gives it back (``psycopg_pool.ConnectionPool.connection``
  fits as-is; other pools via ``lambda: contextlib.closing(pool.connect())``).
  pymodelet ships no pool of its own.
- The connection of the active transaction is bound in a ``ContextVar``
  (keyed by the source, the way Spring keys resources by DataSource), so each
  thread / asyncio task sees only its own transaction. ``Model`` itself holds
  no per-request state and can be a module-level singleton.
"""

from __future__ import annotations

import logging
import math
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, ContextManager, Mapping

from .context import get_login
from .dialect import Dialect
from .entity import AppEntity, Entity, TxnMode
from .exceptions import ModelException
from .paging import PageContainer, PagingElement
from .persistence import id_is_generated
from .rows import dict_to_entity, rows_to_dicts
from .statement import Statement, build_delete, build_insert, build_update

LOG = logging.getLogger("modelet")
EXP_LOG = logging.getLogger("modelet.exception")


ConnectionSource = Callable[[], ContextManager[Any]]
"""Zero-argument callable; ``with source() as cn`` borrows a DB-API
connection and returns it on exit."""


@dataclass(eq=False)
class _TxnState:
    """What ``txn()`` binds for the duration of one physical transaction."""

    connection: Any
    owner_thread: int  # threading.get_ident() of the thread that opened it
    completed: bool = False


# source key -> _TxnState. The mapping is never mutated in place: binding a
# transaction sets a new dict and unbinding resets the token, so a copied
# Context (asyncio tasks, to_thread, copy_context().run) can never observe a
# half-updated map, and a future REQUIRES_NEW can bind a fresh state over an
# outer one and restore it by token.
_bound: ContextVar[Mapping[Any, _TxnState]] = ContextVar(
    "modelet_txn", default={}
)


def _is_dbapi_connection(obj) -> bool:
    # callable() alone cannot tell a source from a connection:
    # sqlite3.Connection implements __call__ (a legacy statement factory).
    return all(hasattr(obj, name) for name in ("cursor", "commit", "rollback"))


# id() of connections currently serving a transaction for some Model(cn);
# shared so that two Model(cn) over the same cn are also guarded.
_single_in_use: set[int] = set()
_single_lock = threading.Lock()


class _SingleConnectionSource:
    """Adapts a bare connection to the source protocol for ``Model(cn)``.

    Yields the one connection and never closes it. It can serve only one
    transaction at a time, so a second concurrent borrow (another thread, or
    another asyncio task while a ``txn()`` is suspended at an ``await``)
    raises instead of silently sharing the transaction.

    Equality follows the wrapped connection, so two ``Model(cn)`` over the
    same ``cn`` join each other's transactions rather than committing each
    other's partial work.
    """

    def __init__(self, connection):
        self.connection = connection

    def __eq__(self, other):
        return (
            isinstance(other, _SingleConnectionSource)
            and other.connection is self.connection
        )

    def __hash__(self):
        return id(self.connection)

    @contextmanager
    def __call__(self):
        key = id(self.connection)
        with _single_lock:
            if key in _single_in_use:
                raise ModelException(
                    "Model(connection) is single-thread only: its one "
                    "connection is already serving another transaction. "
                    "Build the Model from a connection source (a pool) to "
                    "share it across threads or asyncio tasks."
                )
            _single_in_use.add(key)
        try:
            yield self.connection
        finally:
            with _single_lock:
                _single_in_use.discard(key)


class _IdentityKey:
    """Fallback binding key for an unhashable source."""

    __slots__ = ("obj",)

    def __init__(self, obj):
        self.obj = obj

    def __eq__(self, other):
        return isinstance(other, _IdentityKey) and other.obj is self.obj

    def __hash__(self):
        return id(self.obj)


class Model:
    def __init__(self, connection, dialect: Dialect | None = None):
        """``connection`` is either

        - a *connection source*: a zero-argument callable returning a context
          manager that yields a DB-API 2.0 connection and gives it back on
          exit, e.g. ``psycopg_pool.ConnectionPool(...).connection``, or
          ``lambda: contextlib.closing(sqlalchemy_pool.connect())``. A Model
          built this way is safe to share across threads and asyncio tasks;
          or
        - a single DB-API 2.0 connection (sqlite3, PyMySQL, psycopg, ...),
          the original form. Such a Model is **single-thread only**: it
          serves one transaction at a time and raises ``ModelException`` if
          a second one is attempted concurrently.

        Connections must not be in autocommit mode, or ``txn()`` cannot group
        statements. Pick the matching Dialect; defaults to qmark style."""
        if _is_dbapi_connection(connection):
            source: ConnectionSource = _SingleConnectionSource(connection)
        elif callable(connection):
            source = connection
        else:
            raise TypeError(
                "Model() takes a DB-API connection or a zero-argument "
                "callable returning a context manager that yields one; got "
                f"{type(connection).__name__}"
            )
        self._source = source
        try:
            hash(source)
            self._key = source
        except TypeError:
            self._key = _IdentityKey(source)
        self.dialect = dialect or Dialect()

    # ------------------------------------------------------------- queries

    def find(self, sql: str, params=None, cls: type[Entity] | None = None):
        """Run any SELECT you can write. Returns ``list[dict]``, or a list of
        ``cls`` instances (in UPDATE mode, ready to save back) when given."""
        # rows are fully fetched before the connection can be released
        with self.txn():
            cur = self._execute(sql, params)
            try:
                dicts = rows_to_dicts(cur)
            finally:
                cur.close()
        if cls is None:
            return dicts
        return [dict_to_entity(cls, row) for row in dicts]

    def find_one(self, sql: str, params=None, cls: type[Entity] | None = None):
        results = self.find(sql, params, cls)
        return results[0] if results else None

    def get_entity_by_id(self, id, cls: type[Entity], table_name: str | None = None):
        table = table_name or cls.table_name or cls.__name__.lower()
        return self.find_one(f"SELECT * FROM {table} WHERE id=?", [id], cls)

    def get_entity_map_by_id(self, id, table_name: str):
        return self.find_one(f"SELECT * FROM {table_name} WHERE id=?", [id])

    def find_with_paging(
        self,
        sql: str,
        params=None,
        paging: PagingElement | None = None,
        cls: type[Entity] | None = None,
    ) -> PageContainer:
        # COUNT(*) and the page query share one transaction
        with self.txn():
            return self._find_with_paging(sql, params, paging, cls)

    def _find_with_paging(self, sql, params, paging, cls) -> PageContainer:
        paging = paging or PagingElement()
        cur = self._execute(self.dialect.count(sql), params)
        try:
            total_records = cur.fetchone()[0]
        finally:
            cur.close()
        total_pages = math.ceil(total_records / paging.rows_per_page) if total_records else 0

        # same courtesy as the Java DataRoller: an out-of-range page falls
        # back to the first page rather than returning an empty result
        if total_pages and paging.target_page > total_pages:
            paging.target_page = 1

        offset = (paging.target_page - 1) * paging.rows_per_page
        page_sql, page_params = self.dialect.paginate(sql, offset, paging.rows_per_page)
        rows = self.find(page_sql, list(params or []) + page_params, cls)
        return PageContainer(rows=rows, total_pages=total_pages, total_records=total_records)

    # -------------------------------------------------------------- writes

    def save(self, entity_or_entities) -> int:
        """Persist one entity or a list of entities (the list runs in a single
        transaction). What happens is decided by each entity's ``txn_mode``."""
        with self.txn():
            if isinstance(entity_or_entities, (list, tuple)):
                return sum(self._save_one(e) for e in entity_or_entities)
            return self._save_one(entity_or_entities)

    def execute_sql(self, sql: str, params=None) -> int:
        """Run any INSERT/UPDATE/DELETE/DDL you can write; returns rowcount."""
        with self.txn():
            cur = self._execute(sql, params)
            try:
                return cur.rowcount
            finally:
                cur.close()

    def _save_one(self, entity: Entity) -> int:
        mode = getattr(entity, "txn_mode", None)
        if mode is None:
            raise ModelException(
                "Please assign action type (insert, update, delete) before "
                "persisting the entity."
            )
        self._inject_signature_and_timestamp(entity)
        entity.before_save()
        if mode == TxnMode.INSERT:
            return_code = self._insert(entity)
        elif mode == TxnMode.UPDATE:
            return_code = self._run_statement(build_update(entity))
        elif mode == TxnMode.DELETE:
            return_code = self._run_statement(build_delete(entity))
        else:
            raise ModelException(f"txn_mode {mode} is not persistable.")
        entity.after_save()
        return return_code

    def _insert(self, entity: Entity) -> int:
        stmt = build_insert(entity)
        cur = self._execute(stmt.sql, stmt.params)
        try:
            return_code = cur.rowcount
            if entity.id is None and id_is_generated(type(entity)):
                entity.id = cur.lastrowid
        finally:
            cur.close()
        entity.txn_mode = TxnMode.UPDATE
        return return_code

    def _run_statement(self, stmt: Statement) -> int:
        cur = self._execute(stmt.sql, stmt.params)
        try:
            return cur.rowcount
        finally:
            cur.close()

    def _inject_signature_and_timestamp(self, entity: Entity) -> None:
        if not isinstance(entity, AppEntity):
            return
        now = datetime.now()
        login = get_login()
        if entity.txn_mode == TxnMode.INSERT:
            entity.create_date = now
            if login:
                entity.creator = login.login_id
        elif entity.txn_mode == TxnMode.UPDATE:
            entity.modify_date = now
            if login:
                entity.modifier = login.login_id

    # -------------------------------------------------------- transactions

    @contextmanager
    def txn(self):
        """Run the block in one transaction (``PROPAGATION_REQUIRED``).

        The outermost ``txn()`` in the current context borrows a connection
        from the source and binds it; nested blocks, and every Model method
        called inside, reuse that connection. The outermost block commits on
        clean exit and rolls back on error, then returns the connection.

        The binding lives in a ``ContextVar``: other threads and asyncio
        tasks never see it. A *copy* of the context does carry it, so a bound
        transaction reached from a different thread (``asyncio.to_thread``,
        ``copy_context().run`` in a new thread, inherited context on
        free-threaded builds), or after its block has exited (a task created
        inside the block that outlives it), raises ``ModelException``
        rather than sharing the connection.
        """
        if self._bound_state() is not None:
            yield self  # join the enclosing transaction
            return

        with self._source() as cn:
            state = _TxnState(connection=cn, owner_thread=threading.get_ident())
            token = _bound.set({**_bound.get(), self._key: state})
            try:
                try:
                    yield self
                except BaseException:
                    self._rollback_quietly(cn)
                    raise
                try:
                    cn.commit()
                except BaseException:
                    self._rollback_quietly(cn)
                    raise
            finally:
                state.completed = True
                _bound.reset(token)

    def _bound_state(self) -> _TxnState | None:
        state = _bound.get().get(self._key)
        if state is None:
            return None
        if state.owner_thread != threading.get_ident():
            raise ModelException(
                "A transaction bound in another thread was reached through a "
                "copied context (asyncio.to_thread, copy_context().run, or "
                "thread context inheritance). A DB-API connection must not be "
                "shared across threads: do the database work in the thread "
                "that opened the txn(), or hand the work to the other thread "
                "before entering txn()."
            )
        if state.completed:
            raise ModelException(
                "The transaction bound in this context has already ended; the "
                "context was copied (e.g. an asyncio task created inside "
                "txn()) and outlived the txn() block."
            )
        return state

    @staticmethod
    def _rollback_quietly(cn) -> None:
        try:
            cn.rollback()
        except Exception:
            EXP_LOG.error("Rollback failed", exc_info=True)

    # ------------------------------------------------------------ plumbing

    def _execute(self, sql: str, params):
        prepared_sql, prepared_params = self.dialect.prepare(sql, params)
        LOG.info("Model INFO: %s params: %s", prepared_sql, prepared_params)
        state = self._bound_state()
        assert state is not None, "_execute must run inside txn()"
        cur = state.connection.cursor()
        try:
            cur.execute(prepared_sql, prepared_params)
        except Exception as e:
            cur.close()
            EXP_LOG.error("Fail to execute: %s params: %s", prepared_sql, prepared_params, exc_info=True)
            raise ModelException(f"Fail to execute: {prepared_sql}", e) from e
        return cur
