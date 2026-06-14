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


def score_dimension(df: pd.DataFrame, dim: str, indicators: dict = None) -> pd.Series:
    spec = (indicators or config.INDICATORS)[dim]
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


def score_all(df: pd.DataFrame, dim_weights: dict = None, indicators: dict = None,
              veto_dim: str = None, primary_dim: str = None) -> pd.DataFrame:
    """同类组内记分卡评分.
    默认用主动权益配置(config.DIM_WEIGHTS/INDICATORS); 传入 dim_weights/indicators
    可复用同一引擎评其它资产(如债基 config.BOND_*). 维度键须用 A/B/C/D/E 前缀。
    """
    dim_weights = dim_weights or config.DIM_WEIGHTS
    indicators = indicators or config.INDICATORS
    veto_dim = veto_dim or config.VETO_DIM
    primary_dim = primary_dim or config.PRIMARY_DIM
    out = df.copy()
    dim_cols = []
    for dim, w in dim_weights.items():
        col = f"score_{dim}"
        out[col] = score_dimension(df, dim, indicators)
        dim_cols.append((col, w))

    # 综合分: 缺维度按剩余权重归一, 同时输出覆盖率与可信度标识(防止临时分冒充五维综合分)
    def composite(row):
        num, den = 0.0, 0.0
        covered = []
        for col, w in dim_cols:
            if pd.notna(row[col]):
                num += row[col] * w
                den += w
                covered.append(col.replace("score_", "")[0])  # A/B/C/D/E
        score = num / den if den > 0 else np.nan
        return pd.Series({"composite_score": score,
                          "weight_coverage": den,
                          "covered_dims": "".join(covered)})

    out[["composite_score", "weight_coverage", "covered_dims"]] = out.apply(composite, axis=1)
    out["provisional"] = out["weight_coverage"] < config.FORMAL_MIN_WEIGHT_COVERAGE
    out["score_label"] = np.where(out["provisional"],
                                  "provisional(" + out["covered_dims"] + ")", "formal")

    # 短板与否决
    score_cols = [c for c, _ in dim_cols]
    out["shortboard"] = (out[score_cols] < config.SHORTBOARD_PCTL).any(axis=1)
    veto_col = f"score_{veto_dim}"
    out["veto"] = out[veto_col] < config.VETO_PCTL

    # 主维缺失否决: 收益维(A)整维算不出 -> 综合分只剩风险维, 会让低波动小基金虚高
    # 这类基金不得参与排名(标记 primary_missing), 单独成池
    primary_col = f"score_{primary_dim}"
    out["primary_missing"] = out[primary_col].isna()
    out.loc[out["primary_missing"], "veto"] = True

    out.loc[out["shortboard"], "composite_score"] *= 0.9  # 降档: 综合分打9折(v0.1 暂定)

    # 可投性: 规模过小或缺失 -> 容量/限购风险, 不进正式池(参考核心原则: 排名须可投)
    if "scale_yi" in out:
        out["investability_warn"] = (out["scale_yi"].fillna(0) < config.MICRO_SCALE_YI)
    else:
        out["investability_warn"] = False

    # 重点池: 须 formal(覆盖率达标) + 非否决 + 非主维缺失 + 可投
    thresh = out["composite_score"].quantile(1 - config.FOCUS_POOL_TOP_PCT)
    in_top = (out["composite_score"] >= thresh) & (~out["veto"])
    out["focus_pool"] = in_top & (~out["provisional"]) & (~out["investability_warn"])
    # 候选池: provisional 但其余条件满足(数据补齐后可升入重点池)
    out["candidate_pool"] = in_top & out["provisional"] & (~out["primary_missing"])

    # 置信度标记
    if "valid_5y" in out:
        out["low_confidence"] = ~out["valid_5y"].fillna(False)
    return out
