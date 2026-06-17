"""BOND_INDEX 工具型记分卡测试(合成, 无网络)。"""
import numpy as np
import pandas as pd

import scoring_bond_index as bi


def _synth(n_each=6):
    rows = []
    for prefix, fund_type in (("D", "指数型-固收"), ("Q", "QDII-纯债")):
        for i in range(n_each):
            rows.append({
                "fund_code": f"{prefix}{i:03d}",
                "fund_type": fund_type,
                "total_fee": 0.002 + i * 0.001,
                "scale_yi": [1, 3, 8, 20, 50, 100][i % 6],
                "fund_age_years": 2 + i,
            })
    return pd.DataFrame(rows)


def test_split_and_phase_a_degrade():
    print("== BOND_INDEX Phase A 降级评分 ==")
    df = bi.build_index_metrics(_synth())
    assert set(df["index_subgroup"]) == {"指数固收", "QDII债"}
    assert df["tracking_error"].isna().all()
    scored = bi.score_index(df)
    assert not scored.empty
    assert (scored["scorecard"] == "BOND_INDEX").all()
    assert set(scored["index_subgroup"]) == {"指数固收", "QDII债"}
    assert scored["score_label"].str.startswith("provisional").all()
    assert scored["weight_coverage"].max() < 0.75
    assert not scored["veto"].any()
    print("  子组拆分正确, tracking缺失时按B/C/E降级并标provisional ✓")


def test_fee_and_scale_rank_within_group():
    print("== 成本/规模组内分位 ==")
    df = bi.build_index_metrics(_synth(n_each=6))
    scored = bi.score_index(df)
    dom = scored[scored["index_subgroup"] == "指数固收"].copy()
    cheap = dom.loc[dom["total_fee"].idxmin()]
    expensive = dom.loc[dom["total_fee"].idxmax()]
    assert cheap["score_B_risk"] > expensive["score_B_risk"]
    mid_scale = dom.loc[dom["scale_yi"].eq(50)].iloc[0]
    tiny = dom.loc[dom["scale_yi"].eq(1)].iloc[0]
    assert mid_scale["score_C_attribution"] > tiny["score_C_attribution"]
    print("  低费率成本分更高, 适度/大规模流动性分高于迷你规模 ✓")


def test_defer_small_subgroup():
    print("== 子组<5 defer ==")
    df = bi.build_index_metrics(_synth(n_each=4))
    assert bi.score_index(df).empty
    print("  两个子组各4只 -> defer(空) ✓")


def test_tracking_error_direction():
    print("== tracking_error 方向 ==")
    rng = np.random.default_rng(28)
    idx = pd.bdate_range(end="2026-05-29", periods=260)
    index_ret = pd.Series(rng.normal(0.0001, 0.002, len(idx)), index=idx)
    rows, navs, index_map = [], {}, {}
    for i in range(6):
        noise = 0.0002 + i * 0.0005
        ret = index_ret + rng.normal(0, noise, len(idx))
        code = f"D{i:03d}"
        navs[code] = pd.Series((1 + ret).cumprod(), index=idx)
        index_map[code] = index_ret
        rows.append({
            "fund_code": code,
            "fund_type": "指数型-固收",
            "total_fee": 0.004,
            "scale_yi": 10,
            "fund_age_years": 5,
        })
    df = bi.build_index_metrics(pd.DataFrame(rows), navs, index_map)
    scored = bi.score_index(df)
    best = scored.loc[scored["tracking_error"].idxmin()]
    worst = scored.loc[scored["tracking_error"].idxmax()]
    assert best["score_A_return"] > worst["score_A_return"]
    assert best["weight_coverage"] >= 0.75
    print("  跟踪误差小 -> A维更高, A维补齐后覆盖率升为formal区间 ✓")


def test_index_mainstream_direction():
    print("== index_mainstream 方向 ==")
    df = _synth(n_each=6).query("fund_type == '指数型-固收'").copy()
    df["index_mainstream"] = [0.1, 0.2, 0.4, 0.6, 0.8, 1.0]
    scored = bi.score_index(bi.build_index_metrics(df))
    high = scored.loc[scored["index_mainstream"].idxmax()]
    low = scored.loc[scored["index_mainstream"].idxmin()]
    assert high["score_D_manager"] > low["score_D_manager"]
    print("  主流度高 -> D维更高 ✓")


def test_missing_mapping_stays_provisional():
    print("== 映射缺失降级 ==")
    idx = pd.bdate_range(end="2026-05-29", periods=80)
    navs = {f"D{i:03d}": pd.Series(np.linspace(1.0, 1.05, len(idx)), index=idx)
            for i in range(6)}
    df = bi.build_index_metrics(_synth(n_each=6).query("fund_type == '指数型-固收'"),
                                navs=navs, index_ret_map={})
    scored = bi.score_index(df)
    assert scored["tracking_error"].isna().all()
    assert scored["score_label"].str.startswith("provisional").all()
    print("  有基金净值但无指数映射 -> tracking缺失, provisional ✓")


if __name__ == "__main__":
    test_split_and_phase_a_degrade()
    test_fee_and_scale_rank_within_group()
    test_defer_small_subgroup()
    test_tracking_error_direction()
    test_index_mainstream_direction()
    test_missing_mapping_stays_provisional()
    print("\nBOND_INDEX 工具型记分卡测试全部通过 ✅")
