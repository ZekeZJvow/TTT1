# -*- coding: utf-8 -*-
"""
本地行情数据仓库 —— SQLite / MySQL 双后端

落库 + 读库优先；同一套 API 同时支持 SQLite（单机默认）与 MySQL（多用户/商业化）。

后端选择
--------
  默认 SQLite；设置了 MYSQL_DSN / MYSQL_HOST 环境变量则使用 MySQL：
     MYSQL_DSN = mysql://user:pass@127.0.0.1:3306/stock
  或分开指定：MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
  强制指定：DB_BACKEND = sqlite | mysql

设计原则
--------
1. 所有函数内部捕获异常，**永不向调用方抛出** —— 保证不影响主流程。
2. 幂等：依赖各表 UNIQUE 约束 + UPSERT，同一份数据抓取多次不会产生重复行。
3. SQL 用一种写法（`?` 占位符 + 反引号标识符），运行时按方言翻译。
4. MARKET_DB_ENABLED=0 可整体关闭落库。
"""
import os
import sys
import json
import re
import time
import queue
import decimal
import datetime as _dt
import threading
from datetime import datetime

_LOCK = threading.Lock()
_INITED = False
_INITED_PATH = None
_ERR_COUNT = 0
_DISABLED = False
_MAX_ERRS = 8

_SUFFIXES = ("SH", "SZ", "BJ")

_MYSQL_OK = None          # 驱动是否可用（惰性检测）
_MYSQL_ERR = None


# ===========================================================================
# 方言与后端
# ===========================================================================

def _is_mysql():
    """是否使用 MySQL 后端"""
    b = (os.environ.get("DB_BACKEND") or "").strip().lower()
    if b == "mysql":
        return True
    if b == "sqlite":
        return False
    if os.environ.get("MYSQL_DSN") or os.environ.get("MYSQL_HOST"):
        return True
    return False


def _mysql_cfg():
    """解析 MySQL 连接参数"""
    dsn = (os.environ.get("MYSQL_DSN") or "").strip()
    cfg = {}
    if dsn:
        s = dsn
        for p in ("mysql://", "mysql+pymysql://", "mariadb://"):
            if s.startswith(p):
                s = s[len(p):]
        cred, _, hostpart = s.rpartition("@")
        if not hostpart:
            hostpart, cred = cred, ""
        user, _, pwd = cred.partition(":")
        host, _, portdb = hostpart.partition(":")
        port, _, db = portdb.partition("/")
        cfg = {"host": host or "127.0.0.1", "port": int(port or 3306),
               "user": user or "root", "password": pwd, "database": db}
    for k, env in (("host", "MYSQL_HOST"), ("user", "MYSQL_USER"),
                   ("password", "MYSQL_PASSWORD"), ("database", "MYSQL_DATABASE")):
        v = os.environ.get(env)
        if v:
            cfg[k] = v
    if os.environ.get("MYSQL_PORT"):
        cfg["port"] = int(os.environ["MYSQL_PORT"])
    cfg.setdefault("host", "127.0.0.1")
    cfg.setdefault("port", 3306)
    cfg.setdefault("user", "root")
    cfg.setdefault("password", "")
    cfg.setdefault("database", "stock")
    return cfg


def mysql_available():
    global _MYSQL_OK, _MYSQL_ERR
    if _MYSQL_OK is not None:
        return _MYSQL_OK
    try:
        import pymysql  # noqa: F401
        _MYSQL_OK = True
    except Exception:
        try:
            import mysql.connector  # noqa: F401
            _MYSQL_OK = True
        except Exception as e:
            _MYSQL_OK = False
            _MYSQL_ERR = str(e)
    return _MYSQL_OK


# ===========================================================================
# 行/游标/连接 包装（抹平 sqlite3 与 pymysql 的差异）
# ===========================================================================

def _norm(v):
    """把 MySQL 返回的 date/datetime/Decimal/bytes 归一化成与 SQLite 一致的类型，
    否则 jsonify 会失败（Decimal 不可序列化）或前端拿不到期望的日期字符串。"""
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, _dt.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, decimal.Decimal):
        try:
            return float(v)
        except Exception:
            return None
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "ignore")
    return v


class _Row(dict):
    """同时支持 r["col"] 与 r[0] 的行对象（MySQL 用）"""
    def __init__(self, data, order):
        super().__init__(data)
        self._order = order

    def __getitem__(self, k):
        if isinstance(k, int):
            return super().__getitem__(self._order[k])
        return super().__getitem__(k)


class _SqliteCursor:
    def __init__(self, cur):
        self._c = cur

    def execute(self, sql, params=()):
        self._c.execute(sql, params)
        return self

    def executemany(self, sql, seq):
        self._c.executemany(sql, seq)
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def lastrowid(self):
        return self._c.lastrowid

    def close(self):
        self._c.close()


class _MyCursor:
    def __init__(self, conn):
        self._mysqlmod, self._c = conn._new_cursor()
        self._desc = None

    def execute(self, sql, params=()):
        self._c.execute(sql.replace("?", "%s"), params)
        self._desc = self._c.description
        return self

    def executemany(self, sql, seq):
        self._c.executemany(sql.replace("?", "%s"), seq)
        return self

    def _wrap(self, row):
        if row is None:
            return None
        self._colnames = [d[0] for d in (self._desc or [])]
        return _Row({k: _norm(v) for k, v in row.items()}, self._colnames)

    def fetchone(self):
        return self._wrap(self._c.fetchone())

    def fetchall(self):
        return [self._wrap(r) for r in self._c.fetchall()]

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def lastrowid(self):
        return getattr(self._c, "lastrowid", None)

    def close(self):
        self._c.close()


class _Conn:
    """统一连接对象：.execute() / .cursor() / .commit() / .close()"""

    def __init__(self, raw, is_mysql):
        self._raw = raw
        self._mysql = is_mysql
        self._mod = None
        if is_mysql:
            try:
                import pymysql
                self._mod = ("pymysql", pymysql)
            except Exception:
                import mysql.connector
                self._mod = ("mysql.connector", mysql.connector)

    def _new_cursor(self):
        if not self._mysql:
            return None, None
        name, mod = self._mod
        try:
            cur = self._raw.cursor(dictionary=True)
        except TypeError:
            cur = self._raw.cursor()
        return mod, cur

    def cursor(self):
        return _MyCursor(self) if self._mysql else _SqliteCursor(self._raw.cursor())

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def ping(self):
        """连接健康检查（MySQL 池化后必须，防止用到被服务端掐掉的连接）"""
        if not self._mysql:
            return True
        try:
            raw = self._raw
            if hasattr(raw, "ping"):
                try:
                    raw.ping(reconnect=True)
                except TypeError:
                    raw.ping()
            else:
                cur = raw.cursor()
                cur.execute("SELECT 1")
                cur.close()
            return True
        except Exception:
            return False

    def commit(self):
        self._raw.commit()

    def rollback(self):
        try:
            self._raw.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass


# ===========================================================================
# 连接池（MySQL 专用；SQLite 走全局锁，无需池）
# ===========================================================================

class _Pool:
    """线程安全的有界连接池

    - 空闲复用、超限阻塞、坏连接丢弃
    - **自动缩容**：后台清理线程定期关闭"空闲超过 idle_timeout"的连接，
      但至少保留 min_idle 个，避免高并发后连接长期占着不放。
    """

    def __init__(self, factory, size, timeout=15.0,
                 idle_timeout=300.0, min_idle=1, reap_interval=60.0):
        self._factory = factory
        self._size = max(1, int(size))
        self._timeout = timeout
        self._idle_timeout = max(1.0, float(idle_timeout))
        self._min_idle = max(0, min(int(min_idle), self._size))
        self._reap_interval = max(1.0, float(reap_interval))

        self._idle = queue.Queue(maxsize=self._size)   # 元素: (conn, last_used_ts)
        self._made = 0
        self._lock = threading.Lock()
        self._hit = 0
        self._shrunk = 0
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop,
                                        name="dbpool-reaper", daemon=True)
        self._reaper.start()

    # -- 内部 --
    def _new(self):
        return self._factory()

    def _discard(self, conn):
        try:
            conn.close()
        except Exception:
            pass
        with self._lock:
            self._made = max(0, self._made - 1)

    def _try_idle(self):
        """取一个可用空闲连接；返回 conn 或 None"""
        while True:
            try:
                conn, ts = self._idle.get_nowait()
            except queue.Empty:
                return None
            if (time.time() - ts) > self._idle_timeout:
                self._discard(conn)          # 空闲过久，直接回收
                continue
            if conn.ping():
                self._hit += 1
                return conn
            self._discard(conn)              # 坏连接

    # -- 对外 --
    def acquire(self):
        conn = self._try_idle()
        if conn is not None:
            return conn
        with self._lock:
            if self._made < self._size:
                self._made += 1
                create = True
            else:
                create = False
        if create:
            try:
                return self._new()
            except Exception:
                with self._lock:
                    self._made -= 1
                raise
        # 池满 -> 阻塞等待（等到的可能是刚被释放的）
        try:
            conn, ts = self._idle.get(timeout=self._timeout)
        except queue.Empty:
            raise RuntimeError("连接池繁忙（上限 %d），等待 %.0fs 超时"
                               % (self._size, self._timeout))
        if conn.ping():
            self._hit += 1
            return conn
        self._discard(conn)
        raise RuntimeError("连接池中的连接均不可用")

    def release(self, conn, ok=True):
        if conn is None:
            return
        if not ok or self._stop.is_set():
            self._discard(conn)
            return
        try:
            self._idle.put_nowait((conn, time.time()))
        except queue.Full:
            self._discard(conn)

    def reap_once(self):
        """清理过期的空闲连接（至少保留 min_idle 个）。返回释放数量"""
        now = time.time()
        items = []
        while True:
            try:
                items.append(self._idle.get_nowait())
            except queue.Empty:
                break
        # 新的排前面
        items.sort(key=lambda x: x[1], reverse=True)
        keep = items[:self._min_idle]
        rest = items[self._min_idle:]
        closed = 0
        for conn, ts in rest:
            if (now - ts) > self._idle_timeout:
                self._discard(conn)
                closed += 1
            else:
                keep.append((conn, ts))
        for it in keep:
            try:
                self._idle.put_nowait(it)
            except queue.Full:
                self._discard(it[0])
        if closed:
            with self._lock:
                self._shrunk += closed
        return closed

    def _reap_loop(self):
        while not self._stop.wait(self._reap_interval):
            try:
                n = self.reap_once()
                if n:
                    try:
                        sys.stderr.write("[dbpool] 自动缩容，释放 %d 个空闲连接\n" % n)
                    except Exception:
                        pass
            except Exception:
                pass

    def close_all(self):
        self._stop.set()
        while True:
            try:
                conn, _ = self._idle.get_nowait()
                self._discard(conn)
            except queue.Empty:
                break

    def stats(self):
        with self._lock:
            made = self._made
        idle = self._idle.qsize()
        return {"enabled": True, "size": self._size, "created": made,
                "idle": idle, "in_use": max(0, made - idle),
                "reused": self._hit, "shrunk": self._shrunk,
                "idle_timeout": int(self._idle_timeout), "min_idle": self._min_idle}


_POOL = None
_POOL_LOCK = threading.Lock()


def pool_size():
    try:
        return max(1, int(os.environ.get("DB_POOL_SIZE", "5")))
    except Exception:
        return 5


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return float(default)


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return int(default)


def _get_pool():
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = _Pool(_connect, pool_size(),
                              idle_timeout=_env_float("DB_POOL_IDLE_TIMEOUT", 300),
                              min_idle=_env_int("DB_POOL_MIN_IDLE", 1),
                              reap_interval=_env_float("DB_POOL_REAP_INTERVAL", 60))
    return _POOL


def pool_stats():
    if not _is_mysql():
        return {"enabled": False, "note": "SQLite 后端使用全局写锁，无需连接池"}
    try:
        return _get_pool().stats()
    except Exception as e:
        return {"enabled": False, "error": str(e)}


# ===========================================================================
# 路径 / 开关
# ===========================================================================

def _is_frozen():
    return getattr(sys, "frozen", False)


def resource_dir():
    if _is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def app_dir():
    if _is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def db_path():
    """SQLite 文件路径；MySQL 时返回可读的连接描述"""
    if _is_mysql():
        c = _mysql_cfg()
        return "mysql://%s@%s:%s/%s" % (c["user"], c["host"], c["port"], c["database"])
    p = (os.environ.get("MARKET_DB") or "").strip()
    if p:
        return p
    return os.path.join(app_dir(), "data", "market.db")


def enabled():
    if str(os.environ.get("MARKET_DB_ENABLED", "1")).lower() in ("0", "false", "no", "off"):
        return False
    return not _DISABLED


def _on_error(exc):
    global _ERR_COUNT, _DISABLED
    _ERR_COUNT += 1
    try:
        sys.stderr.write("[market_db] %s\n" % exc)
    except Exception:
        pass
    if _ERR_COUNT >= _MAX_ERRS:
        _DISABLED = True
        try:
            sys.stderr.write("[market_db] 连续失败 %d 次，已自动停用落库\n" % _ERR_COUNT)
        except Exception:
            pass


def _schema_sql():
    name = "mysql_schema.sql" if _is_mysql() else "schema.sql"
    sub = ("deploy", "") if _is_mysql() else ("", "")
    for base in (resource_dir(), app_dir()):
        for s in sub:
            p = os.path.join(base, s, name) if s else os.path.join(base, name)
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass
    return ""


def _connect():
    if _is_mysql():
        if not mysql_available():
            raise RuntimeError("MySQL 驱动不可用：pip install pymysql（%s）" % _MYSQL_ERR)
        cfg = _mysql_cfg()
        try:
            import pymysql
            raw = pymysql.connect(charset="utf8mb4", autocommit=False, cursorclass=pymysql.cursors.DictCursor, **cfg)
        except ImportError:
            import mysql.connector
            raw = mysql.connector.connect(charset="utf8mb4", **cfg)
        return _Conn(raw, True)

    import sqlite3
    p = db_path()
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    raw = sqlite3.connect(p, timeout=15)
    raw.row_factory = sqlite3.Row
    for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=10000",
                   "PRAGMA synchronous=NORMAL"):
        try:
            raw.execute(pragma)
        except Exception:
            pass
    return _Conn(raw, False)


def init_db(force=False):
    """建库建表（幂等）。返回 True/False。

    注意：会记录已初始化的目标（路径/DSN），目标变化时自动重新初始化，
    避免同一进程内切换数据库后表不存在。
    """
    global _INITED, _INITED_PATH
    target = db_path()
    if _INITED and not force and _INITED_PATH == target:
        return True
    if not enabled():
        return False
    sql = _schema_sql()
    if not sql:
        _on_error("schema 文件未找到（%s）" % ("mysql_schema.sql" if _is_mysql() else "schema.sql"))
        return False
    try:
        with _LOCK:
            conn = _connect()
            try:
                for raw in sql.split(";"):
                    # 去掉注释行后再判断语句类型（兼容 -- 注释块）
                    st = "\n".join(l for l in raw.splitlines()
                                    if l.strip() and not l.strip().startswith("--")).strip()
                    if not st:
                        continue
                    if not st.upper().startswith(("CREATE", "SET", "USE", "ALTER", "DROP", "INSERT")):
                        continue
                    try:
                        conn.execute(st)
                    except Exception as e:
                        # IF NOT EXISTS 之类的幂等错误忽略
                        if "exist" not in str(e).lower():
                            raise
                conn.commit()
            finally:
                conn.close()
        _INITED = True
        _INITED_PATH = target
        return True
    except Exception as e:
        _on_error(e)
        return False


def _write(fn):
    if not enabled() or not init_db():
        return None
    if _is_mysql():
        # MySQL：走连接池，不加全局锁（真并发）
        conn = None
        ok = False
        try:
            conn = _get_pool().acquire()
            out = fn(conn)
            conn.commit()
            ok = True
            return out
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    ok = False
            _on_error(e)
            return None
        finally:
            if conn is not None:
                _get_pool().release(conn, ok)
    # SQLite：保持单一写锁（写操作本就串行）
    try:
        with _LOCK:
            conn = _connect()
            try:
                out = fn(conn)
                conn.commit()
                return out
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    except Exception as e:
        _on_error(e)
        return None


def _read(fn, default=None):
    if not enabled() or not init_db():
        return default
    if _is_mysql():
        conn = None
        ok = False
        try:
            conn = _get_pool().acquire()
            out = fn(conn)
            # 关键：结束本次读事务。否则连接被复用时（REPEATABLE READ）
            # 会继续看到旧快照，出现"刚写入却读不到"的假象。
            try:
                conn.rollback()
            except Exception:
                pass
            ok = True
            return out
        except Exception as e:
            _on_error(e)
            return default
        finally:
            if conn is not None:
                _get_pool().release(conn, ok)
    try:
        with _LOCK:
            conn = _connect()
            try:
                return fn(conn)
            finally:
                conn.close()
    except Exception as e:
        _on_error(e)
        return default


# ===========================================================================
# 通用小工具
# ===========================================================================

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_code(code):
    if not code:
        return ""
    c = str(code).strip().upper()
    for s in _SUFFIXES:
        c = c.replace(s, "")
    return c.replace(".", "").strip()


def _num(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
        if f != f:
            return None
        return f
    except Exception:
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _boards_count(text):
    if not text:
        return None
    m = re.search(r"(\d+)\s*连板", str(text))
    if m:
        return int(m.group(1))
    if "首板" in str(text):
        return 1
    return None


def _dumps(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return None


def _cols(names):
    return ",".join("`%s`" % n for n in names)


def _ph(n):
    return ",".join(["?"] * n)


def _upsert(table, cols, conflict, updates=None):
    """生成跨方言 UPSERT SQL（标识符用反引号，SQLite 亦兼容）"""
    updates = updates or []
    if _is_mysql():
        if not updates:
            return "INSERT IGNORE INTO `%s` (%s) VALUES (%s)" % (table, _cols(cols), _ph(len(cols)))
        sets = ",".join("`%s`=VALUES(`%s`)" % (c, c) for c in updates)
        return ("INSERT INTO `%s` (%s) VALUES (%s) ON DUPLICATE KEY UPDATE %s"
                % (table, _cols(cols), _ph(len(cols)), sets))
    if not updates or not conflict:
        return "INSERT OR IGNORE INTO `%s` (%s) VALUES (%s)" % (table, _cols(cols), _ph(len(cols)))
    sets = ",".join("`%s`=excluded.`%s`" % (c, c) for c in updates)
    return ("INSERT INTO `%s` (%s) VALUES (%s) ON CONFLICT(%s) DO UPDATE SET %s"
            % (table, _cols(cols), _ph(len(cols)), _cols(conflict), sets))


def _replace_into(table, cols):
    if _is_mysql():
        return "REPLACE INTO `%s` (%s) VALUES (%s)" % (table, _cols(cols), _ph(len(cols)))
    return "INSERT OR REPLACE INTO `%s` (%s) VALUES (%s)" % (table, _cols(cols), _ph(len(cols)))


def _upsert_stock(cur, code, name=None):
    code = clean_code(code)
    if not code:
        return
    if code.startswith(("6", "9")):
        market = "SH"
    elif code.startswith(("4", "8")):
        market = "BJ"
    else:
        market = "SZ"
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        board = "主板"
    elif code.startswith(("300", "301")):
        board = "创业板"
    elif code.startswith("688"):
        board = "科创板"
    else:
        board = None
    cur.execute(
        _upsert("stock", ["code", "name", "market", "board", "updated_at"], ["code"],
                ["name", "market", "board", "updated_at"]),
        (code, name or None, market, board, now_str()))


def log_fetch(task_type, source=None, endpoint=None, trade_date=None,
              status="ok", http_code=None, rows=None, duration_ms=None,
              error=None, detail=None, started_at=None):
    def _f(conn):
        conn.execute(
            "INSERT INTO `fetch_log` (%s) VALUES (%s)" % (
                _cols(["task_type", "source", "endpoint", "trade_date", "status",
                       "http_code", "rows", "duration_ms", "error", "detail",
                       "started_at", "finished_at"]),
                _ph(12)),
            (task_type, source, endpoint, trade_date, status, http_code, rows,
             duration_ms, error, detail, started_at, now_str()))
        return True
    return _write(_f)


# ===========================================================================
# 交易日历
# ===========================================================================

def save_calendar(days):
    days = sorted({str(d).strip() for d in (days or []) if d})
    if not days:
        return 0

    def _f(conn):
        cur = conn.cursor()
        sql = _upsert("trade_calendar",
                      ["trade_date", "is_open", "prev_trade_date", "next_trade_date",
                       "source", "updated_at"],
                      ["trade_date"],
                      ["is_open", "prev_trade_date", "next_trade_date", "updated_at"])
        for i, d in enumerate(days):
            cur.execute(sql, (d, 1, days[i - 1] if i > 0 else None,
                              days[i + 1] if i + 1 < len(days) else None,
                              "sse_index_kline", now_str()))
        return len(days)
    return _write(_f)


def load_calendar(n=60):
    def _f(conn):
        rows = conn.execute(
            "SELECT `trade_date` FROM `trade_calendar` WHERE `is_open`=1 "
            "ORDER BY `trade_date` DESC LIMIT ?", (int(n),)).fetchall()
        return [r["trade_date"] for r in rows]
    return _read(_f, []) or []


def calendar_count():
    return _read(lambda c: c.execute("SELECT COUNT(*) FROM `trade_calendar`").fetchone()[0], 0)


# ===========================================================================
# 人气榜
# ===========================================================================

_HOT_COLS = ["trade_date", "captured_at", "rank", "stock_code", "stock_name",
             "rise_and_fall", "boards_count", "boards_text", "tier", "concept_tag",
             "anomaly_analysis", "is_hot", "source", "degraded"]
_HOT_UPD = ["rank", "stock_name", "rise_and_fall", "boards_count", "boards_text",
            "tier", "concept_tag", "anomaly_analysis", "is_hot", "source", "degraded"]


def save_hotlist(trade_date, rows, source=None, degraded=False, captured_at=None):
    if not trade_date or not rows:
        return 0
    cap = captured_at or now_str()

    def _f(conn):
        cur = conn.cursor()
        sql = _upsert("hotlist_snapshot", _HOT_COLS,
                      ["trade_date", "captured_at", "stock_code"], _HOT_UPD)
        for r in rows:
            code = clean_code(r.get("code"))
            if not code:
                continue
            _upsert_stock(cur, code, r.get("name"))
            cur.execute(sql, (
                trade_date, cap, _int(r.get("rank")), code, r.get("name"),
                _num(r.get("rise_and_fall")), _boards_count(r.get("consecutive_boards")),
                r.get("consecutive_boards"), r.get("tier"), r.get("concept_tag"),
                r.get("anomaly_analysis"), 1 if r.get("is_hot") else 0,
                source, 1 if degraded else 0))
        return len(rows)
    return _write(_f)


# 历史回补的数据源标记（东方财富人气榜，非当天实时抓取）
BACKFILL_SOURCE = "东方财富人气榜·历史回补"


def is_backfill_source(src):
    return bool(src) and ("回补" in str(src))


def load_hotlist(trade_date, prefer_live=True):
    """取该交易日的人气榜。

    prefer_live=True（默认）：优先用当天实时抓取的数据；只有当该日**没有**
    实时数据时，才使用历史回补的数据（避免回补数据盖掉真实快照）。
    """
    if not trade_date:
        return None

    def _f(conn):
        if prefer_live:
            # 实时抓取的优先；都没有实时数据时才退回补数据
            order = ("ORDER BY (CASE WHEN `source` LIKE '%回补%' THEN 1 ELSE 0 END) ASC, "
                     "`captured_at` DESC")
        else:
            order = "ORDER BY `captured_at` DESC"
        row = conn.execute("SELECT `captured_at` FROM `hotlist_snapshot` "
                           "WHERE `trade_date`=? " + order + " LIMIT 1",
                           (trade_date,)).fetchone()
        cap = row[0] if row else None
        if not cap:
            return None
        rows = conn.execute(
            "SELECT `rank`,`stock_code`,`stock_name`,`rise_and_fall`,`boards_text`,`tier`,"
            "`concept_tag`,`anomaly_analysis`,`is_hot`,`source`,`degraded` "
            "FROM `hotlist_snapshot` WHERE `trade_date`=? AND `captured_at`=? "
            "ORDER BY `rank`", (trade_date, cap)).fetchall()
        if not rows:
            return None
        data = [{
            "rank": r["rank"], "name": r["stock_name"], "code": r["stock_code"],
            "rise_and_fall": r["rise_and_fall"], "consecutive_boards": r["boards_text"],
            "tier": r["tier"], "concept_tag": r["concept_tag"],
            "anomaly_analysis": r["anomaly_analysis"], "is_hot": bool(r["is_hot"]),
        } for r in rows]
        return {"data": data, "source": rows[0]["source"],
                "degraded": bool(rows[0]["degraded"]), "captured_at": cap}
    return _read(_f)


def save_backfill_hotlist(trade_date, rows, captured_at=None):
    """写入历史回补的人气榜（source 标记为回补，captured_at 用真实回补时间）"""
    return save_hotlist(trade_date, rows, source=BACKFILL_SOURCE,
                        degraded=False, captured_at=captured_at or now_str())


def clear_backfill_hotlist(trade_date=None):
    """清掉回补数据（不影响实时抓取的数据）"""
    def _f(conn):
        if trade_date:
            cur = conn.execute("DELETE FROM `hotlist_snapshot` WHERE `trade_date`=? "
                               "AND `source` LIKE '%回补%'", (trade_date,))
        else:
            cur = conn.execute("DELETE FROM `hotlist_snapshot` WHERE `source` LIKE '%回补%'")
        return cur.rowcount
    return _write(_f) or 0


def backfill_dates(limit=120):
    """已有回补数据的交易日"""
    def _f(conn):
        rows = conn.execute("SELECT DISTINCT `trade_date` FROM `hotlist_snapshot` "
                            "WHERE `source` LIKE '%回补%' ORDER BY `trade_date` DESC LIMIT ?",
                            (int(limit),)).fetchall()
        return [r["trade_date"] for r in rows]
    return _read(_f, []) or []


def hotlist_dates(limit=30):
    def _f(conn):
        rows = conn.execute("SELECT DISTINCT `trade_date` FROM `hotlist_snapshot` "
                            "ORDER BY `trade_date` DESC LIMIT ?", (int(limit),)).fetchall()
        return [r["trade_date"] for r in rows]
    return _read(_f, []) or []


# ===========================================================================
# 日K线
# ===========================================================================

_K_COLS = ["stock_code", "trade_date", "open", "high", "low", "close", "prev_close",
           "change_pct", "volume", "amount", "source", "collected_at"]
_K_UPD = ["open", "high", "low", "close", "volume", "source", "collected_at"]


def _kline_upsert_sql():
    """日K 的 UPSERT：prev_close/change_pct 用 COALESCE 保留旧值"""
    if _is_mysql():
        return ("INSERT INTO `daily_kline` (%s) VALUES (%s) ON DUPLICATE KEY UPDATE "
                "`open`=VALUES(`open`), `high`=VALUES(`high`), `low`=VALUES(`low`), "
                "`close`=VALUES(`close`), `prev_close`=COALESCE(VALUES(`prev_close`), `prev_close`), "
                "`change_pct`=COALESCE(VALUES(`change_pct`), `change_pct`), "
                "`volume`=VALUES(`volume`), `amount`=COALESCE(VALUES(`amount`), `amount`), "
                "`source`=VALUES(`source`), `collected_at`=VALUES(`collected_at`)"
                % (_cols(_K_COLS), _ph(len(_K_COLS))))
    return ("INSERT INTO `daily_kline` (%s) VALUES (%s) ON CONFLICT(`stock_code`,`trade_date`) "
            "DO UPDATE SET `open`=excluded.`open`, `high`=excluded.`high`, "
            "`low`=excluded.`low`, `close`=excluded.`close`, "
            "`prev_close`=COALESCE(excluded.`prev_close`, `daily_kline`.`prev_close`), "
            "`change_pct`=COALESCE(excluded.`change_pct`, `daily_kline`.`change_pct`), "
            "`volume`=excluded.`volume`, `amount`=COALESCE(excluded.`amount`, `daily_kline`.`amount`), "
            "`source`=excluded.`source`, `collected_at`=excluded.`collected_at`"
            % (_cols(_K_COLS), _ph(len(_K_COLS))))


def _kline_row(code, d, o, h, l, close, pc, chg, vol, amt, source, ts):
    return (code, d, o, h, l, close, pc, chg, vol, amt, source, ts)


def save_daily_kline(code, bars, source="sina", prev_close=None):
    code = clean_code(code)
    if not code or not bars:
        return 0
    seq = sorted(bars, key=lambda x: str(x.get("day") or x.get("date") or ""))
    seq = [b for b in seq if (b.get("day") or b.get("date"))]
    if not seq:
        return 0

    def _f(conn):
        cur = conn.cursor()
        _upsert_stock(cur, code, None)
        sql = _kline_upsert_sql()
        ts = now_str()
        prev = prev_close
        n = 0
        for b in seq:
            d = str(b.get("day") or b.get("date"))
            close = _num(b.get("close"))
            pc = _num(b.get("prev_close"))
            if pc is None:
                pc = prev
            chg = round((close - pc) / pc * 100, 4) if (pc and close is not None and pc > 0) else None
            cur.execute(sql, _kline_row(code, d, _num(b.get("open")), _num(b.get("high")),
                                        _num(b.get("low")), close, pc, chg,
                                        _num(b.get("volume")), _num(b.get("amount")),
                                        source, ts))
            prev = close
            n += 1
        return n
    return _write(_f)


def save_daily_batch(trade_date, items, source="sina"):
    items = [x for x in (items or []) if clean_code(x.get("code"))]
    if not trade_date or not items:
        return 0

    def _f(conn):
        cur = conn.cursor()
        sql = _kline_upsert_sql()
        ts = now_str()
        for it in items:
            code = clean_code(it.get("code"))
            close = _num(it.get("close"))
            pc = _num(it.get("prev_close"))
            chg = round((close - pc) / pc * 100, 4) if (pc and close is not None and pc > 0) else None
            cur.execute(sql, _kline_row(code, trade_date, _num(it.get("open")),
                                        _num(it.get("high")), _num(it.get("low")), close,
                                        pc, chg, _num(it.get("volume")),
                                        _num(it.get("amount")), source, ts))
        return len(items)
    return _write(_f)


def load_daily_kline(code, limit=60, end_date=None):
    code = clean_code(code)
    if not code:
        return []

    def _f(conn):
        base = ("SELECT `trade_date`,`open`,`high`,`low`,`close`,`volume` FROM `daily_kline` "
                "WHERE `stock_code`=?")
        if end_date:
            rows = conn.execute(base + " AND `trade_date`<=? ORDER BY `trade_date` DESC LIMIT ?",
                                (code, end_date, int(limit))).fetchall()
        else:
            rows = conn.execute(base + " ORDER BY `trade_date` DESC LIMIT ?",
                                (code, int(limit))).fetchall()
        out = [{"date": r["trade_date"], "open": _num(r["open"]), "close": _num(r["close"]),
                "high": _num(r["high"]), "low": _num(r["low"]),
                "volume": _num(r["volume"])} for r in rows]
        out.reverse()
        return out
    return _read(_f, []) or []


def kline_dates(code):
    def _f(conn):
        r = conn.execute("SELECT MIN(`trade_date`), MAX(`trade_date`), COUNT(*) "
                         "FROM `daily_kline` WHERE `stock_code`=?",
                         (clean_code(code),)).fetchone()
        if not r or not r[2]:
            return None
        return {"start": r[0], "end": r[1], "count": r[2]}
    return _read(_f)


def load_prev_close(code, trade_date):
    code = clean_code(code)
    if not code or not trade_date:
        return None

    def _f(conn):
        r = conn.execute("SELECT `close` FROM `daily_kline` WHERE `stock_code`=? "
                         "AND `trade_date`<? ORDER BY `trade_date` DESC LIMIT 1",
                         (code, trade_date)).fetchone()
        return _num(r["close"]) if r else None
    return _read(_f)


# ===========================================================================
# 分时线
# ===========================================================================

def save_minute(code, trade_date, points, source="tencent"):
    code = clean_code(code)
    points = [p for p in (points or []) if p.get("time")]
    if not code or not trade_date or not points:
        return 0

    def _f(conn):
        cur = conn.cursor()
        _upsert_stock(cur, code, None)
        sql = _upsert("minute_kline",
                      ["stock_code", "trade_date", "minute", "price", "avg_price", "volume"],
                      ["stock_code", "trade_date", "minute"],
                      ["price", "avg_price", "volume"])
        for p in points:
            cur.execute(sql, (code, trade_date, p.get("time"), _num(p.get("price")),
                              _num(p.get("avg_price")), _num(p.get("volume"))))
        return len(points)
    return _write(_f)


def load_minute(code, trade_date):
    code = clean_code(code)
    if not code or not trade_date:
        return []

    def _f(conn):
        rows = conn.execute("SELECT `minute`,`price`,`volume` FROM `minute_kline` "
                            "WHERE `stock_code`=? AND `trade_date`=? ORDER BY `minute`",
                            (code, trade_date)).fetchall()
        return [{"time": r["minute"], "price": _num(r["price"]),
                 "volume": _num(r["volume"])} for r in rows]
    return _read(_f, []) or []


def minute_dates(code, limit=5):
    def _f(conn):
        rows = conn.execute("SELECT DISTINCT `trade_date` FROM `minute_kline` "
                            "WHERE `stock_code`=? ORDER BY `trade_date` DESC LIMIT ?",
                            (clean_code(code), int(limit))).fetchall()
        return [r["trade_date"] for r in rows]
    return _read(_f, []) or []


def purge_minute(keep_days=30):
    def _f(conn):
        row = conn.execute("SELECT DISTINCT `trade_date` FROM `minute_kline` "
                           "ORDER BY `trade_date` DESC LIMIT 1 OFFSET ?",
                           (int(keep_days),)).fetchone()
        if not row:
            return 0
        cur = conn.execute("DELETE FROM `minute_kline` WHERE `trade_date` < ?", (row[0],))
        return cur.rowcount
    return _write(_f) or 0


# ===========================================================================
# 资讯公告
# ===========================================================================

def save_news(code, items):
    code = clean_code(code)
    items = [x for x in (items or []) if x.get("title")]
    if not code or not items:
        return 0

    def _f(conn):
        cur = conn.cursor()
        _upsert_stock(cur, code, None)
        sql = _upsert("stock_news",
                      ["stock_code", "news_date", "title", "source", "news_type", "url", "collected_at"],
                      ["stock_code", "url"],
                      ["news_date", "title", "source"])
        for it in items:
            url = it.get("url") or ("%s|%s" % (code, it.get("title")))
            cur.execute(sql, (code, (it.get("date") or "")[:10], it.get("title"),
                              it.get("source"), "公告", url, now_str()))
        return len(items)
    return _write(_f)


def load_news(code, limit=8):
    code = clean_code(code)
    if not code:
        return []

    def _f(conn):
        rows = conn.execute("SELECT `title`,`news_date`,`source`,`url` FROM `stock_news` "
                            "WHERE `stock_code`=? ORDER BY `news_date` DESC, `id` DESC LIMIT ?",
                            (code, int(limit))).fetchall()
        return [{"title": r["title"], "date": r["news_date"],
                 "source": r["source"], "url": r["url"]} for r in rows]
    return _read(_f, []) or []


# ===========================================================================
# 涨停 / 炸板池
# ===========================================================================

def save_limit_up_pool(trade_date, pool, kind):
    if not trade_date or not pool:
        return 0
    state = "涨停" if kind == "ZT" else "炸板"

    def _f(conn):
        cur = conn.cursor()
        sql = _upsert("limit_up_pool",
                      ["trade_date", "stock_code", "boards", "first_seal_time", "last_seal_time",
                       "break_count", "amount", "sector", "state", "source", "collected_at"],
                      ["trade_date", "stock_code"],
                      ["boards", "first_seal_time", "last_seal_time", "break_count",
                       "amount", "sector", "state", "collected_at"])
        n = 0
        for code, info in pool.items():
            code = clean_code(code)
            if not code:
                continue
            _upsert_stock(cur, code, None)
            cur.execute(sql, (trade_date, code, _int(info.get("boards")),
                              info.get("firstSeal"), info.get("lastSeal"),
                              _int(info.get("breakCount")), _num(info.get("amount")),
                              info.get("sector"), state, "eastmoney", now_str()))
            n += 1
        return n
    return _write(_f)


def load_limit_up_pool(trade_date, state=None):
    if not trade_date:
        return []

    def _f(conn):
        if state:
            rows = conn.execute("SELECT * FROM `limit_up_pool` WHERE `trade_date`=? AND `state`=? "
                                "ORDER BY `boards` DESC", (trade_date, state)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM `limit_up_pool` WHERE `trade_date`=? "
                                "ORDER BY `boards` DESC", (trade_date,)).fetchall()
        return [dict(r) for r in rows]
    return _read(_f, []) or []


# ===========================================================================
# 选股
# ===========================================================================

_SR_COLS = ["run_id", "target_date", "stock_code", "stock_name", "close_prev", "high",
            "gain_high", "close", "gain_close", "amount_est", "first_seal", "boards",
            "sector", "state", "bucket", "rank"]


def save_screening(res):
    if not res or not res.get("success"):
        return None
    target = res.get("target")
    if not target:
        return None
    funnel = res.get("funnel") or {}

    def _f(conn):
        cur = conn.cursor()
        sql = _upsert("screening_run",
                      ["target_date", "prev_trade_date", "universe_count", "cond2_count",
                       "cond1_count", "sealed_count", "broken_count", "removed_count",
                       "elapsed_sec", "source", "payload_json", "finished_at"],
                      ["target_date"],
                      ["prev_trade_date", "universe_count", "cond2_count", "cond1_count",
                       "sealed_count", "broken_count", "removed_count", "elapsed_sec",
                       "source", "payload_json", "finished_at"])
        cur.execute(sql, (target, res.get("prevDay"), res.get("universe"),
                          funnel.get("cond2"), funnel.get("final"), funnel.get("sealed"),
                          funnel.get("broken"), funnel.get("removedByCond1"),
                          _num(res.get("elapsed")), res.get("source"), _dumps(res), now_str()))
        row = cur.execute("SELECT `run_id` FROM `screening_run` WHERE `target_date`=?",
                          (target,)).fetchone()
        run_id = row["run_id"] if row else None
        if not run_id:
            return None
        cur.execute("DELETE FROM `screening_result` WHERE `run_id`=?", (run_id,))
        isql = _replace_into("screening_result", _SR_COLS)
        for bucket, key in (("selected", "rows"), ("broken", "brokenRows"), ("removed", "removedRows")):
            for i, r in enumerate(res.get(key) or [], 1):
                code = clean_code(r.get("code"))
                if not code:
                    continue
                cur.execute(isql, (
                    run_id, target, code, r.get("name"), _num(r.get("closePrev")),
                    _num(r.get("high")), _num(r.get("gainHigh")), _num(r.get("close")),
                    _num(r.get("gainClose")), _num(r.get("amountEst")), r.get("firstSeal"),
                    _int(r.get("boards")), r.get("sector"), r.get("poolState"), bucket, i))
        return run_id
    return _write(_f)


def load_screening(target):
    if not target:
        return None

    def _f(conn):
        row = conn.execute("SELECT `payload_json` FROM `screening_run` WHERE `target_date`=?",
                           (target,)).fetchone()
        if row and row["payload_json"]:
            txt = row["payload_json"]
            if isinstance(txt, (bytes, bytearray)):
                txt = txt.decode("utf-8", "ignore")
            try:
                return json.loads(txt)
            except Exception:
                return None
        return None
    return _read(_f)


def screening_dates(limit=60):
    def _f(conn):
        rows = conn.execute("SELECT `target_date` FROM `screening_run` "
                            "ORDER BY `target_date` DESC LIMIT ?", (int(limit),)).fetchall()
        return [r["target_date"] for r in rows]
    return _read(_f, []) or []


# ===========================================================================
# 原始响应快照
# ===========================================================================

def _payload_put(cur, kind, trade_date, obj):
    cur.execute(
        _upsert("raw_payload", ["cache_key", "kind", "trade_date", "payload_json", "created_at"],
                ["cache_key"], ["payload_json", "created_at"]),
        ("%s:%s" % (kind, trade_date), kind, trade_date, _dumps(obj), now_str()))


def save_payload(kind, trade_date, obj):
    if not kind or not trade_date or obj is None:
        return False

    def _f(conn):
        _payload_put(conn.cursor(), kind, trade_date, obj)
        return True
    return _write(_f)


def load_payload(kind, trade_date):
    if not kind or not trade_date:
        return None

    def _f(conn):
        row = conn.execute("SELECT `payload_json` FROM `raw_payload` WHERE `cache_key`=?",
                           ("%s:%s" % (kind, trade_date),)).fetchone()
        if row and row["payload_json"]:
            txt = row["payload_json"]
            if isinstance(txt, (bytes, bytearray)):
                txt = txt.decode("utf-8", "ignore")
            try:
                return json.loads(txt)
            except Exception:
                return None
        return None
    return _read(_f)


# ===========================================================================
# 题材热度
# ===========================================================================

def save_event_themes(res, trade_date=None):
    if not res or not res.get("success"):
        return 0
    td = trade_date or res.get("as_of") or res.get("tradeDate")
    if not td:
        td = datetime.now().strftime("%Y-%m-%d")

    def _f(conn):
        cur = conn.cursor()
        cap = now_str()
        sql = _upsert("theme_heat_snapshot",
                      ["trade_date", "captured_at", "theme_name", "tag", "verdict", "rank",
                       "heat_score", "pop_heat", "topic_heat", "net_score", "bull", "bear",
                       "stock_total", "stock_count", "reason_summary"],
                      ["trade_date", "theme_name"],
                      ["captured_at", "tag", "verdict", "rank", "heat_score", "pop_heat",
                       "topic_heat", "net_score", "bull", "bear", "stock_total",
                       "stock_count", "reason_summary"])
        tsql = _upsert("theme_top_stock",
                       ["trade_date", "theme_name", "stock_code", "stock_name", "hot_rank",
                        "trend_rank", "rank"],
                       ["trade_date", "theme_name", "stock_code"],
                       ["stock_name", "hot_rank", "trend_rank", "rank"])
        n = 0
        for i, t in enumerate(res.get("allThemes") or res.get("rows") or [], 1):
            name = t.get("name")
            if not name:
                continue
            cur.execute(sql, (td, cap, name, t.get("tag"), t.get("verdict"),
                              t.get("rank") or i, _num(t.get("heatScore")),
                              _num(t.get("popHeat")), _num(t.get("topicHeat")),
                              _int(t.get("netScore")), _int(t.get("bull")), _int(t.get("bear")),
                              _int(t.get("stockTotal")), _int(t.get("stockCount")),
                              t.get("reason") or t.get("reasonSummary")))
            n += 1
            for s in (t.get("stocks") or [])[:50]:
                sc = clean_code(s.get("ticker") or s.get("code"))
                if not sc:
                    continue
                cur.execute(tsql, (td, name, sc, s.get("name"), _int(s.get("hotRank")),
                                   _int(s.get("trendRank")), None))
        csql = _upsert("theme_topic",
                       ["trade_date", "title", "description", "hot", "url", "source", "collected_at"],
                       ["trade_date", "title"], ["description", "hot", "url"])
        for t in (res.get("topics") or []):
            title = t.get("title")
            if not title:
                continue
            cur.execute(csql, (td, title, t.get("desc"), _num(t.get("hot")),
                               t.get("url"), "ths_topic", cap))
        _payload_put(cur, "themes", td, res)
        return n
    return _write(_f)


def load_event_themes(trade_date):
    return load_payload("themes", trade_date)


def theme_dates(limit=30):
    def _f(conn):
        rows = conn.execute("SELECT DISTINCT `trade_date` FROM `theme_heat_snapshot` "
                            "ORDER BY `trade_date` DESC LIMIT ?", (int(limit),)).fetchall()
        return [r["trade_date"] for r in rows]
    return _read(_f, []) or []


def theme_history(theme_name, limit=10):
    if not theme_name:
        return []

    def _f(conn):
        rows = conn.execute("SELECT `trade_date`,`heat_score`,`rank`,`verdict` "
                            "FROM `theme_heat_snapshot` WHERE `theme_name`=? "
                            "ORDER BY `trade_date` DESC LIMIT ?",
                            (theme_name, int(limit))).fetchall()
        return [dict(r) for r in rows]
    return _read(_f, []) or []


# ===========================================================================
# 数据管理（概览 / 日期明细 / 清理 / 完整性校验）
# ===========================================================================

DATE_COLUMN = {
    "hotlist_snapshot": "trade_date",
    "limit_up_pool": "trade_date",
    "daily_kline": "trade_date",
    "minute_kline": "trade_date",
    "stock_anomaly": "trade_date",
    "dragon_tiger": "trade_date",
    "theme_heat_snapshot": "trade_date",
    "theme_topic": "trade_date",
    "theme_top_stock": "trade_date",
    "theme_topic_link": "trade_date",
    "screening_run": "target_date",
    "screening_result": "target_date",
    "scan_stock": "target_date",
    "trade_calendar": "trade_date",
    "raw_payload": "trade_date",
    "stock_news": "news_date",
    "fetch_log": None,
    "stock": None,
    "theme_catalog": None,
    "theme_member": None,
}

_TABLES = ("stock", "trade_calendar", "theme_catalog", "theme_member",
           "hotlist_snapshot", "limit_up_pool", "daily_kline", "minute_kline",
           "stock_news", "stock_anomaly", "dragon_tiger",
           "theme_heat_snapshot", "theme_topic", "theme_topic_link", "theme_top_stock",
           "screening_run", "screening_result", "scan_stock", "fetch_log", "raw_payload")

_CLEARABLE = tuple(DATE_COLUMN.keys())

TABLE_LABEL = {
    "stock": "股票基础信息", "trade_calendar": "交易日历",
    "theme_catalog": "题材目录", "theme_member": "题材成分股",
    "hotlist_snapshot": "人气榜快照", "limit_up_pool": "涨停/炸板池",
    "daily_kline": "日K线", "minute_kline": "分时线",
    "stock_news": "个股资讯公告", "stock_anomaly": "个股异动原因",
    "dragon_tiger": "龙虎榜", "theme_heat_snapshot": "题材热度快照",
    "theme_topic": "题材话题", "theme_topic_link": "话题-题材关联",
    "theme_top_stock": "题材Top50个股", "screening_run": "选股任务",
    "screening_result": "选股结果明细", "scan_stock": "扫描暂存(断点续传)",
    "fetch_log": "抓取日志",
    "raw_payload": "原始响应快照",
}

# 完整性校验规则：(表, 期望值, 比较方式, 说明)；日期列取自 DATE_COLUMN
# (表, 期望值, 比较方式, 说明, 是否按交易日过滤, 仅统计最新该列的时间点)
# 注意：人气榜一天可能抓多次（早盘/尾盘），必须只统计"最新一次抓取"，
#      否则 30*N 会误判为超量。
INTEGRITY_RULES = [
    ("hotlist_snapshot", 30, "exact", "人气榜应为 30 条（最新一次抓取）", True, "captured_at"),
    ("limit_up_pool", 5, "min", "涨停/炸板池至少 5 条", True, None),
    ("daily_kline", 1000, "min", "日K线至少 1000 条（沪深主板非ST）", True, None),
    ("theme_heat_snapshot", 3, "min", "题材热度至少 3 个题材", True, None),
    ("theme_top_stock", 3, "min", "题材个股至少 3 条", True, None),
    ("screening_run", 1, "min", "选股任务应有记录", True, None),
    ("screening_result", 5, "min", "选股结果至少 5 条", True, None),
    ("trade_calendar", 200, "min", "交易日历至少 200 天（全表）", False, None),
]


def find_last_trading_day_after(date_str=None):
    def _f(conn):
        if date_str:
            r = conn.execute("SELECT `trade_date` FROM `trade_calendar` WHERE `is_open`=1 "
                             "AND `trade_date`<=? ORDER BY `trade_date` DESC LIMIT 1",
                             (date_str,)).fetchone()
        else:
            r = conn.execute("SELECT `trade_date` FROM `trade_calendar` WHERE `is_open`=1 "
                             "ORDER BY `trade_date` DESC LIMIT 1").fetchone()
        return r[0] if r else None
    return _read(_f)


def _count(conn, table):
    try:
        return conn.execute("SELECT COUNT(*) FROM `%s`" % table).fetchone()[0]
    except Exception:
        return None


def overview():
    def _f(conn):
        out = {"enabled": enabled(), "db_path": db_path(),
               "backend": "mysql" if _is_mysql() else "sqlite",
               "pool": pool_stats(),
               "tables": [], "auto_fetch": auto_fetch_info()}
        for t in _TABLES:
            item = {"table": t, "label": TABLE_LABEL.get(t, t), "rows": _count(conn, t)}
            col = DATE_COLUMN.get(t)
            if col and item["rows"]:
                try:
                    r = conn.execute("SELECT MIN(`%s`), MAX(`%s`) FROM `%s`" % (col, col, t)).fetchone()
                    item["date_start"], item["date_end"] = r[0], r[1]
                    item["date_column"] = col
                except Exception:
                    item["date_start"] = item["date_end"] = None
            out["tables"].append(item)
        if not _is_mysql():
            try:
                out["size_mb"] = round(os.path.getsize(db_path()) / 1048576.0, 3)
            except Exception:
                out["size_mb"] = None
        else:
            try:
                r = conn.execute("SELECT ROUND(SUM(data_length+index_length)/1048576, 3) "
                                 "FROM information_schema.TABLES WHERE table_schema=DATABASE()").fetchone()
                out["size_mb"] = float(r[0]) if r and r[0] is not None else None
            except Exception:
                out["size_mb"] = None
        try:
            out["kline_days"] = conn.execute(
                "SELECT COUNT(DISTINCT `trade_date`) FROM `daily_kline`").fetchone()[0]
        except Exception:
            out["kline_days"] = None
        return out
    return _read(_f, {"enabled": False, "db_path": db_path(), "tables": []}) or {}


def table_dates(table, limit=120):
    if table not in DATE_COLUMN:
        return {"table": table, "error": "unknown table"}
    col = DATE_COLUMN.get(table)
    if not col:
        return {"table": table, "dates": [], "note": "该表没有日期列"}

    def _f(conn):
        rows = conn.execute(
            "SELECT `%s` AS d, COUNT(*) AS c FROM `%s` WHERE `%s` IS NOT NULL "
            "GROUP BY `%s` ORDER BY d DESC LIMIT ?" % (col, table, col, col),
            (int(limit),)).fetchall()
        return [{"date": r["d"], "rows": r["c"]} for r in rows]
    return {"table": table, "date_column": col, "dates": _read(_f, []) or []}


def cleanup(scope="minute", table=None, before_date=None, keep_days=None):
    def _f(conn):
        deleted = 0
        if scope == "minute":
            kd = int(keep_days or 30)
            r = conn.execute("SELECT DISTINCT `trade_date` FROM `minute_kline` "
                             "ORDER BY `trade_date` DESC LIMIT 1 OFFSET ?", (kd,)).fetchone()
            if r:
                cur = conn.execute("DELETE FROM `minute_kline` WHERE `trade_date` < ?", (r[0],))
                deleted = cur.rowcount
            return {"deleted": deleted, "detail": "分时线保留最近 %d 个交易日" % kd}

        if scope == "table":
            if table not in _CLEARABLE:
                return {"deleted": 0, "error": "不允许清空该表: %s" % table}
            cur = conn.execute("DELETE FROM `%s`" % table)
            return {"deleted": cur.rowcount, "detail": "已清空表 %s" % table}

        if scope == "before":
            if not before_date:
                return {"deleted": 0, "error": "缺少 before_date"}
            for t, col in DATE_COLUMN.items():
                if not col:
                    continue
                try:
                    cur = conn.execute("DELETE FROM `%s` WHERE `%s` IS NOT NULL AND `%s` < ?"
                                       % (t, col, col), (before_date,))
                    deleted += cur.rowcount
                except Exception:
                    pass
            return {"deleted": deleted, "detail": "已删除 %s 之前的数据" % before_date}

        if scope == "all":
            for t in _CLEARABLE:
                try:
                    cur = conn.execute("DELETE FROM `%s`" % t)
                    deleted += cur.rowcount
                except Exception:
                    pass
            if not _is_mysql():
                try:
                    conn.execute("DELETE FROM sqlite_sequence")
                except Exception:
                    pass
            return {"deleted": deleted, "detail": "已清空全部业务数据（表结构保留）"}

        return {"deleted": 0, "error": "未知 scope: %s" % scope}
    return _write(_f)


# ---------------- 数据完整性校验 ----------------

def integrity_check(trade_date=None, only=None):
    """核对某交易日的数据是否齐全。返回 {ok, items, issues}。

    注意：内部只使用传入的 conn，不再调用其它 _read/_write（避免同锁重入死锁）。
    """
    def _f(conn):
        d = trade_date
        if not d:
            r = conn.execute("SELECT `trade_date` FROM `trade_calendar` WHERE `is_open`=1 "
                             "ORDER BY `trade_date` DESC LIMIT 1").fetchone()
            d = r[0] if r else None
        if not d:
            return {"ok": False, "trade_date": None, "items": [],
                    "issues": ["交易日历为空，无法校验"]}
        items, issues = [], []
        for table, expect, mode, label, by_date, latest_col in INTEGRITY_RULES:
            if only and table not in only:
                continue
            col = DATE_COLUMN.get(table)
            try:
                if by_date and col and latest_col:
                    # 只统计该交易日"最新一次抓取"
                    n = conn.execute(
                        "SELECT COUNT(*) FROM `%s` WHERE `%s`=? AND `%s`=("
                        "SELECT MAX(`%s`) FROM `%s` WHERE `%s`=?)"
                        % (table, col, latest_col, latest_col, table, col),
                        (d, d)).fetchone()[0]
                elif by_date and col:
                    n = conn.execute("SELECT COUNT(*) FROM `%s` WHERE `%s`=?" % (table, col),
                                     (d,)).fetchone()[0]
                else:
                    n = conn.execute("SELECT COUNT(*) FROM `%s`" % table).fetchone()[0]
            except Exception:
                n = -1
            ok = (n == expect) if mode == "exact" else (n >= expect)
            items.append({"table": table, "label": label, "expected": expect,
                          "mode": mode, "actual": n, "ok": ok, "by_date": by_date})
            if not ok:
                issues.append("%s（期望%s%d，实际%d）" % (
                    TABLE_LABEL.get(table, table),
                    "=" if mode == "exact" else "≥", expect, n))
        has_data = any(i["actual"] > 0 for i in items)
        return {"ok": (not issues) and has_data, "trade_date": d,
                "items": items, "issues": issues}
    return _read(_f, {"ok": False, "trade_date": trade_date, "items": [],
                      "issues": ["数据库不可用"]})


# ---------------- 定时任务状态 ----------------

AUTO_FETCH_HOUR = int(os.environ.get("AUTO_FETCH_HOUR", "15"))
AUTO_FETCH_MINUTE = int(os.environ.get("AUTO_FETCH_MINUTE", "30"))


def auto_fetch_info():
    try:
        import scheduler as _sc
        sched = _sc.schedules()
        text = _sc.schedules_text()
    except Exception:
        sched = [{"name": "close", "hour": AUTO_FETCH_HOUR,
                  "minute": AUTO_FETCH_MINUTE, "mode": "full",
                  "time_text": "%02d:%02d" % (AUTO_FETCH_HOUR, AUTO_FETCH_MINUTE)}]
        text = sched[0]["time_text"]
    return {
        "enabled": str(os.environ.get("AUTO_FETCH_ENABLED", "1")).lower() not in
                   ("0", "false", "no", "off"),
        "hour": AUTO_FETCH_HOUR, "minute": AUTO_FETCH_MINUTE,
        "time_text": "%02d:%02d" % (AUTO_FETCH_HOUR, AUTO_FETCH_MINUTE),
        "schedules": sched,
        "schedules_text": text,
    }


def has_fetch_log(task_type, trade_date=None, status="ok"):
    def _f(conn):
        if trade_date:
            r = conn.execute("SELECT COUNT(*) FROM `fetch_log` WHERE `task_type`=? "
                             "AND `trade_date`=? AND `status`=?",
                             (task_type, trade_date, status)).fetchone()
        else:
            r = conn.execute("SELECT COUNT(*) FROM `fetch_log` WHERE `task_type`=? AND `status`=?",
                             (task_type, status)).fetchone()
        return r[0]
    return _read(_f, 0)


def recent_job_logs(limit=10):
    """定时任务执行记录（兼容旧 task_type=daily_job）"""
    def _f(conn):
        rows = conn.execute(
            "SELECT `task_type`,`trade_date`,`status`,`detail`,`started_at`,`finished_at` "
            "FROM `fetch_log` WHERE `task_type` LIKE 'job:%' OR `task_type`='daily_job' "
            "ORDER BY `id` DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]
    return _read(_f, []) or []


def last_fetch_log(task_type, limit=5):
    def _f(conn):
        rows = conn.execute("SELECT `trade_date`,`status`,`rows`,`detail`,`started_at`,"
                            "`finished_at` FROM `fetch_log` WHERE `task_type`=? "
                            "ORDER BY `id` DESC LIMIT ?", (task_type, int(limit))).fetchall()
        return [dict(r) for r in rows]
    return _read(_f, []) or []


def stats():
    def _f(conn):
        out = {"enabled": enabled(), "db_path": db_path(),
               "backend": "mysql" if _is_mysql() else "sqlite", "tables": {}}
        for t in _TABLES:
            out["tables"][t] = _count(conn, t)
        r1 = conn.execute("SELECT MIN(`trade_date`), MAX(`trade_date`) FROM `daily_kline`").fetchone()
        out["kline_range"] = [r1[0], r1[1]] if r1 else None
        r2 = conn.execute("SELECT MIN(`trade_date`), MAX(`trade_date`) FROM `hotlist_snapshot`").fetchone()
        out["hotlist_range"] = [r2[0], r2[1]] if r2 else None
        if not _is_mysql():
            try:
                out["db_size_mb"] = round(os.path.getsize(db_path()) / 1048576.0, 3)
            except Exception:
                out["db_size_mb"] = None
        return out
    return _read(_f, {"enabled": False, "db_path": db_path()}) or {"enabled": False}


# ===========================================================================
# 数据导出（CSV / Excel）
# ===========================================================================

# 可导出的表：日期列、排序列、导出列（列名 -> 中文表头）
EXPORT_TABLES = {
    "hotlist_snapshot": {
        "label": "人气榜",
        "date_col": "trade_date",
        "order": "`captured_at` DESC, `rank` ASC",
        "cols": [("rank", "排名"), ("stock_code", "代码"), ("stock_name", "名称"),
                 ("rise_and_fall", "涨跌幅%"), ("boards_text", "连板数"),
                 ("tier", "所属梯队"), ("concept_tag", "概念标签"),
                 ("anomaly_analysis", "异动解读"), ("source", "数据源")],
    },
    "daily_kline": {
        "label": "日K线",
        "date_col": "trade_date",
        "order": "`stock_code` ASC",
        "cols": [("stock_code", "代码"), ("open", "开盘"), ("high", "最高"),
                 ("low", "最低"), ("close", "收盘"), ("prev_close", "前收盘"),
                 ("change_pct", "涨跌幅%"), ("volume", "成交量"), ("source", "数据源")],
    },
    "limit_up_pool": {
        "label": "涨停炸板池",
        "date_col": "trade_date",
        "order": "`boards` DESC, `stock_code` ASC",
        "cols": [("stock_code", "代码"), ("boards", "连板数"), ("first_seal_time", "首次封板"),
                 ("last_seal_time", "最终封板"), ("break_count", "开板次数"),
                 ("amount", "成交额"), ("sector", "所属行业"), ("state", "状态")],
    },
    "screening_result": {
        "label": "选股结果",
        "date_col": "target_date",
        "order": "`bucket` ASC, `rank` ASC",
        "cols": [("bucket", "分组"), ("rank", "序号"), ("stock_code", "代码"),
                 ("stock_name", "名称"), ("close_prev", "D-1收盘"), ("high", "D最高"),
                 ("gain_high", "最高涨幅%"), ("close", "D收盘"), ("gain_close", "收盘涨跌%"),
                 ("amount_est", "成交额(估)"), ("first_seal", "首次封板"),
                 ("boards", "连板"), ("sector", "所属行业"), ("state", "状态")],
    },
    "theme_heat_snapshot": {
        "label": "题材热度",
        "date_col": "trade_date",
        "order": "`rank` ASC",
        "cols": [("rank", "排名"), ("theme_name", "题材"), ("verdict", "利好利空"),
                 ("heat_score", "综合热度"), ("pop_heat", "人气分项"),
                 ("topic_heat", "话题分项"), ("bull", "利好条数"), ("bear", "利空条数"),
                 ("stock_total", "成分股数"), ("stock_count", "上榜人气股"),
                 ("reason_summary", "原因解读")],
    },
    "theme_top_stock": {
        "label": "题材人气股",
        "date_col": "trade_date",
        "order": "`theme_name` ASC, `rank` ASC",
        "cols": [("theme_name", "所属题材"), ("stock_code", "代码"), ("stock_name", "名称"),
                 ("hot_rank", "人气排名"), ("trend_rank", "飙升排名")],
    },
    "stock_news": {
        "label": "个股资讯",
        "date_col": "news_date",
        "order": "`stock_code` ASC, `news_date` DESC",
        "cols": [("stock_code", "代码"), ("news_date", "日期"), ("title", "标题"),
                 ("source", "来源"), ("url", "链接")],
    },
    "minute_kline": {
        "label": "分时线",
        "date_col": "trade_date",
        "order": "`stock_code` ASC, `minute` ASC",
        "cols": [("stock_code", "代码"), ("minute", "时间"), ("price", "价格"),
                 ("volume", "成交量")],
    },
}


def export_rows(table, date, limit=20000):
    """导出某表某交易日的全部数据。返回 {'label','headers','rows'} 或 None"""
    meta = EXPORT_TABLES.get(table)
    if not meta:
        return None
    cols = [c for c, _ in meta["cols"]]
    headers = [lab for _, lab in meta["cols"]]
    dcol = meta["date_col"]
    order = meta.get("order") or ""

    def _f(conn):
        sql = "SELECT %s FROM `%s` WHERE `%s`=?" % (_cols(cols), table, dcol)
        if order:
            sql += " ORDER BY " + order
        sql += " LIMIT %d" % int(limit)
        rows = conn.execute(sql, (date,)).fetchall()
        out = []
        for r in rows:
            vals = []
            for c in cols:
                v = r[c]
                if v is None:
                    vals.append("")
                elif isinstance(v, float):
                    vals.append(round(v, 4))
                else:
                    vals.append(v)
            out.append(vals)
        return out
    data = _read(_f)
    return {"table": table, "label": meta["label"], "headers": headers, "rows": data or []}


def export_all(date, limit_per_table=20000):
    """导出某交易日所有可导出表。返回 [(label, headers, rows), ...]"""
    sheets = []
    for t in EXPORT_TABLES:
        d = export_rows(t, date, limit_per_table)
        if d and d["rows"]:
            sheets.append((d["label"], d["headers"], d["rows"]))
    return sheets


def export_summary(date):
    """某交易日各表可导出行数（给前端展示）"""
    out = []
    for t, meta in EXPORT_TABLES.items():
        d = export_rows(t, date, limit=1)
        n = 0
        if d is not None:
            def _f(conn, _t=t, _d=date):
                return conn.execute("SELECT COUNT(*) FROM `%s` WHERE `%s`=?"
                                    % (_t, meta["date_col"]), (_d,)).fetchone()[0]
            n = _read(_f, 0) or 0
        out.append({"table": t, "label": meta["label"], "rows": n})
    return out


# ===========================================================================
# 全市场扫描：暂存 + 断点续传
# ===========================================================================

_SCAN_COLS = ["target_date", "stock_code", "stock_name", "close_d2", "close_prev",
              "limit_prev", "open", "high", "low", "close", "limit_price",
              "gain_high", "gain_close", "amplitude", "amount_est", "volume",
              "touched_prev", "sealed", "broke", "cond1", "cond2", "prev_gain",
              "skipped", "collected_at"]
_SCAN_UPD = [c for c in _SCAN_COLS if c not in ("target_date", "stock_code")]


def save_scan_stocks(target_date, items):
    """批量写入扫描暂存（含 skipped 标记）。items: evaluate() 的返回 + code/name"""
    items = [x for x in (items or []) if clean_code(x.get("code"))]
    if not target_date or not items:
        return 0

    def _f(conn):
        cur = conn.cursor()
        sql = _upsert("scan_stock", _SCAN_COLS, ["target_date", "stock_code"], _SCAN_UPD)
        ts = now_str()
        for ev in items:
            ev = ev or {}
            cur.execute(sql, (
                target_date, clean_code(ev.get("code")), ev.get("name"),
                _num(ev.get("closeD2")), _num(ev.get("closePrev")), _num(ev.get("limitPrev")),
                _num(ev.get("open")), _num(ev.get("high")), _num(ev.get("low")),
                _num(ev.get("close")), _num(ev.get("limit")), _num(ev.get("gainHigh")),
                _num(ev.get("gainClose")), _num(ev.get("amplitude")), _num(ev.get("amountEst")),
                _num(ev.get("volume")),
                1 if ev.get("touchedPrev") else 0, 1 if ev.get("sealed") else 0,
                1 if ev.get("broke") else 0, 1 if ev.get("cond1") else 0,
                1 if ev.get("cond2") else 0, _num(ev.get("prevGain")),
                1 if ev.get("skipped") else 0, ts))
        return len(items)
    return _write(_f)


def load_scan_codes(target_date):
    """已处理过的股票代码集合（含 skipped），用于断点续传时跳过"""
    if not target_date:
        return set()

    def _f(conn):
        rows = conn.execute("SELECT `stock_code` FROM `scan_stock` WHERE `target_date`=?",
                            (target_date,)).fetchall()
        return {r["stock_code"] for r in rows}
    return _read(_f, set()) or set()


def load_scan_results(target_date):
    """把暂存还原成 evaluate() 风格的记录（排除 skipped）"""
    if not target_date:
        return []

    def _f(conn):
        rows = conn.execute(
            "SELECT `stock_code`,`stock_name`,`close_d2`,`close_prev`,`limit_prev`,`open`,"
            "`high`,`low`,`close`,`limit_price`,`gain_high`,`gain_close`,`amplitude`,"
            "`amount_est`,`volume`,`touched_prev`,`sealed`,`broke`,`cond1`,`cond2`,`prev_gain` "
            "FROM `scan_stock` WHERE `target_date`=? AND `skipped`=0", (target_date,)).fetchall()
        out = []
        for r in rows:
            out.append({
                "code": r["stock_code"], "name": r["stock_name"],
                "closeD2": _num(r["close_d2"]), "closePrev": _num(r["close_prev"]),
                "limitPrev": _num(r["limit_prev"]), "open": _num(r["open"]),
                "high": _num(r["high"]), "low": _num(r["low"]), "close": _num(r["close"]),
                "limit": _num(r["limit_price"]), "gainHigh": _num(r["gain_high"]),
                "gainClose": _num(r["gain_close"]), "amplitude": _num(r["amplitude"]),
                "amountEst": _num(r["amount_est"]), "volume": _num(r["volume"]),
                "touchedPrev": bool(r["touched_prev"]), "sealed": bool(r["sealed"]),
                "broke": bool(r["broke"]), "cond1": bool(r["cond1"]),
                "cond2": bool(r["cond2"]), "prevGain": _num(r["prev_gain"]),
            })
        return out
    return _read(_f, []) or []


def scan_progress(target_date):
    """扫描进度：{total, scanned, skipped}"""
    if not target_date:
        return {"total": 0, "scanned": 0, "skipped": 0}

    def _f(conn):
        r = conn.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN `skipped`=1 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN `skipped`=0 THEN 1 ELSE 0 END) "
            "FROM `scan_stock` WHERE `target_date`=?", (target_date,)).fetchone()
        return {"total": r[0] or 0, "skipped": r[1] or 0, "scanned": r[2] or 0}
    return _read(_f, {"total": 0, "scanned": 0, "skipped": 0}) or {"total": 0, "scanned": 0, "skipped": 0}


def clear_scan(target_date=None):
    """清空扫描暂存（不传则清全部）"""
    def _f(conn):
        if target_date:
            cur = conn.execute("DELETE FROM `scan_stock` WHERE `target_date`=?", (target_date,))
        else:
            cur = conn.execute("DELETE FROM `scan_stock`")
        return cur.rowcount
    return _write(_f) or 0


# ===========================================================================
# 数据覆盖度（让用户看清"哪些交易日有数据、哪些没有"）
# ===========================================================================

COVERAGE_TABLES = [
    ("hotlist_snapshot", "trade_date", "人气榜"),
    ("theme_heat_snapshot", "trade_date", "题材热度"),
    ("daily_kline", "trade_date", "日K线"),
    ("limit_up_pool", "trade_date", "涨停池"),
    ("screening_run", "target_date", "选股"),
]


def calendar_coverage(n=30):
    """最近 n 个交易日的覆盖情况。

    返回 {'days': [{'trade_date','tables':{名:行数},'count','has_data'}, ...] 倒序}
    """
    days = load_calendar(n)
    if not days:
        return {"days": [], "from": None, "to": None}

    def _f(conn):
        out = []
        for d in days:
            item = {"trade_date": d, "tables": {}, "count": 0}
            for t, col, label in COVERAGE_TABLES:
                try:
                    c = conn.execute("SELECT COUNT(*) FROM `%s` WHERE `%s`=?" % (t, col),
                                     (d,)).fetchone()[0]
                except Exception:
                    c = 0
                item["tables"][label] = c
                item["count"] += c
            # 分级：full=当天完整抓取过（有人气榜/题材快照）；partial=只有零散数据
            hot = item["tables"].get("人气榜", 0)
            thm = item["tables"].get("题材热度", 0)
            kln = item["tables"].get("日K线", 0)
            if hot > 0 or thm > 0:
                item["level"] = "full"
            elif kln >= 500 or item["tables"].get("涨停池", 0) >= 5:
                item["level"] = "partial"
            elif item["count"] > 0:
                item["level"] = "trace"
            else:
                item["level"] = "none"
            item["has_data"] = item["level"] == "full"
            out.append(item)
        return out
    data = _read(_f, []) or []
    return {"days": data, "from": days[-1], "to": days[0],
            "note": "非交易日的数据会自动归到最近一个交易日名下",
            "levels": {
                "full": "当天抓取过（有人气榜/题材快照）",
                "partial": "仅有部分数据（如日K/涨停池）",
                "trace": "仅有零散记录",
                "none": "无数据（程序当时未运行或功能未上线）",
            }}


def hotlist_range_status(start, end, max_days=130):
    """区间内每个交易日的（人气榜数据）情况，供"日期范围"浏览用。

    返回 [{'date','has','source','backfill'}, ...]（升序，仅交易日）
    """
    if not start or not end:
        return []
    if start > end:
        start, end = end, start

    def _cal(conn):
        rows = conn.execute(
            "SELECT `trade_date` FROM `trade_calendar` WHERE `is_open`=1 "
            "AND `trade_date`>=? AND `trade_date`<=? ORDER BY `trade_date` LIMIT ?",
            (start, end, int(max_days))).fetchall()
        return [r["trade_date"] for r in rows]
    days = _read(_cal, []) or []

    out = []
    for d in days:
        h = load_hotlist(d)          # 已含"实时优先"逻辑
        src = (h or {}).get("source") or ""
        out.append({"date": d, "has": bool(h), "source": src,
                    "backfill": is_backfill_source(src)})
    return out


def hotlist_days_summary(start, end):
    """区间概览：有数据 / 仅回补 / 无数据 的天数"""
    rows = hotlist_range_status(start, end)
    return {
        "start": start, "end": end, "total": len(rows),
        "with_data": sum(1 for r in rows if r["has"]),
        "backfill_only": sum(1 for r in rows if r["has"] and r["backfill"]),
        "missing": sum(1 for r in rows if not r["has"]),
    }


def hotlist_streaks(trade_date, top_n=30, max_lookback=60):
    """计算「连续上榜天数」。

    规则（按用户定义）：
      · 上榜 = 当天排名 <= top_n（默认前 30）
      · 从 trade_date 起**按交易日历往前逐日回推**
      · 连续每一天都上榜，才算连续；中途某天不在榜 -> 中断
      · 某天**没有任何人气榜数据** -> 无法判定，保守中断

    返回 {stock_code: 连续天数}（只包含 trade_date 当天在榜的股票）
    """
    if not trade_date:
        return {}

    def _f(conn):
        days = [r["trade_date"] for r in conn.execute(
            "SELECT `trade_date` FROM `trade_calendar` WHERE `is_open`=1 AND `trade_date`<=? "
            "ORDER BY `trade_date` DESC LIMIT ?",
            (trade_date, int(max_lookback))).fetchall()]
        if not days:
            return {}
        if days[0] != trade_date:
            days.insert(0, trade_date)          # 兜底：日历里还没有这一天

        ph = ",".join(["?"] * len(days))
        # 各日的"上榜"股票集合
        by_day = {}
        for r in conn.execute(
                "SELECT `trade_date`,`stock_code` FROM `hotlist_snapshot` "
                "WHERE `trade_date` IN (%s) AND `rank` IS NOT NULL AND `rank`<=?" % ph,
                tuple(days) + (int(top_n),)).fetchall():
            by_day.setdefault(r["trade_date"], set()).add(r["stock_code"])

        # 哪些日子有人气榜数据（用于"无法判定则中断"）
        has = {r["trade_date"] for r in conn.execute(
            "SELECT DISTINCT `trade_date` FROM `hotlist_snapshot` WHERE `trade_date` IN (%s)" % ph,
            tuple(days)).fetchall()}

        today_codes = by_day.get(trade_date, set())
        out = {}
        for code in today_codes:
            n = 0
            for d in days:
                if d not in has:
                    break                        # 该日无数据，保守截断
                if code in by_day.get(d, ()):
                    n += 1
                else:
                    break
            out[code] = n
        return out
    return _read(_f, {}) or {}
