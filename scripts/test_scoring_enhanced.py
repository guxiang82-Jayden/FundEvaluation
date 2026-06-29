"""指数增强记分卡离线测试。"""
import numpy as np
import pandas as pd

import run_monthly_index as runner
import scoring_enhanced as se


def _rows(n=6):
    return pd.DataFrame({
        "fund_code": [f"X{i:03d}" for i in range(n)],
        "fund_name": [f"中证500增强{i}" for i in range(n)],
        "index_family": "中证500",
        "excess_return_ann": np.linspace(0.08, -0.01, n),
        "info_ratio": np.linspace(1.5, -0.2, n),
        "excess_win_rate": np.linspace(0.8, 0.3, n),
        "excess_max_drawdown": np.linspace(-0.02, -0.15, n),
        "excess_calmar": np.linspace(4.0, -0.1, n),
        "style_stability": np.linspace(0.9, 0.4, n),
        "tracking_error": np.linspace(0.03, 0.09, n),
        "manager_experience": np.linspace(10, 2, n),
        "management_load": np.linspace(20, 100, n),
        "total_fee": np.linspace(0.005, 0.015, n),
        "scale_yi": np.linspace(50, 5, n),
    })


def test_high_stable_excess_scores_higher():
    scored, deferred = se.score_enhanced(_rows())
    assert deferred.empty and len(scored) == 6
    best = scored.loc[scored["excess_return_ann"].idxmax()]
    worst = scored.loc[scored["excess_return_ann"].idxmin()]
    assert best["score_A_return"] > worst["score_A_return"]
    assert best["score_B_risk"] > worst["score_B_risk"]
    assert scored["score_label"].eq("formal").all()

    missing_style = _rows()
    missing_style["style_stability"] = np.nan
    rescored, _ = se.score_enhanced(missing_style)
    assert rescored["score_label"].eq("provisional_style_missing").all()


def test_tolerance_warnings():
    rows = _rows()
    rows.loc[0, "tracking_error"] = 0.005
    rows.loc[1, "tracking_error"] = 0.13
    prepared = se.prepare_metrics(rows)
    assert bool(prepared.loc[0, "pseudo_enhance_warn"])
    assert bool(prepared.loc[1, "te_excess_warn"])


def test_missing_mapping_and_small_group_defer():
    missing = _rows()
    missing["index_family"] = "映射缺失"
    scored, deferred = se.score_enhanced(missing)
    assert scored.empty
    assert deferred["score_label"].eq("provisional_mapping_missing").all()
    scored, deferred = se.score_enhanced(_rows(4))
    assert scored.empty and len(deferred) == 4


def test_excess_metrics():
    rng = np.random.default_rng(40)
    dates = pd.bdate_range("2024-01-01", periods=300)
    index_ret = pd.Series(rng.normal(0.0002, 0.01, len(dates)), index=dates)
    fund_ret = index_ret + 0.0002 + rng.normal(0, 0.001, len(dates))
    nav = (1 + fund_ret).cumprod()
    metrics = se.excess_metrics(nav, index_ret)
    assert metrics["excess_return_ann"] > 0
    assert metrics["info_ratio"] > 0
    assert metrics["tracking_error"] < 0.03


def test_only_enhanced_empty_passive_gate():
    gated, withdrawn = runner.apply_te_gate(pd.DataFrame(), "INDEX")
    assert gated.empty and withdrawn.empty


if __name__ == "__main__":
    test_high_stable_excess_scores_higher()
    test_tolerance_warnings()
    test_missing_mapping_and_small_group_defer()
    test_excess_metrics()
    test_only_enhanced_empty_passive_gate()
    print("ENHANCED scoring tests passed [OK]")
