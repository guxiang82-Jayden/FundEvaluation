"""净值法 Campisi 五因子归因(v0.4 固收线核心算法)
依据: 华宝《净值Campisi业绩归因》+ 海通/长江债基归因研报
口径: 周频债基收益 ~ 五因子(均久期中性正交), 残差=alpha

五因子(华宝口径):
  level       久期      : 中债国债总财富指数收益
  slope       期限结构  : 中债中短期 − 中债长期(久期中性)
  credit      信用利差  : 中债企业债AAA − 中债国开债(久期中性)
  default     违约      : 中债高收益企业债 − 中债企业债AAA(久期中性)
  convertible 可转债    : 中债转债 − 中债国债(等比例多空)

判据: 纯债 R²>0.7 → alpha 可信; 含权(二级债基/固收+) R²<0.5 → 标低置信度, 须辅持仓

约束: 不对系数做单纯形约束(债基因子可正可负, 与RBSA不同), 用 OLS 即可;
      但因子已两两正交化构造, 多重共线性低。
"""
import numpy as np
import pandas as pd

# 因子 → 中债指数代码(AKShare/且慢取数; 待实现取数层时核对)
FACTOR_INDICES = {
    "level": ["中债国债总财富"],
    "slope": ["中债中短期", "中债长期"],          # 多空
    "credit": ["中债企业债AAA", "中债国开债"],     # 多空
    "default": ["中债高收益企业债", "中债企业债AAA"],
    "convertible": ["中债转债", "中债国债总财富"],
}

R2_PURE_BOND = 0.70    # 纯债 alpha 可信门槛
R2_LOW_CONF = 0.50     # 低于此 → 含权, alpha 不可信


def build_factors(index_weekly_ret: dict) -> pd.DataFrame:
    """由中债指数周收益构造五因子(久期中性由调用方在指数层面保证, 此处简化为差值)
    index_weekly_ret: 指数名 -> 周收益序列
    返回: DataFrame(index=周, columns=5因子)
    ⚠️ 久期中性的精确实现需各指数久期数据动态调权; v0.4-1 先用等权差值近似, v0.4-2 精化
    """
    def g(name):
        return index_weekly_ret.get(name, pd.Series(dtype=float))

    factors = {}
    if "中债国债总财富" in index_weekly_ret:
        factors["level"] = g("中债国债总财富")
    if {"中债中短期", "中债长期"} <= index_weekly_ret.keys():
        factors["slope"] = g("中债中短期") - g("中债长期")
    if {"中债企业债AAA", "中债国开债"} <= index_weekly_ret.keys():
        factors["credit"] = g("中债企业债AAA") - g("中债国开债")
    if {"中债高收益企业债", "中债企业债AAA"} <= index_weekly_ret.keys():
        factors["default"] = g("中债高收益企业债") - g("中债企业债AAA")
    if {"中债转债", "中债国债总财富"} <= index_weekly_ret.keys():
        factors["convertible"] = g("中债转债") - g("中债国债总财富")
    return pd.DataFrame(factors).dropna()


def campisi_regress(fund_weekly_ret: pd.Series, factors: pd.DataFrame,
                    annualize_weeks: int = 52) -> dict:
    """OLS 回归: fund_ret ~ 五因子 + 截距. 截距(周)年化为 alpha
    返回: {alpha_ann, r2, betas(dict), n, confidence}"""
    df = pd.concat([fund_weekly_ret.rename("y"), factors], axis=1, join="inner").dropna()
    if len(df) < 26:  # 至少半年周频
        return {"alpha_ann": np.nan, "r2": np.nan, "betas": {}, "n": len(df),
                "confidence": "insufficient"}
    y = df["y"].values
    X = df.drop(columns="y").values
    Xd = np.column_stack([np.ones(len(X)), X])  # 加截距
    # 最小二乘
    coef, *_ = np.linalg.lstsq(Xd, y, rcond=None)
    resid = y - Xd @ coef
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - np.sum(resid ** 2) / ss_tot if ss_tot > 0 else np.nan
    alpha_weekly = coef[0]
    alpha_ann = (1 + alpha_weekly) ** annualize_weeks - 1
    betas = dict(zip(df.columns.drop("y"), coef[1:]))
    conf = ("high" if r2 >= R2_PURE_BOND else
            "low(含权?辅持仓)" if r2 < R2_LOW_CONF else "medium")
    return {"alpha_ann": float(alpha_ann), "r2": float(r2),
            "betas": {k: float(v) for k, v in betas.items()},
            "n": len(df), "confidence": conf}


def nav_to_weekly(nav: pd.Series) -> pd.Series:
    """日净值 → 周收益(周五对齐)"""
    nav = nav.sort_index().dropna()
    weekly_nav = nav.resample("W-FRI").last().dropna()
    return weekly_nav.pct_change().dropna()
