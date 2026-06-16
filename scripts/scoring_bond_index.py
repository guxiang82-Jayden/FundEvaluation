"""BOND_INDEX 工具型记分卡(v0 先验, Phase A)。

工具型语义重映射:
    A_return        -> 跟踪有效性
    B_risk          -> 成本
    C_attribution   -> 流动性/规模
    D_manager       -> 指数代表性
    E_operation     -> 运作稳定性

复用 scoring.score_all 的五个槽位键只是为了不改通用评分引擎。
本模块不评价 alpha, 只评价工具属性: 跟得准、便宜、好交易、指数有代表性。

数据相位:
    Phase A: 仓库暂无 "基金 -> 标的指数" 映射表, 因而 tracking_error 与
             index_mainstream 多数缺失。评分会按现有 total_fee/scale/fund_age
             自动降级, 并标记 provisional。
    Phase B: 建 index_map_bond.csv 后补 tracking_error 与 index_mainstream。

权重均为 v0 先验, 待回测/人工复核校准。配置只写在本模块, 不进 config.py。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import scoring


MIN_GROUP = 5

INDEX_DIM_WEIGHTS = {
    "A_return": 0.35,        # 跟踪有效性
    "B_risk": 0.30,          # 成本
    "C_attribution": 0.20,   # 流动性/规模
    "D_manager": 0.10,       # 指数代表性
    "E_operation": 0.05,     # 运作稳定性
}

INDEX_INDICATORS = {
    "A_return": {
        "tracking_error": (0.80, -1),
        "info_ratio_track": (0.20, 1),
    },
    "B_risk": {
        "total_fee": (0.80, -1),
        "bid_ask_proxy": (0.20, -1),
    },
    "C_attribution": {
        "scale_adj": (0.80, 1),
        "turnover_amt_proxy": (0.20, 1),
    },
    "D_manager": {
        "index_mainstream": (1.00, 1),
    },
    "E_operation": {
        "fund_age_years": (0.70, 1),
        "scale_stability": (0.30, 1),
    },
}


def split_index_subgroup(df: pd.DataFrame) -> pd.DataFrame:
    """Add index_subgroup: 指数固收 vs QDII债."""
    if "fund_type" not in df.columns:
        raise ValueError("split_index_subgroup requires fund_type")
    out = df.copy()
    fund_type = out["fund_type"].fillna("").astype(str)
    out["index_subgroup"] = np.where(
        fund_type.str.contains("QDII", regex=False), "QDII债", "指数固收")
    return out


def _scale_adj(scale_yi: pd.Series) -> pd.Series:
    """Log-capped scale score input.

    工具型基金规模太小有清盘/交易冲击风险, 但规模超过约 50 亿后边际收益
    不应继续线性增加, 因此用 log1p(min(scale, 50)) 钝化。
    """
    scale = pd.to_numeric(scale_yi, errors="coerce").clip(lower=0, upper=50)
    return np.log1p(scale)


def _tracking_stats(nav: pd.Series, index_ret: pd.Series) -> tuple[float, float]:
    fund_ret = pd.to_numeric(nav, errors="coerce").sort_index().pct_change()
    idx_ret = pd.to_numeric(index_ret, errors="coerce").sort_index()
    aligned = pd.concat(
        [fund_ret.rename("fund"), idx_ret.rename("index")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 20:
        return np.nan, np.nan
    excess = aligned["fund"] - aligned["index"]
    te = float(excess.std() * np.sqrt(252))
    if te <= 1e-12 or np.isnan(te):
        return te, np.nan
    ir = float(excess.mean() * 252 / te)
    return te, ir


def _lookup_index_return(row: pd.Series, index_ret_map: dict | None):
    """Flexible Phase-B hook.

    Accepted forms:
    - index_ret_map[fund_code] -> Series
    - row["index_code"] or row["benchmark_code"] then index_ret_map[index_code]
    """
    if not index_ret_map:
        return None
    code = str(row.get("fund_code", ""))
    if code in index_ret_map:
        return index_ret_map[code]
    for col in ("index_code", "benchmark_code"):
        key = row.get(col)
        if pd.notna(key) and str(key) in index_ret_map:
            return index_ret_map[str(key)]
    return None


def build_index_metrics(
    df: pd.DataFrame,
    navs: dict[str, pd.Series] | None = None,
    index_ret_map: dict | None = None,
) -> pd.DataFrame:
    """Prepare BOND_INDEX score inputs.

    Phase A 可只传 df, 将补 index_subgroup/scale_adj, tracking_error 保持 NaN。
    Phase B 传 navs + index_ret_map 后计算 tracking_error/info_ratio_track。
    """
    if "fund_code" not in df.columns:
        raise ValueError("build_index_metrics requires fund_code")
    out = split_index_subgroup(df)
    if "scale_yi" in out.columns:
        out["scale_adj"] = _scale_adj(out["scale_yi"])
    else:
        out["scale_adj"] = np.nan

    tracking_errors = {}
    info_ratios = {}
    for _, row in out.iterrows():
        code = str(row["fund_code"])
        nav = (navs or {}).get(code)
        index_ret = _lookup_index_return(row, index_ret_map)
        if nav is None or index_ret is None:
            tracking_errors[code] = np.nan
            info_ratios[code] = np.nan
            continue
        te, ir = _tracking_stats(nav, index_ret)
        tracking_errors[code] = te
        info_ratios[code] = ir
    codes = out["fund_code"].astype(str)
    out["tracking_error"] = codes.map(tracking_errors)
    out["info_ratio_track"] = codes.map(info_ratios)
    return out


def score_index(df: pd.DataFrame, group_col: str = "index_subgroup") -> pd.DataFrame:
    """Score BOND_INDEX funds within 指数固收/QDII债 subgroups.

    子组不足 MIN_GROUP 时 defer(返回空或只返回可评分子组)。工具型只扣分不一票否决:
    score_all 当前不支持 veto_dim=None, 因此内部传入 B_risk 后清零 veto。
    """
    if df is None or df.empty:
        return pd.DataFrame()
    work = build_index_metrics(df) if group_col not in df.columns else df.copy()
    parts = []
    for _, group in work.groupby(group_col, dropna=False, sort=False):
        if len(group) < MIN_GROUP:
            continue
        scored = scoring.score_all(
            group,
            dim_weights=INDEX_DIM_WEIGHTS,
            indicators=INDEX_INDICATORS,
            veto_dim="B_risk",
            primary_dim="A_return",
        )
        scored["veto"] = False
        scored["scorecard"] = "BOND_INDEX"
        parts.append(scored)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True, sort=False)


if __name__ == "__main__":
    demo = pd.DataFrame({
        "fund_code": [f"I{i:03d}" for i in range(6)],
        "fund_type": ["指数型-固收"] * 6,
        "total_fee": np.linspace(0.002, 0.008, 6),
        "scale_yi": [1, 3, 8, 20, 50, 100],
        "fund_age_years": np.linspace(1, 8, 6),
    })
    print(score_index(build_index_metrics(demo))[
        ["fund_code", "index_subgroup", "composite_score", "score_label"]
    ].to_string(index=False))
