# -*- coding: utf-8 -*-
r"""构建 market_day_stats（情绪评分的输入层）+ index_daily（沪深300 / 上证）

口径（固定，随模型版本记录）：
  股票池 = 当日有日K且 prev_close>0 的全部 A 股（含 ST/创业板/科创板/北交所）
  涨停/跌停价 = 前收盘 × (1 ± 幅度)，四舍五入到分（整数运算）
    幅度：主板 10%，创业板/科创板 20%，北交所 30%，主板 ST 5%
  涨停 = 收盘 ≥ 涨停价；跌停 = 收盘 ≤ 跌停价；
  炸板 = 盘中最高 ≥ 涨停价 且 收盘 < 涨停价
  连板高度 = 连续涨停天数的最大值（按交易日连续）
  晋级率 = 今日涨停中「昨日也涨停」的比例
用法：python tools/build_day_stats.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import market_db as m          # noqa: E402
import screener               # noqa: E402

INDEXES = {"000300": "sh000300", "000001": "sh000001"}   # 沪深300 / 上证


def r2(v):
    return ((int(round(v * 1000)) + 5) // 10) / 100.0 if False else int(round(v * 1000)) / 1000.0


def round2(x):
    """四舍五入到分（整数运算，避免浮点误差）"""
    return ((int(round(x * 1000)) * 1 + 0) // 1) / 1000.0 if False else (int(round(x * 100)) / 100.0)


def limit_mult(code, is_st):
    if code.startswith(("300", "301", "688", "689")):
        return 1.20
    if code.startswith(("4", "8", "92")):
        return 1.30
    if is_st:
        return 1.05
    return 1.10


def build_index_daily(datalen=800):
    saved = 0
    for code, sym in INDEXES.items():
        bars = screener.sina_kline(sym, datalen)
        if not bars:
            print("  指数 %s 抓取失败" % sym); continue
        rows = []
        prev = None
        for b in bars:
            c = float(b["close"]) if b.get("close") else None
            if c is None:
                continue
            pct = ((c - prev) / prev * 100) if prev else None
            rows.append({"date": b["day"], "close": c, "pct": pct})
            prev = c
        def _f(conn):
            cur = conn.cursor()
            sql = m._upsert("index_daily", ["trade_date", "code", "close", "pct"],
                            ["trade_date", "code"], ["close", "pct"])
            n = 0
            for r in rows:
                if r["pct"] is None:
                    continue
                cur.execute(sql, (r["date"], code, r["close"], round(r["pct"], 4)))
                n += 1
            return n
        saved += (m._write(_f) or 0)
        print("  指数 %s: %d 条" % (sym, len(rows)))
    return saved


def build_day_stats():
    # 完整交易日（>=2000 只）
    dates = m._read(lambda c: [x[0] for x in c.execute(
        "SELECT trade_date FROM daily_kline WHERE change_pct IS NOT NULL "
        "GROUP BY trade_date HAVING COUNT(*)>=2000 ORDER BY trade_date").fetchall()], [])
    if not dates:
        print("没有完整交易日"); return 0
    tmap = m.market_turnover_map()
    prev_up = set()
    streaks = {}
    out = []
    t0 = time.time()
    for i, d in enumerate(dates):
        rows = m._read(lambda c, d=d: c.execute(
            "SELECT k.stock_code, k.high, k.close, k.prev_close, k.change_pct, "
            "       COALESCE(s.is_st,0) AS is_st "
            "FROM daily_kline k LEFT JOIN stock s ON s.code = k.stock_code "
            "WHERE k.trade_date=? AND k.prev_close>0 AND k.close IS NOT NULL "
            "  AND k.high IS NOT NULL", (d,)).fetchall(), [])
        if not rows:
            continue
        up = down = flat = 0
        up5 = down5 = 0
        lu = ld = br = 0
        tot = 0.0
        upcodes = set()
        for r in rows:
            code = r["stock_code"]
            c = r["close"]; pc = r["prev_close"]; hi = r["high"]; ch = r["change_pct"]
            mult = limit_mult(code, r["is_st"])
            lim_up = round2(pc * mult)
            lim_dn = round2(pc * (2 - mult))
            if ch is not None:
                if ch > 0: up += 1
                elif ch < 0: down += 1
                else: flat += 1
                if ch > 5: up5 += 1
                elif ch < -5: down5 += 1
                tot += ch
            if c >= lim_up - 0.001:
                lu += 1; upcodes.add(code)
            elif c <= lim_dn + 0.001:
                ld += 1
            if hi >= lim_up - 0.001 and c < lim_up - 0.001:
                br += 1
        n = up + down + flat
        new_streaks = {c: streaks.get(c, 0) + 1 for c in upcodes}
        height = max(new_streaks.values()) if new_streaks else 0
        promote = (len(upcodes & prev_up) / len(prev_up) * 100) if prev_up else None
        out.append({"date": d, "universe": len(rows), "up": up, "down": down, "flat": flat,
                    "up5": up5, "down5": down5, "lu": lu, "ld": ld, "br": br,
                    "height": height, "promote": round(promote, 2) if promote is not None else None,
                    "ew": round(tot / n, 4) if n else None,
                    "amount": tmap.get(d)})
        streaks, prev_up = new_streaks, upcodes
        if (i + 1) % 100 == 0:
            print("  进度 %d/%d" % (i + 1, len(dates)), flush=True)

    def _w(conn):
        cur = conn.cursor()
        sql = m._upsert("market_day_stats",
                        ["trade_date", "universe", "up_count", "down_count", "flat_count",
                         "up5_count", "down5_count", "limit_up", "limit_down", "broken",
                         "limit_height", "promote_rate", "ew_return", "amount",
                         "source", "computed_at"],
                        ["trade_date"],
                        ["universe", "up_count", "down_count", "flat_count", "up5_count",
                         "down5_count", "limit_up", "limit_down", "broken", "limit_height",
                         "promote_rate", "ew_return", "amount", "source", "computed_at"])
        ts = m.now_str()
        cnt = 0
        for r in out:
            cur.execute(sql, (r["date"], r["universe"], r["up"], r["down"], r["flat"],
                              r["up5"], r["down5"], r["lu"], r["ld"], r["br"],
                              r["height"], r["promote"], r["ew"], r["amount"], "kline", ts))
            cnt += 1
        return cnt
    n = m._write(_w) or 0
    print("market_day_stats 写入 %d 天，用时 %.0fs" % (n, time.time() - t0))
    return n


if __name__ == "__main__":
    m.init_db()
    print("① 抓指数日线…")
    build_index_daily()
    print("② 构建每日全市场统计…")
    build_day_stats()
    row = m._read(lambda c: c.execute(
        "SELECT trade_date, universe, up_count, down_count, limit_up, limit_down, broken, "
        "limit_height, promote_rate, ew_return, amount FROM market_day_stats "
        "ORDER BY trade_date DESC LIMIT 3").fetchall(), [])
    print("\n最近 3 天:")
    for r in row:
        print("  %s 家数%s 涨%s 跌%s 涨停%s 跌停%s 炸板%s 连板%s 晋级%s%% 等权%.2f%% 成交%.0f亿"
              % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                 r[8] if r[8] is not None else "-", r[9] or 0, r[10] or 0))
