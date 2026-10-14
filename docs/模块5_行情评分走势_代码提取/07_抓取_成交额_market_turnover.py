# -*- coding: utf-8 -*-
"""两市成交额（沪市 + 深市）—— 抓取 / 入库 / 读取

口径：两市成交额 = 沪市成交额 + 深市成交额（与财经媒体口径一致，例：1.68 万亿）
      沪市取「上证综指 000001.SH」成交额，深市取「深证综指 399106.SZ」成交额，
      两者分别覆盖沪市、深市全部挂牌股票（含主板 / 创业板 / 科创板）。
存储单位：亿元（写入 market_turnover 表）。

数据来源（公开接口，免登录、免 Key）：
  · 历史：东方财富 push2his 指数日K（secid 1.000001 / 0.399106）→ f57 成交额(元)
  · 实时：新浪行情（sh000001 / sz399106）→ 成交额(元)，用于收盘后第一时间入库

所有函数内部捕获异常，失败返回 None / 0，绝不影响主流程。
"""
import json

import requests

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://quote.eastmoney.com/",
}
_SINA_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://finance.sina.com.cn/",
}

_EM_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
SECID_SH = "1.000001"      # 上证综指
SECID_SZ = "0.399106"      # 深证综指


def _em_index_amount(secid, lmt=120, timeout=15):
    """东方财富指数日K -> {date: 成交额(亿元)}"""
    url = ("%s?secid=%s&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57"
           "&klt=101&fqt=0&end=20500101&lmt=%d" % (_EM_KLINE, secid, int(lmt)))
    try:
        j = requests.get(url, headers=_HEADERS, timeout=timeout).json()
    except Exception:
        return {}
    out = {}
    for row in ((j.get("data") or {}).get("klines") or []):
        p = str(row).split(",")
        if len(p) < 7:
            continue
        try:
            out[p[0]] = float(p[6]) / 1e8
        except Exception:
            pass
    return out


def fetch_history(days=120):
    """历史每日两市成交额（含今天，只要上游已更新）

    返回 [{date, sh, sz, amount}, ...]（按日期升序，单位：亿元）
    """
    sh = _em_index_amount(SECID_SH, days)
    sz = _em_index_amount(SECID_SZ, days)
    rows = []
    for d in sorted(set(sh) | set(sz)):
        a, b = sh.get(d), sz.get(d)
        if a is None and b is None:
            continue
        rows.append({"date": d,
                     "sh": round(a, 2) if a is not None else None,
                     "sz": round(b, 2) if b is not None else None,
                     "amount": round((a or 0.0) + (b or 0.0), 2)})
    return rows


def fetch_realtime():
    """实时两市成交额（新浪行情）-> {date, sh, sz, amount}，失败返回 None

    注意：盘中抓到的值是「截至此刻」的累计成交额（收盘后才是全天值）。
    """
    url = "https://hq.sinajs.cn/list=sh000001,sz399106"
    try:
        r = requests.get(url, headers=_SINA_HEADERS, timeout=10)
        r.encoding = "gbk"
        txt = r.text
    except Exception:
        return None
    got, date = {}, None
    for line in txt.splitlines():
        if "=" not in line:
            continue
        key, _, payload = line.partition("=")
        parts = payload.strip().strip(";").strip('"').split(",")
        if len(parts) < 11:
            continue
        try:
            amt = float(parts[9])          # 成交额（元）
        except Exception:
            continue
        for p in parts:
            p = p.strip()
            if len(p) == 10 and p[4] == "-" and p[7] == "-":
                date = p
                break
        if "sh000001" in key:
            got["sh"] = amt / 1e8
        elif "sz399106" in key:
            got["sz"] = amt / 1e8
    if not date or "sh" not in got or "sz" not in got:
        return None
    return {"date": date, "sh": round(got["sh"], 2), "sz": round(got["sz"], 2),
            "amount": round(got["sh"] + got["sz"], 2)}


def save_rows(rows, source="em_index"):
    """把成交额写入本地库（亿元），返回写入条数"""
    if not rows:
        return 0
    try:
        import market_db as _mdb
        return int(_mdb.save_turnover_batch(rows, source=source) or 0)
    except Exception:
        return 0


def sync_history(days=120, source="em_index"):
    """抓历史并入库（覆盖同日期旧值），返回写入条数"""
    return save_rows(fetch_history(days), source=source)


def sync_today(source="sina_rt"):
    """抓实时并入库（只写当天一条），返回该条 dict 或 None"""
    row = fetch_realtime()
    if not row:
        return None
    save_rows([row], source=source)
    return row


def sync_recent(days=10):
    """定时任务用：先补实时（当天），再用日K覆盖最近 days 天（更权威）。

    返回给调度器展示的字符串。
    """
    rt = sync_today()
    n = sync_history(days)
    return "实时=%s 历史=%d天" % (("%s 1.68万亿" % rt["date"]) if rt else "无", n)
