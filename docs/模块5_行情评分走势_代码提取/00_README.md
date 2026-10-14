# 模块5 · 行情评分走势 —— 代码提取包

> 从「A股人气雷达」里把 **第5个模块：行情评分走势** 相关的全部代码按层切片导出，方便阅读、复刻或交给别的工具重写。
> 导出时间：2026-10-14

## 一、这个模块做什么

把每天的三个市场情绪指标放在一起看，支持按月份回看：

| 指标 | 含义 | 口径 |
|---|---|---|
| **行情评分** | 当日**封板率** = 封住涨停 / 入选池 × 100 | 沪深主板**非ST**（与「动态选股」同一套规则） |
| **上涨 / 下跌家数** | 当日涨跌家数 | **沪深京全部A股**（含 ST/创业板/科创板/北交所，与同花顺「涨跌分布」完全一致） |
| **成交额总计 / 较上一日** | 两市成交额 + 相对上一交易日的增量/缩量 | 沪市 + 深市（上证综指 + 深证综指成交额） |

展示形式：顶部摘要 → 双轴走势图（橙线=评分，红绿柱=涨跌家数）→ 明细表（8 列，含成交额与较上一日）。
筛选：**1月~12月 月份按钮**（有数据才可点）+ 近30天/近60天/全部。

### 选股口径（封板率怎么算）

```
前收盘 → 涨停价 = 前收盘 × 1.1（四舍五入到分）
入选池 = 昨日「未触及涨停价」 且 今日「盘中最高涨幅 > 9%」
封住   = 今日收盘 ≥ 今日涨停价
封板率 = 封住 / 入选池 × 100
```
> 该反推法已与真实选股结果逐位核对一致。

## 二、文件清单

| 文件 | 内容 |
|---|---|
| `01_前端_面板.html` | 面板 HTML（`index.html` 的 `#panel-market` 整块） |
| `02_前端_逻辑.js` | 前端逻辑（`app.js` 里「模块5：行情评分走势」整段：月份按钮、日期范围、图表、表格渲染） |
| `03_前端_样式.css` | 该模块用到的 CSS |
| `04_后端接口.py` | Flask 路由 `/api/market-history` + 启动预热片段 |
| `05_数据层_market_db.py` | 数据层函数（离线统计、读缓存、涨跌家数/成交额读写、ST 名单） |
| `06_抓取_涨跌家数_market_breadth.py` | 全市场涨跌家数抓取（东方财富行情列表，与同花顺同口径） |
| `07_抓取_成交额_market_turnover.py` | 两市成交额抓取（东方财富指数日K + 新浪实时） |
| `08_建表.sql` | 3 张表 `market_seal_stats` / `market_breadth` / `market_turnover` + 覆盖索引 |
| `09_定时任务_片段.py` | 收盘自动落库的 3 个步骤 |
| `10_历史补齐_脚本.py` | 历史补齐脚本（全市场日K / 成交额） |

## 三、数据流

```
                    ┌── 东方财富行情列表(6000+只) ─→ market_breadth   (涨跌家数，实时口径)
每日抓取 ───────────┤
                    └── 东方财富指数日K + 新浪实时 ─→ market_turnover (两市成交额)
本地日K(daily_kline) ──离线计算封板率──→ market_seal_stats (每日评分/涨跌家数)
                                              │
GET /api/market-history ──读 3 张小表 + 合并 ──┘ ─→ 前端图表 + 明细表
```

**性能设计（重要）**：本地日K有 100 多万行（库 270MB），直接按需计算要 11 秒。
所以把「封板率」离线算好写进 `market_seal_stats`（每天只增量算缺的日子，约 0.1 秒），
接口只读 199 行的小表 → **响应 0.01 秒**；另有 120 秒读缓存 + 启动预热。

## 四、表结构

```sql
market_seal_stats(trade_date PK, up_count, down_count, flat_count,
                  final_count, sealed_count, score, src, computed_at)
market_breadth   (trade_date PK, up_count, down_count, flat_count,
                  total_count, suspended, source, collected_at)
market_turnover  (trade_date PK, sh_amount, sz_amount, amount, source, collected_at)
索引：ix_k_date_pct ON daily_kline(trade_date, change_pct)   -- 覆盖索引，统计快 50 倍
```

## 五、接口

```
GET /api/market-history?days=45                     # 最近 45 个交易日
GET /api/market-history?start=2026-04-01&end=2026-04-30   # 指定区间（月份按钮用这个）
```
返回：`{success, days, start, end, count, months:[可用月份], rows:[{date, up, down, flat,
final, sealed, score, src, breadth_src, amount, amount_prev, amount_diff}]}`

## 六、依赖的第三方接口（都是公开接口，免登录免 Key）

| 用途 | 接口 |
|---|---|
| 历史涨跌家数口径的全市场列表 | `push2.eastmoney.com/api/qt/clist/get`（分页 60 次拉全市场） |
| 两市成交额（历史） | `push2his.eastmoney.com/api/qt/stock/kline/get`（1.000001 沪 + 0.399106 深） |
| 两市成交额（实时） | `hq.sinajs.cn/list=sh000001,sz399106` |
| 个股日K（补齐用） | `quotes.sina.cn/cn/api/jsonp_v2.php/…getKLineData` |

## 七、复刻需要注意的坑

1. **成分口径别搞错**：涨跌家数必须用「沪深京全部A股」，只统计主板会少一半（同花顺对不上）。
2. **ST 过滤**：封板率必须是「主板非ST」；数据库里要保留股票名称或 `is_st` 标记，
   且日K落库时**不能把名称覆盖成 NULL**（本项目踩过这个坑，导致评分虚高）。
3. **涨停价四舍五入**要用十进制/整数运算，浮点 `round()` 会在个别价位差 1 分。
4. **计算别放在请求里**：离线算好落库，接口只读小表，否则大库上会卡 10 秒以上。
