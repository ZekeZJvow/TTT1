-- ============================================================================
--  A股人气榜查询系统 · 本地行情数据仓库 schema
--  引擎: SQLite 3   （MySQL 迁移见文末注释）
--  说明: 幂等设计 —— 每张事实表都有 UNIQUE 约束，重复抓取不会产生重复行
-- ============================================================================

PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 10000;
PRAGMA foreign_keys = ON;

-- ============================================================================
-- 一、维度层
-- ============================================================================

-- 1. 股票基础信息
CREATE TABLE IF NOT EXISTS stock (
  code        TEXT PRIMARY KEY,          -- 6位代码，保留前导0
  name        TEXT,                      -- 股票简称
  market      TEXT,                      -- SH / SZ / BJ
  board       TEXT,                      -- 主板/创业板/科创板/北交所
  is_st       INTEGER DEFAULT 0,         -- 0/1
  thscode     TEXT,                      -- 同花顺代码 如 000002.SZ
  list_date   TEXT,
  status      TEXT DEFAULT 'L',          -- L上市/D退市/P停牌
  updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_stock_name  ON stock(name);
CREATE INDEX IF NOT EXISTS ix_stock_board ON stock(market, board);

-- 2. 交易日历（全站日期口径的唯一依据）
CREATE TABLE IF NOT EXISTS trade_calendar (
  trade_date       TEXT PRIMARY KEY,     -- YYYY-MM-DD
  is_open          INTEGER NOT NULL,     -- 1交易日 / 0休市
  prev_trade_date  TEXT,
  next_trade_date  TEXT,
  source           TEXT DEFAULT 'sse_index_kline',
  updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_cal_open ON trade_calendar(is_open);

-- 3. 题材目录（概念 + 行业）
CREATE TABLE IF NOT EXISTS theme_catalog (
  theme_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  thscode     TEXT NOT NULL UNIQUE,      -- 指数代码 如 881153.TI
  name        TEXT NOT NULL,             -- 题材名
  tag         TEXT,                      -- industry / concept
  source      TEXT DEFAULT 'ths',
  updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_theme_name ON theme_catalog(name);

-- 4. 题材成分股（多对多桥表）
CREATE TABLE IF NOT EXISTS theme_member (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  theme_id    INTEGER NOT NULL REFERENCES theme_catalog(theme_id),
  stock_code  TEXT    NOT NULL,
  in_date     TEXT,
  updated_at  TEXT,
  UNIQUE (theme_id, stock_code)
);
CREATE INDEX IF NOT EXISTS ix_tm_stock ON theme_member(stock_code);

-- ============================================================================
-- 二、快照层（每日写入）
-- ============================================================================

-- 5. 人气榜快照（支持同一天多次抓取，用 captured_at 区分）
CREATE TABLE IF NOT EXISTS hotlist_snapshot (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date        TEXT NOT NULL,
  captured_at       TEXT NOT NULL,
  rank              INTEGER NOT NULL,
  stock_code        TEXT NOT NULL,
  stock_name        TEXT,
  rise_and_fall     REAL,                -- 涨跌幅 %
  boards_count      INTEGER,             -- 连板数（解析值）
  boards_text       TEXT,                -- 原始展示文本
  tier              TEXT,
  concept_tag       TEXT,
  anomaly_analysis  TEXT,
  is_hot            INTEGER DEFAULT 0,
  source            TEXT,
  degraded          INTEGER DEFAULT 0,
  UNIQUE (trade_date, captured_at, stock_code)
);
CREATE INDEX IF NOT EXISTS ix_hot_date_rank ON hotlist_snapshot(trade_date, rank);
CREATE INDEX IF NOT EXISTS ix_hot_stock     ON hotlist_snapshot(stock_code, trade_date);

-- 6. 涨停/炸板池
CREATE TABLE IF NOT EXISTS limit_up_pool (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date      TEXT NOT NULL,
  stock_code      TEXT NOT NULL,
  stock_name      TEXT,
  boards          INTEGER,
  first_seal_time TEXT,
  last_seal_time  TEXT,
  break_count     INTEGER,
  seal_amount     REAL,
  amount          REAL,
  sector          TEXT,
  state           TEXT,                  -- 涨停 / 炸板
  source          TEXT DEFAULT 'eastmoney',
  collected_at    TEXT,
  UNIQUE (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS ix_lu_stock ON limit_up_pool(stock_code, trade_date);

-- 7. 日K线
CREATE TABLE IF NOT EXISTS daily_kline (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code   TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  open         REAL,
  high         REAL,
  low          REAL,
  close        REAL,
  prev_close   REAL,
  change_pct   REAL,
  volume       REAL,
  amount       REAL,
  source       TEXT,
  collected_at TEXT,
  UNIQUE (stock_code, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_k_date  ON daily_kline(trade_date);
CREATE INDEX IF NOT EXISTS ix_k_date_pct ON daily_kline(trade_date, change_pct);
CREATE INDEX IF NOT EXISTS ix_k_stock ON daily_kline(stock_code, trade_date);

-- 8. 分时线（按需存储 + 定期清理）
CREATE TABLE IF NOT EXISTS minute_kline (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code  TEXT NOT NULL,
  trade_date  TEXT NOT NULL,
  minute      TEXT NOT NULL,             -- HH:MM
  price       REAL,
  avg_price   REAL,
  volume      REAL,
  amount      REAL,
  UNIQUE (stock_code, trade_date, minute)
);
CREATE INDEX IF NOT EXISTS ix_min_date ON minute_kline(trade_date);

-- 9. 个股资讯 / 公告
CREATE TABLE IF NOT EXISTS stock_news (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code   TEXT NOT NULL,
  news_date    TEXT,
  published_at TEXT,
  title        TEXT NOT NULL,
  source       TEXT,
  news_type    TEXT,
  url          TEXT,
  collected_at TEXT,
  UNIQUE (stock_code, url)
);
CREATE INDEX IF NOT EXISTS ix_news_stock ON stock_news(stock_code, news_date);

-- 10. 个股异动原因
CREATE TABLE IF NOT EXISTS stock_anomaly (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date   TEXT NOT NULL,
  stock_code   TEXT NOT NULL,
  stock_name   TEXT,
  reason       TEXT,
  change_pct   REAL,
  rank         INTEGER,
  collected_at TEXT,
  UNIQUE (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS ix_an_stock ON stock_anomaly(stock_code, trade_date);

-- 11. 龙虎榜
CREATE TABLE IF NOT EXISTS dragon_tiger (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date       TEXT NOT NULL,
  stock_code       TEXT NOT NULL,
  stock_name       TEXT,
  net_amount       REAL,
  institution_net  REAL,
  reason           TEXT,
  collected_at     TEXT,
  UNIQUE (trade_date, stock_code)
);

-- 12. 题材热度快照（逐日唯一 -> 天然构成热度历史）
CREATE TABLE IF NOT EXISTS theme_heat_snapshot (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date      TEXT NOT NULL,
  captured_at     TEXT,
  theme_id        INTEGER,
  theme_name      TEXT,
  tag             TEXT,
  verdict         TEXT,                  -- 利好 / 利空 / 中性
  rank            INTEGER,
  heat_score      REAL,
  pop_heat        REAL,
  topic_heat      REAL,
  net_score       INTEGER,
  bull            INTEGER,
  bear            INTEGER,
  stock_total     INTEGER,
  stock_count     INTEGER,
  reason_summary  TEXT,
  UNIQUE (trade_date, theme_name)
);
CREATE INDEX IF NOT EXISTS ix_ths_date_rank ON theme_heat_snapshot(trade_date, rank);

-- 13. 题材话题（同花顺话题热榜）
CREATE TABLE IF NOT EXISTS theme_topic (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date   TEXT NOT NULL,
  title        TEXT NOT NULL,
  description  TEXT,
  hot          REAL,
  url          TEXT,
  source       TEXT DEFAULT 'ths_topic',
  collected_at TEXT,
  UNIQUE (trade_date, title)
);

-- 14. 话题—题材关联（多对多）
CREATE TABLE IF NOT EXISTS theme_topic_link (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id   INTEGER REFERENCES theme_topic(id),
  theme_id   INTEGER REFERENCES theme_catalog(theme_id),
  trade_date TEXT,
  weight     REAL,
  UNIQUE (topic_id, theme_id)
);

-- 15. 题材利好个股 Top50
CREATE TABLE IF NOT EXISTS theme_top_stock (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date  TEXT NOT NULL,
  theme_name  TEXT NOT NULL,
  stock_code  TEXT NOT NULL,
  stock_name  TEXT,
  hot_rank    INTEGER,
  trend_rank  INTEGER,
  heat        REAL,
  rank        INTEGER,
  UNIQUE (trade_date, theme_name, stock_code)
);
CREATE INDEX IF NOT EXISTS ix_tts_date_rank ON theme_top_stock(trade_date, rank);

-- 16. 每日封板率统计（离线算好落库，供「行情评分走势」秒读）
CREATE TABLE IF NOT EXISTS market_seal_stats (
  trade_date   TEXT PRIMARY KEY,
  up_count     INTEGER,
  down_count   INTEGER,
  flat_count   INTEGER,
  final_count  INTEGER,               -- 入选池（昨日未涨停 + 今日冲高>9%）
  sealed_count INTEGER,               -- 其中封住涨停的
  score        REAL,                  -- 封板率 = sealed/final*100
  src          TEXT,
  kline_rows   INTEGER,               -- 计算当天的日K行数（日K补齐后不一致 -> 自动重算）
  computed_at  TEXT
);

-- 17. 每日涨跌家数（沪深京全部 A 股口径 —— 与同花顺「涨跌分布」一致）
CREATE TABLE IF NOT EXISTS market_breadth (
  trade_date   TEXT PRIMARY KEY,
  up_count     INTEGER,                  -- 上涨家数
  down_count   INTEGER,                  -- 下跌家数
  flat_count   INTEGER,                  -- 平盘家数
  total_count  INTEGER,                  -- 统计总数
  suspended    INTEGER,                  -- 停牌/无行情 家数
  source       TEXT,
  collected_at TEXT
);

-- 17. 每日融资融券余额（沪深两市合计，单位：亿元）
CREATE TABLE IF NOT EXISTS market_margin (
  trade_date   TEXT PRIMARY KEY,
  rz_ye        REAL,                     -- 融资余额（亿元）
  rq_ye        REAL,                     -- 融券余额（亿元）
  total        REAL,                     -- 融资融券余额合计（亿元）
  source       TEXT,
  collected_at TEXT
);

-- 18. 每日两市成交额（沪市 + 深市，单位：亿元）—— 供「行情评分走势」的成交额总计 / 较上一日
CREATE TABLE IF NOT EXISTS market_turnover (
  trade_date   TEXT PRIMARY KEY,
  sh_amount    REAL,                     -- 沪市成交额（亿元）
  sz_amount    REAL,                     -- 深市成交额（亿元）
  amount       REAL,                     -- 两市合计（亿元）
  source       TEXT,
  collected_at TEXT
);

-- ============================================================================
-- 三、结果层
-- ============================================================================

-- 16. 选股任务（一次扫描 = 一行；payload_json 用于忠实回放）
CREATE TABLE IF NOT EXISTS screening_run (
  run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  target_date     TEXT NOT NULL,
  prev_trade_date TEXT,
  universe_count  INTEGER,
  cond2_count     INTEGER,
  cond1_count     INTEGER,
  sealed_count    INTEGER,
  broken_count    INTEGER,
  removed_count   INTEGER,
  elapsed_sec     REAL,
  source          TEXT,
  payload_json    TEXT,                  -- 完整响应快照（原始层）
  started_at      TEXT,
  finished_at     TEXT,
  UNIQUE (target_date)
);

-- 17. 选股结果明细
CREATE TABLE IF NOT EXISTS screening_result (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       INTEGER NOT NULL REFERENCES screening_run(run_id),
  target_date  TEXT NOT NULL,
  stock_code   TEXT NOT NULL,
  stock_name   TEXT,
  close_prev   REAL,
  high         REAL,
  gain_high    REAL,
  close        REAL,
  gain_close   REAL,
  amount_est   REAL,
  first_seal   TEXT,
  boards       INTEGER,
  sector       TEXT,
  state        TEXT,
  bucket       TEXT NOT NULL,            -- selected / broken / removed
  rank         INTEGER,
  UNIQUE (run_id, stock_code, bucket)
);
CREATE INDEX IF NOT EXISTS ix_sr_date_bucket ON screening_result(target_date, bucket);
CREATE INDEX IF NOT EXISTS ix_sr_stock       ON screening_result(stock_code, target_date);


-- 20. 全市场扫描暂存表（断点续传用：边扫边存，中断后可从断点继续）
CREATE TABLE IF NOT EXISTS scan_stock (
  target_date   TEXT NOT NULL,
  stock_code    TEXT NOT NULL,
  stock_name    TEXT,
  close_d2      REAL,
  close_prev    REAL,
  limit_prev    REAL,
  open          REAL,
  high          REAL,
  low           REAL,
  close         REAL,
  limit_price   REAL,
  gain_high     REAL,
  gain_close    REAL,
  amplitude     REAL,
  amount_est    REAL,
  volume        REAL,
  touched_prev  INTEGER,
  sealed        INTEGER,
  broke         INTEGER,
  cond1         INTEGER,
  cond2         INTEGER,
  prev_gain     REAL,
  skipped       INTEGER DEFAULT 0,
  collected_at  TEXT,
  UNIQUE (target_date, stock_code)
);
CREATE INDEX IF NOT EXISTS ix_scan_date ON scan_stock(target_date);

-- ============================================================================
-- 四、运维层
-- ============================================================================

-- 18. 抓取日志
CREATE TABLE IF NOT EXISTS fetch_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  task_type   TEXT,
  source      TEXT,
  endpoint    TEXT,
  trade_date  TEXT,
  status      TEXT,                      -- ok / fail / degraded / skip
  http_code   INTEGER,
  rows        INTEGER,
  duration_ms INTEGER,
  error       TEXT,
  detail      TEXT,
  started_at  TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_log_task_time ON fetch_log(task_type, started_at);

-- 19. 原始响应快照（复杂响应的忠实回放层，与上方"建模层"并存）
CREATE TABLE IF NOT EXISTS raw_payload (
  cache_key    TEXT PRIMARY KEY,         -- 如 'screen:2026-09-30'
  kind         TEXT NOT NULL,            -- hotlist / screen / themes / ...
  trade_date   TEXT,
  payload_json TEXT NOT NULL,
  created_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_raw_kind_date ON raw_payload(kind, trade_date);

-- ============================================================================
-- MySQL 迁移提示：
--   INTEGER PRIMARY KEY AUTOINCREMENT -> BIGINT PRIMARY KEY AUTO_INCREMENT
--   TEXT                              -> VARCHAR(n) / DATETIME / DATE
--   REAL                              -> DECIMAL(18,4)
--   INSERT ... ON CONFLICT(...) DO UPDATE SET ... -> INSERT ... ON DUPLICATE KEY UPDATE ...
-- ============================================================================

-- 19. 指数日线（沪深300 / 上证）
CREATE TABLE IF NOT EXISTS index_daily (
  trade_date TEXT NOT NULL,
  code       TEXT NOT NULL,
  close      REAL,
  pct        REAL,
  PRIMARY KEY (trade_date, code)
);

-- 20. 每日全市场统计（情绪评分的输入层）
CREATE TABLE IF NOT EXISTS market_day_stats (
  trade_date   TEXT PRIMARY KEY,
  universe     INTEGER,
  up_count     INTEGER,
  down_count   INTEGER,
  flat_count   INTEGER,
  up5_count    INTEGER,
  down5_count  INTEGER,
  limit_up     INTEGER,
  limit_down   INTEGER,
  broken       INTEGER,
  limit_height INTEGER,
  promote_rate REAL,
  ew_return    REAL,
  amount       REAL,
  source       TEXT,
  computed_at  TEXT
);

-- 21. 每日情绪评分（5 个模块分 + 总分 + 完整度）
CREATE TABLE IF NOT EXISTS score_daily (
  trade_date    TEXT PRIMARY KEY,
  s_breadth     REAL,
  s_limit       REAL,
  s_broken      REAL,
  s_hot         REAL,
  s_index       REAL,
  total         REAL,
  label         TEXT,
  alerts        TEXT,
  completeness  REAL,
  missing       TEXT,
  model_version TEXT,
  data_version  TEXT,
  computed_at   TEXT
);
