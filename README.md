# 量化数据源系统

基于 Tushare + DuckDB + Parquet 的 A 股量化数据采集、存储与查询系统。

## 快速开始

### 1. 环境准备

```bash
pip install -r requirements.txt
```

### 2. 配置 Tushare Token

在项目根目录创建 `.env` 文件：

```
TUSHARE_TOKEN=你的tushare_token
```

可选配置项：

```
DATA_DIR=data_files       # 数据存储目录（默认 data_files）
LOG_DIR=logs              # 日志目录（默认 logs）
```

### 3. 初始化数据

```bash
# 初始化全部数据（拉取全量历史数据，耗时较长）
python main.py init

# 只初始化特定数据类型
python main.py init --data-type daily
python main.py init --data-type index_weight
```

## 命令概览

| 命令     | 用途                      |
| -------- | ------------------------- |
| `fetch`  | 直接调用 Tushare API 查询（不存储） |
| `init`   | 全量历史数据拉取 → 存储   |
| `update` | 增量更新 或 全量刷新      |
| `query`  | 交互式查询 REPL / SQL     |
| `export` | 导出数据到文件            |
| `stats`  | 查看各表记录数            |
| `schema` | 查看表结构                |

---

## 支持的数据类型

| 类型            | 说明               | 默认回溯范围     |
| --------------- | ------------------ | ---------------- |
| `daily`         | 日线行情 (OHLCV)   | 最近 5 个交易日  |
| `stock_basic`   | 股票基本信息       | 全量（轻量）     |
| `income`        | 利润表（季度）     | 当前 + 上一季度  |
| `balancesheet`  | 资产负债表（季度） | 当前 + 上一季度  |
| `cashflow`      | 现金流量表（季度） | 当前 + 上一季度  |
| `trade_calendar`| 交易日历           | 1 个月           |
| `st_stocks`     | ST 股票列表        | 全量（轻量）     |
| `adjfactor`     | 复权因子           | 1 个月           |
| `moneyflow`     | 个股资金流向       | 1 个月           |
| `index_basic`   | 指数基础信息       | 全量（轻量）     |
| `index_weight`  | 指数成分权重       | 1 个月           |
| `index_daily`   | 指数日线行情       | 1 个月           |

---

## 命令详解

### fetch — 直接查询 Tushare（不入库）

```bash
# 日线行情
python main.py fetch daily --ts-code 000001.SZ
python main.py fetch daily --ts-code 000001.SZ --start 20260101 --end 20260605

# 股票基本信息
python main.py fetch stock-basic --exchange SSE

# 财务报表
python main.py fetch income --ts-code 000001.SZ
python main.py fetch balancesheet --ts-code 000001.SZ
python main.py fetch cashflow --ts-code 000001.SZ

# 交易日历
python main.py fetch trade-cal

# ST 股票
python main.py fetch st-stocks

# 复权因子
python main.py fetch adj-factor
python main.py fetch adj-factor --ts-code 000001.SZ --start 20240101 --end 20241231

# 资金流向
python main.py fetch moneyflow --trade-date 20260630
python main.py fetch moneyflow --ts-code 000001.SZ --start 20240101

# 指数信息
python main.py fetch index-basic                        # 全部市场
python main.py fetch index-basic --market CSI           # 中证指数

# 指数成分权重
python main.py fetch index-weight --index-code 000300.SH
python main.py fetch index-weight --index-code 000905.SH --start 20240101 --end 20240630

# 指数日线
python main.py fetch index-daily --index-code 000300.SH
python main.py fetch index-daily --index-code 000852.SH --start 20240101

# 保存到文件
python main.py fetch daily --ts-code 000001.SZ -o /tmp/daily.csv
python main.py fetch daily --ts-code 000001.SZ -o /tmp/daily.parquet
```

### update — 增量 / 全量数据更新

```bash
# 增量更新全部数据类型（各类型按默认回溯范围）
python main.py update

# 全量刷新全部数据
python main.py update --full

# 更新特定类型
python main.py update --data-type daily          # 默认最近 5 个交易日
python main.py update --data-type daily -d 10    # 最近 10 个交易日
python main.py update --data-type income         # 默认 1 个月
python main.py update --data-type income -m 3    # 最近 3 个月
python main.py update --data-type index_weight -m 2
```

### query — 交互式查询

```bash
# 单次 SQL 查询
python main.py query --sql "SELECT * FROM daily_view WHERE ts_code='000001.SZ' LIMIT 5"

# 进入交互 REPL 模式
python main.py query
```

交互模式下支持的 Dot 命令：

| 命令                           | 说明                       |
| ------------------------------ | -------------------------- |
| `help`                         | 显示帮助                   |
| `tables`                       | 列出所有视图               |
| `counts`                       | 显示各表行数               |
| `schema [table]`               | 查看表结构                 |
| `.top <date> [n]`              | 某日成交额 Top-N           |
| `.rank <start> <end> [n]`      | 区间涨跌幅排名             |
| `.sector <date>`               | 板块/行业表现              |
| `.search <keyword>`            | 按名称/代码搜索股票        |
| `.industry <name>`             | 列出行业内股票             |
| `.roe <date> [n]`              | ROE 排名                   |
| `.fin <ts_code> [n]`           | 近 N 期利润表              |
| `.bs <ts_code> [n]`            | 近 N 期资产负债表          |
| `.cf <ts_code> [n]`            | 近 N 期现金流量表          |
| `.mf <ts_code> [n]`            | 近 N 日资金流向            |
| `.mfrank <date> [n]`           | 资金净流入排名             |
| `.assets <date> [n]`           | 总资产排名                 |
| `.latest <ts_code>`            | 个股最新日线               |
| `.stocks [market]`             | 股票列表                   |
| `.st [type]`                   | ST 股票列表 (ST/*ST)       |
| `.tcal <start> <end>`          | 交易日历查询               |
| `.isopen <date>`               | 判断是否交易日             |
| `.indices [market]`            | 指数基本信息               |
| `.isearch <keyword>`           | 搜索指数                   |
| `.iw <index> [date]`           | 指数成分权重               |
| `.iwtop <index> [date] [n]`    | 指数 Top-N 权重股          |
| `.iwcon <con_code>`            | 查询个股所属指数           |
| `.iwsum [index]`               | 指数权重汇总统计           |
| `.id <index> [start] [end]`    | 指数日线行情               |
| `.idlatest <index>`            | 指数最新日线               |
| `.idrank <date> [n]`           | 指数涨跌幅排名             |

也可以直接输入任意 SQL 语句：

```sql
SELECT ts_code, trade_date, close, pct_chg
FROM daily_view
WHERE trade_date = '20260630'
ORDER BY amount DESC
LIMIT 20
```

### export — 数据导出

```bash
# 日线
python main.py export --table daily --ts-code 000001.SZ --format csv -o /tmp/daily.csv

# 财务报表（需指定报告期）
python main.py export --table income --period 20260331 --format csv -o /tmp/income.csv
python main.py export --table income --period 20260331 --ts-code 000001.SZ -f csv -o /tmp/income.csv

# 复权因子 / 资金流向（需指定交易日）
python main.py export --table adjfactor --period 20260627 --ts-code 000001.SZ -f csv -o /tmp/adj.csv
python main.py export --table moneyflow --period 20260627 -f csv -o /tmp/mf.csv

# 指数权重
python main.py export --table index_weight --ts-code 000300.SH --start 20260301 --end 20260630 -f csv -o /tmp/iw.csv

# 指数日线
python main.py export --table index_daily --ts-code 000300.SH -f csv -o /tmp/id.csv
```

支持的导出格式：`csv`、`parquet`、`json`

### stats & schema — 信息查看

```bash
# 查看各表记录数
python main.py stats

# 查看表结构
python main.py schema
```

---

## 项目结构

```
quant/
├── main.py              # CLI 入口，argparse 命令行解析
├── config/
│   └── settings.py      # 配置管理（环境变量 / .env）
├── data/
│   ├── fetcher.py       # Tushare API 封装（数据拉取 + 重试）
│   ├── storage.py       # DuckDB + Parquet 读写 / 分区管理
│   └── updater.py       # 增量更新 & 全量初始化逻辑
├── query/
│   └── engine.py        # 查询引擎（REPL / SQL / 快捷查询）
├── utils/
│   ├── logger.py        # 日志系统（控制台 + 文件轮转）
│   └── csv_io.py        # CSV 读写辅助
├── data_files/          # 数据存储目录（Parquet + DuckDB）
│   ├── quant.duckdb     # DuckDB 数据库文件
│   ├── manifest.json    # 元数据清单（表名 / 行数 / 分区信息）
│   ├── daily/           # 日线 Parquet（按日期分区）
│   ├── income/          # 利润表 Parquet（按季度分区）
│   ├── balancesheet/    # 资产负债表 Parquet
│   ├── cashflow/        # 现金流量表 Parquet
│   ├── adjfactor/       # 复权因子 Parquet
│   ├── moneyflow/       # 资金流向 Parquet
│   ├── trade_calendar/  # 交易日历 Parquet
│   ├── index_weight/    # 指数权重 Parquet（按指数分区）
│   └── index_daily/     # 指数日线 Parquet
├── logs/                # 日志文件
├── requirements.txt     # Python 依赖
└── README.md
```

## 覆盖的指数

`index_weight` 和 `index_daily` 默认覆盖以下指数：

| 指数         | 代码        | 说明       |
| ------------ | ----------- | ---------- |
| 沪深 300     | 000300.SH   | HS300      |
| 中证 500     | 000905.SH   | ZZ500      |
| 中证 1000    | 000852.SH   | ZZ1000     |
| 中证 2000    | 932000.CSI  | ZZ2000     |

## 依赖

| 库               | 用途            |
| ---------------- | --------------- |
| `tushare>=1.4.0` | A 股数据源      |
| `duckdb>=1.0.0`  | OLAP 数据库引擎 |
| `pandas>=2.0.0`  | 数据处理        |
| `pyarrow>=14.0.0`| Parquet 读写    |
| `python-dotenv`  | .env 配置加载   |
