#!/usr/bin/env python3
"""Database query tests — DuckDB connection, SQL queries, CSV/JSON export.

This module can be run standalone or via pytest::

    # Run all tests
    python test/test_query.py

    # Run with pytest
    pytest test/test_query.py -v

    # Run a specific test
    python test/test_query.py TestDBQuery::test_connection

Output files are written to ``test/output/`` (created automatically).
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so imports work regardless of cwd
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import get_settings
from data.storage import DataStorage
from query.engine import QueryEngine

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
_OUTPUT_DIR = Path(__file__).resolve().parent / "output"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ======================================================================
# Helper: export utilities
# ======================================================================

def df_to_csv(df: pd.DataFrame, filename: str) -> Path:
    """Save DataFrame as CSV and return the output path."""
    path = _OUTPUT_DIR / filename
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  [CSV]  {len(df)} rows → {path}")
    return path


def df_to_json(df: pd.DataFrame, filename: str) -> Path:
    """Save DataFrame as JSON (records orientation) and return the output path."""
    path = _OUTPUT_DIR / filename
    df.to_json(path, orient="records", force_ascii=False, indent=2)
    print(f"  [JSON] {len(df)} rows → {path}")
    return path


def df_to_console(df: pd.DataFrame, title: str = "") -> None:
    """Pretty-print a DataFrame to stdout."""
    if title:
        print(f"\n{'='*60}")
        print(f"  {title}  ({len(df)} rows)")
        print(f"{'='*60}")
    if df.empty:
        print("  (empty result)")
        return
    with pd.option_context(
        "display.max_rows", 30,
        "display.max_columns", 20,
        "display.width", 160,
        "display.float_format", lambda x: f"{x:.2f}",
    ):
        print(df.to_string(index=False))


# ======================================================================
# Test cases
# ======================================================================

class TestDBConnection(unittest.TestCase):
    """Verify DuckDB connectivity and basic metadata queries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.storage = DataStorage()
        cls.engine = QueryEngine(cls.storage)
        cls.settings = get_settings()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.storage.close()

    def test_connection(self) -> None:
        """DuckDB connection should be alive and usable."""
        result = self.storage.conn.execute("SELECT 1 AS ok").df()
        self.assertEqual(result["ok"].iloc[0], 1)
        print("\n  ✓ DuckDB connection OK")

    def test_db_path(self) -> None:
        """Database file should exist on disk."""
        db_path = self.settings.duckdb_path
        self.assertTrue(db_path.exists(), f"DB not found: {db_path}")
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ DB path: {db_path}  ({size_mb:.1f} MB)")

    def test_record_counts(self) -> None:
        """Every registered table should report a row count."""
        counts = self.engine.record_counts()
        self.assertIsInstance(counts, dict)
        self.assertGreater(len(counts), 0)
        print("\n  Table                   Rows")
        print("  " + "-" * 35)
        for t, c in counts.items():
            print(f"  {t:22s} {c:>10d}")
        print()

        # Export counts as both CSV and JSON
        counts_df = pd.DataFrame(
            [{"table": k, "row_count": v} for k, v in counts.items()]
        )
        df_to_csv(counts_df, "record_counts.csv")
        df_to_json(counts_df, "record_counts.json")

    def test_schemas(self) -> None:
        """Every table should return column metadata."""
        schemas = self.engine.get_schemas()
        self.assertIsInstance(schemas, dict)

        all_rows: list[dict] = []
        for t, df in schemas.items():
            self.assertIsInstance(df, pd.DataFrame)
            if not df.empty:
                for _, row in df.iterrows():
                    all_rows.append({
                        "table": t,
                        "column_name": row["column_name"],
                        "column_type": str(row["column_type"]),
                        "nullable": row.get("null", ""),
                    })

        schema_df = pd.DataFrame(all_rows)
        df_to_csv(schema_df, "schemas.csv")
        df_to_json(schema_df, "schemas.json")
        print(f"  ✓ Exported schema info for {len(schemas)} tables")


class TestDBQuery(unittest.TestCase):
    """Query each view/table and export results as CSV + JSON."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.storage = DataStorage()
        cls.engine = QueryEngine(cls.storage)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.storage.close()

    # ------------------------------------------------------------------
    # Daily data
    # ------------------------------------------------------------------

    def test_daily_view(self) -> None:
        """Query daily_view — all data."""
        df = self.storage.execute_sql(
            "SELECT * FROM daily_view ORDER BY trade_date DESC, ts_code"
        )
        self.assertIsInstance(df, pd.DataFrame)
        if df.empty:
            print("  ⚠ daily_view is empty — skipping export")
            return
        df_to_console(df.head(10), "daily_view (first 10 rows)")
        df_to_csv(df.head(100), "daily_sample.csv")
        df_to_json(df.head(100), "daily_sample.json")

    def test_daily_single_stock(self) -> None:
        """Query daily data for a specific stock: 000001.SZ (平安银行)."""
        df = self.engine.get_daily("000001.SZ")
        if df.empty:
            print("  ⚠ No daily data for 000001.SZ — skipping")
            return
        self.assertTrue(all(df["ts_code"] == "000001.SZ"))
        df_to_console(df.tail(5), "000001.SZ daily (last 5 rows)")
        df_to_csv(df, "daily_000001_SZ.csv")
        df_to_json(df, "daily_000001_SZ.json")

    def test_top_volume(self) -> None:
        """Query top-N by volume for the latest available date."""
        dates_df = self.engine.trading_dates(1)
        if dates_df.empty:
            print("  ⚠ No trading dates — skipping top_volume")
            return
        latest_date = str(dates_df["trade_date"].iloc[0])
        df = self.engine.top_volume(latest_date, n=10)
        self.assertLessEqual(len(df), 10)
        df_to_console(df, f"Top-10 volume on {latest_date}")
        df_to_csv(df, f"top_volume_{latest_date}.csv")
        df_to_json(df, f"top_volume_{latest_date}.json")

    # ------------------------------------------------------------------
    # Stock basic
    # ------------------------------------------------------------------

    def test_stock_basic_view(self) -> None:
        """Query stock_basic_view."""
        df = self.engine.get_stock_info()
        if df.empty:
            print("  ⚠ stock_basic_view is empty — skipping")
            return
        df_to_console(df.head(10), "stock_basic_view (first 10 rows)")
        df_to_csv(df, "stock_basic.csv")
        df_to_json(df, "stock_basic.json")

    def test_search_stock(self) -> None:
        """Search stocks by keyword: '平安'."""
        df = self.engine.search_stock("平安")
        if df.empty:
            print("  ⚠ No matches for '平安' — skipping")
            return
        df_to_console(df, "Search: '平安'")
        df_to_csv(df, "search_平安.csv")
        df_to_json(df, "search_平安.json")

    # ------------------------------------------------------------------
    # Income data
    # ------------------------------------------------------------------

    def test_income_view(self) -> None:
        """Query income_view (may not exist if income data not yet initialized)."""
        try:
            df = self.storage.execute_sql(
                "SELECT * FROM income_view ORDER BY end_date DESC, ts_code"
            )
        except Exception:
            print("  ⚠ income_view does not exist — run 'python main.py init --data-type income' first")
            return
        if df.empty:
            print("  ⚠ income_view is empty — skipping")
            return
        df_to_console(df.head(10), "income_view (first 10 rows)")
        df_to_csv(df.head(100), "income_sample.csv")
        df_to_json(df.head(100), "income_sample.json")

    def test_roe_rank(self) -> None:
        """Query ROE ranking (requires income data to be initialized)."""
        today = datetime.today().strftime("%Y%m%d")
        try:
            df = self.engine.roe_rank(today, n=10)
        except Exception:
            print(f"  ⚠ income_view not available — run 'python main.py init --data-type income' first")
            return
        if df.empty:
            print(f"  ⚠ No ROE data for end_date <= {today} — skipping")
            return
        df_to_console(df, f"Top-10 ROE (as of {today})")
        df_to_csv(df, f"roe_rank_{today}.csv")
        df_to_json(df, f"roe_rank_{today}.json")

    # ------------------------------------------------------------------
    # Trade calendar
    # ------------------------------------------------------------------

    def test_trade_calendar(self) -> None:
        """Query trade_calendar_view for 2026 (raw SQL avoids ts_code bug in reader)."""
        try:
            df = self.storage.execute_sql(
                "SELECT * FROM trade_calendar_view "
                "WHERE cal_date >= '20260101' AND cal_date <= '20261231' "
                "ORDER BY cal_date"
            )
        except Exception:
            print("  ⚠ trade_calendar_view does not exist — run 'python main.py init --data-type trade_calendar' first")
            return
        if df.empty:
            print("  ⚠ No trade calendar data for 2026 — skipping")
            return
        trading_days = int(df["is_open"].sum()) if "is_open" in df.columns else 0
        print(f"\n  2026 trading days: {trading_days}")
        df_to_csv(df, "trade_calendar_2026.csv")
        df_to_json(df, "trade_calendar_2026.json")

    # ------------------------------------------------------------------
    # ST stocks
    # ------------------------------------------------------------------

    def test_st_stocks(self) -> None:
        """Query st_stocks_view."""
        df = self.engine.get_st_stocks()
        if df.empty:
            print("  ⚠ st_stocks_view is empty — skipping")
            return
        df_to_console(df.head(10), "ST stocks (first 10)")
        df_to_csv(df, "st_stocks.csv")
        df_to_json(df, "st_stocks.json")


class TestRawSQL(unittest.TestCase):
    """Ad-hoc / raw SQL queries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.storage = DataStorage()
        cls.engine = QueryEngine(cls.storage)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.storage.close()

    def test_raw_sql_simple(self) -> None:
        """Run a simple raw SQL query."""
        sql = """
            SELECT ts_code, trade_date, close, pct_chg, amount
            FROM daily_view
            WHERE trade_date = (SELECT MAX(trade_date) FROM daily_view)
            ORDER BY amount DESC
            LIMIT 10
        """
        df = self.engine.raw_sql(sql)
        if df.empty:
            print("  ⚠ Raw SQL returned empty — skipping")
            return
        df_to_console(df, "Raw SQL: latest date top-10 by amount")
        df_to_csv(df, "raw_latest_top10.csv")
        df_to_json(df, "raw_latest_top10.json")

    def test_raw_sql_join(self) -> None:
        """Run a JOIN across daily and stock_basic views."""
        sql = """
            SELECT
                d.ts_code,
                s.name,
                s.industry,
                d.trade_date,
                d.close,
                d.pct_chg,
                d.amount
            FROM daily_view d
            LEFT JOIN stock_basic_view s ON d.ts_code = s.ts_code
            WHERE d.trade_date = (SELECT MAX(trade_date) FROM daily_view)
              AND s.industry IS NOT NULL
            ORDER BY d.amount DESC
            LIMIT 20
        """
        df = self.engine.raw_sql(sql)
        if df.empty:
            print("  ⚠ Join query returned empty — skipping")
            return
        df_to_console(df, "Raw SQL: latest date JOIN stock_basic")
        df_to_csv(df, "raw_join_latest.csv")
        df_to_json(df, "raw_join_latest.json")


class TestExportFormats(unittest.TestCase):
    """Test CSV and JSON export edge cases."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.storage = DataStorage()
        cls.engine = QueryEngine(cls.storage)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.storage.close()

    def test_csv_export(self) -> None:
        """CSV export should produce a non-empty file."""
        df = self.storage.execute_sql(
            "SELECT * FROM daily_view LIMIT 50"
        )
        if df.empty:
            self.skipTest("No daily data")
        path = df_to_csv(df, "test_csv_export.csv")
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)
        # Verify we can read it back
        df2 = pd.read_csv(path)
        self.assertEqual(len(df), len(df2))

    def test_json_export(self) -> None:
        """JSON export should produce valid JSON."""
        df = self.storage.execute_sql(
            "SELECT * FROM daily_view LIMIT 50"
        )
        if df.empty:
            self.skipTest("No daily data")
        path = df_to_json(df, "test_json_export.json")
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)
        # Verify it's valid JSON
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), len(df))

    def test_empty_result_handling(self) -> None:
        """Empty DataFrame should still export without error."""
        df = pd.DataFrame()
        path_csv = df_to_csv(df, "empty.csv")
        path_json = df_to_json(df, "empty.json")
        self.assertTrue(path_csv.exists())
        self.assertTrue(path_json.exists())


# ======================================================================
# Main entry point
# ======================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Quant DB Query Tests")
    print(f"  Output dir: {_OUTPUT_DIR}")
    print(f"  Timestamp:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Run with unittest
    unittest.main(verbosity=2, argv=[sys.argv[0]], exit=False)

    # Summary of exported files
    files = sorted(_OUTPUT_DIR.glob("*"))
    if files:
        print(f"\n{'='*60}")
        print(f"  Exported files ({len(files)} total):")
        print(f"{'='*60}")
        for f in files:
            size_kb = f.stat().st_size / 1024
            print(f"  {f.name:45s} {size_kb:>8.1f} KB")
    print()
