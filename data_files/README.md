# 量化数据存储结构说明

## 目录概览

```
data_files/
├── README.md              ← 本文件
├── manifest.json           ← 自动生成的数据清单（表名、行数、更新时间）
├── quant.duckdb            ← DuckDB 数据库文件
│
├── daily/                  ← 日线行情数据（OHLCV）
│   ├── 20260601.parquet    ← 按交易日分区，每个文件为一个交易日的全市场数据
│   └── ...
│
├── stock_basic.parquet     ← 股票基本信息（全量覆盖更新）
├── stock_list.parquet      ← 当前股票列表（精简版，仅当前上市股票）
├── st_stocks.parquet       ← 当前ST股票列表（含 *ST / ST 分类）
│
├── income/                  ← 利润表数据
│   ├── 20260331.parquet     ← 按季度分区（季度截止日期）
│
└── trade_calendar/         ← 交易日历
    ├── 2011.parquet        ← 按年份分区，15年历史
    └── ...
```

## 数据分区策略

| 数据类型 | 分区方式 | 说明 |
|---------|---------|------|
| **日线行情 (daily)** | 按交易日 `YYYYMMDD.parquet` | 每天一个文件，包含当日所有股票的 OHLCV |
| **股票信息 (stock_basic)** | 单文件 `stock_basic.parquet` | 全量基础信息，更新时整体覆盖 |
| **股票列表 (stock_list)** | 单文件 `stock_list.parquet` | 当前上市股票精简列表 |
| **ST股票 (st_stocks)** | 单文件 `st_stocks.parquet` | 当前 ST / \*ST 股票，含分类 |
| **利润表 (income)** | 按季度 `YYYYMMDD.parquet` | 利润表数据按季度发布，按季度分区 |
| **交易日历 (trade_calendar)** | 按年份 `YYYY.parquet` | 交易所交易日历，15年历史 |

## DuckDB 视图

所有 Parquet 数据通过以下视图查询：

| 视图名 | 数据来源 | 主键 | 说明 |
|--------|---------|------|------|
| `daily_view` | `daily/*.parquet` | (ts_code, trade_date) | 日线行情 |
| `stock_basic_view` | `stock_basic.parquet` | ts_code | 股票基本信息 |
| `stock_list_view` | `stock_list.parquet` | ts_code | 当前股票列表 |
| `st_stocks_view` | `st_stocks.parquet` | ts_code | ST股票列表 |
| `income_view` | `income/*.parquet` | (ts_code, end_date) | 利润表 |
| `trade_calendar_view` | `trade_calendar/*.parquet` | (exchange, cal_date) | 交易日历 |

## 使用方式

```bash
# 查看数据清单
cat manifest.json

# 交互式查询
python main.py query

# 快捷命令
.stocks         # 查看当前股票列表
.st *ST         # 查看退市预警股票
.tcal 20260601 20260605  # 查询交易日历
.isopen 20260605         # 判断是否交易日

# 直接拉取
python main.py fetch stock-list
python main.py fetch st-stocks
python main.py fetch trade-cal --start 20260101 --end 20260605

# 初始化到存储
python main.py init --data-type stock_list
python main.py init --data-type trade_calendar
python main.py init --data-type st_stocks

# 导出
python main.py export --table stock_list --format csv --output stocks.csv
```
