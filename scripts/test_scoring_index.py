"""权益指数/ETF 工具型评价卡离线测试。"""
import numpy as np
import pandas as pd

import data_index_equity as die
import run_monthly_index as runner
import scoring_index as si


def _index_rows(n=6):
    return pd.DataFrame({
        "fund_code": [f"I{i:03d}" for i in range(n)],
        "fund_name": [f"沪深300指数{i}" for i in range(n)],
        "index_family": "沪深300",
        "tracking_error": np.linspace(0.002, 0.02, n),
        "info_ratio": np.linspace(0.0, -0.5, n),
        "total_fee": np.linspace(0.002, 0.01, n),
        "scale_yi": [1, 3, 8, 20, 50, 100][:n],
        "index_mainstream": 1.0,
        "fund_age_years": np.linspace(2, 10, n),
    })


def _etf_rows(n=6):
    return pd.DataFrame({
        "fund_code": [f"E{i:03d}" for i in range(n)],
        "fund_name": [f"沪深300ETF{i}" for i in range(n)],
        "index_family": "沪深300",
        "tracking_error": np.linspace(0.001, 0.015, n),
        "tracking_deviation": np.linspace(0.001, 0.01, n),
        "total_fee": np.linspace(0.002, 0.008, n),
        "amount_avg": np.linspace(1e9, 1e7, n),
        "turnover_amt": np.linspace(8, 1, n),
        "bid_ask_spread": np.linspace(0.0001, 0.005, n),
        "premium_discount_abs": np.linspace(0.0002, 0.01, n),
        "premium_discount_std": np.linspace(0.0002, 0.008, n),
        "scale_yi": [100, 50, 20, 8, 3, 1][:n],
        "fund_age_years": np.linspace(10, 2, n),
    })


def test_index_direction_and_provisional():
    scored, deferred = si.score_index_equity(_index_rows())
    assert deferred.empty and len(scored) == 6
    best = scored.loc[scored["tracking_error"].idxmin()]
    worst = scored.loc[scored["tracking_error"].idxmax()]
    assert best["score_A_return"] > worst["score_A_return"]
    missing = _index_rows()
    missing["tracking_error"] = np.nan
    degraded, _ = si.score_index_equity(missing)
    assert degraded["score_label"].str.startswith("provisional").all()


def test_etf_liquidity_premium_and_micro_warning():
    scored, deferred = si.score_etf(_etf_rows())
    assert deferred.empty and len(scored) == 6
    good = scored.iloc[0]
    bad = scored.iloc[-1]
    assert good["score_C_attribution"] > bad["score_C_attribution"]
    assert good["score_D_manager"] > bad["score_D_manager"]
    micro = scored.loc[scored["scale_yi"].idxmin()]
    assert bool(micro["investability_warn"]) is True


def test_small_group_deferred_and_te_gate():
    scored, deferred = si.score_etf(_etf_rows(4))
    assert scored.empty and len(deferred) == 4
    data = _etf_rows()
    data.loc[0, "tracking_error"] = 0.09
    gated, withdrawn = runner.apply_te_gate(data, "ETF")
    assert len(withdrawn) == 1
    assert pd.isna(gated.loc[0, "tracking_error"])


def test_tracking_stats():
    rng = np.random.default_rng(39)
    dates = pd.bdate_range("2024-01-01", periods=300)
    index_ret = pd.Series(rng.normal(0.0003, 0.01, len(dates)), index=dates)
    nav = (1 + index_ret + rng.normal(0, 0.0001, len(dates))).cumprod()
    stats = si.tracking_stats(nav, index_ret)
    assert stats["tracking_error"] < 0.01
    assert stats["tracking_days"] >= 250


def test_mapping_does_not_guess_index_variants():
    assert die.parse_index_name("华泰柏瑞沪深300ETF")["index_code"] == "sh000300"
    for name in ("沪深300成长ETF", "沪深300增强ETF", "沪深300安中指数"):
        assert pd.isna(die.parse_index_name(name)["index_code"])


if __name__ == "__main__":
    test_index_direction_and_provisional()
    test_etf_liquidity_premium_and_micro_warning()
    test_small_group_deferred_and_te_gate()
    test_tracking_stats()
    test_mapping_does_not_guess_index_variants()
    print("INDEX/ETF scoring tests passed [OK]")
