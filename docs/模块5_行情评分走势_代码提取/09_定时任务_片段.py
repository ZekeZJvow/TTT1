def _fetch_seal(target=None):
    """离线算好「每日封板率」并落库（只算缺的日子，一般 1 天）"""
    import market_db as _mdb
    return "封板率+%d天" % _mdb.compute_seal_stats()


def _fetch_breadth(target):
    """涨跌家数落库（沪深京全部 A 股口径 —— 与同花顺「涨跌分布」一致）"""
    import market_breadth as _mb
    row = _mb.sync_today(target)
    if not row:
        return "error: 涨跌家数抓取失败"
    return "涨%d 跌%d 平%d（共%d只）" % (row["up"], row["down"], row["flat"], row["total"])


def _fetch_turnover():
    """两市成交额（沪市 + 深市）落库：收盘后先取实时，再用指数日K覆盖最近 10 天"""
    import market_turnover as _mt
    return _mt.sync_recent(10)


# ---- run_daily_job 里挂上这 3 步（收盘后自动落库）----
#    step("turnover", _fetch_turnover)
#    step("breadth", lambda: _fetch_breadth(target))
#    step("sealstats", lambda: _fetch_seal(target))
