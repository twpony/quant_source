"""DuckDB + Parquet storage layer.

Provides a unified interface to:
- Write DataFrames to Parquet files (daily: by date, income: by quarter).
- Register Parquet data as DuckDB tables / views.
- Upsert (merge) new data with deduplication.
- Maintain a manifest.json that describes stored data.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from config.settings import get_settings
from utils.logger import log


# ---------------------------------------------------------------------------
# Column type overrides per data type — ensures DuckDB uses correct types
# ---------------------------------------------------------------------------
_COLUMN_TYPES: dict[str, dict[str, str]] = {
    "daily": {
        "ts_code": "VARCHAR",
        "trade_date": "VARCHAR",
        "open": "DOUBLE",
        "high": "DOUBLE",
        "low": "DOUBLE",
        "close": "DOUBLE",
        "pre_close": "DOUBLE",
        "change": "DOUBLE",
        "pct_chg": "DOUBLE",
        "vol": "DOUBLE",
        "amount": "DOUBLE",
    },
    "stock_basic": {
        "ts_code": "VARCHAR",
        "symbol": "VARCHAR",
        "name": "VARCHAR",
        "area": "VARCHAR",
        "industry": "VARCHAR",
        "fullname": "VARCHAR",
        "enname": "VARCHAR",
        "cnspell": "VARCHAR",
        "market": "VARCHAR",
        "exchange": "VARCHAR",
        "curr_type": "VARCHAR",
        "list_status": "VARCHAR",
        "list_date": "VARCHAR",
        "delist_date": "VARCHAR",
        "is_hs": "VARCHAR",
        "act_name": "VARCHAR",
        "act_ent_type": "VARCHAR",
    },
    "income": {
        # String / categorical columns
        "ts_code": "VARCHAR",
        "ann_date": "VARCHAR",
        "f_ann_date": "VARCHAR",
        "end_date": "VARCHAR",
        "report_type": "VARCHAR",
        "comp_type": "VARCHAR",
        "end_type": "VARCHAR",
        "update_flag": "VARCHAR",
        # Numeric columns — strictly follow tushare income API output order
        "basic_eps": "DOUBLE",
        "diluted_eps": "DOUBLE",
        "total_revenue": "DOUBLE",
        "revenue": "DOUBLE",
        "int_income": "DOUBLE",
        "prem_earned": "DOUBLE",
        "comm_income": "DOUBLE",
        "n_commis_income": "DOUBLE",
        "n_oth_income": "DOUBLE",
        "n_oth_b_income": "DOUBLE",
        "prem_income": "DOUBLE",
        "out_prem": "DOUBLE",
        "une_prem_reser": "DOUBLE",
        "reins_income": "DOUBLE",
        "n_sec_tb_income": "DOUBLE",
        "n_sec_uw_income": "DOUBLE",
        "n_asset_mg_income": "DOUBLE",
        "oth_b_income": "DOUBLE",
        "fv_value_chg_gain": "DOUBLE",
        "invest_income": "DOUBLE",
        "ass_invest_income": "DOUBLE",
        "forex_gain": "DOUBLE",
        "total_cogs": "DOUBLE",
        "oper_cost": "DOUBLE",
        "int_exp": "DOUBLE",
        "comm_exp": "DOUBLE",
        "biz_tax_surchg": "DOUBLE",
        "sell_exp": "DOUBLE",
        "admin_exp": "DOUBLE",
        "fin_exp": "DOUBLE",
        "assets_impair_loss": "DOUBLE",
        "prem_refund": "DOUBLE",
        "compens_payout": "DOUBLE",
        "reser_insur_liab": "DOUBLE",
        "div_payt": "DOUBLE",
        "reins_exp": "DOUBLE",
        "oper_exp": "DOUBLE",
        "compens_payout_refu": "DOUBLE",
        "insur_reser_refu": "DOUBLE",
        "reins_cost_refund": "DOUBLE",
        "other_bus_cost": "DOUBLE",
        "operate_profit": "DOUBLE",
        "non_oper_income": "DOUBLE",
        "non_oper_exp": "DOUBLE",
        "nca_disploss": "DOUBLE",
        "total_profit": "DOUBLE",
        "income_tax": "DOUBLE",
        "n_income": "DOUBLE",
        "n_income_attr_p": "DOUBLE",
        "minority_gain": "DOUBLE",
        "oth_compr_income": "DOUBLE",
        "t_compr_income": "DOUBLE",
        "compr_inc_attr_p": "DOUBLE",
        "compr_inc_attr_m_s": "DOUBLE",
        "ebit": "DOUBLE",
        "ebitda": "DOUBLE",
        "insurance_exp": "DOUBLE",
        "undist_profit": "DOUBLE",
        "distable_profit": "DOUBLE",
        "rd_exp": "DOUBLE",
        "fin_exp_int_exp": "DOUBLE",
        "fin_exp_int_inc": "DOUBLE",
        "transfer_surplus_rese": "DOUBLE",
        "transfer_housing_imprest": "DOUBLE",
        "transfer_oth": "DOUBLE",
        "adj_lossgain": "DOUBLE",
        "withdra_legal_surplus": "DOUBLE",
        "withdra_legal_pubfund": "DOUBLE",
        "withdra_biz_devfund": "DOUBLE",
        "withdra_rese_fund": "DOUBLE",
        "withdra_oth_ersu": "DOUBLE",
        "workers_welfare": "DOUBLE",
        "distr_profit_shrhder": "DOUBLE",
        "prfshare_payable_dvd": "DOUBLE",
        "comshare_payable_dvd": "DOUBLE",
        "capit_comstock_div": "DOUBLE",
        "continued_net_profit": "DOUBLE",
    },
    "cashflow": {
        # String / categorical columns
        "ts_code": "VARCHAR",
        "ann_date": "VARCHAR",
        "f_ann_date": "VARCHAR",
        "end_date": "VARCHAR",
        "report_type": "VARCHAR",
        "comp_type": "VARCHAR",
        "end_type": "VARCHAR",
        "update_flag": "VARCHAR",
        # Cashflow statement numeric columns
        "net_profit": "DOUBLE",
        "finan_exp": "DOUBLE",
        "c_fr_sale_sg": "DOUBLE",
        "recp_tax_rends": "DOUBLE",
        "n_depos_incr_fi": "DOUBLE",
        "n_incr_loans_cb": "DOUBLE",
        "n_incr_borr_oth_fi": "DOUBLE",
        "prem_fr_orig_contr": "DOUBLE",
        "n_incr_insured_dep": "DOUBLE",
        "n_reinsur_prem": "DOUBLE",
        "n_incr_disp_tfa": "DOUBLE",
        "ifc_cash_incr": "DOUBLE",
        "n_incr_disp_faas": "DOUBLE",
        "n_incr_loans_oth_bank": "DOUBLE",
        "n_cap_incr_repur": "DOUBLE",
        "c_fr_oth_operate_a": "DOUBLE",
        "c_inf_fr_operate_a": "DOUBLE",
        "c_paid_goods_s": "DOUBLE",
        "c_paid_to_for_empl": "DOUBLE",
        "c_paid_for_taxes": "DOUBLE",
        "n_incr_clt_adv": "DOUBLE",
        "n_incr_dep_cbob": "DOUBLE",
        "c_pay_claims_orig_inco": "DOUBLE",
        "pay_handling_chrg": "DOUBLE",
        "pay_comm_insur_plcy": "DOUBLE",
        "oth_cash_pay_oper_act": "DOUBLE",
        "st_cash_out_act": "DOUBLE",
        "n_cashflow_act": "DOUBLE",
        "oth_recp_ral_inv_act": "DOUBLE",
        "c_disp_withdrwl_oth": "DOUBLE",
        "c_recp_return_equit": "DOUBLE",
        "n_recp_disp_fiolta": "DOUBLE",
        "stot_inflows_inv_act": "DOUBLE",
        "c_pay_acq_const_fiolta": "DOUBLE",
        "c_paid_invest": "DOUBLE",
        "n_disp_subs_oth_biz": "DOUBLE",
        "oth_pay_ral_inv_act": "DOUBLE",
        "n_incr_pledge_loan": "DOUBLE",
        "stot_out_inv_act": "DOUBLE",
        "n_cashflow_inv_act": "DOUBLE",
        "c_recp_borrow": "DOUBLE",
        "proc_issue_bonds": "DOUBLE",
        "oth_cash_recp_ral_fnc_act": "DOUBLE",
        "stot_cash_in_fnc_act": "DOUBLE",
        "free_cashflow": "DOUBLE",
        "c_prepay_amt_borr": "DOUBLE",
        "c_pay_dist_dpcp_int_exp": "DOUBLE",
        "incl_dvd_profit_paid_sc_ms": "DOUBLE",
        "oth_cashpay_ral_fnc_act": "DOUBLE",
        "stot_cashout_fnc_act": "DOUBLE",
        "n_cash_flows_fnc_act": "DOUBLE",
        "eff_fx_flu_cash": "DOUBLE",
        "n_incr_cash_cash_equ": "DOUBLE",
        "c_cash_equ_beg_period": "DOUBLE",
        "c_cash_equ_end_period": "DOUBLE",
        "c_recp_cap_contrib": "DOUBLE",
        "incl_cash_rec_saims": "DOUBLE",
        "unpaid_invest": "DOUBLE",
        "prov_depr_assets": "DOUBLE",
        "depr_fa_coga_dpba": "DOUBLE",
        "amort_intang_assets": "DOUBLE",
        "lt_amort_deferred_exp": "DOUBLE",
        "defer_tax_less_assets": "DOUBLE",
        "defer_tax_less_liab": "DOUBLE",
        "loss_disp_fiolta": "DOUBLE",
        "loss_scr_fa": "DOUBLE",
        "loss_fv_chg": "DOUBLE",
        "invest_loss": "DOUBLE",
        "decr_def_inc_tax_assets": "DOUBLE",
        "incr_def_inc_tax_liab": "DOUBLE",
        "decr_inventories": "DOUBLE",
        "decr_oper_payable": "DOUBLE",
        "incr_oper_payable": "DOUBLE",
        "others": "DOUBLE",
        "im_net_cashflow_oper_act": "DOUBLE",
        "conv_debt_into_cap": "DOUBLE",
        "conv_cop_debt_due_1y": "DOUBLE",
        "fa_fnc_leases": "DOUBLE",
        "end_bal_cash": "DOUBLE",
        "less_beg_bal_cash": "DOUBLE",
        "plus_end_bal_cash_equ": "DOUBLE",
        "less_beg_bal_cash_equ": "DOUBLE",
        "im_n_incr_cash_equ": "DOUBLE",
    },
    "balancesheet": {
        # String / categorical columns
        "ts_code": "VARCHAR",
        "ann_date": "VARCHAR",
        "f_ann_date": "VARCHAR",
        "end_date": "VARCHAR",
        "report_type": "VARCHAR",
        "comp_type": "VARCHAR",
        "end_type": "VARCHAR",
        "update_flag": "VARCHAR",
        # Total-level columns
        "total_hldr_eqy_exc_min_int": "DOUBLE",
        "total_hldr_eqy_inc_min_int": "DOUBLE",
        "total_assets": "DOUBLE",
        "total_cur_assets": "DOUBLE",
        "total_nca": "DOUBLE",
        "total_liab": "DOUBLE",
        "total_cur_liab": "DOUBLE",
        "total_ncl": "DOUBLE",
        # Current assets detail
        "money_cap": "DOUBLE",
        "trad_asset": "DOUBLE",
        "notes_receiv": "DOUBLE",
        "accounts_receiv": "DOUBLE",
        "oth_receiv": "DOUBLE",
        "prepayment": "DOUBLE",
        "div_receiv": "DOUBLE",
        "int_receiv": "DOUBLE",
        "inventories": "DOUBLE",
        "amor_exp": "DOUBLE",
        "nca_within_1y": "DOUBLE",
        "sett_rsrv": "DOUBLE",
        "loanto_oth_bank_fi": "DOUBLE",
        "premium_receiv": "DOUBLE",
        "reinsur_receiv": "DOUBLE",
        "reinsur_cont_res": "DOUBLE",
        "redem_meas_inv": "DOUBLE",
        "oth_cur_assets": "DOUBLE",
        # Non-current assets detail
        "nca": "DOUBLE",
        "fin_assets_avail_for_sale": "DOUBLE",
        "htm_invest": "DOUBLE",
        "long_equity_invest": "DOUBLE",
        "invest_real_estate": "DOUBLE",
        "time_deposits": "DOUBLE",
        "oth_assets": "DOUBLE",
        "lt_rec": "DOUBLE",
        "fix_assets": "DOUBLE",
        "cip": "DOUBLE",
        "const_materials": "DOUBLE",
        "fixed_assets_disp": "DOUBLE",
        "intang_assets": "DOUBLE",
        "r_and_d_exp": "DOUBLE",
        "goodwill": "DOUBLE",
        "lt_amor_exp": "DOUBLE",
        "defer_tax_assets": "DOUBLE",
        "oth_nca": "DOUBLE",
        # Current liabilities detail
        "st_borrow": "DOUBLE",
        "st_notes_payable": "DOUBLE",
        "accounts_payable": "DOUBLE",
        "adv_pepmts": "DOUBLE",
        "int_payable": "DOUBLE",
        "div_payable": "DOUBLE",
        "oth_payable": "DOUBLE",
        "accrued_exp": "DOUBLE",
        "deferred_inc": "DOUBLE",
        "lt_borr_due_within_1y": "DOUBLE",
        "sett_rsrv_payable": "DOUBLE",
        "deposit_received": "DOUBLE",
        "trad_liab": "DOUBLE",
        "notes_payable": "DOUBLE",
        "oth_cur_liab": "DOUBLE",
        # Non-current liabilities detail
        "lt_borrow": "DOUBLE",
        "lt_notes_payable": "DOUBLE",
        "bonds_payable": "DOUBLE",
        "lt_payable": "DOUBLE",
        "specific_item_payable": "DOUBLE",
        "long_deferred_inc": "DOUBLE",
        "defer_tax_liab": "DOUBLE",
        "oth_ncl": "DOUBLE",
        # Equity detail
        "cap_rese": "DOUBLE",
        "surplus_rese": "DOUBLE",
        "undistort_profit": "DOUBLE",
        "minority_int": "DOUBLE",
    },
    "trade_calendar": {
        "exchange": "VARCHAR",
        "cal_date": "VARCHAR",
        "is_open": "INTEGER",
        "pretrade_date": "VARCHAR",
    },
    "st_stocks": {
        "ts_code": "VARCHAR",
        "symbol": "VARCHAR",
        "name": "VARCHAR",
        "st_type": "VARCHAR",
        "industry": "VARCHAR",
        "list_date": "VARCHAR",
    },
    "adjfactor": {
        "ts_code": "VARCHAR",
        "trade_date": "VARCHAR",
        "adj_factor": "DOUBLE",
    },
    "moneyflow": {
        "ts_code": "VARCHAR",
        "trade_date": "VARCHAR",
        "buy_sm_vol": "DOUBLE",
        "buy_sm_amount": "DOUBLE",
        "sell_sm_vol": "DOUBLE",
        "sell_sm_amount": "DOUBLE",
        "buy_md_vol": "DOUBLE",
        "buy_md_amount": "DOUBLE",
        "sell_md_vol": "DOUBLE",
        "sell_md_amount": "DOUBLE",
        "buy_lg_vol": "DOUBLE",
        "buy_lg_amount": "DOUBLE",
        "sell_lg_vol": "DOUBLE",
        "sell_lg_amount": "DOUBLE",
        "buy_elg_vol": "DOUBLE",
        "buy_elg_amount": "DOUBLE",
        "sell_elg_vol": "DOUBLE",
        "sell_elg_amount": "DOUBLE",
        "net_mf_vol": "DOUBLE",
        "net_mf_amount": "DOUBLE",
    },
    "index_basic": {
        "ts_code": "VARCHAR",
        "name": "VARCHAR",
        "fullname": "VARCHAR",
        "market": "VARCHAR",
        "publisher": "VARCHAR",
        "index_type": "VARCHAR",
        "category": "VARCHAR",
        "base_date": "VARCHAR",
        "base_point": "DOUBLE",
        "list_date": "VARCHAR",
        "weight_rule": "VARCHAR",
        "desc": "VARCHAR",
        "exp_date": "VARCHAR",
    },
    "index_weight": {
        "index_code": "VARCHAR",
        "con_code": "VARCHAR",
        "trade_date": "VARCHAR",
        "weight": "DOUBLE",
    },
    "index_daily": {
        "ts_code": "VARCHAR",
        "trade_date": "VARCHAR",
        "close": "DOUBLE",
        "open": "DOUBLE",
        "high": "DOUBLE",
        "low": "DOUBLE",
        "pre_close": "DOUBLE",
        "change": "DOUBLE",
        "pct_chg": "DOUBLE",
        "vol": "DOUBLE",
        "amount": "DOUBLE",
    },
}

# Primary-key columns per data type (used for dedup / upsert).
_PRIMARY_KEYS: dict[str, list[str]] = {
    "daily": ["ts_code", "trade_date"],
    "stock_basic": ["ts_code"],
    "income": ["ts_code", "end_date"],
    "cashflow": ["ts_code", "end_date"],
    "balancesheet": ["ts_code", "end_date"],
    "trade_calendar": ["exchange", "cal_date"],
    "st_stocks": ["ts_code"],
    "adjfactor": ["ts_code", "trade_date"],
    "moneyflow": ["ts_code", "trade_date"],
    "index_basic": ["ts_code"],
    "index_weight": ["index_code", "con_code", "trade_date"],
    "index_daily": ["ts_code", "trade_date"],
}

# Which tables are stored as a single Parquet file (not partitioned).
_SINGLE_FILE_TABLES = {"stock_basic", "st_stocks"}

# Which tables are partitioned by full date (YYYYMMDD).
_BY_DATE_TABLES = {"daily", "income", "cashflow", "balancesheet", "adjfactor", "moneyflow"}

# All known data types, in display order.
# Which tables are stored in the index_basic/ sub-directory (multi-file by market).
_INDEX_BASIC_MARKETS = {
    "CSI": "csi",
    "SSE": "sse",
    "SZSE": "szse",
}

# Index weight — maps tushare index_code → short directory name
_INDEX_WEIGHT_INDICES: dict[str, str] = {
    "000852.SH": "zz1000",
    "932000.CSI": "zz2000",
    "000905.SH": "zz500",
    "000300.SH": "hs300",
}

# Index daily — same index set as index_weight, stored under index_daily/
_INDEX_DAILY_INDICES: dict[str, str] = {
    "000852.SH": "zz1000",
    "932000.CSI": "zz2000",
    "000905.SH": "zz500",
    "000300.SH": "hs300",
}

_ALL_TABLES = (
    "daily", "stock_basic", "income", "cashflow", "balancesheet",
    "trade_calendar", "st_stocks", "adjfactor", "moneyflow", "index_basic",
    "index_weight", "index_daily",
)


class DataStorage:
    """Manages DuckDB connection and Parquet file storage.

    Singleton-style connection — the DuckDB handle is opened once and
    reused for the lifetime of the process.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._conn: duckdb.DuckDBPyConnection | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """Return (or create) the DuckDB connection."""
        if self._conn is None:
            db_path = str(self._settings.duckdb_path)
            log.info("Opening DuckDB database: %s", db_path)
            self._conn = duckdb.connect(db_path)
            self._conn.execute("SET enable_progress_bar = false")
        return self._conn

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            log.info("DuckDB connection closed.")

    # ------------------------------------------------------------------
    # Write / Upsert
    # ------------------------------------------------------------------

    def save_daily(self, df: pd.DataFrame) -> int:
        """Save daily OHLCV data — one Parquet file **per trading day**.

        Example output: ``data_files/daily/20260601.parquet``
        """
        return self._save_partitioned(
            df, "daily", _PRIMARY_KEYS["daily"], "trade_date", by_date=True,
        )

    def save_stock_basic(self, df: pd.DataFrame) -> int:
        """Save stock basic info — single Parquet file."""
        return self._save_single(df, "stock_basic", _PRIMARY_KEYS["stock_basic"])

    def save_income(self, df: pd.DataFrame) -> int:
        """Save income statement data — partitioned by quarter end date.

        Each quarter's data is stored in a separate Parquet file named
        after the quarter end date (e.g. ``20260331.parquet``).
        """
        return self._save_partitioned(
            df, "income", _PRIMARY_KEYS["income"], "end_date", by_date=True,
        )

    def save_balancesheet(self, df: pd.DataFrame) -> int:
        """Save balance sheet data — partitioned by quarter end date.

        Each quarter's data is stored in a separate Parquet file named
        after the quarter end date (e.g. ``20260331.parquet``).
        """
        return self._save_partitioned(
            df, "balancesheet", _PRIMARY_KEYS["balancesheet"],
            "end_date", by_date=True,
        )

    def save_cashflow(self, df: pd.DataFrame) -> int:
        """Save cashflow statement data — partitioned by quarter end date.

        Each quarter's data is stored in a separate Parquet file named
        after the quarter end date (e.g. ``20260331.parquet``).
        """
        return self._save_partitioned(
            df, "cashflow", _PRIMARY_KEYS["cashflow"],
            "end_date", by_date=True,
        )

    def save_trade_calendar(self, df: pd.DataFrame) -> int:
        """Save trading calendar — partitioned by year.

        Example: ``data_files/trade_calendar/2026.parquet``
        """
        return self._save_partitioned(
            df, "trade_calendar", _PRIMARY_KEYS["trade_calendar"],
            "cal_date", by_date=False,
        )

    def save_st_stocks(self, df: pd.DataFrame) -> int:
        """Save ST stock list — single Parquet file.

        Example: ``data_files/st_stocks.parquet``
        """
        return self._save_single(df, "st_stocks", _PRIMARY_KEYS["st_stocks"])

    def save_adjfactor(self, df: pd.DataFrame) -> int:
        """Save adjustment factor data — partitioned by trade date.

        Example: ``data_files/adjfactor/20260627.parquet``
        """
        return self._save_partitioned(
            df, "adjfactor", _PRIMARY_KEYS["adjfactor"],
            "trade_date", by_date=True,
        )

    def save_moneyflow(self, df: pd.DataFrame) -> int:
        """Save moneyflow data — partitioned by trade date.

        Example: ``data_files/moneyflow/20260627.parquet``
        """
        return self._save_partitioned(
            df, "moneyflow", _PRIMARY_KEYS["moneyflow"],
            "trade_date", by_date=True,
        )

    def save_index_basic(self, df: pd.DataFrame, market: str) -> int:
        """Save index basic info for a single market.

        Each market is stored as a separate Parquet file in the
        ``data_files/index_basic/`` directory.

        Args:
            df: DataFrame from ``fetch_index_basic(market)``.
            market: One of 'CSI', 'SSE', 'SZSE'.

        Returns:
            Number of rows saved.
        """
        if df.empty:
            log.warning("index_basic/%s: empty DataFrame, nothing to save.", market)
            return 0

        # Cast columns to correct types to prevent DuckDB type inference
        # issues (e.g. all-NULL VARCHAR columns being inferred as INTEGER).
        col_types = _COLUMN_TYPES.get("index_basic", {})
        for col, dtype in col_types.items():
            if col in df.columns:
                if dtype == "VARCHAR":
                    df[col] = df[col].astype(str).replace("nan", "").replace("<NA>", "").replace("None", "")
                    df[col] = df[col].replace("", None)
                elif dtype == "DOUBLE":
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                elif dtype == "INTEGER":
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

        market_lower = _INDEX_BASIC_MARKETS.get(market, market.lower())
        path = self._parquet_path("index_basic", market_lower)
        self._upsert_parquet(df, path, _PRIMARY_KEYS["index_basic"])

        self._ensure_views("index_basic")
        self.write_manifest()
        log.info("index_basic/%s: saved %d rows.", market, len(df))
        return len(df)

    def save_index_weight(self, df: pd.DataFrame, index_code: str) -> int:
        """Save index constituent weight data for a single index.

        Data is stored in ``data_files/index_weight/{short_name}/`` with
        files named ``{short_name}_{trade_date}.parquet``.

        Args:
            df: DataFrame from ``fetch_index_weight(index_code)``.
            index_code: Tushare index code e.g. '000300.SH', '000905.SH'.

        Returns:
            Number of rows saved.
        """
        short_name = _INDEX_WEIGHT_INDICES.get(index_code)
        if short_name is None:
            log.error("Unknown index_code for index_weight: %s", index_code)
            return 0

        if df.empty:
            log.warning("index_weight/%s: empty DataFrame, nothing to save.", short_name)
            return 0

        # Cast columns to correct types
        col_types = _COLUMN_TYPES.get("index_weight", {})
        for col, dtype in col_types.items():
            if col in df.columns:
                if dtype == "VARCHAR":
                    df[col] = df[col].astype(str).replace("nan", "").replace("<NA>", "").replace("None", "")
                    df[col] = df[col].replace("", None)
                elif dtype == "DOUBLE":
                    df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.copy()
        pkeys = _PRIMARY_KEYS["index_weight"]
        total = 0

        # Partition by trade_date within the index subdirectory
        for trade_date, group in df.groupby("trade_date"):
            filename = f"{short_name}_{trade_date}.parquet"
            path = self._parquet_dir("index_weight") / short_name / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            self._upsert_parquet(group, path, pkeys)
            total += len(group)

        self._ensure_views("index_weight")
        self.write_manifest()
        log.info(
            "index_weight/%s: saved %d rows across %d date(s).",
            short_name, total, df["trade_date"].nunique(),
        )
        return total

    def save_index_daily(self, df: pd.DataFrame, index_code: str) -> int:
        """Save index daily OHLCV data for a single index.

        Data is stored in ``data_files/index_daily/{short_name}/`` with
        files named ``{short_name}_{trade_date}.parquet``.

        Args:
            df: DataFrame from ``fetch_index_daily(index_code)``.
            index_code: Tushare index code e.g. '000300.SH', '000905.SH'.

        Returns:
            Number of rows saved.
        """
        short_name = _INDEX_DAILY_INDICES.get(index_code)
        if short_name is None:
            log.error("Unknown index_code for index_daily: %s", index_code)
            return 0

        if df.empty:
            log.warning("index_daily/%s: empty DataFrame, nothing to save.", short_name)
            return 0

        # Cast columns to correct types
        col_types = _COLUMN_TYPES.get("index_daily", {})
        for col, dtype in col_types.items():
            if col in df.columns:
                if dtype == "VARCHAR":
                    df[col] = df[col].astype(str).replace("nan", "").replace("<NA>", "").replace("None", "")
                    df[col] = df[col].replace("", None)
                elif dtype == "DOUBLE":
                    df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.copy()
        pkeys = _PRIMARY_KEYS["index_daily"]
        total = 0

        # Partition by trade_date within the index subdirectory
        for trade_date, group in df.groupby("trade_date"):
            filename = f"{short_name}_{trade_date}.parquet"
            path = self._parquet_dir("index_daily") / short_name / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            self._upsert_parquet(group, path, pkeys)
            total += len(group)

        self._ensure_views("index_daily")
        self.write_manifest()
        log.info(
            "index_daily/%s: saved %d rows across %d date(s).",
            short_name, total, df["trade_date"].nunique(),
        )
        return total

    # ------------------------------------------------------------------
    # Read / Query helpers
    # ------------------------------------------------------------------

    def read_daily(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Read daily data from DuckDB with optional filters."""
        return self._read_table("daily", ts_code, start_date, end_date)

    def read_stock_basic(self, ts_code: str | None = None) -> pd.DataFrame:
        """Read stock basic info."""
        return self._read_table("stock_basic", ts_code)

    def read_income(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Read income statement data."""
        return self._read_table("income", ts_code, start_date, end_date)

    def read_balancesheet(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Read balance sheet data."""
        return self._read_table("balancesheet", ts_code, start_date, end_date)

    def read_cashflow(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Read cashflow statement data."""
        return self._read_table("cashflow", ts_code, start_date, end_date)

    def read_trade_calendar(
        self,
        exchange: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Read trading calendar with optional filters."""
        return self._read_table(
            "trade_calendar", exchange, start_date, end_date,
        )

    def read_st_stocks(self, ts_code: str | None = None) -> pd.DataFrame:
        """Read current ST stock list."""
        return self._read_table("st_stocks", ts_code)

    def read_adjfactor(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Read adjustment factor data."""
        return self._read_table("adjfactor", ts_code, start_date, end_date)

    def read_moneyflow(
        self,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Read moneyflow data."""
        return self._read_table("moneyflow", ts_code, start_date, end_date)

    def read_index_basic(
        self,
        market: str | None = None,
    ) -> pd.DataFrame:
        """Read index basic info, optionally filtered by market.

        Args:
            market: 'CSI', 'SSE', 'SZSE', or None for all.

        Returns:
            DataFrame with index basic information.
        """
        self._ensure_views("index_basic")
        if market:
            sql = f"SELECT * FROM index_basic_view WHERE market = '{market}' ORDER BY ts_code"
        else:
            sql = "SELECT * FROM index_basic_view ORDER BY ts_code"
        try:
            return self.conn.execute(sql).df()
        except Exception:
            log.exception("Read failed for index_basic")
            return pd.DataFrame()

    def read_index_weight(
        self,
        index_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        con_code: str | None = None,
    ) -> pd.DataFrame:
        """Read index constituent weight data.

        Args:
            index_code: Tushare index code e.g. '000300.SH', or None for all.
            start_date: Start date 'YYYYMMDD'.
            end_date: End date 'YYYYMMDD'.
            con_code: Filter by constituent stock code.

        Returns:
            DataFrame with index weight data.
        """
        self._ensure_views("index_weight")

        conditions: list[str] = []
        if index_code:
            conditions.append(f"index_code = '{index_code}'")
        if start_date:
            conditions.append(f"trade_date >= '{start_date}'")
        if end_date:
            conditions.append(f"trade_date <= '{end_date}'")
        if con_code:
            conditions.append(f"con_code = '{con_code}'")

        sql = "SELECT * FROM index_weight_view"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY index_code, trade_date, con_code"

        try:
            return self.conn.execute(sql).df()
        except Exception:
            log.exception("Read failed for index_weight")
            return pd.DataFrame()

    def read_index_daily(
        self,
        index_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Read index daily OHLCV data.

        Args:
            index_code: Tushare index code e.g. '000300.SH', or None for all.
            start_date: Start date 'YYYYMMDD'.
            end_date: End date 'YYYYMMDD'.

        Returns:
            DataFrame with index daily data.
        """
        self._ensure_views("index_daily")

        conditions: list[str] = []
        if index_code:
            conditions.append(f"ts_code = '{index_code}'")
        if start_date:
            conditions.append(f"trade_date >= '{start_date}'")
        if end_date:
            conditions.append(f"trade_date <= '{end_date}'")

        sql = "SELECT * FROM index_daily_view"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY ts_code, trade_date"

        try:
            return self.conn.execute(sql).df()
        except Exception:
            log.exception("Read failed for index_daily")
            return pd.DataFrame()

    def execute_sql(self, sql: str) -> pd.DataFrame:
        """Execute an arbitrary SQL query against the DuckDB database.

        All Parquet-backed tables are available as views named:
        ``daily_view``, ``stock_basic_view``, ``income_view``,
        ``balancesheet_view``, ``adjfactor_view``, ``moneyflow_view``.
        """
        self._ensure_views()
        log.info("Executing SQL: %s", sql[:200])
        try:
            return self.conn.execute(sql).df()
        except Exception:
            log.exception("SQL execution failed")
            raise

    def get_table_schema(self, table: str) -> pd.DataFrame:
        """Return column information for a DuckDB table/view."""
        self._ensure_views()
        view_name = f"{table}_view"
        return self.conn.execute(f"DESCRIBE {view_name}").df()

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def write_manifest(self) -> None:
        """Write ``manifest.json`` summarising all stored data."""
        manifest: dict[str, Any] = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "tables": {},
        }
        for dt in _ALL_TABLES:
            info: dict[str, Any] = {}
            view_name = f"{dt}_view"
            try:
                self._ensure_views(dt)
                cnt_df = self.conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM {view_name}"
                ).df()
                info["rows"] = int(cnt_df["cnt"].iloc[0])
            except Exception:
                info["rows"] = 0

            # Count Parquet files
            if dt in _SINGLE_FILE_TABLES:
                p = _single_file_path(self._settings, dt)
                info["files"] = 1 if p.exists() else 0
                info["partition"] = "single"
            elif dt == "index_weight":
                d = self._parquet_dir(dt)
                all_files: list[Path] = []
                if d.exists():
                    for sub_dir in d.iterdir():
                        if sub_dir.is_dir():
                            all_files.extend(sorted(sub_dir.glob("*.parquet")))
                info["files"] = len(all_files)
                info["partition"] = "by_index"
                if all_files:
                    info["date_range"] = {
                        "first": all_files[0].stem,
                        "last": all_files[-1].stem,
                    }
            elif dt == "index_daily":
                d = self._parquet_dir(dt)
                all_files: list[Path] = []
                if d.exists():
                    for sub_dir in d.iterdir():
                        if sub_dir.is_dir():
                            all_files.extend(sorted(sub_dir.glob("*.parquet")))
                info["files"] = len(all_files)
                info["partition"] = "by_index"
                if all_files:
                    info["date_range"] = {
                        "first": all_files[0].stem,
                        "last": all_files[-1].stem,
                    }
            else:
                d = self._parquet_dir(dt)
                files = sorted(d.glob("*.parquet")) if d.exists() else []
                info["files"] = len(files)
                if dt == "index_basic":
                    info["partition"] = "by_market"
                elif dt in _BY_DATE_TABLES:
                    info["partition"] = "by_date"
                else:
                    info["partition"] = "by_year"
                if files:
                    info["date_range"] = {
                        "first": files[0].stem,
                        "last": files[-1].stem,
                    }

            manifest["tables"][dt] = info

        path = self._settings.manifest_path
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        log.debug("Manifest written: %s", path)

    # ------------------------------------------------------------------
    # Internal: write paths
    # ------------------------------------------------------------------

    def _parquet_dir(self, data_type: str) -> Path:
        return self._settings.data_dir / data_type

    def _parquet_path(self, data_type: str, partition_key: str) -> Path:
        d = self._parquet_dir(data_type)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{partition_key}.parquet"

    # ------------------------------------------------------------------
    # Internal: save logic
    # ------------------------------------------------------------------

    def _save_partitioned(
        self,
        df: pd.DataFrame,
        data_type: str,
        pkeys: list[str],
        date_col: str,
        by_date: bool = False,
    ) -> int:
        """Save a DataFrame to partitioned Parquet files with upsert.

        Args:
            df: DataFrame to save.
            data_type: One of 'daily', 'income'.
            pkeys: Primary-key columns for dedup.
            date_col: Column to partition on.
            by_date: If True, partition by full date (e.g. trade_date
                     or quarter end_date); if False, partition by year.
        """
        if df.empty:
            log.warning("%s: empty DataFrame, nothing to save.", data_type)
            return 0

        if date_col not in df.columns:
            log.error("%s: missing date column '%s'", data_type, date_col)
            return 0

        df = df.copy()
        partition_label = date_col if by_date else "_year"

        if by_date:
            # Partition key = full trade date, e.g. "20260601"
            df["_partition"] = df[date_col]
        else:
            # Partition key = year only, e.g. "2026"
            df["_partition"] = df[date_col].str[:4]

        total = 0
        for key, group in df.groupby("_partition"):
            group = group.drop(columns=["_partition"])
            path = self._parquet_path(data_type, key)
            self._upsert_parquet(group, path, pkeys)
            total += len(group)

        # Refresh DuckDB views so new data is queryable
        self._ensure_views(data_type)
        self.write_manifest()

        n_files = df["_partition"].nunique()
        partition_unit = "date" if by_date else "year"
        log.info(
            "%s: saved %d rows across %d %s partitions.",
            data_type, total, n_files, partition_unit,
        )
        return total

    def _save_single(
        self,
        df: pd.DataFrame,
        data_type: str,
        pkeys: list[str],
    ) -> int:
        """Save to a single Parquet file with upsert."""
        if df.empty:
            log.warning("%s: empty DataFrame, nothing to save.", data_type)
            return 0

        path = self._settings.data_dir / f"{data_type}.parquet"
        self._upsert_parquet(df, path, pkeys)

        self._ensure_views(data_type)
        self.write_manifest()
        log.info("%s: saved %d rows.", data_type, len(df))
        return len(df)

    # ------------------------------------------------------------------
    # Internal: upsert via DuckDB
    # ------------------------------------------------------------------

    def _upsert_parquet(
        self,
        df: pd.DataFrame,
        path: Path,
        pkeys: list[str],
    ) -> None:
        """Merge *df* into an existing (or new) Parquet file on *pkeys*.

        Strategy:
        1. Register *df* as a temporary DuckDB table.
        2. If *path* exists, read it, concat with new data, dedup (keep last).
        3. Write the merged result back to Parquet.
        """
        data_type = _infer_data_type_from_path(path)
        col_types = _COLUMN_TYPES.get(data_type, {})

        # Ensure columns exist in df
        for col in col_types:
            if col not in df.columns:
                df[col] = None

        # Register incoming data as temp table
        temp_name = "_tmp_incoming"
        self.conn.register(temp_name, df)

        if path.exists():
            existing = self.conn.execute(
                f"SELECT * FROM read_parquet('{path}')"
            ).df()

            # Align columns so concat doesn't warn about all-NA columns.
            all_cols = sorted(set(existing.columns) | set(df.columns))
            existing = existing.reindex(columns=all_cols)
            df = df.reindex(columns=all_cols)

            combined = pd.concat([existing, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=pkeys, keep="last")
            combined = combined.reset_index(drop=True)

            self.conn.register("_tmp_combined", combined)
            self.conn.execute(
                f"COPY _tmp_combined TO '{path}' (FORMAT PARQUET, OVERWRITE_OR_IGNORE true)"
            )
            self.conn.unregister("_tmp_combined")

            log.debug(
                "upsert %s: %d existing + %d new → %d merged.",
                path.name, len(existing), len(df), len(combined),
            )
        else:
            self.conn.execute(
                f"COPY {temp_name} TO '{path}' (FORMAT PARQUET)"
            )
            log.debug("Created new Parquet: %s (%d rows)", path.name, len(df))

        self.conn.unregister(temp_name)

    # ------------------------------------------------------------------
    # Internal: DuckDB views
    # ------------------------------------------------------------------

    def _ensure_views(self, data_type: str | None = None) -> None:
        """Create/replace DuckDB views that point to the Parquet globs.

        When no Parquet files exist for a data type an empty view with the
        correct column schema is still created, so that ``SELECT ... FROM
        <view>`` never fails with ``CatalogException``.
        """
        types = [data_type] if data_type else list(_ALL_TABLES)

        for dt in types:
            view_name = f"{dt}_view"
            try:
                if dt in _SINGLE_FILE_TABLES:
                    path = _single_file_path(self._settings, dt)
                    if path.exists():
                        self.conn.execute(
                            f"CREATE OR REPLACE VIEW {view_name} AS "
                            f"SELECT * FROM read_parquet('{path}')"
                        )
                    else:
                        self._create_empty_view(dt, view_name)
                elif dt == "index_basic":
                    # Use explicit column type casting — all-NULL columns
                    # would otherwise be inferred as INTEGER by DuckDB.
                    # Columns are quoted to handle reserved words like "desc".
                    glob_path = self._parquet_dir(dt) / "*.parquet"
                    if list(self._parquet_dir(dt).glob("*.parquet")):
                        col_types = _COLUMN_TYPES.get(dt, {})
                        if col_types:
                            casts = []
                            for col_name, col_type in col_types.items():
                                casts.append(
                                    f'CAST("{col_name}" AS {col_type}) AS "{col_name}"'
                                )
                            cast_sel = "SELECT " + ", ".join(casts)
                            self.conn.execute(
                                f"CREATE OR REPLACE VIEW {view_name} AS "
                                f"{cast_sel} FROM read_parquet('{glob_path}', "
                                f"union_by_name=true)"
                            )
                        else:
                            self.conn.execute(
                                f"CREATE OR REPLACE VIEW {view_name} AS "
                                f"SELECT * FROM read_parquet('{glob_path}', "
                                f"union_by_name=true)"
                            )
                    else:
                        self._create_empty_view(dt, view_name)
                elif dt == "index_weight":
                    self._ensure_index_weight_views()
                elif dt == "index_daily":
                    self._ensure_index_daily_views()
                else:
                    glob_path = self._parquet_dir(dt) / "*.parquet"
                    if list(self._parquet_dir(dt).glob("*.parquet")):
                        self.conn.execute(
                            f"CREATE OR REPLACE VIEW {view_name} AS "
                            f"SELECT * FROM read_parquet('{glob_path}', "
                            f"union_by_name=true)"
                        )
                    else:
                        self._create_empty_view(dt, view_name)
            except Exception:
                log.exception("Failed to create view %s", view_name)

    def _create_empty_view(self, data_type: str, view_name: str) -> None:
        """Create an empty view with the correct column schema.

        The view returns zero rows but has the right column names and types
        so that queries never fail with ``CatalogException``.
        """
        col_types = _COLUMN_TYPES.get(data_type, {})
        if not col_types:
            log.debug("No column type info for %s, skipping empty view.", data_type)
            return
        col_defs: list[str] = []
        for col_name, col_type in col_types.items():
            col_defs.append(f"CAST(NULL AS {col_type}) AS {col_name}")
        empty_select = "SELECT " + ", ".join(col_defs) + " WHERE FALSE"
        self.conn.execute(
            f"CREATE OR REPLACE VIEW {view_name} AS {empty_select}"
        )

    def _ensure_index_weight_views(self) -> None:
        """Create per-index and combined views for index_weight data.

        Creates:
        - ``index_weight_zz1000_view``, ``index_weight_zz2000_view``,
          ``index_weight_zz500_view``, ``index_weight_hs300_view``
        - ``index_weight_view`` — union of all per-index views.
        """
        col_types = _COLUMN_TYPES.get("index_weight", {})
        base_dir = self._parquet_dir("index_weight")
        any_data = False
        union_parts: list[str] = []

        for short_name in _INDEX_WEIGHT_INDICES.values():
            view_name = f"index_weight_{short_name}_view"
            glob_path = base_dir / short_name / "*.parquet"
            files_exist = bool(list(base_dir.glob(f"{short_name}/*.parquet")))

            if files_exist:
                any_data = True
                if col_types:
                    casts = []
                    for col_name, col_type in col_types.items():
                        casts.append(
                            f'CAST("{col_name}" AS {col_type}) AS "{col_name}"'
                        )
                    cast_sel = "SELECT " + ", ".join(casts)
                    self.conn.execute(
                        f"CREATE OR REPLACE VIEW {view_name} AS "
                        f"{cast_sel} FROM read_parquet('{glob_path}', "
                        f"union_by_name=true)"
                    )
                else:
                    self.conn.execute(
                        f"CREATE OR REPLACE VIEW {view_name} AS "
                        f"SELECT * FROM read_parquet('{glob_path}', "
                        f"union_by_name=true)"
                    )
                union_parts.append(f"SELECT * FROM {view_name}")
            else:
                self._create_empty_view("index_weight", view_name)

        # Combined view
        if union_parts:
            union_sql = " UNION ALL ".join(union_parts)
            self.conn.execute(
                f"CREATE OR REPLACE VIEW index_weight_view AS {union_sql}"
            )
        else:
            self._create_empty_view("index_weight", "index_weight_view")

    def _ensure_index_daily_views(self) -> None:
        """Create per-index and combined views for index_daily data.

        Creates:
        - ``index_daily_zz1000_view``, ``index_daily_zz2000_view``,
          ``index_daily_zz500_view``, ``index_daily_hs300_view``
        - ``index_daily_view`` — union of all per-index views.
        """
        col_types = _COLUMN_TYPES.get("index_daily", {})
        base_dir = self._parquet_dir("index_daily")
        union_parts: list[str] = []

        for short_name in _INDEX_DAILY_INDICES.values():
            view_name = f"index_daily_{short_name}_view"
            glob_path = base_dir / short_name / "*.parquet"
            files_exist = bool(list(base_dir.glob(f"{short_name}/*.parquet")))

            if files_exist:
                if col_types:
                    casts = []
                    for col_name, col_type in col_types.items():
                        casts.append(
                            f'CAST("{col_name}" AS {col_type}) AS "{col_name}"'
                        )
                    cast_sel = "SELECT " + ", ".join(casts)
                    self.conn.execute(
                        f"CREATE OR REPLACE VIEW {view_name} AS "
                        f"{cast_sel} FROM read_parquet('{glob_path}', "
                        f"union_by_name=true)"
                    )
                else:
                    self.conn.execute(
                        f"CREATE OR REPLACE VIEW {view_name} AS "
                        f"SELECT * FROM read_parquet('{glob_path}', "
                        f"union_by_name=true)"
                    )
                union_parts.append(f"SELECT * FROM {view_name}")
            else:
                self._create_empty_view("index_daily", view_name)

        # Combined view
        if union_parts:
            union_sql = " UNION ALL ".join(union_parts)
            self.conn.execute(
                f"CREATE OR REPLACE VIEW index_daily_view AS {union_sql}"
            )
        else:
            self._create_empty_view("index_daily", "index_daily_view")

    # ------------------------------------------------------------------
    # Internal: read
    # ------------------------------------------------------------------

    # Columns used for filtering and ordering per data type.
    # For tables that don't have ``ts_code`` we use a different primary column.
    _FILTER_COL: dict[str, str] = {
        "trade_calendar": "exchange",
    }
    _SORT_COLS: dict[str, list[str]] = {
        "trade_calendar": ["cal_date", "exchange"],
    }

    def _read_table(
        self,
        data_type: str,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Generic Parquet-backed read with filters."""
        self._ensure_views(data_type)
        view = f"{data_type}_view"

        date_col = (
            "trade_date" if data_type in ("daily", "adjfactor", "moneyflow")
            else ("end_date" if data_type in ("income", "cashflow", "balancesheet")
            else ("cal_date" if data_type == "trade_calendar" else None))
        )

        filter_col = self._FILTER_COL.get(data_type, "ts_code")
        sort_cols = self._SORT_COLS.get(
            data_type,
            ["ts_code"] + ([date_col] if date_col else []),
        )

        conditions = []
        params: list[Any] = []
        if ts_code:
            conditions.append(f"{filter_col} = ?")
            params.append(ts_code)
        if date_col and start_date:
            conditions.append(f"{date_col} >= ?")
            params.append(start_date)
        if date_col and end_date:
            conditions.append(f"{date_col} <= ?")
            params.append(end_date)

        sql = f"SELECT * FROM {view}"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if sort_cols:
            sql += " ORDER BY " + ", ".join(sort_cols)

        try:
            return self.conn.execute(sql, params).df()
        except Exception:
            log.exception("Read failed for %s", data_type)
            return pd.DataFrame()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _infer_data_type_from_path(path: Path) -> str:
    """Heuristic to determine data_type from a Parquet path."""
    parent = path.parent.name
    if parent in ("daily", "income", "balancesheet", "trade_calendar", "adjfactor", "moneyflow"):
        return parent
    name = path.stem
    if name in ("stock_basic", "st_stocks"):
        return name
    return parent


def _single_file_path(settings, data_type: str) -> Path:
    """Return the Parquet path for a single-file table."""
    mapping: dict[str, Path] = {
        "stock_basic": settings.stock_basic_parquet_path,
        "st_stocks": settings.st_stocks_parquet_path,
    }
    return mapping.get(data_type, settings.data_dir / f"{data_type}.parquet")
