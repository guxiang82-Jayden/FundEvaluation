"""RBSA 风格数据通路测试（离线合成数据）。"""
import numpy as np
import pandas as pd

import build_style_cdim
import cdim
import screening


def test_style_metrics_and_cdim_merge():
    rng = np.random.default_rng(36)
    dates = pd.bdate_range("2021-01-01", periods=1000)
    styles = pd.DataFrame({
        "large_value": rng.normal(0.0003, 0.009, len(dates)),
        "large_growth": rng.normal(0.0004, 0.012, len(dates)),
        "small_value": rng.normal(0.0003, 0.011, len(dates)),
        "small_growth": rng.normal(0.0005, 0.015, len(dates)),
    }, index=dates)
    fund_ret = 0.8 * styles["small_growth"] + 0.2 * styles["large_growth"]
    nav = (1 + fund_ret).cumprod()
    result = build_style_cdim.compute_style_metrics(nav, styles)
    assert 0 <= result["style_stability"] <= 1
    assert result["rbsa_r2"] > 0.95
    assert result["style_small_growth"] > 0.7

    old_path = cdim.CDIM_CSV
    try:
        cdim.CDIM_CSV = "_test_style_cdim.csv"
        pd.DataFrame([{"fund_code": "000001", **result}]).to_csv(
            cdim.CDIM_CSV, index=False)
        merged = cdim.load_cdim(pd.DataFrame({
            "fund_code": ["000001"],
            "fund_name": ["样本基金"],
            "fund_age_for_style": [5.0],
            "style_switches_2y": [None],
        }))
    finally:
        import os
        if os.path.exists(cdim.CDIM_CSV):
            os.remove(cdim.CDIM_CSV)
        cdim.CDIM_CSV = old_path
    assert np.isclose(
        merged.loc[0, "style_stability"], result["style_stability"])
    assert "style_switches_2y_x" not in merged.columns
    assert merged.loc[0, "style_switches_2y"] == result["style_switches_2y"]


def test_n7_strictly_above_threshold():
    base = pd.DataFrame({
        "fund_code": ["000001", "000002"],
        "fund_name": ["稳定样本", "漂移样本"],
        "fund_age_for_style": [5.0, 5.0],
        "style_switches_2y": [2, 3],
    })
    out = screening.apply_screening(base)
    assert not bool(out.loc[0, "style_drift_warn"])
    assert bool(out.loc[1, "style_drift_warn"])
    assert "N7_风格漂移" not in out.loc[1, "screen_reasons"]


def test_low_r2_degrades_c2_and_n7():
    old_path = cdim.CDIM_CSV
    try:
        cdim.CDIM_CSV = "_test_style_low_r2.csv"
        pd.DataFrame([{
            "fund_code": "000003",
            "style_stability": 0.9,
            "style_switches_2y": 9,
            "rbsa_r2": 0.1,
        }]).to_csv(cdim.CDIM_CSV, index=False)
        merged = cdim.load_cdim(pd.DataFrame({
            "fund_code": ["000003"],
            "fund_name": ["低置信样本"],
            "fund_age_for_style": [5.0],
        }))
    finally:
        import os
        if os.path.exists(cdim.CDIM_CSV):
            os.remove(cdim.CDIM_CSV)
        cdim.CDIM_CSV = old_path
    assert pd.isna(merged.loc[0, "style_stability"])
    assert pd.isna(merged.loc[0, "style_switches_2y"])
    screened = screening.apply_screening(merged)
    assert "N7_风格漂移" not in screened.loc[0, "screen_reasons"]


if __name__ == "__main__":
    test_style_metrics_and_cdim_merge()
    test_n7_strictly_above_threshold()
    test_low_r2_degrades_c2_and_n7()
    print("style C2/N7 tests passed [OK]")
