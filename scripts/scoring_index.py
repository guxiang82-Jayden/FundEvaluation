"""权益被动指数与 ETF 工具型记分卡（v0 先验，待校准）。

复用 scoring.score_all 的五槽结构：
  A 跟踪有效性 / B 成本 / C 流动性规模 / D 指数代表性 / E 运作。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import scoring

MIN_GROUP = 5

INDEX_EQUITY_DIM_WEIGHTS = {
    "A_return": 0.40,
    "B_risk": 0.25,
    "C_attribution": 0.20,
    "D_manager": 0.10,
    "E_operation": 0.05,
}

INDEX_EQUITY_INDICATORS = {
    "A_return": {
        "tracking_error": (0.80, -1),
        "info_ratio": (0.20, 1),
    },
    "B_risk": {"total_fee": (1.00, -1)},
    "C_attribution": {"scale_adj": (1.00, 1)},
    "D_manager": {"index_mainstream": (1.00, 1)},
    "E_operation": {
        "fund_age_years": (0.70, 1),
        "scale_stability": (0.30, 1),
    },
}

ETF_DIM_WEIGHTS = {
    "A_return": 0.35,
    "B_risk": 0.15,
    "C_attribution": 0.25,
    "D_manager": 0.15,
    "E_operation": 0.10,
}

ETF_INDICATORS = {
    "A_return": {
        "tracking_error": (0.70, -1),
        "tracking_deviation": (0.30, -1),
    },
    "B_risk": {"total_fee": (1.00, -1)},
    "C_attribution": {
        "amount_avg": (0.50, 1),
        "turnover_amt": (0.25, 1),
        "bid_ask_spread": (0.25, -1),
    },
    "D_manager": {
        "premium_discount_abs": (0.60, -1),
        "premium_discount_std": (0.40, -1),
    },
    "E_operation": {
        "scale_adj": (0.65, 1),
        "fund_age_years": (0.35, 1),
    },
}


def scale_adjusted(scale_yi: pd.Series) -> pd.Series:
    """规模边际钝化；低于 2 亿另由 investability_warn 前置提示。"""
    scale = pd.to_numeric(scale_yi, errors="coerce").clip(lower=0, upper=100)
    return np.log1p(scale)


def tracking_stats(nav: pd.Series, index_ret: pd.Series) -> dict:
    fund_ret = pd.to_numeric(nav, errors="coerce").sort_index().pct_change()
    idx_ret = pd.to_numeric(index_ret, errors="coerce").sort_index()
    aligned = pd.concat(
        [fund_ret.rename("fund"), idx_ret.rename("index")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 60:
        return {
            "tracking_error": np.nan,
            "info_ratio": np.nan,
            "tracking_deviation": np.nan,
            "tracking_days": len(aligned),
        }
    excess = aligned["fund"] - aligned["index"]
    te = float(excess.std() * np.sqrt(252))
    deviation = float(abs(excess.mean() * 252))
    ir = float(excess.mean() * 252 / te) if te > 1e-12 else np.nan
    return {
        "tracking_error": te,
        "info_ratio": ir,
        "tracking_deviation": deviation,
        "tracking_days": len(aligned),
    }


def prepare_metrics(df: pd.DataFrame, track: str) -> pd.DataFrame:
    out = df.copy()
    out["scale_adj"] = scale_adjusted(
        out.get("scale_yi", pd.Series(np.nan, index=out.index)))
    out["investability_warn"] = (
        out.get("investability_warn", pd.Series(False, index=out.index))
        .fillna(False).astype(bool)
        | (pd.to_numeric(out.get("scale_yi"), errors="coerce") < 2)
    )
    out["track"] = track
    return out


def _score_by_family(
    df: pd.DataFrame,
    *,
    scorecard: str,
    dim_weights: dict,
    indicators: dict,
    group_col: str = "index_family",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    scored_parts = []
    deferred_parts = []
    for _, group in df.groupby(group_col, dropna=False, sort=False):
        if len(group) < MIN_GROUP:
            deferred_parts.append(group.assign(defer_reason="同指数族少于5只"))
            continue
        scored = scoring.score_all(
            group,
            dim_weights=dim_weights,
            indicators=indicators,
            veto_dim="B_risk",
            primary_dim="A_return",
        )
        scored["veto"] = False
        tracking_missing = scored["tracking_error"].isna()
        scored.loc[tracking_missing, "provisional"] = True
        scored.loc[tracking_missing, "score_label"] = "provisional_tracking_missing"
        if "focus_pool" in scored:
            scored.loc[tracking_missing, "focus_pool"] = False
        scored["scorecard"] = scorecard
        scored_parts.append(scored)
    scored_out = (
        pd.concat(scored_parts, ignore_index=True, sort=False)
        if scored_parts else pd.DataFrame())
    deferred_out = (
        pd.concat(deferred_parts, ignore_index=True, sort=False)
        if deferred_parts else pd.DataFrame())
    return scored_out, deferred_out


def score_index_equity(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = prepare_metrics(df, "INDEX")
    return _score_by_family(
        work,
        scorecard="INDEX",
        dim_weights=INDEX_EQUITY_DIM_WEIGHTS,
        indicators=INDEX_EQUITY_INDICATORS,
    )


def score_etf(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = prepare_metrics(df, "ETF")
    return _score_by_family(
        work,
        scorecard="ETF",
        dim_weights=ETF_DIM_WEIGHTS,
        indicators=ETF_INDICATORS,
    )
