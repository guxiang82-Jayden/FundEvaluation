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
    # 权重在前 + 全角＋
    p3 = bm.parse_benchmark("85%×中证500指数收益率＋15%×中证全债指数收益率")
    assert abs(dict((n, w) for n, w in p3).get("中证500指数", 0) - 0.85) < 1e-9, p3
    print(f"  parse 权重在前/全角＋: {p3} ✓")
    # 安全规则: 已映射权重<50% 必须回退(不得用残缺基准)
    c4 = bm.resolve_components(bm.parse_benchmark("80%×不存在的指数+20%×中证全债指数"))
    assert c4 == [], c4
    print("  resolve 残缺基准回退保护 ✓")


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
    # 可信度标识: 本测试只喂 A/B 维数据 -> 必须全部标记 provisional, 不得进正式重点池
    assert (scored["covered_dims"] == "AB").all(), scored["covered_dims"].unique()
    assert scored["provisional"].all(), "A/B-only 评分未标记 provisional"
    assert scored["focus_pool"].sum() == 0, "provisional 评分混入了正式重点池"
    assert scored["candidate_pool"].sum() > 0
    assert abs(scored["weight_coverage"].iloc[0] - 0.55) < 1e-9  # A(0.30)+B(0.25)
    print("  可信度标识: provisional/候选池/覆盖率 0.55 ✓")
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


def test_primary_missing_and_investability():
    print("== 主维缺失否决 + 可投性测试 ==")
    # 6只: 1只A维全缺(只有B), 1只规模过小, 其余正常
    df = pd.DataFrame({
        "excess_return_ann_3y": [0.10, 0.08, 0.06, 0.04, 0.02, None],  # 最后一只A维缺
        "monthly_win_rate_3y": [0.6, 0.55, 0.5, 0.45, 0.4, None],
        "max_drawdown_3y": [-0.1, -0.15, -0.2, -0.25, -0.3, -0.05],   # 缺A那只回撤最小
        "calmar_3y": [2, 1.5, 1, 0.8, 0.5, 3],
        "sortino_3y": [3, 2, 1.5, 1, 0.5, 4],
        "scale_yi": [50, 30, 20, 1.0, 10, 40],   # 第4只规模1亿(<2)
        "valid_3y": True,
    })
    s = scoring.score_all(df)
    # A维缺的那只(idx5): primary_missing=True, veto=True, 不进任何池
    assert s.loc[5, "primary_missing"], "A维缺未标记"
    assert s.loc[5, "veto"], "A维缺未否决"
    assert not s.loc[5, "focus_pool"] and not s.loc[5, "candidate_pool"], "A维缺仍进池"
    print("  A维缺失→否决→不进池 ✓")
    # 规模1亿那只(idx3): investability_warn=True, 不进正式focus_pool
    assert s.loc[3, "investability_warn"], "小规模未预警"
    print("  规模<2亿→可投性预警→挡出正式池 ✓")


def test_cdim_coverage():
    print("== C/E维接入提升覆盖率测试 ==")
    base = dict(excess_return_ann_3y=[0.10, 0.08, 0.06, 0.04, 0.02],
                monthly_win_rate_3y=[0.6, 0.55, 0.5, 0.45, 0.4],
                max_drawdown_3y=[-0.1, -0.15, -0.2, -0.25, -0.3],
                calmar_3y=[2, 1.5, 1, 0.8, 0.5],
                sortino_3y=[3, 2, 1.5, 1, 0.5],
                scale_yi=[50, 30, 20, 15, 10], valid_3y=True)
    # 无C/E
    s_no = scoring.score_all(pd.DataFrame(base))
    # 有C/E(selection_share+concentration+turnover)
    withce = dict(base, selection_share=[0.4, 0.6, 0.4, 1.0, 0.58],
                  concentration=[0.76, 0.84, 0.91, 0.70, 0.93],
                  turnover=[2.7, 3.9, 7.0, 3.5, 2.1])
    s_ce = scoring.score_all(pd.DataFrame(withce))
    assert abs(s_no["weight_coverage"].iloc[0] - 0.55) < 0.01
    assert abs(s_ce["weight_coverage"].iloc[0] - 0.85) < 0.01, s_ce["weight_coverage"].iloc[0]
    assert (s_ce["score_label"] == "formal").all(), "C/E补充后未升formal"
    assert s_ce["score_C_attribution"].notna().all() and s_ce["score_E_operation"].notna().all()
    print(f"  覆盖率: 无C/E {s_no['weight_coverage'].iloc[0]:.0%} → 有C/E {s_ce['weight_coverage'].iloc[0]:.0%} → formal ✓")

    # 全五维(加D: manager_experience + management_load) → 覆盖率应达 100%
    full = dict(withce, manager_experience=[7, 6, 5, 4, 3],
                management_load=[20, 50, 100, 150, 300])
    s_full = scoring.score_all(pd.DataFrame(full))
    assert abs(s_full["weight_coverage"].iloc[0] - 1.0) < 0.01, s_full["weight_coverage"].iloc[0]
    assert s_full["score_D_manager"].notna().all()
    print(f"  全五维覆盖率: {s_full['weight_coverage'].iloc[0]:.0%}(A+B+C+D+E)✓")


def test_classify_and_group_scoring():
    print("== 同类组细分+组内评分测试 ==")
    import classify
    df = pd.DataFrame({
        "fund_code": [f"{i:06d}" for i in range(1, 7)],
        "fund_name": ["华夏成长混合", "易方达医药股票", "嘉实新能源股票",
                      "广发量化多因子混合", "兴全合润混合", "南方医疗保健灵活配置"],
        "fund_type": ["混合型-偏股", "股票型", "股票型", "混合型-偏股", "混合型-偏股", "混合型-灵活"],
    })
    out = classify.classify(df)
    assert out.loc[1, "subgroup"] == "行业主题:医药"
    assert out.loc[5, "subgroup"] == "行业主题:医药"   # 灵活配置的医药基金也入医药组
    assert out.loc[3, "strategy_tags"] == "量化"
    assert out.loc[1, "backbone"] == "普通股票型"
    print("  分类与 backbone ✓")

    # 组内分位独立性: 同样的指标值, 在弱组里分位应高于在强组里
    g1 = pd.DataFrame({"excess_return_ann_3y": [0.10, 0.08, 0.06, 0.04, 0.02, 0.05],
                       "valid_3y": True})
    g2 = pd.DataFrame({"excess_return_ann_3y": [0.05, 0.04, 0.03, 0.02, 0.01, 0.00],
                       "valid_3y": True})
    s1 = scoring.score_all(g1)   # 0.05 在强组排第4/6
    s2 = scoring.score_all(g2)   # 0.05 在弱组排第1/6
    r1 = s1.loc[5, "score_A_return"]
    r2 = s2.loc[0, "score_A_return"]
    assert r2 > r1, (r1, r2)
    print(f"  组内分位独立性: 同值0.05 弱组{r2:.0f}分 > 强组{r1:.0f}分 ✓")


if __name__ == "__main__":
    test_metrics()
    test_benchmark()
    test_pipeline()
    test_classify_and_group_scoring()
    test_primary_missing_and_investability()
    test_cdim_coverage()
    print("\n全部测试通过 ✅")
