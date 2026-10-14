# -*- coding: utf-8 -*-
r"""盘中实时快照 —— 用「此刻的现价 + 已发生的最高价」算当天数据

为什么盘中就能算封板率：
    · 入选池 = 昨日未触及涨停价 且 今日盘中最高涨幅 > 9%   ← 最高价盘中已经存在
    · 封住   = 今日收盘 >= 今日涨停价                      ← 盘中用「现价」代替收盘价
    所以盘中给出的是「当前封板率」：此刻还封在涨停价的 / 冲高超过 9% 的。
    收盘后 15:30 的正式统计会覆盖它（src=intraday 视为"未定稿"，会被重算）。

数据源：新浪批量行情（一次 150 只，全市场约 40 次请求 / 4~6 秒）
    每行：名称,今开,昨收,现价,最高,最低,...,成交量,成交额,...,日期,时间
    · 日期字段很关键：长期停牌股的行情日期会停留在停牌前那天，据此剔除，避免误算成"平盘"
    不依赖东方财富接口，所以不受它偶发拒连影响。

一次抓取同时得到（口径与原系统一致）：
    · 涨跌家数   = 沪深京全部 A 股（现价 vs 昨收，剔除停牌/非当日行情）
                   优先用东财实时列表（与同花顺完全一致），东财不可用时用新浪兜底
    · 两市成交额 = 上证综指 + 深证综指 的成交额（取不到则用全市场个股成交额之和）
    · 盘中封板率 = 沪深主板非ST
"""
import time
from concurrent.futures import ThreadPoolExecutor

import requests

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://finance.sina.com.cn/",
}
_BATCH = 150
_WORKERS = 6
_MAIN = ("600", "601", "603", "605", "000", "001", "002", "003")
_SH_IDX = "sh000001"      # 上证综指（覆盖沪市全部）
_SZ_IDX = "sz399106"      # 深证综指（覆盖深市全部）


def sina_symbol(code):
    """股票代码 -> 新浪符号（sh/sz/bj）"""
    code = str(code or "").strip()
    if not code:
        return ""
    if code.startswith(("92", "43", "83", "87", "88", "4", "8")):
        return "bj" + code
    if code.startswith(("6", "9")):
        return "sh" + code
    return "sz" + code


def _parse_line(line):
    """解析一行 hq_str_xxx="..." -> (符号, 字段列表)"""
    if "=" not in line:
        return None, None
    key, _, payload = line.partition("=")
    key = key.strip().replace("var hq_str_", "")
    parts = payload.strip().strip(";").strip('"').split(",")
    if len(parts) < 32:
        return key, None
    return key, parts


def _fetch_batch(symbols, timeout=15):
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    for _ in range(2):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=timeout)
            r.encoding = "gbk"
            return r.text
        except Exception:
            time.sleep(0.4)
    return ""


def fetch_quotes(codes, batch=_BATCH, workers=_WORKERS):
    """按股票代码批量抓实时行情 -> {code: {...}}（内部自动加 sh/sz/bj 前缀）"""
    codes = [str(c).strip() for c in (codes or []) if str(c).strip()]
    if not codes:
        return {}
    sym_map = {sina_symbol(c): c for c in codes}
    return fetch_by_symbols(list(sym_map.keys()), sym_map, batch, workers)


def fetch_by_symbols(symbols, sym_map=None, batch=_BATCH, workers=_WORKERS):
    """按新浪符号抓（指数也用这个，如 sh000001 / sz399106）"""
    symbols = [s for s in (symbols or []) if s]
    if not symbols:
        return {}
    sym_map = sym_map or {s: s for s in symbols}
    chunks = [symbols[i:i + batch] for i in range(0, len(symbols), batch)]
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for txt in ex.map(_fetch_batch, chunks):
            for line in txt.splitlines():
                key, p = _parse_line(line)
                if not p:
                    continue
                code = sym_map.get(key)
                if not code:
                    continue

                def _f(i):
                    try:
                        return float(p[i])
                    except Exception:
                        return None
                out[code] = {
                    "name": p[0], "open": _f(1), "prev_close": _f(2), "price": _f(3),
                    "high": _f(4), "low": _f(5), "amount": _f(9),
                    "date": p[30], "clock": p[31],
                    "suspended": (not _f(3)) or _f(3) <= 0,
                }
    return out


def _limit_price(prev_close):
    """前收盘 -> 涨停价（×1.1 四舍五入到分，整数运算避免浮点误差）"""
    return ((int(round(prev_close * 1000)) * 11 + 50) // 100) / 100.0


def _breadth_from_em(trade_date):
    """东财实时列表（与同花顺完全一致）；失败返回 None"""
    try:
        import market_breadth as mb
        return mb.fetch_realtime(trade_date)
    except Exception:
        return None


def snapshot(with_pool=True, use_em=True):
    """抓一次全市场实时快照并算好当天数据

    返回 dict：date/quote_time/up/down/flat/susp/total/breadth_src
              amount_yi/sh_yi/sz_yi/final/sealed/score/pool_days/elapsed
    """
    import market_db as m

    rows = m._read(lambda c: c.execute("SELECT `code`,`name`,`is_st` FROM `stock`").fetchall(), [])
    codes = [r["code"] for r in rows]
    if not codes:
        return None
    st = set()
    for r in rows:
        nm = (r["name"] or "").upper().replace(" ", "")
        if r["is_st"] or ("ST" in nm):
            st.add(str(r["code"]))
    name_map = {str(r["code"]): (r["name"] or "") for r in rows}

    t0 = time.time()
    quotes = fetch_quotes(codes)
    idx = fetch_by_symbols([_SH_IDX, _SZ_IDX], {_SH_IDX: _SH_IDX, _SZ_IDX: _SZ_IDX})
    elapsed = round(time.time() - t0, 1)
    if not quotes:
        return None
    sh, sz = idx.get(_SH_IDX), idx.get(_SZ_IDX)

    # 基准行情日期：取两个指数的时间（最权威），否则取多数股票
    ref_date = (sh or {}).get("date") or (sz or {}).get("date")
    if not ref_date:
        cnt = {}
        for x in quotes.values():
            cnt[x["date"]] = cnt.get(x["date"], 0) + 1
        ref_date = max(cnt.items(), key=lambda kv: kv[1])[0] if cnt else None
    ref_clock = (sh or {}).get("clock") or ""

    # ① 涨跌家数（新浪兜底口径：只统计"行情日期=当日"的股票，停牌/长期停牌剔除）
    up = down = flat = susp = 0
    amount_sum = 0.0
    for code, q in quotes.items():
        pc, pr = q.get("prev_close"), q.get("price")
        if q.get("suspended") or not pc or pc <= 0 or (ref_date and q.get("date") != ref_date):
            susp += 1
            continue
        amount_sum += q.get("amount") or 0.0
        if pr > pc:
            up += 1
        elif pr < pc:
            down += 1
        else:
            flat += 1

    out = {"date": ref_date, "quote_date": ref_date, "quote_time": ref_clock,
           "up": up, "down": down, "flat": flat, "susp": susp,
           "total": up + down + flat + susp, "breadth_src": "sina_rt",
           "amount_yi": None, "sh_yi": None, "sz_yi": None,
           "final": 0, "sealed": 0, "score": None, "elapsed": elapsed}

    # ② 涨跌家数优先用东财（与同花顺完全一致）
    if use_em:
        em = _breadth_from_em(ref_date)
        if em and (em.get("up") or em.get("down")):
            out.update({"up": em["up"], "down": em["down"], "flat": em.get("flat") or 0,
                        "total": em.get("total") or out["total"],
                        "susp": em.get("suspended") or out["susp"],
                        "breadth_src": "em_clist"})

    # ③ 两市成交额（优先两个指数的官方成交额）
    sh_yi = (sh["amount"] / 1e8) if (sh and sh.get("amount")) else None
    sz_yi = (sz["amount"] / 1e8) if (sz and sz.get("amount")) else None
    if sh_yi and sz_yi:
        out["sh_yi"], out["sz_yi"] = round(sh_yi, 2), round(sz_yi, 2)
        out["amount_yi"] = round(sh_yi + sz_yi, 2)
    else:
        out["amount_yi"] = round(amount_sum / 1e8, 2)

    # ④ 盘中封板率（沪深主板非ST）——基准日取"行情日期之前的最近两个交易日"
    if with_pool and ref_date:
        days = m._read(lambda c, d=ref_date: [r[0] for r in c.execute(
            "SELECT DISTINCT `trade_date` FROM `daily_kline` WHERE `trade_date` < ? "
            "ORDER BY `trade_date` DESC LIMIT 2", (d,)).fetchall()], [])
        if len(days) >= 2:
            d1, d2 = days[0], days[1]
            b1 = {r["stock_code"]: (r["high"], r["close"]) for r in
                  m._read(lambda c, d=d1: c.execute(
                      "SELECT `stock_code`,`high`,`close` FROM `daily_kline` "
                      "WHERE `trade_date`=? AND substr(`stock_code`,1,3) IN "
                      "('600','601','603','605','000','001','002','003')", (d,)).fetchall(), [])}
            b2 = {r["stock_code"]: r["close"] for r in
                  m._read(lambda c, d=d2: c.execute(
                      "SELECT `stock_code`,`close` FROM `daily_kline` WHERE `trade_date`=?",
                      (d,)).fetchall(), [])}
            final = sealed = 0
            for code, qq in quotes.items():
                if code in st or not code.startswith(_MAIN):
                    continue
                if ref_date and qq.get("date") != ref_date:
                    continue                                   # 当天没行情的票不算
                t1, c2 = b1.get(code), b2.get(code)
                if not t1 or c2 is None:
                    continue
                h1, c1 = t1
                if not c1 or not c2 or not h1 or not qq.get("high"):
                    continue
                if h1 >= _limit_price(c2) - 0.001:              # 昨日已触及涨停 -> 剔除
                    continue
                if (qq["high"] - c1) / c1 > 0.09:               # 今日(盘中)最高涨幅 > 9%
                    final += 1
                    if (qq.get("price") or 0) >= _limit_price(c1) - 0.001:
                        sealed += 1
            out["final"], out["sealed"] = final, sealed
            out["score"] = round(sealed / final * 100, 1) if final else None
            out["pool_days"] = [d1, d2]
    return out


def save(snap, force=False):
    """把快照写入 3 张表（涨跌家数 / 成交额 / 封板率）

    只有「行情日期 == 今天」才写入（非交易时段行情日期停在上一个交易日，
    写进去会把正式数据降级成盘中数据）；force=True 可强制。
    """
    import datetime as _dt
    import market_db as m

    if not snap:
        return None
    today = _dt.date.today().isoformat()
    if snap.get("date") != today and not force:
        return {"skipped": True, "reason": "行情快照日期 %s != 今天 %s（非交易时段）"
                                           % (snap.get("date"), today)}
    d = snap["date"]
    m.save_market_breadth({"date": d, "up": snap["up"], "down": snap["down"],
                           "flat": snap["flat"], "total": snap["total"],
                           "suspended": snap["susp"]}, source=snap.get("breadth_src") or "sina_rt")
    if snap.get("amount_yi"):
        m.save_turnover_batch([{"date": d, "sh": snap.get("sh_yi"), "sz": snap.get("sz_yi"),
                                "amount": snap["amount_yi"]}], source="sina_rt")
    if snap.get("final"):
        m.save_seal_intraday({"date": d, "up": snap["up"], "down": snap["down"],
                              "flat": snap["flat"], "final": snap["final"],
                              "sealed": snap["sealed"], "score": snap["score"]})
    return snap


def run(force=False):
    """抓一次 + 落库（供定时任务 / 手动按钮调用）"""
    snap = snapshot()
    if not snap:
        return None
    save(snap, force=force)
    return snap
