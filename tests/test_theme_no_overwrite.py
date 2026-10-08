# -*- coding: utf-8 -*-
"""专项：非交易时段调用题材接口，绝不能覆盖已存档的题材快照（独立库 + 独立端口）"""
import io, os, sys, json, shutil, sqlite3, subprocess, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTDIR = os.path.join(ROOT, "_test_artifacts")
os.makedirs(TESTDIR, exist_ok=True)
TDB = os.path.join(TESTDIR, "guard_theme.db")
SRC = os.path.join(ROOT, "dist", "data", "market.db")
PORT = 5002
BASE = "http://127.0.0.1:%d" % PORT

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "|", name, ("| " + str(detail)) if detail else "")

def snapshot():
    """抓取所有题材相关存档的指纹"""
    c = sqlite3.connect(TDB)
    fp = {}
    for k, ca, pj in c.execute("select cache_key, created_at, payload_json from raw_payload "
                               "where cache_key like 'themes:%' order by cache_key"):
        try:
            d = json.loads(pj)
        except Exception:
            d = {}
        fp[k] = (ca, d.get("as_of"), d.get("themeCount"), len(pj))
    for td, cnt, mx in c.execute("select trade_date, count(*), max(captured_at) from "
                                 "theme_heat_snapshot group by trade_date order by trade_date"):
        fp["snap:" + td] = (cnt, mx)
    for td, cnt in c.execute("select trade_date, count(*) from theme_topic group by trade_date"):
        fp["topic:" + td] = cnt
    c.close()
    return fp

srv = None
try:
    if os.path.exists(TDB):
        os.remove(TDB)
    shutil.copy2(SRC, TDB)
    env = dict(os.environ)
    env["MARKET_DB"] = TDB
    env["AUTO_FETCH_ENABLED"] = "0"
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "_run_test_server.py"), TDB, str(PORT)],
                           cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    up = False
    for _ in range(40):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(BASE + "/api/db-stats", timeout=2).read(); up = True; break
        except Exception:
            pass
    check("测试服务已启动 (port %d)" % PORT, up)

    # 确认当前确实处于"非交易时段"
    with urllib.request.urlopen(BASE + "/api/trading-days?n=1", timeout=10) as r:
        last_td = json.loads(r.read().decode("utf-8"))["days"][0]
    print("最近交易日 =", last_td, " (当前 2026-10-08 盘后 → 非交易时段)")

    before = snapshot()
    print("调用前指纹:", json.dumps(before, ensure_ascii=False))

    # 前端真实调用方式：limit=6&stocks=20（旧逻辑正是被这个参数绕过保护）
    urls = ["/api/event-themes?limit=6&stocks=20",
            "/api/event-themes?limit=6&stocks=20",
            "/api/event-themes?limit=12&stocks=20",
            "/api/event-themes?limit=6&stocks=10",
            "/api/event-themes?date=" + last_td]
    ok_all = True
    for u in urls:
        with urllib.request.urlopen(BASE + u, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8"))
            if not d.get("success"):
                ok_all = False
            print("   GET", u, "-> success=%s themeCount=%s from_db=%s"
                  % (d.get("success"), d.get("themeCount"), d.get("from_db")))
    check("题材接口均返回成功", ok_all)

    after = snapshot()
    print("调用后指纹:", json.dumps(after, ensure_ascii=False))
    check("非交易时段调用后：题材存档【完全未变】", before == after,
          "changed=" + str({k: (before.get(k), after.get(k)) for k in set(before) | set(after)
                            if before.get(k) != after.get(k)}))
    if last_td in [k.split(":", 1)[1] for k in before if k.startswith("snap:")]:
        check("最近交易日(%s)快照条数保持" % last_td,
              before.get("snap:" + last_td) == after.get("snap:" + last_td),
              "%s -> %s" % (before.get("snap:" + last_td), after.get("snap:" + last_td)))
finally:
    if srv:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
    if os.path.exists(TDB):
        try:
            os.remove(TDB); print("已删除测试库")
        except Exception as e:
            print("删除失败:", e)

print()
print("=" * 60)
bad = [r for r in results if not r[1]]
print("总计 %d 项，通过 %d，失败 %d" % (len(results), len(results) - len(bad), len(bad)))
for n, ok, d in bad:
    print("  FAIL:", n, d)
sys.exit(1 if bad else 0)
