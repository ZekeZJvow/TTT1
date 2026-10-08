# -*- coding: utf-8 -*-
"""独立端口的测试服务启动器（不碰生产库/生产端口）"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ["MARKET_DB"] = sys.argv[1]
os.environ["AUTO_FETCH_ENABLED"] = "0"
os.environ["PORT"] = sys.argv[2]
import server
server.app.run(host="127.0.0.1", port=int(sys.argv[2]), debug=False,
               use_reloader=False, threaded=True)
