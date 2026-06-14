"""Scoring helpers for fixed-income-plus funds.

Funds are compared only within the same equity-position band. The module
reuses the generic scoring engine and the mainline BOND_PLUS configuration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
import scoring


ROLLING_DD_DAYS = 60
MIN_GROUP_SIZE = 5


def equity_center_band(equity_position: float) -> str:
    """Map an equity allocation in [0, 1] to 保守/稳健/积极."""
    if equity_position is None or pd.isna(equity_position):
        return "未分组"
    try:
        value = float(equity_position)
    except (TypeError, ValueError):
        return "未分组"
    if value < 0 or value > 1:
        return "未分组"

    bands = list(config.BOND_PLUS_EQUITY_BANDS.items())
    for position, (label, (lower, upper)) in enumerate(bands):
        is_last = position == len(bands) - 1
        if lower <= value < upper or (is_last and value == upper):
            return label
    return "未分组"


def _window_max_drawdown(values: np.ndarray) -> float:
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1.0))


def target_dd_pass(nav: pd.Series, target: float = None) -> float:
    """Share of 60-day windows whose maximum drawdown does not breach target."""
    threshold = config.BOND_PLUS_TARGET_DD if target is None else float(target)
    clean = pd.to_numeric(nav, errors="coerce").dropna().sort_index()
    if len(clean) < ROLLING_DD_DAYS:
        return np.nan
    rolling_dd = clean.rolling(ROLLING_DD_DAYS).apply(
        _window_max_drawdown,
        raw=True,
    )
    valid = rolling_dd.dropna()
    if valid.empty:
        return np.nan
    return float((valid >= threshold).mean())


def equity_contrib_ratio(
    nav: pd.Series,
    equity_index_ret: pd.Series,
) -> float:
    """Estimate the equity contribution as a share of the fund total return.

    OLS is run without changing frequency: fund returns are aligned to the
    supplied equity-index returns and include an intercept. The contribution
    is ``beta * index cumulative return`` over the aligned sample.
    """
    fund_ret = pd.to_numeric(nav, errors="coerce").sort_index().pct_change()
    index_ret = pd.to_numeric(
        equity_index_ret, errors="coerce"
    ).sort_index()
    aligned = pd.concat(
        [fund_ret.rename("fund"), index_ret.rename("equity")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 20:
        return np.nan

    x = aligned["equity"].to_numpy(dtype=float)
    y = aligned["fund"].to_numpy(dtype=float)
    x_var = float(np.var(x))
    if x_var <= 1e-16:
        return np.nan
    beta = float(np.cov(x, y, ddof=0)[0, 1] / x_var)

    equity_total = float(np.prod(1.0 + x) - 1.0)
    fund_total = float(np.prod(1.0 + y) - 1.0)
    if abs(fund_total) <= 1e-12:
        return np.nan
    return beta * equity_total / fund_total


def build_bond_plus_metrics(
    df: pd.DataFrame,
    navs: dict[str, pd.Series],
    equity_index_ret: pd.Series | None = None,
) -> pd.DataFrame:
    """Add the two fixed-income-plus metrics to an existing metric table."""
    if "fund_code" not in df.columns:
        raise ValueError("build_bond_plus_metrics requires fund_code")

    out = df.copy()
    dd_values = {}
    equity_values = {}
    for code in out["fund_code"].astype(str):
        nav = navs.get(code)
        if nav is None:
            dd_values[code] = np.nan
            equity_values[code] = np.nan
            continue
        dd_values[code] = target_dd_pass(nav)
        equity_values[code] = (
            equity_contrib_ratio(nav, equity_index_ret)
            if equity_index_ret is not None
            else np.nan
        )
    codes = out["fund_code"].astype(str)
    out["target_dd_pass"] = codes.map(dd_values)
    out["equity_contrib_ratio"] = codes.map(equity_values)
    return out


def score_bond_plus(df: pd.DataFrame) -> pd.DataFrame:
    """Score fixed-income-plus funds within their equity-position bands."""
    if "equity_position" not in df.columns:
        raise ValueError("score_bond_plus requires equity_position")

    work = df.copy()
    work["equity_band"] = work["equity_position"].map(equity_center_band)
    work["group_score_eligible"] = False
    work["group_score_note"] = ""
    for dim in config.BOND_PLUS_DIM_WEIGHTS:
        work[f"score_{dim}"] = np.nan
    for col in ("composite_score", "weight_coverage"):
        work[col] = np.nan
    work["covered_dims"] = ""
    work["provisional"] = True
    work["score_label"] = "unscored"
    work["shortboard"] = False
    work["veto"] = True
    work["primary_missing"] = True
    work["investability_warn"] = False
    work["focus_pool"] = False
    work["candidate_pool"] = False

    scored_parts = []
    deferred_parts = []
    for band, group in work.groupby("equity_band", sort=False, dropna=False):
        group = group.copy()
        if band == "未分组":
            group["group_score_note"] = "权益仓位缺失或越界"
            deferred_parts.append(group)
            continue
        if len(group) < MIN_GROUP_SIZE:
            group["group_score_note"] = f"同档样本不足{MIN_GROUP_SIZE}只"
            deferred_parts.append(group)
            continue

        group["group_score_eligible"] = True
        scored = scoring.score_all(
            group,
            dim_weights=config.BOND_PLUS_DIM_WEIGHTS,
            indicators=config.BOND_PLUS_INDICATORS,
            veto_dim="B_risk",
            primary_dim="A_return",
        )
        scored_parts.append(scored)

    parts = scored_parts + deferred_parts
    if not parts:
        return work
    return pd.concat(parts, ignore_index=True, sort=False)


if __name__ == "__main__":
    rng = np.random.default_rng(18)
    rows = []
    for band_center in (0.05, 0.15, 0.25):
        for rank in range(10):
            rows.append(
                {
                    "fund_code": f"B{len(rows):03d}",
                    "equity_position": band_center,
                    "ann_return": 0.02 + rank * 0.002,
                    "campisi_alpha": 0.003 + rank * 0.0002,
                    "monthly_positive_ratio": 0.60 + rank * 0.02,
                    "target_dd_pass": 0.70 + rank * 0.025,
                    "max_drawdown": -0.05 + rank * 0.004,
                    "calmar": 0.5 + rank * 0.1,
                    "recovery_days": 100 - rank * 8,
                    "equity_contrib_ratio": 0.10 + rng.normal(0, 0.02),
                    "convertible_ratio": 0.12 + rng.normal(0, 0.02),
                    "credit_sink": 0.50 + rng.normal(0, 0.03),
                    "duration_dev": rng.normal(0, 0.05),
                    "manager_experience": 3 + rank,
                    "management_load": 100 - rank * 3,
                    "total_fee": 0.008 - rank * 0.0002,
                    "inst_ratio": 0.50,
                    "scale_yi": 10.0,
                }
            )
    result = score_bond_plus(pd.DataFrame(rows))
    print(result.groupby("equity_band").size().to_string())
    print(
        result[
            ["fund_code", "equity_band", "composite_score", "score_B_risk"]
        ]
        .sort_values(["equity_band", "composite_score"], ascending=[True, False])
        .groupby("equity_band")
        .head(2)
        .to_string(index=False)
    )
