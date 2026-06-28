"""rbsa.py / backtest.py 合成数据测试
运行: python test_modules.py
"""
import numpy as np
import pandas as pd

import backtest
import rbsa


def make_style_basis(days=1500, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-05-29", periods=days)
    return pd.DataFrame({
        "large_value": rng.normal(0.0003, 0.009, days),
        "large_growth": rng.normal(0.0004, 0.013, days),
        "small_value": rng.normal(0.0003, 0.011, days),
        "small_growth": rng.normal(0.0005, 0.016, days),
    }, index=dates)


def test_rbsa():
    print("== RBSA 测试 ==")
    styles = make_style_basis()
    rng = np.random.default_rng(1)

    # 1. 已知权重还原: 70%大盘成长+30%大盘价值
    true_w = np.array([0.3, 0.7, 0.0, 0.0])
    fund = pd.Series(styles.values @ true_w + rng.normal(0, 0.001, len(styles)), index=styles.index)
    r = rbsa.rbsa(fund, styles)
    est = r["weights"].values
    err = np.abs(est - true_w).max()
    assert err < 0.05, (est, true_w)
    print(f"  权重还原误差 {err:.3f} [OK] (估计: {dict(r['weights'].round(2))}, R^2={r['r2']:.3f})")
    assert r["r2"] > 0.95

    # 2. 稳定风格 -> 高稳定度, 0切换
    roll = rbsa.rolling_rbsa(fund, styles)
    st = rbsa.style_stability(roll)
    print(f"  稳定基金: stability={st['stability']:.2f}, switches_2y={st['switches_2y']}")
    assert st["stability"] > 0.7 and st["switches_2y"] <= 1

    # 3. 漂移基金: 前半段小盘成长, 后半段大盘价值
    half = len(styles) // 2
    drift_ret = np.concatenate([
        styles["small_growth"].values[:half],
        styles["large_value"].values[half:],
    ]) + rng.normal(0, 0.001, len(styles))
    drift_fund = pd.Series(drift_ret, index=styles.index)
    roll_d = rbsa.rolling_rbsa(drift_fund, styles)
    st_d = rbsa.style_stability(roll_d)
    print(f"  漂移基金: stability={st_d['stability']:.2f}, switches_2y={st_d['switches_2y']}")
    assert st_d["stability"] < st["stability"]
    # 标签验证
    lbl = rbsa.style_label(r["weights"])
    assert lbl == "large_growth", lbl
    print(f"  风格标签: {lbl} [OK]")


def test_backtest():
    print("== 回测模块测试 ==")
    rng = np.random.default_rng(9)
    dates = pd.bdate_range(end="2026-05-29", periods=2000)
    bench = pd.Series(rng.normal(0.0003, 0.01, len(dates)), index=dates)

    # 构造 30 只基金: 一半"真有技能"(漂移高且持续), 一半平庸
    navs = {}
    skills = {}
    for i in range(30):
        skilled = i < 15
        drift = 0.0007 if skilled else 0.0002
        ret = bench.values + rng.normal(drift - 0.0003, 0.006, len(dates))
        navs[f"F{i:03d}"] = pd.Series((1 + pd.Series(ret, index=dates)).cumprod(), index=dates)
        skills[f"F{i:03d}"] = skilled

    res = backtest.backtest_multi_period(
        navs, bench, asof_list=["2024-05-31", "2024-11-30", "2025-05-31"], top_pct=0.3)
    print(res[["asof", "n_universe", "top_fwd_return", "universe_fwd_return", "excess", "rank_ic"]]
          .to_string(index=False))
    # 技能持续的世界里, 评分应能选出技能组 -> 平均超额>0, IC>0
    assert res["excess"].mean() > 0, "回测未能识别持续技能(检查评分或窗口)"
    assert res["rank_ic"].mean() > 0.1
    print(f"  平均超额 {res['excess'].mean():.2%} > 0 [OK], RankIC {res['rank_ic'].mean():.2f} [OK]")


if __name__ == "__main__":
    test_rbsa()
    test_backtest()
    print("\n模块测试全部通过 [OK]")
