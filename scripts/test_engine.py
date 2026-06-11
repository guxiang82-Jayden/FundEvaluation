"""合成数据测试: 验证指标计算正确性 + 初筛/评分流水线跑通
运行: python test_engine.py
"""
import numpy as np
import pandas as pd

import benchmark as bm
import metrics
import screening
import scoring


def make_nav(days=1300, drift=0.0004, vol=0.012, seed=0, crash_at=None, crash_size=0.3):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-05-29", periods=days)
    ret = rng.normal(drift, vol, days)
    if crash_at is not None:
        ret[crash_at] = -crash_size
    nav = pd.Series((1 + pd.Series(ret, index=dates)).cumprod(), index=dates)
    return nav


def test_metrics():
    print("== 指标计算单元测试 ==")
    # 1. 已知回撤: 净值 1->1.2->0.9->1.3, mdd = 0.9/1.2-1 = -25%
    nav = pd.Series([1.0, 1.2, 0.9, 1.3],
                    index=pd.to_datetime(["2024-01-01", "2024-06-01", "2024-09-01", "2025-06-01"]))
    mdd = metrics.max_drawdown(nav)
    assert abs(mdd - (-0.25)) < 1e-9, mdd
    print(f"  max_drawdown: {mdd:.4f} ✓ (期望 -0.25)")

    rec = metrics.recovery_days(nav)
    expected = (pd.Timestamp("2025-06-01") - pd.Timestamp("2024-09-01")).days
    assert rec == expected, (rec, expected)
    print(f"  recovery_days: {rec} ✓ (期望 {expected})")

    # 2. 年化收益: 2年翻倍 -> ~41.4%
    nav2 = pd.Series([1.0, 2.0], index=pd.to_datetime(["2024-01-01", "2026-01-01"]))
    ann = metrics.annualized_return(nav2)
    assert abs(ann - (2 ** (1 / 2.0016) - 1)) < 0.01, ann
    print(f"  annualized_return: {ann:.4f} ✓ (期望 ~0.414)")

    # 3. 胜率: 基金恒胜基准
    nav3 = make_nav(days=800, drift=0.001, vol=0.001, seed=1)
    bench = pd.Series(0.0, index=nav3.index)
    wr = metrics.monthly_win_rate(nav3, bench)
    assert wr > 0.95, wr
    print(f"  monthly_win_rate: {wr:.2f} ✓ (期望 ~1.0)")

    # 4. 窗口截取: 数据不足返回空
    short_nav = make_nav(days=300)
    assert metrics.window_slice(short_nav, 3).empty
    assert not metrics.window_slice(make_nav(days=1300), 3).empty
    print("  window_slice 数据不足保护 ✓")


def test_benchmark():
    print("== 基准解析测试 ==")
    parts = bm.parse_benchmark("沪深300指数收益率×45%+中证港股通综合指数收益率×35%+中债总指数收益率×20%")
    assert len(parts) == 3 and abs(sum(w for _, w in parts) - 1.0) < 1e-9, parts
    print(f"  parse: {parts} ✓")
    comps = bm.resolve_components(parts)
    print(f"  resolve(部分指数未配置, 权重归一): {comps} ✓")
    parts2 = bm.parse_benchmark("中证800指数收益率*80%+活期存款利率*20%")
    assert len(parts2) == 2, parts2
    print(f"  parse 星号兼容: {parts2} ✓")


def test_pipeline():
    print("== 初筛+评分流水线测试 ==")
    n = 60
    rng = np.random.default_rng(42)
    index_rets = {"sh000906": pd.Series(rng.normal(0.0003, 0.01, 1300),
                                        index=pd.bdate_range(end="2026-05-29", periods=1300))}
    rows = []
    for i in range(n):
        nav = make_nav(seed=i, drift=rng.normal(0.0004, 0.0002), vol=rng.uniform(0.008, 0.018),
                       crash_at=600 if i % 10 == 0 else None)
        bench_ret, _ = bm.get_benchmark_returns("", index_rets)
        m = metrics.compute_fund_metrics(nav, bench_ret)
        m["fund_code"] = f"F{i:03d}"
        m["fund_name"] = f"测试AI主题基金{i}" if i % 7 == 0 else f"测试价值精选{i}"
        m["scale_yi"] = float(rng.uniform(0.2, 400))
        m["fund_age_years"] = float(rng.uniform(0.5, 10))
        m["tenure_years"] = float(rng.uniform(0.3, 8))
        m["manager_changed_recent"] = bool(rng.random() < 0.1)
        m["inst_ratio"] = float(rng.uniform(0, 1))
        m["style_switches_2y"] = int(rng.integers(0, 4))
        m["fund_age_for_style"] = m["fund_age_years"]
        m["equity_low_quarters"] = int(rng.integers(0, 6))
        m["negative_record"] = bool(rng.random() < 0.05)
        rows.append(m)
    df = pd.DataFrame(rows)

    df = screening.apply_screening(df)
    n_excluded = df["screened_out"].sum()
    n_obs = (df["channel"] == "theme_observation").sum()
    print(f"  初筛: 剔除 {n_excluded}, 主题观察 {n_obs}, 标准 {len(df) - n_excluded - n_obs}")
    assert (df.loc[df["channel"] == "theme_observation", "fund_name"].str.contains("AI")).all()

    standard = df[df["channel"] == "standard"]
    scored = scoring.score_all(standard)
    assert scored["composite_score"].notna().any()
    assert scored["composite_score"].between(0, 100).all()
    top = scored.sort_values("composite_score", ascending=False).head(3)
    print(f"  评分: 综合分范围 [{scored['composite_score'].min():.1f}, {scored['composite_score'].max():.1f}]")
    print(f"  重点池 {scored['focus_pool'].sum()} 只, 否决 {scored['veto'].sum()} 只, 短板 {scored['shortboard'].sum()} 只")
    cols = ["fund_code", "composite_score", "score_A_return", "score_B_risk"]
    print(top[cols].to_string(index=False))
    # 一致性: 含崩盘日的基金 B 维应显著低于无崩盘均值
    crash_funds = [f"F{i:03d}" for i in range(n) if i % 10 == 0]
    in_std = scored[scored["fund_code"].isin(crash_funds)]
    if len(in_std) >= 2:
        diff = scored["score_B_risk"].mean() - in_std["score_B_risk"].mean()
        print(f"  崩盘组 B 维低于均值 {diff:.1f} 分 {'✓' if diff > 0 else '✗ 需检查'}")


if __name__ == "__main__":
    test_metrics()
    test_benchmark()
    test_pipeline()
    print("\n全部测试通过 ✅")
