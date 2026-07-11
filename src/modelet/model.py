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
  instead of Spring's declarative ``@Transactional``. Every ``save`` /
  ``execute_sql`` outside a ``txn()`` block commits on its own, mirroring
  Spring's per-method transaction.
"""

from __future__ import annotations

import logging
import math
from contextlib import contextmanager
from datetime import datetime

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


class Model:
    def __init__(self, connection, dialect: Dialect | None = None):
        """``connection`` is any DB-API 2.0 connection (sqlite3, PyMySQL,
        psycopg, ...). Pick the matching Dialect; defaults to qmark style."""
        self._cn = connection
        self.dialect = dialect or Dialect()
        self._txn_depth = 0

    # ------------------------------------------------------------- queries

    def find(self, sql: str, params=None, cls: type[Entity] | None = None):
        """Run any SELECT you can write. Returns ``list[dict]``, or a list of
        ``cls`` instances (in UPDATE mode, ready to save back) when given."""
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
        """Commit on clean exit of the outermost block, roll back on error."""
        self._txn_depth += 1
        try:
            yield self
        except BaseException:
            self._txn_depth -= 1
            if self._txn_depth == 0:
                self._cn.rollback()
            raise
        else:
            self._txn_depth -= 1
            if self._txn_depth == 0:
                self._cn.commit()

    # ------------------------------------------------------------ plumbing

    def _execute(self, sql: str, params):
        prepared_sql, prepared_params = self.dialect.prepare(sql, params)
        LOG.info("Model INFO: %s params: %s", prepared_sql, prepared_params)
        cur = self._cn.cursor()
        try:
            cur.execute(prepared_sql, prepared_params)
        except Exception as e:
            cur.close()
            EXP_LOG.error("Fail to execute: %s params: %s", prepared_sql, prepared_params, exc_info=True)
            raise ModelException(f"Fail to execute: {prepared_sql}", e) from e
        return cur
