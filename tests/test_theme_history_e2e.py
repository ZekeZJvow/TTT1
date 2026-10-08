# -*- coding: utf-8 -*-
"""题材页历史回看 E2E（独立库 + 独立端口 5001，不碰生产）"""
import io, os, sys, shutil, copy, subprocess, time, json, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTDIR = os.path.join(ROOT, "_test_artifacts")
os.makedirs(TESTDIR, exist_ok=True)
TDB = os.path.join(TESTDIR, "e2e_history.db")
SRC = os.path.join(ROOT, "dist", "data", "market.db")
PORT = 5001
BASE = "http://127.0.0.1:%d" % PORT
MARKER = "测试题材10月8日"
D930, D1008 = "2026-09-30", "2026-10-08"

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "|", name, ("| " + str(detail)) if detail else "")

def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

srv = None
try:
    if os.path.exists(TDB):
        os.remove(TDB)
    shutil.copy2(SRC, TDB)
    print("测试库 =", TDB, os.path.getsize(TDB), "bytes")

    os.environ["MARKET_DB"] = TDB
    sys.path.insert(0, ROOT)
    import market_db as m
    m.init_db()

    real = m.load_event_themes(D930)
    check("生产库含 09-30 题材 payload", bool(real and real.get("success")),
          "themeCount=%s" % (real.get("themeCount") if real else None))

    fake = copy.deepcopy(real)
    fake["as_of"] = "2026-10-08 15:30"
    top = {"name": MARKER, "verdict": "利好", "rank": 1, "heatScore": 9999.0,
           "netScore": 9, "topicHeat": 0.0, "stockCount": 0, "stocks": []}
    fake["rows"].insert(0, dict(top))
    fake["allThemes"].insert(0, dict(top))
    fake["themeCount"] = len(fake["allThemes"])
    m.save_event_themes(fake, trade_date=D1008)
    dates = m.theme_dates(30)
    check("测试库题材日期含 09-30 与 10-08",
          D930 in dates and D1008 in dates, dates)

    env = dict(os.environ)
    env["MARKET_DB"] = TDB
    env["AUTO_FETCH_ENABLED"] = "0"
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "_run_test_server.py"), TDB, str(PORT)],
                           cwd=ROOT, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    up = False
    for _ in range(40):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(BASE + "/api/db-stats", timeout=2).read()
            up = True
            break
        except Exception:
            pass
    check("测试服务已启动 (port %d)" % PORT, up)

    d1 = get_json("/api/themes/dates?limit=60")
    check("GET /api/themes/dates 返回两个日期",
          d1.get("success") and D930 in d1.get("dates", []) and D1008 in d1.get("dates", []),
          d1.get("dates"))

    r930 = get_json("/api/event-themes?limit=6&stocks=20&date=" + D930)
    check("查 09-30 返回真实题材", r930.get("success") and r930.get("themeCount", 0) > 1,
          "themeCount=%s first=%s" % (r930.get("themeCount"),
                                      (r930.get("rows") or [{}])[0].get("name")))
    check("查 09-30 时 trade_date 回填为所选日期", r930.get("trade_date") == D930,
          r930.get("trade_date"))
    check("09-30 结果不含测试标记", MARKER not in json.dumps(r930, ensure_ascii=False))

    r1008 = get_json("/api/event-themes?limit=6&stocks=20&date=" + D1008)
    check("查 10-08 返回测试题材", r1008.get("success")
          and MARKER == ((r1008.get("rows") or [{}])[0].get("name")),
          "first=%s" % ((r1008.get("rows") or [{}])[0].get("name")))

    rnod = get_json("/api/event-themes?limit=6&stocks=20&date=2026-10-01")
    check("查无数据日期 10-01 返回 NO_DATA",
          (not rnod.get("success")) and rnod.get("error") == "NO_DATA", rnod.get("error"))

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.click("#mode-theme")
        pg.wait_for_function(
            "document.querySelectorAll('#theme-date-chips .day-chip').length >= 2", timeout=20000)
        chips = pg.eval_on_selector_all(
            "#theme-date-chips .day-chip", "els => els.map(e => e.textContent.trim())")
        check("题材页显示 >=2 个可点日期块", len(chips) >= 2, chips)

        def click_date(d):
            pg.evaluate("(d) => { document.querySelectorAll('#theme-date-chips .day-chip')"
                        ".forEach(e => { if (e.textContent.trim() === d) e.click(); }); }", d)

        # 点 10-08
        click_date(D1008)
        pg.wait_for_function("document.querySelector('#hot-themes').textContent.includes('%s')"
                             % MARKER, timeout=25000)
        note8 = pg.inner_text("#hot-themes-note")
        sel8 = pg.eval_on_selector_all("#theme-date-chips .day-chip.sel",
                                       "els => els.map(e => e.textContent.trim())")
        check("点 10-08：切到该日题材", MARKER in pg.inner_text("#hot-themes"))
        check("点 10-08：高亮切到该日期块", sel8 == [D1008], sel8)
        check("点 10-08：标注『回看交易日 2026-10-08』", ("回看交易日 " + D1008) in note8,
              note8.replace(chr(10), " ")[:60])
        pg.screenshot(path=os.path.join(TESTDIR, "G3_theme_switch_1008.png"), full_page=True)

        # 点 09-30
        click_date(D930)
        pg.wait_for_function("document.querySelector('#hot-themes-note').textContent"
                             ".includes('%s')" % ("回看交易日 " + D930), timeout=25000)
        txt930 = pg.inner_text("#hot-themes")
        n930 = pg.eval_on_selector_all("#hot-themes .theme-chip", "els => els.length")
        sel930 = pg.eval_on_selector_all("#theme-date-chips .day-chip.sel",
                                         "els => els.map(e => e.textContent.trim())")
        check("点 09-30：题材 chip 渲染", n930 >= 1, "chips=%d" % n930)
        check("点 09-30：内容为真实题材（不含测试标记）", MARKER not in txt930,
              txt930.replace(chr(10), " ")[:70])
        check("点 09-30：高亮切到该日期块", sel930 == [D930], sel930)
        pg.screenshot(path=os.path.join(TESTDIR, "G2_theme_switch_0930.png"), full_page=True)

        # 再切回 10-08，证明可来回切换
        click_date(D1008)
        pg.wait_for_function("document.querySelector('#hot-themes').textContent.includes('%s')"
                             % MARKER, timeout=25000)
        check("来回切换：再点 10-08 又能切回", MARKER in pg.inner_text("#hot-themes"))
        b.close()

finally:
    if srv:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
    if os.path.exists(TDB):
        try:
            os.remove(TDB)
            print("已删除测试库")
        except Exception as e:
            print("删除测试库失败:", e)

print()
print("=" * 60)
bad = [r for r in results if not r[1]]
print("总计 %d 项，通过 %d，失败 %d" % (len(results), len(results) - len(bad), len(bad)))
for n, ok, d in bad:
    print("  FAIL:", n, d)
sys.exit(1 if bad else 0)
