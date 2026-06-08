================================================================================
                    Quant 量化数据采集与查询系统 — 使用说明书
================================================================================

一、系统概述
--------------------------------------------------------------------------------

本系统是一个基于 Tushare Pro API 的 A 股量化数据采集、存储与查询工具。
核心功能包括：

  1. 从 Tushare 拉取股票数据（日线行情、基本信息、利润表、资产负债表、
     现金流量表、交易日历、ST 股票等）
  2. 以 Parquet 格式存储数据，使用 DuckDB 作为查询引擎
  3. 提供命令行工具（CLI）和交互式查询终端（REPL）
  4. 支持增量更新与全量刷新

技术栈：Python 3.10+ / Tushare Pro / DuckDB / Pandas / PyArrow

数据存储目录结构：

  data_files/
  ├── manifest.json           ← 自动生成的数据清单
  ├── quant.duckdb            ← DuckDB 数据库文件
  ├── daily/                  ← 日线行情（按交易日分区：20260601.parquet）
  ├── stock_basic.parquet     ← 股票基本信息（单文件）
  ├── stock_list.parquet      ← 股票列表（精简版，单文件）
  ├── st_stocks.parquet       ← 当前 ST 股票列表（单文件）
  ├── income/                 ← 利润表数据（按季度分区：20260331.parquet）
  ├── balancesheet/           ← 资产负债表数据（按季度分区：20260331.parquet）
  ├── cashflow/               ← 现金流量表数据（按季度分区：20260331.parquet）
  └── trade_calendar/         ← 交易日历（按年份分区：2026.parquet）

当前数据规模（截至 2026-06-08）：
  daily:           13,351,617 行（3,641 个交易日，2011-06 至今）
  stock_basic:      5,526 行（全部上市股票）
  income:            266,591 行（61 个季度）
  cashflow:          288,564 行（61 个季度）
  balancesheet:      330,975 行（61 个季度）
  trade_calendar:     5,479 行（16 年）
  st_stocks:            241 行（当前 ST 股票）


二、环境准备
--------------------------------------------------------------------------------

1. 安装 Python 依赖：

    pip install -r requirements.txt

   依赖包清单：
   - tushare >= 1.4.0       (Tushare Pro API 客户端)
   - duckdb >= 1.0.0        (嵌入式分析型数据库)
   - pandas >= 2.0.0        (数据处理)
   - pyarrow >= 14.0.0      (Parquet 读写支持)
   - python-dotenv >= 1.0.0 (环境变量加载)

2. 配置 Tushare Token：

   复制 .env.example 为 .env 并填入你的 Tushare Pro token：

    cp .env.example .env

   .env 文件内容说明：

    TUSHARE_TOKEN=你的token    ← 必填！在 https://tushare.pro/user/token 获取
    DATA_DIR=./data_files      ← 数据存储目录（可选，默认为 ./data_files）
    LOG_DIR=./logs             ← 日志目录（可选，默认为 ./logs）
    DUCKDB_PATH=./data_files/quant.duckdb  ← DuckDB 路径（可选）

   注意：Tushare Pro 不同积分等级对应不同的 API 访问权限。部分接口
   （如 income_vip、balancesheet_vip、cashflow_vip）需要较高积分才能使用。
   详见：https://tushare.pro/document/1?doc_id=40


三、命令行使用
--------------------------------------------------------------------------------

所有命令均通过 main.py 执行，格式为：

    python main.py <命令> [子命令] [参数]

可用命令一览：

    命令      说明
    -----------------------------------------------------------
    fetch     直接从 Tushare 拉取数据（不存入本地存储）
    init      全量历史数据拉取并存入本地存储
    update    增量或全量更新本地数据
    query     交互式查询终端 或 单条 SQL 查询
    export    将本地存储的数据导出为文件
    stats     查看各数据表的记录数
    schema    查看各数据表的结构（列名、类型）


3.1 fetch — 直接拉取数据（不存储）
................................................................................

用途：直接从 Tushare API 拉取数据，结果打印到终端或保存为文件。
      这些数据不会被存入本地 Parquet/DuckDB 存储。

子命令：

  (1) 日线行情 (daily)

      python main.py fetch daily --ts-code 000001.SZ
      python main.py fetch daily --ts-code 000001.SZ --start 20260101 --end 20260605
      python main.py fetch daily --output result.csv

      参数：
        --ts-code    股票代码，格式如 000001.SZ（省略则拉取全部股票）
        --start      起始日期 YYYYMMDD（默认：15 年前）
        --end        结束日期 YYYYMMDD（默认：今天）
        -o, --output 保存到文件（支持 .csv / .parquet）

  (2) 股票基本信息 (stock-basic)

      python main.py fetch stock-basic
      python main.py fetch stock-basic --exchange SSE
      python main.py fetch stock-basic -o stocks_info.csv

      参数：
        --exchange   交易所筛选：SSE(上交所) / SZSE(深交所) / BSE(北交所)
                     （默认为空，即全部）
        -o, --output 保存到文件

  (3) 利润表 (income)

      python main.py fetch income --ts-code 000001.SZ
      python main.py fetch income --period 20260331
      python main.py fetch income -o income.csv

      参数：
        --ts-code    股票代码（省略则使用 income_vip 接口拉取全部）
        --period     报告期截止日 YYYYMMDD（默认为当前季度末）
        -o, --output 保存到文件

      说明：income API 要求必须提供 ts_code；当省略 ts_code 时，
      系统自动切换到 income_vip 接口，支持全市场拉取。

  (4) 资产负债表 (balancesheet)

      python main.py fetch balancesheet --ts-code 000001.SZ
      python main.py fetch balancesheet --period 20260331
      python main.py fetch balancesheet -o balance.csv

      参数：
        --ts-code    股票代码（省略则拉取全部）
        --period     报告期截止日 YYYYMMDD（默认为当前季度末）
        -o, --output 保存到文件

  (5) 现金流量表 (cashflow)

      python main.py fetch cashflow --ts-code 000001.SZ
      python main.py fetch cashflow --period 20260331
      python main.py fetch cashflow -o cashflow.csv

      参数：
        --ts-code    股票代码（省略则拉取全部）
        --period     报告期截止日 YYYYMMDD（默认为当前季度末）
        -o, --output 保存到文件

  (6) 交易日历 (trade-cal)

      python main.py fetch trade-cal
      python main.py fetch trade-cal --start 20260101 --end 20261231
      python main.py fetch trade-cal --exchange SSE

      参数：
        --start      起始日期（默认：15 年前）
        --end        结束日期（默认：今天）
        --exchange   交易所筛选（SSE / SZSE / BSE，默认全部）
        -o, --output 保存到文件

  (7) ST 股票列表 (st-stocks)

      python main.py fetch st-stocks
      python main.py fetch st-stocks -o st_list.csv

      拉取当前全部 ST / *ST 股票列表（从 stock_basic 中筛选）。


3.2 init — 初始化全量数据
................................................................................

用途：首次使用时，从 Tushare 拉取全量历史数据并存入本地 Parquet 存储。
      此操作数据量较大、耗时较长，建议在网络稳定时执行。

    python main.py init                      # 初始化全部数据类型
    python main.py init --data-type daily    # 仅初始化日线数据
    python main.py init --data-type stock_basic  # 仅初始化股票基本信息
    python main.py init --data-type income   # 仅初始化利润表数据
    python main.py init --data-type balancesheet  # 仅初始化资产负债表数据
    python main.py init --data-type cashflow  # 仅初始化现金流量表数据
    python main.py init --data-type trade_calendar  # 仅初始化交易日历
    python main.py init --data-type st_stocks  # 仅初始化 ST 股票列表

    python main.py init --data-type income --ts-code 000001.SZ
      # 仅初始化单只股票的利润表数据（ts-code 仅对 income/cashflow/balancesheet 有效）

说明：
  - daily 数据按交易日逐日拉取（约 15 年历史），每交易日一个 Parquet 文件
  - income / balancesheet / cashflow 按季度逐季拉取（约 61 个季度），
    每季一个 Parquet 文件（如 20260331.parquet），使用 VIP 接口支持全量拉取
  - stock_basic / st_stocks 为单文件全量覆盖更新
  - trade_calendar 按年份分区存储

  预计耗时：
  - 全量初始化（全部类型）：约 30-60 分钟（取决于网络和 API 限速）
  - 仅 daily：约 20-40 分钟（约 3750+ 次 API 调用）
  - 仅财务数据（income/balancesheet/cashflow）：约 5-10 分钟
  - 其他类型：数秒至数十秒


3.3 update — 更新数据
................................................................................

用途：增量拉取最新数据并入本地存储，适合每日定时执行。

    python main.py update                    # 增量更新所有类型（默认）
    python main.py update --full             # 全量刷新（重新拉取全部历史）
    python main.py update --data-type daily  # 仅更新日线数据
    python main.py update --data-type income  # 仅更新利润表数据
    python main.py update --data-type balancesheet  # 仅更新资产负债表数据
    python main.py update --data-type cashflow  # 仅更新现金流量表数据
    python main.py update --months 6         # 增量更新最近 6 个月的数据

增量更新策略：
  - daily：找到最近 4 个交易日，仅拉取缺失的交易日数据
  - income / balancesheet / cashflow：拉取当前季度 + 上一季度的财务数据
  - stock_basic / st_stocks：全量刷新（数据量小）
  - trade_calendar：拉取最近 N 个月（默认 3 个月）


3.4 query — 数据查询
................................................................................

用途：支持交互式 REPL 查询和单条 SQL 查询两种模式。

  (1) 交互式查询（REPL）

      python main.py query

      进入交互终端后，可以使用以下 dot-command 快捷命令：

      行情类：
      .top <日期> [N]        指定日期成交额 Top-N 排名
                             例：.top 20260605 20

      .rank <起始日> <结束日> [N]  区间累计涨跌幅排名
                             例：.rank 20260601 20260605 20

      .sector <日期>         指定日期各行业板块表现（涨跌幅、成交额均值）
                             例：.sector 20260605

      .latest <股票代码>     查看某股票最新一个交易日数据
                             例：.latest 000001.SZ

      股票信息类：
      .search <关键词>       按股票名称/代码/拼音搜索
                             例：.search 平安

      .industry <行业名>     查看某行业下全部股票
                             例：.industry 银行

      .stocks [市场]         查看股票列表（可选按市场筛选：主板/创业板/科创板）
                             例：.stocks 创业板

      .st [类型]             查看 ST 股票（ST 或 *ST）
                             例：.st *ST

      财务数据类：
      .roe <截止日期> [N]    归母净利润排名 Top-N（基于利润表）
                             例：.roe 20260331 30

      .fin <股票代码> [N]    查看某股票最近 N 期利润表数据（默认 8 期）
                             例：.fin 000001.SZ 8

      .bs <股票代码> [N]     查看某股票最近 N 期资产负债表数据（默认 8 期）
                             例：.bs 000001.SZ 8

      .cf <股票代码> [N]     查看某股票最近 N 期现金流量表数据（默认 8 期）
                             例：.cf 000001.SZ 8

      .assets <截止日期> [N] 总资产排名 Top-N（基于资产负债表）
                             例：.assets 20260331 20

      交易日历类：
      .tcal <起始> <结束>    查询交易日历
                             例：.tcal 20260601 20260605

      .isopen <日期>         判断某日是否为交易日
                             例：.isopen 20260606

      Meta 命令：
        help                 显示帮助
        tables               列出可用视图
        counts               显示各表行数
        schema [表名]         显示表结构
        exit / quit / q      退出

      也可直接输入任意 SQL 语句查询，例如：
      SELECT * FROM daily_view WHERE ts_code='000001.SZ' LIMIT 5;

      可用的 DuckDB 视图（共 7 个）：
        daily_view           日线行情
        stock_basic_view     股票基本信息
        income_view          利润表
        balancesheet_view    资产负债表
        cashflow_view        现金流量表
        trade_calendar_view  交易日历
        st_stocks_view       ST 股票列表

  (2) 单条 SQL 查询

      python main.py query --sql "SELECT * FROM daily_view LIMIT 5"
      python main.py query -s "SELECT ts_code, name FROM stock_basic_view WHERE industry='银行'"
      python main.py query -s "SELECT ts_code, end_date, total_assets, total_liab FROM balancesheet_view WHERE ts_code='000001.SZ' ORDER BY end_date DESC LIMIT 4"


3.5 export — 导出数据
................................................................................

用途：将本地存储的数据导出为 CSV / Parquet / JSON 文件。

    # 日线数据导出
    python main.py export --table daily --ts-code 000001.SZ --format csv --output /tmp/daily.csv
    python main.py export --table daily --start 20260101 --end 20260605 --format csv --output result.csv

    # 财务数据导出（需指定 --period）
    python main.py export --table income --period 20260331 --format csv --output /tmp/income.csv
    python main.py export --table income --period 20260331 --ts-code 000001.SZ --format csv --output /tmp/income.csv
    python main.py export --table balancesheet --period 20260331 --format csv --output /tmp/balance.csv
    python main.py export --table cashflow --period 20260331 --format csv --output /tmp/cashflow.csv

    # 其他数据导出
    python main.py export --table stock_basic --format json --output stocks.json
    python main.py export --table trade_calendar --start 20260101 --end 20261231 --format csv --output cal.csv
    python main.py export --table st_stocks --format csv --output st.csv

    参数：
      -t, --table   数据表名（必填），可选值：
                    daily / stock_basic / income / balancesheet / cashflow /
                    trade_calendar / st_stocks
      -f, --format  导出格式（默认 csv），可选：csv / parquet / json
      -o, --output  输出文件路径（必填）
      --ts-code     按股票代码筛选（可选）
      --period      季度截止日 YYYYMMDD（income/balancesheet/cashflow 必填）
      --start       起始日期 YYYYMMDD（可选，用于 daily / trade_calendar）
      --end         结束日期 YYYYMMDD（可选，用于 daily / trade_calendar）

    注意：导出 CSV 时，数值列会自动转为字符串以防止 Excel 整数溢出。


3.6 stats & schema — 数据概览
................................................................................

    python main.py stats      # 显示各数据表的记录数
    python main.py schema     # 显示各数据表的列名和数据类型


四、典型工作流程
--------------------------------------------------------------------------------

4.1 首次使用 — 全量初始化

    # 步骤 1：配置 .env 文件（填入 Tushare Token）
    cp .env.example .env
    vim .env

    # 步骤 2：全量拉取所有数据（耗时较长，约需 30-60 分钟）
    python main.py init

    # 或分批初始化（推荐，易于排查问题）
    python main.py init --data-type stock_basic
    python main.py init --data-type trade_calendar
    python main.py init --data-type daily
    python main.py init --data-type income
    python main.py init --data-type balancesheet
    python main.py init --data-type cashflow
    python main.py init --data-type st_stocks

    # 步骤 3：查看数据概览
    python main.py stats
    python main.py schema

    # 步骤 4：开始查询
    python main.py query


4.2 日常使用 — 增量更新 + 查询

    # 每日更新（建议收盘后执行）
    python main.py update

    # 查看最新行情
    python main.py query --sql "SELECT * FROM daily_view ORDER BY trade_date DESC LIMIT 10"

    # 进入交互模式进行分析
    python main.py query


4.3 定时任务 — cron 自动化

    在 crontab 中添加（每个交易日 15:30 执行增量更新）：

    crontab -e
    30 15 * * 1-5 cd /home/twpony/quant/twpony && python main.py update >> logs/cron.log 2>&1

    注意：cron 执行时需确保 .env 文件可被正确加载（工作目录正确）。


五、数据库表结构与字段说明
--------------------------------------------------------------------------------

5.1 daily_view — 日线行情

    DuckDB 视图：daily_view
    数据来源：daily/*.parquet
    主键：(ts_code, trade_date)
    分区方式：按交易日（YYYYMMDD.parquet）

    字段          类型        说明
    ----------------------------------------------------------
    ts_code       VARCHAR     股票代码（如 000001.SZ）
    trade_date    VARCHAR     交易日期 YYYYMMDD
    open          DOUBLE      开盘价
    high          DOUBLE      最高价
    low           DOUBLE      最低价
    close         DOUBLE      收盘价
    pre_close     DOUBLE      前收盘价
    change        DOUBLE      涨跌额
    pct_chg       DOUBLE      涨跌幅（%）
    vol           DOUBLE      成交量（手）
    amount        DOUBLE      成交额（千元）


5.2 stock_basic_view — 股票基本信息

    DuckDB 视图：stock_basic_view
    数据来源：stock_basic.parquet（单文件）
    主键：ts_code

    字段          类型        说明
    ----------------------------------------------------------
    ts_code       VARCHAR     股票代码
    symbol        VARCHAR     股票简称（如 000001）
    name          VARCHAR     股票名称（如 平安银行）
    area          VARCHAR     地区
    industry      VARCHAR     所属行业
    fullname      VARCHAR     公司全称
    enname        VARCHAR     英文名称
    cnspell       VARCHAR     拼音缩写
    market        VARCHAR     市场类型（主板/创业板/科创板）
    exchange      VARCHAR     交易所（SSE/SZSE/BSE）
    curr_type     VARCHAR     货币类型
    list_status   VARCHAR     上市状态（L=上市 D=退市 P=暂停）
    list_date     VARCHAR     上市日期 YYYYMMDD
    delist_date   VARCHAR     退市日期
    is_hs         VARCHAR     是否沪深港通标的（S=是 N=否 H=沪港通）
    act_name      VARCHAR     实际控制人名称
    act_ent_type  VARCHAR     实际控制人企业类型


5.3 income_view — 利润表

    DuckDB 视图：income_view
    数据来源：income/*.parquet（按季度分区）
    主键：(ts_code, end_date)
    分区方式：按季度截止日（YYYYMMDD.parquet）
    API 接口：income / income_vip（全量拉取时使用 VIP 接口）
    总计 63 列（7 个分类列 + 56 个数值列）

    分类字段：
    字段          类型        说明
    ----------------------------------------------------------
    ts_code       VARCHAR     股票代码
    ann_date      VARCHAR     公告日期
    f_ann_date    VARCHAR     实际公告日期
    end_date      VARCHAR     报告期截止日（季度末）
    report_type   VARCHAR     报告类型（1=合并报表 2=单季报表）
    comp_type     VARCHAR     公司类型（1=一般工商业 2=银行 3=保险 4=证券）
    end_type      VARCHAR     期末类型（1=年报 2=半年报 3=一季报 4=三季报）
    update_flag   VARCHAR     更新标识

    收益类：
    字段                     类型        说明
    ----------------------------------------------------------
    basic_eps                DOUBLE      基本每股收益
    diluted_eps              DOUBLE      稀释每股收益
    total_revenue            DOUBLE      营业总收入
    revenue                  DOUBLE      营业收入
    int_income               DOUBLE      利息收入
    prem_earned              DOUBLE      已赚保费
    comm_income              DOUBLE      手续费及佣金收入
    n_commis_income          DOUBLE      手续费及佣金净收入
    n_oth_income             DOUBLE      其他经营净收益
    n_oth_b_income           DOUBLE      其他业务净收益
    prem_income              DOUBLE      保险业务收入
    out_prem                 DOUBLE      分出保费
    une_prem_reser           DOUBLE      未到期责任准备金
    reins_income             DOUBLE      分保收益
    n_sec_tb_income          DOUBLE      代理买卖证券业务净收入
    n_sec_uw_income          DOUBLE      证券承销业务净收入
    n_asset_mg_income        DOUBLE      受托客户资产管理业务净收入
    oth_b_income             DOUBLE      其他业务收入
    fv_value_chg_gain        DOUBLE      公允价值变动收益
    invest_income            DOUBLE      投资收益
    ass_invest_income        DOUBLE      对联营企业和合营企业的投资收益
    forex_gain               DOUBLE      汇兑收益

    成本费用类：
    字段                     类型        说明
    ----------------------------------------------------------
    total_cogs               DOUBLE      营业总成本
    oper_cost                DOUBLE      营业成本
    int_exp                  DOUBLE      利息支出
    comm_exp                 DOUBLE      手续费及佣金支出
    biz_tax_surchg           DOUBLE      营业税金及附加
    sell_exp                 DOUBLE      销售费用
    admin_exp                DOUBLE      管理费用
    fin_exp                  DOUBLE      财务费用
    assets_impair_loss       DOUBLE      资产减值损失
    prem_refund              DOUBLE      退保金
    compens_payout           DOUBLE      赔付支出净额
    reser_insur_liab         DOUBLE      提取保险责任准备金
    div_payt                 DOUBLE      保单红利支出
    reins_exp                DOUBLE      分保费用
    oper_exp                 DOUBLE      营业支出
    compens_payout_refu      DOUBLE      摊回赔付支出
    insur_reser_refu         DOUBLE      摊回保险责任准备金
    reins_cost_refund        DOUBLE      摊回分保费用
    other_bus_cost           DOUBLE      其他业务成本

    利润类：
    字段                     类型        说明
    ----------------------------------------------------------
    operate_profit           DOUBLE      营业利润
    non_oper_income          DOUBLE      营业外收入
    non_oper_exp             DOUBLE      营业外支出
    nca_disploss             DOUBLE      非流动资产处置净损失
    total_profit             DOUBLE      利润总额
    income_tax               DOUBLE      所得税费用
    n_income                 DOUBLE      净利润
    n_income_attr_p          DOUBLE      归母净利润
    minority_gain            DOUBLE      少数股东损益
    oth_compr_income         DOUBLE      其他综合收益
    t_compr_income           DOUBLE      综合收益总额
    compr_inc_attr_p         DOUBLE      归母综合收益
    compr_inc_attr_m_s       DOUBLE      归少数股东综合收益
    ebit                     DOUBLE      息税前利润
    ebitda                   DOUBLE      息税折旧摊销前利润

    其他财务指标：
    字段                     类型        说明
    ----------------------------------------------------------
    insurance_exp            DOUBLE      保险业务支出
    undist_profit            DOUBLE      未分配利润
    distable_profit          DOUBLE      可供分配利润
    rd_exp                   DOUBLE      研发费用
    fin_exp_int_exp          DOUBLE      财务费用:利息费用
    fin_exp_int_inc          DOUBLE      财务费用:利息收入
    transfer_surplus_rese    DOUBLE      盈余公积转入
    transfer_housing_imprest DOUBLE      住房公积金转入
    transfer_oth             DOUBLE      其他转入
    adj_lossgain             DOUBLE      调整净损益
    withdra_legal_surplus    DOUBLE      提取法定盈余公积
    withdra_legal_pubfund    DOUBLE      提取法定公益金
    withdra_biz_devfund      DOUBLE      提取企业发展基金
    withdra_rese_fund        DOUBLE      提取储备基金
    withdra_oth_ersu         DOUBLE      提取其他盈余公积
    workers_welfare          DOUBLE      职工福利及奖励基金
    distr_profit_shrhder     DOUBLE      分配股东利润
    prfshare_payable_dvd     DOUBLE      应付优先股股利
    comshare_payable_dvd     DOUBLE      应付普通股股利
    capit_comstock_div       DOUBLE      转作股本的普通股股利
    continued_net_profit     DOUBLE      持续经营净利润


5.4 balancesheet_view — 资产负债表

    DuckDB 视图：balancesheet_view
    数据来源：balancesheet/*.parquet（按季度分区）
    主键：(ts_code, end_date)
    分区方式：按季度截止日（YYYYMMDD.parquet）
    API 接口：balancesheet_vip
    总计 70 列（7 个分类列 + 63 个数值列）

    分类字段：
    字段          类型        说明
    ----------------------------------------------------------
    ts_code       VARCHAR     股票代码
    ann_date      VARCHAR     公告日期
    f_ann_date    VARCHAR     实际公告日期
    end_date      VARCHAR     报告期截止日（季度末）
    report_type   VARCHAR     报告类型（1=合并报表 2=单季报表）
    comp_type     VARCHAR     公司类型（1=一般工商业 2=银行 3=保险 4=证券）
    end_type      VARCHAR     期末类型（1=年报 2=半年报 3=一季报 4=三季报）
    update_flag   VARCHAR     更新标识

    总项指标：
    字段                     类型        说明
    ----------------------------------------------------------
    total_hldr_eqy_exc_min_int DOUBLE    股东权益（不含少数股东权益）
    total_hldr_eqy_inc_min_int DOUBLE    股东权益（含少数股东权益）
    total_assets              DOUBLE      总资产
    total_cur_assets          DOUBLE      流动资产合计
    total_nca                 DOUBLE      非流动资产合计
    total_liab                DOUBLE      总负债
    total_cur_liab            DOUBLE      流动负债合计
    total_ncl                 DOUBLE      非流动负债合计

    流动资产明细：
    字段                     类型        说明
    ----------------------------------------------------------
    money_cap                 DOUBLE      货币资金
    trad_asset                DOUBLE      交易性金融资产
    notes_receiv              DOUBLE      应收票据
    accounts_receiv           DOUBLE      应收账款
    oth_receiv                DOUBLE      其他应收款
    prepayment                DOUBLE      预付款项
    div_receiv                DOUBLE      应收股利
    int_receiv                DOUBLE      应收利息
    inventories               DOUBLE      存货
    amor_exp                  DOUBLE      待摊费用
    nca_within_1y             DOUBLE      一年内到期的非流动资产
    sett_rsrv                 DOUBLE      结算备付金
    loanto_oth_bank_fi        DOUBLE      拆出资金
    premium_receiv            DOUBLE      应收保费
    reinsur_receiv            DOUBLE      应收分保账款
    reinsur_cont_res          DOUBLE      应收分保合同准备金
    redem_meas_inv            DOUBLE      买入返售金融资产
    oth_cur_assets            DOUBLE      其他流动资产

    非流动资产明细：
    字段                     类型        说明
    ----------------------------------------------------------
    nca                       DOUBLE      非流动资产（二级科目）
    fin_assets_avail_for_sale DOUBLE      可供出售金融资产
    htm_invest                DOUBLE      持有至到期投资
    long_equity_invest        DOUBLE      长期股权投资
    invest_real_estate        DOUBLE      投资性房地产
    time_deposits             DOUBLE      定期存款
    oth_assets                DOUBLE      其他资产
    lt_rec                    DOUBLE      长期应收款
    fix_assets                DOUBLE      固定资产
    cip                       DOUBLE      在建工程
    const_materials           DOUBLE      工程物资
    fixed_assets_disp         DOUBLE      固定资产清理
    intang_assets             DOUBLE      无形资产
    r_and_d_exp               DOUBLE      研发支出
    goodwill                  DOUBLE      商誉
    lt_amor_exp               DOUBLE      长期待摊费用
    defer_tax_assets          DOUBLE      递延所得税资产
    oth_nca                   DOUBLE      其他非流动资产

    流动负债明细：
    字段                     类型        说明
    ----------------------------------------------------------
    st_borrow                 DOUBLE      短期借款
    st_notes_payable          DOUBLE      应付短期债券（应付票据）
    accounts_payable          DOUBLE      应付账款
    adv_pepmts                DOUBLE      预收款项
    int_payable               DOUBLE      应付利息
    div_payable               DOUBLE      应付股利
    oth_payable               DOUBLE      其他应付款
    accrued_exp               DOUBLE      预提费用
    deferred_inc              DOUBLE      递延收益
    lt_borr_due_within_1y     DOUBLE      一年内到期的非流动负债
    sett_rsrv_payable         DOUBLE      应付结算备付金
    deposit_received          DOUBLE      吸收存款
    trad_liab                 DOUBLE      交易性金融负债
    notes_payable             DOUBLE      应付票据
    oth_cur_liab              DOUBLE      其他流动负债

    非流动负债明细：
    字段                     类型        说明
    ----------------------------------------------------------
    lt_borrow                 DOUBLE      长期借款
    lt_notes_payable          DOUBLE      应付长期债券
    bonds_payable             DOUBLE      应付债券
    lt_payable                DOUBLE      长期应付款
    specific_item_payable     DOUBLE      专项应付款
    long_deferred_inc         DOUBLE      长期递延收益
    defer_tax_liab            DOUBLE      递延所得税负债
    oth_ncl                   DOUBLE      其他非流动负债

    权益明细：
    字段                     类型        说明
    ----------------------------------------------------------
    cap_rese                  DOUBLE      资本公积
    surplus_rese              DOUBLE      盈余公积
    undistort_profit          DOUBLE      未分配利润
    minority_int              DOUBLE      少数股东权益


5.5 cashflow_view — 现金流量表

    DuckDB 视图：cashflow_view
    数据来源：cashflow/*.parquet（按季度分区）
    主键：(ts_code, end_date)
    分区方式：按季度截止日（YYYYMMDD.parquet）
    API 接口：cashflow_vip
    总计 76 列（7 个分类列 + 69 个数值列）

    分类字段：
    字段          类型        说明
    ----------------------------------------------------------
    ts_code       VARCHAR     股票代码
    ann_date      VARCHAR     公告日期
    f_ann_date    VARCHAR     实际公告日期
    end_date      VARCHAR     报告期截止日（季度末）
    report_type   VARCHAR     报告类型（1=合并报表 2=单季报表）
    comp_type     VARCHAR     公司类型（1=一般工商业 2=银行 3=保险 4=证券）
    end_type      VARCHAR     期末类型（1=年报 2=半年报 3=一季报 4=三季报）
    update_flag   VARCHAR     更新标识

    经营活动现金流（流入）：
    字段                     类型        说明
    ----------------------------------------------------------
    net_profit                DOUBLE      净利润
    finan_exp                 DOUBLE      财务费用
    c_fr_sale_sg              DOUBLE      销售商品、提供劳务收到的现金
    recp_tax_rends            DOUBLE      收到的税费返还
    n_depos_incr_fi           DOUBLE      客户存款和同业存放款项净增加额
    n_incr_loans_cb           DOUBLE      向中央银行借款净增加额
    n_incr_borr_oth_fi        DOUBLE      向其他金融机构拆入资金净增加额
    prem_fr_orig_contr        DOUBLE      收到原保险合同保费取得的现金
    n_incr_insured_dep        DOUBLE      保户储金及投资款净增加额
    n_reinsur_prem            DOUBLE      收到再保险业务现金净额
    n_incr_disp_tfa           DOUBLE      处置交易性金融资产净增加额
    ifc_cash_incr             DOUBLE      收取利息、手续费及佣金的现金
    n_incr_disp_faas          DOUBLE      处置可供出售金融资产净增加额
    n_incr_loans_oth_bank     DOUBLE      拆入资金净增加额
    n_cap_incr_repur          DOUBLE      回购业务资金净增加额
    c_fr_oth_operate_a        DOUBLE      收到的其他与经营活动有关的现金
    c_inf_fr_operate_a        DOUBLE      经营活动现金流入小计

    经营活动现金流（流出）：
    字段                     类型        说明
    ----------------------------------------------------------
    c_paid_goods_s            DOUBLE      购买商品、接受劳务支付的现金
    c_paid_to_for_empl        DOUBLE      支付给职工以及为职工支付的现金
    c_paid_for_taxes          DOUBLE      支付的各项税费
    n_incr_clt_adv            DOUBLE      客户贷款及垫款净增加额
    n_incr_dep_cbob           DOUBLE      存放央行和同业款项净增加额
    c_pay_claims_orig_inco    DOUBLE      支付原保险合同赔付款项的现金
    pay_handling_chrg         DOUBLE      支付手续费及佣金的现金
    pay_comm_insur_plcy       DOUBLE      支付保单红利的现金
    oth_cash_pay_oper_act     DOUBLE      支付其他与经营活动有关的现金
    st_cash_out_act           DOUBLE      经营活动现金流出小计
    n_cashflow_act            DOUBLE      经营活动产生的现金流量净额

    投资活动现金流：
    字段                     类型        说明
    ----------------------------------------------------------
    oth_recp_ral_inv_act      DOUBLE      收到其他与投资活动有关的现金
    c_disp_withdrwl_oth       DOUBLE      收回投资所收到的现金
    c_recp_return_equit       DOUBLE      取得投资收益所收到的现金
    n_recp_disp_fiolta        DOUBLE      处置固定资产、无形资产和其他长期资产收回的现金净额
    stot_inflows_inv_act      DOUBLE      投资活动现金流入小计
    c_pay_acq_const_fiolta    DOUBLE      购建固定资产、无形资产和其他长期资产支付的现金
    c_paid_invest             DOUBLE      投资支付的现金
    n_disp_subs_oth_biz       DOUBLE      取得子公司及其他营业单位支付的现金净额
    oth_pay_ral_inv_act       DOUBLE      支付其他与投资活动有关的现金
    n_incr_pledge_loan        DOUBLE      质押贷款净增加额
    stot_out_inv_act          DOUBLE      投资活动现金流出小计
    n_cashflow_inv_act        DOUBLE      投资活动产生的现金流量净额

    筹资活动现金流：
    字段                     类型        说明
    ----------------------------------------------------------
    c_recp_borrow             DOUBLE      取得借款收到的现金
    proc_issue_bonds          DOUBLE      发行债券收到的现金
    oth_cash_recp_ral_fnc_act DOUBLE     收到其他与筹资活动有关的现金
    stot_cash_in_fnc_act      DOUBLE      筹资活动现金流入小计
    free_cashflow             DOUBLE      企业自由现金流量
    c_prepay_amt_borr         DOUBLE      偿还债务支付的现金
    c_pay_dist_dpcp_int_exp   DOUBLE      分配股利、利润或偿付利息支付的现金
    incl_dvd_profit_paid_sc_ms DOUBLE    子公司支付给少数股东的股利、利润
    oth_cashpay_ral_fnc_act   DOUBLE      支付其他与筹资活动有关的现金
    stot_cashout_fnc_act      DOUBLE      筹资活动现金流出小计
    n_cash_flows_fnc_act      DOUBLE      筹资活动产生的现金流量净额

    现金及调节项：
    字段                     类型        说明
    ----------------------------------------------------------
    eff_fx_flu_cash           DOUBLE      汇率变动对现金及现金等价物的影响
    n_incr_cash_cash_equ      DOUBLE      现金及现金等价物净增加额
    c_cash_equ_beg_period     DOUBLE      期初现金及现金等价物余额
    c_cash_equ_end_period     DOUBLE      期末现金及现金等价物余额
    c_recp_cap_contrib        DOUBLE      吸收投资收到的现金
    incl_cash_rec_saims       DOUBLE      其中:子公司吸收少数股东投资收到的现金
    unpaid_invest             DOUBLE      未付投资款
    prov_depr_assets          DOUBLE      资产减值准备
    depr_fa_coga_dpba         DOUBLE      固定资产折旧、油气资产折耗、生产性物资折旧
    amort_intang_assets       DOUBLE      无形资产摊销
    lt_amort_deferred_exp     DOUBLE      长期待摊费用摊销
    defer_tax_less_assets     DOUBLE      递延所得税资产减少
    defer_tax_less_liab       DOUBLE      递延所得税负债增加
    loss_disp_fiolta          DOUBLE      处置固定、无形资产和其他长期资产的损失
    loss_scr_fa               DOUBLE      固定资产报废损失
    loss_fv_chg               DOUBLE      公允价值变动损失
    invest_loss               DOUBLE      投资损失
    decr_def_inc_tax_assets   DOUBLE      递延所得税资产减少
    incr_def_inc_tax_liab     DOUBLE      递延所得税负债增加
    decr_inventories          DOUBLE      存货的减少
    decr_oper_payable         DOUBLE      经营性应收项目的减少
    incr_oper_payable         DOUBLE      经营性应付项目的增加
    others                    DOUBLE      其他
    im_net_cashflow_oper_act  DOUBLE      经营活动产生的现金流量净额（间接法）
    conv_debt_into_cap        DOUBLE      债务转为资本
    conv_cop_debt_due_1y      DOUBLE      一年内到期的可转换公司债券
    fa_fnc_leases             DOUBLE      融资租入固定资产
    end_bal_cash              DOUBLE      现金的期末余额
    less_beg_bal_cash         DOUBLE      减：现金的期初余额
    plus_end_bal_cash_equ     DOUBLE      加：现金等价物的期末余额
    less_beg_bal_cash_equ     DOUBLE      减：现金等价物的期初余额
    im_n_incr_cash_equ        DOUBLE      现金及现金等价物净增加额（间接法）


5.6 trade_calendar_view — 交易日历

    DuckDB 视图：trade_calendar_view
    数据来源：trade_calendar/*.parquet（按年份分区 YYYY.parquet）
    主键：(exchange, cal_date)

    字段          类型        说明
    ----------------------------------------------------------
    exchange       VARCHAR     交易所（SSE/SZSE/BSE）
    cal_date       VARCHAR     日历日期 YYYYMMDD
    is_open        INTEGER     是否交易日（1=是 0=否）
    pretrade_date  VARCHAR     上一个交易日


5.7 st_stocks_view — ST 股票列表

    DuckDB 视图：st_stocks_view
    数据来源：st_stocks.parquet（单文件）
    主键：ts_code

    字段          类型        说明
    ----------------------------------------------------------
    ts_code       VARCHAR     股票代码
    symbol        VARCHAR     股票简称
    name          VARCHAR     股票名称
    st_type       VARCHAR     ST 类型（ST 或 *ST）
    industry      VARCHAR     行业
    list_date     VARCHAR     上市日期


六、日志
--------------------------------------------------------------------------------

日志同时输出到终端和文件。日志文件位于 logs/app.log，采用滚动策略：
  - 单个日志文件最大 10MB
  - 保留最近 5 个备份（app.log.1 ~ app.log.5）
  - 时间戳精度为微秒

日志级别：INFO（默认），可在 utils/logger.py 中修改 level 参数。


七、常见问题
--------------------------------------------------------------------------------

Q1: 提示 "TUSHARE_TOKEN not set" 怎么办？
A1: 检查 .env 文件是否存在且 TUSHARE_TOKEN 已正确填写。确保 .env 文件
    与 main.py 在同一目录下。

Q2: fetch 或 init 命令返回空数据？
A2: 可能原因：
    - Tushare token 积分不足，无权访问该接口
      （income_vip / balancesheet_vip / cashflow_vip 需要较高积分）
    - 日期范围内无交易日（如周末/节假日）
    - 网络连接问题（系统会自动重试 3 次）
    检查 logs/app.log 查看详细错误信息。

Q3: init 命令执行时间很长？
A3: 正常现象。全量拉取 15 年的日线数据需要逐日调用 API（每年约 250 个
    交易日），总计约 3750+ 次 API 调用。加上 61 个季度的三大财务报表
    数据，总计耗时约 30-60 分钟。建议先使用 --data-type 参数按数据类型
    分批初始化。

Q4: 如何获取更多 Tushare 字段？
A4: 编辑 data/fetcher.py 中对应 fetch 方法的 fields 参数，添加需要的
    字段名（需确保你的 Tushare 积分等级支持该字段）。
    同时需要在 data/storage.py 的 _COLUMN_TYPES 字典中注册新字段的类型。

Q5: DuckDB 视图查询报错？
A5: 确保 data_files/ 目录下的 Parquet 文件未被手动删除或移动。运行
    python main.py stats 检查数据完整性。

Q6: 如何更新到最新交易日数据？
A6: 执行 python main.py update 即可增量拉取最新的交易日数据。
    系统会自动比对本地已有数据，仅拉取缺失的交易日。

Q7: balancesheet_view 或 cashflow_view 查询报错 "does not exist"？
A7: 需要先初始化对应数据：
    python main.py init --data-type balancesheet
    python main.py init --data-type cashflow
    这两个表与 income 一样使用 VIP 接口，需要较高 Tushare 积分等级。

Q8: 导出的 CSV 中数值列变成了字符串？
A8: 这是设计行为。大数值（如总资产 244164100000）在 Excel 中会触发
    INT32 溢出。导出时自动将数值转为字符串以避免此问题。如需保留数值
    类型，请使用 parquet 格式导出。

Q9: 定时任务（cron）执行时日志为空？
A9: cron 环境变量与交互式 shell 不同。确保 crontab 中 cd 到正确的
    工作目录，使 .env 能被 python-dotenv 正确加载。


八、项目文件结构
--------------------------------------------------------------------------------

  twpony/
  ├── main.py                  ← 主入口（CLI 命令行解析与命令分发，~1000 行）
  ├── requirements.txt         ← Python 依赖清单
  ├── .env                     ← 环境变量配置（需自行创建）
  ├── .env.example             ← 环境变量模板
  ├── readme.txt               ← 本说明书
  ├── stock_list.csv           ← 股票列表（CSV 快照）
  ├── stock_basic.csv          ← 股票基本信息（CSV 快照）
  ├── st_stocks.csv            ← ST 股票列表（CSV 快照）
  ├── trade_calendar.csv       ← 交易日历（CSV 快照）
  ├── income_20260331.csv      ← 利润表 CSV 样本
  ├── balancesheet_20260331.csv ← 资产负债表 CSV 样本
  ├── cashflow_20260331.csv    ← 现金流量表 CSV 样本
  ├── out_daily.out            ← 日线输出样本
  │
  ├── config/                  ← 配置模块
  │   ├── __init__.py
  │   └── settings.py          ← 全局配置（读取 .env 环境变量，管理各路径，
  │                               DataClass 单例模式，含 manifest/data 目录/
  │                               DuckDB 路径等属性）
  │
  ├── data/                    ← 数据层模块
  │   ├── __init__.py
  │   ├── fetcher.py           ← Tushare API 数据拉取
  │   │                          封装了以下 API：
  │   │                          - daily (日线 OHLCV)
  │   │                          - stock_basic (股票基本信息)
  │   │                          - income / income_vip (利润表)
  │   │                          - balancesheet_vip (资产负债表)
  │   │                          - cashflow_vip (现金流量表)
  │   │                          - trade_cal / trade_calendar (交易日历)
  │   │                          - fetch_st_stocks (ST 股票筛选)
  │   │                          含自动重试机制（默认 3 次，指数退避）
  │   │
  │   ├── storage.py           ← DuckDB + Parquet 存储层
  │   │                          功能：
  │   │                          - 按日期/年份分区写入 Parquet 文件
  │   │                          - Upsert 合并（按主键去重，保留最新）
  │   │                          - DuckDB 视图自动注册（7 个视图）
  │   │                          - manifest.json 自动维护
  │   │                          - 读接口（支持 ts_code/日期范围过滤）
  │   │                          - 定义了所有表的主键 (_PRIMARY_KEYS)
  │   │                          - 定义了所有列的 DuckDB 类型 (_COLUMN_TYPES)
  │   │
  │   └── updater.py           ← 增量/全量更新编排逻辑
  │                              功能：
  │                              - update_incremental() — 增量更新全部类型
  │                              - update_full() — 全量刷新全部类型
  │                              - 各类型独立的增量/全量更新方法
  │                              - 季度计算工具函数（_get_quarter_end 等）
  │                              - 交易日历辅助（判断最近交易日）
  │
  ├── query/                   ← 查询引擎模块
  │   ├── __init__.py
  │   └── engine.py            ← 查询引擎（高层查询接口）
  │                              预设查询方法：
  │                              【日线】get_daily, get_daily_latest,
  │                                top_volume, price_change_rank,
  │                                sector_performance, trading_dates
  │                              【股票】get_stock_info, search_stock,
  │                                industry_stocks, filter_stocks_by_market
  │                              【利润表】get_income, roe_rank, income_summary
  │                              【资产负债表】get_balancesheet,
  │                                balancesheet_summary, asset_rank
  │                              【现金流量表】get_cashflow, cashflow_summary
  │                              【交易日历】get_trade_calendar, is_trading_day,
  │                                next_trading_day, trading_days_count
  │                              【ST】get_st_stocks, get_st_stocks_by_type
  │                              【通用】raw_sql, get_schemas, record_counts
  │
  ├── utils/                   ← 工具模块
  │   ├── __init__.py
  │   ├── logger.py            ← 日志配置
  │   │                          - 终端 + 文件双输出
  │   │                          - 微秒精度时间戳 (MicrosecondFormatter)
  │   │                          - 滚动日志（10MB × 5 个备份）
  │   │
  │   └── csv_io.py            ← CSV 读写工具
  │                              - 统一编码（UTF-8 BOM）
  │                              - 自动编码检测（UTF-8 → GBK → Latin-1）
  │                              - 格式化的读写日志
  │
  ├── test/                    ← 测试模块
  │   ├── test_query.py        ← 数据库查询测试（unittest）
  │   │                          测试类：
  │   │                          - TestDBConnection: 连接/路径/行数/模式
  │   │                          - TestDBQuery: 各视图查询 + 导出 CSV/JSON
  │   │                          - TestRawSQL: 原始 SQL + JOIN 查询
  │   │                          - TestExportFormats: CSV/JSON 导出验证
  │   │
  │   ├── test_cmp.py          ← 数据对比工具（Tushare vs 东方财富）
  │   ├── temp/                ← 测试临时文件
  │   └── output/              ← 测试输出目录
  │
  ├── data_files/              ← 数据存储目录（可通过 .env 配置路径）
  │   ├── README.md            ← 数据存储结构说明
  │   ├── manifest.json        ← 自动生成的数据清单
  │   │                          （含各表行数、文件数、分区策略、日期范围）
  │   ├── quant.duckdb         ← DuckDB 数据库文件
  │   ├── daily/               ← 日线 Parquet 文件（按交易日：20260601.parquet）
  │   │                          ~3,641 个文件
  │   ├── income/              ← 利润表 Parquet 文件（按季度：20260331.parquet）
  │   │                         ~61 个文件
  │   ├── balancesheet/        ← 资产负债表 Parquet 文件（按季度）
  │   │                         ~61 个文件
  │   ├── cashflow/            ← 现金流量表 Parquet 文件（按季度）
  │   │                         ~61 个文件
  │   ├── trade_calendar/      ← 交易日历 Parquet 文件（按年份：2026.parquet）
  │   │                         ~16 个文件
  │   ├── stock_basic.parquet  ← 股票基本信息（单文件）
  │   ├── stock_list.parquet   ← 股票列表精简版（单文件）
  │   └── st_stocks.parquet    ← ST 股票列表（单文件）
  │
  └── logs/
      └── app.log              ← 应用日志（含滚动备份 app.log.1 ~ app.log.5）


九、数据分区策略与主键汇总
--------------------------------------------------------------------------------

  数据类型           分区方式              分区键          主键
  ------------------------------------------------------------------------------
  daily              按交易日（每日一个）    trade_date      (ts_code, trade_date)
  stock_basic        单文件全量             -               ts_code
  income             按季度                 end_date        (ts_code, end_date)
  balancesheet       按季度                 end_date        (ts_code, end_date)
  cashflow           按季度                 end_date        (ts_code, end_date)
  trade_calendar     按年份                 cal_date[:4]    (exchange, cal_date)
  st_stocks          单文件全量             -               ts_code


十、DuckDB 视图与可用 SQL 示例
--------------------------------------------------------------------------------

  视图名              数据来源                    可 JOIN 键
  ------------------------------------------------------------------------------
  daily_view          daily/*.parquet              ts_code
  stock_basic_view    stock_basic.parquet          ts_code
  income_view         income/*.parquet             ts_code
  balancesheet_view   balancesheet/*.parquet       ts_code
  cashflow_view       cashflow/*.parquet           ts_code
  trade_calendar_view trade_calendar/*.parquet     exchange
  st_stocks_view      st_stocks.parquet            ts_code

  SQL 示例：

  -- 查询某股票全部日线数据
  SELECT * FROM daily_view WHERE ts_code='000001.SZ'
  ORDER BY trade_date DESC LIMIT 10;

  -- 某日成交额 Top-10（关联股票名称）
  SELECT d.ts_code, s.name, d.close, d.pct_chg, d.amount
  FROM daily_view d
  LEFT JOIN stock_basic_view s ON d.ts_code = s.ts_code
  WHERE d.trade_date = '20260605'
  ORDER BY d.amount DESC LIMIT 10;

  -- 某行业区间涨跌幅
  SELECT d.ts_code, s.name,
         ROUND((MAX(CASE WHEN d.trade_date='20260605' THEN d.close END)
              - MAX(CASE WHEN d.trade_date='20260601' THEN d.close END))
              / MAX(CASE WHEN d.trade_date='20260601' THEN d.close END) * 100, 2)
         AS cum_return_pct
  FROM daily_view d
  JOIN stock_basic_view s ON d.ts_code = s.ts_code
  WHERE d.trade_date IN ('20260601', '20260605') AND s.industry = '银行'
  GROUP BY d.ts_code, s.name
  ORDER BY cum_return_pct DESC;

  -- 最新季度总资产 Top-10
  WITH latest AS (
      SELECT ts_code, MAX(end_date) AS max_end_date
      FROM balancesheet_view WHERE end_date <= '20260331' GROUP BY ts_code
  )
  SELECT b.ts_code, s.name, b.total_assets, b.total_liab,
         ROUND(b.total_liab / NULLIF(b.total_assets, 0) * 100, 2) AS debt_ratio_pct
  FROM balancesheet_view b
  JOIN latest l ON b.ts_code = l.ts_code AND b.end_date = l.max_end_date
  LEFT JOIN stock_basic_view s ON b.ts_code = s.ts_code
  WHERE b.total_assets IS NOT NULL
  ORDER BY b.total_assets DESC LIMIT 10;

  -- 净利润与经营现金流对比（筛选"利润有现金支撑"的公司）
  SELECT f.ts_code, s.name, f.end_date,
         ROUND(f.n_income_attr_p / 10000.0, 2) AS net_profit_yi,
         ROUND(c.n_cashflow_act / 10000.0, 2) AS oper_cashflow_yi
  FROM income_view f
  JOIN cashflow_view c ON f.ts_code = c.ts_code AND f.end_date = c.end_date
  LEFT JOIN stock_basic_view s ON f.ts_code = s.ts_code
  WHERE f.end_date = '20260331'
    AND f.n_income_attr_p > 0 AND c.n_cashflow_act > 0
  ORDER BY f.n_income_attr_p DESC LIMIT 20;

  -- 交易日查询
  SELECT * FROM trade_calendar_view
  WHERE cal_date BETWEEN '20260601' AND '20260605'
    AND exchange = 'SSE' ORDER BY cal_date;


十一、许可与数据来源
--------------------------------------------------------------------------------

本工具使用 Tushare Pro (https://tushare.pro) 作为数据源。
使用前请注册 Tushare 账号并获取 API Token。
Tushare 数据仅供学习和研究使用，请遵守 Tushare 用户协议。

技术栈开源许可：
  - DuckDB: MIT License
  - Pandas: BSD 3-Clause
  - PyArrow: Apache 2.0
  - python-dotenv: BSD

================================================================================
                              文档版本: 2.0
                              更新日期: 2026-06-08
================================================================================
