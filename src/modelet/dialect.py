"""Database dialects.

Modelet SQL is written with DB-API ``qmark`` placeholders (``?``), matching
the framework's JDBC heritage. A Dialect adapts that to the driver's actual
paramstyle and applies per-driver parameter conversions, plus the two pieces
of SQL that cannot be expressed portably: pagination and row counting.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class Dialect:
    #: DB-API paramstyle of the target driver: "qmark" or "format"
    paramstyle = "qmark"

    def prepare(self, sql: str, params) -> tuple[str, list]:
        converted = [self.convert_param(p) for p in (params or [])]
        if self.paramstyle == "qmark":
            return sql, converted
        return self._qmark_to_format(sql), converted

    def convert_param(self, value):
        """Mirror of Java DefaultModel.convertParams: Enum -> name string,
        list/tuple -> comma-joined string. Dates and bools are left to the
        driver unless a subclass overrides."""
        if isinstance(value, Enum):
            return value.name
        if isinstance(value, (list, tuple)):
            return ", ".join(str(self.convert_param(v)) for v in value)
        return value

    def paginate(self, sql: str, offset: int, limit: int) -> tuple[str, list]:
        return f"{sql} LIMIT ? OFFSET ?", [limit, offset]

    def count(self, sql: str) -> str:
        return f"SELECT COUNT(*) FROM ({sql}) AS modelet_count"

    @staticmethod
    def _qmark_to_format(sql: str) -> str:
        out, in_string = [], False
        for ch in sql:
            if ch == "'":
                in_string = not in_string
            if ch == "?" and not in_string:
                out.append("%s")
            else:
                out.append(ch)
        return "".join(out)


class SqliteDialect(Dialect):
    """sqlite3 binds only None/int/float/str/bytes; adapt the rest."""

    def convert_param(self, value):
        value = super().convert_param(value)
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bool):
            return int(value)
        return value


class MySQLDialect(Dialect):
    """PyMySQL / mysql-connector use the ``format`` paramstyle and handle
    datetime/Decimal/bool natively."""

    paramstyle = "format"
