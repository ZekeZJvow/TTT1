# -*- coding: utf-8 -*-
r"""情绪评分引擎 V1（对应 PRD 第 4 节）

5 个模块（权重固定，随 MODEL_VERSION 记录）：
    市场广度 30 / 涨停跌停情绪 25 / 炸板质量 15 / 人气股表现 15 / 指数与成交确认 15

缺失策略（不伪造数据）：
    某因子缺输入 -> 该因子为 None，不参与加权；按可用因子重新归一
    completeness = 可用权重 / 总权重；<0.9 视为「降级评分」，原因写入 missing / alerts

用法：
    python score_engine.py            # 重算全部历史并落库
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isfile(os.path.join(ROOT, "market_db.py")):
    ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import market_db as m

MODEL_VERSION = "v1.0"
WEIGHTS = {"breadth": 30.0, "limit": 25.0, "broken": 15.0, "hot": 15.0, "index": 15.0}
LABELS = [(80, "强势"), (65, "偏强"), (45, "震荡分化"), (30, "偏弱"), (0, "高风险/恐慌")]
_INTRA_CACHE = {"ts": 0.0, "res": None}


def clamp01(x):
    return max(0.0, min(1.0, float(x)))


def label_of(total):
    if total is None:
        return ""
    for th, name in LABELS:
        if total >= th:
            return name
    return ""


def compute_scores(stats, idx_pct, amt_ma20, hot):
    """stats: market_day_stats 行；idx_pct: 沪深300 涨跌幅%；amt_ma20: 20日均额；hot: {avg, up_ratio, n}"""
    s = {}
    missing = []

    # ① 市场广度 30
    universe = stats["universe"] or 0
    n = (stats["up_count"] or 0) + (stats["down_count"] or 0) + (stats["flat_count"] or 0)
    if n > 0 and universe > 0:
        up_ratio = (stats["up_count"] or 0) / n
        extreme = ((stats["up5_count"] or 0) - (stats["down5_count"] or 0)) / universe
        s["breadth"] = 100 * (0.6 * up_ratio + 0.4 * clamp01(0.5 + extreme))
    else:
        missing.append("市场广度")

    # ② 涨停/跌停情绪 25
    if stats["limit_up"] is not None and stats["limit_down"] is not None:
        lu = stats["limit_up"] or 0
        ld = stats["limit_down"] or 0
        hgt = stats["limit_height"] or 0
        s["limit"] = 100 * (0.50 * clamp01(lu / 100.0) +
                            0.30 * clamp01(1 - ld / 60.0) +
                            0.20 * clamp01(hgt / 10.0))
    else:
        missing.append("涨停情绪")

    # ③ 炸板质量 15（炸板率越低越好）
    lu = stats["limit_up"] or 0
    br = stats["broken"] or 0
    if (lu + br) > 0:
        s["broken"] = 100 * (1 - clamp01(br / (lu + br)))
    else:
        missing.append("炸板质量")

    # ④ 人气股表现 15
    if hot and hot.get("n"):
        s["hot"] = 100 * (0.6 * clamp01(0.5 + hot["avg"] / 10.0) + 0.4 * clamp01(hot["up_ratio"]))
    else:
        missing.append("人气股表现")

    # ⑤ 指数与成交确认 15
    if idx_pct is not None and amt_ma20 and stats["amount"]:
        vr = stats["amount"] / amt_ma20
        agree = 1.0 if ((idx_pct > 0) == ((stats["up_count"] or 0) > (stats["down_count"] or 0))) else 0.0
        s["index"] = 100 * (0.40 * clamp01(0.5 + idx_pct / 3.0) +
                            0.40 * clamp01(vr / 1.5) +
                            0.20 * agree)
    else:
        missing.append("指数确认")

    used = sum(WEIGHTS[k] for k in s)
    total = sum(WEIGHTS[k] * v for k, v in s.items()) / used if used else None
    if total is not None:
        total = round(total, 1)
    completeness = round(used / sum(WEIGHTS.values()), 3)

    alerts = []
    if (stats["limit_down"] or 0) >= 20:
        alerts.append("跌停 %d 只，亏钱效应扩散" % stats["limit_down"])
    if (lu + br) > 0 and br / (lu + br) >= 0.5:
        alerts.append("炸板率 %.0f%%，封板不稳" % (br / (lu + br) * 100))
    if n > 0 and (stats["up_count"] or 0) / n <= 0.3:
        alerts.append("上涨占比仅 %.0f%%" % ((stats["up_count"] or 0) / n * 100))
    if amt_ma20 and stats["amount"] and stats["amount"] / amt_ma20 <= 0.7:
        alerts.append("成交额为 20 日均额的 %.0f%%" % (stats["amount"] / amt_ma20 * 100))
    if completeness < 0.9:
        alerts.append("数据不完整，降级评分（缺：%s）" % "、".join(missing))

    return s, total, label_of(total), alerts, completeness, missing


def compute_from_snapshot(snap, today=None):
    """用一次实时快照计算「盘中估算」评分（不写库、不覆盖历史）

    snap 需包含：universe/up/down/flat/up5/down5/limit_up/limit_down/
                 broken/limit_height/promote_rate/amount_yi/index_pct/hot/date/quote_time
    数据不足的因子按缺失处理；返回 provisional=True，由前端标注「盘中估算」。
    """
    if not snap:
        return {"ok": False, "error": "没有实时快照"}
    today = today or time.strftime("%Y-%m-%d")

    # 20 日均额：用「今天之前」已入库的完整交易日，避免把盘中半天成交额混进均值
    rows = m._read(lambda c: c.execute(
        "SELECT `amount` FROM `market_day_stats` "
        "WHERE `trade_date` < ? AND `amount` IS NOT NULL "
        "ORDER BY `trade_date` DESC LIMIT 20", (today,)).fetchall(), [])
    amts = [r["amount"] for r in rows if r["amount"]]
    amt_ma20 = (sum(amts) / len(amts)) if amts else None

    universe = snap.get("universe") or (
        (snap.get("up") or 0) + (snap.get("down") or 0) + (snap.get("flat") or 0))
    stats = {
        "universe": universe,
        "up_count": snap.get("up"),
        "down_count": snap.get("down"),
        "flat_count": snap.get("flat"),
        "up5_count": snap.get("up5"),
        "down5_count": snap.get("down5"),
        "limit_up": snap.get("limit_up"),
        "limit_down": snap.get("limit_down"),
        "broken": snap.get("broken"),
        "limit_height": snap.get("limit_height"),
        "promote_rate": snap.get("promote_rate"),
        "amount": snap.get("amount_yi"),
    }
    s, total, lab, alerts, comp, missing = compute_scores(
        stats, snap.get("index_pct"), amt_ma20, snap.get("hot"))
    if total is None:
        return {"ok": False, "error": "盘中数据不足，无法计算评分"}

    out = {
        "ok": True, "date": today, "quote_time": snap.get("quote_time"),
        "total": total, "label": lab, "alerts": "；".join(alerts),
        "completeness": comp, "missing": "、".join(missing),
        "model_version": "%s-intraday" % MODEL_VERSION,
        "computed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "provisional": True,
        "breadth": round(s["breadth"], 1) if "breadth" in s else None,
        "limit": round(s["limit"], 1) if "limit" in s else None,
        "broken": round(s["broken"], 1) if "broken" in s else None,
        "hot": round(s["hot"], 1) if "hot" in s else None,
        "index": round(s["index"], 1) if "index" in s else None,
        # 明细（便于核对，不影响页面展示）
        "detail": {
            "universe": universe, "up": snap.get("up"), "down": snap.get("down"),
            "flat": snap.get("flat"), "up5": snap.get("up5"), "down5": snap.get("down5"),
            "limit_up": snap.get("limit_up"), "limit_down": snap.get("limit_down"),
            "broken": snap.get("broken"), "limit_height": snap.get("limit_height"),
            "promote_rate": snap.get("promote_rate"),
            "amount_yi": snap.get("amount_yi"), "amount_ma20": round(amt_ma20, 2) if amt_ma20 else None,
            "index_pct": snap.get("index_pct"), "hot": snap.get("hot"),
        },
    }
    return out


def compute_intraday(force=False):
    """抓一次全市场实时快照并计算当日盘中评分（非交易时段返回 stale）

    45 秒内重复调用直接返回上次结果：页面自动估算 + 手动点按钮不会重复抓全市场。
    """
    now = time.time()
    if not force and _INTRA_CACHE["res"] is not None and (now - _INTRA_CACHE["ts"]) < 45:
        return _INTRA_CACHE["res"]
    try:
        import realtime_snapshot as rt
    except Exception as e:
        return {"ok": False, "error": "realtime_snapshot 不可用: %s" % e}
    try:
        snap = rt.snapshot()
    except Exception as e:
        return {"ok": False, "error": "抓取实时行情失败: %s" % e}
    if not snap:
        return {"ok": False, "error": "抓不到实时行情（网络或数据源异常）"}
    today = time.strftime("%Y-%m-%d")
    if snap.get("date") != today:
        res = {"ok": False, "stale": True, "date": snap.get("date"),
               "message": "当前非交易时段（行情日期 %s），无法计算盘中评分" % snap.get("date")}
        _INTRA_CACHE.update({"ts": now, "res": res})
        return res
    res = compute_from_snapshot(snap, today)
    _INTRA_CACHE.update({"ts": time.time(), "res": res})
    return res


def compute_all():
    m.init_db()
    rows = m._read(lambda c: c.execute(
        "SELECT trade_date, universe, up_count, down_count, flat_count, up5_count, down5_count, "
        "limit_up, limit_down, broken, limit_height, promote_rate, ew_return, amount "
        "FROM market_day_stats ORDER BY trade_date").fetchall(), [])
    if not rows:
        print("market_day_stats 为空，请先运行 tools/build_day_stats.py"); return 0

    idx = {}
    for r in m._read(lambda c: c.execute(
            "SELECT trade_date, pct FROM index_daily WHERE code='000300'").fetchall(), []):
        idx[r["trade_date"]] = r["pct"]

    hot = {}
    for r in m._read(lambda c: c.execute(
            "SELECT h.trade_date AS d, AVG(k.change_pct) AS avg_pct, "
            "       SUM(CASE WHEN k.change_pct>0 THEN 1 ELSE 0 END) AS ups, COUNT(*) AS cnt "
            "FROM hotlist_snapshot h "
            "JOIN daily_kline k ON k.stock_code=h.stock_code AND k.trade_date=h.trade_date "
            "WHERE h.rank<=30 AND k.change_pct IS NOT NULL "
            "GROUP BY h.trade_date").fetchall(), []):
        hot[r["d"]] = {"avg": r["avg_pct"] or 0.0,
                       "up_ratio": (r["ups"] or 0) / (r["cnt"] or 1), "n": r["cnt"] or 0}

    amts = [r["amount"] for r in rows]
    out = []
    for i, r in enumerate(rows):
        win = [a for a in amts[max(0, i - 19):i + 1] if a]
        ma20 = (sum(win) / len(win)) if win else None
        s, total, lab, alerts, comp, missing = compute_scores(
            r, idx.get(r["trade_date"]), ma20, hot.get(r["trade_date"]))
        out.append({"date": r["trade_date"],
                    "s_breadth": round(s.get("breadth"), 1) if "breadth" in s else None,
                    "s_limit": round(s.get("limit"), 1) if "limit" in s else None,
                    "s_broken": round(s.get("broken"), 1) if "broken" in s else None,
                    "s_hot": round(s.get("hot"), 1) if "hot" in s else None,
                    "s_index": round(s.get("index"), 1) if "index" in s else None,
                    "total": total, "label": lab, "alerts": "；".join(alerts),
                    "completeness": comp, "missing": "、".join(missing)})

    def _w(conn):
        cur = conn.cursor()
        sql = m._upsert("score_daily",
                        ["trade_date", "s_breadth", "s_limit", "s_broken", "s_hot", "s_index",
                         "total", "label", "alerts", "completeness", "missing",
                         "model_version", "data_version", "computed_at"],
                        ["trade_date"],
                        ["s_breadth", "s_limit", "s_broken", "s_hot", "s_index", "total",
                         "label", "alerts", "completeness", "missing",
                         "model_version", "data_version", "computed_at"])
        ts = m.now_str()
        n = 0
        for r in out:
            cur.execute(sql, (r["date"], r["s_breadth"], r["s_limit"], r["s_broken"],
                              r["s_hot"], r["s_index"], r["total"], r["label"], r["alerts"],
                              r["completeness"], r["missing"], MODEL_VERSION, "kline", ts))
            n += 1
        return n
    n = m._write(_w) or 0
    print("score_daily 写入 %d 天（模型 %s）" % (n, MODEL_VERSION))
    return n


if __name__ == "__main__":
    compute_all()
    rows = m._read(lambda c: c.execute(
        "SELECT trade_date, s_breadth, s_limit, s_broken, s_hot, s_index, total, label, "
        "completeness FROM score_daily ORDER BY trade_date DESC LIMIT 5").fetchall(), [])
    print("\n最近 5 天:")
    for r in rows:
        print("  %s 广度%s 涨停%s 炸板%s 人气%s 指数%s => %.1f %s (完整度%.2f)"
              % (r[0], r[1], r[2], r[3], r[4], r[5], r[6] or 0, r[7], r[8] or 0))
