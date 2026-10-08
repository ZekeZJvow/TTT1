# -*- coding: utf-8 -*-
import io, os, sys, time, shutil, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
d = os.path.join(tempfile.gettempdir(), "scan_resume"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
os.environ["MARKET_DB"] = os.path.join(d, "market.db")
os.environ["AUTO_FETCH_ENABLED"] = "0"
for k in ("MYSQL_DSN", "DB_BACKEND"): os.environ.pop(k, None)

import market_db as m
import screener
m.init_db()

T = "2026-09-30"
ok = []
def chk(l, c, e=""):
    ok.append(c); print(("PASS " if c else "FAIL ") + l + ("  [" + str(e) + "]" if e != "" else ""))

print("=== 1) 首次全量扫描 ===")
t0 = time.time()
r1 = screener.run_screen(T)
t1 = time.time() - t0
chk("首次扫描成功", r1.get("success"), r1.get("error"))
f1 = r1["funnel"]
p1 = m.scan_progress(T)
print("   用时 %.1fs  漏斗=%s" % (t1, f1))
print("   暂存: %s" % p1)
chk("暂存已建立", p1["total"] > 3000, p1)
chk("首次 resumedFrom=0", r1.get("resumedFrom") == 0, r1.get("resumedFrom"))

print("\n=== 2) 二次调用（应全部命中暂存，不再联网扫描）===")
t0 = time.time()
r2 = screener.run_screen(T)
t2 = time.time() - t0
chk("二次结果与首次一致", r2["funnel"] == f1, "%s vs %s" % (r2["funnel"], f1))
chk("二次 resumedFrom>0（跳过全部）", r2.get("resumedFrom", 0) >= p1["total"] - 100, r2.get("resumedFrom"))
print("   用时 %.1fs（首次 %.1fs）resumedFrom=%s" % (t2, t1, r2.get("resumedFrom")))

print("\n=== 3) 模拟中断：删掉 500 只的暂存，再跑 ===")
codes = sorted(m.load_scan_codes(T))[-500:]
removed = 0
def _del(conn):
    global removed
    for c in codes:
        cur = conn.execute("DELETE FROM `scan_stock` WHERE `target_date`=? AND `stock_code`=?", (T, c))
        removed += cur.rowcount
m._write(_del)
p3 = m.scan_progress(T)
print("   删除 %d 条；剩余暂存 %s" % (removed, p3))
chk("暂存被部分删除", p3["total"] == p1["total"] - removed, p3)

t0 = time.time()
r3 = screener.run_screen(T)
t3 = time.time() - t0
chk("断点续传后结果仍与首次一致", r3["funnel"] == f1, "%s vs %s" % (r3["funnel"], f1))
chk("只补扫了缺失部分", 0 < r3.get("resumedFrom", 0) < p1["total"], r3.get("resumedFrom"))
print("   用时 %.1fs  resumedFrom=%s  todo≈%d" % (t3, r3.get("resumedFrom"), p1["total"] - r3.get("resumedFrom", 0)))

print("\n=== 4) resume=False 强制重扫 ===")
m.clear_scan(T)
chk("clear_scan 生效", m.scan_progress(T)["total"] == 0, m.scan_progress(T))
r4 = screener.run_screen(T, resume=False)
chk("强制重扫成功", r4.get("success"), r4.get("error"))
chk("强制重扫漏斗一致", r4["funnel"] == f1, r4["funnel"])

print("\nRESULT: %d/%d" % (sum(1 for x in ok if x), len(ok)))
shutil.rmtree(d, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
