"""可转债(CB)专用记分卡(v0 先验, 对应 25 号子任务 + 10_固收线框架)。
背景: 真跑质检确认可转债净值 Campisi R²≈0.03, 权益属性强, 不能与纯债同卡。
口径: 在"可转债基金"组内分位; **不展示可解释为择券alpha的净值残差**, 评价绝对收益体验+风控+弹性适度。
⚠️ 维度权重为 v0 先验, 待 backtest RankIC 校准。配置写在本模块, 暂不进 config.py。
隔离: 复用 scoring.score_all(参数化) + metrics; 不改任何主线文件。主线后续一行接入 run_monthly_bond。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import scoring

# v0 先验权重(待校准)——B风控最重, A绝对收益, C弹性适度(U型), D/E轻
CB_DIM_WEIGHTS = {
    "A_return": 0.30,
    "B_risk": 0.40,
    "C_attribution": 0.20,
    "D_manager": 0.05,
    "E_operation": 0.05,
}

CB_INDICATORS = {
    "A_return": {
        "ann_return": (0.50, 1),                # 绝对年化收益
        "monthly_positive_ratio": (0.50, 1),    # 月度正收益占比
    },
    "B_risk": {
        "max_drawdown": (0.35, 1),              # 取负后高=好(scoring._PREP 处理)
        "calmar": (0.30, 1),
        "sortino": (0.20, 1),
        "recovery_days": (0.15, -1),
    },
    "C_attribution": {                           # 弹性/风格: 适度为佳(U型)
        "equity_beta": (0.50, 0),               # 对权益指数的净值回归 beta
        "convertible_ratio": (0.50, 0),         # 转债仓位(来自 cdim_bond)
    },
    "D_manager": {
        "manager_experience": (0.50, 1),
        "management_load": (0.50, -1),
    },
    "E_operation": {
        "total_fee": (1.00, -1),
    },
}

MIN_GROUP = 5


def equity_beta(nav: pd.Series, equity_index_ret: pd.Series) -> float:
    """净值日收益对权益指数日收益的 OLS beta(弹性代理)。无重叠返回 NaN。"""
    if nav is None or equity_index_ret is None or len(nav) == 0:
        return np.nan
    fund_ret = pd.to_numeric(nav, errors="coerce").sort_index().pct_change()
    idx = pd.to_numeric(equity_index_ret, errors="coerce").sort_index()
    a = pd.concat([fund_ret.rename("f"), idx.rename("x")], axis=1, join="inner").dropna()
    if len(a) < 20:
        return np.nan
    x = a["x"].to_numpy(dtype=float)
    if float(np.var(x)) <= 1e-16:
        return np.nan
    return float(np.cov(x, a["f"].to_numpy(dtype=float), ddof=0)[0, 1] / np.var(x))


def build_cb_metrics(df: pd.DataFrame, navs: dict,
                     equity_index_ret: pd.Series | None = None) -> pd.DataFrame:
    """补 equity_beta 列(convertible_ratio 若已由 cdim_bond 并入则保留)。"""
    out = df.copy()
    if "fund_code" not in out.columns:
        raise ValueError("build_cb_metrics requires fund_code")
    betas = {}
    for code in out["fund_code"].astype(str):
        nav = (navs or {}).get(code)
        betas[code] = equity_beta(nav, equity_index_ret) if (nav is not None and equity_index_ret is not None) else np.nan
    out["equity_beta"] = out["fund_code"].astype(str).map(betas)
    return out


def score_cb(df: pd.DataFrame, group_col: str = "bond_subgroup") -> pd.DataFrame:
    """可转债组内分位评分(<MIN_GROUP defer)。tag scorecard='CB'。"""
    if df is None or df.empty:
        return pd.DataFrame()
    parts = []
    for _, gdf in df.groupby(group_col):
        if len(gdf) < MIN_GROUP:
            continue
        parts.append(scoring.score_all(
            gdf, dim_weights=CB_DIM_WEIGHTS, indicators=CB_INDICATORS,
            veto_dim="B_risk", primary_dim="A_return"))
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["scorecard"] = "CB"
    return out


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    idx = pd.bdate_range(end="2026-05-29", periods=800)
    eq = pd.Series(rng.normal(0.0003, 0.012, 800), index=idx)
    navs = {}
    rows = []
    for i in range(8):
        beta = 0.2 + i * 0.08
        r = beta * eq.values + rng.normal(0.0002, 0.004, 800)
        nav = pd.Series((1 + pd.Series(r, index=idx)).cumprod(), index=idx)
        navs[f"{i:06d}"] = nav
        rows.append({"fund_code": f"{i:06d}", "bond_subgroup": "可转债基金",
                     "ann_return_3y": rng.uniform(0, 0.15), "monthly_positive_ratio_3y": rng.uniform(0.4, 0.8),
                     "max_drawdown_3y": -rng.uniform(0.05, 0.3), "calmar_3y": rng.uniform(0.2, 2),
                     "sortino_3y": rng.uniform(0.2, 2), "recovery_days_3y": rng.integers(20, 300),
                     "convertible_ratio": rng.uniform(0.5, 1.0), "manager_experience": rng.uniform(2, 12),
                     "management_load": rng.uniform(20, 300), "total_fee": rng.uniform(0.004, 0.009),
                     "scale_yi": rng.uniform(5, 50), "valid_3y": True})
    df = build_cb_metrics(pd.DataFrame(rows), navs, eq)
    print("equity_beta:", df["equity_beta"].round(2).tolist())
    print(score_cb(df)[["fund_code", "composite_score", "score_B_risk", "equity_beta"]].round(2).to_string(index=False))
