# -*- coding: utf-8 -*-
"""
当日事件驱动题材 + 人气排序

流程：
  ① 采集当日事件（人气榜异动解读 + 个股异动原因）
  ② 题材归类（事件文本 -> 匹配同花顺指数目录）
  ③ 利好/利空判定（关键词词典 + 涨跌方向确认）
  ④ 取利好题材成分股
  ⑤ 按人气排名排序
"""

import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import urllib3

import theme_heat_service as T

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

_THS_URL = ("https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
            "?stock_type=a&type=hour&list_type=normal")
_TOPIC_URL = ("https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/topic?type=hour")
_THS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.10jqka.com.cn/",
}

_TTL = 300               # 结果缓存 5 分钟
_TREND_BUDGET = 52       # 单次最多做多少次人气趋势查询
_TREND_PER_THEME = 14    # 每个题材最多补几次

# 利好 / 利空 关键词词典（可维护）
BULL_WORDS = [
    "收购", "重组", "并购", "置入", "注入", "中标", "签订", "签约", "合同", "订单",
    "获批", "批准", "许可", "通过", "突破", "量产", "投产", "扩产", "达产", "交付",
    "业绩增长", "增长", "扭亏", "预增", "超预期", "创新高", "涨价", "提价", "景气",
    "回购", "增持", "举牌", "战略合作", "合作", "政策支持", "补贴", "国产替代",
    "专利", "摘帽", "涨价函", "重大合同", "业绩预增", "订单饱满",
]
BEAR_WORDS = [
    "减持", "清仓", "质押", "问询", "立案", "调查", "处罚", "罚款", "警示",
    "亏损", "预亏", "下滑", "下降", "终止", "失败", "退市", "诉讼", "仲裁",
    "违约", "逾期", "减值", "计提", "商誉", "解禁", "被执行", "冻结", "违规",
    "被查", "风险提示", "监管", "停牌核查", "澄清", "不属实", "终止合作",
]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _to_thscode(code: Any) -> str:
    c = str(code or "").strip().upper()
    if not c:
        return ""
    c = re.sub(r"\.(SH|SZ|BJ)$", "", c)
    if c.startswith("6"):
        return c + ".SH"
    if c.startswith(("0", "3")):
        return c + ".SZ"
    if c.startswith(("4", "8", "9")):
        return c + ".BJ"
    return c + ".SZ"


def _all_text(obj: Any) -> str:
    """递归拼接任意结构里的所有字符串"""
    parts: List[str] = []

    def walk(x):
        if isinstance(x, str):
            parts.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(obj)
    return " ".join(parts)


def _is_st(name: str) -> bool:
    n = (name or "").upper().replace(" ", "")
    return ("ST" in n) or ("退" in (name or ""))


def _theme_hit(name: str, ev: Dict[str, Any]) -> bool:
    """题材命中判定：先看概念标签精确匹配，再看解读标题，最后才看长文本"""
    tags = [str(t).strip() for t in (ev.get("concepts") or []) if str(t).strip()]
    if name in tags:                      # 概念标签精确命中（最可靠）
        return True
    title = ev.get("analyse_title") or ""
    if name in title:                     # 解读标题命中（短且人工整理过）
        return True
    if len(name) >= 3:
        if name in (ev.get("text") or ""):
            return True
        for t in tags:
            if name in t:
                return True
    return False


def _lexicon_score(text: str) -> Dict[str, int]:
    if not text:
        return {"bull": 0, "bear": 0, "net": 0}
    b = sum(text.count(w) for w in BULL_WORDS)
    s = sum(text.count(w) for w in BEAR_WORDS)
    return {"bull": b, "bear": s, "net": b - s}


def _matched(text: str, words: List[str]) -> List[str]:
    """返回文本中命中的词"""
    if not text:
        return []
    return [w for w in words if w in text]


def _direction_score(change: Any, popularity_tag: str) -> int:
    """由涨跌幅与涨停标记给出方向分（正=强，负=弱）"""
    if popularity_tag:
        return 3
    try:
        c = float(change)
    except (TypeError, ValueError):
        c = 0.0
    if c >= 7:
        return 3
    if c >= 3:
        return 2
    if c > 0:
        return 1
    if c <= -7:
        return -3
    if c <= -3:
        return -2
    if c < 0:
        return -1
    return 0


# ---------------------------------------------------------------------------
# 数据采集
# ---------------------------------------------------------------------------

def _fetch_hotlist() -> List[Dict[str, Any]]:
    """同花顺人气榜 Top30（含异动解读）"""
    try:
        r = requests.get(_THS_URL, headers=_THS_HEADERS, timeout=15, verify=False)
        data = r.json()
        lst = ((data.get("data") or {}).get("stock_list")) or []
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for it in lst[:30]:
        tag = it.get("tag") or {}
        concepts = tag.get("concept_tag") or []
        if isinstance(concepts, str):
            concepts = [concepts]
        title = str(it.get("analyse_title") or "")
        analyse = str(it.get("analyse") or "")
        out.append({
            "thscode": _to_thscode(it.get("code")),
            "ticker": str(it.get("code") or ""),
            "name": str(it.get("name") or ""),
            "rank": int(it.get("order") or 0),
            "change": it.get("rise_and_fall"),
            "popularity_tag": str(tag.get("popularity_tag") or ""),
            "concepts": [str(c) for c in concepts if c],
            "analyse_title": title,
            "text": " ".join([title, analyse] + [str(c) for c in concepts if c]),
        })
    return out


def _fetch_topics() -> List[Dict[str, Any]]:
    """同花顺热榜 - 热门话题（带热度值）"""
    try:
        r = requests.get(_TOPIC_URL, headers=_THS_HEADERS, timeout=15, verify=False)
        data = r.json()
        lst = ((data.get("data") or {}).get("topic_list")) or []
    except Exception:
        return []
    out = []
    for t in lst:
        title = str(t.get("title") or "").strip()
        desc = str(t.get("description") or "").strip()
        if not title:
            continue
        try:
            hot = float(t.get("hot_value") or 0)
        except (TypeError, ValueError):
            hot = 0.0
        out.append({
            "title": title,
            "desc": desc,
            "hot": hot,
            "text": (title + " " + desc).strip(),
            "url": str(t.get("jump_url") or ""),
        })
    return out


def _fetch_anomaly() -> List[Dict[str, Any]]:
    """当日个股异动原因（假期/盘前可能为空）"""
    try:
        obj = T._cached_json(["special", "anomaly-list", "--format", "json"], T._HOT_TTL, timeout=45)
        items = list((obj.get("data") or {}).get("item") or [])
    except Exception:
        return []
    codes = []
    base: Dict[str, Dict[str, Any]] = {}
    for x in items:
        c = str(x.get("thscode") or "")
        if c and c not in base:
            base[c] = x
            codes.append(c)
    if not codes:
        return []

    reasons: Dict[str, Any] = {}
    # 每批 ≤50 个，全部批完（不只取前 50 只），保证每条异动股都拿到原因文本
    for i in range(0, len(codes), 50):
        chunk = codes[i:i + 50]
        try:
            obj2 = T._cached_json(
                ["special", "anomaly-stock", "--thscodes", ",".join(chunk), "--format", "json"],
                T._HOT_TTL, timeout=60)
            for x in ((obj2.get("data") or {}).get("item")) or []:
                reasons[str(x.get("thscode") or "")] = x
        except Exception:
            pass

    out = []
    for c in codes:
        merged = dict(base.get(c) or {})
        merged["_reason"] = reasons.get(c) or {}
        out.append({
            "thscode": c,
            "ticker": str(c.split(".")[0]),
            "name": str((reasons.get(c) or {}).get("name") or base[c].get("name") or ""),
            "change": (reasons.get(c) or {}).get("change") or base[c].get("change"),
            "text": _all_text(merged),
            "source": "异动",
        })
    return out


def _fetch_trend_rank(thscode: str, days: int = 4) -> Optional[int]:
    """取个股最近一次热度排名"""
    now = datetime.now()
    start = (now.timestamp() - days * 86400)
    try:
        obj = T._cached_json(
            ["special", "hot-stock-trend", "--thscode", thscode,
             "--start-date", datetime.fromtimestamp(start).strftime("%Y-%m-%d"),
             "--end-date", now.strftime("%Y-%m-%d"), "--format", "json"],
            T._TREND_TTL, timeout=45)
        rows = list((obj.get("data") or {}).get("item") or [])
    except Exception:
        return None
    best = None
    for r in rows:
        rk = r.get("rank")
        if isinstance(rk, int) and rk > 0:
            best = rk
    return best


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _build_uncached(limit: int, stock_limit: int, min_heat: int) -> Dict[str, Any]:
    t0 = time.time()

    # 先检查数据组件是否可用（题材热度依赖 hithink-finance CLI）
    import shutil as _shutil
    if not T._cli_candidates() and not _shutil.which("hithink-finance"):
        return {
            "success": False,
            "error": "CLI_MISSING",
            "message": "题材热度功能需要本机安装 hithink-finance 数据组件（人气榜查询与动态选股不受影响）",
        }

    catalog = T._catalog_all()                       # 710 个概念+行业指数
    if not catalog:
        return {"success": False, "error": "指数目录获取失败"}

    hot = _fetch_hotlist()
    anom = _fetch_anomaly()
    topics = _fetch_topics()
    if not hot and not anom and not topics:
        return {"success": False, "error": "当日无事件数据（非交易日或尚未开盘）"}

    # 合并事件源（人气榜优先保留解读文本，异动补充新增个股）
    events: Dict[str, Dict[str, Any]] = {}
    for s in hot:
        s["source"] = "人气榜"
        events[s["thscode"]] = s
    for s in anom:
        ev = events.get(s["thscode"])
        if ev:
            if s.get("text"):
                ev["text"] = (ev.get("text") or "") + " " + s["text"]
            ev.setdefault("anomaly", True)
        else:
            events[s["thscode"]] = s
    event_list = [e for e in events.values() if e.get("thscode")]

    themes: Dict[str, Dict[str, Any]] = {}

    # 题材归类（一）：热门话题 → 题材（话题热度为主权重）
    for tp in topics:
        lex_t = _lexicon_score(tp["text"])
        for item in catalog:
            name = item["name"]
            if len(name) < 2 or not _theme_hit(name, {"concepts": [], "analyse_title": tp["title"], "text": tp["text"]}):
                continue
            th = themes.setdefault(item["thscode"], {
                "name": name, "thscode": item["thscode"], "tag": item["tag"],
                "members": [], "heat": 0, "bull": 0, "bear": 0, "net": 0,
                "topicHeat": 0.0, "topics": [], "bullWords": [],
            })
            th["topicHeat"] += tp["hot"] / 10000.0        # 万为单位
            if tp["title"] not in [x["title"] for x in th["topics"]]:
                th["topics"].append({"title": tp["title"], "hot": tp["hot"], "desc": tp["desc"]})
            for w in _matched(tp["text"], BULL_WORDS):
                if w not in th["bullWords"]:
                    th["bullWords"].append(w)
            th["bull"] += lex_t["bull"]
            th["bear"] += lex_t["bear"]
            th["net"] += lex_t["net"]

    # 题材归类（二）：人气榜事件股 → 题材（人气权重 + 方向确认）
    for ev in event_list:
        text = ev.get("text") or ""
        if not text:
            continue
        lex = _lexicon_score(text)
        dscore = _direction_score(ev.get("change"), ev.get("popularity_tag") or "")
        rank = int(ev.get("rank") or 0)
        weight = (31 - rank) if rank else 6          # 人气榜权重；异动股给基准分
        for item in catalog:
            name = item["name"]
            if len(name) < 2 or not _theme_hit(name, ev):
                continue
            th = themes.setdefault(item["thscode"], {
                "name": name, "thscode": item["thscode"], "tag": item["tag"],
                "members": [], "heat": 0, "bull": 0, "bear": 0, "net": 0,
                "topicHeat": 0.0, "topics": [], "bullWords": [],
            })
            if any(m["thscode"] == ev["thscode"] for m in th["members"]):
                continue
            th["members"].append({
                "thscode": ev["thscode"], "ticker": ev.get("ticker", ""),
                "name": ev.get("name", ""), "rank": rank,
                "change": ev.get("change"),
                "reason": (ev.get("analyse_title") or "").strip() or (ev.get("text") or "")[:40],
                "source": ev.get("source", ""),
            })
            th["heat"] += weight
            for w in _matched(ev.get("text") or "", BULL_WORDS):
                if w not in th["bullWords"]:
                    th["bullWords"].append(w)
            th["bull"] += lex["bull"] + (1 if dscore > 0 else 0)
            th["bear"] += lex["bear"] + (1 if dscore < 0 else 0)
            th["net"] += lex["net"] + dscore

    rows = []
    for th in themes.values():
        th["members"].sort(key=lambda m: (m["rank"] or 999))
        th["popHeat"] = th["heat"]
        th["topicHeat"] = round(th["topicHeat"], 1)
        th["heatScore"] = round(th["topicHeat"] + th["heat"], 1)
        th["netScore"] = th["net"]
        if th["net"] > 0:
            th["verdict"] = "利好"
        elif th["net"] < 0:
            th["verdict"] = "利空"
        else:
            th["verdict"] = "中性"
        th["stockCount"] = len(th["members"])
        th["stockReasons"] = [
            {"name": m["name"], "reason": m["reason"], "rank": m["rank"], "change": m["change"]}
            for m in th["members"] if (m.get("reason") or "").strip()
        ][:3]
        th["bullWords"] = th.get("bullWords", [])[:6]
        rows.append(th)

    rows.sort(key=lambda r: (-r["heatScore"], -r["netScore"]))
    bulls = [r for r in rows if r["verdict"] == "利好" and r["heatScore"] >= min_heat]
    picks = bulls[:limit]

    # ④⑤ 取利好题材成分股 + 人气排序
    hot_rank = {s["thscode"]: s["rank"] for s in hot if s.get("rank")}
    pos_rank: Dict[str, int] = {}
    for s in hot:
        c = s.get("ticker") or ""
        if c and s.get("rank"):
            pos_rank[c] = s["rank"]

    trend_budget = _TREND_BUDGET
    for th in picks:
        try:
            cons = T._constituents(th["thscode"])
        except Exception:
            cons = []
        stocks = []
        for c in cons:
            nm = str(c.get("name") or "")
            if _is_st(nm):                     # 剔除 ST / *ST / 退市
                continue
            code = str(c.get("ticker") or "")
            stocks.append({
                "thscode": str(c.get("thscode") or ""),
                "ticker": code,
                "name": nm,
                "hotRank": pos_rank.get(code),
                "trendRank": None,
                "change": None,
            })
        # 非热榜个股补人气趋势（配额在各题材间平均分配）
        need = [s for s in stocks if s["hotRank"] is None]
        need.sort(key=lambda s: s["name"])
        share = max(1, trend_budget // max(1, len(picks) - picks.index(th)))
        for s in need[:min(_TREND_PER_THEME, share)]:
            if trend_budget <= 0:
                break
            trend_budget -= 1
            s["trendRank"] = _fetch_trend_rank(s["thscode"])

        def _key(s):
            if s["hotRank"]:
                return (0, s["hotRank"])
            if s["trendRank"]:
                return (1, s["trendRank"])
            return (2, 999)

        stocks.sort(key=_key)
        th["stocks"] = stocks[:stock_limit]
        th["stockTotal"] = len(stocks)

    # ⑥ 合并 6 个利好题材的成分股 → 去重 → 按人气排序 → Top 50
    merged: Dict[str, Dict[str, Any]] = {}
    for th in picks:
        for st in (th.get("stocks") or []):
            key = st.get("ticker") or st.get("thscode")
            if not key:
                continue
            cur = merged.get(key)
            if cur is None:
                cur = dict(st)
                cur["themes"] = [th["name"]]
                cur["themeHeat"] = th["heatScore"]
                merged[key] = cur
            else:
                if th["name"] not in cur["themes"]:
                    cur["themes"].append(th["name"])
                cur["themeHeat"] = max(cur.get("themeHeat") or 0, th["heatScore"])
                if not cur.get("hotRank") and st.get("hotRank"):
                    cur["hotRank"] = st["hotRank"]
                if not cur.get("trendRank") and st.get("trendRank"):
                    cur["trendRank"] = st["trendRank"]

    def _sk(x):
        if x.get("hotRank"):
            return (0, int(x["hotRank"]), 0.0, "")
        if x.get("trendRank"):
            return (1, int(x["trendRank"]), 0.0, "")
        return (2, 0, -(x.get("themeHeat") or 0.0), x.get("ticker") or "")

    top_stocks = sorted(merged.values(), key=_sk)[:50]

    for th in rows:
        th.pop("members", None)

    return {
        "success": True,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "eventCount": len(event_list),
        "themeCount": len(rows),
        "bullCount": len(bulls),
        "bearCount": len([r for r in rows if r["verdict"] == "利空"]),
        "sources": {"hotlist": len(hot), "anomaly": len(anom), "topics": len(topics)},
        "topics": [{"title": t["title"], "desc": t["desc"], "hot": t["hot"],
                    "url": t["url"]} for t in topics],
        "rows": picks,
        "topStocks": top_stocks,
        "stockTotal": len(merged),
        "stockRanked": len([x for x in top_stocks if x.get("hotRank") or x.get("trendRank")]),
        "allThemes": rows[:20],
        "method": "同花顺热门话题(hot_value) + 人气榜异动解读 + 个股异动原因 → 匹配指数目录归类题材 → 关键词词典+涨跌方向判定利好利空 → 利好题材取成分股 → 按人气排名排序；热度 = 话题热度(万) + Σ(31-人气榜排名)",
        "caveat": "事件源仅覆盖当日（热门话题15条 + 人气榜Top30 + 异动榜），且利好利空为关键词规则判定，非语义模型，可能漏判新说法。",
        "elapsed": round(time.time() - t0, 2),
    }


def build_event_themes(limit: int = 6, stock_limit: int = 10, min_heat: int = 6) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 6), 20))
    stock_limit = max(3, min(int(stock_limit or 10), 50))
    try:
        return T._memoized(
            "event-themes:%s:%s:%s:%s" % (T._CACHE_NAMESPACE, limit, stock_limit, min_heat),
            _TTL,
            lambda: _build_uncached(limit, stock_limit, min_heat),
        )
    except Exception as exc:
        return {"success": False, "error": "事件题材构建失败: %s" % exc}