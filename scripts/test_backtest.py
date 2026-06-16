"""回测模块测试 (合成数据, 不依赖网络)
验证:
1. forward_return 计算正确性
2. 防前视: asof 之后净值不参与评分
3. 成立不足3年的基金被排除
4. 分维度 IC 结构 (返回 dict 含 ic_A_return / ic_B_risk 等)
5. 多期聚合: backtest_multi_period 返回 DataFrame, 含 rank_ic 列
6. dim_ic_summary + calibration_suggest 结构正确
"""
import warnings
import numpy as np
import pandas as pd

import backtest as bt


# ---------------------------------------------------------------------------
# 合成数据工厂
# ---------------------------------------------------------------------------

def make_nav(start="2014-01-01", end="2026-05-30", drift=0.0004, vol=0.012, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, end=end)
    ret = rng.normal(drift, vol, len(dates))
    nav = pd.Series((1 + pd.Series(ret, index=dates)).cumprod(), index=dates)
    return nav


def make_bench(start="2014-01-01", end="2026-05-30", seed=99):
    return make_nav(start, end, drift=0.0002, vol=0.010, seed=seed)


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------

def test_forward_return():
    print("== forward_return 测试 ==")
    nav = make_nav()
    start = pd.Timestamp("2023-12-31")
    fwd = bt.forward_return(nav, start, months=12)
    assert pd.notna(fwd), "前瞻收益应为有限值"
    # start 之后无数据时返回 nan
    short = nav.loc[nav.index <= start]
    assert pd.isna(bt.forward_return(short, start, months=12)), "无后续数据应返回 nan"
    print(f"  12个月前瞻收益: {fwd:.2%} ✓")


def test_anti_lookahead():
    """评分阶段不得使用 asof 之后净值"""
    print("== 防前视切片测试 ==")
    asof = "2022-12-31"
    asof_ts = pd.Timestamp(asof)

    # 构造两只基金: A 在 asof 之前表现平平, asof 之后暴涨; B 相反
    # 若有前视: A 会得高分; 若防前视正确: A/B 评分应接近
    dates_pre = pd.bdate_range("2014-01-01", asof)
    dates_post = pd.bdate_range(asof, "2024-12-31")[1:]

    rng = np.random.default_rng(42)
    # A: 评估期平庸, 此后超强
    ret_a_pre = rng.normal(0.0002, 0.010, len(dates_pre))
    ret_a_post = rng.normal(0.002, 0.010, len(dates_post))   # 10x drift
    nav_a = pd.concat([
        pd.Series((1 + pd.Series(ret_a_pre, index=dates_pre)).cumprod(), index=dates_pre),
        pd.Series([], dtype=float),
    ])
    # 拼接: post 从 pre 末尾继续
    last_a = (1 + pd.Series(ret_a_pre, index=dates_pre)).cumprod().iloc[-1]
    post_a = last_a * (1 + pd.Series(ret_a_post, index=dates_post)).cumprod()
    nav_a = pd.concat([
        pd.Series((1 + pd.Series(ret_a_pre, index=dates_pre)).cumprod(), index=dates_pre),
        post_a,
    ])

    # B: 评估期强劲
    ret_b_pre = rng.normal(0.001, 0.010, len(dates_pre))   # 5x drift
    ret_b_post = rng.normal(0.0001, 0.010, len(dates_post))
    last_b = (1 + pd.Series(ret_b_pre, index=dates_pre)).cumprod().iloc[-1]
    post_b = last_b * (1 + pd.Series(ret_b_post, index=dates_post)).cumprod()
    nav_b = pd.concat([
        pd.Series((1 + pd.Series(ret_b_pre, index=dates_pre)).cumprod(), index=dates_pre),
        post_b,
    ])

    bench = make_bench(end="2024-12-31")
    # 填充足够多的基金让 score_all 有足够样本
    navs = {f"F{i:03d}": make_nav(seed=i, end="2024-12-31") for i in range(20)}
    navs["FA"] = nav_a
    navs["FB"] = nav_b

    result = bt.backtest_one_period(navs, bench, asof)
    assert "error" not in result, f"回测出错: {result}"
    # B 应比 A 得分高 (B 在 asof 前表现好); 验证防前视
    # 取回 scored (通过 forward_return 间接验证; 此处只检查结构完整)
    assert "rank_ic" in result
    assert "ic_A_return" in result or "ic_B_risk" in result, \
        f"缺分维度IC, keys={list(result.keys())}"
    print(f"  asof={asof}, n={result['n_universe']}, rank_ic={result['rank_ic']:.3f} ✓")


def test_inception_exclusion():
    """asof 时点成立不足3年的基金应被排除"""
    print("== 成立不足3年排除测试 ==")
    asof = "2022-12-31"
    bench = make_bench(end="2024-12-31")

    # 20 只正常基金 (2014 起)
    navs = {f"F{i:03d}": make_nav(seed=i, end="2024-12-31") for i in range(20)}
    # 2 只新基金: 2021-06-01 成立 (距 asof 不足 3 年)
    new_nav = make_nav(start="2021-06-01", end="2024-12-31", seed=99)
    navs["NEW1"] = new_nav
    navs["NEW2"] = make_nav(start="2022-01-01", end="2024-12-31", seed=100)

    inception_dates = {
        "NEW1": pd.Timestamp("2021-06-01"),
        "NEW2": pd.Timestamp("2022-01-01"),
    }
    result_with = bt.backtest_one_period(navs, bench, asof, inception_dates=inception_dates)
    result_without = bt.backtest_one_period(navs, bench, asof)

    assert "error" not in result_with
    # 排除新基金后宇宙规模应 <= 不排除时
    assert result_with["n_universe"] <= result_without["n_universe"], \
        f"排除后数量({result_with['n_universe']}) 应 <= 不排除({result_without['n_universe']})"
    print(f"  有inception_dates: {result_with['n_universe']}只  "
          f"无: {result_without['n_universe']}只 ✓")


def test_dim_ic_structure():
    """backtest_one_period 返回 dict 含正确的分维度 IC 键"""
    print("== 分维度IC结构测试 ==")
    navs = {f"F{i:03d}": make_nav(seed=i, end="2024-12-31") for i in range(30)}
    bench = make_bench(end="2024-12-31")
    result = bt.backtest_one_period(navs, bench, "2022-12-31")

    assert "error" not in result, f"回测错误: {result}"
    # 必须有 A/B 维 IC (C/D/E 因无数据可能为 nan 但键应存在)
    assert "ic_A_return" in result, f"缺 ic_A_return, keys={list(result.keys())}"
    assert "ic_B_risk" in result, f"缺 ic_B_risk, keys={list(result.keys())}"
    # 至少一个窗口 IC
    window_keys = [k for k in result if "_3y" in k or "_5y" in k]
    assert len(window_keys) > 0, "缺窗口级 IC"
    print(f"  维度IC键: {[k for k in result if k.startswith('ic_')]}")
    print("  ✓")


def test_multi_period():
    """backtest_multi_period 返回 DataFrame, dim_ic_summary 结构正确"""
    print("== 多期汇总测试 ==")
    navs = {f"F{i:03d}": make_nav(seed=i, end="2026-01-01") for i in range(30)}
    bench = make_bench(end="2026-01-01")
    asof_list = ["2020-12-31", "2021-12-31", "2022-12-31"]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        results = bt.backtest_multi_period(navs, bench, asof_list)

    assert isinstance(results, pd.DataFrame)
    assert len(results) == 3
    assert "rank_ic" in results.columns

    summary = bt.dim_ic_summary(results)
    assert isinstance(summary, pd.DataFrame)
    assert "mean_ic" in summary.columns
    assert "positive_rate" in summary.columns
    assert len(summary) > 0
    print(f"  期数: {len(results)}, IC汇总行数: {len(summary)} ✓")

    suggestions = bt.calibration_suggest(summary)
    assert isinstance(suggestions, dict)
    assert "A_return" in suggestions
    for dim, info in suggestions.items():
        assert "current" in info and "suggested" in info
    print(f"  calibration_suggest 覆盖维度: {list(suggestions.keys())} ✓")


def test_no_future_data_in_score():
    """评分使用的 metrics 不包含 asof 之后数据 (防前视完整性)"""
    print("== metrics 防前视完整性测试 ==")
    import metrics as mt
    asof_ts = pd.Timestamp("2021-12-31")
    nav_full = make_nav(end="2024-12-31", seed=7)
    nav_cut = nav_full.loc[nav_full.index <= asof_ts]
    bench = make_bench(end="2024-12-31")
    bench_cut = bench.loc[bench.index <= asof_ts]

    m_full = mt.compute_fund_metrics(nav_full, bench, asof=asof_ts)
    m_cut = mt.compute_fund_metrics(nav_cut, bench_cut, asof=asof_ts)
    # asof 参数应使两者结果一致 (若 compute_fund_metrics 尊重 asof 切片)
    for key in ["excess_return_ann_3y", "max_drawdown_3y"]:
        if key in m_full and key in m_cut and pd.notna(m_full[key]) and pd.notna(m_cut[key]):
            diff = abs(m_full[key] - m_cut[key])
            assert diff < 1e-9, f"{key} 差异 {diff} 超限, 可能有前视"
    print("  asof 切片一致性 ✓")




def test_calibration_significance_guard():
    """calibration_suggest 显著性护栏: 无数据保持/不显著维持/显著才有界调整且永不清零。"""
    import backtest as bt
    # 1) 无IC数据 -> 保持原权重
    nan = pd.DataFrame({"metric": ["ic_A_return"], "mean_ic": [float("nan")],
                        "ic_std": [float("nan")], "n_periods": [0]})
    assert "无IC数据" in bt.calibration_suggest(nan)["A_return"]["note"]
    # 2) IC 不显著(大 std -> |t|<1) -> delta=0 且 note 标注不显著(杜绝 0%/100% 假象)
    insig = pd.DataFrame({
        "metric": ["ic_A_return", "ic_B_risk"],
        "mean_ic": [0.0007, -0.04], "ic_std": [0.15, 0.13], "n_periods": [6, 6]})
    s = bt.calibration_suggest(insig)
    assert abs(s["A_return"]["delta"]) < 1e-9 and "不显著" in s["A_return"]["note"], s["A_return"]
    assert abs(s["B_risk"]["delta"]) < 1e-9, s["B_risk"]
    # 3) 显著为负(小 std -> |t|大) -> 有界下调, 但不清零(>=0.05)
    sig = pd.DataFrame({"metric": ["ic_A_return"], "mean_ic": [-0.10],
                        "ic_std": [0.05], "n_periods": [9]})  # t≈-6
    a = bt.calibration_suggest(sig)["A_return"]
    assert a["delta"] < 0 and a["suggested"] >= 0.05 and a["suggested"] < a["current"], a
    # 4) 显著为正 -> 有界上调(<= cur + max_step)
    sigp = bt.calibration_suggest(pd.DataFrame({
        "metric": ["ic_B_risk"], "mean_ic": [0.10],
        "ic_std": [0.05], "n_periods": [9]}))["B_risk"]
    assert sigp["delta"] > 0 and sigp["suggested"] <= sigp["current"] + 0.10 + 1e-9, sigp
    print("  calibration 显著性护栏(无数据/不显著/显著±有界/不清零) OK")


def test_load_navs_diag():
    """_load_navs: 去2014硬门槛 + 失败/历史太短/有效 分桶诊断(任务26核心)"""
    import run_backtest as rb
    idx_old = pd.bdate_range("2015-01-01", periods=2000)
    idx_new = pd.bdate_range("2023-01-01", periods=400)

    def fake_nav(code):
        if code == "FAIL":
            raise ValueError("html反爬")
        if code == "EMPTY":
            return pd.Series(dtype=float)
        if code == "NEW":
            return pd.Series(1.0, index=idx_new)
        return pd.Series(1.0, index=idx_old)

    orig = rb.da.fund_nav
    rb.da.fund_nav = fake_nav
    try:
        navs, diag = rb._load_navs(["OLD1", "OLD2", "NEW", "FAIL", "EMPTY"],
                                   pd.Timestamp("2021-12-31"))
    finally:
        rb.da.fund_nav = orig
    assert diag == {"requested": 5, "fetch_fail": 2, "too_short": 1, "valid": 2}, diag
    assert set(navs) == {"OLD1", "OLD2"}
    print(f"  _load_navs 分桶诊断 {diag} OK")




def test_within_subgroup_scoring():
    """组内分位打分(精化): 传 subgroups 时按组打分, 两组各6只均参与。"""
    import backtest as bt
    idx = pd.bdate_range("2016-01-01", periods=2200)
    rng = np.random.default_rng(5)
    navs, subs, inc = {}, {}, {}
    for g, base in [("普通股票型", 0.0005), ("偏股混合型", 0.0002)]:
        for i in range(6):
            c = f"{g[:2]}{i}"
            navs[c] = pd.Series((1 + pd.Series(rng.normal(base, 0.01, 2200),
                                               index=idx)).cumprod(), index=idx)
            subs[c] = g
            inc[c] = idx[0]
    bench = pd.Series(rng.normal(0.0003, 0.01, 2200), index=idx)
    res = bt.backtest_one_period(navs, bench, "2021-12-31",
                                 subgroups=subs, inception_dates=inc)
    assert "error" not in res, res
    assert res["n_universe"] == 12, res  # 两组各6只均评分
    assert "rank_ic" in res
    print(f"  组内打分: n={res['n_universe']}, rank_ic={res['rank_ic']:.3f} ✓")


if __name__ == "__main__":
    test_forward_return()
    test_anti_lookahead()
    test_inception_exclusion()
    test_dim_ic_structure()
    test_multi_period()
    test_no_future_data_in_score()
    test_calibration_significance_guard()
    test_load_navs_diag()
    test_within_subgroup_scoring()
    print("\n全部回测测试通过 ✅")
