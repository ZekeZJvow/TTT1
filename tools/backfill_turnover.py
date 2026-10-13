# -*- coding: utf-8 -*-
r"""一次性补齐「两市成交额」历史 —— 供「行情评分走势」的成交额总计 / 较上一日

用法：
    set MARKET_DB=<项目>\dist\data\market.db
    python tools/backfill_turnover.py [天数]

默认 120 天。只请求 2 个指数日K接口，秒级完成；重复运行按日期覆盖，幂等。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
if sys.stdout is None:
    sys.stdout = open(os.path.join(ROOT, "backfill_turnover.log"), "w",
                      encoding="utf-8", buffering=1)

import market_db as m
import market_turnover as mt


def main(n=120):
    m.init_db()
    print("开始补齐两市成交额，天数=%d" % n, flush=True)
    rows = mt.fetch_history(n)
    if not rows:
        print("抓取失败：接口无返回", flush=True)
        return 1
    saved = mt.save_rows(rows, source="em_index")
    print("抓到 %d 天（%s ~ %s），写入 %d 条"
          % (len(rows), rows[0]["date"], rows[-1]["date"], saved), flush=True)
    for r in rows[-5:]:
        print("  %s  沪%.0f亿 + 深%.0f亿 = %.2f万亿"
              % (r["date"], r["sh"] or 0, r["sz"] or 0, r["amount"] / 10000), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 120))
