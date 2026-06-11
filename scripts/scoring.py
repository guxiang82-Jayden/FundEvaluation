"""L2 评分引擎: 同类组内分位记分卡
输入: 指标宽表 DataFrame (一行一基金, 列=指标原始值)
输出: 维度分(0-100)、综合分、短板/否决标记
数据源无关; 指标缺失时该指标在维度内按剩余权重归一
"""
import numpy as np
import pandas as pd

import config


def winsorize(s: pd.Series) -> pd.Series:
    lo, hi = s.quantile(config.WINSORIZE[0]), s.quantile(config.WINSORIZE[1])
    return s.clip(lo, hi)


def pctl_score(s: pd.Series, direction: int) -> pd.Series:
    """同类组内百分位 0-100. direction: 1 高=好, -1 低=好, 0 U型(距中位数近=好)"""
    s = winsorize(s.astype(float))
    if direction == 0:
        dist = (s - s.median()).abs()
        return (1 - dist.rank(pct=True)) * 100
    r = s.rank(pct=True) * 100
    return r if direction == 1 else 100 - r


def blend_windows(df: pd.DataFrame, base: str) -> pd.Series:
    """3y/5y 窗口合成: 5y*0.6 + 3y*0.4; 无5y用3y"""
    c3, c5 = f"{base}_3y", f"{base}_5y"
    if c5 in df and c3 in df:
        w5, w3 = config.WINDOW_WEIGHTS["5y"], config.WINDOW_WEIGHTS["3y"]
        blended = df[c5] * w5 + df[c3] * w3
        return blended.fillna(df[c3])
    if c3 in df:
        return df[c3]
    if base in df:
        return df[base]
    return pd.Series(np.nan, index=df.index)


# 指标取值的特殊预处理
_PREP = {
    "max_drawdown": lambda s: s.abs() * -1,   # 统一为"越大越好"前先确保负值语义: 回撤浅=值大
    "recovery_days": lambda s: s.replace(np.inf, s[s != np.inf].max() * 2 if (s != np.inf).any() else np.nan),
}


def score_dimension(df: pd.DataFrame, dim: str) -> pd.Series:
    spec = config.INDICATORS[dim]
    parts, weights = [], []
    for ind, (w, direction) in spec.items():
        raw = blend_windows(df, ind)
        if raw.isna().all():
            continue
        if ind in _PREP:
            raw = _PREP[ind](raw)
        # max_drawdown 经预处理后(负值, 浅回撤大) 方向仍为 1
        parts.append(pctl_score(raw, direction) * w)
        weights.append(w)
    if not parts:
        return pd.Series(np.nan, index=df.index)
    return sum(parts) / sum(weights)


def score_all(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    dim_cols = []
    for dim, w in config.DIM_WEIGHTS.items():
        col = f"score_{dim}"
        out[col] = score_dimension(df, dim)
        dim_cols.append((col, w))

    # 综合分: 缺维度按剩余权重归一
    def composite(row):
        num, den = 0.0, 0.0
        for col, w in dim_cols:
            if pd.notna(row[col]):
                num += row[col] * w
                den += w
        return num / den if den > 0 else np.nan

    out["composite_score"] = out.apply(composite, axis=1)

    # 短板与否决
    score_cols = [c for c, _ in dim_cols]
    out["shortboard"] = (out[score_cols] < config.SHORTBOARD_PCTL).any(axis=1)
    veto_col = f"score_{config.VETO_DIM}"
    out["veto"] = out[veto_col] < config.VETO_PCTL
    out.loc[out["shortboard"], "composite_score"] *= 0.9  # 降档: 综合分打9折(v0.1 暂定)

    # 重点池
    thresh = out["composite_score"].quantile(1 - config.FOCUS_POOL_TOP_PCT)
    out["focus_pool"] = (out["composite_score"] >= thresh) & (~out["veto"])

    # 置信度标记
    if "valid_5y" in out:
        out["low_confidence"] = ~out["valid_5y"].fillna(False)
    return out
