# -*- coding: utf-8 -*-
r"""融资融券余额（沪深两市合计）—— 东方财富 datacenter

数据源：RPTA_RZRQ_LSHJ（沪深两市融资融券交易汇总），每个交易日一条：
    RZYE  融资余额(元)
    RQYE  融券余额(元)
    RZRQYE 融资融券余额合计(元)
统一换算成「亿元」入库。

注意：融资融券数据是 T+1 公布（当天收盘后通常还没有当天值），
      所以每日任务用 sync_recent() 回补最近一段时间即可。
"""
import time

import requests

_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://data.eastmoney.com/rzrq/",
}


def _fetch_page(page, size=1000, timeout=20):
    params = {
        "reportName": "RPTA_RZRQ_LSHJ",
        "columns": "ALL",
        "pageNumber": int(page),
        "pageSize": int(size),
        "sortColumns": "DIM_DATE",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    for _ in range(3):
        try:
            j = requests.get(_URL, params=params, headers=_HEADERS, timeout=timeout).json()
            return (j.get("result") or {}).get("data") or []
        except Exception:
            time.sleep(0.5)
    return []


def _f(v):
    try:
        return float(v) / 1e8          # 元 -> 亿元
    except Exception:
        return None


def fetch_history(days=1200, max_pages=12):
    """抓最近 days 个自然日内的融资融券余额 -> [{date, rz, rq, total}]（升序，亿元）"""
    import datetime as _dt
    since = (_dt.date.today() - _dt.timedelta(days=int(days))).isoformat()
    out = {}
    for page in range(1, max_pages + 1):
        rows = _fetch_page(page)
        if not rows:
            break
        oldest = None
        for r in rows:
            d = str(r.get("DIM_DATE") or "")[:10]
            if not d:
                continue
            oldest = d if oldest is None else min(oldest, d)
            out[d] = {"date": d,
                      "rz": round(_f(r.get("RZYE")), 2) if _f(r.get("RZYE")) is not None else None,
                      "rq": round(_f(r.get("RQYE")), 2) if _f(r.get("RQYE")) is not None else None,
                      "total": round(_f(r.get("RZRQYE")), 2) if _f(r.get("RZRQYE")) is not None else None}
        if oldest and oldest < since:
            break
        time.sleep(0.15)
    return [out[d] for d in sorted(out)]


def save_rows(rows, source="em_rzrq"):
    if not rows:
        return 0
    try:
        import market_db as m
        return int(m.save_margin_batch(rows, source=source) or 0)
    except Exception:
        return 0


def sync_history(days=1200):
    """抓取并入库，返回写入条数"""
    return save_rows(fetch_history(days))


def sync_recent(days=30):
    """每日任务用：回补最近 days 天（T+1 数据，所以多抓几天）"""
    return sync_history(days)


def latest(n=3):
    """库里最近的 n 条（调试用）"""
    import market_db as m
    return m.margin_map()[-n:] if False else m.margin_map()
