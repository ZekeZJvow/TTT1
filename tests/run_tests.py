# -*- coding: utf-8 -*-
"""
本地回归测试套件（不需要 MySQL 服务器）

用法:  python tests/run_tests.py
覆盖:  数据层(SQLite) / SQL方言 / 完整性校验 / 清理 / 连接池状态 / 通知模块 / 定时任务逻辑
"""
import io
import os
import shutil
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PASS, FAIL = [], []


def chk(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("PASS " if cond else "FAIL ") + label + ("  [" + str(extra) + "]" if extra != "" else ""))


def section(name):
    print("\n" + "=" * 60)
    print("  " + name)
    print("=" * 60)


def reset_env():
    for k in ("DB_BACKEND", "MYSQL_DSN", "MYSQL_HOST", "NOTIFY_WEBHOOK", "NOTIFY_ON",
              "NOTIFY_ENABLED", "NOTIFY_CONFIG", "DB_POOL_SIZE"):
        os.environ.pop(k, None)
    os.environ["AUTO_FETCH_ENABLED"] = "0"


def fresh_db(tag="a"):
    """每个用例用独立目录，避免 init_db 的目标缓存互相干扰"""
    d = os.path.join(tempfile.gettempdir(), "mdb_tests_" + tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    os.environ["MARKET_DB"] = os.path.join(d, "market.db")
    return d


# ---------------------------------------------------------------------------
def test_data_layer():
    section("1. 数据层（SQLite）")
    reset_env()
    d = fresh_db("1")
    import market_db as m
    chk("init_db", m.init_db())
    chk("backend=sqlite", m.stats().get("backend") == "sqlite")

    chk("日历写入", m.save_calendar(["2026-09-30", "2026-09-29", "2026-09-22"]) == 3)
    chk("日历读取(倒序)", m.load_calendar(3) == ["2026-09-30", "2026-09-29", "2026-09-22"], m.load_calendar(3))

    rows = [{"rank": 1, "name": "中际旭创", "code": "300308", "rise_and_fall": -0.56,
             "consecutive_boards": "无", "tier": "第一梯队", "concept_tag": "CPO",
             "anomaly_analysis": "无", "is_hot": False},
            {"rank": 2, "name": "万科A", "code": "000002", "rise_and_fall": 4.41,
             "consecutive_boards": "3连板（3天3板）", "tier": "第一梯队", "concept_tag": "物业",
             "anomaly_analysis": "地产", "is_hot": True}]
    chk("人气榜写入", m.save_hotlist("2026-09-30", rows, source="同花顺", captured_at="2026-09-30 15:30:00") == 2)
    h = m.load_hotlist("2026-09-30")
    chk("人气榜读取", h and len(h["data"]) == 2 and h["data"][0]["name"] == "中际旭创")
    chk("连板数解析", h["data"][1]["consecutive_boards"] == "3连板（3天3板）")
    m.save_hotlist("2026-09-30", rows, source="同花顺", captured_at="2026-09-30 15:30:00")
    chk("人气榜幂等(UPSERT)", len(m.load_hotlist("2026-09-30")["data"]) == 2)

    bars = [{"day": "2026-09-29", "open": 10, "high": 11, "low": 9.9, "close": 10.5, "volume": 1000},
            {"day": "2026-09-30", "open": 10.5, "high": 11.5, "low": 10.4, "close": 11.0, "volume": 1500}]
    chk("日K写入", m.save_daily_kline("000002", bars) == 2)
    k = m.load_daily_kline("000002", 10)
    chk("日K读取(升序/日期为字符串)", [x["date"] for x in k] == ["2026-09-29", "2026-09-30"], k)
    chk("前收价", m.load_prev_close("000002", "2026-09-30") == 10.5)

    chk("分时写入", m.save_minute("000002", "2026-09-30", [{"time": "09:31", "price": 10.6, "volume": 100}]) == 1)
    chk("分时读取", len(m.load_minute("000002", "2026-09-30")) == 1)

    chk("资讯写入", m.save_news("000002", [{"title": "测试公告", "date": "2026-09-30",
                                          "source": "东财", "url": "http://x/1"}]) == 1)
    chk("资讯读取", len(m.load_news("000002")) == 1)

    chk("涨停池写入", m.save_limit_up_pool("2026-09-30", {"300308": {"boards": 1, "firstSeal": "09:33",
                                                                    "sector": "通信"}}, "ZT") == 1)
    chk("涨停池读取", len(m.load_limit_up_pool("2026-09-30")) == 1)

    res = {"success": True, "target": "2026-09-30", "prevDay": "2026-09-29", "universe": 3052,
           "funnel": {"cond2": 72, "final": 57, "sealed": 37, "broken": 20, "removedByCond1": 15},
           "elapsed": 26.0, "source": "sina+em",
           "rows": [{"code": "601933", "name": "永辉超市", "closePrev": 2.55, "high": 2.81,
                     "gainHigh": 10.2, "close": 2.74, "gainClose": 7.45, "amountEst": 12.5,
                     "firstSeal": "09:33:00", "boards": 1, "sector": "百货", "poolState": "涨停"}],
           "brokenRows": [], "removedRows": []}
    chk("选股写入", m.save_screening(res) is not None)
    r = m.load_screening("2026-09-30")
    chk("选股回放", r and r["funnel"]["final"] == 57 and len(r["rows"]) == 1)

    th = {"success": True, "as_of": "2026-09-30",
          "allThemes": [{"name": "房地产", "tag": "industry", "verdict": "利好", "rank": 1,
                         "heatScore": 158.7, "popHeat": 3, "topicHeat": 155.7, "netScore": 2,
                         "bull": 1, "bear": 1, "stockTotal": 81, "stockCount": 1,
                         "stocks": [{"ticker": "000002", "name": "万科Ａ", "hotRank": 4}]}],
          "topics": [{"title": "购房贷款贴息落地", "desc": "财政部", "hot": 954642.0, "url": "http://t"}]}
    chk("题材写入", m.save_event_themes(th) >= 1)
    chk("题材回放", (m.load_event_themes("2026-09-30") or {}).get("allThemes", [{}])[0].get("name") == "房地产")
    chk("题材热度历史", len(m.theme_history("房地产")) == 1)

    m.log_fetch("hotlist", source="ths", rows=30)
    chk("日志写入", m.stats()["tables"]["fetch_log"] >= 1)
    chk("overview 20 表", len(m.overview()["tables"]) == 20)
    chk("table_dates", len(m.table_dates("daily_kline")["dates"]) >= 1)
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
def test_integrity_and_cleanup():
    section("2. 完整性校验 / 清理 / 连接池状态")
    reset_env()
    d = fresh_db("2")
    import market_db as m
    m.init_db()
    m.save_calendar(["2026-09-2%d" % i for i in range(0, 9)] + ["2026-09-30"] * 0)
    m.save_calendar(["2026-08-%02d" % i for i in range(1, 29)])
    ic = m.integrity_check("2026-09-30")
    chk("校验可运行/8 项", len(ic.get("items") or []) == 8, len(ic.get("items") or []))
    chk("空库校验应为不通过", ic["ok"] is False)
    names = [i["label"] for i in ic["items"]]
    chk("含交易日历(全表)规则", any("交易日历" in n for n in names))
    cal = [i for i in ic["items"] if "交易日历" in i["label"]][0]
    chk("交易日历按全表统计(≥28)", cal["actual"] >= 28, cal)

    m.save_hotlist("2026-09-30", [{"rank": i, "name": "x", "code": "00000%d" % i} for i in range(1, 31)])
    ic2 = m.integrity_check("2026-09-30")
    h = [i for i in ic2["items"] if i["table"] == "hotlist_snapshot"][0]
    chk("人气榜精确=30 通过", h["ok"] is True, h)

    chk("清理-单表", m.cleanup(scope="table", table="raw_payload")["deleted"] >= 0)
    chk("清理-非法表拒绝", m.cleanup(scope="table", table="sqlite_master").get("error") is not None)
    chk("清理-分时保留N天", "deleted" in m.cleanup(scope="minute", keep_days=999))

    # ---- 数据覆盖日历 ----
    cv = m.calendar_coverage(10)
    chk("覆盖日历可运行", isinstance(cv.get("days"), list) and len(cv["days"]) >= 1,
        len(cv.get("days") or []))
    chk("覆盖项含 level 分级", all("level" in d for d in cv["days"]),
        [d.get("level") for d in cv["days"][:3]])
    chk("覆盖项含分表行数", all("tables" in d for d in cv["days"]))
    chk("覆盖结果含 levels 说明", "levels" in cv and "full" in cv["levels"])

    ps = m.pool_stats()
    chk("pool_stats 对 SQLite 返回 enabled=False", ps.get("enabled") is False, ps)

    # ---- 连接池自动缩容（用假连接模拟，不依赖 MySQL）----
    import time as _t
    class _FakeConn:
        def __init__(self): self.closed = False
        def ping(self): return True
        def close(self): self.closed = True
    pool = m._Pool(lambda: _FakeConn(), 4, idle_timeout=10, min_idle=1, reap_interval=999)
    conns = [pool.acquire() for _ in range(4)]
    for c in conns:
        pool.release(c)
    chk("池中有 4 个空闲", pool.stats()["idle"] == 4, pool.stats())
    n = pool.reap_once()
    chk("未过期时不缩容", n == 0 and pool.stats()["idle"] == 4, pool.stats())
    # 把 3 个改成"很久没用"
    items = []
    while True:
        try:
            items.append(pool._idle.get_nowait())
        except Exception:
            break
    items.sort(key=lambda x: x[1])
    items[0] = (items[0][0], _t.time() - 9999)
    items[1] = (items[1][0], _t.time() - 9999)
    items[2] = (items[2][0], _t.time() - 9999)
    for it in items:
        pool._idle.put_nowait(it)
    n = pool.reap_once()
    chk("缩容释放 3 个", n == 3, n)
    chk("保留 min_idle=1", pool.stats()["idle"] == 1, pool.stats())
    chk("统计记录了缩容次数", pool.stats()["shrunk"] == 3, pool.stats())
    pool.close_all()
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
def test_dialect():
    section("3. SQL 方言生成")
    reset_env()
    import importlib
    import market_db as m
    os.environ["DB_BACKEND"] = "sqlite"
    importlib.reload(m)
    s1 = m._upsert("t", ["a", "b", "c"], ["a", "b"], ["c"])
    chk("sqlite: ON CONFLICT", "ON CONFLICT(`a`,`b`) DO UPDATE SET" in s1, s1)
    chk("sqlite: ? 占位符", s1.count("?") == 3)
    chk("sqlite: excluded.x", "`c`=excluded.`c`" in s1)
    chk("sqlite: INSERT OR REPLACE", m._replace_into("t", ["a", "b"]).startswith("INSERT OR REPLACE"))
    chk("sqlite: 空更新用 INSERT OR IGNORE", m._upsert("t", ["a"], ["a"], []).startswith("INSERT OR IGNORE"))

    os.environ["DB_BACKEND"] = "mysql"
    os.environ["MYSQL_DSN"] = "mysql://root:pwd@127.0.0.1:3306/stock"
    importlib.reload(m)
    m2 = m._upsert("t", ["a", "b", "c"], ["a", "b"], ["c"])
    chk("mysql: ON DUPLICATE KEY UPDATE", "ON DUPLICATE KEY UPDATE" in m2, m2)
    chk("mysql: VALUES()", "`c`=VALUES(`c`)" in m2)
    chk("mysql: REPLACE INTO", m._replace_into("t", ["a", "b"]).startswith("REPLACE INTO"))
    chk("mysql: INSERT IGNORE", m._upsert("t", ["a"], ["a"], []).startswith("INSERT IGNORE"))
    chk("mysql: DSN 解析", m._mysql_cfg()["host"] == "127.0.0.1" and m._mysql_cfg()["database"] == "stock")
    chk("mysql: rank 加反引号", "`rank`=VALUES(`rank`)" in
        m._upsert("hotlist_snapshot", m._HOT_COLS, ["trade_date", "captured_at", "stock_code"], m._HOT_UPD))
    chk("mysql: 日K COALESCE(VALUES)", "COALESCE(VALUES(`prev_close`), `prev_close`)" in m._kline_upsert_sql())
    chk("mysql: pool_stats 结构", "size" in m.pool_stats() or "error" in m.pool_stats(), m.pool_stats())

    # 值归一化
    import datetime as dt
    import decimal as dec
    chk("_norm date -> str", m._norm(dt.date(2026, 9, 30)) == "2026-09-30")
    chk("_norm datetime -> str", m._norm(dt.datetime(2026, 9, 30, 15, 30, 0)) == "2026-09-30 15:30:00")
    chk("_norm Decimal -> float", m._norm(dec.Decimal("1.25")) == 1.25)
    chk("_norm bytes -> str", m._norm("中文".encode("utf-8")) == "中文")
    reset_env()


# ---------------------------------------------------------------------------
def test_notifier():
    section("4. 通知模块")
    reset_env()
    import importlib
    import notifier
    importlib.reload(notifier)
    chk("未配置 -> 无通道", notifier.channels() == [], notifier.channels())
    chk("未配置 -> should_send=False", notifier.should_send(True) is False)
    st = notifier.status()
    chk("status 字段完整", all(k in st for k in ("enabled", "notify_on", "channels", "config_path")))

    os.environ["NOTIFY_WEBHOOK"] = "http://127.0.0.1:9/dead"
    importlib.reload(notifier)
    chk("配置后 -> 通道=[webhook]", notifier.channels() == ["webhook"])
    r = notifier.send("t", "b")
    chk("不可达地址不抛异常", isinstance(r, list) and r[0]["ok"] is False, r)

    os.environ["NOTIFY_ON"] = "issues_only"
    importlib.reload(notifier)
    chk("issues_only: 正常->不发", notifier.should_send(True) is False)
    chk("issues_only: 异常->发", notifier.should_send(False) is True)

    title, text = notifier.format_summary(
        job={"target": "2026-09-30", "ok": True, "elapsed": 68.5,
             "steps": {"calendar": "days=400", "hotlist": "rows=30", "integrity": "ok", "notify": "sent"}},
        integrity={"ok": True, "trade_date": "2026-09-30", "issues": [],
                   "items": [{"label": "人气榜应为 30 条", "mode": "exact", "expected": 30,
                              "actual": 30, "ok": True}]},
        stats={"db_path": "x", "db_size_mb": 1.0, "tables": {"a": 1}})
    chk("汇总含交易日", "2026-09-30" in text)
    chk("汇总含完整性结论", "完整性校验" in text)
    chk("汇总含免责声明", "不构成投资建议" in text)
    chk("汇总过滤 integrity/notify 步骤", "integrity：" not in text)
    reset_env()


# ---------------------------------------------------------------------------
def test_scheduler():
    section("5. 定时任务逻辑")
    reset_env()
    d = fresh_db("2")
    import market_db as m
    m.init_db()
    try:
        import importlib
        import scheduler
        importlib.reload(scheduler)
    except Exception as e:
        chk("scheduler 可导入", False, e)
        shutil.rmtree(d, ignore_errors=True)
        return
    os.environ["AUTO_FETCH_ENABLED"] = "1"      # 本用例需开启调度
    scheduler.enabled = lambda: True
    chk("schedules() 返回列表", isinstance(scheduler.schedules(), list) and len(scheduler.schedules()) >= 1)
    names = [s["name"] for s in scheduler.schedules()]
    chk("默认含 morning/close", "morning" in names and "close" in names, names)
    chk("morning 为轻量模式", any(s["name"] == "morning" and s["mode"] == "light" for s in scheduler.schedules()))
    chk("close 为完整模式", any(s["name"] == "close" and s["mode"] == "full" for s in scheduler.schedules()))

    cal = ["2026-09-30", "2026-09-29"]
    import server
    server._trading_calendar = lambda n=60: cal[:n]
    state = {"done": set()}
    m.has_fetch_log = lambda t, d=None, s="ok": ("%s" % t) in state["done"]
    calls = []
    scheduler.run_job = lambda name, mode, target=None, **kw: calls.append((name, mode)) or {"ok": True}

    def T(label, now, expect):
        scheduler._LAST_ATTEMPT.clear()
        calls.clear()
        r = scheduler.tick(now)
        ok = (len(calls) == expect)
        chk(label, ok, "触发 %d 次(期望 %d) %s" % (len(calls), expect, calls))
        return ok

    state["done"] = set()
    T("非交易日不触发", datetime(2026, 10, 3, 16, 0), 0)
    T("早于 11:35 不触发", datetime(2026, 9, 30, 9, 0), 0)
    T("11:35 只触发 morning", datetime(2026, 9, 30, 11, 35), 1)
    state["done"] = {"job:morning"}
    T("15:30 触发 close", datetime(2026, 9, 30, 15, 30), 1)
    state["done"] = {"job:morning", "job:close"}
    T("两个都跑过则不再触发", datetime(2026, 9, 30, 20, 0), 0)
    reset_env()
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_data_layer()
    test_integrity_and_cleanup()
    test_dialect()
    test_notifier()
    test_scheduler()
    print("\n" + "=" * 60)
    print("  汇总：%d 通过 / %d 失败 / 共 %d" % (len(PASS), len(FAIL), len(PASS) + len(FAIL)))
    if FAIL:
        print("  失败项：")
        for f in FAIL:
            print("    - " + f)
    print("=" * 60)
    sys.exit(1 if FAIL else 0)
