# -*- coding: utf-8 -*-
"""
SQLite -> MySQL 数据迁移工具

用法示例
--------
# 1) 只建表
python tools/sqlite_to_mysql.py --mysql "mysql://root:pwd@127.0.0.1:3306/stock" --schema-only

# 2) 建表 + 迁移全部数据（幂等，可重复执行）
python tools/sqlite_to_mysql.py --mysql "mysql://root:pwd@127.0.0.1:3306/stock" \
    --sqlite "dist/data/market.db"

# 3) 先清空目标表再迁移
python tools/sqlite_to_mysql.py --mysql "..." --sqlite "..." --truncate

# 4) 只看要迁移多少行，不写库
python tools/sqlite_to_mysql.py --mysql "..." --sqlite "..." --dry-run

依赖：pip install pymysql        （或 pip install mysql-connector-python）
"""
import argparse
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_SCHEMA = os.path.join(ROOT, "deploy", "mysql_schema.sql")
DEFAULT_SQLITE = os.path.join(ROOT, "data", "market.db")

# 迁移顺序：先维度、后事实（外键顺序）
TABLES = [
    "stock", "trade_calendar", "theme_catalog", "theme_member",
    "hotlist_snapshot", "limit_up_pool", "daily_kline", "minute_kline",
    "stock_news", "stock_anomaly", "dragon_tiger",
    "theme_heat_snapshot", "theme_topic", "theme_topic_link", "theme_top_stock",
    "screening_run", "screening_result", "fetch_log", "raw_payload",
]

BATCH = 1000


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------

def connect_mysql(dsn=None, host=None, port=None, user=None, password=None,
                  database=None, charset="utf8mb4"):
    """返回 (conn, driver_name)。优先 pymysql，其次 mysql-connector。"""
    cfg = {}
    if dsn:
        # mysql://user:pass@host:port/db
        s = dsn
        for p in ("mysql://", "mysql+pymysql://"):
            if s.startswith(p):
                s = s[len(p):]
        cred, _, hostpart = s.rpartition("@")
        if not hostpart:
            hostpart, cred = cred, ""
        user_, _, pass_ = cred.partition(":")
        host_, _, portdb = hostpart.partition(":")
        port_, _, db_ = portdb.partition("/")
        cfg = dict(host=host_ or "127.0.0.1", port=int(port_ or 3306),
                   user=user_ or "root", password=pass_, database=db_)
    if host:
        cfg["host"] = host
    if port:
        cfg["port"] = int(port)
    if user:
        cfg["user"] = user
    if password is not None:
        cfg["password"] = password
    if database:
        cfg["database"] = database

    try:
        import pymysql
        conn = pymysql.connect(charset=charset, autocommit=False, **cfg)
        return conn, "pymysql"
    except ImportError:
        pass
    except Exception as e:
        raise SystemExit("pymysql 连接失败: %s" % e)

    try:
        import mysql.connector as mc
        conn = mc.connect(charset=charset, **cfg)
        return conn, "mysql.connector"
    except ImportError:
        raise SystemExit("缺少 MySQL 驱动，请先执行：pip install pymysql")
    except Exception as e:
        raise SystemExit("mysql-connector 连接失败: %s" % e)


def mysql_column_types(conn, database):
    """{table: {column: data_type}}，用于做值类型清洗"""
    cur = conn.cursor()
    cur.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=%s", (database,))
    out = {}
    for t, c, dt in cur.fetchall():
        out.setdefault(t, {})[c.lower()] = (dt or "").lower()
    cur.close()
    return out


# ---------------------------------------------------------------------------
# 值清洗
# ---------------------------------------------------------------------------

_DATEISH = ("date",)
_DATETIMEISH = ("datetime", "timestamp")
_NUMERIC = ("int", "bigint", "smallint", "tinyint", "mediumint",
            "decimal", "double", "float", "bit")


def clean_value(v, dtype):
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        if dtype in _DATEISH:
            return s[:10]
        if dtype in _DATETIMEISH:
            if len(s) == 10:
                return s + " 00:00:00"
            return s[:19]
        return v
    if dtype in _DATEISH or dtype in _DATETIMEISH:
        return str(v)[:19]
    if dtype in _NUMERIC:
        return v
    return v


def table_columns(sqlite_conn, table):
    cur = sqlite_conn.execute("PRAGMA table_info(%s)" % table)
    return [r[1] for r in cur.fetchall()]


def table_exists(sqlite_conn, table):
    r = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(r)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_schema(conn, schema_file, driver):
    if not os.path.isfile(schema_file):
        raise SystemExit("找不到结构文件: %s" % schema_file)
    sql = open(schema_file, encoding="utf-8").read()
    cur = conn.cursor()
    done = 0
    skipped = 0
    for raw in sql.split(";"):
        # 去掉 -- 注释行后再判断语句类型（SQL 里 CREATE 前的注释块很常见）
        st = "\n".join(l for l in raw.splitlines()
                        if l.strip() and not l.strip().startswith("--")).strip()
        if not st:
            continue
        head = st.upper()
        if not head.startswith(("CREATE", "SET", "USE", "ALTER", "DROP", "INSERT")):
            skipped += 1
            continue
        cur.execute(st)
        done += 1
    conn.commit()
    cur.close()
    print("[结构] 已执行 %d 条语句，跳过 %d 条（来自 %s）" % (done, skipped, os.path.basename(schema_file)))


def migrate_table(sqlite_conn, mysql_conn, database, table, coltypes,
                  truncate=False, dry_run=False):
    if not table_exists(sqlite_conn, table):
        return 0, "跳过（SQLite 中无此表）"
    cols = table_columns(sqlite_conn, table)
    if not cols:
        return 0, "跳过（无字段）"

    cur = mysql_conn.cursor()
    if truncate and not dry_run:
        cur.execute("DELETE FROM `%s`" % table)

    cur.execute("SELECT COUNT(*) FROM `%s`" % table)
    total = cur.fetchone()[0]

    types = coltypes.get(table, {})
    col_sql = ",".join("`%s`" % c for c in cols)
    upd_cols = [c for c in cols if c.lower() not in ("id", "code", "trade_date", "cache_key",
                                                     "run_id", "theme_id")]
    if upd_cols:
        upd_sql = ",".join("`%s`=VALUES(`%s`)" % (c, c) for c in upd_cols)
        insert_sql = "INSERT INTO `%s` (%s) VALUES (%s) ON DUPLICATE KEY UPDATE %s" % (
            table, col_sql, ",".join(["%s"] * len(cols)), upd_sql)
    else:
        insert_sql = "INSERT IGNORE INTO `%s` (%s) VALUES (%s)" % (
            table, col_sql, ",".join(["%s"] * len(cols)))

    read = sqlite_conn.execute("SELECT %s FROM `%s`" % (",".join('"%s"' % c for c in cols), table))
    n = 0
    batch = []
    while True:
        rows = read.fetchmany(BATCH)
        if not rows:
            break
        for row in rows:
            vals = [clean_value(row[i], types.get(cols[i].lower(), "")) for i in range(len(cols))]
            batch.append(vals)
        if batch and not dry_run:
            cur.executemany(insert_sql, batch)
            mysql_conn.commit()
        n += len(batch)
        batch = []
    cur.close()
    return n, "OK"


def main():
    ap = argparse.ArgumentParser(description="SQLite -> MySQL 迁移")
    ap.add_argument("--mysql", help='MySQL DSN，如 mysql://root:pwd@127.0.0.1:3306/stock')
    ap.add_argument("--host"); ap.add_argument("--port")
    ap.add_argument("--user"); ap.add_argument("--password"); ap.add_argument("--database")
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE, help="源 SQLite 文件")
    ap.add_argument("--schema", default=DEFAULT_SCHEMA, help="MySQL 建表脚本")
    ap.add_argument("--schema-only", action="store_true", help="只建表，不迁数据")
    ap.add_argument("--skip-schema", action="store_true", help="跳过建表")
    ap.add_argument("--truncate", action="store_true", help="迁移前清空目标表")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    ap.add_argument("--tables", help="只迁移指定表，逗号分隔")
    args = ap.parse_args()

    if not args.schema_only and not os.path.isfile(args.sqlite):
        raise SystemExit("找不到 SQLite 文件: %s" % args.sqlite)

    t0 = time.time()
    conn, driver = connect_mysql(args.mysql, args.host, args.port, args.user,
                                 args.password, args.database)
    print("[连接] MySQL 驱动=%s" % driver)

    dbname = args.database
    if not dbname:
        if args.mysql:
            dbname = args.mysql.rstrip("/").rsplit("/", 1)[-1]
        else:
            raise SystemExit("请通过 --database 或 DSN 指定数据库名")

    if not args.skip_schema:
        run_schema(conn, args.schema, driver)
    if args.schema_only:
        print("[完成] 仅建表")
        return

    coltypes = mysql_column_types(conn, dbname)
    sconn = sqlite3.connect(args.sqlite)

    want = [t.strip() for t in args.tables.split(",")] if args.tables else TABLES
    print("\n%-22s %10s   %s" % ("表", "行数", "结果"))
    print("-" * 52)
    grand = 0
    for t in want:
        n, msg = migrate_table(sconn, conn, dbname, t, coltypes,
                               truncate=args.truncate, dry_run=args.dry_run)
        grand += n
        print("%-22s %10d   %s" % (t, n, msg))
    print("-" * 52)
    print("合计 %d 行，用时 %.1fs%s" % (grand, time.time() - t0,
                                    "（dry-run，未写库）" if args.dry_run else ""))
    sconn.close()
    conn.close()


if __name__ == "__main__":
    main()
