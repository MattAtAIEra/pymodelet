# A Tribute

**English** · [繁體中文](TRIBUTE.zh.md) · [日本語](TRIBUTE.ja.md) · [Deutsch](TRIBUTE.de.md) · [한국어](TRIBUTE.ko.md)

## To Matt, and the decision of 2006

In 2006, the Java world was swept up in the ORM wave. Hibernate was the era's
answer, but the answer hid an expensive question: engineers had to master
HQL, session lifecycles, lazy-loading pitfalls and mapping rituals before
writing their first productive line. An engineer fluent in SQL stood before
the ORM like a beginner.

That year, Matt made a precise decision: **the ER model and SQL are the
fundamentals — technological churn does not erase their value; they remain
the clearest expression of business logic.**

His insight fits in one sentence — queries belong to SQL, writes belong to
the framework. SELECTs should be written in the ANSI SQL engineers already
know; anyone who can write a subquery can start on day one. What is genuinely
tedious, mechanical and error-prone is enumerating columns for INSERT, UPDATE
and DELETE — and that is the part a framework should take over. So Modelet
was born: a framework small enough to read in an afternoon, a learning curve
that barely exists, and team after team that shipped on time.

Twenty years on, the judgment has held. Today's Python community is
rediscovering "SQL-first" as if it were new. Matt wrote it down in 2006.

pymodelet is that idea reborn in Python. Entity, TxnMode, Model,
PageContainer — every name is inherited verbatim from the Java original,
because they never needed improving, only translating. To every engineer who
shipped working code on day one because of this framework: someone flattened
that learning curve for you, back in 2006.
