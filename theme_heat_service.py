# -*- coding: utf-8 -*-
"""Current A-share theme heat ranking based on hithink-finance.

The service deliberately treats the CLI as a scarce resource:

1. all CLI subprocesses share a small global concurrency gate;
2. identical requests are collapsed into one in-flight computation;
3. immutable/slow-moving data is cached in memory and on disk;
4. hot-stock top-30 data is used directly where possible, and the
   single-stock trend endpoint is only used for rows that cross the
   top-30 boundary during the comparison window.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import random
import shutil
import sqlite3
import subprocess
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE_NAMESPACE = "v3"   # v3: 题材 Top50 增加「涨跌幅」，命名空间 +1 强制重建

_CACHE: Dict[str, Tuple[float, Any]] = {}
_CACHE_LOCK = threading.RLock()
_INFLIGHT: Dict[str, concurrent.futures.Future] = {}
_INFLIGHT_LOCK = threading.Lock()
_QUERY_LOCKS: Dict[str, threading.Lock] = {}
_QUERY_LOCKS_LOCK = threading.Lock()

_CACHE_DB = os.environ.get("THEME_HEAT_CACHE_DB", os.path.join(HERE, "theme_heat_cache.sqlite3"))
_DB_LOCK = threading.Lock()
_DB_READY = False

_CATALOG_TTL = 12 * 3600
_QUERY_TTL = 300
_HOT_TTL = 120
_HISTORY_TTL = 30 * 24 * 3600
_SNAPSHOT_TTL = 45
_LHB_TTL = 1800
_TREND_TTL = 600

_CLI_CONCURRENCY = max(1, min(4, int(os.environ.get("HITHINK_FINANCE_CONCURRENCY", "2") or "2")))
_RETRY_LIMIT = max(0, min(2, int(os.environ.get("HITHINK_FINANCE_RETRIES", "1") or "1")))
_TREND_LOOKUP_LIMIT = max(0, min(30, int(os.environ.get("THEME_HEAT_TREND_LOOKUP_LIMIT", "8") or "8")))
_SNAPSHOT_BATCH_SIZE = 500
_CLI_GATE = threading.BoundedSemaphore(_CLI_CONCURRENCY)

_STATS_LOCK = threading.Lock()
_CLI_STATS = {
    "calls": 0,
    "retries": 0,
    "errors": 0,
    "active": 0,
    "max_active": 0,
}

THEME_ALIASES: Dict[str, List[str]] = {
    "房贷贴息": ["房地产", "物业管理", "家用电器", "家居用品", "建筑材料"],
    "地产链": ["房地产", "物业管理", "建筑装饰", "建筑材料", "家用电器", "家居用品"],
    "地产": ["房地产", "物业管理", "建筑装饰", "建筑材料"],
    "房地产": ["房地产", "物业管理", "建筑装饰", "建筑材料"],
    "家电": ["家用电器", "白色家电", "小家电"],
    "家居": ["家居用品", "成品家居", "定制家居"],
    "建材": ["建筑材料", "水泥", "玻璃玻纤", "其他建材"],
}


def _cli_candidates() -> List[str]:
    """候选 CLI 路径。

    workbuddy 托管的 node 版本号会变（22.22.2-3 / 22.22.2-6 / …），
    所以这里动态扫描 ~/.workbuddy/binaries/node/versions/*/hithink-finance.cmd，
    避免写死版本号后因升级 node 而误判为 CLI_MISSING。
    """
    home = os.path.expanduser("~")
    values = [
        os.environ.get("HITHINK_FINANCE_CLI", ""),
        shutil.which("hithink-finance") or "",
        os.path.join(home, ".local", "bin", "hithink-finance.cmd"),
    ]
    vdir = os.path.join(home, ".workbuddy", "binaries", "node", "versions")
    try:
        for d in sorted(os.listdir(vdir), reverse=True):     # 新版本优先
            values.append(os.path.join(vdir, d, "hithink-finance.cmd"))
    except OSError:
        pass
    return [v for v in values if v and os.path.exists(v)]


CLI = next(iter(_cli_candidates()), "hithink-finance")
_SPAWN_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# Cache primitives
# ---------------------------------------------------------------------------

def _ensure_db() -> None:
    global _DB_READY
    if _DB_READY:
        return
    with _DB_LOCK:
        if _DB_READY:
            return
        parent = os.path.dirname(_CACHE_DB) or "."
        os.makedirs(parent, exist_ok=True)
        with sqlite3.connect(_CACHE_DB, timeout=3) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                "cache_key TEXT PRIMARY KEY, "
                "saved_at REAL NOT NULL, "
                "payload TEXT NOT NULL"
                ")"
            )
            con.execute(
                "DELETE FROM cache WHERE saved_at < ?",
                (time.time() - 90 * 24 * 3600,),
            )
            con.commit()
        _DB_READY = True


def _disk_cache_get(key: str) -> Optional[Tuple[float, Any]]:
    try:
        _ensure_db()
        with sqlite3.connect(_CACHE_DB, timeout=3) as con:
            row = con.execute(
                "SELECT saved_at, payload FROM cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row:
            return float(row[0]), json.loads(row[1])
    except Exception:
        return None
    return None


def _disk_cache_set(key: str, saved_at: float, value: Any) -> None:
    try:
        _ensure_db()
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with sqlite3.connect(_CACHE_DB, timeout=3) as con:
            con.execute(
                "INSERT OR REPLACE INTO cache (cache_key, saved_at, payload) VALUES (?, ?, ?)",
                (key, saved_at, payload),
            )
            con.commit()
    except Exception:
        # Cache failures must never make a data query fail.
        return


def _cache_get_raw(key: str) -> Optional[Tuple[float, Any]]:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit

    disk_hit = _disk_cache_get(key)
    if disk_hit is not None:
        with _CACHE_LOCK:
            _CACHE[key] = disk_hit
        return disk_hit
    return None


def _cache_get(key: str, ttl: int) -> Any:
    hit = _cache_get_raw(key)
    if hit is not None and time.time() - hit[0] < ttl:
        return hit[1]
    return None


def _cache_set(key: str, value: Any) -> Any:
    saved_at = time.time()
    with _CACHE_LOCK:
        _CACHE[key] = (saved_at, value)
    _disk_cache_set(key, saved_at, value)
    return value


def _memoized(
    key: str,
    ttl: int,
    loader: Callable[[], Any],
    *,
    allow_stale: bool = True,
) -> Any:
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached

    owner = False
    with _INFLIGHT_LOCK:
        future = _INFLIGHT.get(key)
        if future is None:
            future = concurrent.futures.Future()
            _INFLIGHT[key] = future
            owner = True

    if not owner:
        return future.result()

    try:
        value = loader()
        _cache_set(key, value)
        future.set_result(value)
        return value
    except BaseException as exc:
        stale = _cache_get_raw(key)
        if allow_stale and stale is not None:
            future.set_result(stale[1])
            return stale[1]
        future.set_exception(exc)
        raise
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(key, None)


def _clear_all_caches() -> None:
    """Clear memory and disk caches. Intended for diagnostics/tests."""
    with _CACHE_LOCK:
        _CACHE.clear()
    try:
        _ensure_db()
        with sqlite3.connect(_CACHE_DB, timeout=3) as con:
            con.execute("DELETE FROM cache")
            con.commit()
    except Exception:
        pass


def _stats_snapshot() -> Dict[str, int]:
    with _STATS_LOCK:
        return dict(_CLI_STATS)


def _stats_reset() -> None:
    with _STATS_LOCK:
        for key in _CLI_STATS:
            _CLI_STATS[key] = 0


def _bump_stat(name: str, delta: int = 1) -> None:
    with _STATS_LOCK:
        _CLI_STATS[name] = _CLI_STATS.get(name, 0) + delta


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, FileNotFoundError):
        return False
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError, ConnectionError, OSError)):
        return True

    message = str(exc).lower()
    markers = (
        "timed out",
        "timeout",
        "connection",
        "network",
        "temporarily",
        "temporary",
        "busy",
        "rate limit",
        "too many requests",
        "econn",
        "socket",
        " 429",
        " 500",
        " 502",
        " 503",
        " 504",
    )
    return any(marker in message for marker in markers)


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                creationflags=_SPAWN_FLAGS,
            )
        except Exception:
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def _execute_cli(args: List[str], timeout: int) -> subprocess.CompletedProcess:
    with _CLI_GATE:
        with _STATS_LOCK:
            _CLI_STATS["calls"] += 1
            _CLI_STATS["active"] += 1
            _CLI_STATS["max_active"] = max(_CLI_STATS["max_active"], _CLI_STATS["active"])
        try:
            proc = subprocess.Popen(
                [CLI] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=HERE,
                creationflags=_SPAWN_FLAGS,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(proc)
                stdout, stderr = proc.communicate()
                raise TimeoutError("hithink-finance timed out after %s seconds" % timeout)
            return subprocess.CompletedProcess([CLI] + args, proc.returncode, stdout, stderr)
        finally:
            with _STATS_LOCK:
                _CLI_STATS["active"] -= 1


def _run_json(args: List[str], timeout: int = 45) -> Dict[str, Any]:
    attempt = 0
    while True:
        try:
            proc = _execute_cli(args, timeout)
            if proc.returncode != 0:
                message = (proc.stderr or proc.stdout or "").strip()
                raise RuntimeError(
                    "hithink-finance %s failed (rc=%s): %s"
                    % (" ".join(args[:3]), proc.returncode, message[:500])
                )
            text = (proc.stdout or "").strip()
            if not text:
                raise RuntimeError("hithink-finance returned empty output")
            obj = json.loads(text)
            if not obj.get("ok", False):
                err = obj.get("error") or {}
                raise RuntimeError(err.get("message") or "hithink-finance returned ok=false")
            return obj
        except Exception as exc:
            _bump_stat("errors")
            if attempt >= _RETRY_LIMIT or not _is_transient(exc):
                raise
            attempt += 1
            _bump_stat("retries")
            time.sleep(min(4.0, 0.6 * (2 ** attempt)) + random.uniform(0.0, 0.25))


def _cache_key_for_args(args: List[str]) -> str:
    encoded = json.dumps(args, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "cli:%s:%s" % (_CACHE_NAMESPACE, hashlib.sha256(encoded).hexdigest())


def _cached_json(args: List[str], ttl: int, timeout: int = 45) -> Dict[str, Any]:
    key = _cache_key_for_args(args)
    return _memoized(key, ttl, lambda: _run_json(args, timeout=timeout))


# ---------------------------------------------------------------------------
# hithink-finance data adapters
# ---------------------------------------------------------------------------

def _catalog(tag: str) -> List[Dict[str, Any]]:
    obj = _cached_json(["index", "catalog", "--tag", tag, "--format", "json"], _CATALOG_TTL, timeout=60)
    data = obj.get("data") or {}
    items = data.get("item") if isinstance(data, dict) else data
    return list(items or [])


def _normalise_theme(theme: str) -> str:
    return "".join((theme or "").strip().lower().split())


def _indices_key(theme: str, max_indices: int) -> str:
    return "indices:%s:%s:%s" % (_CACHE_NAMESPACE, theme, max_indices)


def _resolve_indices_uncached(theme: str, max_indices: int) -> List[Dict[str, str]]:
    catalogs = [("cn_concept", _catalog("cn_concept")), ("industry", _catalog("industry"))]
    alias_names = [x.lower() for x in THEME_ALIASES.get(theme, [])]
    ranked = []
    for tag, items in catalogs:
        for item in items:
            name = str(item.get("name") or "")
            code = str(item.get("thscode") or "")
            if not name or not code:
                continue
            low = name.lower()
            score = 0
            if low in alias_names:
                score = 1000 - alias_names.index(low)
            elif theme == low:
                score = 900
            elif theme in low:
                score = 700 - min(len(low), 100)
            elif low in theme:
                score = 600 - min(len(low), 100)
            if score:
                ranked.append((score, {"name": name, "thscode": code, "tag": tag}))

    ranked.sort(key=lambda x: (-x[0], len(x[1]["name"]), x[1]["name"]))
    out = []
    seen = set()
    for _, item in ranked:
        if item["thscode"] in seen:
            continue
        seen.add(item["thscode"])
        out.append(item)
        if len(out) >= max_indices:
            break
    return out


def resolve_indices(theme: str, max_indices: int = 6) -> List[Dict[str, str]]:
    normalized = _normalise_theme(theme)
    if not normalized:
        return []
    return _memoized(
        _indices_key(normalized, max_indices),
        _CATALOG_TTL,
        lambda: _resolve_indices_uncached(normalized, max_indices),
    )


def _constituents(index_code: str) -> List[Dict[str, str]]:
    def load() -> List[Dict[str, str]]:
        obj = _cached_json(
            ["index", "constituents", "--thscode", index_code, "--format", "json"],
            _CATALOG_TTL,
            timeout=60,
        )
        items = list((obj.get("data") or {}).get("item") or [])
        return [
            {
                "thscode": str(x.get("thscode") or ""),
                "ticker": str(x.get("ticker") or ""),
                "name": str(x.get("name") or ""),
            }
            for x in items
            if x.get("thscode")
        ]

    return _memoized("constituents:%s:%s" % (_CACHE_NAMESPACE, index_code), _CATALOG_TTL, load)


def _market_snapshot(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    unique = sorted({str(code) for code in codes if code})
    if not unique:
        return {}

    def load_batch(batch: List[str]) -> List[Dict[str, Any]]:
        obj = _cached_json(
            [
                "market",
                "snapshot",
                "--thscodes",
                ",".join(batch),
                "--limit",
                "500",
                "--format",
                "json",
            ],
            _SNAPSHOT_TTL,
            timeout=60,
        )
        return list((obj.get("data") or {}).get("item") or [])

    batches = [unique[i:i + _SNAPSHOT_BATCH_SIZE] for i in range(0, len(unique), _SNAPSHOT_BATCH_SIZE)]
    out: Dict[str, Dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(_CLI_CONCURRENCY, len(batches))) as ex:
        for rows in ex.map(load_batch, batches):
            for item in rows:
                code = str(item.get("thscode") or "")
                if code:
                    out[code] = item
    return out


def _hot_list(period: str = "day") -> Dict[str, Any]:
    obj = _cached_json(
        ["special", "hot-stock", "--period", period, "--format", "json"],
        _HOT_TTL,
        timeout=30,
    )
    data = obj.get("data") or {}
    return {
        "items": list(data.get("item") or []),
        "as_of": _timestamp_to_date(data.get("timestamp")) or datetime.now().strftime("%Y-%m-%d"),
    }


def _hot_history(date: str) -> Dict[str, Any]:
    ttl = _HOT_TTL if date >= datetime.now().strftime("%Y-%m-%d") else _HISTORY_TTL
    obj = _cached_json(
        ["special", "hot-stock-history", "--date", date, "--format", "json"],
        ttl,
        timeout=30,
    )
    data = obj.get("data") or {}
    return {
        "items": list(data.get("item") or []),
        "as_of": str(data.get("date") or date),
    }


def _hot_trend(code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    obj = _cached_json(
        [
            "special",
            "hot-stock-trend",
            "--thscode",
            code,
            "--start-date",
            start_date,
            "--end-date",
            end_date,
            "--format",
            "json",
        ],
        _TREND_TTL,
        timeout=35,
    )
    return list((obj.get("data") or {}).get("item") or [])


def _latest_lhb() -> Dict[str, Dict[str, Any]]:
    def load() -> Dict[str, Dict[str, Any]]:
        obj = _cached_json(
            ["special", "dragon-tiger", "--board-type", "all", "--format", "json"],
            _LHB_TTL,
            timeout=60,
        )
        data = obj.get("data") or {}
        rows = {}
        for item in list(data.get("stock_items") or []):
            if item.get("range_days") is not None and int(item.get("range_days") or 0) != 1:
                continue
            code = str(item.get("thscode") or "")
            if not code:
                continue
            row = rows.setdefault(
                code,
                {
                    "net": 0.0,
                    "org": 0.0,
                    "hot_money": 0.0,
                    "amount": 0.0,
                    "net_rate": None,
                    "trade_date": data.get("trade_date"),
                },
            )
            row["net"] += float(item.get("net_value") or 0)
            row["org"] += float(item.get("org_net_value") or 0)
            row["hot_money"] += float(item.get("hot_money_net_value") or 0)
            row["amount"] += float(item.get("amount") or 0)
            if item.get("net_rate") is not None:
                row["net_rate"] = float(item.get("net_rate"))
        return rows

    return _memoized("lhb:%s:latest" % _CACHE_NAMESPACE, _LHB_TTL, load)


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 自动发现近期热门题材
# ---------------------------------------------------------------------------

_HOT_THEME_TTL = 15 * 60
_MIN_TURNOVER = 1e8          # 成交额门槛（元），剔除冷门指数


def _catalog_all() -> List[Dict[str, str]]:
    """概念 + 行业 指数目录合并"""
    out: List[Dict[str, str]] = []
    seen = set()
    for tag in ("cn_concept", "industry"):
        for it in _catalog(tag):
            code = str(it.get("thscode") or "")
            name = str(it.get("name") or "")
            if code and name and code not in seen:
                seen.add(code)
                out.append({"name": name, "thscode": code, "tag": tag})
    return out


def _index_snapshot(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """指数行情快照（分批并发）"""
    unique = sorted({str(c) for c in codes if c})
    if not unique:
        return {}

    def load_batch(batch: List[str]) -> List[Dict[str, Any]]:
        obj = _cached_json(
            ["index", "snapshot", "--thscodes", ",".join(batch), "--format", "json"],
            _SNAPSHOT_TTL,
            timeout=60,
        )
        return list((obj.get("data") or {}).get("item") or [])

    batches = [unique[i:i + _SNAPSHOT_BATCH_SIZE] for i in range(0, len(unique), _SNAPSHOT_BATCH_SIZE)]
    out: Dict[str, Dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(_CLI_CONCURRENCY, max(1, len(batches)))) as ex:
        for rows in ex.map(load_batch, batches):
            for it in rows:
                code = str(it.get("thscode") or "")
                if code:
                    out[code] = it
    return out


def _index_history(codes: List[str], days: int) -> Dict[str, List[Dict[str, Any]]]:
    """指数日线（逐个并发；CLI 仅支持单指数）"""
    now = datetime.now()
    end_ms = int(now.timestamp() * 1000)
    start_ms = int((now - timedelta(days=days)).timestamp() * 1000)

    def one(code: str):
        obj = _cached_json(
            ["index", "history", "--thscode", code, "--start-ms", str(start_ms),
             "--end-ms", str(end_ms), "--format", "json"],
            _TREND_TTL,
            timeout=45,
        )
        return code, list((obj.get("data") or {}).get("item") or [])

    out: Dict[str, List[Dict[str, Any]]] = {}
    if not codes:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(_CLI_CONCURRENCY, max(1, len(codes)))) as ex:
        for code, rows in ex.map(one, codes):
            out[code] = rows
    return out


def _discover_uncached(limit: int, lookback: int) -> Dict[str, Any]:
    t0 = time.time()
    cats = _catalog_all()
    if not cats:
        return {"success": False, "error": "指数目录获取失败"}

    snap = _index_snapshot([c["thscode"] for c in cats])

    rows: List[Dict[str, Any]] = []
    for c in cats:
        s = snap.get(c["thscode"])
        if not s:
            continue
        try:
            d1 = float(s.get("price_change_ratio_pct"))
        except (TypeError, ValueError):
            continue
        try:
            turnover = float(s.get("turnover") or 0)
        except (TypeError, ValueError):
            turnover = 0.0
        rows.append({
            "name": c["name"],
            "thscode": c["thscode"],
            "tag": c["tag"],
            "d1": round(d1, 2),
            "turnover": turnover,
        })

    if not rows:
        return {"success": False, "error": "指数快照为空"}

    liquid = [r for r in rows if r["turnover"] >= _MIN_TURNOVER]
    pool = liquid if len(liquid) >= limit * 2 else rows

    pool.sort(key=lambda r: -r["d1"])
    cand = pool[:max(limit * 2, 24)]

    hist = _index_history([r["thscode"] for r in cand], days=max(lookback * 2 + 6, 15))
    for r in cand:
        closes = [b.get("close_price") for b in (hist.get(r["thscode"]) or []) if b.get("close_price")]
        d5 = None
        if len(closes) >= lookback + 1:
            base = closes[-(lookback + 1)]
            if base:
                d5 = (closes[-1] - base) / base * 100.0
        r["d5"] = round(d5, 2) if d5 is not None else None
        r["score"] = round(r["d1"] + (d5 or 0.0) * 0.6, 2)

    cand.sort(key=lambda r: -r["score"])
    top = cand[:limit]

    return {
        "success": True,
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "lookback": lookback,
        "scanned": len(rows),
        "liquid": len(liquid),
        "rows": top,
        "method": "全量概念+行业指数快照按最新涨幅初筛，再叠加近%d日涨幅加权排序（score = 当日涨幅 + 近%d日涨幅 x 0.6）"
                  % (lookback, lookback),
        "note": "初筛只看当日强势品种，因此「近%d日强、当日弱」的题材可能不入榜。" % lookback,
        "elapsed": round(time.time() - t0, 2),
    }


def discover_hot_themes(limit: int = 12, lookback: int = 5) -> Dict[str, Any]:
    """自动发现近期热门题材"""
    limit = max(3, min(int(limit or 12), 30))
    lookback = max(2, min(int(lookback or 5), 20))
    try:
        return _memoized(
            "hot-themes:%s:%s:%s" % (_CACHE_NAMESPACE, limit, lookback),
            _HOT_THEME_TTL,
            lambda: _discover_uncached(limit, lookback),
        )
    except Exception as exc:
        return {"success": False, "error": "题材发现失败: %s" % exc}


def _timestamp_to_date(value: Any) -> Optional[str]:
    try:
        number = float(value)
        if number > 1e12:
            number /= 1000.0
        return datetime.fromtimestamp(number).strftime("%Y-%m-%d")
    except Exception:
        return None


def _rank_map(items: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in items:
        code = str(item.get("thscode") or "")
        rank = item.get("rank")
        if not code or rank is None:
            continue
        try:
            out[code] = int(rank)
        except Exception:
            continue
    return out


def _state(current_rank, rank_change, lhb) -> str:
    if current_rank is None:
        return "未上榜"
    if current_rank <= 10:
        if rank_change is not None and rank_change > 0:
            return "核心加速"
        if rank_change is not None and rank_change < -10:
            return "高位降温"
        return "核心高热"
    if current_rank <= 30:
        return "热度回升" if (rank_change or 0) > 0 else "次核心"
    if current_rank <= 60:
        return "升温" if (rank_change or 0) > 0 else "边缘降温"
    if current_rank <= 150:
        return "回温" if (rank_change or 0) > 0 else "退潮"
    return "边缘/退潮"


def _theme_lock(theme: str) -> threading.Lock:
    with _QUERY_LOCKS_LOCK:
        return _QUERY_LOCKS.setdefault(theme, threading.Lock())


def _choose_codes(
    members: Dict[str, Dict[str, Any]],
    snapshot: Dict[str, Dict[str, Any]],
    current_ranks: Dict[str, int],
    old_ranks: Dict[str, int],
    limit: int,
) -> List[str]:
    forced: List[str] = []
    seen = set()
    for code, _ in sorted(current_ranks.items(), key=lambda item: (item[1], item[0])):
        if code in members and code not in seen:
            seen.add(code)
            forced.append(code)
    for code, _ in sorted(old_ranks.items(), key=lambda item: (item[1], item[0])):
        if code in members and code not in seen:
            seen.add(code)
            forced.append(code)

    candidates = sorted(
        members,
        key=lambda code: (
            -float(snapshot.get(code, {}).get("turnover") or 0),
            code,
        ),
    )
    chosen = []
    chosen_seen = set()
    for code in forced:
        if code in members and code not in chosen_seen:
            chosen_seen.add(code)
            chosen.append(code)
        if len(chosen) >= limit:
            return chosen[:limit]
    for code in candidates:
        if code in members and code not in chosen_seen:
            chosen_seen.add(code)
            chosen.append(code)
        if len(chosen) >= limit:
            break
    return chosen[:limit]


def _load_trends(codes: List[str], start_date: str, end_date: str) -> Dict[str, Dict[str, int]]:
    if not codes:
        return {}
    out: Dict[str, Dict[str, int]] = {}
    workers = min(_CLI_CONCURRENCY, len(codes))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_hot_trend, code, start_date, end_date): code for code in codes}
        for future in concurrent.futures.as_completed(futures):
            code = futures[future]
            try:
                items = future.result()
            except Exception:
                items = []
            ranks = {}
            for item in items:
                date = str(item.get("date") or "")
                rank = item.get("rank")
                if date and rank is not None:
                    try:
                        ranks[date] = int(rank)
                    except Exception:
                        pass
            out[code] = ranks
    return out


def _trend_ranks_for(code: str, trends: Dict[str, Dict[str, int]]) -> List[Tuple[str, int]]:
    return sorted((date, rank) for date, rank in (trends.get(code) or {}).items() if rank is not None)


def _public_result(payload: Dict[str, Any], limit: int, *, cached: bool, stale: bool = False, age: Optional[float] = None) -> Dict[str, Any]:
    result = deepcopy(payload.get("result") or {})
    result["rows"] = list(result.get("rows") or [])[:limit]
    result["cached"] = cached
    if stale:
        result["stale"] = True
        warning = result.get("warning") or ""
        suffix = "上游暂时不可用，当前展示最近一次缓存结果。"
        result["warning"] = (warning + " " + suffix).strip()
    if age is not None:
        result["cache_age"] = round(max(0.0, age), 1)
    return result


def _compute_theme_heat(theme: str, limit: int) -> Dict[str, Any]:
    started = time.time()
    indices = resolve_indices(theme)
    if not indices:
        return {"success": False, "error": "未在同花顺概念/行业目录中找到匹配题材，请换用更标准的题材名。"}

    members: Dict[str, Dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(_CLI_CONCURRENCY, len(indices))) as ex:
        lists = list(ex.map(_constituents, [ix["thscode"] for ix in indices]))
    for ix, rows in zip(indices, lists):
        for row in rows:
            code = row["thscode"]
            if code not in members:
                members[code] = dict(row)
                members[code]["themes"] = []
            members[code]["themes"].append(ix["name"])

    codes = list(members.keys())
    snapshot = _market_snapshot(codes) if codes else {}

    current = _hot_list("day")
    current_ranks = _rank_map(current.get("items") or [])
    current_as_of = str(current.get("as_of") or datetime.now().strftime("%Y-%m-%d"))
    old_date = (datetime.now().date() - timedelta(days=3)).strftime("%Y-%m-%d")
    previous = _hot_history(old_date)
    previous_ranks = _rank_map(previous.get("items") or [])
    previous_as_of = str(previous.get("as_of") or old_date)

    chosen = _choose_codes(members, snapshot, current_ranks, previous_ranks, limit)

    # Spend the limited single-stock trend budget first on rows crossing the
    # top-30 boundary. If budget remains, fill it with the highest-priority
    # otherwise-unranked candidates so the visible table has useful ranks
    # without spawning one process per stock.
    boundary_codes = [
        code for code in chosen
        if (code in current_ranks) != (code in previous_ranks)
    ]
    fallback_codes = [
        code for code in chosen
        if code not in boundary_codes
        and code not in current_ranks
        and code not in previous_ranks
    ]
    trend_codes = (boundary_codes + fallback_codes)[:_TREND_LOOKUP_LIMIT]
    trends = _load_trends(trend_codes, old_date, current_as_of)

    lhb = _latest_lhb()
    rows = []
    for code in chosen:
        member = members[code]
        snap = snapshot.get(code) or {}
        trend_ranks = _trend_ranks_for(code, trends)

        current_rank = current_ranks.get(code)
        previous_rank = previous_ranks.get(code)
        if trend_ranks:
            current_rank = trend_ranks[-1][1]
            previous_rank = trend_ranks[0][1]

        rank_change = None
        if current_rank is not None and previous_rank is not None:
            rank_change = previous_rank - current_rank

        lhb_row = lhb.get(code) or {}
        latest_hot_date = None
        if trend_ranks:
            latest_hot_date = trend_ranks[-1][0]
        elif current_rank is not None:
            latest_hot_date = current_as_of
        elif previous_rank is not None:
            latest_hot_date = previous_as_of

        rows.append({
            "name": member.get("name") or "",
            "thscode": code,
            "ticker": member.get("ticker") or code.split(".")[0],
            "themes": "、".join(sorted(set(member.get("themes") or []))),
            "current_rank": current_rank,
            "rank_3d_ago": previous_rank,
            "rank_change": rank_change,
            "latest_hot_date": latest_hot_date,
            "turnover": float(snap.get("turnover") or 0),
            "change_pct": float(snap.get("price_change_ratio_pct") or 0),
            "last_price": float(snap.get("last_price") or 0),
            "lhb_net": float(lhb_row.get("net") or 0),
            "lhb_org": float(lhb_row.get("org") or 0),
            "lhb_hot_money": float(lhb_row.get("hot_money") or 0),
            "lhb_net_rate": lhb_row.get("net_rate"),
            "lhb_date": lhb_row.get("trade_date"),
            "state": _state(current_rank, rank_change, lhb_row),
        })

    rows.sort(
        key=lambda row: (
            row["current_rank"] if row["current_rank"] is not None else 99999,
            -(row["rank_change"] if row["rank_change"] is not None else -99999),
            -float(row["lhb_org"] or 0),
            -float(row["turnover"] or 0),
        )
    )
    for index, row in enumerate(rows, 1):
        row["display_rank"] = index

    hot_date = None
    for row in rows:
        if row.get("latest_hot_date"):
            hot_date = max(hot_date or "", row["latest_hot_date"])

    result = {
        "success": True,
        "theme": theme,
        "matched_indices": indices,
        "as_of": hot_date or current_as_of,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "universe_count": len(members),
        "ranked_count": len(rows),
        "rows": rows,
        "method": "当前热榜排名优先；近3个自然日的排名变化次之；最新龙虎榜机构/资金净额作为确认。",
        "warning": (
            "同花顺热榜接口默认展示前30名；未返回排名的股票按未上榜处理。"
            "热榜和龙虎榜只反映可观测关注度与资金，不等同于全市场主力净流入。"
        ),
        "elapsed": round(time.time() - started, 2),
        "cached": False,
    }
    return result


def query_theme_heat(theme: str, limit: int = 60) -> Dict[str, Any]:
    theme = (theme or "").strip()
    if not theme:
        return {"success": False, "error": "请输入题材关键词"}

    limit = max(10, min(int(limit or 60), 100))
    normalized = _normalise_theme(theme)
    cache_key = "query:%s:%s" % (_CACHE_NAMESPACE, normalized)

    entry = _cache_get_raw(cache_key)
    if entry is not None:
        age = time.time() - entry[0]
        payload = entry[1] or {}
        if age < _QUERY_TTL and int(payload.get("computed_limit") or 0) >= limit:
            return _public_result(payload, limit, cached=True, age=age)

    lock = _theme_lock(normalized)
    with lock:
        entry = _cache_get_raw(cache_key)
        if entry is not None:
            age = time.time() - entry[0]
            payload = entry[1] or {}
            if age < _QUERY_TTL and int(payload.get("computed_limit") or 0) >= limit:
                return _public_result(payload, limit, cached=True, age=age)

        try:
            result = _compute_theme_heat(theme, limit)
        except Exception:
            if entry is not None:
                age = time.time() - entry[0]
                return _public_result(entry[1] or {}, limit, cached=True, stale=True, age=age)
            raise

        if not result.get("success", True):
            return result

        payload = {"computed_limit": limit, "result": result}
        _cache_set(cache_key, payload)
        return _public_result(payload, limit, cached=False)


__all__ = ["query_theme_heat", "resolve_indices"]
