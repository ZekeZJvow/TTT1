# -*- coding: utf-8 -*-
r"""打包 exe（输出到 _dist_v31，绝不碰 dist\data）"""
import os, subprocess, sys, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

datas = ["index.html", "app.js", "styles.css", "icon.ico", "echarts.min.js",
         "schema.sql", "deploy/mysql_schema.sql",
         "tools/backfill_hotlist.py", "tools/backfill_turnover.py",
         "tools/backfill_kline_all.py"]
hidden = ["flask", "flask_cors", "urllib3", "requests", "screener", "stock_data",
          "market_db", "market_turnover", "market_breadth", "realtime_snapshot", "ths_turnover", "scheduler", "notifier", "backfill_hotlist",
          "openpyxl"]

cmd = [os.path.join(ROOT, "venv", "Scripts", "python.exe"), "-m", "PyInstaller",
       "--noconfirm", "--clean", "--onefile", "--name", "A股人气雷达",
       "--icon", os.path.join(ROOT, "icon.ico"),
       "--collect-data", "certifi", "--collect-data", "openpyxl",
       "--workpath", os.path.join(ROOT, "_build_v31"),
       "--distpath", os.path.join(ROOT, "_dist_v31"),
       "--specpath", os.path.join(ROOT, "_spec_v31")]
for d in datas:
    cmd += ["--add-data", os.path.join(ROOT, d) + ";."]
for h in hidden:
    cmd += ["--hidden-import", h]
cmd += [os.path.join(ROOT, "app_entry.py")]

p = subprocess.run(cmd, cwd=ROOT, capture_output=True)
tail = (p.stdout or b"").decode("utf-8", "replace").splitlines()[-12:]
print("\n".join(tail))
print("returncode:", p.returncode)
if p.returncode != 0:
    print((p.stderr or b"").decode("utf-8", "replace")[-2000:])
    sys.exit(1)
src = os.path.join(ROOT, "_dist_v31", "A股人气雷达.exe")
print("built:", src, os.path.getsize(src) if os.path.exists(src) else "MISSING")
