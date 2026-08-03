"""Tushare data fetcher with retry and error handling."""

import time
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts

from config.settings import get_settings
from utils.logger import log


class TushareDataFetcher:
    """Encapsulates Tushare Pro API calls for stock data retrieval.

    Handles authentication, retries on transient failures, and returns
    empty DataFrames on unrecoverable errors (logging each failure).
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.tushare_token:
            raise ValueError(
                "TUSHARE_TOKEN not set. Please set it in .env or environment."
            )
        self._settings = settings
        self._pro = ts.pro_api(settings.tushare_token)
        self._max_retries = settings.max_retries
        self._retry_delay = settings.retry_delay

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_daily(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV data.

        Args:
            ts_code: Stock code in tushare format (e.g. '000001.SZ').
                     If None, fetches all stocks.
            start_date: Start date 'YYYYMMDD'.
            end_date: End date 'YYYYMMDD'.

        Returns:
            DataFrame with columns: ts_code, trade_date, open, high, low,
            close, pre_close, change, pct_chg, vol, amount.
        """
        if start_date is None:
            start_date = _default_start_date(self._settings.history_years)
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        log.info(
            "Fetching daily data | ts_code=%s | %s → %s",
            ts_code or "ALL",
            start_date,
            end_date,
        )

        def _call() -> pd.DataFrame:
            return self._pro.daily(
                ts_code=ts_code or "",
                start_date=start_date,
                end_date=end_date,
            )

        df = self._retry_call(_call, "daily")
        if df is None:
            return pd.DataFrame()

        # Standardize column names
        df = df.rename(columns={
            "trade_date": "trade_date",
            "ts_code": "ts_code",
        })
        return df

    def fetch_stock_basic(self, exchange: str = "") -> pd.DataFrame:
        """Fetch all stock basic information (name, industry, list date, etc.).

        Args:
            exchange: Exchange filter — 'SSE' (Shanghai), 'SZSE' (Shenzhen),
                      'BSE' (Beijing), or '' for all.

        Returns:
            DataFrame with stock metadata.
        """
        log.info("Fetching stock basic info | exchange=%s", exchange or "ALL")

        def _call() -> pd.DataFrame:
            return self._pro.stock_basic(
                exchange=exchange,
                list_status="L",
                fields=(
                    "ts_code,symbol,name,area,industry,fullname,enname,"
                    "cnspell,market,exchange,curr_type,list_status,"
                    "list_date,delist_date,is_hs,act_name,act_ent_type"
                ),
            )

        df = self._retry_call(_call, "stock_basic")
        return df if df is not None else pd.DataFrame()

    def fetch_income(
        self,
        ts_code: str | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        """Fetch income statement data via the standard ``income`` API.

        .. note::
           The Tushare ``income`` API **requires** ``ts_code`` as a
           mandatory parameter.  To fetch **all stocks** for a given
           period use :meth:`fetch_income_vip` instead — it supports
           queries without ``ts_code`` and has higher row limits.

        Args:
            ts_code: Stock code in tushare format (required by income API).
            period: Reporting-period end date 'YYYYMMDD' (quarter end).

        Returns:
            DataFrame with income statement columns.
        """
        if period is None:
            from data.updater import _get_quarter_end
            period = _get_quarter_end(datetime.today())

        if ts_code is None:
            raise ValueError(
                "ts_code is required for the standard income API. "
                "Use fetch_income_vip() to fetch all stocks, "
                "or provide a specific ts_code."
            )

        log.info(
            "Fetching income | ts_code=%s | period=%s",
            ts_code, period,
        )

        def _call() -> pd.DataFrame:
            kwargs: dict = {"ts_code": ts_code}
            if period:
                kwargs["period"] = period
            return self._pro.income(**kwargs)

        df = self._retry_call(_call, "income")
        return df if df is not None else pd.DataFrame()

    # ------------------------------------------------------------------
    # income_vip — Income Statement VIP (higher limits, optional ts_code)
    # ------------------------------------------------------------------

    def fetch_income_vip(
        self,
        ts_code: str | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        """Fetch income statement data via the ``income_vip`` API.

        Unlike the standard ``income`` API, ``income_vip`` allows
        ``ts_code`` to be omitted — when absent the API returns **all
        stocks** for the given *period* and has a higher row limit
        (tested at 12 000 rows / call).

        Args:
            ts_code: Stock code in tushare format (omit for all stocks).
            period: Reporting-period end date 'YYYYMMDD' (quarter end).

        Returns:
            DataFrame with income statement columns.
        """
        if period is None:
            from data.updater import _get_quarter_end
            period = _get_quarter_end(datetime.today())

        log.info(
            "Fetching income_vip | ts_code=%s | period=%s",
            ts_code or "ALL", period,
        )

        def _call() -> pd.DataFrame:
            kwargs: dict = {}
            if ts_code:
                kwargs["ts_code"] = ts_code
            if period:
                kwargs["period"] = period
            return self._pro.income_vip(**kwargs)

        df = self._retry_call(_call, "income_vip")
        return df if df is not None else pd.DataFrame()

    # ------------------------------------------------------------------
    # balancesheet_vip — Balance Sheet VIP (higher limits, optional ts_code)
    # ------------------------------------------------------------------

    def fetch_balancesheet_vip(
        self,
        ts_code: str | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        """Fetch balance sheet data via the ``balancesheet_vip`` API.

        Like ``income_vip``, ``balancesheet_vip`` allows ``ts_code`` to be
        omitted — when absent the API returns **all stocks** for the given
        *period* and has a higher row limit.

        Args:
            ts_code: Stock code in tushare format (omit for all stocks).
            period: Reporting-period end date 'YYYYMMDD' (quarter end).

        Returns:
            DataFrame with balance sheet columns.
        """
        if period is None:
            from data.updater import _get_quarter_end
            period = _get_quarter_end(datetime.today())

        log.info(
            "Fetching balancesheet_vip | ts_code=%s | period=%s",
            ts_code or "ALL", period,
        )

        def _call() -> pd.DataFrame:
            kwargs: dict = {}
            if ts_code:
                kwargs["ts_code"] = ts_code
            if period:
                kwargs["period"] = period
            return self._pro.balancesheet_vip(**kwargs)

        df = self._retry_call(_call, "balancesheet_vip")
        return df if df is not None else pd.DataFrame()

    # ------------------------------------------------------------------
    # cashflow_vip — Cashflow Statement VIP (higher limits, optional ts_code)
    # ------------------------------------------------------------------

    def fetch_cashflow_vip(
        self,
        ts_code: str | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        """Fetch cashflow statement data via the ``cashflow_vip`` API.

        Like ``income_vip``, ``cashflow_vip`` allows ``ts_code`` to be
        omitted — when absent the API returns **all stocks** for the given
        *period* and has a higher row limit.

        Args:
            ts_code: Stock code in tushare format (omit for all stocks).
            period: Reporting-period end date 'YYYYMMDD' (quarter end).

        Returns:
            DataFrame with cashflow statement columns.
        """
        if period is None:
            from data.updater import _get_quarter_end
            period = _get_quarter_end(datetime.today())

        log.info(
            "Fetching cashflow_vip | ts_code=%s | period=%s",
            ts_code or "ALL", period,
        )

        def _call() -> pd.DataFrame:
            kwargs: dict = {}
            if ts_code:
                kwargs["ts_code"] = ts_code
            if period:
                kwargs["period"] = period
            return self._pro.cashflow_vip(**kwargs)

        df = self._retry_call(_call, "cashflow_vip")
        return df if df is not None else pd.DataFrame()

    def fetch_trade_calendar(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        exchange: str = "",
    ) -> pd.DataFrame:
        """Fetch trading calendar from Tushare.

        Args:
            start_date: Start date 'YYYYMMDD' (default: 15 years ago).
            end_date: End date 'YYYYMMDD' (default: today).
            exchange: 'SSE', 'SZSE', 'BSE', or '' for all.

        Returns:
            DataFrame with columns: exchange, cal_date, is_open, pretrade_date.
        """
        if start_date is None:
            start_date = _default_start_date(self._settings.history_years)
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        log.info(
            "Fetching trade calendar | exchange=%s | %s → %s",
            exchange or "ALL", start_date, end_date,
        )

        def _call() -> pd.DataFrame:
            return self._pro.trade_cal(
                exchange=exchange,
                start_date=start_date,
                end_date=end_date,
                fields="exchange,cal_date,is_open,pretrade_date",
            )

        df = self._retry_call(_call, "trade_calendar")
        return df if df is not None else pd.DataFrame()

    def fetch_st_stocks(self) -> pd.DataFrame:
        """Fetch the current list of ST (Special Treatment) stocks.

        Strategy: fetch all listed stocks, then filter for names
        containing 'ST' (including '*ST').

        Returns:
            DataFrame with columns: ts_code, symbol, name, st_type,
            industry, list_date.
        """
        log.info("Fetching ST stock list")

        # Reuse stock_basic, then filter
        df = self.fetch_stock_basic()
        if df.empty:
            return df

        # Filter: name contains 'ST' (covers both 'ST' and '*ST')
        st_mask = df["name"].str.contains("ST", na=False)
        st_df = df[st_mask].copy()

        if st_df.empty:
            log.info("No ST stocks found.")
            return st_df

        # Derive st_type
        st_df["st_type"] = st_df["name"].apply(_classify_st)

        # Select and rename for output
        result = st_df[
            ["ts_code", "symbol", "name", "st_type", "industry", "list_date"]
        ].reset_index(drop=True)

        log.info("Found %d ST stocks (%d *ST, %d ST).",
                 len(result),
                 (result["st_type"] == "*ST").sum(),
                 (result["st_type"] == "ST").sum(),
                 )
        return result

    def fetch_daily_by_date(
        self, trade_date: str
    ) -> pd.DataFrame:
        """Fetch daily data for a single trading day across all stocks.

        Convenience wrapper around ``fetch_daily`` with ts_code=None.

        Args:
            trade_date: Trading date 'YYYYMMDD'.
        """
        return self.fetch_daily(
            ts_code=None, start_date=trade_date, end_date=trade_date
        )

    def fetch_adj_factor(
        self,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch adjustment factor (复权因子) data.

        Args:
            ts_code: Stock code e.g. '000001.SZ'. If None, fetches all stocks.
            trade_date: Single trading date 'YYYYMMDD'.
                        At least one of *ts_code* or *trade_date* is required
                        by the Tushare API.
            start_date: Start date 'YYYYMMDD' (default: 15 years ago).
            end_date: End date 'YYYYMMDD' (default: today).

        Returns:
            DataFrame with columns: ts_code, trade_date, adj_factor.
        """
        if start_date is None and trade_date is None:
            start_date = _default_start_date(self._settings.history_years)
        if end_date is None and trade_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        log.info(
            "Fetching adj_factor | ts_code=%s | trade_date=%s | %s → %s",
            ts_code or "ALL",
            trade_date or "-",
            start_date or "-",
            end_date or "-",
        )

        def _call() -> pd.DataFrame:
            kwargs: dict = {}
            if ts_code:
                kwargs["ts_code"] = ts_code
            if trade_date:
                kwargs["trade_date"] = trade_date
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return self._pro.adj_factor(**kwargs)

        df = self._retry_call(_call, "adj_factor")
        return df if df is not None else pd.DataFrame()

    def fetch_index_basic(self, market: str = "") -> pd.DataFrame:
        """Fetch index basic information (指数基础信息).

        Args:
            market: Market filter — 'CSI' (中证指数), 'SSE' (上证指数),
                    'SZSE' (深证指数), or '' for all markets.

        Returns:
            DataFrame with columns: ts_code, name, fullname, market,
            publisher, index_type, category, base_date, base_point,
            list_date, weight_rule, desc, exp_date.
        """
        log.info("Fetching index basic info | market=%s", market or "ALL")

        def _call() -> pd.DataFrame:
            return self._pro.index_basic(market=market)

        df = self._retry_call(_call, "index_basic")
        return df if df is not None else pd.DataFrame()

    def fetch_index_weight(
        self,
        index_code: str,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch index constituent weight data (指数成分权重).

        Args:
            index_code: Index code e.g. '000300.SH', '000905.SH'.
            trade_date: Single trading date 'YYYYMMDD' (month-end).
            start_date: Start date 'YYYYMMDD'.
            end_date: End date 'YYYYMMDD'.

        Returns:
            DataFrame with columns: index_code, con_code, trade_date, weight.
        """
        log.info(
            "Fetching index_weight | index_code=%s | trade_date=%s | %s → %s",
            index_code,
            trade_date or "-",
            start_date or "-",
            end_date or "-",
        )

        def _call() -> pd.DataFrame:
            kwargs: dict = {"index_code": index_code}
            if trade_date:
                kwargs["trade_date"] = trade_date
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return self._pro.index_weight(**kwargs)

        df = self._retry_call(_call, "index_weight")
        return df if df is not None else pd.DataFrame()

    def fetch_index_daily(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch index daily OHLCV data (指数日线行情).

        Args:
            ts_code: Index code e.g. '000300.SH', '000905.SH'.
            start_date: Start date 'YYYYMMDD' (default: 13 years ago).
            end_date: End date 'YYYYMMDD' (default: today).

        Returns:
            DataFrame with columns: ts_code, trade_date, close, open, high,
            low, pre_close, change, pct_chg, vol, amount.
        """
        if start_date is None:
            start_date = _default_start_date(self._settings.history_years)
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        log.info(
            "Fetching index_daily | ts_code=%s | %s → %s",
            ts_code, start_date, end_date,
        )

        def _call() -> pd.DataFrame:
            return self._pro.index_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )

        df = self._retry_call(_call, "index_daily")
        return df if df is not None else pd.DataFrame()

    def fetch_moneyflow(
        self,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch moneyflow (个股资金流向) data.

        Args:
            ts_code: Stock code e.g. '000001.SZ'. If None, fetches all stocks.
            trade_date: Single trading date 'YYYYMMDD'.
                        At least one of *ts_code* or *trade_date* is required
                        by the Tushare API.
            start_date: Start date 'YYYYMMDD' (default: 15 years ago).
            end_date: End date 'YYYYMMDD' (default: today).

        Returns:
            DataFrame with columns: ts_code, trade_date, buy_sm_vol,
            buy_sm_amount, sell_sm_vol, sell_sm_amount, buy_md_vol,
            buy_md_amount, sell_md_vol, sell_md_amount, buy_lg_vol,
            buy_lg_amount, sell_lg_vol, sell_lg_amount, buy_elg_vol,
            buy_elg_amount, sell_elg_vol, sell_elg_amount, net_mf_vol,
            net_mf_amount.
        """
        if start_date is None and trade_date is None:
            start_date = _default_start_date(self._settings.history_years)
        if end_date is None and trade_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        log.info(
            "Fetching moneyflow | ts_code=%s | trade_date=%s | %s → %s",
            ts_code or "ALL",
            trade_date or "-",
            start_date or "-",
            end_date or "-",
        )

        def _call() -> pd.DataFrame:
            kwargs: dict = {}
            if ts_code:
                kwargs["ts_code"] = ts_code
            if trade_date:
                kwargs["trade_date"] = trade_date
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return self._pro.moneyflow(**kwargs)

        df = self._retry_call(_call, "moneyflow")
        return df if df is not None else pd.DataFrame()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _retry_call(
        self,
        func,
        label: str,
    ) -> pd.DataFrame | None:
        """Call *func* with retries on failure.

        Returns the DataFrame on success, or None after exhausting retries.
        Logs each attempt and failure.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                df = func()
                if df is None or df.empty:
                    log.warning(
                        "%s: attempt %d returned empty DataFrame", label, attempt
                    )
                return df
            except Exception as e:
                last_exc = e
                log.error(
                    "%s: attempt %d/%d failed — %s: %s",
                    label,
                    attempt,
                    self._max_retries,
                    type(e).__name__,
                    e,
                )
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay * attempt)  # exponential-ish
        log.critical(
            "%s: all %d attempts failed. Last error: %s",
            label,
            self._max_retries,
            last_exc,
        )
        return None


# ------------------------------------------------------------------
# Module helpers
# ------------------------------------------------------------------

def _default_start_date(years_back: int) -> str:
    """Return a date string 'YYYYMMDD' *years_back* years ago."""
    return (datetime.today() - timedelta(days=years_back * 365)).strftime(
        "%Y%m%d"
    )


def _classify_st(name: str) -> str:
    """Classify an ST stock name as '\*ST' or 'ST'."""
    if name is None:
        return "ST"
    if name.startswith("*ST"):
        return "*ST"
    if "ST" in name:
        return "ST"
    return "ST"
