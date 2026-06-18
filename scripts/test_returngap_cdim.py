"""半年频 ReturnGap 数据通路测试（离线合成数据）。"""
import os

import numpy as np
import pandas as pd

import build_returngap_cdim as rg
import cdim


def test_report_period_filter():
    assert rg._report_date("2025年2季度股票投资明细") == pd.Timestamp("2025-06-30")
    assert rg._report_date("2025年4季度股票投资明细") == pd.Timestamp("2025-12-31")
    assert rg._report_date("2025年1季度股票投资明细") is None


def test_returngap_and_coverage_gate():
    dates = pd.bdate_range("2024-06-30", "2025-06-30")
    nav = pd.Series(np.linspace(1.0, 1.15, len(dates)), index=dates)
    snapshots = {
        pd.Timestamp("2024-06-30"): pd.DataFrame({
            "stock_code": ["000001", "000002"],
            "weight": [0.8, 0.2],
        }),
        pd.Timestamp("2024-12-31"): pd.DataFrame({
            "stock_code": ["000001", "000002"],
            "weight": [0.5, 0.5],
        }),
        pd.Timestamp("2025-06-30"): pd.DataFrame({
            "stock_code": ["000001"],
            "weight": [1.0],
        }),
    }
    prices = {
        "000001": pd.Series(np.linspace(10, 11, len(dates)), index=dates),
        "000002": pd.Series(np.linspace(20, 21, len(dates)), index=dates),
    }
    result, records = rg.compute_return_gap(nav, snapshots, prices)
    assert result["return_gap_n_periods"] == 2
    assert result["holdings_coverage"] == 1.0
    assert np.isfinite(result["return_gap"])
    assert len(records) == 2

    low_prices = {"000001": prices["000001"]}
    low, low_records = rg.compute_return_gap(nav, snapshots, low_prices)
    assert low["return_gap_n_periods"] == 1
    assert sum(not row["valid"] for row in low_records) == 1


def test_cdim_low_confidence_degrades():
    old_path = cdim.CDIM_CSV
    try:
        cdim.CDIM_CSV = "_test_returngap_cdim.csv"
        pd.DataFrame([
            {"fund_code": "000001", "return_gap": 0.03,
             "return_gap_n_periods": 2, "holdings_coverage": 0.8},
            {"fund_code": "000002", "return_gap": 0.10,
             "return_gap_n_periods": 1, "holdings_coverage": 0.9},
            {"fund_code": "000003", "return_gap": 0.10,
             "return_gap_n_periods": 3, "holdings_coverage": 0.6},
        ]).to_csv(cdim.CDIM_CSV, index=False)
        merged = cdim.load_cdim(pd.DataFrame({
            "fund_code": ["000001", "000002", "000003"],
        }))
    finally:
        if os.path.exists(cdim.CDIM_CSV):
            os.remove(cdim.CDIM_CSV)
        cdim.CDIM_CSV = old_path
    assert merged.loc[0, "return_gap"] == 0.03
    assert pd.isna(merged.loc[1, "return_gap"])
    assert pd.isna(merged.loc[2, "return_gap"])


if __name__ == "__main__":
    test_report_period_filter()
    test_returngap_and_coverage_gate()
    test_cdim_low_confidence_degrades()
    print("ReturnGap C3 tests passed [OK]")
