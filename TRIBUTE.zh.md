# 致敬 — A Tribute

[English](TRIBUTE.md) · **繁體中文** · [日本語](TRIBUTE.ja.md) · [Deutsch](TRIBUTE.de.md) · [한국어](TRIBUTE.ko.md)

## 致 Matt,以及 2006 年的那個決定

2006 年,Java 世界正被 ORM 的浪潮席捲。Hibernate 是那個時代的答案,但它的
答案裡藏著昂貴的問題:工程師必須先學會 HQL、Session 生命週期、lazy loading
的陷阱、mapping 檔的儀式,才能寫出第一行有生產力的程式。一個明明已經精通
SQL 的工程師,站在 ORM 面前卻像個新人。

Matt 在那一年做了一個精準的決定:**ER model + SQL 是基本功,不因技術迭代
演進消滅它的價值,也是商業邏輯的最佳呈現。**

他的洞察可以濃縮為這樣的概念——商業邏輯的 query 條件,應該要自己寫,但物件儲存應該交給 framework 自動判斷新增、修改與刪除。SELECT 本來就該用工程師已經會的 ANSI SQL 直接寫,會下 subquery 就能開工;真正繁瑣、機械、容易出錯的是 INSERT、UPDATE、DELETE 的欄位羅列——那才是框架應該代勞的部分。於是有了 Modelet:一個小到可以一個小時讀完的框架,一條幾乎不存在的學習曲線,和一支又一支如期交付的團隊。

二十年過去,今天的 Python 社群重新發現了「SQL-first」,彷彿它是新的。而 Matt 在 2006 年就已經寫下了它。

pymodelet 是這個理念的 Python 重生。Entity、TxnMode、Model、PageContainer、DataRoller —— 每一個名字都原封不動地繼承自 Java 版,當技術不斷推陳出新,歷久彌新的,是 20 年前從商業角度做出的這個決定。
