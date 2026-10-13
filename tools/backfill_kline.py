# -*- coding: utf-8 -*-
"""一次性补齐全市场日K（近 N 个交易日）—— 供「行情评分走势」的历史数据

每只股票只请求一次（新浪日K，datalen=N），把返回的多天一次性入库。
用法：python tools/backfill_kline.py [datalen]
"""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
if sys.stdout is None:
    sys.stdout = open(os.path.join(ROOT, "backfill_kline.log"), "w", encoding="utf-8", buffering=1)

from concurrent.futures import ThreadPoolExecutor
import screener
import market_db as m


def main(n=30):
    m.init_db()
    print("开始补齐日K，datalen=%d" % n, flush=True)
    uni = screener.get_mainboard_universe()
    print("主板股票数: %d" % len(uni), flush=True)

    done = [0, 0]      # [成功只数, 已处理]

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
        if done[1] % 300 == 0:
            print("  进度 %d/%d  成功=%d" % (done[1], len(uni), done[0]), flush=True)
        return r

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, uni))
    print("完成：成功 %d/%d 只，用时 %.0fs" % (done[0], len(uni), time.time() - t0), flush=True)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    main(n)
