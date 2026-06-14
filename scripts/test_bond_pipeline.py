"""债基固收线端到端合成测试(无网络): classify_bond -> 指标 -> screening_bond -> score_all(BOND)
验证四个独立模块 + 评分引擎能串成一条流水线并产出合理结果。
运行: python test_bond_pipeline.py
"""
import numpy as np
import pandas as pd

import campisi
import classify_bond
import config
import metrics_bond
import scoring
import screening_bond


def make_nav(days=1300, drift=0.0003, vol=0.0015, seed=0, crash_at=None, crash_size=0.06):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-05-29", periods=days)
    ret = rng.normal(drift, vol, days)
    if crash_at is not None:
        ret[crash_at] = -crash_size
    return pd.Series((1 + pd.Series(ret, index=dates)).cumprod(), index=dates)


def synth_factors(seed=99):
    rng = np.random.default_rng(seed)
    widx = pd.bdate_range(end="2026-05-29", periods=260, freq="W-FRI")
    return pd.DataFrame(
        {f: rng.normal(0, 0.003, len(widx)) for f in
         ["level", "slope", "credit", "default", "convertible"]}, index=widx)


def test_classify_bond():
    print("== 债基 L0 分类 ==")
    df = pd.DataFrame({
        "fund_code": [f"{i:06d}" for i in range(1, 7)],
        "fund_name": ["易方达信用债A", "南方中短债C", "广发可转债",
                      "博时信用债纯债", "天弘永利债券", "招商产业债摊余"],
        "fund_type": ["债券型-长债", "债券型-中短债", "债券型-混合二级",
                      "债券型-长债", "债券型-混合一级", "债券型-中短债"],
    })
    out = classify_bond.classify_bond(df)
    assert out.loc[0, "bond_subgroup"] == "中长期纯债"
    assert out.loc[1, "bond_subgroup"] == "短期纯债"
    assert out.loc[2, "bond_subgroup"] == "可转债基金"  # 名称含"可转债"优先
    assert "信用债型" in out.loc[0, "bond_strategy_tags"]
    assert "摊余成本法" in out.loc[5, "bond_strategy_tags"]
    print("  子组/策略标签/置信度 ✓")


def test_screening_bond():
    print("== 债基 L1 初筛 ==")
    df = pd.DataFrame([
        {"fund_code": "B1", "scale_yi": 10.0, "fund_age_years": 5.0, "leverage_ratio": 1.2},
        {"fund_code": "B2", "scale_yi": 0.3, "fund_age_years": 5.0, "leverage_ratio": 1.2},  # FN1
        {"fund_code": "B3", "scale_yi": 10.0, "fund_age_years": 0.5, "leverage_ratio": 1.2},  # FN2
        {"fund_code": "B4", "scale_yi": 10.0, "fund_age_years": 5.0, "leverage_ratio": 1.6},  # FN4
    ])
    out = screening_bond.apply_screening_bond(df)
    ch = dict(zip(out["fund_code"], out["channel"]))
    assert ch["B1"] == "standard" and ch["B2"] == "excluded"
    assert ch["B3"] == "excluded" and ch["B4"] == "excluded"
    print(f"  FN1/FN2/FN4 触发 ✓; 缺列规则自动跳过({len(out.attrs['screening_warnings'])} 条 warning)")


def test_end_to_end():
    print("== 债基流水线端到端(分类→指标→初筛→评分) ==")
    factors = synth_factors()
    rng = np.random.default_rng(7)
    rows = []
    n_per = 14
    specs = [("债券型-长债", "中长期纯债"), ("债券型-中短债", "短期纯债")]
    k = 0
    for ftype, _ in specs:
        for j in range(n_per):
            crash = 600 if j == 0 else None  # 每组1只埋崩盘 -> B维应垫底
            nav = make_nav(seed=k, drift=rng.normal(0.0003, 0.0001),
                           vol=rng.uniform(0.001, 0.003), crash_at=crash)
            m = metrics_bond.compute_bond_metrics(nav, factors)
            m["fund_code"] = f"{k+1:06d}"
            m["fund_name"] = f"测试债基{k}"
            m["fund_type"] = ftype
            m["scale_yi"] = float(rng.uniform(3, 80))
            m["fund_age_years"] = float(rng.uniform(2, 8))
            m["manager_experience"] = float(rng.uniform(2, 12))   # D1
            m["management_load"] = float(rng.uniform(20, 400))     # D2
            m["total_fee"] = float(rng.uniform(0.003, 0.008))      # E1
            rows.append(m)
            k += 1
    df = pd.DataFrame(rows)

    df = classify_bond.classify_bond(df)
    df = screening_bond.apply_screening_bond(df)
    standard = df[df["channel"] == "standard"].copy()

    parts = []
    for g, gdf in standard.groupby("bond_subgroup"):
        if len(gdf) < 5:
            continue
        parts.append(scoring.score_all(
            gdf, dim_weights=config.BOND_DIM_WEIGHTS,
            indicators=config.BOND_INDICATORS,
            veto_dim="B_risk", primary_dim="A_return"))
    scored = pd.concat(parts, ignore_index=True)

    # 1) 综合分合法
    assert scored["composite_score"].between(0, 100).all()
    # 2) 覆盖率: C1(净值法择券)使 C 维生效 -> A+B+C+D+E -> 1.0 -> formal
    cov = scored["weight_coverage"].iloc[0]
    assert abs(cov - 1.0) < 1e-9, cov
    assert (scored["covered_dims"] == "ABCDE").all(), scored["covered_dims"].unique()
    assert (scored["score_label"] == "formal").all(), "全五维应 formal"
    # 3) C 维由净值法 Campisi 残差(C1 选股占比)算出, 无需持仓
    assert scored["score_C_attribution"].notna().any()
    assert scored["selection_share_bond"].notna().any()
    # 4) 崩盘组 B 维显著低于均值
    crash_codes = [f"{i+1:06d}" for i in (0, n_per)]
    crash_in = scored[scored["fund_code"].isin(crash_codes)]
    diff = scored["score_B_risk"].mean() - crash_in["score_B_risk"].mean()
    assert diff > 0, "崩盘基金 B 维未低于均值"
    # 5) Campisi alpha 已落表
    assert scored["campisi_alpha"].notna().any()
    print(f"  评分 {len(scored)} 只 | 覆盖率 {cov:.0%}(ABCDE)→formal ✓")
    print(f"  崩盘组 B 维低于均值 {diff:.1f} 分 ✓ | 重点池 {scored['focus_pool'].sum()} 只")
    print(f"  综合分范围 [{scored['composite_score'].min():.1f}, {scored['composite_score'].max():.1f}]")
    cols = ["fund_code", "composite_score", "score_A_return", "score_B_risk",
            "score_D_manager", "campisi_alpha"]
    print(scored.sort_values("composite_score", ascending=False).head(5)[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    test_classify_bond()
    test_screening_bond()
    test_end_to_end()
    print("\n债基固收线端到端测试全部通过 ✅")
