"""债基指标层(v0.4 固收线): 净值风控指标 + Campisi 净值法 alpha + 持续性
对应 10_固收线框架v0.4 第3节 A/B 维。数据源无关:
  输入 nav(pd.Series, 累计净值) + factors(中债五因子周收益, 来自 data_bond)
  输出扁平 dict, 键对齐 config.BOND_INDICATORS(3y/5y 双窗 + 全样本 alpha/CPR)

复用 metrics.py 的窗口与风控算法(回撤/卡玛/索提诺/修复天数), 保证与权益线口径一致。
C 维(择券/信用/久期/杠杆)依赖且慢持仓工具, 不在本层计算(留待持仓数据层)。
"""
import numpy as np
import pandas as pd

import campisi
import metrics


def monthly_returns(nav: pd.Series) -> pd.Series:
    """日净值 -> 月度收益(月末对齐)"""
    r = nav.sort_index().pct_change().dropna()
    if r.empty:
        return r
    return ((1 + r).resample("ME").prod() - 1).dropna()


def monthly_positive_ratio(nav: pd.Series) -> float:
    """B5 月度正收益占比(绝对收益体验)"""
    m = monthly_returns(nav)
    if len(m) < 6:
        return np.nan
    return float((m > 0).mean())


def cpr_persistence(nav: pd.Series) -> float:
    """A2 持续性(NAFMII 胜率持续法 CPR = WW×LL / (WL×LW))
    以月度收益是否为正作为相邻期"胜/负"状态(纯绝对收益代理)。
    CPR>1 表示胜负有持续性;无连续判据时返回 NaN;上限截断防极端值破坏分位。
    注: 严格 NAFMII 口径应以"跑赢同类中位"定义胜负, 待组内截面数据接入后精化。
    """
    m = monthly_returns(nav)
    if len(m) < 12:
        return np.nan
    s = (m > 0).astype(int)
    prev = s.shift(1).dropna()
    cur = s.loc[prev.index]
    WW = int(((prev == 1) & (cur == 1)).sum())
    LL = int(((prev == 0) & (cur == 0)).sum())
    WL = int(((prev == 1) & (cur == 0)).sum())
    LW = int(((prev == 0) & (cur == 1)).sum())
    if WL == 0 or LW == 0:
        return np.nan
    return float(min((WW * LL) / (WL * LW), 10.0))


def _selection_share(reg: dict, factors: pd.DataFrame) -> float:
    """C1 择券占比(净值法代理): alpha(择券/择时残差)占 (|alpha|+|因子beta贡献|) 的比。
    近似 NAFMII"择券占超额比", 无需持仓。范围裁剪 [-1, 2]。"""
    alpha = reg.get("alpha_ann")
    betas = reg.get("betas") or {}
    if alpha is None or not betas or (isinstance(alpha, float) and np.isnan(alpha)):
        return np.nan
    fac_ann = sum(betas.get(f, 0.0) * float(factors[f].mean()) * 52
                  for f in factors.columns)
    denom = abs(alpha) + abs(fac_ann)
    if denom < 1e-9:
        return np.nan
    return float(max(-1.0, min(2.0, alpha / denom)))


def compute_bond_metrics(nav: pd.Series, factors: pd.DataFrame = None,
                         asof=None) -> dict:
    """单只债基 3y/5y 风控指标 + 全样本 Campisi alpha + CPR, 返回扁平 dict。
    factors 为 None 或空时跳过 Campisi(campisi_alpha 缺失 -> A 维按剩余权重归一)。"""
    out = {}
    for label, yrs in (("3y", 3), ("5y", 5)):
        win = metrics.window_slice(nav, yrs, asof)
        if win.empty:
            out[f"valid_{label}"] = False
            continue
        out[f"valid_{label}"] = True
        ret = metrics.to_returns(win)
        out[f"ann_return_{label}"] = metrics.annualized_return(win)
        out[f"max_drawdown_{label}"] = metrics.max_drawdown(win)
        out[f"calmar_{label}"] = metrics.calmar(win)
        out[f"sortino_{label}"] = metrics.sortino(ret)
        out[f"recovery_days_{label}"] = metrics.recovery_days(win)
        out[f"monthly_positive_ratio_{label}"] = monthly_positive_ratio(win)

    out["cpr_persistence"] = cpr_persistence(nav)

    if factors is not None and not factors.empty:
        fund_weekly = campisi.nav_to_weekly(nav)
        reg = campisi.campisi_regress(fund_weekly, factors)
        out["campisi_alpha"] = reg["alpha_ann"]
        out["campisi_r2"] = reg["r2"]
        out["campisi_conf"] = reg["confidence"]
        out["campisi_n"] = reg["n"]
        out["selection_share_bond"] = _selection_share(reg, factors)  # C1
    return out


if __name__ == "__main__":
    # 合成自测(无网络): 平稳上行净值应得正 alpha、低回撤、高月胜率
    rng = np.random.default_rng(0)
    dates = pd.bdate_range(end="2026-05-29", periods=1300)
    nav = pd.Series((1 + pd.Series(rng.normal(0.0003, 0.0015, 1300),
                                   index=dates)).cumprod(), index=dates)
    # 合成五因子
    widx = pd.bdate_range(end="2026-05-29", periods=260, freq="W-FRI")
    factors = pd.DataFrame(
        {f: rng.normal(0, 0.003, len(widx)) for f in
         ["level", "slope", "credit", "default", "convertible"]}, index=widx)
    m = compute_bond_metrics(nav, factors)
    for k, v in m.items():
        print(f"  {k}: {v}")
