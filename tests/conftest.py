import sqlite3

import pytest

from modelet import Model, SqliteDialect


@pytest.fixture
def model():
    cn = sqlite3.connect(":memory:")
    cn.execute(
        """
        CREATE TABLE book (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_name TEXT,
          price NUMERIC,
          a_enum TEXT,
          create_date TIMESTAMP
        )
        """
    )
    cn.execute(
        """
        CREATE TABLE article (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT,
          create_date TIMESTAMP,
          creator TEXT,
          modify_date TIMESTAMP,
          modifier TEXT
        )
        """
    )
    yield Model(cn, SqliteDialect())
    cn.close()
