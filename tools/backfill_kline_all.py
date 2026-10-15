# -*- coding: utf-8 -*-
r"""一次性补齐「全市场日K」（沪深京全部 A 股）—— 让「行情评分走势」的涨跌家数
按同花顺口径（沪深京全部 A 股）统计历史。

用法：
    set MARKET_DB=<项目>\dist\data\market.db
    python tools/backfill_kline_all.py [datalen]

默认 datalen=45（约 45 个交易日）。每只股票只请求一次新浪日K，一次入库多天。
全市场约 5900 只，预计 3~5 分钟；重复运行按 (code, date) 覆盖，幂等。
注意：本脚本只影响「涨跌家数」口径；「行情评分」始终只认沪深主板。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
if sys.stdout is None:
    sys.stdout = open(os.path.join(ROOT, "backfill_kline_all.log"), "w",
                      encoding="utf-8", buffering=1)

from concurrent.futures import ThreadPoolExecutor
import screener
import market_db as m
import market_breadth as mb


def _universe():
    """股票列表：优先用本地 stock 表（离线可用），再退回东财接口"""
    import realtime_snapshot as rs
    rows = m._read(lambda c: c.execute("SELECT `code`,`name` FROM `stock`").fetchall(), [])
    out = []
    for r in rows:
        sym = rs.sina_symbol(r["code"])
        if sym:
            out.append((sym, r["code"], r["name"]))
    if out:
        print("  股票列表来源：本地 stock 表（%d 只）" % len(out), flush=True)
        return out
    print("  本地无列表，改用东财接口…", flush=True)
    return mb.a_share_symbols()


def main(n=45):
    m.init_db()
    print("开始补齐全市场日K，datalen=%d" % n, flush=True)
    uni = _universe()
    print("全市场股票数: %d" % len(uni), flush=True)
    if not uni:
        print("获取股票列表失败", flush=True)
        return 1

    done = [0, 0]

    def one(item):
        sym, code, name = item
        r = 0
        try:
            k = screener.sina_kline(sym, n)
            if k:
                r = m.save_daily_kline(code, k)
        except Exception:
            r = 0
        done[1] += 1
        if r:
            done[0] += 1
        if done[1] % 500 == 0:
            print("  进度 %d/%d  成功=%d" % (done[1], len(uni), done[0]), flush=True)
        return r

    import time
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, uni))
    print("完成：成功 %d/%d 只，用时 %.0fs" % (done[0], len(uni), time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 45))
