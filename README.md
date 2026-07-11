# pymodelet

Python port of [Modelet](https://github.com/MattAtAIEra/modelet) — the
SQL-first micro ORM created by Matt in 2006. See [TRIBUTE.md](TRIBUTE.md)
for the story and the debt this port owes to the original.

**Website:** https://mattataiera.github.io/pymodelet/ ·
**Comparison** with psycopg / aiosql / SQLAlchemy:
https://mattataiera.github.io/pymodelet/compare-python.html

## Install

```bash
pip install pymodelet          # once published to PyPI
pip install git+https://github.com/MattAtAIEra/pymodelet   # from source
```

The distribution is named `pymodelet`; the import name is `modelet`
(`from modelet import Model, Entity`), matching the Java original's package.

The founding idea, unchanged: **queries belong to SQL, writes belong to the
framework.** Anyone with ANSI SQL experience (and a subquery or two) can build
and maintain an application without learning a query DSL. The ORM's job is
only the tedious part: turning entities into INSERT / UPDATE / DELETE
statements, writing generated keys back, stamping audit fields.

- Python 3.10+, zero runtime dependencies — sits directly on any
  [DB-API 2.0](https://peps.python.org/pep-0249/) connection
  (sqlite3, PyMySQL, psycopg, ...).
- Entities are plain dataclasses.
- ~600 lines of source. Read it in one sitting.

## Usage

```python
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from modelet import Entity, Model, PagingElement, SqliteDialect, TxnMode

@dataclass
class Book(Entity):
    book_name: str | None = None
    price: Decimal | None = None
    create_date: datetime | None = None

    table_name = "book"

model = Model(sqlite3.connect("app.db"), SqliteDialect())

# --- writes: the framework's job -------------------------------------
book = Book(book_name="ANSI SQL in a nutshell", price=Decimal("150"))
model.save(book)          # INSERT; db-generated id written back to book.id
                          # book.txn_mode is now UPDATE

book.price = Decimal("120")
model.save(book)          # UPDATE ... WHERE id=?

book.txn_mode = TxnMode.DELETE
model.save(book)          # DELETE ... WHERE id=?

# --- queries: your job, in plain SQL ----------------------------------
rows  = model.find("select * from book where price > ?", [100])         # dicts
books = model.find("select * from book where price > ?", [100], Book)   # entities

page = model.find_with_paging(
    "select * from book order by id", None,
    PagingElement(target_page=2, rows_per_page=20), Book)
print(page.total_pages, page.total_records, page.rows)

# --- transactions ------------------------------------------------------
with model.txn():
    model.save(books_a)
    model.save(books_b)   # both commit together, roll back together
```

### Audit fields

Subclass `AppEntity` instead of `Entity` and bind a login to the current
context; `creator/create_date` are stamped on insert, `modifier/modify_date`
on update:

```python
from modelet import AppEntity, Login, set_login

set_login(Login("matt"))
```

### Entity declaration vocabulary

Entity metadata is declared through the `modelet.persistence` helpers. Their
names are borrowed from the Jakarta Persistence (JPA) annotations used by the
Java original, so an entity declaration reads line-for-line the same in both
languages — but only the vocabulary is borrowed: the engine stays SQL-first,
and no Java spec is involved:

```python
from modelet import Column, Entity, Enumerated, EnumType, Id, Table, Transient

@Table("book")                                        # @Table(name = "book")
@dataclass
class Book(Entity):
    title: str | None = Column("bookName")            # @Column(name = "bookName")
    grade: Grade | None = Enumerated(EnumType.ORDINAL)  # @Enumerated(ORDINAL)
    joined_row_count: int | None = Transient()        # @Transient

@Table("account")
@dataclass
class Account(Entity):
    account_no: str | None = Id()   # @Id without @GeneratedValue:
    owner: str | None = None        # application supplies the key itself
```

- `Id()` markers replace `key_names`; multiple `Id()` fields form a composite
  key, and UPDATE/DELETE criteria always bind key values as placeholders.
- `Id(generated=True)` (or `GeneratedValue()`) means the database generates
  the key and Modelet writes it back after insert. `Id()` alone means the
  application supplies it (the annotation-era `system_increment`).
- `Enumerated(EnumType.STRING)` stores the member name (the default, even
  unannotated); `EnumType.ORDINAL` stores the member's position.
- Without any annotations, the class-attribute conventions below apply
  unchanged.

### Column mapping

Field names match columns case-insensitively, ignoring underscores — a
`bookName` column fills a `book_name` field automatically. `Column(...)` above
is sugar for dataclass field metadata; the raw form also works:

```python
book_name: str | None = field(default=None, metadata={"column": "bookName"})
row_count: int | None = field(default=None, metadata={"transient": True})
```

### Entity configuration (class attributes)

| Attribute | Default | Java counterpart |
|---|---|---|
| `table_name` | class name lowercased | `getTableName()` |
| `key_names` | `("id",)` | `getKeyNames()` |
| `exclusive_fields` | `()` | `getExclusiveFields()` |
| `system_increment` | `False` | `SystemIncrementEntity` |
| `allow_null_value` | `False` | `isAllowNullValue()` |

### Relationships, the SQL-first way

There is no `@OneToMany`, no lazy loading, no cascade configuration — the
foreign key IS the relationship, and SQL already speaks it fluently. See
[`examples/one_to_many.py`](examples/one_to_many.py) for the complete
pattern: children by WHERE clause, parent+child in one JOIN landing on a
read-shape entity with a `Transient()` column, aggregation with GROUP BY,
and explicit parent-with-children deletion in one transaction.

```bash
PYTHONPATH=src python3 examples/one_to_many.py
```

## Tests

```bash
cd python
PYTHONPATH=src python3 -m pytest tests
```

Runs against in-memory SQLite; no database setup required.
