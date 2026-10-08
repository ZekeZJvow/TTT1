# -*- coding: utf-8 -*-
"""
定时任务：每日多时段抓取入库 + 完整性校验 + 自动补抓 + 推送

时段配置（AUTO_FETCH_SCHEDULES，默认见下）
------------------------------------------
  AUTO_FETCH_SCHEDULES="morning=11:35:light,close=15:30:full"
  格式： 名称=HH:MM:模式     模式： light（仅人气榜，快） / full（全量）
  旧变量 AUTO_FETCH_HOUR / AUTO_FETCH_MINUTE 仍可覆盖 close 时段。

行为
----
- 后台守护线程，每 60 秒检查一次
- 仅在交易日触发；已成功执行过的时段不重复（查 fetch_log 的 job:<名称>）
- 若同一时刻有多个时段到期（例如程序 20:00 才启动），
  只跑最晚的那个 full 任务，更早的 light 记为 skip（避免重复劳动）
- 失败后 10 分钟内不重试
- full 任务：抓取 → 完整性校验 → **缺失自动补抓** → 复校 → 推送
"""
import os
import sys
import time
import threading
from datetime import datetime

_STARTED = False
_THREAD = None
_LAST_ATTEMPT = {}
_COOLDOWN = 600
_INTERVAL = 60

DEFAULT_SCHEDULES = "morning=11:35:light,close=15:30:full"


def _log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        sys.stderr.write("[scheduler %s] %s\n" % (ts, msg))
        sys.stderr.flush()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def enabled():
    return str(os.environ.get("AUTO_FETCH_ENABLED", "1")).lower() not in (
        "0", "false", "no", "off")


def schedules():
    """返回 [{'name','hour','minute','mode','time_text'}]（按时间升序）

    配置格式： "morning=11:35:light,close=15:30:full"
    """
    raw = (os.environ.get("AUTO_FETCH_SCHEDULES") or DEFAULT_SCHEDULES).strip()
    out = []
    for part in raw.split(","):
        part = part.strip().replace(" ", "")
        if not part or "=" not in part:
            continue
        name, rest = part.split("=", 1)
        name = name.strip()
        pieces = rest.split(":")
        if len(pieces) < 2 or not name:
            continue
        try:
            h, m = int(pieces[0]), int(pieces[1])
        except Exception:
            continue
        mode = pieces[2].strip() if len(pieces) > 2 else "full"
        if mode not in ("light", "full"):
            mode = "full"
        out.append({"name": name, "hour": h, "minute": m, "mode": mode,
                    "time_text": "%02d:%02d" % (h, m)})

    # 兼容旧的 AUTO_FETCH_HOUR/MINUTE（覆盖 close 时段）
    for env_k, env_v in (("hour", os.environ.get("AUTO_FETCH_HOUR")),
                         ("minute", os.environ.get("AUTO_FETCH_MINUTE"))):
        if env_v is None:
            continue
        for sc in out:
            if sc["name"] == "close":
                try:
                    sc[env_k] = int(env_v)
                except Exception:
                    pass
    for sc in out:
        sc["time_text"] = "%02d:%02d" % (sc["hour"], sc["minute"])
    out.sort(key=lambda s: (s["hour"] * 60 + s["minute"], s["mode"] == "light"))
    return out


def schedules_text():
    return "、".join("%s@%s(%s)" % (s["name"], s["time_text"], s["mode"]) for s in schedules())


# ---------------------------------------------------------------------------
# 启动 / 循环
# ---------------------------------------------------------------------------

def start_if_enabled():
    global _STARTED, _THREAD
    if _STARTED or not enabled():
        return False
    _STARTED = True
    _THREAD = threading.Thread(target=_loop, name="auto-fetch", daemon=True)
    _THREAD.start()
    _log("定时任务已启动：%s" % schedules_text())
    return True


def _loop():
    time.sleep(20)
    while True:
        try:
            tick()
        except Exception as e:
            _log("tick 异常: %s" % e)
        time.sleep(_INTERVAL)


def tick(now=None):
    now = now or datetime.now()
    if not enabled():
        return False
    import server as _server
    import market_db as _mdb

    today = now.strftime("%Y-%m-%d")
    try:
        days = set(_server._trading_calendar(60))
    except Exception:
        return False
    if today not in days:
        return False

    mins = now.hour * 60 + now.minute
    due = []
    for sc in schedules():
        if mins < (sc["hour"] * 60 + sc["minute"]):
            continue
        try:
            if _mdb.has_fetch_log("job:%s" % sc["name"], today, "ok"):
                continue
        except Exception:
            pass
        key = (today, sc["name"])
        last = _LAST_ATTEMPT.get(key)
        if last and (time.time() - last) < _COOLDOWN:
            continue
        due.append(sc)

    if not due:
        return False

    # 有 full 到期 -> 只跑最晚的那个 full，其余记为 skip
    fulls = [s for s in due if s["mode"] == "full"]
    if fulls:
        keep = max(fulls, key=lambda s: s["hour"] * 60 + s["minute"])
        for s in due:
            if s is not keep:
                try:
                    _mdb.log_fetch("job:%s" % s["name"], trade_date=today, status="skip",
                                   detail="被 %s 的完整任务覆盖" % keep["name"])
                except Exception:
                    pass
        due = [keep]

    fired = False
    for sc in due:
        _LAST_ATTEMPT[(today, sc["name"])] = time.time()
        run_job(sc["name"], sc["mode"], today)
        fired = True
    return fired


# ---------------------------------------------------------------------------
# 抓取步骤（run_job 与补抓共用）
# ---------------------------------------------------------------------------

def _fetch_calendar():
    import screener
    import market_db as _mdb
    d = screener.get_trading_days(400)
    if d:
        _mdb.save_calendar(d)
    return "days=%d" % len(d or [])


def _fetch_hotlist(target):
    import server as _server
    import market_db as _mdb
    rows, source, degraded, err = _server.build_hotlist_live()
    if rows is None:
        raise RuntimeError(err)
    _mdb.save_hotlist(target, rows, source=source, degraded=degraded)
    _mdb.log_fetch("hotlist", source=source, trade_date=target, rows=len(rows),
                   status="degraded" if degraded else "ok", detail="auto")
    return "rows=%d source=%s" % (len(rows), source)


def _fetch_scan(target):
    import screener
    import market_db as _mdb
    res = screener.run_screen(target)
    if not res.get("success"):
        raise RuntimeError(res.get("error"))
    _mdb.save_screening(res)
    return "final=%s" % (res.get("funnel", {}).get("final"))


def _fetch_themes(target):
    import event_theme_service as _et
    import market_db as _mdb
    res = _et.build_event_themes(6, 10)
    if not res.get("success"):
        raise RuntimeError(res.get("error") or res.get("message"))
    _mdb.save_event_themes(res, trade_date=target)
    return "themes=%s" % res.get("themeCount")


# ---------------------------------------------------------------------------
# 自动补抓：按缺失项做针对性重抓
# ---------------------------------------------------------------------------

_REPAIR_MAP = {
    "trade_calendar": ("calendar", _fetch_calendar),
    "hotlist_snapshot": ("hotlist", None),          # 需 target，下面特殊处理
    "limit_up_pool": ("scan", None),
    "daily_kline": ("scan", None),
    "screening_run": ("scan", None),
    "screening_result": ("scan", None),
    "theme_heat_snapshot": ("themes", None),
    "theme_top_stock": ("themes", None),
}


def repair_missing(target, integrity):
    """针对缺失项重新抓取。返回 {'actions': [...], 'summary': str}"""
    import market_db as _mdb
    failed = [i for i in (integrity.get("items") or []) if not i.get("ok")]
    if not failed:
        return {"actions": [], "summary": "无需补抓"}

    want = []
    for it in failed:
        key = _REPAIR_MAP.get(it["table"], (None, None))[0]
        if key and key not in want:
            want.append(key)

    def _run(key):
        if key == "calendar":
            return _fetch_calendar()
        if key == "hotlist":
            return _fetch_hotlist(target)
        if key == "scan":
            return _fetch_scan(target)
        if key == "themes":
            return _fetch_themes(target)
        return "unknown"

    actions = []
    for key in want:
        t0 = time.time()
        try:
            detail = _run(key)
            actions.append({"action": key, "ok": True, "detail": detail,
                            "elapsed": round(time.time() - t0, 1)})
            _log("补抓 %s -> %s" % (key, detail))
        except Exception as e:
            actions.append({"action": key, "ok": False, "detail": str(e),
                            "elapsed": round(time.time() - t0, 1)})
            _log("补抓 %s 失败: %s" % (key, e))
    try:
        _mdb.log_fetch("repair", trade_date=target,
                       status="ok" if all(a["ok"] for a in actions) else "partial",
                       detail=str([(a["action"], a["ok"]) for a in actions]))
    except Exception:
        pass
    okn = sum(1 for a in actions if a["ok"])
    return {"actions": actions, "summary": "补抓 %d/%d 成功" % (okn, len(actions))}


# ---------------------------------------------------------------------------
# 任务编排
# ---------------------------------------------------------------------------

def _make_step(result, progress):
    def step(name, fn):
        try:
            v = fn()
            result["steps"][name] = v if v is not None else "ok"
        except Exception as e:
            result["steps"][name] = "error: %s" % e
            _log("%s 失败: %s" % (name, e))
        if progress:
            try:
                progress(name, result["steps"][name])
            except Exception:
                pass
    return step


def _notify_step(result, integrity, target):
    try:
        import notifier
    except Exception as e:
        return "notifier unavailable: %s" % e
    if not notifier.channels():
        return "skipped(未配置通知通道)"
    if not notifier.should_send(integrity.get("ok", False)):
        return "skipped(策略=仅异常时发送且本次正常)"
    try:
        import market_db as _mdb
        title, text = notifier.format_summary(result, integrity, _mdb.stats(), target)
        res = notifier.send(title, text, meta={
            "trade_date": target, "job": result.get("job"),
            "ok": bool(result.get("ok")), "integrity_ok": bool(integrity.get("ok"))})
        good = sum(1 for r in res if r.get("ok"))
        return "sent %d/%d" % (good, len(res))
    except Exception as e:
        return "error: %s" % e


def run_job(name="close", mode="full", target_date=None, progress=None):
    """统一入口：mode=light -> 轻量（人气榜）；mode=full -> 全量"""
    if mode == "light":
        return run_light_job(name, target_date, progress)
    return run_daily_job(target_date, progress, name=name)


# ---------------------------------------------------------------------------
# 轻量任务（早盘：只抓人气榜，~5 秒）
# ---------------------------------------------------------------------------

def run_light_job(name="morning", target_date=None, progress=None):
    import server as _server
    import market_db as _mdb

    t0 = time.time()
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target = target_date or _server._session_date()
    result = {"target": target, "job": name, "mode": "light",
              "steps": {}, "started_at": started}
    step = _make_step(result, progress)

    step("hotlist", lambda: _fetch_hotlist(target))

    integrity = {}

    def _ic():
        nonlocal integrity
        integrity = _mdb.integrity_check(target, only=["hotlist_snapshot"])
        return "ok" if integrity.get("ok") else "issues=%d" % len(integrity.get("issues") or [])
    step("integrity", _ic)

    result["integrity"] = integrity
    result["ok"] = all(not str(v).startswith("error") for v in result["steps"].values())
    result["elapsed"] = round(time.time() - t0, 1)

    step("notify", lambda: _notify_step(result, integrity, target))

    try:
        _mdb.log_fetch("job:%s" % name, source="scheduler", trade_date=target,
                       status="ok" if result["ok"] else "partial",
                       duration_ms=int(result["elapsed"] * 1000),
                       detail=str(result["steps"]), started_at=started)
    except Exception:
        pass
    _log("轻量任务完成 job=%s target=%s ok=%s 用时%.1fs"
         % (name, target, result["ok"], result["elapsed"]))
    return result


# ---------------------------------------------------------------------------
# 全量任务（尾盘：日历 + 人气榜 + 全市场扫描 + 题材），含完整性校验与自动补抓
# ---------------------------------------------------------------------------

def run_daily_job(target_date=None, progress=None, name="close"):
    import server as _server
    import market_db as _mdb

    t0 = time.time()
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target = target_date or _server._session_date()
    result = {"target": target, "job": name, "mode": "full",
              "steps": {}, "started_at": started}
    step = _make_step(result, progress)

    step("calendar", _fetch_calendar)
    step("hotlist", lambda: _fetch_hotlist(target))
    step("screen", lambda: _fetch_scan(target))
    step("themes", lambda: _fetch_themes(target))

    # 1) 第一次完整性校验
    integrity = {}

    def _ic():
        nonlocal integrity
        integrity = _mdb.integrity_check(target)
        return "ok" if integrity.get("ok") else "issues=%d" % len(integrity.get("issues") or [])
    step("integrity", _ic)

    # 2) 缺失则自动补抓
    repair = {}

    def _rep():
        nonlocal repair
        if integrity.get("ok"):
            return "无需补抓"
        repair = repair_missing(target, integrity)
        return repair.get("summary") or "已补抓"
    step("repair", _rep)

    # 3) 补抓后复校
    def _recheck():
        nonlocal integrity
        if integrity.get("ok"):
            return "ok(首检已通过)"
        integrity = _mdb.integrity_check(target)
        return "ok" if integrity.get("ok") else "issues=%d" % len(integrity.get("issues") or [])
    step("recheck", _recheck)

    result["repair"] = repair
    result["ok"] = all(not str(v).startswith("error") for v in result["steps"].values())
    result["integrity"] = integrity
    result["elapsed"] = round(time.time() - t0, 1)

    # 4) 推送
    step("notify", lambda: _notify_step(result, integrity, target))

    try:
        _mdb.log_fetch("job:%s" % name, source="scheduler", trade_date=target,
                       status="ok" if result["ok"] else "partial",
                       duration_ms=int(result["elapsed"] * 1000),
                       detail=str(result["steps"]), started_at=started)
        _mdb.log_fetch("integrity", trade_date=target,
                       status="ok" if integrity.get("ok") else "issues",
                       detail="; ".join(integrity.get("issues") or []) or "全部通过")
    except Exception:
        pass
    _log("全量任务完成 job=%s target=%s ok=%s 完整性=%s 用时%.1fs"
         % (name, target, result["ok"],
            "通过" if integrity.get("ok") else "不通过", result["elapsed"]))
    return result
