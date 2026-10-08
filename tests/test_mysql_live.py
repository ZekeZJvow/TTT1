# -*- coding: utf-8 -*-
"""
MySQL 真机测试（需要可用的 MySQL/MariaDB）

用法:
  # 1) 建库
  mysql -h127.0.0.1 -P3306 -uroot -e "CREATE DATABASE stock_test DEFAULT CHARSET utf8mb4"
  # 2) 跑测试
  set MYSQL_DSN=mysql://root:pwd@127.0.0.1:3306/stock_test
  python tests/test_mysql_live.py
"""
import io
import os
import sys
import threading
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PASS, FAIL = [], []


def chk(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("PASS " if cond else "FAIL ") + label + ("  [" + str(extra) + "]" if extra != "" else ""))


def main():
    dsn = os.environ.get("MYSQL_DSN") or ""
    if not dsn and os.path.isfile(os.path.join(ROOT, "_mysql_port.txt")):
        port = open(os.path.join(ROOT, "_mysql_port.txt")).read().strip()
        dsn = "mysql://root:@127.0.0.1:%s/stock_pool" % port
    if not dsn:
        print("未设置 MYSQL_DSN，跳过")
        return 0
    os.environ["MYSQL_DSN"] = dsn
    os.environ["DB_BACKEND"] = "mysql"
    os.environ["DB_POOL_SIZE"] = "5"
    os.environ["AUTO_FETCH_ENABLED"] = "0"

    import market_db as m
    print("backend =", "mysql" if m._is_mysql() else "sqlite", " dsn =", dsn)
    if not m.init_db(force=True):
        print("init_db 失败，请确认 MySQL 可用")
        return 1

    m.cleanup(scope="all")
    chk("建库成功", m.stats().get("backend") == "mysql")

    # ---- 基础读写 ----
    chk("日历写入", m.save_calendar(["2026-09-30", "2026-09-29"]) == 2)
    chk("日历读取(日期为字符串)", m.load_calendar(2) == ["2026-09-30", "2026-09-29"], m.load_calendar(2))

    rows = [{"rank": 1, "name": "中际旭创", "code": "300308", "rise_and_fall": -0.56,
             "consecutive_boards": "无", "tier": "第一梯队", "concept_tag": "CPO",
             "anomaly_analysis": "无", "is_hot": False}]
    chk("人气榜写入", m.save_hotlist("2026-09-30", rows, source="同花顺",
                                    captured_at="2026-09-30 15:30:00") == 1)
    h = m.load_hotlist("2026-09-30")
    chk("人气榜读取(rank 保留字)", h and h["data"][0]["rank"] == 1)
    chk("Decimal 归一化为 float", isinstance(h["data"][0]["rise_and_fall"], float),
        type(h["data"][0]["rise_and_fall"]).__name__)
    m.save_hotlist("2026-09-30", rows, source="同花顺", captured_at="2026-09-30 15:30:00")
    chk("UPSERT 幂等", len(m.load_hotlist("2026-09-30")["data"]) == 1)

    bars = [{"day": "2026-09-29", "open": 10, "high": 11, "low": 9.9, "close": 10.5, "volume": 1000},
            {"day": "2026-09-30", "open": 10.5, "high": 11.5, "low": 10.4, "close": 11.0, "volume": 1500}]
    chk("日K写入", m.save_daily_kline("000002", bars) == 2)
    k = m.load_daily_kline("000002", 10)
    chk("日K读取(日期字符串)", [x["date"] for x in k] == ["2026-09-29", "2026-09-30"], k)
    chk("前收价", m.load_prev_close("000002", "2026-09-30") == 10.5)

    res = {"success": True, "target": "2026-09-30", "prevDay": "2026-09-29", "universe": 100,
           "funnel": {"cond2": 10, "final": 5, "sealed": 3, "broken": 2, "removedByCond1": 5},
           "rows": [{"code": "601933", "name": "永辉超市", "gainHigh": 10.2}],
           "brokenRows": [], "removedRows": []}
    m.save_screening(res)
    chk("选股 payload 回放(LONGTEXT)", (m.load_screening("2026-09-30") or {}).get("funnel", {}).get("final") == 5)

    th = {"success": True, "as_of": "2026-09-30",
          "allThemes": [{"name": "房地产", "verdict": "利好", "rank": 1, "heatScore": 158.7}],
          "topics": [{"title": "t", "hot": 1.0}]}
    m.save_event_themes(th)
    chk("题材回放", (m.load_event_themes("2026-09-30") or {}).get("allThemes", [{}])[0].get("name") == "房地产")
    chk("日志写入(rows 保留字)", m.log_fetch("t", rows=1) is not None)

    # ---- 连接池 ----
    st = m.pool_stats()
    chk("连接池已启用", st.get("enabled") is True, st)
    chk("连接池上限=5", st.get("size") == 5, st)

    # ---- 并发压力：8 线程 × 40 次读写 ----
    errs = []
    barrier = threading.Barrier(8)

    def worker(wid):
        try:
            barrier.wait(timeout=20)
            for i in range(40):
                code = "%06d" % (100000 + wid * 100 + i)
                m.save_daily_kline(code, [{"day": "2026-09-30", "open": 1, "high": 2,
                                           "low": 0.5, "close": 1.5, "volume": 10}])
                r = m.load_daily_kline(code, 5)
                if not r or r[0]["date"] != "2026-09-30":
                    errs.append("wid=%d i=%d 读回不一致" % (wid, i))
        except Exception as e:
            errs.append("wid=%d %s" % (wid, e))

    ths = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    t0 = time.time()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    dt = time.time() - t0
    total = 8 * 40
    chk("并发写读无错误(%d 次操作, %.1fs)" % (total, dt), not errs, errs[:2])
    st2 = m.pool_stats()
    chk("连接池发生了复用", st2.get("reused", 0) > 0, st2)
    chk("连接数不超上限", st2.get("created", 99) <= 5, st2)
    cnt = m.kline_dates("100000")
    chk("并发写入数据落库正确", cnt and cnt["count"] == 1, cnt)

    # ---- 清理 ----
    chk("清理-按表", m.cleanup(scope="table", table="minute_kline")["deleted"] >= 0)
    chk("清空全部", m.cleanup(scope="all")["deleted"] >= 0)
    chk("清空后表结构仍在", len(m.overview()["tables"]) == 20)

    print("\n" + "=" * 60)
    print("  MySQL 真机：%d 通过 / %d 失败 / 共 %d" % (len(PASS), len(FAIL), len(PASS) + len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("    - " + f)
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
