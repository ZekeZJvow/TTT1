@app.route("/api/market-history")
def market_history_api():
    """每日行情评分 + 涨跌家数（近 N 天，默认 45 天）"""
    try:
        days = int(request.args.get("days", 45))
    except Exception:
        days = 45
    days = max(5, min(days, 120))
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    # 窗口：默认 120 天；指定了开始日期就往前覆盖到那天（最多 500 天）
    n = 120
    if start:
        try:
            _need = (datetime.now().date()
                     - datetime.strptime(start, "%Y-%m-%d").date()).days + 30
            n = max(120, min(_need, 500))
        except Exception:
            n = 260
    try:
        # 内部有缓存（写入入库时会主动清），重复请求不再重算
        rows = _mdb.daily_market_stats(n)
        # 统计落后于最新日K时，后台补算（不阻塞本次响应）
        try:
            _mdb.ensure_seal_stats_async()
        except Exception:
            pass
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    if start:
        rows = [x for x in rows if x["date"] >= start]
    if end:
        rows = [x for x in rows if x["date"] <= end]
    if not (start or end):
        rows = rows[-days:]
    try:
        months = _mdb.available_months()
    except Exception:
        months = []
    return jsonify({"success": True, "days": days, "start": start, "end": end,
                    "rows": rows, "count": len(rows), "months": months})


# ---- 启动时预热（run_server 内）----
def _prewarm():
        """后台预热行情统计（行情评分走势），首次打开就不用等"""
        try:
            time.sleep(3)
            import market_db as _m
            _m.compute_seal_stats()          # 只补缺的日子，通常 0 天
            _m.daily_market_stats(500)       # 预热读缓存
            _m.available_months()
        except Exception:
            pass
    try:
        threading.Thread(target=_prewarm, name="stats-prewarm", daemon=True).start()
    except Exception:
        pass
