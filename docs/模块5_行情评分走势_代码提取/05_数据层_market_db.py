_STATS_CACHE = {"ts": 0.0, "n": 0, "rows": []}
_MONTHS_CACHE = {"ts": 0.0, "data": []}
_SEAL_STATE = {"running": False, "last_try": 0.0}
_STATS_TTL = 120.0         # 秒；读缓存
EPS_LIMIT = 0.001          # 涨停价比较容差


def _limit_price(prev_close):
    """前收盘 -> 涨停价（×1.1 四舍五入到分）

    用整数运算实现（与 Decimal ROUND_HALF_UP 版逐位一致，已用全库 116 万条收盘价核对）。
    """
    return ((int(round(prev_close * 1000)) * 11 + 50) // 100) / 100.0


def invalidate_market_stats():
    """清空行情统计缓存（抓取入库后调用，保证页面立刻看到新数据）"""
    _STATS_CACHE["ts"] = 0.0
    _STATS_CACHE["n"] = 0
    _STATS_CACHE["rows"] = []
    _MONTHS_CACHE["ts"] = 0.0
    _MONTHS_CACHE["data"] = []


def available_months(min_rows=2000, ttl=600.0):
    """有数据的月份列表（升序，形如 ['2026-01', ...]）—— 页面用它决定哪些月份按钮可点"""
    c = _MONTHS_CACHE
    if c["data"] and (time.time() - c["ts"]) < ttl:
        return c["data"]

    def _f(conn):
        months = set()
        for r in conn.execute(
                "SELECT DISTINCT substr(`trade_date`,1,7) FROM `market_seal_stats`").fetchall():
            if r[0]:
                months.add(str(r[0]))
        return sorted(months)
    out = _read(_f, []) or []
    if out:
        c["ts"] = time.time()
        c["data"] = out
    return out


def compute_seal_stats(lookback_days=460, force=False, progress=None):
    """离线计算「每日封板率」并落库到 market_seal_stats（只算缺的日子）

    口径 = 沪深主板非ST：
        · 入选池 = 昨日未触及涨停价 且 今日盘中最高涨幅 > 9%
        · 封住   = 今日收盘 >= 今日涨停价（前收盘 × 1.1，四舍五入到分）
        · 行情评分 = 封板率 = 封住 / 入选池 × 100
    返回本次新算的天数。
    """
    import datetime as _dt
    n_done = [0]

    def _f(conn):
        cur = conn.cursor()
        since = (_dt.datetime.now() - _dt.timedelta(days=int(lookback_days))).strftime("%Y-%m-%d")
        # ① 最近每日行数 -> 完整交易日（当日有涨跌幅的股票 >= 2000 只）
        rows = conn.execute(
            "SELECT `trade_date`, COUNT(*) FROM `daily_kline` "
            "WHERE `trade_date` >= ? AND `change_pct` IS NOT NULL "
            "GROUP BY `trade_date`", (since,)).fetchall()
        complete = sorted(str(r[0]) for r in rows if (r[1] or 0) >= 2000)
        if len(complete) < 3:
            return 0
        pos = {d: i for i, d in enumerate(complete)}

        # ② 已算过的日子
        have = set()
        if not force:
            for r in conn.execute(
                    "SELECT `trade_date` FROM `market_seal_stats` WHERE `trade_date` >= ?",
                    (since,)).fetchall():
                have.add(str(r[0]))
        todo = [d for d in complete if pos[d] >= 2 and (force or d not in have)]
        if not todo:
            return 0

        # ③ ST 名单（评分口径 = 沪深主板非ST）
        st_codes = set()
        for r in conn.execute("SELECT `code`,`is_st`,`name` FROM `stock`").fetchall():
            nm = (r["name"] or "").upper().replace(" ", "")
            if r["is_st"] or ("ST" in nm):
                st_codes.add(clean_code(r["code"]))

        day_sql = ("SELECT k.`stock_code`, k.`high`, k.`close`, "
                   "k1.`high`, k1.`close`, k2.`close` "
                   "FROM `daily_kline` k "
                   "JOIN `daily_kline` k1 ON k1.`stock_code`=k.`stock_code` AND k1.`trade_date`=? "
                   "JOIN `daily_kline` k2 ON k2.`stock_code`=k.`stock_code` AND k2.`trade_date`=? "
                   "WHERE k.`trade_date`=? AND substr(k.`stock_code`,1,3) IN "
                   "('600','601','603','605','000','001','002','003')")
        upsert = _upsert("market_seal_stats",
                         ["trade_date", "up_count", "down_count", "flat_count",
                          "final_count", "sealed_count", "score", "src", "computed_at"],
                         ["trade_date"],
                         ["up_count", "down_count", "flat_count",
                          "final_count", "sealed_count", "score", "src", "computed_at"])
        ts = now_str()
        for d in todo:
            i = pos[d]
            d1, d2 = complete[i - 1], complete[i - 2]
            final = sealed = 0
            for r in conn.execute(day_sql, (d1, d2, d)).fetchall():
                code_, hi, cl, h1, c1, c2 = r[0], r[1], r[2], r[3], r[4], r[5]
                if code_ in st_codes:                  # 非 ST（与动态选股一致）
                    continue
                if not c1 or not c2 or not hi or h1 is None:
                    continue
                if h1 >= _limit_price(c2) - EPS_LIMIT:  # 昨日触及涨停 -> 剔除
                    continue
                if (hi - c1) / c1 > 0.09:               # 今日盘中冲高 > 9%
                    final += 1
                    if cl is not None and cl >= _limit_price(c1) - EPS_LIMIT:
                        sealed += 1
            agg = conn.execute(
                "SELECT SUM(`change_pct` > 0), SUM(`change_pct` < 0), SUM(`change_pct` = 0) "
                "FROM `daily_kline` WHERE `trade_date`=? AND `change_pct` IS NOT NULL",
                (d,)).fetchone()
            up = int(agg[0] or 0) if agg else 0
            down = int(agg[1] or 0) if agg else 0
            flat = int(agg[2] or 0) if agg else 0
            score = round(sealed / final * 100, 1) if final else None
            cur.execute(upsert, (d, up, down, flat, final, sealed, score, "kline", ts))
            n_done[0] += 1
            if progress:
                try:
                    progress(d, score)
                except Exception:
                    pass
        return n_done[0]

    out = _write(_f)
    if out:
        invalidate_market_stats()
    return out or 0


def ensure_seal_stats_async(min_interval=600.0):
    """若封板率统计落后于最新日K，后台补算（不阻塞页面）"""
    now = time.time()
    if _SEAL_STATE["running"] or (now - _SEAL_STATE["last_try"]) < min_interval:
        return False
    try:
        latest_k = _read(lambda c: c.execute("SELECT MAX(`trade_date`) FROM `daily_kline`").fetchone()[0], None)
        latest_s = _read(lambda c: c.execute("SELECT MAX(`trade_date`) FROM `market_seal_stats`").fetchone()[0], None)
    except Exception:
        return False
    if not latest_k:
        return False
    if latest_s and str(latest_s) >= str(latest_k):
        return False
    _SEAL_STATE["last_try"] = now
    _SEAL_STATE["running"] = True

    def _run():
        try:
            compute_seal_stats()
        except Exception:
            pass
        finally:
            _SEAL_STATE["running"] = False
    threading.Thread(target=_run, name="seal-stats", daemon=True).start()
    return True


def daily_market_stats(max_days=45, prefer_screening=True):
    """按日行情统计（读 market_seal_stats，秒出；带 120 秒缓存）

    返回 [{date, up, down, flat, final, sealed, score, src, breadth_src,
            amount, amount_prev, amount_diff}]（升序，最多 max_days 天）

    · 涨跌家数：优先用 market_breadth（实时抓取，沪深京全部A股口径，与同花顺一致），
                否则用离线统计里按本地日K算出的全市场家数
    · 行情评分：离线统计的封板率；若该日有真实选股结果则用真实值（更权威）
    """
    n = int(max_days)
    if prefer_screening:
        c = _STATS_CACHE
        if c["rows"] and c["n"] >= n and (time.time() - c["ts"]) < _STATS_TTL:
            return c["rows"][-n:]

    def _f(conn):
        head = conn.execute(
            "SELECT `trade_date`,`up_count`,`down_count`,`flat_count`,"
            "`final_count`,`sealed_count`,`score`,`src` FROM `market_seal_stats` "
            "ORDER BY `trade_date` DESC LIMIT ?", (n + 3,)).fetchall()
        if not head:
            return []
        rows = list(reversed(head))

        # 涨跌家数（实时抓取值优先）
        bmap = {}
        try:
            for r in conn.execute(
                    "SELECT `trade_date`,`up_count`,`down_count`,`flat_count` "
                    "FROM `market_breadth`").fetchall():
                bmap[r["trade_date"]] = (r["up_count"], r["down_count"], r["flat_count"])
        except Exception:
            bmap = {}
        # 两市成交额
        tmap = {}
        try:
            for r in conn.execute(
                    "SELECT `trade_date`,`amount` FROM `market_turnover`").fetchall():
                if r["amount"] is not None:
                    tmap[r["trade_date"]] = float(r["amount"])
        except Exception:
            tmap = {}
        # 真实选股结果（更权威）
        real = {}
        if prefer_screening:
            try:
                for r in conn.execute("SELECT target_date, payload_json FROM screening_run").fetchall():
                    try:
                        dd = json.loads(r["payload_json"])
                        if dd.get("success") and dd.get("sealedRate") is not None:
                            real[r["target_date"]] = float(dd["sealedRate"])
                    except Exception:
                        pass
            except Exception:
                real = {}

        out = []
        prev_amt = None
        for r in rows:
            d = str(r["trade_date"])
            up, down, flat = r["up_count"], r["down_count"], r["flat_count"]
            final, sealed = r["final_count"] or 0, r["sealed_count"] or 0
            bsrc = "kline"
            if d in bmap and bmap[d][0] is not None:
                up, down, flat = bmap[d][0], bmap[d][1], bmap[d][2]
                bsrc = "breadth"
            score, src = r["score"], r["src"] or "kline"
            if d in real:
                score = round(real[d], 1)
                src = "screening"
            amt = tmap.get(d)
            diff = (round(amt - prev_amt, 2)
                    if (amt is not None and prev_amt is not None) else None)
            prev_amt = amt if amt is not None else prev_amt
            out.append({"date": d, "up": up, "down": down, "flat": flat,
                        "final": final, "sealed": sealed, "score": score, "src": src,
                        "breadth_src": bsrc, "amount": amt, "amount_prev": None,
                        "amount_diff": diff})
        return out[-n:]
    rows = _read(_f, []) or []
    if not rows:
        # 首次使用（统计表还空着）-> 现算一次，保证页面有内容
        try:
            compute_seal_stats()
        except Exception:
            pass
        rows = _read(_f, []) or []
    if prefer_screening and rows:
        _STATS_CACHE["ts"] = time.time()
        _STATS_CACHE["n"] = n
        _STATS_CACHE["rows"] = rows
    return rows


def save_market_breadth(row, source="em_clist"):
    """写入每日涨跌家数（沪深京全部 A 股口径）

    row = {"date": "2026-10-13", "up": 2909, "down": 2486, "flat": 167,
           "total": 5923, "suspended": 361}
    """
    if not row or not (row.get("date") or row.get("trade_date")):
        return 0

    def _f(conn):
        cur = conn.cursor()
        sql = _upsert("market_breadth",
                      ["trade_date", "up_count", "down_count", "flat_count",
                       "total_count", "suspended", "source", "collected_at"],
                      ["trade_date"],
                      ["up_count", "down_count", "flat_count", "total_count",
                       "suspended", "source", "collected_at"])
        cur.execute(sql, (str(row.get("date") or row.get("trade_date")),
                          _int(row.get("up")), _int(row.get("down")),
                          _int(row.get("flat")), _int(row.get("total")),
                          _int(row.get("suspended")), source, now_str()))
        return 1
    n = _write(_f)
    if n:
        invalidate_market_stats()
    return n


def market_breadth_map(start=None, end=None):
    """读涨跌家数历史 -> {trade_date: {"up","down","flat","total","suspended"}}"""

    def _f(conn):
        sql = ("SELECT `trade_date`,`up_count`,`down_count`,`flat_count`,`total_count`,"
               "`suspended` FROM `market_breadth`")
        cond, args = [], []
        if start:
            cond.append("`trade_date`>=?"); args.append(start)
        if end:
            cond.append("`trade_date`<=?"); args.append(end)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        out = {}
        for r in conn.execute(sql, tuple(args)).fetchall():
            out[r["trade_date"]] = {"up": r["up_count"], "down": r["down_count"],
                                    "flat": r["flat_count"], "total": r["total_count"],
                                    "suspended": r["suspended"]}
        return out
    return _read(_f, {}) or {}


def save_turnover_batch(rows, source="em_index"):
    """写入每日两市成交额（单位：亿元）

    rows = [{"date": "2026-10-13", "sh": 7793.02, "sz": 8966.06, "amount": 16759.08}, ...]
    幂等：同一日期重复写入按 UPSERT 覆盖（保留最新一次）。
    """
    rows = [r for r in (rows or []) if r and (r.get("date") or r.get("trade_date"))]
    if not rows:
        return 0

    def _f(conn):
        cur = conn.cursor()
        sql = _upsert("market_turnover",
                      ["trade_date", "sh_amount", "sz_amount", "amount", "source", "collected_at"],
                      ["trade_date"],
                      ["sh_amount", "sz_amount", "amount", "source", "collected_at"])
        ts = now_str()
        n = 0
        for r in rows:
            cur.execute(sql, (str(r.get("date") or r.get("trade_date")),
                              _num(r.get("sh")), _num(r.get("sz")), _num(r.get("amount")),
                              source, ts))
            n += 1
        return n
    n = _write(_f)
    if n:
        invalidate_market_stats()
    return n


def market_turnover_map(start=None, end=None):
    """读「两市成交额」历史 -> {trade_date: 亿元}

    start/end 为 'YYYY-MM-DD'（含端点），留空表示不限。
    """

    def _f(conn):
        sql = "SELECT `trade_date`,`amount` FROM `market_turnover`"
        cond, args = [], []
        if start:
            cond.append("`trade_date`>=?"); args.append(start)
        if end:
            cond.append("`trade_date`<=?"); args.append(end)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        out = {}
        for r in conn.execute(sql, tuple(args)).fetchall():
            if r["amount"] is not None:
                try:
                    out[r["trade_date"]] = float(r["amount"])
                except Exception:
                    pass
        return out
    return _read(_f, {}) or {}


_STATS_CACHE = {"ts": 0.0, "n": 0, "rows": []}
_MONTHS_CACHE = {"ts": 0.0, "data": []}
_SEAL_STATE = {"running": False, "last_try": 0.0}
_STATS_TTL = 120.0         # 秒；读缓存
EPS_LIMIT = 0.001          # 涨停价比较容差


def save_stock_names(rows):
    """保存「代码 -> 名称」（来源：全市场行情列表），用于识别 ST 股

    rows = [{"code": "600340", "name": "*ST华业"}, ...]
    """
    rows = [r for r in (rows or []) if clean_code(r.get("code")) and (r.get("name") or "").strip()]
    if not rows:
        return 0

    def _f(conn):
        cur = conn.cursor()
        n = 0
        for r in rows:
            code = clean_code(r["code"])
            name = str(r["name"]).strip()
            if not code or not name:
                continue
            _upsert_stock(cur, code, name)
            cur.execute("UPDATE `stock` SET `is_st`=? WHERE `code`=?",
                        (1 if "ST" in name.upper().replace(" ", "") else 0, code))
            n += 1
        return n
    return _write(_f)


def st_stock_codes():
    """当前 ST / *ST 股票代码集合（用于「动态选股」口径的非ST过滤）

    优先读 stock.is_st 标记；没有标记的再按名称里是否含 ST 判断。
    """
    def _f(conn):
        out = set()
        for r in conn.execute(
                "SELECT `code`,`is_st`,`name` FROM `stock`").fetchall():
            nm = (r["name"] or "").upper().replace(" ", "")
            if r["is_st"] or ("ST" in nm):
                out.add(clean_code(r["code"]))
        return out
    return _read(_f, set()) or set()
