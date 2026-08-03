"""Query engine — high-level query interface over DuckDB-stored data.

All Parquet-backed data is accessible through DuckDB views:
``daily_view``, ``stock_basic_view``, ``income_view``.
"""

from __future__ import annotations

import pandas as pd

from data.storage import DataStorage
from utils.logger import log


class QueryEngine:
    """Provides pre-built and ad-hoc SQL queries against the quant database."""

    def __init__(self, storage: DataStorage | None = None) -> None:
        self._storage = storage or DataStorage()

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def storage(self) -> DataStorage:
        return self._storage

    # ------------------------------------------------------------------
    # Pre-built queries — Daily
    # ------------------------------------------------------------------

    def get_daily(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Get daily OHLCV data for a single stock.

        Args:
            ts_code: e.g. '000001.SZ'.
            start_date: 'YYYYMMDD'.
            end_date: 'YYYYMMDD'.
        """
        log.info("Query daily: %s [%s → %s]", ts_code, start_date, end_date)
        return self._storage.read_daily(ts_code, start_date, end_date)

    def get_daily_latest(self, ts_code: str) -> pd.DataFrame:
        """Get the most recent trading day for *ts_code*."""
        sql = """
            SELECT * FROM daily_view
            WHERE ts_code = ?
            ORDER BY trade_date DESC
            LIMIT 1
        """
        return self._storage.execute_sql(sql.replace("?", f"'{ts_code}'"))

    def top_volume(
        self,
        trade_date: str,
        n: int = 20,
    ) -> pd.DataFrame:
        """Top-N stocks by trading volume on a given date.

        Args:
            trade_date: 'YYYYMMDD'.
            n: Number of top stocks to return.
        """
        log.info("Query top_volume: date=%s, n=%d", trade_date, n)
        sql = f"""
            SELECT d.ts_code, s.name, d.close, d.pct_chg, d.vol, d.amount
            FROM daily_view d
            LEFT JOIN stock_basic_view s ON d.ts_code = s.ts_code
            WHERE d.trade_date = '{trade_date}'
            ORDER BY d.amount DESC
            LIMIT {n}
        """
        return self._storage.execute_sql(sql)

    def price_change_rank(
        self,
        start_date: str,
        end_date: str,
        n: int = 20,
        ascending: bool = False,
    ) -> pd.DataFrame:
        """Cumulative price-change ranking over a period.

        Computes cumulative return = (close_last - close_first) / close_first.

        Args:
            start_date: 'YYYYMMDD'.
            end_date: 'YYYYMMDD'.
            n: Number of results.
            ascending: False → best performers first; True → worst first.
        """
        direction = "ASC" if ascending else "DESC"
        sql = f"""
            WITH first_day AS (
                SELECT ts_code, close AS close_first
                FROM daily_view WHERE trade_date = '{start_date}'
            ),
            last_day AS (
                SELECT ts_code, close AS close_last
                FROM daily_view WHERE trade_date = '{end_date}'
            )
            SELECT
                f.ts_code,
                s.name,
                f.close_first,
                l.close_last,
                ROUND((l.close_last - f.close_first) / f.close_first * 100, 2) AS cum_return_pct
            FROM first_day f
            JOIN last_day l ON f.ts_code = l.ts_code
            LEFT JOIN stock_basic_view s ON f.ts_code = s.ts_code
            ORDER BY cum_return_pct {direction}
            LIMIT {n}
        """
        return self._storage.execute_sql(sql)

    def sector_performance(
        self,
        trade_date: str,
    ) -> pd.DataFrame:
        """Average daily return per industry sector on a given date."""
        sql = f"""
            SELECT
                s.industry,
                COUNT(*) AS stock_count,
                ROUND(AVG(d.pct_chg), 2) AS avg_pct_chg,
                ROUND(AVG(d.amount), 0) AS avg_amount
            FROM daily_view d
            JOIN stock_basic_view s ON d.ts_code = s.ts_code
            WHERE d.trade_date = '{trade_date}'
              AND s.industry IS NOT NULL
            GROUP BY s.industry
            ORDER BY avg_pct_chg DESC
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Stock info
    # ------------------------------------------------------------------

    def get_stock_info(self, ts_code: str | None = None) -> pd.DataFrame:
        """Get stock basic information.

        Args:
            ts_code: Optional stock-code filter.
        """
        log.info("Query stock info: %s", ts_code or "ALL")
        return self._storage.read_stock_basic(ts_code)

    def search_stock(self, keyword: str) -> pd.DataFrame:
        """Search stocks by name, symbol, or pinyin abbreviation."""
        kw = keyword.upper()
        sql = f"""
            SELECT ts_code, symbol, name, area, industry, list_date, is_hs
            FROM stock_basic_view
            WHERE name LIKE '%{kw}%'
               OR symbol LIKE '%{kw}%'
               OR UPPER(cnspell) LIKE '%{kw}%'
            ORDER BY ts_code
        """
        return self._storage.execute_sql(sql)

    def industry_stocks(self, industry: str) -> pd.DataFrame:
        """List all stocks in a given industry."""
        sql = f"""
            SELECT ts_code, symbol, name, area, list_date
            FROM stock_basic_view
            WHERE industry = '{industry}'
            ORDER BY ts_code
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Income
    # ------------------------------------------------------------------

    def get_income(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Get income statement data for a stock."""
        log.info("Query income: %s [%s → %s]", ts_code, start_date, end_date)
        return self._storage.read_income(ts_code, start_date, end_date)

    def roe_rank(
        self,
        end_date: str,
        n: int = 20,
    ) -> pd.DataFrame:
        """Top-N stocks by net profit (归母净利润) for the latest reporting
        period ending on or before *end_date*.

        With ``income`` as the data source the income_view has income-
        statement fields.  We rank by ``n_income_attr_p`` (net profit
        attributable to parent) and display basic_eps / total revenue alongside.
        """
        sql = f"""
            WITH latest AS (
                SELECT ts_code, MAX(end_date) AS max_end_date
                FROM income_view
                WHERE end_date <= '{end_date}'
                GROUP BY ts_code
            )
            SELECT
                f.ts_code,
                s.name,
                f.end_date,
                ROUND(f.n_income_attr_p / 10000.0, 2) AS net_profit_yi,
                f.basic_eps,
                f.total_revenue,
                f.operate_profit,
                f.total_profit
            FROM income_view f
            JOIN latest l ON f.ts_code = l.ts_code AND f.end_date = l.max_end_date
            LEFT JOIN stock_basic_view s ON f.ts_code = s.ts_code
            WHERE f.n_income_attr_p IS NOT NULL
            ORDER BY f.n_income_attr_p DESC
            LIMIT {n}
        """
        return self._storage.execute_sql(sql)

    def income_summary(
        self,
        ts_code: str,
        n_periods: int = 8,
    ) -> pd.DataFrame:
        """Recent N income reporting periods for a single stock."""
        sql = f"""
            SELECT *
            FROM income_view
            WHERE ts_code = '{ts_code}'
            ORDER BY end_date DESC
            LIMIT {n_periods}
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Balance Sheet
    # ------------------------------------------------------------------

    def get_balancesheet(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Get balance sheet data for a stock."""
        log.info("Query balancesheet: %s [%s → %s]", ts_code, start_date, end_date)
        return self._storage.read_balancesheet(ts_code, start_date, end_date)

    def balancesheet_summary(
        self,
        ts_code: str,
        n_periods: int = 8,
    ) -> pd.DataFrame:
        """Recent N balance sheet reporting periods for a single stock.

        Returns key indicators: total assets, total liabilities, total
        equity, current ratio, debt-to-asset ratio.
        """
        sql = f"""
            SELECT
                ts_code,
                end_date,
                total_assets,
                total_cur_assets,
                total_nca,
                total_liab,
                total_cur_liab,
                total_ncl,
                total_hldr_eqy_inc_min_int,
                money_cap,
                accounts_receiv,
                inventories,
                fix_assets,
                intang_assets,
                goodwill,
                st_borrow,
                lt_borrow,
                bonds_payable,
                -- Derived: current ratio
                ROUND(total_cur_assets / NULLIF(total_cur_liab, 0), 2) AS current_ratio,
                -- Derived: debt-to-asset ratio (%)
                ROUND(total_liab / NULLIF(total_assets, 0) * 100, 2) AS debt_ratio_pct
            FROM balancesheet_view
            WHERE ts_code = '{ts_code}'
            ORDER BY end_date DESC
            LIMIT {n_periods}
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Cashflow
    # ------------------------------------------------------------------

    def get_cashflow(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Get cashflow statement data for a stock."""
        log.info("Query cashflow: %s [%s → %s]", ts_code, start_date, end_date)
        return self._storage.read_cashflow(ts_code, start_date, end_date)

    # ------------------------------------------------------------------
    # Pre-built queries — Moneyflow
    # ------------------------------------------------------------------

    def get_moneyflow(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Get moneyflow data with optional filters.

        Args:
            ts_code: e.g. '000001.SZ'. If None, returns all stocks.
            start_date: 'YYYYMMDD'.
            end_date: 'YYYYMMDD'.
        """
        log.info("Query moneyflow: %s [%s → %s]", ts_code or "ALL", start_date, end_date)
        return self._storage.read_moneyflow(ts_code, start_date, end_date)

    def moneyflow_rank(
        self,
        trade_date: str,
        n: int = 20,
    ) -> pd.DataFrame:
        """Top-N stocks by net moneyflow amount on a given date.

        Args:
            trade_date: 'YYYYMMDD'.
            n: Number of top stocks to return.
        """
        log.info("Query moneyflow_rank: date=%s, n=%d", trade_date, n)
        sql = f"""
            SELECT m.ts_code, s.name, m.net_mf_amount, m.net_mf_vol,
                   m.buy_lg_amount, m.sell_lg_amount,
                   m.buy_elg_amount, m.sell_elg_amount
            FROM moneyflow_view m
            LEFT JOIN stock_basic_view s ON m.ts_code = s.ts_code
            WHERE m.trade_date = '{trade_date}'
            ORDER BY m.net_mf_amount DESC
            LIMIT {n}
        """
        return self._storage.execute_sql(sql)

    def moneyflow_summary(
        self,
        ts_code: str,
        n_days: int = 20,
    ) -> pd.DataFrame:
        """Recent N trading days of moneyflow for a single stock."""
        sql = f"""
            SELECT *
            FROM moneyflow_view
            WHERE ts_code = '{ts_code}'
            ORDER BY trade_date DESC
            LIMIT {n_days}
        """
        return self._storage.execute_sql(sql)

    def cashflow_summary(
        self,
        ts_code: str,
        n_periods: int = 8,
    ) -> pd.DataFrame:
        """Recent N cashflow reporting periods for a single stock.

        Returns key indicators: operating/investing/financing net cashflow,
        free cashflow, net profit, and cash equivalents.
        """
        sql = f"""
            SELECT
                ts_code,
                end_date,
                net_profit,
                n_cashflow_act,
                n_cashflow_inv_act,
                n_cash_flows_fnc_act,
                free_cashflow,
                c_cash_equ_beg_period,
                c_cash_equ_end_period,
                n_incr_cash_cash_equ
            FROM cashflow_view
            WHERE ts_code = '{ts_code}'
            ORDER BY end_date DESC
            LIMIT {n_periods}
        """
        return self._storage.execute_sql(sql)

    def asset_rank(
        self,
        end_date: str,
        n: int = 20,
    ) -> pd.DataFrame:
        """Top-N stocks by total assets for the latest reporting period
        ending on or before *end_date*.
        """
        sql = f"""
            WITH latest AS (
                SELECT ts_code, MAX(end_date) AS max_end_date
                FROM balancesheet_view
                WHERE end_date <= '{end_date}'
                GROUP BY ts_code
            )
            SELECT
                b.ts_code,
                s.name,
                b.end_date,
                ROUND(b.total_assets / 100000000.0, 2) AS total_assets_yi,
                ROUND(b.total_liab / 100000000.0, 2) AS total_liab_yi,
                ROUND(b.total_hldr_eqy_inc_min_int / 100000000.0, 2) AS total_equity_yi,
                ROUND(b.total_liab / NULLIF(b.total_assets, 0) * 100, 2) AS debt_ratio_pct
            FROM balancesheet_view b
            JOIN latest l ON b.ts_code = l.ts_code AND b.end_date = l.max_end_date
            LEFT JOIN stock_basic_view s ON b.ts_code = s.ts_code
            WHERE b.total_assets IS NOT NULL
            ORDER BY b.total_assets DESC
            LIMIT {n}
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Stock List
    # ------------------------------------------------------------------

    def filter_stocks_by_market(self, market: str) -> pd.DataFrame:
        """Filter stocks by market (主板/创业板/科创板)."""
        sql = f"""
            SELECT ts_code, symbol, name, area, industry, list_date
            FROM stock_basic_view
            WHERE market = '{market}'
            ORDER BY ts_code
        """
        return self._storage.execute_sql(sql)

    def stocks_by_industry(self, industry: str) -> pd.DataFrame:
        """Group stocks by industry from stock basic info."""
        sql = f"""
            SELECT industry, COUNT(*) AS stock_count
            FROM stock_basic_view
            WHERE industry = '{industry}'
            GROUP BY industry
            ORDER BY stock_count DESC
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Trade Calendar
    # ------------------------------------------------------------------

    def get_trade_calendar(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        """Query trading calendar.

        Args:
            start_date: 'YYYYMMDD'.
            end_date: 'YYYYMMDD'.
            exchange: 'SSE', 'SZSE', or None for all.
        """
        log.info("Query trade_calendar: %s → %s", start_date, end_date)
        return self._storage.read_trade_calendar(
            exchange, start_date, end_date,
        )

    def is_trading_day(self, date: str, exchange: str = "SSE") -> bool:
        """Check if *date* is a trading day."""
        sql = f"""
            SELECT is_open FROM trade_calendar_view
            WHERE cal_date = '{date}' AND exchange = '{exchange}'
        """
        df = self._storage.execute_sql(sql)
        if df.empty:
            return False
        return int(df["is_open"].iloc[0]) == 1

    def next_trading_day(
        self, date: str, exchange: str = "SSE"
    ) -> str | None:
        """Get the next trading day on or after *date*."""
        sql = f"""
            SELECT cal_date FROM trade_calendar_view
            WHERE cal_date >= '{date}' AND exchange = '{exchange}'
              AND is_open = 1
            ORDER BY cal_date ASC LIMIT 1
        """
        df = self._storage.execute_sql(sql)
        if df.empty:
            return None
        return str(df["cal_date"].iloc[0])

    def trading_days_count(
        self, start_date: str, end_date: str, exchange: str = "SSE",
    ) -> int:
        """Count trading days in a date range."""
        sql = f"""
            SELECT COUNT(*) AS cnt FROM trade_calendar_view
            WHERE cal_date >= '{start_date}' AND cal_date <= '{end_date}'
              AND exchange = '{exchange}' AND is_open = 1
        """
        df = self._storage.execute_sql(sql)
        return int(df["cnt"].iloc[0])

    # ------------------------------------------------------------------
    # Pre-built queries — ST Stocks
    # ------------------------------------------------------------------

    def get_st_stocks(self) -> pd.DataFrame:
        """Get the current list of ST stocks."""
        log.info("Query st_stocks: ALL")
        return self._storage.read_st_stocks()

    def get_st_stocks_by_type(self, st_type: str) -> pd.DataFrame:
        """Filter ST stocks by type ('ST' or '\*ST')."""
        sql = f"""
            SELECT ts_code, symbol, name, industry, list_date
            FROM st_stocks_view
            WHERE st_type = '{st_type}'
            ORDER BY ts_code
        """
        return self._storage.execute_sql(sql)

    def st_stocks_by_industry(self) -> pd.DataFrame:
        """Count ST stocks by industry."""
        sql = """
            SELECT industry, COUNT(*) AS st_count
            FROM st_stocks_view
            WHERE industry IS NOT NULL
            GROUP BY industry
            ORDER BY st_count DESC
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Index Basic
    # ------------------------------------------------------------------

    def get_index_basic(
        self,
        market: str | None = None,
    ) -> pd.DataFrame:
        """Get index basic information.

        Args:
            market: 'CSI', 'SSE', 'SZSE', or None for all markets.
        """
        log.info("Query index_basic: market=%s", market or "ALL")
        return self._storage.read_index_basic(market=market)

    def search_index(self, keyword: str) -> pd.DataFrame:
        """Search indices by name, fullname, or ts_code.

        Args:
            keyword: Search keyword (case-insensitive for name fields).
        """
        kw = keyword.upper()
        sql = f"""
            SELECT ts_code, name, fullname, market, publisher, index_type,
                   category, base_date, base_point, list_date, weight_rule
            FROM index_basic_view
            WHERE UPPER(name) LIKE '%{kw}%'
               OR UPPER(fullname) LIKE '%{kw}%'
               OR UPPER(ts_code) LIKE '%{kw}%'
            ORDER BY ts_code
        """
        return self._storage.execute_sql(sql)

    def index_count_by_market(self) -> pd.DataFrame:
        """Count indices per market."""
        sql = """
            SELECT market, COUNT(*) AS index_count
            FROM index_basic_view
            GROUP BY market
            ORDER BY index_count DESC
        """
        return self._storage.execute_sql(sql)

    def index_count_by_category(self, market: str | None = None) -> pd.DataFrame:
        """Count indices per category, optionally filtered by market."""
        if market:
            sql = f"""
                SELECT market, category, COUNT(*) AS index_count
                FROM index_basic_view
                WHERE market = '{market}'
                GROUP BY market, category
                ORDER BY index_count DESC
            """
        else:
            sql = """
                SELECT market, category, COUNT(*) AS index_count
                FROM index_basic_view
                GROUP BY market, category
                ORDER BY market, index_count DESC
            """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Index Weight
    # ------------------------------------------------------------------

    def get_index_weight(
        self,
        index_code: str | None = None,
        trade_date: str | None = None,
        con_code: str | None = None,
    ) -> pd.DataFrame:
        """Get index constituent weight data.

        Args:
            index_code: Tushare index code e.g. '000300.SH', or None for all.
            trade_date: Month-end date 'YYYYMMDD', or None for all dates.
            con_code: Filter by constituent stock code.

        Returns:
            DataFrame with index_code, con_code, trade_date, weight.
        """
        log.info(
            "Query index_weight: index=%s, date=%s, con=%s",
            index_code or "ALL", trade_date or "ALL", con_code or "ALL",
        )
        return self._storage.read_index_weight(
            index_code=index_code,
            start_date=trade_date,
            end_date=trade_date,
            con_code=con_code,
        )

    def index_weight_latest(
        self,
        index_code: str,
    ) -> pd.DataFrame:
        """Get the most recent constituent weights for an index."""
        sql = f"""
            SELECT * FROM index_weight_view
            WHERE index_code = '{index_code}'
            ORDER BY trade_date DESC
            LIMIT 500
        """
        # Get the latest date first, then filter
        latest_date_sql = f"""
            SELECT MAX(trade_date) AS max_date
            FROM index_weight_view
            WHERE index_code = '{index_code}'
        """
        latest_df = self._storage.execute_sql(latest_date_sql)
        if latest_df.empty or latest_df["max_date"].iloc[0] is None:
            return pd.DataFrame()
        max_date = latest_df["max_date"].iloc[0]
        return self._storage.execute_sql(
            f"SELECT * FROM index_weight_view "
            f"WHERE index_code = '{index_code}' AND trade_date = '{max_date}' "
            f"ORDER BY weight DESC"
        )

    def search_constituent(
        self,
        con_code: str,
    ) -> pd.DataFrame:
        """Find all index memberships for a given stock.

        Args:
            con_code: Constituent stock code e.g. '000001.SZ'.
        """
        log.info("Query constituent: %s", con_code)
        sql = f"""
            SELECT DISTINCT index_code, trade_date, weight
            FROM index_weight_view
            WHERE con_code = '{con_code}'
            ORDER BY trade_date DESC
        """
        return self._storage.execute_sql(sql)

    def constituent_history(
        self,
        con_code: str,
        index_code: str | None = None,
    ) -> pd.DataFrame:
        """Get historical weight changes for a stock in indices.

        Args:
            con_code: Constituent stock code.
            index_code: Optional index filter.
        """
        log.info("Query constituent history: %s, index=%s", con_code, index_code or "ALL")
        if index_code:
            sql = f"""
                SELECT index_code, trade_date, weight
                FROM index_weight_view
                WHERE con_code = '{con_code}' AND index_code = '{index_code}'
                ORDER BY trade_date
            """
        else:
            sql = f"""
                SELECT index_code, trade_date, weight
                FROM index_weight_view
                WHERE con_code = '{con_code}'
                ORDER BY index_code, trade_date
            """
        return self._storage.execute_sql(sql)

    def index_weight_summary(
        self,
        index_code: str | None = None,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        """Get summary statistics for index weights.

        Args:
            index_code: Optional index filter.
            trade_date: Optional date filter.
        """
        conditions = []
        if index_code:
            conditions.append(f"index_code = '{index_code}'")
        if trade_date:
            conditions.append(f"trade_date = '{trade_date}'")

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                index_code,
                trade_date,
                COUNT(*) AS constituent_count,
                ROUND(SUM(weight), 4) AS total_weight,
                ROUND(AVG(weight), 6) AS avg_weight,
                ROUND(MAX(weight), 4) AS max_weight,
                ROUND(MIN(weight), 6) AS min_weight
            FROM index_weight_view
            {where}
            GROUP BY index_code, trade_date
            ORDER BY index_code, trade_date DESC
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Pre-built queries — Index Daily
    # ------------------------------------------------------------------

    def get_index_daily(
        self,
        index_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Get index daily OHLCV data.

        Args:
            index_code: Tushare index code e.g. '000300.SH', or None for all.
            start_date: Start date 'YYYYMMDD'.
            end_date: End date 'YYYYMMDD'.

        Returns:
            DataFrame with index daily data.
        """
        log.info(
            "Query index_daily: index=%s [%s → %s]",
            index_code or "ALL", start_date, end_date,
        )
        return self._storage.read_index_daily(index_code, start_date, end_date)

    def get_index_daily_latest(self, index_code: str) -> pd.DataFrame:
        """Get the most recent trading day for an index."""
        sql = f"""
            SELECT * FROM index_daily_view
            WHERE ts_code = '{index_code}'
            ORDER BY trade_date DESC
            LIMIT 1
        """
        return self._storage.execute_sql(sql)

    def index_performance_rank(
        self,
        trade_date: str,
        n: int = 10,
    ) -> pd.DataFrame:
        """Rank indices by daily percentage change on a given date."""
        sql = f"""
            SELECT ts_code, trade_date, close, open, high, low,
                   pct_chg, vol, amount
            FROM index_daily_view
            WHERE trade_date = '{trade_date}'
            ORDER BY pct_chg DESC
            LIMIT {n}
        """
        return self._storage.execute_sql(sql)

    def index_cumulative_return(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Calculate cumulative return for an index over a period."""
        sql = f"""
            WITH start_price AS (
                SELECT close AS start_close
                FROM index_daily_view
                WHERE ts_code = '{index_code}' AND trade_date = '{start_date}'
            ),
            end_price AS (
                SELECT close AS end_close
                FROM index_daily_view
                WHERE ts_code = '{index_code}' AND trade_date = '{end_date}'
            )
            SELECT
                '{index_code}' AS ts_code,
                '{start_date}' AS start_date,
                s.start_close,
                '{end_date}' AS end_date,
                e.end_close,
                ROUND((e.end_close - s.start_close) / s.start_close * 100, 2) AS cum_return_pct
            FROM start_price s, end_price e
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Raw SQL
    # ------------------------------------------------------------------

    def raw_sql(self, sql: str) -> pd.DataFrame:
        """Execute an arbitrary SQL statement. Tables available:
        ``daily_view``, ``stock_basic_view``, ``income_view``,
        ``cashflow_view``, ``balancesheet_view``, ``adjfactor_view``,
        ``moneyflow_view``, ``index_basic_view``, ``index_weight_view``,
        ``index_weight_zz1000_view``, ``index_weight_zz2000_view``,
        ``index_weight_zz500_view``, ``index_weight_hs300_view``,
        ``index_daily_view``, ``index_daily_zz1000_view``,
        ``index_daily_zz2000_view``, ``index_daily_zz500_view``,
        ``index_daily_hs300_view``.
        """
        return self._storage.execute_sql(sql)

    # ------------------------------------------------------------------
    # Schema / meta
    # ------------------------------------------------------------------

    def get_schemas(self) -> dict[str, pd.DataFrame]:
        """Return column schemas for all tables."""
        result: dict[str, pd.DataFrame] = {}
        for t in (
            "daily", "stock_basic", "income", "cashflow", "balancesheet",
            "trade_calendar", "st_stocks", "adjfactor", "moneyflow",
            "index_basic", "index_weight", "index_daily",
        ):
            try:
                result[t] = self._storage.get_table_schema(t)
            except Exception:
                log.warning("Could not describe %s_view", t)
                result[t] = pd.DataFrame()
        return result

    def record_counts(self) -> dict[str, int]:
        """Row counts per table."""
        counts: dict[str, int] = {}
        for t in (
            "daily", "stock_basic", "income", "cashflow", "balancesheet",
            "trade_calendar", "st_stocks", "adjfactor", "moneyflow",
            "index_basic", "index_weight", "index_daily",
        ):
            try:
                df = self._storage.execute_sql(
                    f"SELECT COUNT(*) AS cnt FROM {t}_view"
                )
                counts[t] = int(df["cnt"].iloc[0])
            except Exception:
                counts[t] = 0
        return counts

    def trading_dates(self, n: int = 10) -> pd.DataFrame:
        """Most recent N distinct trading dates."""
        sql = f"""
            SELECT DISTINCT trade_date
            FROM daily_view
            ORDER BY trade_date DESC
            LIMIT {n}
        """
        return self._storage.execute_sql(sql)

    def close(self) -> None:
        self._storage.close()
