# -*- coding: utf-8 -*-
"""
人气榜历史回补工具（东方财富 getHisList）

背景
----
同花顺人气榜接口只有"此刻"的榜，不支持历史，所以程序没运行的日子就缺数据。
但东方财富提供了一个按个股查询的接口，能返回**最近约 120 天**的每日人气排名：
    POST https://emappdata.eastmoney.com/stockrank/getHisList
    {"srcSecurityCode":"SH600519", ...}  ->  {"data":[{"calcTime":"2026-06-10","rank":61}, ...]}
因此可以：对全市场每只股票各查一次 -> 取出目标日期的排名 -> 排序取前 N -> 重建当天人气榜。

注意
----
* 数据源是**东方财富人气榜**，与同花顺人气榜算法不同，排名会有差异；
  回补数据的 source 会标记为「东方财富人气榜·历史回补」，UI 上能区分，
  且**不会覆盖**当天真实抓取的同花顺数据。
* 一次全市场扫描（约 30 秒）即可同时获得**所有日期**的数据（接口一次返回 120 天）。

用法
----
  # 看哪些交易日缺人气榜数据
  python tools/backfill_hotlist.py --list

  # 回补指定日期
  python tools/backfill_hotlist.py --date 2026-09-29

  # 回补最近 N 个交易日中缺失的
  python tools/backfill_hotlist.py --days 20

  # 只预览不写库
  python tools/backfill_hotlist.py --days 20 --dry-run
"""
import argparse
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def resolve_db(explicit=None):
    """确定要写入哪个 market.db。

    优先级：--db 参数 > 环境变量 MARKET_DB > <root>/dist/data/market.db（应用在用的）
            > <root>/data/market.db
    否则会把数据写到一个没人看的库里去。
    """
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("MARKET_DB"):
        cands.append(os.environ["MARKET_DB"])
    cands.append(os.path.join(ROOT, "dist", "data", "market.db"))
    cands.append(os.path.join(ROOT, "data", "market.db"))
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return os.path.abspath(cands[-1]) if cands else None

import requests
import urllib3
urllib3.disable_warnings()

EM_HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
EM_BASE = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38",
           "marketType": "", "pageNo": 1, "pageSize": 30}
HIS_URL = "https://emappdata.eastmoney.com/stockrank/getHisList"
_SESS = requests.Session()


def get_universe(progress=None):
    """全市场 A 股列表 -> [(sym, code, name)]，sym 形如 SH600519"""
    out, seen = [], set()
    for node in ("sh_a", "sz_a"):
        for page in range(1, 80):
            url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   "Market_Center.getHQNodeData?page=%d&num=100&sort=symbol&asc=1&node=%s"
                   % (page, node))
            try:
                rows = _SESS.get(url, timeout=15).json()
            except Exception:
                break
            if not rows:
                break
            for it in rows:
                sym, code, name = it.get("symbol", ""), it.get("code", ""), it.get("name", "")
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                out.append((sym.upper(), code, name))
            if progress:
                progress(len(out))
    return out


def fetch_hist(sym):
    """查一只股票的历史排名 -> {date: rank}"""
    for _ in range(2):
        try:
            p = dict(EM_BASE)
            p["srcSecurityCode"] = sym
            r = _SESS.post(HIS_URL, headers=EM_HEADERS, json=p, timeout=12, verify=False)
            j = r.json()
            out = {}
            for d in (j.get("data") or []):
                t, rk = d.get("calcTime"), d.get("rank")
                if t and isinstance(rk, int) and rk > 0:
                    out[t] = rk
            return out
        except Exception:
            time.sleep(0.3)
    return {}


def _tier(order):
    if order <= 10:
        return "第一梯队·人气Top10"
    if order <= 20:
        return "第二梯队·人气Top20"
    return "第三梯队·人气Top30"


def api_date_range(probe_code="SH600519"):
    """探测接口覆盖的日期范围（拿一只权重股试）。返回 (最早, 最晚)，失败返回 (None, None)"""
    hist = fetch_hist(probe_code)
    if not hist:
        return None, None
    ds = sorted(hist.keys())
    return ds[0], ds[-1]


def backfill(target_dates, top_n=30, workers=16, progress=None, dry_run=False):
    """回补指定交易日的人气榜。返回 {date: 写入条数}"""
    import market_db as mdb

    t0 = time.time()
    uni = get_universe()
    if not uni:
        raise RuntimeError("股票列表获取失败")
    if progress:
        progress("universe", len(uni))

    # date -> [(rank, code, name)]
    tables = {d: [] for d in target_dates}
    done = 0
    ok_cnt = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        # 注意：fetch_hist 接收的是 symbol 字符串，所以要取 u[0]
        for (sym, code, name), hist in zip(uni, ex.map(lambda u: fetch_hist(u[0]), uni)):
            done += 1
            if hist:
                ok_cnt += 1
            if progress and done % 500 == 0:
                progress("scan", (done, len(uni)))
            for d in target_dates:
                rk = hist.get(d)
                if rk:
                    tables[d].append((rk, code, name))

    if ok_cnt == 0:
        raise RuntimeError("全部请求都失败了（返回 0 条）—— 检查网络或接口是否可用")

    result = {}
    for d in target_dates:
        rows_raw = sorted(tables[d])[:top_n]
        if not rows_raw:
            result[d] = 0
            continue
        rows = []
        for i, (rk, code, name) in enumerate(rows_raw, 1):
            rows.append({
                "rank": i,
                "code": code,
                "name": name,
                "rise_and_fall": None,          # 该接口不提供涨跌幅，留空（UI 显示 —）
                "consecutive_boards": "无",
                "tier": _tier(i),
                "concept_tag": "—",
                "anomaly_analysis": "—",
                "is_hot": False,
            })
        if not dry_run:
            mdb.save_backfill_hotlist(d, rows)
        result[d] = len(rows)

    if progress:
        progress("done", result)
    return {"result": result, "universe": len(uni), "elapsed": round(time.time() - t0, 1)}


def hotlist_stats(n=20):
    """最近 n 个交易日的人气榜数据情况

    missing    : 完全没有数据（实时/回补都没有）-> 需要回补
    backfilled : 只有回补数据（没有当天实时抓取）
    live       : 有当天实时抓取的数据
    """
    import market_db as mdb
    days = mdb.load_calendar(n)
    missing, backfilled, live = [], [], []
    for d in days:
        h = mdb._read(lambda c, _d=d: c.execute(
            "SELECT `source` FROM `hotlist_snapshot` WHERE `trade_date`=? LIMIT 1",
            (_d,)).fetchone())
        if not h:
            missing.append(d)
        elif mdb.is_backfill_source(h["source"]):
            backfilled.append(d)
        else:
            live.append(d)
    return {"missing": missing, "backfilled": backfilled, "live": live, "days": days}


def _missing_trading_days(n=20):
    """最近 n 个交易日中，完全没有数据的（既无实时也无回补）"""
    return hotlist_stats(n)["missing"]


def main():
    # 只在作为脚本运行时才重设 stdout（被 import 时不能动调用方的 stdout）
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="人气榜历史回补（东方财富）")
    ap.add_argument("--date", help="单个交易日 YYYY-MM-DD")
    ap.add_argument("--days", type=int, help="回补最近 N 个交易日中缺失的")
    ap.add_argument("--top", type=int, default=30, help="取前 N 名（默认 30）")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", help="列出缺失的交易日")
    ap.add_argument("--db", help="指定 market.db 路径（默认自动找应用正在用的那个）")
    args = ap.parse_args()

    db = resolve_db(getattr(args, "db", None))
    if db:
        os.environ["MARKET_DB"] = db
        print("目标数据库：%s" % db)
        print()

    if args.list:
        ms = _missing_trading_days(args.days or 20)
        if not ms:
            print("最近交易日的人气榜数据都已存在（无需回补）")
        else:
            print("缺少人气榜数据的交易日（最近 %d 个交易日中）：" % (args.days or 20))
            for d in ms:
                print("   " + d)
            print("\n回补命令：python tools\\backfill_hotlist.py --days %d" % (args.days or 20))
        return 0

    targets = []
    if args.date:
        targets = [args.date]
    elif args.days:
        targets = _missing_trading_days(args.days)
    else:
        ap.error("请指定 --date 或 --days（或用 --list 查看缺失）")

    if not targets:
        print("这些交易日的数据都已存在，无需回补")
        return 0

    # 接口只覆盖最近约 120 个自然日，先探测范围并过滤掉拿不到的日期
    lo, hi = api_date_range()
    if lo:
        out_of_range = [d for d in targets if d < lo]
        targets = [d for d in targets if d >= lo]
        print("接口可用范围：%s ~ %s" % (lo, hi))
        if out_of_range:
            print("以下 %d 天超出接口范围（拿不到，已跳过）：%s%s"
                  % (len(out_of_range), ", ".join(out_of_range[:5]),
                     " …" if len(out_of_range) > 5 else ""))
        if not targets:
            print("\n这些日期都超出接口可回溯范围，无法回补。")
            return 0

    print("将回补 %d 个交易日：%s" % (len(targets), ", ".join(targets)))
    print("数据源：东方财富人气榜（与同花顺算法不同，排名会有差异）")
    print("（一次全市场扫描即可覆盖全部日期，约 30~60 秒）\n")

    last = [0]

    def prog(stage, info):
        if stage == "scan":
            done, total = info
            if done - last[0] >= 1000:
                last[0] = done
                print("   已扫描 %d/%d ..." % (done, total))
        elif stage == "universe":
            print("   全市场股票数：%d" % info)

    res = backfill(targets, top_n=args.top, workers=args.workers,
                   progress=prog, dry_run=args.dry_run)
    print("\n回补结果：")
    for d, n in sorted(res["result"].items()):
        print("   %s  ->  %d 条%s" % (d, n, "（dry-run，未写库）" if args.dry_run else ""))
    print("用时 %.1fs" % res["elapsed"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
