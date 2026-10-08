# -*- coding: utf-8 -*-
"""
A股人气雷达 · PyInstaller 打包入口

与 serve.py 的区别：
  1. 兼容 PyInstaller 冻结模式（静态文件从解包目录读取）
  2. 运行期产物（缓存/日志）写到 exe 所在目录，避免写进临时目录
  3. 启动后自动打开浏览器
  4. 显示控制台提示（关闭窗口即停止服务）
"""
import os
import sys
import threading
import time
import webbrowser


def _resource_dir():
    """打包后 = PyInstaller 解包目录；开发时 = 脚本目录"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _writable_dir():
    """exe 所在目录（可写）；开发时 = 脚本目录"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


RES_DIR = _resource_dir()
WORK_DIR = _writable_dir()

sys.path.insert(0, RES_DIR)
# 从资源目录提供静态文件（index.html / app.js / styles.css）
os.chdir(RES_DIR)

# 缓存数据库写到 exe 旁边（解包目录是临时的，重启就没了）
os.environ.setdefault("THEME_HEAT_CACHE_DB",
                      os.path.join(WORK_DIR, "theme_heat_cache.sqlite3"))

# 本地行情数据仓库也写到 exe 旁边
os.environ.setdefault("MARKET_DB",
                      os.path.join(WORK_DIR, "data", "market.db"))

import server  # noqa: E402

server.app.static_folder = RES_DIR
server.app.template_folder = RES_DIR

PORT = int(os.environ.get("PORT", "5000"))

# 开机自启时不想每次弹浏览器：--no-browser 或 APP_NO_BROWSER=1
NO_BROWSER = ("--no-browser" in sys.argv) or (os.environ.get("APP_NO_BROWSER") == "1")


def _open_browser():
    if NO_BROWSER:
        return
    time.sleep(2.5)
    try:
        webbrowser.open("http://localhost:%d" % PORT)
    except Exception:
        pass


def _redirect_log():
    """后台模式：把输出写到 exe 同目录的 data/autostart.log（每次覆盖，避免无限增长）。
    隐藏窗口运行时看不到任何输出，日志是排查问题的唯一线索。"""
    try:
        d = os.path.join(WORK_DIR, "data")
        os.makedirs(d, exist_ok=True)
        f = open(os.path.join(d, "autostart.log"), "w", encoding="utf-8", buffering=1)
        sys.stdout = f
        sys.stderr = f
        return True
    except Exception:
        return False


def _already_running():
    """探测端口上是不是本程序已经在跑（避免重复启动/误报端口占用）"""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/api/db-stats" % PORT, timeout=3) as r:
            body = r.read(300).decode("utf-8", "ignore")
        return ("enabled" in body) or ("backend" in body)
    except Exception:
        return False


def main():
    if NO_BROWSER:
        _redirect_log()          # 后台静默模式：输出写日志文件

    print("=" * 54)
    print("   A股人气雷达")
    print("")
    print("   访问地址 : http://localhost:%d" % PORT)
    if NO_BROWSER:
        print("   运行方式 : 后台静默（不显示窗口）")
        print("   停止服务 : 运行「停止后台运行.bat」，或任务管理器结束本进程")
    else:
        print("   停止服务 : 直接关闭本窗口")
    print("=" * 54)
    # ---- 绑定端口之前先探测：已有实例在跑就直接退出 ----
    # 原因：Windows 上重复绑定同一端口不一定会报错，靠异常捕获不可靠。
    if _already_running():
        print("")
        print("  程序已经在运行了（端口 %d），本次不再重复启动。" % PORT)
        print("  访问地址 : http://localhost:%d" % PORT)
        if not NO_BROWSER:
            try:
                webbrowser.open("http://localhost:%d" % PORT)
            except Exception:
                pass
        time.sleep(1.5)
        return

    print("")
    print("  正在启动%s ..." % ("" if NO_BROWSER else "，浏览器稍后会自动打开"))

    threading.Thread(target=_open_browser, daemon=True).start()

    try:
        server.app.run(host="127.0.0.1", port=PORT,
                       debug=False, use_reloader=False, threaded=True)
    except OSError as e:
        # 如果端口上已经是"本程序"，说明重复启动了 —— 直接开浏览器然后退出
        if _already_running():
            print("")
            print("  程序已经在运行了（端口 %d）。" % PORT)
            print("  访问地址 : http://localhost:%d" % PORT)
            if not NO_BROWSER:
                try:
                    webbrowser.open("http://localhost:%d" % PORT)
                except Exception:
                    pass
            time.sleep(1.5)
            return
        print("")
        print("  [启动失败] %s" % e)
        print("  可能原因：端口 %d 已被其他程序占用。" % PORT)
        print("  解决办法：关闭占用程序，或设置环境变量 PORT 换端口。")
        _wait_exit()
    except Exception as e:
        print("")
        print("  [启动失败] %s" % e)
        _wait_exit()


def _wait_exit():
    """退出前停留一会儿。**不做 input() 阻塞**：后台/隐藏窗口启动时
    stdin 仍连着控制台，input() 会永久挂住进程。"""
    secs = 3 if NO_BROWSER else 20
    try:
        print("  （%d 秒后自动关闭此窗口）" % secs)
    except Exception:
        pass
    time.sleep(secs)


if __name__ == "__main__":
    main()
