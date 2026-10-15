# -*- coding: utf-8 -*-
r"""同花顺 CLI 备用源：历史两市成交额（东财偶发拒连时兜底）

取上证综指(000001.SH) + 深证综指(399106.SZ)的 turnover，相加即两市成交额。
坑：CLI 返回的 date_ms 是「北京时间零点」，必须按 UTC+8 转日期，
    按 UTC 转整体会差一天。
"""
import datetime as _dt
import json
import os
import subprocess

CLI = os.environ.get("HITHINK_CLI") or os.path.join(
    os.path.expanduser("~"), ".local", "bin", "hithink-finance.CMD")


def available():
    return os.path.isfile(CLI)


def index_turnover(ths, start_ms, end_ms, timeout=90):
    """-> {date: 成交额(亿元)}"""
    if not available():
        return {}
    cmd = [CLI, "index", "history", "--thscode", ths,
           "--start-ms", str(int(start_ms)), "--end-ms", str(int(end_ms)), "--format", "json"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        if p.returncode != 0 or not (p.stdout or "").strip():
            return {}
        j = json.loads(p.stdout)
    except Exception:
        return {}
    tz = _dt.timezone(_dt.timedelta(hours=8))
    out = {}
    for it in ((j.get("data") or {}).get("item") or []):
        try:
            d = _dt.datetime.fromtimestamp(float(it["date_ms"]) / 1000.0, tz).strftime("%Y-%m-%d")
            out[d] = float(it["turnover"]) / 1e8
        except Exception:
            pass
    return out


def fetch_history(days=300):
    """-> [{"date","sh","sz","amount"}, ...]（升序，单位亿元）"""
    end = _dt.datetime.now()
    start = end - _dt.timedelta(days=int(days) * 1.6 + 10)
    sms = int(start.timestamp() * 1000)
    ems = int((end + _dt.timedelta(days=1)).timestamp() * 1000)
    sh = index_turnover("000001.SH", sms, ems)
    sz = index_turnover("399106.SZ", sms, ems)
    rows = []
    for d in sorted(set(sh) | set(sz)):
        a, b = sh.get(d), sz.get(d)
        if a is None and b is None:
            continue
        rows.append({"date": d, "sh": round(a, 2) if a is not None else None,
                     "sz": round(b, 2) if b is not None else None,
                     "amount": round((a or 0.0) + (b or 0.0), 2)})
    return rows
