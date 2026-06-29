"""指数增强评价卡：评价相对标的指数的持续、风险调整后超额。

权重为 v0 先验，待指增专用回测校准。基金使用复权净值，标的使用价格
指数，因此超额可能略高估；取得全收益指数后应替换标的源。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import scoring

MIN_GROUP = 5

ENHANCED_DIM_WEIGHTS = {
    "A_return": 0.40,
    "B_risk": 0.25,
    "C_attribution": 0.15,
    "D_manager": 0.10,
    "E_operation": 0.10,
}

ENHANCED_INDICATORS = {
    "A_return": {
        "excess_return_ann": (0.40, 1),
        "info_ratio": (0.35, 1),
        "excess_win_rate": (0.25, 1),
    },
    "B_risk": {
        "excess_max_drawdown": (0.60, 1),
        "excess_calmar": (0.40, 1),
    },
    "C_attribution": {
        "style_stability": (0.60, 1),
        # 指增 TE 追求适中而非越低越好；组内距中位数近得分高。
        "tracking_error": (0.40, 0),
    },
    "D_manager": {
        "manager_experience": (0.60, 1),
        "management_load": (0.40, -1),
    },
    "E_operation": {
        "total_fee": (0.85, -1),
        "turnover": (0.15, -1),
    },
}


def _empty_metrics(days: int = 0) -> dict:
    return {
        "excess_return_ann": np.nan,
        "info_ratio": np.nan,
        "excess_win_rate": np.nan,
        "excess_max_drawdown": np.nan,
        "excess_calmar": np.nan,
        "tracking_error": np.nan,
        "tracking_days": days,
    }


def excess_metrics(nav: pd.Series, index_ret: pd.Series) -> dict:
    """按共同交易日计算指增超额指标，至少需要120个观测。"""
    fund_ret = pd.to_numeric(nav, errors="coerce").sort_index().pct_change()
    benchmark = pd.to_numeric(index_ret, errors="coerce").sort_index()
    aligned = pd.concat(
        [fund_ret.rename("fund"), benchmark.rename("index")],
        axis=1, join="inner").replace([np.inf, -np.inf], np.nan).dropna()
    if len(aligned) < 120:
        return _empty_metrics(len(aligned))

    excess = aligned["fund"] - aligned["index"]
    tracking_error = float(excess.std() * np.sqrt(252))
    excess_ann = float(excess.mean() * 252)
    info_ratio = (
        float(excess_ann / tracking_error)
        if tracking_error > 1e-12 else np.nan)
    rolling_excess = excess.rolling(60, min_periods=60).sum()
    win_rate = float((rolling_excess > 0).mean())
    wealth = (1 + excess.clip(lower=-0.999999)).cumprod()
    drawdown = wealth / wealth.cummax() - 1
    max_drawdown = float(drawdown.min())
    calmar = (
        float(excess_ann / abs(max_drawdown))
        if abs(max_drawdown) > 1e-12 else np.nan)
    return {
        "excess_return_ann": excess_ann,
        "info_ratio": info_ratio,
        "excess_win_rate": win_rate,
        "excess_max_drawdown": max_drawdown,
        "excess_calmar": calmar,
        "tracking_error": tracking_error,
        "tracking_days": len(aligned),
    }


def prepare_metrics(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    te = pd.to_numeric(
        out.get("tracking_error", pd.Series(np.nan, index=out.index)),
        errors="coerce")
    out["pseudo_enhance_warn"] = te < 0.01
    out["te_excess_warn"] = te > 0.12
    out["track"] = "ENHANCED"
    return out


def score_enhanced(
    df: pd.DataFrame,
    group_col: str = "index_family",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = prepare_metrics(df)
    scored_parts = []
    deferred_parts = []
    for family, group in work.groupby(group_col, dropna=False, sort=False):
        if family == "映射缺失":
            provisional = group.copy()
            provisional["provisional"] = True
            provisional["score_label"] = "provisional_mapping_missing"
            provisional["scorecard"] = "ENHANCED"
            provisional["defer_reason"] = "标的指数映射缺失"
            deferred_parts.append(provisional)
            continue
        if len(group) < MIN_GROUP:
            deferred_parts.append(group.assign(defer_reason="同指数族少于5只"))
            continue
        scored = scoring.score_all(
            group,
            dim_weights=ENHANCED_DIM_WEIGHTS,
            indicators=ENHANCED_INDICATORS,
            veto_dim="B_risk",
            primary_dim="A_return",
        )
        style_missing = scored.get(
            "style_stability", pd.Series(np.nan, index=scored.index)).isna()
        scored["low_confidence"] = style_missing
        scored.loc[style_missing, "provisional"] = True
        scored.loc[style_missing, "score_label"] = "provisional_style_missing"
        scored.loc[style_missing, "focus_pool"] = False
        scored["scorecard"] = "ENHANCED"
        scored_parts.append(scored)
    scored_out = (
        pd.concat(scored_parts, ignore_index=True, sort=False)
        if scored_parts else pd.DataFrame())
    deferred_out = (
        pd.concat(deferred_parts, ignore_index=True, sort=False)
        if deferred_parts else pd.DataFrame())
    return scored_out, deferred_out
