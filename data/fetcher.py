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
