"""pymodelet — SQL-first micro ORM.

Python port of the Modelet framework (Java, 2006): write queries in the ANSI
SQL you already know; let the framework generate the tedious INSERT / UPDATE /
DELETE statements from your entities.
"""

from .context import Login, get_login, reset_login, set_login
from .dialect import Dialect, MySQLDialect, SqliteDialect
from .entity import AppEntity, Entity, TxnMode
from .exceptions import ModelException
from .model import Model
from .paging import PageContainer, PagingElement
from .persistence import (
    Column,
    Enumerated,
    EnumType,
    GeneratedValue,
    Id,
    Table,
    Transient,
)

__all__ = [
    "AppEntity",
    "Column",
    "Dialect",
    "Entity",
    "Enumerated",
    "EnumType",
    "GeneratedValue",
    "Id",
    "Login",
    "Model",
    "ModelException",
    "MySQLDialect",
    "PageContainer",
    "PagingElement",
    "SqliteDialect",
    "Table",
    "Transient",
    "TxnMode",
    "get_login",
    "reset_login",
    "set_login",
]
