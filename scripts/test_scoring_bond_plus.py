"""Offline tests for the fixed-income-plus scoring module."""

import numpy as np
import pandas as pd

import scoring_bond_plus as sbp


def test_equity_center_band() -> None:
    assert sbp.equity_center_band(0.0) == "保守"
    assert sbp.equity_center_band(0.0999) == "保守"
    assert sbp.equity_center_band(0.10) == "稳健"
    assert sbp.equity_center_band(0.1999) == "稳健"
    assert sbp.equity_center_band(0.20) == "积极"
    assert sbp.equity_center_band(1.0) == "积极"
    assert sbp.equity_center_band(np.nan) == "未分组"
    assert sbp.equity_center_band(-0.1) == "未分组"


def test_target_dd_pass() -> None:
    dates = pd.bdate_range("2025-01-01", periods=180)
    rising = pd.Series(np.linspace(1.0, 1.2, len(dates)), index=dates)
    assert sbp.target_dd_pass(rising) == 1.0

    values = np.ones(len(dates))
    values[90] = 0.90
    breached = pd.Series(values, index=dates)
    rate = sbp.target_dd_pass(breached, target=-0.03)
    assert 0.0 < rate < 1.0
    assert np.isnan(sbp.target_dd_pass(rising.head(30)))


def test_equity_contrib_ratio() -> None:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2024-01-01", periods=300)
    equity = pd.Series(rng.normal(0.0005, 0.008, len(dates)), index=dates)
    fund_ret = 0.5 * equity
    nav = (1.0 + fund_ret).cumprod()
    ratio = sbp.equity_contrib_ratio(nav, equity)

    expected = (
        0.5 * ((1.0 + equity.iloc[1:]).prod() - 1.0)
        / ((1.0 + fund_ret.iloc[1:]).prod() - 1.0)
    )
    assert abs(ratio - expected) < 1e-10
    assert np.isnan(sbp.equity_contrib_ratio(nav, equity.head(10)))


def _score_rows() -> pd.DataFrame:
    rows = []
    band_centers = {"保守": 0.05, "稳健": 0.15, "积极": 0.25}
    for band, center in band_centers.items():
        for rank in range(10):
            rows.append(
                {
                    "fund_code": f"{band}{rank}",
                    "equity_position": center,
                    "ann_return": 0.02 + rank * 0.002,
                    "campisi_alpha": 0.002 + rank * 0.0002,
                    "monthly_positive_ratio": 0.55 + rank * 0.03,
                    "target_dd_pass": 0.60 + rank * 0.04,
                    "max_drawdown": -0.08 + rank * 0.007,
                    "calmar": 0.4 + rank * 0.12,
                    "recovery_days": 120 - rank * 10,
                    "equity_contrib_ratio": 0.10 + rank * 0.01,
                    "convertible_ratio": 0.08 + rank * 0.01,
                    "credit_sink": 0.40 + rank * 0.02,
                    "duration_dev": -0.10 + rank * 0.02,
                    "manager_experience": 2 + rank,
                    "management_load": 150 - rank * 5,
                    "total_fee": 0.009 - rank * 0.0003,
                    "inst_ratio": 0.60 - rank * 0.01,
                    "scale_yi": 10.0,
                }
            )
    return pd.DataFrame(rows)


def test_group_scoring() -> None:
    source = _score_rows()
    scored = sbp.score_bond_plus(source)

    assert len(scored) == 30
    assert scored["composite_score"].between(0, 100).all()
    assert set(scored["equity_band"]) == {"保守", "稳健", "积极"}
    assert scored["group_score_eligible"].all()

    # Identical within-band ranks must produce identical percentile scores.
    ranked = scored.assign(within_rank=scored["fund_code"].str[-1].astype(int))
    pivot = ranked.pivot(
        index="within_rank",
        columns="equity_band",
        values="score_A_return",
    )
    assert np.allclose(pivot["保守"], pivot["稳健"])
    assert np.allclose(pivot["稳健"], pivot["积极"])

    # Within each band, stronger drawdown metrics should score better on B.
    for _, group in scored.groupby("equity_band"):
        best = group.loc[group["target_dd_pass"].idxmax(), "score_B_risk"]
        worst = group.loc[group["target_dd_pass"].idxmin(), "score_B_risk"]
        assert best > worst


def test_small_and_ungrouped_are_retained() -> None:
    tiny = _score_rows().head(3).copy()
    tiny.loc[tiny.index[0], "equity_position"] = np.nan
    out = sbp.score_bond_plus(tiny)
    assert len(out) == 3
    assert not out["group_score_eligible"].any()
    assert out["composite_score"].isna().all()


if __name__ == "__main__":
    test_equity_center_band()
    test_target_dd_pass()
    test_equity_contrib_ratio()
    test_group_scoring()
    test_small_and_ungrouped_are_retained()
    print("scoring_bond_plus tests passed")
