-- ============================================================================
--  A股人气榜查询系统 · MySQL 结构（19 张表）
--  用法： mysql -u root -p your_db < deploy/mysql_schema.sql
--  迁移数据： python tools/sqlite_to_mysql.py --help
--
--  与 SQLite 版的差异：
--    INTEGER PK AUTOINCREMENT -> BIGINT UNSIGNED AUTO_INCREMENT
--    TEXT(短字段)             -> VARCHAR(n)  （MySQL 索引需要长度）
--    REAL                     -> DECIMAL(18,4)（金额/价格精确）
--    payload_json/大文本       -> LONGTEXT
--    INSERT ... ON CONFLICT   -> INSERT ... ON DUPLICATE KEY UPDATE（见迁移脚本）
-- ============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------- 一、维度层 ----------

CREATE TABLE IF NOT EXISTS stock (
  code        VARCHAR(10)  NOT NULL COMMENT '6位代码',
  name        VARCHAR(32)      NULL,
  market      VARCHAR(8)       NULL COMMENT 'SH/SZ/BJ',
  board       VARCHAR(16)      NULL,
  is_st       TINYINT          NOT NULL DEFAULT 0,
  thscode     VARCHAR(20)      NULL,
  list_date   DATE             NULL,
  status      VARCHAR(4)       NOT NULL DEFAULT 'L',
  updated_at  DATETIME         NULL,
  PRIMARY KEY (code),
  KEY ix_stock_name (name),
  KEY ix_stock_board (market, board)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS trade_calendar (
  trade_date       DATE        NOT NULL,
  is_open          TINYINT     NOT NULL DEFAULT 1,
  prev_trade_date  DATE            NULL,
  next_trade_date  DATE            NULL,
  source           VARCHAR(32)     NULL,
  updated_at       DATETIME        NULL,
  PRIMARY KEY (trade_date),
  KEY ix_cal_open (is_open)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS theme_catalog (
  theme_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  thscode     VARCHAR(20)     NOT NULL,
  name        VARCHAR(64)     NOT NULL,
  tag         VARCHAR(16)         NULL,
  source      VARCHAR(16)         NULL,
  updated_at  DATETIME            NULL,
  PRIMARY KEY (theme_id),
  UNIQUE KEY uk_theme_thscode (thscode),
  KEY ix_theme_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS theme_member (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  theme_id    BIGINT UNSIGNED NOT NULL,
  stock_code  VARCHAR(10)     NOT NULL,
  in_date     DATE                NULL,
  updated_at  DATETIME            NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_tm (theme_id, stock_code),
  KEY ix_tm_stock (stock_code),
  CONSTRAINT fk_tm_theme FOREIGN KEY (theme_id) REFERENCES theme_catalog(theme_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- 二、快照层 ----------

CREATE TABLE IF NOT EXISTS hotlist_snapshot (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  trade_date        DATE            NOT NULL,
  captured_at       DATETIME        NOT NULL,
  `rank`            INT             NOT NULL,
  stock_code        VARCHAR(10)     NOT NULL,
  stock_name        VARCHAR(32)         NULL,
  rise_and_fall     DECIMAL(10,4)       NULL,
  boards_count      INT                 NULL,
  boards_text       VARCHAR(32)         NULL,
  tier              VARCHAR(32)         NULL,
  concept_tag       VARCHAR(255)        NULL,
  anomaly_analysis  VARCHAR(255)        NULL,
  is_hot            TINYINT             NOT NULL DEFAULT 0,
  source            VARCHAR(32)         NULL,
  degraded          TINYINT             NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uk_hot (trade_date, captured_at, stock_code),
  KEY ix_hot_date_rank (trade_date, `rank`),
  KEY ix_hot_stock (stock_code, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS limit_up_pool (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  trade_date      DATE            NOT NULL,
  stock_code      VARCHAR(10)     NOT NULL,
  stock_name      VARCHAR(32)         NULL,
  boards          INT                 NULL,
  first_seal_time VARCHAR(12)         NULL,
  last_seal_time  VARCHAR(12)         NULL,
  break_count     INT                 NULL,
  seal_amount     DECIMAL(20,4)       NULL,
  amount          DECIMAL(20,4)       NULL,
  sector          VARCHAR(64)         NULL,
  state           VARCHAR(16)         NULL COMMENT '涨停/炸板',
  source          VARCHAR(32)         NULL,
  collected_at    DATETIME            NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_lu (trade_date, stock_code),
  KEY ix_lu_stock (stock_code, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS daily_kline (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  stock_code   VARCHAR(10)     NOT NULL,
  trade_date   DATE            NOT NULL,
  open         DECIMAL(12,4)       NULL,
  high         DECIMAL(12,4)       NULL,
  low          DECIMAL(12,4)       NULL,
  close        DECIMAL(12,4)       NULL,
  prev_close   DECIMAL(12,4)       NULL,
  change_pct   DECIMAL(10,4)       NULL,
  volume       DECIMAL(24,4)       NULL,
  amount       DECIMAL(24,4)       NULL,
  source       VARCHAR(16)         NULL,
  collected_at DATETIME            NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_kline (stock_code, trade_date),
  KEY ix_k_date (trade_date),
  KEY ix_k_stock (stock_code, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS minute_kline (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  stock_code  VARCHAR(10)     NOT NULL,
  trade_date  DATE            NOT NULL,
  minute      CHAR(5)         NOT NULL COMMENT 'HH:MM',
  price       DECIMAL(12,4)       NULL,
  avg_price   DECIMAL(12,4)       NULL,
  volume      DECIMAL(24,4)       NULL,
  amount      DECIMAL(24,4)       NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_min (stock_code, trade_date, minute),
  KEY ix_min_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stock_news (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  stock_code   VARCHAR(10)     NOT NULL,
  news_date    DATE                NULL,
  published_at DATETIME            NULL,
  title        VARCHAR(255)    NOT NULL,
  source       VARCHAR(32)         NULL,
  news_type    VARCHAR(16)         NULL,
  url          VARCHAR(255)        NULL,
  collected_at DATETIME            NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_news (stock_code, url),
  KEY ix_news_stock (stock_code, news_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stock_anomaly (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  trade_date   DATE            NOT NULL,
  stock_code   VARCHAR(10)     NOT NULL,
  stock_name   VARCHAR(32)         NULL,
  reason       VARCHAR(255)        NULL,
  change_pct   DECIMAL(10,4)       NULL,
  `rank`       INT                 NULL,
  collected_at DATETIME            NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_an (trade_date, stock_code),
  KEY ix_an_stock (stock_code, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dragon_tiger (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  trade_date       DATE            NOT NULL,
  stock_code       VARCHAR(10)     NOT NULL,
  stock_name       VARCHAR(32)         NULL,
  net_amount       DECIMAL(20,4)       NULL,
  institution_net  DECIMAL(20,4)       NULL,
  reason           VARCHAR(255)        NULL,
  collected_at     DATETIME            NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_dt (trade_date, stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS theme_heat_snapshot (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  trade_date      DATE            NOT NULL,
  captured_at     DATETIME            NULL,
  theme_id        BIGINT UNSIGNED     NULL,
  theme_name      VARCHAR(64)     NOT NULL,
  tag             VARCHAR(16)         NULL,
  verdict         VARCHAR(8)          NULL COMMENT '利好/利空/中性',
  `rank`          INT                 NULL,
  heat_score      DECIMAL(12,2)       NULL,
  pop_heat        DECIMAL(12,2)       NULL,
  topic_heat      DECIMAL(12,2)       NULL,
  net_score       INT                 NULL,
  bull            INT                 NULL,
  bear            INT                 NULL,
  stock_total     INT                 NULL,
  stock_count     INT                 NULL,
  reason_summary  TEXT                NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_ths (trade_date, theme_name),
  KEY ix_ths_date_rank (trade_date, `rank`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS theme_topic (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  trade_date   DATE            NOT NULL,
  title        VARCHAR(255)    NOT NULL,
  description  TEXT                NULL,
  hot          DECIMAL(20,2)       NULL,
  url          VARCHAR(500)        NULL,
  source       VARCHAR(16)         NULL,
  collected_at DATETIME            NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_topic (trade_date, title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS theme_topic_link (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  topic_id   BIGINT UNSIGNED     NULL,
  theme_id   BIGINT UNSIGNED     NULL,
  trade_date DATE                NULL,
  weight     DECIMAL(8,4)        NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_ttl (topic_id, theme_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS theme_top_stock (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  trade_date  DATE            NOT NULL,
  theme_name  VARCHAR(64)     NOT NULL,
  stock_code  VARCHAR(10)     NOT NULL,
  stock_name  VARCHAR(32)         NULL,
  hot_rank    INT                 NULL,
  trend_rank  INT                 NULL,
  heat        DECIMAL(12,2)       NULL,
  `rank`      INT                 NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_tts (trade_date, theme_name, stock_code),
  KEY ix_tts_date_rank (trade_date, `rank`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS scan_stock (
  target_date   DATE        NOT NULL,
  stock_code    VARCHAR(10) NOT NULL,
  stock_name    VARCHAR(32)     NULL,
  close_d2      DECIMAL(12,4)   NULL,
  close_prev    DECIMAL(12,4)   NULL,
  limit_prev    DECIMAL(12,4)   NULL,
  open          DECIMAL(12,4)   NULL,
  high          DECIMAL(12,4)   NULL,
  low           DECIMAL(12,4)   NULL,
  close         DECIMAL(12,4)   NULL,
  limit_price   DECIMAL(12,4)   NULL,
  gain_high     DECIMAL(10,4)   NULL,
  gain_close    DECIMAL(10,4)   NULL,
  amplitude     DECIMAL(10,4)   NULL,
  amount_est    DECIMAL(24,4)   NULL,
  volume        DECIMAL(24,4)   NULL,
  touched_prev  TINYINT         NULL,
  sealed        TINYINT         NULL,
  broke         TINYINT         NULL,
  cond1         TINYINT         NULL,
  cond2         TINYINT         NULL,
  prev_gain     DECIMAL(10,4)   NULL,
  skipped       TINYINT         NOT NULL DEFAULT 0,
  collected_at  DATETIME        NULL,
  PRIMARY KEY (target_date, stock_code),
  KEY ix_scan_date (target_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- 三、结果层 ----------

CREATE TABLE IF NOT EXISTS screening_run (
  run_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  target_date     DATE            NOT NULL,
  prev_trade_date DATE                NULL,
  universe_count  INT                 NULL,
  cond2_count     INT                 NULL,
  cond1_count     INT                 NULL,
  sealed_count    INT                 NULL,
  broken_count    INT                 NULL,
  removed_count   INT                 NULL,
  elapsed_sec     DECIMAL(10,2)       NULL,
  source          VARCHAR(64)         NULL,
  payload_json    LONGTEXT            NULL,
  started_at      DATETIME            NULL,
  finished_at     DATETIME            NULL,
  PRIMARY KEY (run_id),
  UNIQUE KEY uk_run (target_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS screening_result (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id       BIGINT UNSIGNED NOT NULL,
  target_date  DATE            NOT NULL,
  stock_code   VARCHAR(10)     NOT NULL,
  stock_name   VARCHAR(32)         NULL,
  close_prev   DECIMAL(12,4)       NULL,
  high         DECIMAL(12,4)       NULL,
  gain_high    DECIMAL(10,4)       NULL,
  close        DECIMAL(12,4)       NULL,
  gain_close   DECIMAL(10,4)       NULL,
  amount_est   DECIMAL(24,4)       NULL,
  first_seal   VARCHAR(12)         NULL,
  boards       INT                 NULL,
  sector       VARCHAR(64)         NULL,
  state        VARCHAR(16)         NULL,
  bucket       VARCHAR(16)     NOT NULL COMMENT 'selected/broken/removed',
  `rank`       INT                 NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sr (run_id, stock_code, bucket),
  KEY ix_sr_date_bucket (target_date, bucket),
  KEY ix_sr_stock (stock_code, target_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- 四、运维层 ----------

CREATE TABLE IF NOT EXISTS fetch_log (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  task_type   VARCHAR(32)         NULL,
  source      VARCHAR(64)         NULL,
  endpoint    VARCHAR(500)        NULL,
  trade_date  DATE                NULL,
  status      VARCHAR(16)         NULL,
  http_code   INT                 NULL,
  `rows`      INT                 NULL,
  duration_ms INT                 NULL,
  error       TEXT                NULL,
  detail      TEXT                NULL,
  started_at  DATETIME            NULL,
  finished_at DATETIME            NULL,
  PRIMARY KEY (id),
  KEY ix_log_task_time (task_type, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS raw_payload (
  cache_key    VARCHAR(64)  NOT NULL,
  kind         VARCHAR(16)  NOT NULL,
  trade_date   DATE             NULL,
  payload_json LONGTEXT     NOT NULL,
  created_at   DATETIME         NULL,
  PRIMARY KEY (cache_key),
  KEY ix_raw_kind_date (kind, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;
