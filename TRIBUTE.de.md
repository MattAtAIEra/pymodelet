# Eine Widmung — A Tribute

[English](TRIBUTE.md) · [繁體中文](TRIBUTE.zh.md) · [日本語](TRIBUTE.ja.md) · **Deutsch** · [한국어](TRIBUTE.ko.md)

## An Matt und die Entscheidung von 2006

2006 wurde die Java-Welt von der ORM-Welle erfasst. Hibernate war die Antwort
jener Zeit, doch die Antwort verbarg eine teure Frage: Ingenieure mussten
HQL, Session-Lebenszyklen, die Fallstricke des Lazy Loading und
Mapping-Rituale beherrschen, bevor sie die erste produktive Zeile schrieben.
Ein in SQL versierter Ingenieur stand vor dem ORM wie ein Anfänger.

In jenem Jahr traf Matt eine präzise Entscheidung: **Das ER-Modell und SQL
sind das Fundament — technologischer Wandel löscht ihren Wert nicht aus; sie
bleiben der klarste Ausdruck der Geschäftslogik.**

Seine Einsicht verdichtet sich zu einem Gedanken — die Abfragebedingungen deiner Geschäftslogik solltest du selbst schreiben, doch die Persistenz der Objekte sollte dem Framework überlassen werden, das Insert, Update oder Delete automatisch entscheidet. SELECTs schreibt man in dem ANSI-SQL, das Ingenieure schon kennen; wer eine Subquery schreiben kann, legt am ersten Tag los. Wirklich mühsam, mechanisch und fehleranfällig ist das Auflisten der Spalten für INSERT, UPDATE und DELETE — und genau das sollte ein Framework übernehmen. So entstand Modelet: ein Framework, klein genug, um es in einer Stunde zu lesen, eine Lernkurve, die kaum existiert, und ein Team nach dem anderen, das pünktlich lieferte.

Zwei Jahrzehnte später entdeckt die heutige Python-Community „SQL-first“ neu, als wäre es neu. Matt schrieb es 2006 nieder.

pymodelet ist diese Idee, in Python wiedergeboren. Entity, TxnMode, Model, PageContainer, DataRoller — jeder Name ist wortgetreu vom Java-Original übernommen. Während sich die Technik immer wieder neu erfindet, bleibt bestehen: diese Entscheidung, vor zwei Jahrzehnten aus geschäftlicher Sicht getroffen.
