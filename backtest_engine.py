# -*- coding: utf-8 -*-
r"""历史回测引擎（对应 PRD 第 5 节）

口径：
  · T 日评分只用 T 日收盘后可得数据
  · 未来 N 日收益 = close[T+N]/close[T]-1（N=1/3/5），窗口不完整的末尾日期不计入
  · 全 A 等权收益 = 各日 ew_return 复利
  · 最大不利波动 = 窗口内最低收盘价 / T 日收盘 - 1（**最低收盘价近似**，非盘中真实回撤）
  · 极端亏损概率阈值可配置（默认 指数5日 ≤ -3%、全A 5日 ≤ -5%，各 N 用同一阈值并注明）
  · 开发集/样本外按日期前 70% / 后 30% 切分，不打乱
"""
import math

BUCKETS = [(0, 30, "0~29"), (30, 45, "30~44"), (45, 65, "45~64"), (65, 80, "65~79"), (80, 101, "80~100")]


def _mean(v):
    return (sum(v) / len(v)) if v else None


def _median(v):
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _rank(v):
    """平均秩（并列取均值），用于 Spearman"""
    order = sorted(range(len(v)), key=lambda i: v[i])
    ranks = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def _pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = _mean(x), _mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if not sx or not sy:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def _spearman(x, y):
    if len(x) < 3:
        return None
    return _pearson(_rank(x), _rank(y))


def _stats(rets, adverse, ext, threshold):
    """一组收益的统计（rets: 指数收益%；adverse: 最大不利%；ext: 是否极端亏损）"""
    n = len(rets)
    if not n:
        return {"n": 0}
    m = _mean(rets)
    se = None
    if n > 1:
        var = sum((a - m) ** 2 for a in rets) / (n - 1)
        se = math.sqrt(var / n)
    return {
        "n": n,
        "mean": round(m, 2),
        "median": round(_median(rets), 2),
        "up_prob": round(100.0 * sum(1 for a in rets if a > 0) / n, 1),
        "extreme_prob": round(100.0 * sum(1 for e in ext if e) / n, 1),
        "mean_adverse": round(_mean(adverse), 2) if adverse else None,
        "ci_low": round(m - 1.96 * se, 2) if se is not None else None,
        "ci_high": round(m + 1.96 * se, 2) if se is not None else None,
    }


def run(m, start=None, end=None, index_code="000300", horizons=(1, 3, 5),
        split=0.7, ext_index=-3.0, ext_ew=-5.0, min_completeness=0.0):
    scores = m._read(lambda c: c.execute(
        "SELECT trade_date, total, completeness, label FROM score_daily ORDER BY trade_date").fetchall(), [])
    closes = {r["trade_date"]: r["close"] for r in m._read(lambda c: c.execute(
        "SELECT trade_date, close FROM index_daily WHERE code=?", (index_code,)).fetchall(), [])}
    ew = {r["trade_date"]: r["ew_return"] for r in m._read(lambda c: c.execute(
        "SELECT trade_date, ew_return FROM market_day_stats").fetchall(), [])}

    dates = [r["trade_date"] for r in scores]
    keep = set(dates)
    seq = sorted(d for d in keep if d in closes and closes.get(d) is not None)
    if start:
        seq = [d for d in seq if d >= start]
    if end:
        seq = [d for d in seq if d <= end]
    if len(seq) < 10:
        return {"ok": False, "error": "有效样本不足（<10 天），请放宽日期范围"}

    smap = {r["trade_date"]: r for r in scores}
    seq = [d for d in seq if (smap[d]["completeness"] or 0) >= min_completeness]
    if len(seq) < 10:
        return {"ok": False, "error": "满足完整度要求的样本不足（<10 天）"}

    n_split = max(1, int(round(len(seq) * split)))
    dev_dates = set(seq[:n_split])
    oos_dates = set(seq[n_split:])
    split_date = seq[n_split] if n_split < len(seq) else None
    dev_seq = seq[:n_split]
    oos_seq = seq[n_split:]

    # 逐日 + 逐窗口
    daily = []          # 每行：date, total, label, r1/r3/r5, a1/a3/a5, e1/e3/e5
    for i, d in enumerate(seq):
        c0 = closes[d]
        row = {"date": d, "total": smap[d]["total"], "label": smap[d]["label"],
               "completeness": smap[d]["completeness"]}
        ok_any = False
        for N in horizons:
            if i + N >= len(seq):
                continue
            cN = closes.get(seq[i + N])
            if not cN:
                continue
            ret = (cN / c0 - 1) * 100
            lows = [closes[seq[j]] for j in range(i + 1, i + N + 1) if closes.get(seq[j])]
            adverse = (min(lows) / c0 - 1) * 100 if lows else None
            # 全A等权复利
            acc = 1.0
            ok = True
            for j in range(i + 1, i + N + 1):
                v = ew.get(seq[j])
                if v is None:
                    ok = False
                    break
                acc *= (1 + v / 100.0)
            ewret = (acc - 1) * 100 if ok else None
            row["r%d" % N] = round(ret, 3)
            row["a%d" % N] = round(adverse, 3) if adverse is not None else None
            row["w%d" % N] = round(ewret, 3) if ewret is not None else None
            row["e%d" % N] = 1 if (ret <= ext_index or (ewret is not None and ewret <= ext_ew)) else 0
            ok_any = True
        if ok_any:
            daily.append(row)

    def agg(rows):
        out = {}
        for N in horizons:
            sub = [r for r in rows if r.get("r%d" % N) is not None]
            out[str(N)] = _stats([r["r%d" % N] for r in sub],
                                 [r["a%d" % N] for r in sub if r.get("a%d" % N) is not None],
                                 [r["e%d" % N] for r in sub], ext_index)
        return out

    buckets = []
    for lo, hi, name in BUCKETS:
        sub = [r for r in daily if r["total"] is not None and lo <= r["total"] < hi]
        item = {"bucket": name, "n": len(sub), "horizons": agg(sub)}
        buckets.append(item)

    def corr(rows):
        out = {}
        for N in horizons:
            sub = [r for r in rows if r.get("r%d" % N) is not None and r["total"] is not None]
            xs = [r["total"] for r in sub]
            ys = [r["r%d" % N] for r in sub]
            ws = [r["w%d" % N] for r in sub if r.get("w%d" % N) is not None]
            out[str(N)] = {"n": len(sub),
                           "pearson": round(_pearson(xs, ys), 3) if _pearson(xs, ys) is not None else None,
                           "spearman": round(_spearman(xs, ys), 3) if _spearman(xs, ys) is not None else None}
        return out

    mono = {}
    for N in horizons:
        seqm = []
        for b in buckets:
            st = b["horizons"].get(str(N)) or {}
            if st.get("mean") is not None:
                seqm.append(st["mean"])
        mono[str(N)] = (len(seqm) >= 3 and all(seqm[i] <= seqm[i + 1] for i in range(len(seqm) - 1)))

    return {
        "ok": True,
        "index_code": index_code,
        "range": [seq[0], seq[-1]],
        "n_days": len(seq),
        "n_scored": len(daily),
        "split": {"ratio": split, "split_date": split_date,
                  "dev": {"n": len(dev_dates), "range": [dev_seq[0], dev_seq[-1]] if dev_seq else [],
                          "horizons": agg([r for r in daily if r["date"] in dev_dates])},
                  "oos": {"n": len(oos_dates), "range": [oos_seq[0], oos_seq[-1]] if oos_seq else [],
                          "horizons": agg([r for r in daily if r["date"] in oos_dates])}},
        "overall": agg(daily),
        "buckets": buckets,
        "corr": corr(daily),
        "monotonic": mono,
        "thresholds": {"index_extreme_pct": ext_index, "ew_extreme_pct": ext_ew,
                       "min_completeness": min_completeness},
        "notes": [
            "未来收益 = close[T+N]/close[T]-1；窗口不完整的末尾日期不计入",
            "最大不利波动为「窗口内最低收盘价」近似，非盘中真实回撤",
            "极端亏损：指数收益 ≤ %.1f%% 或 全A等权 ≤ %.1f%%（各 N 使用同一阈值）" % (ext_index, ext_ew),
            "相邻交易日窗口重叠，显著性需谨慎解读",
        ],
        "daily_tail": daily[-10:],
    }
