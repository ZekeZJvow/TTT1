# -*- coding: utf-8 -*-
import io, sys

def edit(path, pairs):
    s = io.open(path, "r", encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in s else "\n"
    for i, (old, new) in enumerate(pairs):
        o, n_ = old.replace("\n", nl), new.replace("\n", nl)
        c = s.count(o)
        if c != 1:
            print("!! %s [%d] count=%d" % (path, i, c)); sys.exit(1)
        s = s.replace(o, n_)
    io.open(path, "w", encoding="utf-8", newline="").write(s)
    print("ok", path)

# 1) schema：新装时带 kline_rows 列
edit("schema.sql", [(
"  src          TEXT,\n  computed_at  TEXT\n);\n",
"  src          TEXT,\n  kline_rows   INTEGER,               -- 计算当天的日K行数（日K补齐后不一致 -> 自动重算）\n  computed_at  TEXT\n);\n",
)])

# 2) init_db：老库补列（忽略已存在错误）
edit("market_db.py", [
('''                conn.commit()
            finally:
                conn.close()
        _INITED = True
''',
 '''                # 老库补列（新装时 schema.sql 已含该列；重复 ALTER 报错会被忽略）
                for _sql in ("ALTER TABLE `market_seal_stats` ADD COLUMN `kline_rows` INTEGER",
                             "ALTER TABLE `market_breadth` ADD COLUMN `total_count` INTEGER",
                             "ALTER TABLE `market_breadth` ADD COLUMN `suspended` INTEGER"):
                    try:
                        conn.execute(_sql)
                    except Exception:
                        pass
                conn.commit()
            finally:
                conn.close()
        _INITED = True
'''),
# 3) compute_seal_stats：记录行数 + 行数变了就重算
('''        have = {}
        if not force:
            for r in conn.execute(
                    "SELECT `trade_date`,`src` FROM `market_seal_stats` WHERE `trade_date` >= ?",
                    (since,)).fetchall():
                have[str(r[0])] = (r[1] or "")
        # 盘中数据（src=intraday）不算定稿，收盘后要重算覆盖
        todo = [d for d in complete
                if pos[d] >= 2 and (force or have.get(d, "") in ("", "intraday"))]
''',
 '''        # 每天当前有多少条日K（用于判断统计是否已过期）
        counts = {}
        for r in conn.execute(
                "SELECT `trade_date`, COUNT(*) FROM `daily_kline` "
                "WHERE `trade_date` >= ? AND `change_pct` IS NOT NULL GROUP BY `trade_date`",
                (since,)).fetchall():
            counts[str(r[0])] = int(r[1] or 0)

        have = {}
        if not force:
            for r in conn.execute(
                    "SELECT `trade_date`,`src`,`kline_rows` FROM `market_seal_stats` "
                    "WHERE `trade_date` >= ?", (since,)).fetchall():
                have[str(r[0])] = (r[1] or "", int(r[2] or 0))

        def _need(d):
            if pos[d] < 2:
                return False
            src, rows = have.get(d, ("", 0))
            if src in ("", "intraday"):        # 没算过 / 盘中数据 -> 要算
                return True
            # 日K行数变了（补过历史 / 覆盖度变化）-> 统计已过期，重算
            return rows != counts.get(d, 0)

        todo = [d for d in complete if force or _need(d)]
'''),
# 4) upsert 带上 kline_rows
('''        upsert = _upsert("market_seal_stats",
                         ["trade_date", "up_count", "down_count", "flat_count",
                          "final_count", "sealed_count", "score", "src", "computed_at"],
                         ["trade_date"],
                         ["up_count", "down_count", "flat_count", "final_count",
                          "sealed_count", "score", "src", "computed_at"])
''',
 '''        upsert = _upsert("market_seal_stats",
                         ["trade_date", "up_count", "down_count", "flat_count",
                          "final_count", "sealed_count", "score", "src", "kline_rows",
                          "computed_at"],
                         ["trade_date"],
                         ["up_count", "down_count", "flat_count", "final_count",
                          "sealed_count", "score", "src", "kline_rows", "computed_at"])
'''),
('''            score = round(sealed / final * 100, 1) if final else None
            cur.execute(upsert, (d, up, down, flat, final, sealed, score, "kline", ts))
''',
 '''            score = round(sealed / final * 100, 1) if final else None
            cur.execute(upsert, (d, up, down, flat, final, sealed, score, "kline",
                                 counts.get(d, 0), ts))
'''),
# 5) 完整交易日的 counts 复用（原来那次查询已经是 counts）
('''        rows = conn.execute(
            "SELECT `trade_date`, COUNT(*) FROM `daily_kline` "
            "WHERE `trade_date` >= ? AND `change_pct` IS NOT NULL "
            "GROUP BY `trade_date`", (since,)).fetchall()
        complete = sorted(str(r[0]) for r in rows if (r[1] or 0) >= 2000)
''',
 '''        rows = conn.execute(
            "SELECT `trade_date`, COUNT(*) FROM `daily_kline` "
            "WHERE `trade_date` >= ? AND `change_pct` IS NOT NULL "
            "GROUP BY `trade_date`", (since,)).fetchall()
        complete = sorted(str(r[0]) for r in rows if (r[1] or 0) >= 2000)
        # 注：counts 在下面还会再查一次（保持逻辑清晰，代价很小）
'''),
])
