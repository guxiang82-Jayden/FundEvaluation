"""cdim_bond 加载层 + C 维生效离线测试。
验证: 接入 C 维后, 债基评分覆盖率从 0.75(ABDE) 升到 1.0(ABCDE) -> formal。
运行(在 scripts/ 下): python test_cdim_bond.py
"""
import numpy as np
import pandas as pd

import cdim_bond
import config
import scoring


def test_cdim_bond_loader_and_coverage():
    import tempfile

    print("== cdim_bond 加载 + C 维覆盖率测试 ==")
    codes = [f"{i:06d}" for i in range(10)]
    n = len(codes)
    rng = np.random.default_rng(0)
    # 合成 A/B/D/E(C 来自真实 CSV)
    df = pd.DataFrame({
        "fund_code": codes,
        "bond_subgroup": "中长期纯债",
        "campisi_alpha": rng.normal(0.01, 0.005, n),
        "ann_return_3y": rng.normal(0.03, 0.01, n),
        "cpr_persistence": rng.uniform(0.5, 3, n),
        "calmar_3y": rng.uniform(0.5, 5, n),
        "max_drawdown_3y": -rng.uniform(0.005, 0.05, n),
        "recovery_days_3y": rng.integers(10, 200, n),
        "sortino_3y": rng.uniform(0.5, 4, n),
        "monthly_positive_ratio_3y": rng.uniform(0.5, 0.95, n),
        "manager_experience": rng.uniform(2, 12, n),
        "management_load": rng.uniform(20, 400, n),
        "total_fee": rng.uniform(0.003, 0.008, n),
        "scale_yi": rng.uniform(5, 50, n),
        "valid_3y": True,
    })

    source = pd.DataFrame({
        "fund_code": codes,
        "credit_ratio": rng.uniform(0.2, 0.8, n),
        "dur_sensitive": rng.uniform(1.0, 5.0, n),
        "leverage_ratio": rng.uniform(1.0, 1.3, n),
        "neg_alert": False,
        "cr5_bond": rng.uniform(0.2, 0.6, n),
        "convertible_ratio": 0.0,
    })
    old_path = cdim_bond.CDIM_BOND_CSV
    try:
        with tempfile.TemporaryDirectory() as d:
            cdim_bond.CDIM_BOND_CSV = f"{d}/cdim_bond_data.csv"
            source.to_csv(cdim_bond.CDIM_BOND_CSV, index=False)
            merged = cdim_bond.load_cdim_bond(df)
    finally:
        cdim_bond.CDIM_BOND_CSV = old_path
    # C 维派生列已并入
    assert "credit_sink" in merged and "duration_dev" in merged and "leverage_contrib" in merged
    assert merged["credit_sink"].notna().sum() == n
    assert "neg_alert" in merged and "leverage_ratio" in merged, "排雷/杠杆列未直通"

    scored = scoring.score_all(
        merged, dim_weights=config.BOND_DIM_WEIGHTS,
        indicators=config.BOND_INDICATORS, veto_dim="B_risk", primary_dim="A_return")

    assert scored["composite_score"].between(0, 100).all()
    assert scored["score_C_attribution"].notna().any(), "C 维仍全空"
    cov = scored["weight_coverage"].iloc[0]
    assert abs(cov - 1.0) < 1e-9, f"接 C 维后覆盖率应 1.0, 实为 {cov}"
    assert (scored["score_label"] == "formal").all(), "全五维应 formal"
    cmissing = scored["score_C_attribution"].isna().sum()
    print(f"  C维命中: credit_sink {merged['credit_sink'].notna().sum()}/{n}, "
          f"duration {merged['duration_dev'].notna().sum()}/{n}")
    print(f"  覆盖率 {cov:.0%}(ABCDE) -> formal [OK] | C维评出 {n - cmissing}/{n} 只")
    print(f"  综合分范围 [{scored['composite_score'].min():.1f}, {scored['composite_score'].max():.1f}]")


def test_pick_effect_data_gated(tmp_path=None):
    print("== pick_effect -> pick_alpha_bond data-gated 测试 ==")
    import tempfile
    rng = np.random.default_rng(32)
    codes = [f"{i:06d}" for i in range(6)]
    base = pd.DataFrame({
        "fund_code": codes,
        "bond_subgroup": "中长期纯债",
        "campisi_alpha": rng.normal(0.01, 0.001, 6),
        "ann_return_3y": rng.normal(0.03, 0.001, 6),
        "cpr_persistence": rng.uniform(1, 2, 6),
        "calmar_3y": rng.uniform(2, 3, 6),
        "max_drawdown_3y": -rng.uniform(0.01, 0.02, 6),
        "recovery_days_3y": rng.integers(20, 40, 6),
        "sortino_3y": rng.uniform(1, 2, 6),
        "monthly_positive_ratio_3y": rng.uniform(0.7, 0.9, 6),
        "selection_share_bond": 0.2,
        "manager_experience": 5.0,
        "management_load": 100.0,
        "total_fee": 0.004,
        "scale_yi": 30.0,
        "valid_3y": True,
    })
    cdim = pd.DataFrame({
        "fund_code": codes,
        "credit_ratio": 0.4,
        "dur_sensitive": 3.0,
        "leverage_ratio": 1.1,
        "pick_effect": [-0.8, -0.4, -0.1, 0.1, 0.4, 0.8],
    })
    old_path = cdim_bond.CDIM_BOND_CSV
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/cdim_bond_data.csv"
        cdim.to_csv(path, index=False)
        cdim_bond.CDIM_BOND_CSV = path
        merged = cdim_bond.load_cdim_bond(base)
        assert "pick_alpha_bond" in merged.columns
        scored = scoring.score_all(
            merged, dim_weights=config.BOND_DIM_WEIGHTS,
            indicators=config.BOND_INDICATORS, veto_dim="B_risk", primary_dim="A_return")
        ranked = scored.sort_values("pick_alpha_bond")
        assert ranked.iloc[0]["score_C_attribution"] < ranked.iloc[-1]["score_C_attribution"]

        no_pick = cdim.drop(columns=["pick_effect"])
        no_pick.to_csv(path, index=False)
        merged2 = cdim_bond.load_cdim_bond(base)
        assert "pick_alpha_bond" not in merged2.columns
        scored2 = scoring.score_all(
            merged2, dim_weights=config.BOND_DIM_WEIGHTS,
            indicators=config.BOND_INDICATORS, veto_dim="B_risk", primary_dim="A_return")
        assert scored2["score_C_attribution"].notna().any()
    cdim_bond.CDIM_BOND_CSV = old_path
    print("  pick_effect 有则纳入; 缺列则优雅降级 OK")


if __name__ == "__main__":
    test_cdim_bond_loader_and_coverage()
    test_pick_effect_data_gated()
    print("\ncdim_bond C维接入测试通过 [OK]")
