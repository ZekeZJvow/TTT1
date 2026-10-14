CREATE TABLE IF NOT EXISTS market_seal_stats (
  trade_date   TEXT PRIMARY KEY,
  up_count     INTEGER,
  down_count   INTEGER,
  flat_count   INTEGER,
  final_count  INTEGER,               -- 入选池（昨日未涨停 + 今日冲高>9%）
  sealed_count INTEGER,               -- 其中封住涨停的
  score        REAL,                  -- 封板率 = sealed/final*100
  src          TEXT,
  computed_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_k_date_pct ON daily_kline(trade_date, change_pct);


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
CREATE INDEX IF NOT EXISTS ix_k_date_pct ON daily_kline(trade_date, change_pct);


CREATE TABLE IF NOT EXISTS market_turnover (
  trade_date   TEXT PRIMARY KEY,
  sh_amount    REAL,                     -- 沪市成交额（亿元）
  sz_amount    REAL,                     -- 深市成交额（亿元）
  amount       REAL,                     -- 两市合计（亿元）
  source       TEXT,
  collected_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_k_date_pct ON daily_kline(trade_date, change_pct);
