"""One-to-many, the SQL-first way.  一對多,SQL-first 的做法。

Hibernate-style ORMs model relationships with mapping annotations, proxies and
lazy loading — and a learning curve to match. Modelet's answer, unchanged
since 2006: **the foreign key IS the relationship, and SQL already speaks it
fluently.** You write the JOIN / GROUP BY you already know; the framework
only does the tedious INSERT / UPDATE / DELETE.

傳統 ORM 用 mapping 註解、proxy、lazy loading 來表達關聯;Modelet 的答案從
2006 年至今沒變:**外鍵本身就是關聯,而 SQL 天生就會處理它。** JOIN 和
GROUP BY 你本來就會寫;框架只代勞繁瑣的寫入。

Run it (no database setup needed):

    cd python
    PYTHONPATH=src python3 examples/one_to_many.py
"""

import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from modelet import Entity, Model, SqliteDialect, Table, Transient, TxnMode

# ---------------------------------------------------------------- entities
# One Author has many Books. The relationship is just author_id — no
# @OneToMany, no mappedBy, no cascade configuration to memorize.


@Table("author")
@dataclass
class Author(Entity):
    name: str | None = None


@Table("book")
@dataclass
class Book(Entity):
    author_id: int | None = None  # ← the relationship, plain and visible
    title: str | None = None
    price: Decimal | None = None


# A read-shape for JOIN results: the extra joined column is Transient(),
# so it fills up on SELECT but never leaks into INSERT/UPDATE.
@dataclass
class BookWithAuthor(Book):
    author_name: str | None = Transient()


def main():
    cn = sqlite3.connect(":memory:")
    cn.executescript(
        """
        CREATE TABLE author (
          id   INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT
        );
        CREATE TABLE book (
          id        INTEGER PRIMARY KEY AUTOINCREMENT,
          author_id INTEGER REFERENCES author(id),
          title     TEXT,
          price     NUMERIC
        );
        """
    )
    model = Model(cn, SqliteDialect())

    # -------------------------------------------- writes: the framework's job
    # Save the parent, wire the children by foreign key, save them in one
    # transaction. Ids come back automatically.
    matt = Author(name="Matt")
    model.save(matt)

    books = [
        Book(author_id=matt.id, title="Modelet in Action", price=Decimal("450")),
        Book(author_id=matt.id, title="SQL-first ORM Design", price=Decimal("520")),
        Book(author_id=matt.id, title="ANSI SQL for Everyone", price=Decimal("380")),
    ]
    model.save(books)  # one transaction, three INSERTs, three ids written back

    someone = Author(name="Someone Else")
    model.save(someone)
    model.save(Book(author_id=someone.id, title="Another Book", price=Decimal("300")))

    # ------------------------------------- reads: your job, in SQL you know

    # 1. Children of one parent — a WHERE clause, nothing to configure.
    matts_books = model.find(
        "select * from book where author_id = ? order by id", [matt.id], Book
    )
    print(f"{len(matts_books)} books by Matt:")
    for b in matts_books:
        print(f"  [{b.id}] {b.title} — ${b.price}")

    # 2. Parent + child in one round trip — write the JOIN yourself, land it
    #    on a read-shape entity. author_name is Transient: filled on read,
    #    excluded from any future save.
    joined = model.find(
        """
        select b.*, a.name as author_name
          from book b
          join author a on a.id = b.author_id
         order by b.id
        """,
        None,
        BookWithAuthor,
    )
    print("\nAll books with their author (single JOIN):")
    for b in joined:
        print(f"  {b.title} by {b.author_name}")

    # ...and the read-shape saves back safely: author_name never leaks.
    first = joined[0]
    first.price = Decimal("499")
    model.save(first)  # UPDATE book SET author_id=?, title=?, price=? WHERE id=?

    # 3. Aggregation across the relationship — GROUP BY beats any ORM API.
    stats = model.find(
        """
        select a.name          as author,
               count(b.id)     as books,
               sum(b.price)    as total_price
          from author a
          left join book b on b.author_id = a.id
         group by a.id, a.name
         order by a.id
        """
    )
    print("\nBooks per author (GROUP BY, returned as dicts):")
    for row in stats:
        print(f"  {row['author']}: {row['books']} books, total ${row['total_price']}")

    # -------------------------- deleting a parent with children: explicit,
    # in one transaction. No cascade annotations — you can read exactly what
    # happens, because it's written right here.
    with model.txn():
        model.execute_sql("delete from book where author_id = ?", [someone.id])
        someone.txn_mode = TxnMode.DELETE
        model.save(someone)

    remaining = model.find("select count(*) as n from author")[0]["n"]
    print(f"\nAfter deleting 'Someone Else' and their books: {remaining} author(s) left.")

    cn.close()


if __name__ == "__main__":
    main()
