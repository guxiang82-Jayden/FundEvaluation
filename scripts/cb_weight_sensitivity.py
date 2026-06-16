"""CB v0 权重敏感性分析。

默认用合成样本自测；也可传入 CSV/Excel 指标表，要求列名与
scoring_bond_cb.CB_INDICATORS 对齐。脚本不修改 scoring_bond_cb.py。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import scoring
import scoring_bond_cb as cb


SHOCKS = (-0.20, -0.10, 0.10, 0.20)
TARGET_DIMS = ("A_return", "B_risk", "C_attribution")


def synth_cb_metrics(n: int = 24, seed: int = 29) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    quality = np.linspace(0, 1, n)
    return pd.DataFrame({
        "fund_code": [f"CB{i:03d}" for i in range(n)],
        "bond_subgroup": "可转债基金",
        "ann_return_3y": 0.02 + 0.12 * quality + rng.normal(0, 0.01, n),
        "monthly_positive_ratio_3y": 0.45 + 0.35 * quality + rng.normal(0, 0.03, n),
        "max_drawdown_3y": -(0.28 - 0.16 * quality + rng.normal(0, 0.02, n)),
        "calmar_3y": 0.2 + 1.8 * quality + rng.normal(0, 0.15, n),
        "sortino_3y": 0.3 + 1.6 * quality + rng.normal(0, 0.15, n),
        "recovery_days_3y": 260 - 180 * quality + rng.normal(0, 20, n),
        "equity_beta": 0.25 + 0.45 * quality + rng.normal(0, 0.04, n),
        "convertible_ratio": 0.45 + 0.45 * quality + rng.normal(0, 0.04, n),
        "manager_experience": 2 + 8 * rng.random(n),
        "management_load": 30 + 200 * rng.random(n),
        "total_fee": 0.004 + 0.006 * rng.random(n),
        "scale_yi": 3 + 60 * rng.random(n),
        "valid_3y": True,
    })


def _read_table(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(p, dtype={"fund_code": str})
    return pd.read_csv(p, dtype={"fund_code": str})


def _renormalized_weights(dim: str, shock: float) -> dict:
    """Perturb one of A/B/C, keep D/E fixed, renormalize A/B/C sum."""
    weights = dict(cb.CB_DIM_WEIGHTS)
    fixed_sum = weights["D_manager"] + weights["E_operation"]
    variable_sum = 1.0 - fixed_sum
    raw = {k: weights[k] for k in TARGET_DIMS}
    raw[dim] = max(0.01, raw[dim] * (1.0 + shock))
    scale = variable_sum / sum(raw.values())
    for k in TARGET_DIMS:
        weights[k] = raw[k] * scale
    return weights


def _score_with_weights(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    out = scoring.score_all(
        df,
        dim_weights=weights,
        indicators=cb.CB_INDICATORS,
        veto_dim="B_risk",
        primary_dim="A_return",
    )
    out["scorecard"] = "CB"
    return out


def top_overlap(a: pd.Series, b: pd.Series, top_n: int = 5) -> float:
    aa = set(a.sort_values(ascending=False).head(top_n).index)
    bb = set(b.sort_values(ascending=False).head(top_n).index)
    return len(aa & bb) / max(1, top_n)


def sensitivity_table(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    base = _score_with_weights(df, cb.CB_DIM_WEIGHTS).set_index("fund_code")
    base_score = base["composite_score"]
    rows = []
    for dim in TARGET_DIMS:
        for shock in SHOCKS:
            weights = _renormalized_weights(dim, shock)
            scored = _score_with_weights(df, weights).set_index("fund_code")
            score = scored["composite_score"]
            rows.append({
                "perturbed_dim": dim,
                "shock": shock,
                "weight_after": round(weights[dim], 4),
                "spearman": float(base_score.rank().corr(score.rank())),
                "top5_overlap": top_overlap(base_score, score, top_n=top_n),
            })
    return pd.DataFrame(rows)


def summarize_sensitivity(tab: pd.DataFrame) -> pd.DataFrame:
    return (
        tab.groupby("perturbed_dim")
        .agg(
            mean_spearman=("spearman", "mean"),
            min_spearman=("spearman", "min"),
            mean_top5_overlap=("top5_overlap", "mean"),
            min_top5_overlap=("top5_overlap", "min"),
        )
        .reset_index()
        .sort_values("min_spearman")
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="CB metric table csv/xlsx; omit for synthetic self-test")
    ap.add_argument("--top-n", type=int, default=5)
    args = ap.parse_args()

    df = _read_table(args.input) if args.input else synth_cb_metrics()
    tab = sensitivity_table(df, top_n=args.top_n)
    summary = summarize_sensitivity(tab)
    print("== 扰动明细 ==")
    print(tab.round(4).to_string(index=False))
    print("\n== 敏感性汇总 ==")
    print(summary.round(4).to_string(index=False))
    weakest = summary.iloc[0]
    print(
        f"\n最敏感维度: {weakest['perturbed_dim']} | "
        f"最低Spearman={weakest['min_spearman']:.3f}, "
        f"最低Top{args.top_n}重合={weakest['min_top5_overlap']:.0%}"
    )


if __name__ == "__main__":
    main()
