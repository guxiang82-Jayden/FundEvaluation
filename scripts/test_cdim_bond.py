"""cdim_bond 加载层 + C 维生效 测试(用真实 data/cdim_bond_data.csv)。
验证: 接入 C 维后, 债基评分覆盖率从 0.75(ABDE) 升到 1.0(ABCDE) -> formal。
运行(在 scripts/ 下): python test_cdim_bond.py
"""
import numpy as np
import pandas as pd

import cdim_bond
import config
import scoring


def test_cdim_bond_loader_and_coverage():
    print("== cdim_bond 加载 + C 维覆盖率测试 ==")
    src = pd.read_csv("data/cdim_bond_data.csv", dtype={"fund_code": str})
    codes = src["fund_code"].str.zfill(6).tolist()
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

    merged = cdim_bond.load_cdim_bond(df)
    # C 维派生列已并入
    assert "credit_sink" in merged and "duration_dev" in merged and "leverage_contrib" in merged
    assert merged["credit_sink"].notna().sum() >= n * 0.9, "credit_sink 命中过少"
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
    print(f"  覆盖率 {cov:.0%}(ABCDE) -> formal ✓ | C维评出 {n - cmissing}/{n} 只")
    print(f"  综合分范围 [{scored['composite_score'].min():.1f}, {scored['composite_score'].max():.1f}]")


if __name__ == "__main__":
    test_cdim_bond_loader_and_coverage()
    print("\ncdim_bond C维接入测试通过 ✅")
