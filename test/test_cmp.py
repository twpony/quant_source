#!/usr/bin/env python3
"""Comparison / ad-hoc test module — quick CSV inspection and data checks."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.csv_io import csv

# 东方财富客户端显示股票数量有5532只，而tushare显示有5525只
# 为了弄清楚是不是tushare的数据不全，比较了两个数据列表的差异
# 结果发现tushare的数据是可信的，两者差异原因是：
# 东方财富客户端显示了部分未上市的股票信息，而tushare中未包含了这些未上市的股票数据。
def main() -> None:
    """Read and display a sample CSV file."""
    df_0 = csv.read("./test/output/stock_basic.csv")
    if df_0 is not None:
        df_0.info()
        print(df_0.head())
    col_0 = df_0.iloc[:, 0]

    df_1 = csv.read("./test/temp/stock_dfcf.csv")
    if df_1 is not None:
        df_1.info()
        print(df_1.head())
    col_1 = df_1.iloc[:, 1]

    print(f"First column name in stock_basic.csv: {col_0.name}, {col_0.nunique()} unique values")
    print(f"Second column name in stock_dfcf.csv: {col_1.name}, {col_1.nunique()} unique values")

    result = col_1[~col_1.isin(col_0)]
    # tushare中没有的股票主要为未上市的股票信息
    print(f"Values in stock_dfcf.csv that are not in stock_basic.csv: {result.tolist()}")
if __name__ == "__main__":
    main()