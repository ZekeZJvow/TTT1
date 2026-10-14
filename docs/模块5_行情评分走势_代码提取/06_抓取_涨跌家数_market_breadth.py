# -*- coding: utf-8 -*-
r"""每日涨跌家数（沪深京全部 A 股口径）—— 抓取 / 入库 / 读取

口径与同花顺「涨跌分布」一致：
    统计范围 = 沪深京全部 A 股（含 ST / 创业板 / 科创板 / 北交所）
    上涨 = 当日涨跌幅 > 0，下跌 = 当日涨跌幅 < 0，平盘 = 涨跌幅 == 0，
    停牌（无行情）不计入三者，单独记 suspended。

数据源：东方财富行情列表接口（clist），一次分页拉全市场（约 60 页 / 7 秒）。
所有函数内部捕获异常，失败返回 None / 0，不影响主流程。
"""
import time
from concurrent.futures import ThreadPoolExecutor

import requests

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://quote.eastmoney.com/",
}
_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
# 沪深主板 + 创业板 + 科创板 + 北交所
_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
_PAGE_SIZE = 100


def fetch_page(pn, pz=_PAGE_SIZE, timeout=20, fields="f12,f13,f14,f3", fid="f12"):
    """取第 pn 页 -> {"total": n, "rows": [...]}（失败返回空）"""
    url = ("%s?pn=%d&pz=%d&po=1&np=1&fltt=2&invt=2&fid=%s&fs=%s&fields=%s"
           % (_CLIST, int(pn), int(pz), fid, _FS, fields))
    for _ in range(3):
        try:
            j = requests.get(url, headers=_HEADERS, timeout=timeout).json()
            d = j.get("data") or {}
            return {"total": d.get("total") or 0, "rows": d.get("diff") or []}
        except Exception:
            time.sleep(0.4)
    return {"total": 0, "rows": []}


def fetch_all(workers=10):
    """拉全市场股票列表 -> [{"code","market","name","change_pct"}, ...]"""
    first = fetch_page(1)
    if not first["total"]:
        return []
    pages = (first["total"] + _PAGE_SIZE - 1) // _PAGE_SIZE
    out = list(first["rows"])
    if pages > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(lambda p: fetch_page(p), range(2, pages + 1)):
                out.extend(res["rows"])
    seen, uniq = set(), []
    for it in out:
        c = it.get("f12")
        if not c or c in seen:
            continue
        seen.add(c)
        uniq.append(it)
    return uniq


def count_breadth(rows):
    """统计涨跌家数 -> (up, down, flat, suspended)"""
    up = down = flat = suspended = 0
    for it in rows:
        v = it.get("f3")
        if v in ("-", None, ""):
            suspended += 1
            continue
        try:
            f = float(v)
        except Exception:
            suspended += 1
            continue
        if f > 0:
            up += 1
        elif f < 0:
            down += 1
        else:
            flat += 1
    return up, down, flat, suspended


def fetch_realtime(trade_date=None):
    """实时涨跌家数 -> {date, up, down, flat, total, suspended}，失败返回 None"""
    rows = fetch_all()
    if not rows:
        return None
    up, down, flat, susp = count_breadth(rows)
    if up + down + flat <= 0:
        return None
    return {"date": trade_date, "up": up, "down": down, "flat": flat,
            "total": len(rows), "suspended": susp}


def sync_today(trade_date, source="em_clist"):
    """抓今天的涨跌家数并入库（trade_date 由调用方给，接口本身不带日期）

    顺带把全市场「代码 -> 名称」存起来，用于识别 ST（评分口径要求非 ST）。
    """
    rows = fetch_all()
    if not rows:
        return None
    up, down, flat, susp = count_breadth(rows)
    if up + down + flat <= 0:
        return None
    row = {"date": trade_date, "up": up, "down": down, "flat": flat,
           "total": len(rows), "suspended": susp}
    try:
        import market_db as _mdb
        _mdb.save_market_breadth(row, source=source)
        _mdb.save_stock_names([{"code": it.get("f12"), "name": it.get("f14")}
                               for it in rows])
    except Exception:
        return row
    return row


def em_to_sina_symbol(code, market=None):
    """东方财富代码 -> 新浪行情符号（sh/sz/bj 前缀）"""
    code = str(code or "").strip()
    if not code:
        return ""
    if code.startswith(("92", "43", "83", "87", "88")):
        return "bj" + code              # 北交所（92xxxx 等）优先
    if market == 1 or code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def a_share_symbols():
    """全市场 A 股代码 -> [("sh600000", "600000", "浦发银行"), ...]"""
    out = []
    for it in fetch_all():
        code = it.get("f12")
        sym = em_to_sina_symbol(code, it.get("f13"))
        if sym:
            out.append((sym, code, it.get("f14")))
    return out
