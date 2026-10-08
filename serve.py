# -*- coding: utf-8 -*-
r"""
A股人气雷达 - 后台常驻服务入口

与 server.py 的区别：
  - 关闭 debug / 自动重载（debug 模式会派生 2 个进程，不适合常驻）
  - 开启多线程，避免扫描时阻塞其他请求
  - 日志写入 service.log，便于排查

启动：venv\Scripts\pythonw.exe serve.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

# pythonw 下没有控制台，把输出重定向到日志文件
try:
    if sys.stdout is None or sys.stderr is None:
        _log = open(os.path.join(HERE, "service.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = _log
        sys.stderr = _log
except Exception:
    pass

# 与打包版(exe)保持一致：统一用 dist\data\market.db，避免源码模式与打包模式用两个库、历史对不上
_dist_db = os.path.join(HERE, "dist", "data", "market.db")
if os.path.isfile(_dist_db):
    os.environ.setdefault("MARKET_DB", _dist_db)

from server import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print("\n===== 服务启动 %s  http://localhost:%d =====" % (
        __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"), port))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
