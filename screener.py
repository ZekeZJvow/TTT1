# -*- coding: utf-8 -*-
"""
动态选股引擎（参数化）

输入：目标日期 D
流程：推导前一交易日 -> 全市场抓取日K -> 逐条推算条件 -> 语义交叉验证 -> 结构化输出

三条选股条件：
  条件1  前一交易日(D-1)首次涨停时间取反  = D-1 全天未触及涨停价
  条件2  (D最高价 - D-1收盘价) / D-1收盘价 > 0.09
  条件3  沪深主板 且 非ST
"""

import json
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------- 常量 ----------------

_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
}
_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

_SESS = requests.Session()
_SESS.headers.update(_SINA_HEADERS)
_SESS.mount("https://", HTTPAdapter(pool_connections=64, pool_maxsize=64))
_SESS.mount("http://", HTTPAdapter(pool_connections=64, pool_maxsize=64))

SH_MAIN = ("600", "601", "603", "605")
SZ_MAIN = ("000", "001", "002", "003")

WORKERS = 24
THRESHOLD = 0.09
PRICE_EPS = 0.005

# ---------------- 基础工具 ----------------


def round2(x):
    """四舍五入到分，避免浮点误差"""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt_hhmmss(v):
    """92500 -> 09:25:00"""
    try:
        s = "%06d" % int(v)
        return "%s:%s:%s" % (s[0:2], s[2:4], s[4:6])
    except Exception:
        return ""


def is_mainboard(symbol):
    """symbol 形如 sh600000 / sz000001"""
    if symbol.startswith("sh"):
        return symbol[2:5] in SH_MAIN
    if symbol.startswith("sz"):
        return symbol[2:5] in SZ_MAIN
    return False


def is_st(name):
    n = name or ""
    return ("ST" in n.upper().replace(" ", "")) or ("退" in n)


# ---------------- 新浪数据源 ----------------


def _sina_jsonp(url, retries=3):
    last = None
    for i in range(retries):
        try:
            t = _SESS.get(url, timeout=10).text
            a = t.find("(")
            b = t.rfind(")")
            if a < 0 or b <= a:
                return []
            return json.loads(t[a + 1:b])
        except Exception as e:
            last = e
            time.sleep(0.25 * (i + 1))
    return []


def sina_kline(symbol, datalen=10):
    """日K：返回 [{day, open, high, low, close, volume}, ...]（按日期升序）"""
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData"
           "?symbol=%s&scale=240&ma=no&datalen=%d" % (symbol, datalen))
    return _sina_jsonp(url)


def get_trading_days(datalen=200):
    """用上证指数日K当交易日历，天然覆盖节假日"""
    k = sina_kline("sh000001", datalen)
    return [x["day"] for x in k if x.get("day")]


def get_mainboard_universe(progress=None):
    """沪深主板 非ST 全量列表 -> [(symbol, code, name), ...]"""
    out = []
    seen = set()
    for node in ("sh_a", "sz_a"):
        page = 1
        while page <= 80:
            url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   "Market_Center.getHQNodeData?page=%d&num=100&sort=symbol&asc=1&node=%s"
                   % (page, node))
            try:
                rows = _SESS.get(url, timeout=15).json()
            except Exception:
                break
            if not rows:
                break
            for it in rows:
                sym = it.get("symbol", "")
                name = it.get("name", "")
                code = it.get("code", "")
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                if is_mainboard(sym) and not is_st(name):
                    out.append((sym, code, name))
            if progress:
                progress(len(out))
            page += 1
    out.sort(key=lambda x: x[1])
    return out


# ---------------- 东方财富涨停/炸板池（用于语义校验与信息补全） ----------------


def em_pool(kind, ymd):
    """kind: 'ZT' (涨停池) / 'ZB' (炸板池)。ymd: '20260930'"""
    api = "getTopicZTPool" if kind == "ZT" else "getTopicZBPool"
    url = ("https://push2ex.eastmoney.com/%s?ut=7eea3edcaed734bea9cbfc24409ed989"
           "&dpt=wz.ztzt&Pageindex=0&pagesize=600&sort=fbt%%3Aasc&date=%s" % (api, ymd))
    try:
        j = requests.get(url, headers=_EM_HEADERS, timeout=15, verify=False).json()
    except Exception:
        return {}, "request failed"
    pool = ((j.get("data") or {}).get("pool")) or []
    m = {}
    for it in pool:
        c = str(it.get("c", "")).zfill(6)
        m[c] = {
            "firstSeal": fmt_hhmmss(it.get("fbt")),
            "lastSeal": fmt_hhmmss(it.get("lbt")),
            "breakCount": it.get("zbc"),
            "boards": it.get("lbc"),
            "sector": it.get("hybk"),
            "turnover": it.get("hs"),
            "amount": it.get("amount"),
        }
    return m, None


_SINA_INDUSTRY = None


def _sina_industry_map():
    """构建 code -> 新浪行业 全量映射（进程内缓存，48 个板块一次拉取）"""
    global _SINA_INDUSTRY
    if _SINA_INDUSTRY is not None:
        return _SINA_INDUSTRY

    base = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    m = {}
    try:
        nodes = _SESS.get(base + "Market_Center.getHQNodes", timeout=15).json()
    except Exception:
        _SINA_INDUSTRY = m
        return m

    def find_ind_list(x):
        if isinstance(x, list):
            if x and isinstance(x[0], list) and len(x[0]) >= 3 and x[0][0] == "玻璃行业":
                return x
            for y in x:
                got = find_ind_list(y)
                if got:
                    return got
        return None

    blocks = find_ind_list(nodes)
    if not blocks:
        _SINA_INDUSTRY = m
        return m

    def one(item):
        name, node = item[0], item[2]
        out = []
        for page in range(1, 4):
            url = (base + "Market_Center.getHQNodeData?page=%d&num=100&sort=symbol&asc=1&node=%s"
                   % (page, node))
            try:
                rows = _SESS.get(url, timeout=15).json()
            except Exception:
                break
            if not rows:
                break
            for r in rows:
                sym = r.get("symbol", "")
                if len(sym) >= 6:
                    out.append((sym[-6:], name))
        return out

    with ThreadPoolExecutor(max_workers=12) as ex:
        for pairs in ex.map(one, blocks):
            for code, name in pairs:
                m.setdefault(code, name)

    _SINA_INDUSTRY = m
    return m


def fill_sectors(rows):
    """给缺行业的行补行业（新浪行业板块全量映射）"""
    need = [r for r in rows if not (r.get("sector") or "").strip()]
    if not need:
        return 0
    m = _sina_industry_map()
    got = 0
    for r in need:
        sec = m.get(r["code"], "")
        if sec:
            r["sector"] = sec
            got += 1
    return got


# ---------------- 单只股票推算 ----------------


def evaluate(k, d2, d1, d):
    """按三条条件推算单只股票。返回 dict 或 None（数据不足/停牌）"""
    if not k:
        return None
    m = {}
    for x in k:
        m[x.get("day")] = x
    if d not in m or d1 not in m or d2 not in m:
        return None
    try:
        r2, r1, r0 = m[d2], m[d1], m[d]
        c2 = float(r2["close"])
        c1 = float(r1["close"])
        h1 = float(r1["high"])
        o0 = float(r0["open"])
        h0 = float(r0["high"])
        l0 = float(r0["low"])
        c0 = float(r0["close"])
        v0 = float(r0["volume"])
        o1 = float(r1["open"])
        l1 = float(r1["low"])
        v1 = float(r1["volume"])
    except Exception:
        return None
    if c1 <= 0 or c2 <= 0:
        return None

    limit1 = round2(c2 * 1.1)          # D-1 涨停价
    limit0 = round2(c1 * 1.1)          # D 涨停价
    touched_prev = h1 >= limit1 - PRICE_EPS
    sealed = c0 >= limit0 - PRICE_EPS
    broke = (not sealed) and (h0 >= limit0 - PRICE_EPS)

    gain_high = (h0 - c1) / c1
    gain_close = (c0 - c1) / c1
    amplitude = (h0 - l0) / c1
    amount_est = v0 * ((o0 + h0 + l0 + c0) / 4.0)

    return {
        "code": None,
        "name": None,
        "closeD2": c2,
        "closePrev": c1,
        "limitPrev": limit1,
        "high": h0,
        "low": l0,
        "open": o0,
        "close": c0,
        "limit": limit0,
        "gainHigh": round(gain_high * 100, 2),
        "gainClose": round(gain_close * 100, 2),
        "amplitude": round(amplitude * 100, 2),
        "amountEst": amount_est,
        "volume": v0,
        "touchedPrev": touched_prev,
        "sealed": sealed,
        "broke": broke,
        "cond2": gain_high > THRESHOLD,
        "cond1": not touched_prev,
        "prevGain": round((c1 - c2) / c2 * 100, 2),
    }


def recent_trading_days(n=10):
    """返回最近 n 个交易日（倒序，最新在前）"""
    t = get_trading_days(80)
    if not t:
        return []
    return list(reversed(t[-int(n):]))


# ---------------- 报告渲染 ----------------


def render_report_html(res):
    """把扫描结果渲染成独立 HTML 报告（可直接下载/存档）"""
    import html as _h

    def e(x):
        return _h.escape(str(x if x is not None else ""))

    f = res["funnel"]
    v = res["validation"]

    def tbl(rows, title, note):
        out = ['<h2>%s</h2>' % e(title), '<p class="sub">%s</p>' % e(note)]
        cols = ["代码", "名称", "涨跌幅", "最高价", "收盘价", "最高涨幅",
                "首次封板时间", "连板", "所属行业", "状态"]
        out.append('<table><thead><tr>' + "".join("<th>%s</th>" % e(c) for c in cols) + "</tr></thead><tbody>")
        for r in rows:
            state = "封板" if r["sealed"] else ("炸板" if r["broke"] else "未封板")
            cls = "up" if r["gainClose"] >= 0 else "down"
            sign = "+" if r["gainClose"] >= 0 else ""
            out.append(
                "<tr><td>%s</td><td>%s</td>"
                "<td class=\"n %s\">%s%.2f%%</td>"
                "<td class=\"n\">%.2f</td><td class=\"n\">%.2f</td>"
                "<td class=\"n up\">+%.2f%%</td>"
                "<td>%s</td><td class=\"n\">%s</td><td>%s</td><td>%s</td></tr>" % (
                    e(r["code"]), e(r["name"]),
                    cls, sign, r["gainClose"],
                    r["high"], r["close"], r["gainHigh"],
                    e(r["firstSeal"] or "无"),
                    e(r["boards"] if r["boards"] is not None else "无"),
                    e(r["sector"] or "无"), state))
        out.append("</tbody></table>")
        return "".join(out)

    css = (
        'body{font-family:-apple-system,"Microsoft YaHei",sans-serif;max-width:1180px;'
        'margin:24px auto;padding:0 18px;color:#222;line-height:1.6;background:#fff}'
        'h1{border-bottom:3px solid #e74c3c;padding-bottom:8px}'
        'h2{margin-top:28px;border-left:4px solid #3498db;padding-left:10px;font-size:19px}'
        'table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}'
        'th,td{border:1px solid #ddd;padding:6px 8px;text-align:left}'
        'th{background:#f5f7fa}td.n{text-align:right;font-variant-numeric:tabular-nums}'
        '.up{color:#e74c3c}.down{color:#2ecc71}.sub{color:#666}'
        '.warn{color:#c0392b;font-weight:600}table.fn{width:auto;min-width:340px}'
        '.kv{color:#555;font-size:14px}'
    )

    funnel_rows = [
        ("全部沪深主板非ST", res["universe"]),
        ("条件② 盘中最高涨幅 > %g%%" % (res["threshold"] * 100), f["cond2"]),
        ("+ 条件① 昨日未涨停（入选）", f["final"]),
        ("　其中 封住涨停", f["sealed"]),
        ("　其中 冲高未封", f["broken"]),
        ("被条件①剔除", f["removedByCond1"]),
        ("封板率", "%s%%" % res["sealedRate"]),
    ]

    parts = []
    parts.append("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\">")
    parts.append("<title>动态选股报告 %s</title><style>%s</style></head><body>" % (e(res["target"]), css))
    parts.append("<h1>A股动态选股报告</h1>")
    parts.append('<p class="kv">数据所属交易日 <b>%s</b>　|　前一交易日 <b>%s</b>　|　生成时间 %s</p>'
                 % (e(res["target"]), e(res["prevDay"]), e(res["collectedAt"])))
    parts.append("<h2>一、选股条件（参数化口径）</h2><ul>")
    parts.append("<li>条件①：%s 首次涨停时间取反 → 当日全天未触及涨停价</li>" % e(res["prevDay"]))
    parts.append("<li>条件②：(%s 最高价 − %s 收盘价) ÷ %s 收盘价 &gt; %g</li>"
                 % (e(res["target"]), e(res["prevDay"]), e(res["prevDay"]), res["threshold"]))
    parts.append("<li>条件③：沪深主板 且 非 ST</li></ul>")
    parts.append("<h2>二、选股漏斗</h2><table class=\"fn\"><tbody>")
    for k, val in funnel_rows:
        parts.append("<tr><td>%s</td><td class=\"n\">%s</td></tr>" % (e(k), e(val)))
    parts.append("</tbody></table>")
    parts.append("<h2>三、语义交叉校验</h2>")
    parts.append("<p>%s 涨停池 <b>%d</b> 只，炸板池 <b>%d</b> 只；%s 涨停+炸板池 <b>%d</b> 只。</p>"
                 % (e(res["target"]), v["poolZtCount"], v["poolZbCount"],
                    e(res["prevDay"]), v["prevPoolCount"]))
    if v["mismatch"]:
        parts.append('<p class="warn">价格法（最高价 ≥ 涨停价）与涨停池法存在 %d 处冲突：</p><ul class="warn">' % len(v["mismatch"]))
        for m in v["mismatch"][:20]:
            parts.append("<li>%s %s：价格法=%s，池法=%s</li>" % (e(m["code"]), e(m["name"]), m["byPrice"], m["byPool"]))
        parts.append("</ul>")
    else:
        parts.append("<p>价格法（最高价 ≥ 涨停价）与涨停池法结果完全一致，<b>冲突 0 处</b>。</p>")
    parts.append(tbl(res["rows"], "四、入选池明细",
                     "%s 盘中冲高 &gt;%g%% 且 %s 未涨停" % (res["target"], res["threshold"] * 100, res["prevDay"])))
    parts.append(tbl(res["brokenRows"], "五、冲高未封样本", "盘中触及涨停价但收盘未封住"))
    parts.append(tbl(res["removedRows"], "六、被条件①剔除", "%s 已涨停（含炸板）" % res["prevDay"]))
    parts.append("<h2>七、数据来源与声明</h2>")
    parts.append("<p class=\"kv\">%s</p>" % e(res["source"]))
    parts.append('<p class="warn">风险提示：本报告为条件逻辑解读与历史数据统计，不构成投资建议。</p>')
    parts.append("</body></html>")
    return "".join(parts)


# ---------------- 主流程 ----------------


def run_screen(target, progress=None, resume=True):
    """target: 'YYYY-MM-DD'。返回结构化结果 dict。

    resume=True 时支持**断点续传**：已经扫描过的股票会跳过，
    只补扫剩余部分（暂存于 scan_stock 表）。
    """
    t0 = time.time()
    tdays = get_trading_days(400)
    if not tdays:
        return {"success": False, "error": "无法获取交易日历（指数日K获取失败）"}
    if target not in tdays:
        return {
            "success": False,
            "error": "目标日期不是交易日：%s" % target,
            "hint": "最近可用交易日：" + ", ".join(tdays[-6:]),
            "recentDays": list(reversed(tdays[-10:])),
        }
    i = tdays.index(target)
    if i < 2:
        return {"success": False, "error": "历史数据不足，无法推导前两个交易日"}

    d = target
    d1 = tdays[i - 1]
    d2 = tdays[i - 2]

    # 需要的日K长度：覆盖 d2 到 今天
    try:
        back = (datetime.now().date() - datetime.strptime(d2, "%Y-%m-%d").date()).days
    except Exception:
        back = 60
    datalen = int(back * 7 / 5) + 25
    datalen = max(12, min(datalen, 900))

    if progress:
        progress(0, 1, "正在获取沪深主板股票列表...")
    uni = get_mainboard_universe()
    total = len(uni)
    if total == 0:
        return {"success": False, "error": "股票列表获取失败（新浪接口不可用）"}

    # ---- 断点续传：找出还没扫过的股票 ----
    try:
        import market_db as _mdb
    except Exception:
        _mdb = None

    resumed_from = 0
    if _mdb is not None:
        if resume:
            done_codes = _mdb.load_scan_codes(target)
            todo = [u for u in uni if u[1] not in done_codes]
            resumed_from = total - len(todo)
        else:
            _mdb.clear_scan(target)
            todo = uni
            resumed_from = 0
    else:
        todo = uni

    if progress:
        tip = "正在扫描 %d 只主板股票..." % total
        if resumed_from:
            tip = "断点续传：已扫 %d 只，继续扫描剩余 %d 只..." % (resumed_from, len(todo))
        progress(resumed_from, total, tip)

    def work(item):
        sym, code, name = item
        return sym, code, name, sina_kline(sym, datalen)

    batch = []
    done = resumed_from
    FLUSH = 300

    def flush():
        if _mdb is not None and batch:
            try:
                _mdb.save_scan_stocks(target, batch)
            except Exception:
                pass
            del batch[:]

    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for sym, code, name, k in ex.map(work, todo):
                done += 1
                if progress and (done % 100 == 0 or done == total):
                    progress(done, total, "已扫描 %d/%d" % (done, total))
                if not k:
                    # 取数失败（网络/停牌无数据）：不落暂存，下次运行会重试
                    continue
                ev = evaluate(k, d2, d1, d)
                if ev is None:
                    batch.append({"code": code, "name": name, "skipped": True})
                else:
                    ev["code"] = code
                    ev["name"] = name
                    batch.append(ev)
                if len(batch) >= FLUSH:
                    flush()
    flush()

    # ---- 从暂存重建结果（断点续传后与一次扫完等价）----
    if _mdb is not None:
        results = _mdb.load_scan_results(target)
        _prog = _mdb.scan_progress(target)
        skipped = _prog.get("skipped", 0)
    else:
        results = []
        skipped = 0

    # ---- 落库：当日全市场日K（沪深主板非ST）----
    try:
        import market_db as _mdb
        _mdb.save_daily_batch(d, [{
            "code": r["code"], "open": r["open"], "high": r["high"], "low": r["low"],
            "close": r["close"], "volume": r["volume"], "prev_close": r["closePrev"],
        } for r in results], source="sina")
    except Exception:
        pass

    cond2 = [r for r in results if r["cond2"]]
    final = [r for r in cond2 if r["cond1"]]
    sealed = [r for r in final if r["sealed"]]
    broken = [r for r in final if not r["sealed"]]
    removed = [r for r in cond2 if not r["cond1"]]

    # 语义交叉验证：与东财涨停/炸板池对照
    ymd = d.replace("-", "")
    zt, zt_err = em_pool("ZT", ymd)
    zb, zb_err = em_pool("ZB", ymd)
    ymd1 = d1.replace("-", "")
    zt1, zt1_err = em_pool("ZT", ymd1)
    zb1, zb1_err = em_pool("ZB", ymd1)

    # ---- 落库：交易日历 + 涨停/炸板池（失败不影响主流程）----
    try:
        import market_db as _mdb
        _mdb.save_calendar(tdays)
        _mdb.save_limit_up_pool(d, zt, "ZT")
        _mdb.save_limit_up_pool(d, zb, "ZB")
        _mdb.save_limit_up_pool(d1, zt1, "ZT")
        _mdb.save_limit_up_pool(d1, zb1, "ZB")
        _mdb.log_fetch('limit_up_pool', source='eastmoney', trade_date=d,
                       rows=len(zt) + len(zb), status='ok')
    except Exception:
        pass

    for r in results:
        c = r["code"]
        info = zt.get(c)
        if info:
            r["firstSeal"] = info["firstSeal"]
            r["lastSeal"] = info["lastSeal"]
            r["boards"] = info["boards"]
            r["sector"] = info["sector"]
            r["poolState"] = "涨停"
        elif c in zb:
            r["firstSeal"] = zb[c]["firstSeal"]
            r["lastSeal"] = ""
            r["boards"] = None
            r["sector"] = zb[c]["sector"]
            r["poolState"] = "炸板"
        else:
            r["firstSeal"] = ""
            r["lastSeal"] = ""
            r["boards"] = None
            r["sector"] = ""
            r["poolState"] = ""

    # 校验：D-1 被东财池标记为「触及涨停」的股票
    prev_touched_pool = set(zt1.keys()) | set(zb1.keys())
    mismatch = []
    for r in cond2:
        by_price = r["touchedPrev"]
        by_pool = r["code"] in prev_touched_pool
        if by_price != by_pool:
            mismatch.append({
                "code": r["code"], "name": r["name"],
                "byPrice": by_price, "byPool": by_pool,
                "gainHigh": r["gainHigh"],
            })

    # 行业补全：涨停/炸板池之外的行用新浪行业映射补齐
    sector_filled = fill_sectors(final + broken + removed)

    for r in final:
        r.pop("cond2", None)
        r.pop("cond1", None)

    final.sort(key=lambda r: -r["gainHigh"])
    broken.sort(key=lambda r: -r["gainHigh"])
    removed.sort(key=lambda r: -r["gainHigh"])

    elapsed = round(time.time() - t0, 1)

    return {
        "success": True,
        "target": d,
        "prevDay": d1,
        "prevDay2": d2,
        "universe": total,
        "scanned": total - skipped,
        "suspended": skipped,
        "funnel": {
            "cond2": len(cond2),
            "final": len(final),
            "sealed": len(sealed),
            "broken": len(broken),
            "removedByCond1": len(removed),
        },
        "sealedRate": round(len(sealed) / len(final) * 100, 1) if final else 0,
        "rows": final,
        "brokenRows": broken,
        "removedRows": removed,
        "validation": {
            "poolZtCount": len(zt),
            "poolZbCount": len(zb),
            "prevPoolCount": len(prev_touched_pool),
            "mismatch": mismatch,
            "errors": [x for x in (zt_err, zb_err, zt1_err, zb1_err) if x],
        },
        "sectorFilled": sector_filled,
        "resumedFrom": resumed_from,
        "scanStaging": (_mdb.scan_progress(target) if _mdb is not None else None),
        "elapsed": elapsed,
        "threshold": THRESHOLD,
        "source": "新浪财经（日K） + 东方财富（涨停/炸板池校验）",
        "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }