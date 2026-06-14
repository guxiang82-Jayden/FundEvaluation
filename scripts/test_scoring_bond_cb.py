"""可转债 CB 专用记分卡测试(合成, 无网络)。"""
import numpy as np
import pandas as pd

import scoring_bond_cb as cb


def _synth(n=8, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-05-29", periods=800)
    eq = pd.Series(rng.normal(0.0003, 0.012, 800), index=idx)
    navs, rows, true_beta = {}, [], {}
    for i in range(n):
        beta = 0.2 + i * 0.08
        r = beta * eq.values + rng.normal(0.0002, 0.004, 800)
        navs[f"{i:06d}"] = pd.Series((1 + pd.Series(r, index=idx)).cumprod(), index=idx)
        true_beta[f"{i:06d}"] = beta
        rows.append({"fund_code": f"{i:06d}", "bond_subgroup": "可转债基金",
                     "ann_return_3y": rng.uniform(0, 0.15), "monthly_positive_ratio_3y": rng.uniform(0.4, 0.8),
                     "max_drawdown_3y": -rng.uniform(0.05, 0.3), "calmar_3y": rng.uniform(0.2, 2),
                     "sortino_3y": rng.uniform(0.2, 2), "recovery_days_3y": int(rng.integers(20, 300)),
                     "convertible_ratio": rng.uniform(0.5, 1.0), "manager_experience": rng.uniform(2, 12),
                     "management_load": rng.uniform(20, 300), "total_fee": rng.uniform(0.004, 0.009),
                     "scale_yi": rng.uniform(5, 50), "valid_3y": True})
    return pd.DataFrame(rows), navs, eq, true_beta


def test_equity_beta_recovery():
    print("== equity_beta 还原 ==")
    _, navs, eq, tb = _synth()
    for code, beta in tb.items():
        est = cb.equity_beta(navs[code], eq)
        assert abs(est - beta) < 0.08, (code, est, beta)
    print("  8 只 beta 估计与真值偏差<0.08 ✓")


def test_score_cb():
    print("== score_cb 组内评分 ==")
    df, navs, eq, _ = _synth()
    df = cb.build_cb_metrics(df, navs, eq)
    assert df["equity_beta"].notna().all()
    scored = cb.score_cb(df)
    assert not scored.empty and (scored["scorecard"] == "CB").all()
    assert scored["composite_score"].between(0, 100).all()
    assert "score_C_attribution" in scored and scored["score_C_attribution"].notna().any()
    print(f"  {len(scored)}只 scorecard=CB, 综合分∈[0,100], C维(beta/转债仓位)生效 ✓")


def test_defer_small_group():
    print("== 小组(<5)defer ==")
    df, navs, eq, _ = _synth(n=3)
    df = cb.build_cb_metrics(df, navs, eq)
    assert cb.score_cb(df).empty, "可转债<5只应 defer"
    print("  3只<5 → defer(空) ✓")


if __name__ == "__main__":
    test_equity_beta_recovery()
    test_score_cb()
    test_defer_small_group()
    print("\n可转债 CB 记分卡测试全部通过 ✅")
