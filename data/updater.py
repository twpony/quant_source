"""Daily (incremental) and full-refresh data update logic.

- ``DailyUpdater.update_incremental()`` — fetches the current trading day
  plus the previous 3 trading days and merges them into storage.
- ``DailyUpdater.update_full()`` — re-fetches 15 years of history for all
  stocks and replaces the data.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

import pandas as pd

from data.fetcher import TushareDataFetcher
from data.storage import DataStorage
from utils.logger import log


class DailyUpdater:
    """Orchestrates data updates: incremental (daily) or full historical."""

    def __init__(
        self,
        fetcher: TushareDataFetcher | None = None,
        storage: DataStorage | None = None,
    ) -> None:
        self._fetcher = fetcher or TushareDataFetcher()
        self._storage = storage or DataStorage()

    # ------------------------------------------------------------------
    # Incremental update (daily)
    # ------------------------------------------------------------------

    def update_incremental(self, months: int = 3) -> dict[str, int]:
        """Fetch and merge recent data.

        Strategy:
        1. Fetch daily data for the current trading day + previous 3 trading days.
        2. Re-fetch stock_basic (lightweight, always current).
        3. Fetch income data within *months* lookback.
        4. Fetch trading calendar within *months* lookback.

        Args:
            months: Number of months to look back from today (for non-daily data).

        Returns:
            Dict mapping data_type → rows added.
        """
        log.info("=" * 60)
        log.info("Starting INCREMENTAL update (months=%d)", months)
        log.info("=" * 60)

        results: dict[str, int] = {}

        # --- Daily data ---
        results["daily"] = self._update_daily_incremental(months=months)

        # --- Stock basic (always refresh — lightweight) ---
        results["stock_basic"] = self._update_stock_basic()

        # --- Income data ---
        results["income"] = self._update_income_incremental(months=months)

        # --- Cashflow data ---
        results["cashflow"] = self._update_cashflow_incremental(months=months)

        # --- Balance Sheet data ---
        results["balancesheet"] = self._update_balancesheet_incremental(months=months)

        # --- Trading calendar ---
        results["trade_calendar"] = self._update_trade_calendar_incremental(months=months)

        # --- ST stocks (always refresh — lightweight) ---
        results["st_stocks"] = self._update_st_stocks()

        self._log_summary(results)
        return results

    # ------------------------------------------------------------------
    # Full refresh
    # ------------------------------------------------------------------

    def update_full(self) -> dict[str, int]:
        """Full historical data refresh (10 years).

        Returns:
            Dict mapping data_type → rows written.
        """
        log.info("=" * 60)
        log.info("Starting FULL historical update (10 years)")
        log.info("=" * 60)

        results: dict[str, int] = {}

        # --- Stock basic ---
        results["stock_basic"] = self._update_stock_basic()

        # --- Daily data for all stocks (batched) ---
        results["daily"] = self._update_daily_full()

        # --- Income data for all stocks ---
        results["income"] = self._update_income_full()

        # --- Cashflow data for all stocks ---
        results["cashflow"] = self._update_cashflow_full()

        # --- Balance Sheet data for all stocks ---
        results["balancesheet"] = self._update_balancesheet_full()

        # --- Trading calendar (full 15 years) ---
        results["trade_calendar"] = self._update_trade_calendar_full()

        # --- ST stocks ---
        results["st_stocks"] = self._update_st_stocks()

        self._log_summary(results)
        return results

    # ------------------------------------------------------------------
    # Private: incremental
    # ------------------------------------------------------------------

    def _update_daily_incremental(self, months: int = 3) -> int:
        """Fetch daily data for the current trading day + previous 3 trading days.

        Uses the trade calendar to determine the most recent 4 trading days,
        then fetches only those that are missing from storage.
        """
        log.info("--- Daily data (incremental, last 4 trading days) ---")

        today = datetime.today()
        today_str = today.strftime("%Y%m%d")

        # 1. Get the last 4 trading days from the trade calendar
        try:
            recent_dates_df = self._storage.execute_sql(
                f"SELECT DISTINCT cal_date FROM trade_calendar_view "
                f"WHERE is_open = 1 AND exchange = 'SSE' "
                f"AND cal_date <= '{today_str}' "
                f"ORDER BY cal_date DESC "
                f"LIMIT 4"
            )
        except Exception:
            log.warning("Trade calendar unavailable, falling back to date range.")
            recent_dates_df = None

        if recent_dates_df is not None and not recent_dates_df.empty:
            target_dates = set(recent_dates_df["cal_date"].tolist())
        else:
            # Fallback: use the last 4 calendar days (not ideal but safe)
            target_dates = {
                (today - timedelta(days=i)).strftime("%Y%m%d")
                for i in range(4)
            }

        log.info("Target trading days: %s", sorted(target_dates))

        # 2. Find which of these dates are already stored
        try:
            existing_df = self._storage.execute_sql(
                "SELECT DISTINCT trade_date FROM daily_view "
                "WHERE trade_date IN ({})".format(
                    ",".join(f"'{d}'" for d in target_dates)
                )
            )
            existing_dates = set(existing_df["trade_date"].tolist())
        except Exception:
            existing_dates = set()

        missing_dates = target_dates - existing_dates

        if not missing_dates:
            log.info(
                "Daily data already up-to-date for last 4 trading days. Skipping."
            )
            return 0

        log.info(
            "%d/%d trading days already stored, %d missing: %s",
            len(existing_dates), len(target_dates),
            len(missing_dates), sorted(missing_dates),
        )

        # 3. Fetch from earliest missing date to today
        earliest_missing = min(missing_dates)
        log.info("Fetching daily data from %s to %s", earliest_missing, today_str)
        df = self._fetcher.fetch_daily(
            start_date=earliest_missing, end_date=today_str,
        )

        if df.empty:
            log.warning("No new daily data returned.")
            return 0

        # 4. Only keep rows for the missing dates (in case API returns extra)
        df = df[df["trade_date"].isin(missing_dates)]
        if df.empty:
            log.warning("No data for missing dates after filtering.")
            return 0

        return self._storage.save_daily(df)

    def _update_income_incremental(self, months: int = 3) -> int:
        """Update income data for current + previous quarter.

        Uses ``income_vip`` to fetch all stocks for the current quarter
        and the previous quarter.  This is the default update mode.

        Args:
            months: Ignored for the quarter-based approach; kept for
                    interface compatibility.
        """
        log.info("--- Income data (incremental — current + previous quarter) ---")

        today = datetime.today()
        current_q = _get_quarter_end(today)
        prev_q = _prev_quarter_end(current_q)

        periods = [current_q, prev_q]
        log.info("Target reporting periods: %s", periods)

        total_rows = 0
        for period in periods:
            log.info("Fetching income_vip for period=%s (all stocks)", period)
            df = self._fetcher.fetch_income_vip(period=period)
            if df.empty:
                log.warning(
                    "  period=%s returned empty (may not yet be reported).", period
                )
                continue
            rows = self._storage.save_income(df)
            log.info("  period=%s: saved %d rows.", period, rows)
            total_rows += rows

        return total_rows

    def _update_balancesheet_incremental(self, months: int = 3) -> int:
        """Update balance sheet data for current + previous quarter.

        Uses ``balancesheet_vip`` to fetch all stocks for the current
        quarter and the previous quarter.

        Args:
            months: Ignored for the quarter-based approach; kept for
                    interface compatibility.
        """
        log.info("--- Balance Sheet data (incremental — current + previous quarter) ---")

        today = datetime.today()
        current_q = _get_quarter_end(today)
        prev_q = _prev_quarter_end(current_q)

        periods = [current_q, prev_q]
        log.info("Target reporting periods: %s", periods)

        total_rows = 0
        for period in periods:
            log.info(
                "Fetching balancesheet_vip for period=%s (all stocks)", period
            )
            df = self._fetcher.fetch_balancesheet_vip(period=period)
            if df.empty:
                log.warning(
                    "  period=%s returned empty (may not yet be reported).", period
                )
                continue
            rows = self._storage.save_balancesheet(df)
            log.info("  period=%s: saved %d rows.", period, rows)
            total_rows += rows

        return total_rows

    def _update_cashflow_incremental(self, months: int = 3) -> int:
        """Update cashflow data for current + previous quarter.

        Uses ``cashflow_vip`` to fetch all stocks for the current
        quarter and the previous quarter.

        Args:
            months: Ignored for the quarter-based approach; kept for
                    interface compatibility.
        """
        log.info("--- Cashflow data (incremental — current + previous quarter) ---")

        today = datetime.today()
        current_q = _get_quarter_end(today)
        prev_q = _prev_quarter_end(current_q)

        periods = [current_q, prev_q]
        log.info("Target reporting periods: %s", periods)

        total_rows = 0
        for period in periods:
            log.info(
                "Fetching cashflow_vip for period=%s (all stocks)", period
            )
            df = self._fetcher.fetch_cashflow_vip(period=period)
            if df.empty:
                log.warning(
                    "  period=%s returned empty (may not yet be reported).", period
                )
                continue
            rows = self._storage.save_cashflow(df)
            log.info("  period=%s: saved %d rows.", period, rows)
            total_rows += rows

        return total_rows

    # ------------------------------------------------------------------
    # Private: full
    # ------------------------------------------------------------------

    def _update_daily_full(self) -> int:
        """Fetch full 15-year daily data — batched by month via trade calendar."""
        log.info("--- Daily data (full, batched) ---")

        # 1. Get all trading days from the stored calendar
        try:
            cal_df = self._storage.execute_sql(
                "SELECT DISTINCT cal_date FROM trade_calendar_view "
                "WHERE is_open = 1 AND exchange = 'SSE' "
                "ORDER BY cal_date"
            )
        except Exception:
            log.warning("Trade calendar not available, falling back to date range.")
            df = self._fetcher.fetch_daily()
            return self._storage.save_daily(df) if not df.empty else 0

        if cal_df.empty:
            log.warning("Trade calendar empty, falling back to date range.")
            df = self._fetcher.fetch_daily()
            return self._storage.save_daily(df) if not df.empty else 0

        all_dates = cal_df["cal_date"].tolist()
        log.info("Found %d trading days in calendar.", len(all_dates))

        # Determine which dates are already stored
        try:
            existing_df = self._storage.execute_sql(
                "SELECT DISTINCT trade_date FROM daily_view"
            )
            existing_dates = set(existing_df["trade_date"].tolist())
        except Exception:
            existing_dates = set()

        missing_dates = [d for d in all_dates if d not in existing_dates]
        log.info(
            "%d already stored, %d missing trading days to fetch.",
            len(existing_dates), len(missing_dates),
        )

        if not missing_dates:
            log.info("Daily data already complete. Nothing to fetch.")
            return 0

        # 2. Batch — 1 day per call to avoid Tushare 6000-row limit
        total_rows = 0
        batch_size = 1  # one trading day per API call ensures no truncation

        for i in range(0, len(missing_dates), batch_size):
            batch = missing_dates[i : i + batch_size]
            start = batch[0]
            end = batch[-1]

            batch_num = i // batch_size + 1
            total_batches = (len(missing_dates) + batch_size - 1) // batch_size

            log.info(
                "Batch %d/%d: %s (%d days)",
                batch_num, total_batches, start, len(batch),
            )

            df = self._fetcher.fetch_daily(start_date=start, end_date=end)
            if df.empty:
                log.warning("Batch %s→%s returned empty, skipping.", start, end)
                continue

            rows = self._storage.save_daily(df)
            total_rows += rows
            log.info("Batch saved: %d rows (running total: %d).", rows, total_rows)

        return total_rows

    def _update_income_full(self) -> int:
        """Fetch all historical quarters using ``income_vip`` API.

        Iterates through every quarter from *history_years* ago to today.
        For each quarter the API is called **without ts_code** so all
        stocks are returned in one call (``income_vip`` supports higher
        row limits than the standard ``income`` endpoint).
        """
        log.info("--- Income data (full, quarter-by-quarter via income_vip) ---")

        from config.settings import get_settings
        settings = get_settings()
        start_year = datetime.today().year - settings.history_years
        end_year = datetime.today().year

        quarters = _generate_quarter_ends(start_year, end_year)
        log.info(
            "Will fetch %d quarters (%d–%d).", len(quarters), start_year, end_year
        )

        total_rows = 0
        for i, period in enumerate(quarters, 1):
            log.info(
                "[%d/%d] Fetching income_vip for period=%s",
                i, len(quarters), period,
            )
            df = self._fetcher.fetch_income_vip(period=period)
            if df.empty:
                log.warning(
                    "  period=%s returned empty (may not yet be reported).", period
                )
                continue
            rows = self._storage.save_income(df)
            log.info("  period=%s: saved %d rows.", period, rows)
            total_rows += rows

        return total_rows

    def _update_balancesheet_full(self) -> int:
        """Fetch all historical quarters using ``balancesheet_vip`` API.

        Iterates through every quarter from *history_years* ago to today.
        For each quarter the API is called **without ts_code** so all
        stocks are returned in one call (``balancesheet_vip`` supports
        higher row limits than the standard ``balancesheet`` endpoint).
        """
        log.info(
            "--- Balance Sheet data (full, quarter-by-quarter via balancesheet_vip) ---"
        )

        from config.settings import get_settings
        settings = get_settings()
        start_year = datetime.today().year - settings.history_years
        end_year = datetime.today().year

        quarters = _generate_quarter_ends(start_year, end_year)
        log.info(
            "Will fetch %d quarters (%d–%d).", len(quarters), start_year, end_year
        )

        total_rows = 0
        for i, period in enumerate(quarters, 1):
            log.info(
                "[%d/%d] Fetching balancesheet_vip for period=%s",
                i, len(quarters), period,
            )
            df = self._fetcher.fetch_balancesheet_vip(period=period)
            if df.empty:
                log.warning(
                    "  period=%s returned empty (may not yet be reported).", period
                )
                continue
            rows = self._storage.save_balancesheet(df)
            log.info("  period=%s: saved %d rows.", period, rows)
            total_rows += rows

        return total_rows

    def _update_cashflow_full(self) -> int:
        """Fetch all historical quarters using ``cashflow_vip`` API.

        Iterates through every quarter from *history_years* ago to today.
        For each quarter the API is called **without ts_code** so all
        stocks are returned in one call (``cashflow_vip`` supports higher
        row limits than the standard ``cashflow`` endpoint).
        """
        log.info(
            "--- Cashflow data (full, quarter-by-quarter via cashflow_vip) ---"
        )

        from config.settings import get_settings
        settings = get_settings()
        start_year = datetime.today().year - settings.history_years
        end_year = datetime.today().year

        quarters = _generate_quarter_ends(start_year, end_year)
        log.info(
            "Will fetch %d quarters (%d–%d).", len(quarters), start_year, end_year
        )

        total_rows = 0
        for i, period in enumerate(quarters, 1):
            log.info(
                "[%d/%d] Fetching cashflow_vip for period=%s",
                i, len(quarters), period,
            )
            df = self._fetcher.fetch_cashflow_vip(period=period)
            if df.empty:
                log.warning(
                    "  period=%s returned empty (may not yet be reported).", period
                )
                continue
            rows = self._storage.save_cashflow(df)
            log.info("  period=%s: saved %d rows.", period, rows)
            total_rows += rows

        return total_rows

    def _update_stock_basic(self) -> int:
        """Refresh stock_basic. Always cheap — ~5000 rows."""
        log.info("--- Stock basic info ---")
        df = self._fetcher.fetch_stock_basic()
        if df.empty:
            log.error("Stock basic fetch returned empty.")
            return 0
        return self._storage.save_stock_basic(df)

    def _update_trade_calendar_incremental(self, months: int = 3) -> int:
        """Fetch trading calendar for the last *months* months."""
        log.info("--- Trade calendar (incremental, months=%d) ---", months)
        today = datetime.today()
        start = _months_ago(today, months).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        log.info("Fetching trade calendar from %s to %s", start, end)
        df = self._fetcher.fetch_trade_calendar(start_date=start, end_date=end)
        if df.empty:
            log.warning("No new trade calendar data returned.")
            return 0
        return self._storage.save_trade_calendar(df)

    def _update_trade_calendar_full(self) -> int:
        """Fetch full 15-year trading calendar."""
        log.info("--- Trade calendar (full) ---")
        df = self._fetcher.fetch_trade_calendar()
        if df.empty:
            log.error("Full trade calendar fetch returned empty.")
            return 0
        return self._storage.save_trade_calendar(df)

    def _update_st_stocks(self) -> int:
        """Refresh current ST stock list."""
        log.info("--- ST stocks ---")
        df = self._fetcher.fetch_st_stocks()
        if df.empty:
            log.warning("ST stock list is empty (may be normal).")
            return 0
        return self._storage.save_st_stocks(df)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log_summary(results: dict[str, int]) -> None:
        log.info("=" * 60)
        log.info("Update complete. Summary:")
        for data_type, rows in results.items():
            log.info("  %s: %d rows", data_type, rows)
        log.info("=" * 60)


def _next_day(date_str: str) -> str:
    """Return the next calendar day as 'YYYYMMDD'."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return (dt + timedelta(days=1)).strftime("%Y%m%d")


def _months_ago(dt: datetime, months: int) -> datetime:
    """Return a datetime *months* before *dt*, clamped to the 1st of the month."""
    # Pure month subtraction — handles year boundaries correctly.
    year = dt.year
    month = dt.month - months
    while month <= 0:
        month += 12
        year -= 1
    # Clamp day to valid range for the target month
    max_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, max_day)
    return dt.replace(year=year, month=month, day=day)


# ------------------------------------------------------------------
# Quarter helpers (for income data via income API)
# ------------------------------------------------------------------

_QUARTER_ENDS = ("0331", "0630", "0930", "1231")


def _get_quarter_end(dt: datetime) -> str:
    """Return the reporting-period end date 'YYYYMMDD' for the quarter
    that contains *dt*."""
    year = dt.year
    month = dt.month
    if month <= 3:
        return f"{year}0331"
    elif month <= 6:
        return f"{year}0630"
    elif month <= 9:
        return f"{year}0930"
    else:
        return f"{year}1231"


def _prev_quarter_end(end_date: str) -> str:
    """Return the previous quarter's end date given a quarter end date."""
    year = int(end_date[:4])
    mmdd = end_date[4:]
    idx = _QUARTER_ENDS.index(mmdd)
    if idx == 0:
        return f"{year - 1}1231"
    else:
        return f"{year}{_QUARTER_ENDS[idx - 1]}"


def _generate_quarter_ends(start_year: int, end_year: int) -> list[str]:
    """Generate all quarter end dates from *start_year* to *end_year*
    (inclusive).  Future quarters (end_date > today) are excluded."""
    today_str = datetime.today().strftime("%Y%m%d")
    dates: list[str] = []
    for year in range(start_year, end_year + 1):
        for end in _QUARTER_ENDS:
            d = f"{year}{end}"
            if d <= today_str:
                dates.append(d)
    return dates
