# -*- coding: utf-8 -*-
import io, sys
p = "market_db.py"
s = io.open(p, "r", encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
def rep(old, new, tag):
    global s
    o, n_ = old.replace("\n", nl), new.replace("\n", nl)
    c = s.count(o)
    if c != 1:
        print("!! %s count=%d" % (tag, c)); sys.exit(1)
    s = s.replace(o, n_)

# 1) init_db 提交前补列
rep('''                        if "exist" not in str(e).lower():
                            raise
                conn.commit()
''',
'''                        if "exist" not in str(e).lower():
                            raise
                # 老库补列（新装时 schema.sql 已含；重复 ALTER 的错误忽略）
                for _sql in ("ALTER TABLE `market_seal_stats` ADD COLUMN `kline_rows` INTEGER",
                             "ALTER TABLE `market_breadth` ADD COLUMN `total_count` INTEGER",
                             "ALTER TABLE `market_breadth` ADD COLUMN `suspended` INTEGER"):
                    try:
                        conn.execute(_sql)
                    except Exception:
                        pass
                conn.commit()
''', "init_db")

# 2) have/todo + counts
rep('''        have = {}
        if not force:
            for r in conn.execute(
                    "SELECT `trade_date` FROM `market_seal_stats` WHERE `trade_date` >= ?",
                    (since,)).fetchall():
                have.add(str(r[0]))
        todo = [d for d in complete if pos[d] >= 2 and (force or d not in have)]
''',
'''        # 每天当前有多少条日K（统计是否过期，用它判断）
        counts = {}
        for r in conn.execute(
                "SELECT `trade_date`, COUNT(*) FROM `daily_kline` "
                "WHERE `trade_date` >= ? AND `change_pct` IS NOT NULL "
                "GROUP BY `trade_date`", (since,)).fetchall():
            counts[str(r[0])] = int(r[1] or 0)

        have = {}
        if not force:
            try:
                for r in conn.execute(
                        "SELECT `trade_date`,`src`,`kline_rows` FROM `market_seal_stats` "
                        "WHERE `trade_date` >= ?", (since,)).fetchall():
                    have[str(r[0])] = (r[1] or "", int(r[2] or 0))
            except Exception:
                for r in conn.execute(
                        "SELECT `trade_date`,`src` FROM `market_seal_stats` "
                        "WHERE `trade_date` >= ?", (since,)).fetchall():
                    have[str(r[0])] = (r[1] or "", 0)

        def _need(d):
            if pos[d] < 2:
                return False
            src, rows = have.get(d, ("", 0))
            if src in ("", "intraday"):       # 没算过 / 盘中数据 -> 要算
                return True
            return rows != counts.get(d, 0)   # 日K行数变了 -> 统计过期，重算

        todo = [d for d in complete if force or _need(d)]
''', "have/todo")

# 3) upsert 带 kline_rows
rep('''        upsert = _upsert("market_seal_stats",
                         ["trade_date", "up_count", "down_count", "flat_count",
                          "final_count", "sealed_count", "score", "src", "computed_at"],
                         ["trade_date"],
                         ["up_count", "down_count", "flat_count",
                          "final_count", "sealed_count", "score", "src", "computed_at"])
''',
'''        upsert = _upsert("market_seal_stats",
                         ["trade_date", "up_count", "down_count", "flat_count",
                          "final_count", "sealed_count", "score", "src", "kline_rows",
                          "computed_at"],
                         ["trade_date"],
                         ["up_count", "down_count", "flat_count",
                          "final_count", "sealed_count", "score", "src", "kline_rows",
                          "computed_at"])
''', "upsert")

# 4) 写入时带行数
rep('''            cur.execute(upsert, (d, up, down, flat, final, sealed, score, "kline", ts))
''',
'''            cur.execute(upsert, (d, up, down, flat, final, sealed, score, "kline",
                                 counts.get(d, 0), ts))
''', "insert")

io.open(p, "w", encoding="utf-8", newline="").write(s)
import ast; ast.parse(s)
print("market_db.py 补丁完成，语法 OK")
