"""指标计算模块: 输入净值/收益序列(pandas), 输出标量指标
数据源无关 —— 上游适配层负责把 AKShare/MCP 数据整成标准格式:
  nav: pd.Series, index=DatetimeIndex(交易日), values=复权累计净值
  bench_ret: pd.Series, 日收益率, 与 nav 对齐
"""
import numpy as np
import pandas as pd

import config


def to_returns(nav: pd.Series) -> pd.Series:
    """净值 -> 日收益率"""
    return nav.sort_index().pct_change().dropna()


def annualized_return(nav: pd.Series) -> float:
    """几何年化收益"""
    nav = nav.sort_index().dropna()
    if len(nav) < 2:
        return np.nan
    total = nav.iloc[-1] / nav.iloc[0]
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    if years <= 0 or total <= 0:
        return np.nan
    return total ** (1 / years) - 1


def annualized_vol(ret: pd.Series) -> float:
    return ret.std() * np.sqrt(config.TRADING_DAYS_PER_YEAR)


def max_drawdown(nav: pd.Series) -> float:
    """最大回撤, 返回负数 (如 -0.31)"""
    nav = nav.sort_index().dropna()
    if len(nav) < 2:
        return np.nan
    dd = nav / nav.cummax() - 1
    return float(dd.min())


def recovery_days(nav: pd.Series) -> float:
    """最深回撤的修复天数(自然日); 未修复返回 np.inf"""
    nav = nav.sort_index().dropna()
    if len(nav) < 2:
        return np.nan
    cummax = nav.cummax()
    dd = nav / cummax - 1
    trough_date = dd.idxmin()
    peak_value = cummax.loc[trough_date]
    after = nav.loc[trough_date:]
    recovered = after[after >= peak_value]
    if recovered.empty:
        return np.inf
    return (recovered.index[0] - trough_date).days


def sharpe(ret: pd.Series, rf_annual: float = None) -> float:
    rf = config.RISK_FREE_ANNUAL if rf_annual is None else rf_annual
    rf_daily = (1 + rf) ** (1 / config.TRADING_DAYS_PER_YEAR) - 1
    ex = ret - rf_daily
    if ex.std() == 0 or len(ex) < 20:
        return np.nan
    return ex.mean() / ex.std() * np.sqrt(config.TRADING_DAYS_PER_YEAR)


def sortino(ret: pd.Series, rf_annual: float = None) -> float:
    rf = config.RISK_FREE_ANNUAL if rf_annual is None else rf_annual
    rf_daily = (1 + rf) ** (1 / config.TRADING_DAYS_PER_YEAR) - 1
    ex = ret - rf_daily
    downside = ex[ex < 0]
    if len(downside) < 5:
        return np.nan
    dd_std = np.sqrt((downside ** 2).mean()) * np.sqrt(config.TRADING_DAYS_PER_YEAR)
    if dd_std == 0:
        return np.nan
    return ex.mean() * config.TRADING_DAYS_PER_YEAR / dd_std


def calmar(nav: pd.Series) -> float:
    mdd = max_drawdown(nav)
    ann = annualized_return(nav)
    if pd.isna(mdd) or mdd == 0 or pd.isna(ann):
        return np.nan
    return ann / abs(mdd)


def excess_return_ann(nav: pd.Series, bench_ret: pd.Series) -> float:
    """相对基准的几何年化超额: (1+fund_ann)/(1+bench_ann)-1"""
    ret = to_returns(nav)
    aligned = pd.concat([ret, bench_ret], axis=1, join="inner").dropna()
    if len(aligned) < 60:
        return np.nan
    f_ann = (1 + aligned.iloc[:, 0]).prod() ** (config.TRADING_DAYS_PER_YEAR / len(aligned)) - 1
    b_ann = (1 + aligned.iloc[:, 1]).prod() ** (config.TRADING_DAYS_PER_YEAR / len(aligned)) - 1
    return (1 + f_ann) / (1 + b_ann) - 1


def monthly_win_rate(nav: pd.Series, bench_ret: pd.Series) -> float:
    """月度跑赢基准的占比"""
    ret = to_returns(nav)
    aligned = pd.concat([ret.rename("f"), bench_ret.rename("b")], axis=1, join="inner").dropna()
    if len(aligned) < 60:
        return np.nan
    monthly = (1 + aligned).resample("ME").prod() - 1
    monthly = monthly.dropna()
    if len(monthly) < 6:
        return np.nan
    return float((monthly["f"] > monthly["b"]).mean())


def rolling_rank_persistence(rank_series: pd.Series) -> float:
    """A2: 滚动1年同类分位的中位数. 输入: 每月末的同类分位(0-100, 高=好)"""
    s = rank_series.dropna()
    if len(s) < 6:
        return np.nan
    return float(s.median())


def window_slice(nav: pd.Series, years: float, asof=None) -> pd.Series:
    """截取截止日前 N 年的净值窗口; 不足 N*0.9 年返回空"""
    nav = nav.sort_index().dropna()
    if nav.empty:
        return nav
    end = pd.Timestamp(asof) if asof is not None else nav.index[-1]
    start = end - pd.Timedelta(days=int(years * 365.25))
    win = nav.loc[(nav.index >= start) & (nav.index <= end)]
    if win.empty:
        return win
    actual_years = (win.index[-1] - win.index[0]).days / 365.25
    if actual_years < years * 0.9:
        return nav.iloc[0:0]  # 数据不足
    return win


def compute_fund_metrics(nav: pd.Series, bench_ret: pd.Series, asof=None) -> dict:
    """对单只基金计算 3y/5y 两窗口的核心指标, 返回扁平 dict"""
    out = {}
    for label, yrs in (("3y", 3), ("5y", 5)):
        win = window_slice(nav, yrs, asof)
        if win.empty:
            out[f"valid_{label}"] = False
            continue
        out[f"valid_{label}"] = True
        ret = to_returns(win)
        b = bench_ret.loc[bench_ret.index.isin(win.index)]
        out[f"ann_return_{label}"] = annualized_return(win)
        out[f"excess_return_ann_{label}"] = excess_return_ann(win, b)
        out[f"max_drawdown_{label}"] = max_drawdown(win)
        out[f"calmar_{label}"] = calmar(win)
        out[f"sortino_{label}"] = sortino(ret)
        out[f"sharpe_{label}"] = sharpe(ret)
        out[f"monthly_win_rate_{label}"] = monthly_win_rate(win, b)
        out[f"recovery_days_{label}"] = recovery_days(win)
        out[f"vol_{label}"] = annualized_vol(ret)
    return out
