"""Daily (incremental) and full-refresh data update logic.

- ``DailyUpdater.update_incremental()`` — fetches recent trading days
  (default: 1 month lookback) and merges them into storage.
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
        1. Fetch daily data for the last *months* months (one day at a time).
        2. Re-fetch stock_basic (lightweight, always current).
        3. Fetch income / cashflow / balancesheet for current + previous quarter.
        4. Fetch trading calendar within *months* lookback.

        Args:
            months: Number of months to look back from today.

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

        # --- Adjustment factors ---
        results["adjfactor"] = self._update_adjfactor_incremental(months=months)

        # --- Moneyflow data ---
        results["moneyflow"] = self._update_moneyflow_incremental(months=months)

        # --- ST stocks (always refresh — lightweight) ---
        results["st_stocks"] = self._update_st_stocks()

        # --- Index basic (always refresh — lightweight) ---
        results["index_basic"] = self._update_index_basic()

        # --- Index weight ---
        results["index_weight"] = self._update_index_weight_incremental(months=months)

        # --- Index daily ---
        results["index_daily"] = self._update_index_daily_incremental(months=months)

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

        # --- Adjustment factors ---
        results["adjfactor"] = self._update_adjfactor_full()

        # --- Moneyflow data ---
        results["moneyflow"] = self._update_moneyflow_full()

        # --- ST stocks ---
        results["st_stocks"] = self._update_st_stocks()

        # --- Index basic ---
        results["index_basic"] = self._update_index_basic()

        # --- Index weight ---
        results["index_weight"] = self._update_index_weight_full()

        # --- Index daily ---
        results["index_daily"] = self._update_index_daily_full()

        self._log_summary(results)
        return results

    # ------------------------------------------------------------------
    # Private: incremental
    # ------------------------------------------------------------------

    def _update_daily_incremental(self, months: int = 1, days: int | None = None) -> int:
        """Fetch daily data for the last *months* months or last *days* trading days.

        Uses the trade calendar to determine which trading days in the
        lookback window are missing from storage, then fetches them
        one day at a time to avoid exceeding Tushare API row limits
        (6000 rows / call).  Already-stored dates are skipped.

        Args:
            months: Number of months to look back from today (used when days is None).
            days: If provided, look back exactly this many trading days instead of
                  using the months-based window.
        """
        today = datetime.today()
        today_str = today.strftime("%Y%m%d")

        if days is not None:
            log.info("--- Daily data (incremental, last %d trading day(s)) ---", days)
            # Look back exactly N trading days from the calendar
            try:
                cal_df = self._storage.execute_sql(
                    f"SELECT DISTINCT cal_date FROM trade_calendar_view "
                    f"WHERE is_open = 1 AND exchange = 'SSE' "
                    f"AND cal_date <= '{today_str}' "
                    f"ORDER BY cal_date DESC "
                    f"LIMIT {days}"
                )
            except Exception:
                log.warning("Trade calendar unavailable, falling back to date range.")
                cal_df = None

            if cal_df is not None and not cal_df.empty:
                target_dates = set(cal_df["cal_date"].tolist())
            else:
                # Fallback: last N calendar days
                target_dates = set()
                d = today
                for _ in range(days * 2):  # overshoot to account for weekends
                    target_dates.add(d.strftime("%Y%m%d"))
                    d -= timedelta(days=1)
                    if len(target_dates) >= days:
                        break

            start_date = min(target_dates) if target_dates else today_str
        else:
            log.info("--- Daily data (incremental, last %d month(s)) ---", months)
            start_date = _months_ago(today, months).strftime("%Y%m%d")

            # 1. Get all trading days in the lookback window
            try:
                cal_df = self._storage.execute_sql(
                    f"SELECT DISTINCT cal_date FROM trade_calendar_view "
                    f"WHERE is_open = 1 AND exchange = 'SSE' "
                    f"AND cal_date >= '{start_date}' "
                    f"AND cal_date <= '{today_str}' "
                    f"ORDER BY cal_date"
                )
            except Exception:
                log.warning("Trade calendar unavailable, falling back to date range.")
                cal_df = None

            if cal_df is not None and not cal_df.empty:
                target_dates = set(cal_df["cal_date"].tolist())
            else:
                # Fallback: every calendar day in the window
                target_dates = set()
                d = today
                for _ in range(months * 31):
                    target_dates.add(d.strftime("%Y%m%d"))
                    d -= timedelta(days=1)

        log.info(
            "Lookback window: %s → %s (%d trading days)",
            min(target_dates) if target_dates else today_str,
            today_str,
            len(target_dates),
        )

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

        missing_dates = sorted(target_dates - existing_dates)

        if not missing_dates:
            log.info("Daily data already up-to-date. Nothing to fetch.")
            return 0

        log.info(
            "%d/%d trading days already stored, %d missing to fetch.",
            len(existing_dates), len(target_dates), len(missing_dates),
        )

        # 3. Fetch one day at a time to stay under Tushare's 6000-row limit
        total_rows = 0
        for i, trade_date in enumerate(missing_dates, 1):
            log.info(
                "[%d/%d] Fetching daily data for %s",
                i, len(missing_dates), trade_date,
            )
            df = self._fetcher.fetch_daily(
                start_date=trade_date, end_date=trade_date,
            )
            if df.empty:
                log.warning("  %s returned empty, skipping.", trade_date)
                continue
            rows = self._storage.save_daily(df)
            total_rows += rows
            log.info(
                "  %s: saved %d rows (running total: %d).",
                trade_date, rows, total_rows,
            )

        return total_rows

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

    def _update_adjfactor_incremental(self, months: int = 1) -> int:
        """Fetch adj_factor for trading days in the last *months* months.

        Uses the trade calendar to determine which trading days in the
        lookback window are missing from storage, then fetches them
        one day at a time.  Already-stored dates are skipped.
        """
        log.info("--- Adj factor data (incremental, last %d month(s)) ---", months)

        today = datetime.today()
        today_str = today.strftime("%Y%m%d")
        start_date = _months_ago(today, months).strftime("%Y%m%d")

        # 1. Get all trading days in the lookback window
        try:
            cal_df = self._storage.execute_sql(
                f"SELECT DISTINCT cal_date FROM trade_calendar_view "
                f"WHERE is_open = 1 AND exchange = 'SSE' "
                f"AND cal_date >= '{start_date}' "
                f"AND cal_date <= '{today_str}' "
                f"ORDER BY cal_date"
            )
        except Exception:
            log.warning("Trade calendar unavailable, falling back to date range.")
            cal_df = None

        if cal_df is not None and not cal_df.empty:
            target_dates = set(cal_df["cal_date"].tolist())
        else:
            target_dates = set()
            d = today
            for _ in range(months * 31):
                target_dates.add(d.strftime("%Y%m%d"))
                d -= timedelta(days=1)

        log.info(
            "Lookback window: %s → %s (%d calendar days)",
            start_date, today_str, len(target_dates),
        )

        # 2. Find which dates are already stored
        try:
            existing_df = self._storage.execute_sql(
                "SELECT DISTINCT trade_date FROM adjfactor_view "
                "WHERE trade_date IN ({})".format(
                    ",".join(f"'{d}'" for d in target_dates)
                )
            )
            existing_dates = set(existing_df["trade_date"].tolist())
        except Exception:
            existing_dates = set()

        missing_dates = sorted(target_dates - existing_dates)

        if not missing_dates:
            log.info("Adj factor data already up-to-date. Nothing to fetch.")
            return 0

        log.info(
            "%d/%d dates already stored, %d missing to fetch.",
            len(existing_dates), len(target_dates), len(missing_dates),
        )

        # 3. Fetch one day at a time
        total_rows = 0
        for i, trade_date in enumerate(missing_dates, 1):
            log.info(
                "[%d/%d] Fetching adj_factor for %s",
                i, len(missing_dates), trade_date,
            )
            df = self._fetcher.fetch_adj_factor(
                start_date=trade_date, end_date=trade_date,
            )
            if df.empty:
                log.warning("  %s returned empty, skipping.", trade_date)
                continue
            rows = self._storage.save_adjfactor(df)
            total_rows += rows
            log.info(
                "  %s: saved %d rows (running total: %d).",
                trade_date, rows, total_rows,
            )

        return total_rows

    def _update_moneyflow_incremental(self, months: int = 1) -> int:
        """Fetch moneyflow for trading days in the last *months* months.

        Uses the trade calendar to determine which trading days in the
        lookback window are missing from storage, then fetches them
        one day at a time.  Already-stored dates are skipped.
        """
        log.info("--- Moneyflow data (incremental, last %d month(s)) ---", months)

        today = datetime.today()
        today_str = today.strftime("%Y%m%d")
        start_date = _months_ago(today, months).strftime("%Y%m%d")

        # 1. Get all trading days in the lookback window
        try:
            cal_df = self._storage.execute_sql(
                f"SELECT DISTINCT cal_date FROM trade_calendar_view "
                f"WHERE is_open = 1 AND exchange = 'SSE' "
                f"AND cal_date >= '{start_date}' "
                f"AND cal_date <= '{today_str}' "
                f"ORDER BY cal_date"
            )
        except Exception:
            log.warning("Trade calendar unavailable, falling back to date range.")
            cal_df = None

        if cal_df is not None and not cal_df.empty:
            target_dates = set(cal_df["cal_date"].tolist())
        else:
            target_dates = set()
            d = today
            for _ in range(months * 31):
                target_dates.add(d.strftime("%Y%m%d"))
                d -= timedelta(days=1)

        log.info(
            "Lookback window: %s → %s (%d calendar days)",
            start_date, today_str, len(target_dates),
        )

        # 2. Find which dates are already stored
        try:
            existing_df = self._storage.execute_sql(
                "SELECT DISTINCT trade_date FROM moneyflow_view "
                "WHERE trade_date IN ({})".format(
                    ",".join(f"'{d}'" for d in target_dates)
                )
            )
            existing_dates = set(existing_df["trade_date"].tolist())
        except Exception:
            existing_dates = set()

        missing_dates = sorted(target_dates - existing_dates)

        if not missing_dates:
            log.info("Moneyflow data already up-to-date. Nothing to fetch.")
            return 0

        log.info(
            "%d/%d dates already stored, %d missing to fetch.",
            len(existing_dates), len(target_dates), len(missing_dates),
        )

        # 3. Fetch one day at a time
        total_rows = 0
        for i, trade_date in enumerate(missing_dates, 1):
            log.info(
                "[%d/%d] Fetching moneyflow for %s",
                i, len(missing_dates), trade_date,
            )
            df = self._fetcher.fetch_moneyflow(
                trade_date=trade_date,
            )
            if df.empty:
                log.warning("  %s returned empty, skipping.", trade_date)
                continue
            rows = self._storage.save_moneyflow(df)
            total_rows += rows
            log.info(
                "  %s: saved %d rows (running total: %d).",
                trade_date, rows, total_rows,
            )

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

    def _update_adjfactor_full(self) -> int:
        """Fetch full 15-year adj_factor data — batched by trading day."""
        log.info("--- Adj factor data (full, batched by trading day) ---")

        # 1. Get all trading days from the stored calendar
        try:
            cal_df = self._storage.execute_sql(
                "SELECT DISTINCT cal_date FROM trade_calendar_view "
                "WHERE is_open = 1 AND exchange = 'SSE' "
                "ORDER BY cal_date"
            )
        except Exception:
            log.warning("Trade calendar not available, falling back to date range.")
            df = self._fetcher.fetch_adj_factor()
            return self._storage.save_adjfactor(df) if not df.empty else 0

        if cal_df.empty:
            log.warning("Trade calendar empty, falling back to date range.")
            df = self._fetcher.fetch_adj_factor()
            return self._storage.save_adjfactor(df) if not df.empty else 0

        all_dates = cal_df["cal_date"].tolist()
        log.info("Found %d trading days in calendar.", len(all_dates))

        # Determine which dates are already stored
        try:
            existing_df = self._storage.execute_sql(
                "SELECT DISTINCT trade_date FROM adjfactor_view"
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
            log.info("Adj factor data already complete. Nothing to fetch.")
            return 0

        # 2. Fetch one day at a time
        total_rows = 0
        for i, trade_date in enumerate(missing_dates, 1):
            log.info(
                "[%d/%d] Fetching adj_factor for %s",
                i, len(missing_dates), trade_date,
            )
            df = self._fetcher.fetch_adj_factor(
                start_date=trade_date, end_date=trade_date,
            )
            if df.empty:
                log.warning("  %s returned empty, skipping.", trade_date)
                continue
            rows = self._storage.save_adjfactor(df)
            total_rows += rows
            log.info(
                "  %s: saved %d rows (running total: %d).",
                trade_date, rows, total_rows,
            )

        return total_rows

    def _update_moneyflow_full(self) -> int:
        """Fetch full 15-year moneyflow data — batched by trading day."""
        log.info("--- Moneyflow data (full, batched by trading day) ---")

        # 1. Get all trading days from the stored calendar
        try:
            cal_df = self._storage.execute_sql(
                "SELECT DISTINCT cal_date FROM trade_calendar_view "
                "WHERE is_open = 1 AND exchange = 'SSE' "
                "ORDER BY cal_date"
            )
        except Exception:
            log.warning("Trade calendar not available, falling back to date range.")
            df = self._fetcher.fetch_moneyflow()
            return self._storage.save_moneyflow(df) if not df.empty else 0

        if cal_df.empty:
            log.warning("Trade calendar empty, falling back to date range.")
            df = self._fetcher.fetch_moneyflow()
            return self._storage.save_moneyflow(df) if not df.empty else 0

        all_dates = cal_df["cal_date"].tolist()
        log.info("Found %d trading days in calendar.", len(all_dates))

        # Determine which dates are already stored
        try:
            existing_df = self._storage.execute_sql(
                "SELECT DISTINCT trade_date FROM moneyflow_view"
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
            log.info("Moneyflow data already complete. Nothing to fetch.")
            return 0

        # 2. Fetch one day at a time
        total_rows = 0
        for i, trade_date in enumerate(missing_dates, 1):
            log.info(
                "[%d/%d] Fetching moneyflow for %s",
                i, len(missing_dates), trade_date,
            )
            df = self._fetcher.fetch_moneyflow(
                trade_date=trade_date,
            )
            if df.empty:
                log.warning("  %s returned empty, skipping.", trade_date)
                continue
            rows = self._storage.save_moneyflow(df)
            total_rows += rows
            log.info(
                "  %s: saved %d rows (running total: %d).",
                trade_date, rows, total_rows,
            )

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

    def _update_index_basic(self) -> int:
        """Fetch and save index basic info for all three markets (CSI, SSE, SZSE)."""
        log.info("--- Index basic info (CSI / SSE / SZSE) ---")
        total_rows = 0
        for market in ("CSI", "SSE", "SZSE"):
            log.info("Fetching index_basic for market=%s", market)
            df = self._fetcher.fetch_index_basic(market=market)
            if df.empty:
                log.warning("  index_basic/%s returned empty, skipping.", market)
                continue
            rows = self._storage.save_index_basic(df, market)
            log.info("  index_basic/%s: saved %d rows.", market, rows)
            total_rows += rows
        return total_rows

    def _update_index_weight_full(self) -> int:
        """Fetch full 13-year index constituent weight data for all four indices.

        Batches are sized per index to stay under the Tushare API row limit
        (~7000 rows/call).  Larger indices (zz1000: 1000 constituents,
        zz2000: 2000 constituents) use shorter date ranges to avoid
        truncation.
        """
        log.info("--- Index weight data (full, batched by date range) ---")

        from config.settings import get_settings
        settings = get_settings()

        from data.storage import _INDEX_WEIGHT_INDICES
        indices = list(_INDEX_WEIGHT_INDICES.keys())

        # Conservative max rows per API call
        MAX_ROWS_PER_CALL = 6000

        # Approximate constituent counts (will be refined after first fetch)
        constituent_estimates: dict[str, int] = {
            "000300.SH": 300,
            "000905.SH": 500,
            "000852.SH": 1000,
            "932000.CSI": 2000,
        }

        today = datetime.today()
        start_year = today.year - settings.history_years
        end_year = today.year

        total_rows = 0
        for index_code in indices:
            short_name = _INDEX_WEIGHT_INDICES.get(index_code, index_code)
            est_constituents = constituent_estimates.get(index_code, 500)

            # Safe months per batch = floor(MAX_ROWS / estimated constituents)
            # but at least 1 month and at most 12 months
            months_per_batch = max(1, min(12, MAX_ROWS_PER_CALL // est_constituents))
            log.info(
                "--- index_weight/%s (est. %d constituents, %d month(s)/batch) ---",
                short_name, est_constituents, months_per_batch,
            )

            # Check which months are already stored for this index
            try:
                view_name = f"index_weight_{short_name}_view"
                existing_df = self._storage.execute_sql(
                    f"SELECT DISTINCT SUBSTR(trade_date, 1, 6) AS ym "
                    f"FROM {view_name}"
                )
                existing_months = set(existing_df["ym"].tolist()) if not existing_df.empty else set()
            except Exception:
                existing_months = set()

            # Generate batches of months
            batches = _generate_month_batches(
                start_year, end_year, months_per_batch, today
            )
            log.info("  %d batches to check, %d month(s) already stored.",
                     len(batches), len(existing_months))

            for batch_start, batch_end in batches:
                # Check if all months in this batch are already stored
                batch_months = _months_in_range(batch_start, batch_end)
                if batch_months.issubset(existing_months):
                    log.debug("  %s → %s: all stored, skipping.", batch_start, batch_end)
                    continue

                log.info("  Fetching %s → %s", batch_start, batch_end)
                df = self._fetcher.fetch_index_weight(
                    index_code=index_code,
                    start_date=batch_start,
                    end_date=batch_end,
                )
                if df.empty:
                    log.warning("  %s → %s: no data returned.", batch_start, batch_end)
                    continue

                rows = self._storage.save_index_weight(df, index_code)
                total_rows += rows
                n_dates = df["trade_date"].nunique()

                # Update estimate with actual constituent count
                actual_constituents = df.groupby("trade_date")["con_code"].count().max()
                log.info(
                    "  %s → %s: saved %d rows, %d date(s), max %d constituents/date.",
                    batch_start, batch_end, rows, n_dates, actual_constituents,
                )

        return total_rows

    def _update_index_weight_incremental(self, months: int = 3) -> int:
        """Fetch recent months of index constituent weight data.

        Uses a date range query per index so that all available records
        in the lookback window are captured, regardless of whether the
        calendar month-end falls on a trading day.

        Args:
            months: Number of months to look back from today.
        """
        log.info("--- Index weight data (incremental, last %d month(s)) ---", months)

        from data.storage import _INDEX_WEIGHT_INDICES
        indices = list(_INDEX_WEIGHT_INDICES.keys())

        today = datetime.today()
        start_dt = _months_ago(today, months)
        start_str = start_dt.strftime("%Y%m%d")
        end_str = today.strftime("%Y%m%d")

        log.info("Lookback window: %s → %s", start_str, end_str)

        total_rows = 0
        for index_code in indices:
            short_name = _INDEX_WEIGHT_INDICES.get(index_code, index_code)

            # Find which trade_dates are already stored within the window
            try:
                view_name = f"index_weight_{short_name}_view"
                existing_df = self._storage.execute_sql(
                    f"SELECT DISTINCT trade_date FROM {view_name} "
                    f"WHERE trade_date >= '{start_str}' "
                    f"AND trade_date <= '{end_str}'"
                )
                existing_dates = set(existing_df["trade_date"].tolist()) if not existing_df.empty else set()
            except Exception:
                existing_dates = set()

            log.info(
                "  index_weight/%s: %d date(s) already stored in window.",
                short_name, len(existing_dates),
            )

            # Fetch the full range — API returns all available records
            df = self._fetcher.fetch_index_weight(
                index_code=index_code,
                start_date=start_str,
                end_date=end_str,
            )
            if df.empty:
                log.info("  index_weight/%s: no new data in window.", short_name)
                continue

            # Filter out already-stored dates
            if existing_dates:
                new_df = df[~df["trade_date"].isin(existing_dates)]
            else:
                new_df = df

            if new_df.empty:
                log.info("  index_weight/%s: all dates already stored.", short_name)
                continue

            rows = self._storage.save_index_weight(new_df, index_code)
            n_dates = new_df["trade_date"].nunique()
            log.info(
                "  index_weight/%s: saved %d new rows across %d date(s).",
                short_name, rows, n_dates,
            )
            total_rows += rows

        return total_rows

    def _update_index_daily_full(self) -> int:
        """Fetch full 13-year index daily OHLCV data for all four indices.

        Each index is fetched with a single API call since the row count
        (~3300 rows/index for 13 years) is well within API limits.
        """
        log.info("--- Index daily data (full, past 13 years) ---")

        from config.settings import get_settings
        settings = get_settings()

        from data.storage import _INDEX_DAILY_INDICES
        indices = list(_INDEX_DAILY_INDICES.keys())

        today = datetime.today()
        start_year = today.year - settings.history_years
        start_str = f"{start_year}0101"
        end_str = today.strftime("%Y%m%d")

        log.info("Date range: %s → %s", start_str, end_str)

        total_rows = 0
        for index_code in indices:
            short_name = _INDEX_DAILY_INDICES.get(index_code, index_code)
            log.info("Fetching index_daily for %s (%s)...", index_code, short_name)

            # Check which dates are already stored
            try:
                view_name = f"index_daily_{short_name}_view"
                existing_df = self._storage.execute_sql(
                    f"SELECT DISTINCT trade_date FROM {view_name}"
                )
                existing_dates = set(existing_df["trade_date"].tolist()) if not existing_df.empty else set()
            except Exception:
                existing_dates = set()

            df = self._fetcher.fetch_index_daily(
                ts_code=index_code,
                start_date=start_str,
                end_date=end_str,
            )
            if df.empty:
                log.warning("  %s: no data returned.", index_code)
                continue

            # Filter out already-stored dates
            if existing_dates:
                new_df = df[~df["trade_date"].isin(existing_dates)]
            else:
                new_df = df

            if new_df.empty:
                log.info("  %s: all dates already stored.", short_name)
                continue

            rows = self._storage.save_index_daily(new_df, index_code)
            log.info(
                "  %s: saved %d new rows across %d date(s).",
                short_name, rows, new_df["trade_date"].nunique(),
            )
            total_rows += rows

        return total_rows

    def _update_index_daily_incremental(self, months: int = 3) -> int:
        """Fetch recent months of index daily OHLCV data.

        Uses a date range query per index — the row count per index is
        small (~21 trading days/month).

        Args:
            months: Number of months to look back from today.
        """
        log.info("--- Index daily data (incremental, last %d month(s)) ---", months)

        from data.storage import _INDEX_DAILY_INDICES
        indices = list(_INDEX_DAILY_INDICES.keys())

        today = datetime.today()
        start_dt = _months_ago(today, months)
        start_str = start_dt.strftime("%Y%m%d")
        end_str = today.strftime("%Y%m%d")

        log.info("Lookback window: %s → %s", start_str, end_str)

        total_rows = 0
        for index_code in indices:
            short_name = _INDEX_DAILY_INDICES.get(index_code, index_code)

            # Find which trade_dates are already stored within the window
            try:
                view_name = f"index_daily_{short_name}_view"
                existing_df = self._storage.execute_sql(
                    f"SELECT DISTINCT trade_date FROM {view_name} "
                    f"WHERE trade_date >= '{start_str}' "
                    f"AND trade_date <= '{end_str}'"
                )
                existing_dates = set(existing_df["trade_date"].tolist()) if not existing_df.empty else set()
            except Exception:
                existing_dates = set()

            log.info(
                "  index_daily/%s: %d date(s) already stored in window.",
                short_name, len(existing_dates),
            )

            df = self._fetcher.fetch_index_daily(
                ts_code=index_code,
                start_date=start_str,
                end_date=end_str,
            )
            if df.empty:
                log.info("  index_daily/%s: no new data in window.", short_name)
                continue

            # Filter out already-stored dates
            if existing_dates:
                new_df = df[~df["trade_date"].isin(existing_dates)]
            else:
                new_df = df

            if new_df.empty:
                log.info("  index_daily/%s: all dates already stored.", short_name)
                continue

            rows = self._storage.save_index_daily(new_df, index_code)
            n_dates = new_df["trade_date"].nunique()
            log.info(
                "  index_daily/%s: saved %d new rows across %d date(s).",
                short_name, rows, n_dates,
            )
            total_rows += rows

        return total_rows

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


def _generate_month_batches(
    start_year: int,
    end_year: int,
    months_per_batch: int,
    today: datetime,
) -> list[tuple[str, str]]:
    """Generate (start_date, end_date) batches covering the full history.

    Each batch spans *months_per_batch* calendar months.  The final batch
    is capped at *today*.
    """
    batches: list[tuple[str, str]] = []
    year, month = start_year, 1

    while year < end_year or (year == end_year and month <= 12):
        # Batch start: first day of *month*
        batch_start = f"{year}{month:02d}01"

        # Batch end: advance (months_per_batch - 1) months, then last day
        end_m = month + months_per_batch - 1
        end_y = year + (end_m - 1) // 12
        end_m = ((end_m - 1) % 12) + 1
        last_day = calendar.monthrange(end_y, end_m)[1]
        batch_end = f"{end_y}{end_m:02d}{last_day:02d}"

        # Don't go past today
        today_str = today.strftime("%Y%m%d")
        if batch_end > today_str:
            batch_end = today_str

        batches.append((batch_start, batch_end))

        # Advance to next batch
        month += months_per_batch
        while month > 12:
            month -= 12
            year += 1

        if batch_end == today_str:
            break

    return batches


def _months_in_range(start_date: str, end_date: str) -> set[str]:
    """Return the set of YYYYMM month strings covered by [start, end]."""
    sy, sm = int(start_date[:4]), int(start_date[4:6])
    ey, em = int(end_date[:4]), int(end_date[4:6])
    months: set[str] = set()
    y, m = sy, sm
    while y < ey or (y == ey and m <= em):
        months.add(f"{y}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _generate_month_ends(start_year: int, end_year: int) -> list[str]:
    """Generate all month-end dates from *start_year* to *end_year*
    (inclusive).  Future months (last day > today) are excluded."""
    today = datetime.today()
    today_str = today.strftime("%Y%m%d")
    dates: list[str] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            d = f"{year}{month:02d}{last_day:02d}"
            if d <= today_str:
                dates.append(d)
    return dates
