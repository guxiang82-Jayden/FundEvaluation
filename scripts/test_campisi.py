"""campisi.py 净值五因子归因测试
运行: python test_campisi.py
"""
import numpy as np
import pandas as pd

import campisi


def _make_factors(seed=5, n=150):
    rng = np.random.default_rng(seed)
    weeks = pd.date_range(end="2026-06-12", periods=n, freq="W-FRI")
    idx = {
        "中债国债总财富": pd.Series(rng.normal(0.0008, 0.003, n), index=weeks),
        "中债中短期": pd.Series(rng.normal(0.0009, 0.0035, n), index=weeks),
        "中债长期": pd.Series(rng.normal(0.001, 0.006, n), index=weeks),
        "中债企业债AAA": pd.Series(rng.normal(0.001, 0.004, n), index=weeks),
        "中债国开债": pd.Series(rng.normal(0.0009, 0.0035, n), index=weeks),
        "中债高收益企业债": pd.Series(rng.normal(0.0015, 0.006, n), index=weeks),
        "中债转债": pd.Series(rng.normal(0.002, 0.02, n), index=weeks),
    }
    return campisi.build_factors(idx), rng


def test_campisi():
    print("== Campisi 净值五因子测试 ==")
    F, rng = _make_factors()
    assert list(F.columns) == ["level", "slope", "credit", "default", "convertible"]
    print(f"  五因子构造 [OK] {F.shape}")

    # 纯债: 因子线性组合 + 小alpha + 小噪声 → 高R^2, alpha可信
    pure = 0.8 * F["level"] + 0.5 * F["credit"] + 0.0003 + rng.normal(0, 0.0005, len(F))
    rp = campisi.campisi_regress(pure, F)
    assert rp["r2"] > 0.7 and rp["confidence"] == "high", rp
    print(f"  纯债: R^2={rp['r2']:.3f} high, alpha年化={rp['alpha_ann']:.2%} [OK]")

    # 含权: 大独立噪声(权益部分债券因子无法解释) → 低R^2, 标低置信度
    mixed = 0.6 * F["level"] + 0.4 * F["convertible"] + rng.normal(0, 0.015, len(F))
    rm = campisi.campisi_regress(mixed, F)
    assert rm["r2"] < 0.5 and "low" in rm["confidence"], rm
    print(f"  含权: R^2={rm['r2']:.3f} {rm['confidence']} [OK]")

    # 数据不足保护
    assert campisi.campisi_regress(pure.head(10), F.head(10))["confidence"] == "insufficient"
    print("  数据不足保护 [OK]")

    # 日→周频
    nav = pd.Series((1 + pd.Series(rng.normal(0.0002, 0.002, 400),
                                   index=pd.bdate_range(end="2026-06-12", periods=400))).cumprod())
    wk = campisi.nav_to_weekly(nav)
    assert 70 < len(wk) < 85
    print(f"  日→周频: {len(nav)}日→{len(wk)}周 [OK]")


if __name__ == "__main__":
    test_campisi()
    print("\n全部通过 [OK]")
