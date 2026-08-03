#!/usr/bin/env python3
"""Quant data acquisition & query system — comprehensive CLI.

Usage examples::

    # ---- Fetch (direct Tushare API calls, no storage) ----
    python main.py fetch daily  --ts-code 000001.SZ
    python main.py fetch daily  --ts-code 000001.SZ --start 20260101 --end 20260605
    python main.py fetch stock-basic  --exchange SSE
    python main.py fetch index-weight --index-code 000300.SH
    python main.py fetch index-weight --index-code 000905.SH --start 20240101 --end 20240630
    python main.py fetch index-daily --index-code 000300.SH
    python main.py fetch index-daily --index-code 000852.SH --start 20240101 --end 20260630
    python main.py fetch income --ts-code 000001.SZ
    python main.py fetch balancesheet --ts-code 000001.SZ
    python main.py fetch cashflow --ts-code 000001.SZ

    # ---- Init (full historical pull → storage) ----
    python main.py init
    python main.py init --data-type daily
    python main.py init --data-type stock_basic

    # ---- Update (incremental or full) ----
    python main.py update
    python main.py update --full
    python main.py update --data-type daily         # last 5 trading days by default
    python main.py update --data-type daily -d 10   # last 10 trading days
    python main.py update --data-type income

    # ---- Query ----
    python main.py query                              # interactive REPL
    python main.py query --sql "SELECT * FROM daily_view LIMIT 5"

    # ---- Export ----
    python main.py export --table daily --ts-code 000001.SZ --format csv --output /tmp/daily.csv
    python main.py export --table income --period 20260331 --format csv --output /tmp/income.csv
    python main.py export --table income --period 20260331 --ts-code 000001.SZ --format csv --output /tmp/income.csv
    python main.py export --table balancesheet --period 20260331 --format csv --output /tmp/balance.csv
    python main.py export --table cashflow --period 20260331 --format csv --output /tmp/cashflow.csv

    # ---- Info ----
    python main.py stats
    python main.py schema
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Callable

import pandas as pd

from utils.logger import log


# ======================================================================
# Entry point
# ======================================================================

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    func: Callable = args.func
    func(args)


# ======================================================================
# CLI tree builder
# ======================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant",
        description=(
            "Quant data acquisition & query system "
            "(Tushare + DuckDB + Parquet)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")
    sub.required = False

    _add_fetch_parsers(sub)
    _add_init_parser(sub)
    _add_update_parser(sub)
    _add_query_parser(sub)
    _add_export_parser(sub)
    _add_info_parsers(sub)

    return parser


# ======================================================================
# Sub-parser builders
# ======================================================================

def _add_fetch_parsers(sub: argparse._SubParsersAction) -> None:
    """``fetch`` group — direct Tushare API calls, no storage."""
    fetch = sub.add_parser(
        "fetch",
        help="Fetch data directly from Tushare (no storage)",
    )
    fetch_sub = fetch.add_subparsers(dest="fetch_command", help="Data type")
    fetch_sub.required = True

    # fetch daily
    fd = fetch_sub.add_parser("daily", help="Fetch daily OHLCV data")
    fd.add_argument("--ts-code", type=str, default=None,
                    help="Stock code e.g. 000001.SZ (omit for all)")
    fd.add_argument("--start", type=str, default=None,
                    help="Start date YYYYMMDD (default: 1 year ago)")
    fd.add_argument("--end", type=str, default=None,
                    help="End date YYYYMMDD (default: today)")
    fd.add_argument("--output", "-o", type=str, default=None,
                    help="Save to file (.csv or .parquet)")
    fd.set_defaults(func=cmd_fetch_daily)

    # fetch stock-basic
    fb = fetch_sub.add_parser("stock-basic", help="Fetch stock basic info")
    fb.add_argument("--exchange", type=str, default="",
                    choices=["", "SSE", "SZSE", "BSE"],
                    help="Exchange filter (default: all)")
    fb.add_argument("--output", "-o", type=str, default=None,
                    help="Save to file (.csv or .parquet)")
    fb.set_defaults(func=cmd_fetch_basic)

    # fetch income
    fi = fetch_sub.add_parser("income", help="Fetch income statement data")
    fi.add_argument("--ts-code", type=str, default=None,
                    help="Stock code e.g. 000001.SZ (omit for all)")
    fi.add_argument("--period", type=str, default=None,
                    help="Reporting period end date YYYYMMDD (quarter end)")
    fi.add_argument("--output", "-o", type=str, default=None,
                    help="Save to file (.csv or .parquet)")
    fi.set_defaults(func=cmd_fetch_income)

    # fetch balancesheet
    fbs = fetch_sub.add_parser("balancesheet", help="Fetch balance sheet data")
    fbs.add_argument("--ts-code", type=str, default=None,
                     help="Stock code e.g. 000001.SZ (omit for all)")
    fbs.add_argument("--period", type=str, default=None,
                     help="Reporting period end date YYYYMMDD (quarter end)")
    fbs.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    fbs.set_defaults(func=cmd_fetch_balancesheet)

    # fetch cashflow
    fcf = fetch_sub.add_parser("cashflow", help="Fetch cashflow statement data")
    fcf.add_argument("--ts-code", type=str, default=None,
                     help="Stock code e.g. 000001.SZ (omit for all)")
    fcf.add_argument("--period", type=str, default=None,
                     help="Reporting period end date YYYYMMDD (quarter end)")
    fcf.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    fcf.set_defaults(func=cmd_fetch_cashflow)

    # fetch trade-cal
    ftc = fetch_sub.add_parser("trade-cal", help="Fetch trading calendar")
    ftc.add_argument("--start", type=str, default=None,
                     help="Start date YYYYMMDD (default: 15 years ago)")
    ftc.add_argument("--end", type=str, default=None,
                     help="End date YYYYMMDD (default: today)")
    ftc.add_argument("--exchange", type=str, default="",
                     choices=["", "SSE", "SZSE", "BSE"],
                     help="Exchange filter (default: all)")
    ftc.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    ftc.set_defaults(func=cmd_fetch_trade_calendar)

    # fetch st-stocks
    fst = fetch_sub.add_parser("st-stocks", help="Fetch current ST stock list")
    fst.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    fst.set_defaults(func=cmd_fetch_st_stocks)

    # fetch adj-factor
    fadj = fetch_sub.add_parser("adj-factor", help="Fetch adjustment factor (复权因子) data")
    fadj.add_argument("--ts-code", type=str, default=None,
                      help="Stock code e.g. 000001.SZ (omit for all)")
    fadj.add_argument("--start", type=str, default=None,
                      help="Start date YYYYMMDD (default: 15 years ago)")
    fadj.add_argument("--end", type=str, default=None,
                      help="End date YYYYMMDD (default: today)")
    fadj.add_argument("--output", "-o", type=str, default=None,
                      help="Save to file (.csv or .parquet)")
    fadj.set_defaults(func=cmd_fetch_adj_factor)

    # fetch moneyflow
    fmf = fetch_sub.add_parser("moneyflow", help="Fetch moneyflow (个股资金流向) data")
    fmf.add_argument("--ts-code", type=str, default=None,
                     help="Stock code e.g. 000001.SZ (omit for all)")
    fmf.add_argument("--trade-date", type=str, default=None,
                     help="Trading date YYYYMMDD (single date)")
    fmf.add_argument("--start", type=str, default=None,
                     help="Start date YYYYMMDD (default: 15 years ago)")
    fmf.add_argument("--end", type=str, default=None,
                     help="End date YYYYMMDD (default: today)")
    fmf.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    fmf.set_defaults(func=cmd_fetch_moneyflow)

    # fetch index-basic
    fib = fetch_sub.add_parser("index-basic", help="Fetch index basic info (指数基础信息)")
    fib.add_argument("--market", "-m", type=str, default="",
                     choices=["", "CSI", "SSE", "SZSE"],
                     help="Market filter (default: all — fetches CSI/SSE/SZSE separately)")
    fib.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    fib.set_defaults(func=cmd_fetch_index_basic)

    # fetch index-weight
    fiw = fetch_sub.add_parser("index-weight", help="Fetch index constituent weight data (指数成分权重)")
    fiw.add_argument("--index-code", "-i", type=str, required=True,
                     help="Index code e.g. 000300.SH, 000905.SH, 000852.SH, 932000.CSI")
    fiw.add_argument("--trade-date", type=str, default=None,
                     help="Single month-end date YYYYMMDD")
    fiw.add_argument("--start", type=str, default=None,
                     help="Start date YYYYMMDD")
    fiw.add_argument("--end", type=str, default=None,
                     help="End date YYYYMMDD")
    fiw.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    fiw.set_defaults(func=cmd_fetch_index_weight)

    # fetch index-daily
    fid = fetch_sub.add_parser("index-daily", help="Fetch index daily OHLCV data (指数日线行情)")
    fid.add_argument("--index-code", "-i", type=str, required=True,
                     help="Index code e.g. 000300.SH, 000905.SH, 000852.SH, 932000.CSI")
    fid.add_argument("--start", type=str, default=None,
                     help="Start date YYYYMMDD (default: 13 years ago)")
    fid.add_argument("--end", type=str, default=None,
                     help="End date YYYYMMDD (default: today)")
    fid.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    fid.set_defaults(func=cmd_fetch_index_daily)


def _add_init_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init", help="Full historical data pull → storage")
    p.add_argument(
        "--data-type", type=str, default="all",
        choices=["all", "daily", "stock_basic", "income", "cashflow",
                 "balancesheet", "trade_calendar", "st_stocks", "adjfactor",
                 "moneyflow", "index_basic", "index_weight", "index_daily"],
        help="Which data type to initialize (default: all)",
    )
    p.add_argument(
        "--ts-code", type=str, default=None,
        help="Limit to a single stock code (income/cashflow/balancesheet only; daily always fetches all)",
    )
    p.set_defaults(func=cmd_init)


def _add_update_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("update", help="Incremental or full data update")
    p.add_argument(
        "--full", action="store_true", default=False,
        help="Full refresh instead of incremental",
    )
    p.add_argument(
        "--data-type", type=str, default="all",
        choices=["all", "daily", "stock_basic", "income", "cashflow",
                 "balancesheet", "trade_calendar", "st_stocks", "adjfactor",
                 "moneyflow", "index_basic", "index_weight", "index_daily"],
        help="Which data type to update (default: all)",
    )
    p.add_argument(
        "--months", "-m", type=int, default=1,
        help="Number of months to look back for incremental update (default: 1; not used for daily when --days is specified)",
    )
    p.add_argument(
        "--days", "-d", type=int, default=5,
        help="Number of trading days to look back for daily update (default: 5; only used with --data-type daily)",
    )
    p.set_defaults(func=cmd_update)


def _add_query_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "query",
        help="Query data (interactive REPL, one-shot SQL, or named sub-commands)",
    )
    query_sub = p.add_subparsers(dest="query_command", help="Query type")
    query_sub.required = False

    # query --sql / interactive (default)
    p.add_argument("--sql", "-s", type=str, default=None,
                   help="SQL query to execute (omit for interactive mode)")
    p.set_defaults(func=cmd_query)

    # query index-weight
    qiw = query_sub.add_parser("index-weight", help="Query index constituent weights")
    qiw.add_argument("--index-code", "-i", type=str, default=None,
                     help="Index code e.g. 000300.SH")
    qiw.add_argument("--date", "-d", type=str, default=None,
                     help="Month-end date YYYYMMDD (default: latest)")
    qiw.add_argument("--con-code", "-c", type=str, default=None,
                     help="Search a constituent stock in all indices")
    qiw.add_argument("--top", "-n", type=int, default=None,
                     help="Show top N by weight")
    qiw.add_argument("--output", "-o", type=str, default=None,
                     help="Save to file (.csv or .parquet)")
    qiw.set_defaults(func=cmd_query_index_weight)


def _add_export_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("export", help="Export stored data to file")
    p.add_argument(
        "--table", "-t", type=str, required=True,
        choices=["daily", "stock_basic", "income", "cashflow",
                 "balancesheet", "trade_calendar", "st_stocks", "adjfactor",
                 "moneyflow", "index_basic", "index_weight", "index_daily"],
        help="Data table to export",
    )
    p.add_argument(
        "--format", "-f", type=str, default="csv",
        choices=["csv", "parquet", "json"],
        help="Output format (default: csv)",
    )
    p.add_argument(
        "--output", "-o", type=str, required=True,
        help="Output file path",
    )
    p.add_argument("--ts-code", type=str, default=None,
                   help="Optional stock filter")
    p.add_argument("--period", type=str, default=None,
                   help="Trading date YYYYMMDD (required for adjfactor) / Quarter end date YYYYMMDD (required for income/cashflow/balancesheet tables)")
    p.add_argument("--start", type=str, default=None,
                   help="Start date YYYYMMDD")
    p.add_argument("--end", type=str, default=None,
                   help="End date YYYYMMDD")
    p.set_defaults(func=cmd_export)


def _add_info_parsers(sub: argparse._SubParsersAction) -> None:
    p1 = sub.add_parser("stats", help="Show record counts per table")
    p1.set_defaults(func=cmd_stats)

    p2 = sub.add_parser("schema", help="Show table schemas")
    p2.set_defaults(func=cmd_schema)


# ======================================================================
# Command: fetch daily
# ======================================================================

def cmd_fetch_daily(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()
    df = fetcher.fetch_daily(
        ts_code=args.ts_code,
        start_date=args.start,
        end_date=args.end,
    )
    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, "daily")


# ======================================================================
# Command: fetch stock-basic
# ======================================================================

def cmd_fetch_basic(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()
    df = fetcher.fetch_stock_basic(exchange=args.exchange)
    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, "stock_basic")


# ======================================================================
# Command: fetch income
# ======================================================================

def cmd_fetch_income(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()

    # Use income_vip when ts_code is omitted so "all stocks" works.
    # The standard income API requires ts_code as a mandatory parameter.
    if args.ts_code:
        df = fetcher.fetch_income(
            ts_code=args.ts_code,
            period=args.period,
        )
    else:
        df = fetcher.fetch_income_vip(
            ts_code=None,
            period=args.period,
        )

    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, "income")


# ======================================================================
# Command: fetch balancesheet
# ======================================================================

def cmd_fetch_balancesheet(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()

    # balancesheet_vip supports ts_code=None (all stocks).
    df = fetcher.fetch_balancesheet_vip(
        ts_code=args.ts_code,
        period=args.period,
    )

    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, "balancesheet")


# ======================================================================
# Command: fetch cashflow
# ======================================================================

def cmd_fetch_cashflow(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()

    # cashflow_vip supports ts_code=None (all stocks).
    df = fetcher.fetch_cashflow_vip(
        ts_code=args.ts_code,
        period=args.period,
    )

    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, "cashflow")


# ======================================================================
# Command: fetch trade-cal
# ======================================================================

def cmd_fetch_trade_calendar(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()
    df = fetcher.fetch_trade_calendar(
        start_date=args.start,
        end_date=args.end,
        exchange=args.exchange,
    )
    if df.empty:
        print("No data returned.")
        sys.exit(1)
    _output_or_show(df, args.output, "trade_calendar")


# ======================================================================
# Command: fetch st-stocks
# ======================================================================

def cmd_fetch_st_stocks(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()
    df = fetcher.fetch_st_stocks()
    if df.empty:
        print("No ST stocks found.")
        sys.exit(1)
    _output_or_show(df, args.output, "st_stocks")


# ======================================================================
# Command: fetch adj-factor
# ======================================================================

def cmd_fetch_adj_factor(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()
    df = fetcher.fetch_adj_factor(
        ts_code=args.ts_code,
        start_date=args.start,
        end_date=args.end,
    )
    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, "adjfactor")


# ======================================================================
# Command: fetch moneyflow
# ======================================================================

def cmd_fetch_moneyflow(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()
    df = fetcher.fetch_moneyflow(
        ts_code=args.ts_code,
        trade_date=args.trade_date,
        start_date=args.start,
        end_date=args.end,
    )
    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, "moneyflow")


# ======================================================================
# Command: fetch index-basic
# ======================================================================

def cmd_fetch_index_basic(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()

    if args.market:
        df = fetcher.fetch_index_basic(market=args.market)
        if df.empty:
            print(f"No index basic data for market={args.market}")
            sys.exit(1)
        _output_or_show(df, args.output, f"index_basic/{args.market}")
    else:
        # Fetch all three markets
        dfs: list[pd.DataFrame] = []
        for market in ("CSI", "SSE", "SZSE"):
            df = fetcher.fetch_index_basic(market=market)
            if not df.empty:
                dfs.append(df)
                print(f"  {market}: {len(df)} indices")
            else:
                print(f"  {market}: (empty)")
        if not dfs:
            print("No index basic data returned for any market.")
            sys.exit(1)
        combined = pd.concat(dfs, ignore_index=True)
        _output_or_show(combined, args.output, "index_basic")


# ======================================================================
# Command: fetch index-weight
# ======================================================================

def cmd_fetch_index_weight(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()
    df = fetcher.fetch_index_weight(
        index_code=args.index_code,
        trade_date=args.trade_date,
        start_date=args.start,
        end_date=args.end,
    )
    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, f"index_weight/{args.index_code}")


# ======================================================================
# Command: fetch index-daily
# ======================================================================

def cmd_fetch_index_daily(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher

    fetcher = TushareDataFetcher()
    df = fetcher.fetch_index_daily(
        ts_code=args.index_code,
        start_date=args.start,
        end_date=args.end,
    )
    if df.empty:
        print("No data returned.")
        sys.exit(1)

    _output_or_show(df, args.output, f"index_daily/{args.index_code}")


# ======================================================================
# Command: query index-weight
# ======================================================================

def cmd_query_index_weight(args: argparse.Namespace) -> None:
    from query.engine import QueryEngine

    engine = QueryEngine()

    try:
        if args.con_code:
            # Search a stock across all indices
            df = engine.search_constituent(args.con_code)
            if args.index_code:
                df = df[df["index_code"] == args.index_code]
            label = f"index_weight/con={args.con_code}"
        elif args.index_code:
            if args.date:
                df = engine.get_index_weight(args.index_code, args.date)
            else:
                df = engine.index_weight_latest(args.index_code)
            label = f"index_weight/{args.index_code}"
        else:
            # Summary of all indices, latest date each
            df = engine.index_weight_summary()
            label = "index_weight/summary"

        if args.top and len(df) > args.top:
            df = df.head(args.top)

        if df.empty:
            print("No data matched.")
            return

        _output_or_show(df, args.output, label)
    finally:
        engine.close()


# ======================================================================
# Command: init
# ======================================================================

def cmd_init(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher
    from data.storage import DataStorage
    from data.updater import DailyUpdater

    data_type = args.data_type
    log.info("=== INIT (data_type=%s) ===", data_type)

    try:
        fetcher = TushareDataFetcher()
        storage = DataStorage()
        updater = DailyUpdater(fetcher, storage)

        results: dict[str, int] = {}

        if data_type in ("all", "stock_basic"):
            df = fetcher.fetch_stock_basic()
            results["stock_basic"] = storage.save_stock_basic(df)

        if data_type in ("all", "daily"):
            # Use updater's batched refresh — loops by month via trade calendar
            results["daily"] = updater._update_daily_full()

        if data_type in ("all", "income"):
            # Use income quarter-by-quarter for all stocks.
            log.info("Initialising income data via income (all quarters)...")
            results["income"] = updater._update_income_full()

        if data_type in ("all", "balancesheet"):
            log.info(
                "Initialising balance sheet data via balancesheet_vip (all quarters)..."
            )
            results["balancesheet"] = updater._update_balancesheet_full()

        if data_type in ("all", "cashflow"):
            log.info(
                "Initialising cashflow data via cashflow_vip (all quarters)..."
            )
            results["cashflow"] = updater._update_cashflow_full()

        if data_type in ("all", "trade_calendar"):
            df = fetcher.fetch_trade_calendar()
            results["trade_calendar"] = storage.save_trade_calendar(df)

        if data_type in ("all", "adjfactor"):
            log.info("Initialising adjfactor data...")
            results["adjfactor"] = updater._update_adjfactor_full()

        if data_type in ("all", "moneyflow"):
            log.info("Initialising moneyflow data...")
            results["moneyflow"] = updater._update_moneyflow_full()

        if data_type in ("all", "st_stocks"):
            df = fetcher.fetch_st_stocks()
            results["st_stocks"] = storage.save_st_stocks(df)

        if data_type in ("all", "index_basic"):
            log.info("Initialising index basic info (CSI/SSE/SZSE)...")
            results["index_basic"] = updater._update_index_basic()

        if data_type in ("all", "index_weight"):
            log.info("Initialising index weight data (past 13 years)...")
            results["index_weight"] = updater._update_index_weight_full()

        if data_type in ("all", "index_daily"):
            log.info("Initialising index daily data (past 13 years)...")
            results["index_daily"] = updater._update_index_daily_full()

        _print_summary("INIT complete!", results)
    except ValueError as e:
        log.error("Configuration error: %s", e)
        sys.exit(1)
    except Exception:
        log.exception("Init failed")
        sys.exit(1)


# ======================================================================
# Command: update
# ======================================================================

def cmd_update(args: argparse.Namespace) -> None:
    from data.fetcher import TushareDataFetcher
    from data.storage import DataStorage
    from data.updater import DailyUpdater

    data_type = args.data_type
    months = args.months
    days = args.days

    log.info(
        "=== UPDATE (mode=%s, data_type=%s, months=%d, days=%d) ===",
        "full" if args.full else "incremental",
        data_type,
        months,
        days,
    )

    try:
        fetcher = TushareDataFetcher()
        storage = DataStorage()
        updater = DailyUpdater(fetcher, storage)

        if data_type == "all":
            # Full pipeline — all data types
            if args.full:
                results = updater.update_full()
            else:
                results = updater.update_incremental(months=months)
        else:
            # Single data type — always full refresh for lightweight types;
            # trade_calendar / daily / income support incremental via --months
            results = _update_single(updater, data_type, months, days=days, full=args.full)

        _print_summary("UPDATE complete!", results)
    except ValueError as e:
        log.error("Configuration error: %s", e)
        sys.exit(1)
    except Exception:
        log.exception("Update failed")
        sys.exit(1)


def _update_single(updater, data_type: str, months: int = 3, days: int = 5, full: bool = False) -> dict[str, int]:
    """Update a single data type.

    Lightweight types (st_stocks, stock_basic) always do full refresh.
    Heavier types (daily, income, trade_calendar) use incremental with
    configurable *months* for lookback range, or full refresh when *full*
    is True.  Daily data uses *days* (trading days) instead of *months*.
    """
    results: dict[str, int] = {}

    if data_type == "st_stocks":
        results["st_stocks"] = updater._update_st_stocks()
    elif data_type == "stock_basic":
        results["stock_basic"] = updater._update_stock_basic()
    elif data_type == "daily":
        if full:
            results["daily"] = updater._update_daily_full()
        else:
            results["daily"] = updater._update_daily_incremental(days=days)
    elif data_type == "income":
        if full:
            results["income"] = updater._update_income_full()
        else:
            results["income"] = updater._update_income_incremental(months=months)
    elif data_type == "balancesheet":
        if full:
            results["balancesheet"] = updater._update_balancesheet_full()
        else:
            results["balancesheet"] = updater._update_balancesheet_incremental(months=months)
    elif data_type == "cashflow":
        if full:
            results["cashflow"] = updater._update_cashflow_full()
        else:
            results["cashflow"] = updater._update_cashflow_incremental(months=months)
    elif data_type == "trade_calendar":
        if full:
            results["trade_calendar"] = updater._update_trade_calendar_full()
        else:
            results["trade_calendar"] = updater._update_trade_calendar_incremental(months=months)
    elif data_type == "adjfactor":
        if full:
            results["adjfactor"] = updater._update_adjfactor_full()
        else:
            results["adjfactor"] = updater._update_adjfactor_incremental(months=months)
    elif data_type == "moneyflow":
        if full:
            results["moneyflow"] = updater._update_moneyflow_full()
        else:
            results["moneyflow"] = updater._update_moneyflow_incremental(months=months)
    elif data_type == "index_basic":
        results["index_basic"] = updater._update_index_basic()
    elif data_type == "index_weight":
        if full:
            results["index_weight"] = updater._update_index_weight_full()
        else:
            results["index_weight"] = updater._update_index_weight_incremental(months=months)
    elif data_type == "index_daily":
        if full:
            results["index_daily"] = updater._update_index_daily_full()
        else:
            results["index_daily"] = updater._update_index_daily_incremental(months=months)

    return results


# ======================================================================
# Command: query
# ======================================================================

def cmd_query(args: argparse.Namespace) -> None:
    # Dispatch to subcommand if specified
    if hasattr(args, "query_command") and args.query_command == "index-weight":
        cmd_query_index_weight(args)
        return

    from query.engine import QueryEngine

    engine = QueryEngine()

    if args.sql:
        try:
            df = engine.raw_sql(args.sql)
            _print_df(df)
        except Exception:
            log.exception("Query failed")
        finally:
            engine.close()
        return

    _interactive_loop(engine)


# ======================================================================
# Command: export
# ======================================================================

def cmd_export(args: argparse.Namespace) -> None:
    from data.storage import DataStorage

    storage = DataStorage()
    table = args.table
    fmt = args.format
    out = args.output

    log.info("Exporting %s → %s (%s)", table, out, fmt)

    try:
        # Read from storage with filters
        if table == "daily":
            df = storage.read_daily(args.ts_code, args.start, args.end)
        elif table == "stock_basic":
            df = storage.read_stock_basic(args.ts_code)
        elif table == "income":
            period = args.period
            if not period:
                log.error(
                    "--period is required for income table "
                    "(e.g. --period 20260331)."
                )
                sys.exit(1)
            # Use period as both start and end to filter exactly one quarter
            df = storage.read_income(args.ts_code, period, period)
        elif table == "balancesheet":
            period = args.period
            if not period:
                log.error(
                    "--period is required for balancesheet table "
                    "(e.g. --period 20260331)."
                )
                sys.exit(1)
            # Use period as both start and end to filter exactly one quarter
            df = storage.read_balancesheet(args.ts_code, period, period)
        elif table == "cashflow":
            period = args.period
            if not period:
                log.error(
                    "--period is required for cashflow table "
                    "(e.g. --period 20260331)."
                )
                sys.exit(1)
            # Use period as both start and end to filter exactly one quarter
            df = storage.read_cashflow(args.ts_code, period, period)
        elif table == "trade_calendar":
            df = storage.read_trade_calendar(args.ts_code, args.start, args.end)
        elif table == "adjfactor":
            period = args.period
            if not period:
                log.error(
                    "--period is required for adjfactor table "
                    "(e.g. --period 20260627)."
                )
                sys.exit(1)
            # Use period as both start and end to filter exactly one trading day
            df = storage.read_adjfactor(args.ts_code, period, period)
        elif table == "moneyflow":
            period = args.period
            if not period:
                log.error(
                    "--period is required for moneyflow table "
                    "(e.g. --period 20260627)."
                )
                sys.exit(1)
            # Use period as both start and end to filter exactly one trading day
            df = storage.read_moneyflow(args.ts_code, period, period)
        elif table == "st_stocks":
            df = storage.read_st_stocks(args.ts_code)
        elif table == "index_basic":
            # --ts-code can be used as market filter (CSI/SSE/SZSE); omit for all
            market = args.ts_code if args.ts_code in ("CSI", "SSE", "SZSE") else None
            df = storage.read_index_basic(market=market)
        elif table == "index_weight":
            # --ts-code as index_code filter (e.g. 000300.SH); --start/--end for date range
            df = storage.read_index_weight(
                index_code=args.ts_code,
                start_date=args.start,
                end_date=args.end,
            )
        elif table == "index_daily":
            # --ts-code as index_code filter (e.g. 000300.SH); --start/--end for date range
            df = storage.read_index_daily(
                index_code=args.ts_code,
                start_date=args.start,
                end_date=args.end,
            )
        else:
            log.error("Unknown table: %s", table)
            sys.exit(1)

        if df.empty:
            print("No data matched — export file not written.")
            return

        if fmt == "csv":
            # Convert numeric columns to strings to prevent overflow
            # (e.g. large financial values like 2,441,641,000 won't fit in Excel's INT32).
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col].astype(str)
            df.to_csv(out, index=False, encoding="utf-8-sig")
        elif fmt == "parquet":
            df.to_parquet(out, index=False)
        elif fmt == "json":
            df.to_json(out, orient="records", force_ascii=False, indent=2)

        print(f"Exported {len(df)} rows → {out}")
    except Exception:
        log.exception("Export failed")
        sys.exit(1)
    finally:
        storage.close()


# ======================================================================
# Command: stats
# ======================================================================

def cmd_stats(_args: argparse.Namespace) -> None:
    from query.engine import QueryEngine

    engine = QueryEngine()
    try:
        counts = engine.record_counts()
        print("\n  Table             Row Count")
        print("  " + "-" * 30)
        for t, c in counts.items():
            print(f"  {t:20s}: {c:>8d}")
        print()
    except Exception:
        log.exception("Stats query failed")
    finally:
        engine.close()


# ======================================================================
# Command: schema
# ======================================================================

def cmd_schema(_args: argparse.Namespace) -> None:
    from query.engine import QueryEngine

    engine = QueryEngine()
    try:
        schemas = engine.get_schemas()
        for t, df in schemas.items():
            print(f"\n  === {t}_view ===")
            if df.empty:
                print("  (no data)")
            else:
                for _, row in df.iterrows():
                    print(
                        f"  {row['column_name']:25s} "
                        f"{str(row['column_type']):20s}"
                        f"{'NULL' if row.get('null') == 'YES' else ''}"
                    )
        print()
    except Exception:
        log.exception("Schema query failed")
    finally:
        engine.close()


# ======================================================================
# Interactive REPL
# ======================================================================

def _interactive_loop(engine) -> None:
    """REPL with dot-command shortcuts and raw SQL support."""

    print("\n" + "=" * 60)
    print("  Quant Data Query — Interactive Mode")
    print("  Tables: daily_view | stock_basic_view | income_view | cashflow_view | balancesheet_view | adjfactor_view | moneyflow_view | index_basic_view | index_weight_view | index_daily_view")
    print("  Type 'help' for commands, 'exit' to quit.")
    print("=" * 60 + "\n")

    while True:
        try:
            cmd = input("quant> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not cmd:
            continue

        if cmd.lower() in ("exit", "quit", "q"):
            print("Bye.")
            break

        if cmd.lower() == "help":
            _print_help()
            continue

        if cmd.lower() == "tables":
            print("  daily_view | stock_basic_view | income_view | cashflow_view | balancesheet_view | adjfactor_view | moneyflow_view | index_basic_view | index_weight_view | index_daily_view\n")
            continue

        if cmd.lower() == "counts":
            try:
                counts = engine.record_counts()
                for t, c in counts.items():
                    print(f"  {t:20s}: {c:>8d}")
                print()
            except Exception as e:
                print(f"  Error: {e}\n")
            continue

        if cmd.lower().startswith("schema"):
            parts = cmd.split()
            table = parts[1] if len(parts) > 1 else None
            try:
                schemas = engine.get_schemas()
                for t, df in schemas.items():
                    if table and table not in t:
                        continue
                    print(f"\n  === {t}_view ===")
                    if df.empty:
                        print("  (no data)")
                    else:
                        for _, row in df.iterrows():
                            print(
                                f"  {row['column_name']:25s} "
                                f"{str(row['column_type']):20s}"
                            )
                    print()
            except Exception as e:
                print(f"  Error: {e}\n")
            continue

        # Dot-command shortcuts
        if cmd.startswith("."):
            if _dispatch_shortcut(cmd, engine):
                continue

        # Fallback: raw SQL
        try:
            df = engine.raw_sql(cmd)
            _print_df(df)
        except Exception as e:
            print(f"  Error: {e}\n")

    engine.close()


def _dispatch_shortcut(cmd: str, engine) -> bool:
    """Handle dot-commands. Returns True if the command was handled."""
    parts = cmd.split()
    if not parts or not parts[0].startswith("."):
        return False

    sc = parts[0].lower()

    try:
        if sc == ".top":
            date = (
                parts[1]
                if len(parts) > 1
                else datetime.today().strftime("%Y%m%d")
            )
            n = int(parts[2]) if len(parts) > 2 else 20
            _print_df(engine.top_volume(date, n))

        elif sc == ".rank":
            if len(parts) < 3:
                print("  Usage: .rank <start_date> <end_date> [n]")
                return True
            start, end = parts[1], parts[2]
            n = int(parts[3]) if len(parts) > 3 else 20
            _print_df(engine.price_change_rank(start, end, n))

        elif sc == ".sector":
            date = (
                parts[1]
                if len(parts) > 1
                else datetime.today().strftime("%Y%m%d")
            )
            _print_df(engine.sector_performance(date))

        elif sc == ".search":
            if len(parts) < 2:
                print("  Usage: .search <keyword>")
                return True
            _print_df(engine.search_stock(parts[1]))

        elif sc == ".industry":
            if len(parts) < 2:
                print("  Usage: .industry <name>")
                return True
            _print_df(engine.industry_stocks(parts[1]))

        elif sc == ".roe":
            date = (
                parts[1]
                if len(parts) > 1
                else datetime.today().strftime("%Y%m%d")
            )
            n = int(parts[2]) if len(parts) > 2 else 20
            _print_df(engine.roe_rank(date, n))

        elif sc == ".fin":
            if len(parts) < 2:
                print("  Usage: .fin <ts_code> [n_periods]")
                return True
            n = int(parts[2]) if len(parts) > 2 else 8
            _print_df(engine.income_summary(parts[1], n))

        elif sc == ".bs":
            if len(parts) < 2:
                print("  Usage: .bs <ts_code> [n_periods]")
                return True
            n = int(parts[2]) if len(parts) > 2 else 8
            _print_df(engine.balancesheet_summary(parts[1], n))

        elif sc == ".cf":
            if len(parts) < 2:
                print("  Usage: .cf <ts_code> [n_periods]")
                return True
            n = int(parts[2]) if len(parts) > 2 else 8
            _print_df(engine.cashflow_summary(parts[1], n))

        elif sc == ".mf":
            if len(parts) < 2:
                print("  Usage: .mf <ts_code> [n_days]")
                return True
            n = int(parts[2]) if len(parts) > 2 else 20
            _print_df(engine.moneyflow_summary(parts[1], n))

        elif sc == ".mfrank":
            date = (
                parts[1]
                if len(parts) > 1
                else datetime.today().strftime("%Y%m%d")
            )
            n = int(parts[2]) if len(parts) > 2 else 20
            _print_df(engine.moneyflow_rank(date, n))

        elif sc == ".assets":
            date = (
                parts[1]
                if len(parts) > 1
                else datetime.today().strftime("%Y%m%d")
            )
            n = int(parts[2]) if len(parts) > 2 else 20
            _print_df(engine.asset_rank(date, n))

        elif sc == ".latest":
            if len(parts) < 2:
                print("  Usage: .latest <ts_code>")
                return True
            _print_df(engine.get_daily_latest(parts[1]))

        elif sc == ".stocks":
            market = parts[1] if len(parts) > 1 else None
            if market:
                _print_df(engine.filter_stocks_by_market(market))
            else:
                _print_df(engine.get_stock_info())

        elif sc == ".st":
            st_type = parts[1] if len(parts) > 1 else None
            if st_type and st_type in ("ST", "*ST"):
                _print_df(engine.get_st_stocks_by_type(st_type))
            else:
                _print_df(engine.get_st_stocks())

        elif sc == ".tcal":
            if len(parts) < 3:
                print("  Usage: .tcal <start_date> <end_date>")
                return True
            _print_df(engine.get_trade_calendar(parts[1], parts[2]))

        elif sc == ".isopen":
            if len(parts) < 2:
                print("  Usage: .isopen <date>")
                return True
            is_open = engine.is_trading_day(parts[1])
            print(f"  {parts[1]} is {'a trading day' if is_open else 'NOT a trading day'}\n")

        elif sc == ".indices":
            market = parts[1] if len(parts) > 1 else None
            _print_df(engine.get_index_basic(market=market))

        elif sc == ".isearch":
            if len(parts) < 2:
                print("  Usage: .isearch <keyword>")
                return True
            _print_df(engine.search_index(parts[1]))

        elif sc == ".iw":
            if len(parts) < 2:
                print("  Usage: .iw <index_code> [date]")
                return True
            date = parts[2] if len(parts) > 2 else None
            if date:
                _print_df(engine.get_index_weight(parts[1], date))
            else:
                _print_df(engine.index_weight_latest(parts[1]))

        elif sc == ".iwtop":
            if len(parts) < 2:
                print("  Usage: .iwtop <index_code> [date] [n]")
                return True
            date = parts[2] if len(parts) > 2 else None
            n = int(parts[3]) if len(parts) > 3 else 20
            if date:
                df = engine.get_index_weight(parts[1], date)
            else:
                df = engine.index_weight_latest(parts[1])
            if not df.empty:
                _print_df(df.head(n))

        elif sc == ".iwcon":
            if len(parts) < 2:
                print("  Usage: .iwcon <con_code>")
                return True
            _print_df(engine.search_constituent(parts[1]))

        elif sc == ".iwsum":
            index_code = parts[1] if len(parts) > 1 else None
            _print_df(engine.index_weight_summary(index_code=index_code))

        elif sc == ".id":
            if len(parts) < 2:
                print("  Usage: .id <index_code> [start_date] [end_date]")
                return True
            index_code = parts[1]
            start = parts[2] if len(parts) > 2 else None
            end = parts[3] if len(parts) > 3 else None
            _print_df(engine.get_index_daily(index_code, start, end))

        elif sc == ".idlatest":
            if len(parts) < 2:
                print("  Usage: .idlatest <index_code>")
                return True
            _print_df(engine.get_index_daily_latest(parts[1]))

        elif sc == ".idrank":
            date = (
                parts[1]
                if len(parts) > 1
                else datetime.today().strftime("%Y%m%d")
            )
            n = int(parts[2]) if len(parts) > 2 else 10
            _print_df(engine.index_performance_rank(date, n))

        else:
            print(f"  Unknown command: {sc}")
        return True

    except Exception as e:
        print(f"  Error: {e}\n")
        return True


# ======================================================================
# Display helpers
# ======================================================================

def _print_help() -> None:
    print(
        """
  Dot-command shortcuts:
    .top <date> [n]         Top-N by trading amount on a date
    .rank <start> <end> [n] Price change rank over period
    .sector <date>          Sector/industry performance
    .search <keyword>       Search stocks by name/symbol
    .industry <name>        List stocks in an industry
    .roe <end_date> [n]     Top-N by ROE
    .fin <ts_code> [n]      Recent N income reporting periods
    .bs <ts_code> [n]       Recent N balance sheet periods
    .cf <ts_code> [n]       Recent N cashflow reporting periods
    .mf <ts_code> [n]       Recent N days moneyflow for a stock
    .mfrank <date> [n]      Top-N by net moneyflow amount on a date
    .assets [date] [n]      Top-N by total assets
    .latest <ts_code>       Latest daily bar for a stock
    .stocks [market]        List stocks, optionally by market
    .st [type]              List ST stocks (ST or *ST)
    .tcal <start> <end>     Query trading calendar
    .isopen <date>          Check if date is a trading day
    .indices [market]       List index basic info (CSI/SSE/SZSE)
    .isearch <keyword>      Search indices by name/code
    .iw <index_code> [date] View index constituent weights
    .iwtop <index> [date] [n]Top-N constituents by weight
    .iwcon <con_code>       Find index memberships for a stock
    .iwsum [index]          Index weight summary statistics
    .id <index> [start] [end] Query index daily OHLCV data
    .idlatest <index>       Latest index daily bar
    .idrank [date] [n]      Index performance rank by pct_chg

  Meta commands:
    help                    Show this help
    tables                  List available tables/views
    counts                  Show row counts per table
    schema [table]          Show column schemas
    exit / quit / q         Exit

  Or type any raw SQL query.
  Example:  SELECT * FROM daily_view WHERE ts_code='000001.SZ' LIMIT 5;
"""
    )


def _print_df(df: pd.DataFrame | None) -> None:
    """Pretty-print a DataFrame."""
    if df is None or df.empty:
        print("  (empty result)\n")
        return
    with pd.option_context(
        "display.max_rows", 50,
        "display.max_columns", 20,
        "display.width", 160,
        "display.float_format", lambda x: f"{x:.2f}",
    ):
        print(df.to_string(index=False))
        print(f"\n  [{len(df)} rows]\n")


def _print_summary(title: str, results: dict[str, int]) -> None:
    """Print a formatted results table."""
    print("\n" + "=" * 50)
    print(f"  {title}")
    print("=" * 50)
    for dt, rows in results.items():
        print(f"  {dt:20s}: {rows:>8d} rows")
    print("=" * 50)


def _output_or_show(
    df: pd.DataFrame,
    output_path: str | None,
    label: str,
) -> None:
    """Save to file or print to stdout."""
    if output_path:
        if output_path.endswith(".csv"):
            df.to_csv(output_path, index=False, encoding="utf-8-sig")
        elif output_path.endswith(".parquet"):
            df.to_parquet(output_path, index=False)
        else:
            df.to_csv(output_path, index=False, encoding="utf-8-sig")  # default csv
        print(f"Saved {len(df)} rows ({label}) → {output_path}")
    else:
        print(f"\n  [{label} — {len(df)} rows]")
        _print_df(df)


# ======================================================================
# Main
# ======================================================================

if __name__ == "__main__":
    main()
