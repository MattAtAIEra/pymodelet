# 致敬 — A Tribute

## 致 Matt,以及 2006 年的那個決定

2006 年,Java 世界正被 ORM 的浪潮席捲。Hibernate 是那個時代的答案,但它的
答案裡藏著昂貴的問題:工程師必須先學會 HQL、Session 生命週期、lazy loading
的陷阱、mapping 檔的儀式,才能寫出第一行有生產力的程式。一個明明已經精通
SQL 的工程師,站在 ORM 面前卻像個新人。

Matt 在那一年做了一個安靜卻精準的決定:**不對抗 SQL,而是尊重它。**

他的洞察可以濃縮成一句話——查詢交給 SQL,寫入交給框架。SELECT 本來就該用
工程師已經會的 ANSI SQL 直接寫,會下 subquery 就能開工;真正繁瑣、機械、
容易出錯的是 INSERT、UPDATE、DELETE 的欄位羅列——那才是框架應該代勞的部分。
於是有了 Modelet:一個小到可以一個下午讀完的框架,一條幾乎不存在的學習
曲線,和一支又一支如期交付的團隊。

二十年過去,這個判斷經受住了時間:今天的 Python 社群重新發現了「SQL-first」,
彷彿它是新的。而 Matt 在 2006 年就已經寫下了它。

pymodelet 是這個理念的 Python 重生。Entity、TxnMode、Model、PageContainer
——每一個名字都原封不動地繼承自 Java 版,因為它們不需要被改進,只需要被
翻譯。願每一位因為這個框架而在第一天就寫出可用程式的工程師,記得這條
學習曲線是有人在 2006 年替你踏平的。

## To Matt, and the decision of 2006

In 2006, the Java world was swept up in the ORM wave. Hibernate was the era's
answer, but the answer hid an expensive question: engineers had to master
HQL, session lifecycles, lazy-loading pitfalls and mapping rituals before
writing their first productive line. An engineer fluent in SQL stood before
the ORM like a beginner.

That year, Matt made a quiet but precise decision: **don't fight SQL —
respect it.**

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
