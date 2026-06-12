"""回测验证模块 (框架文档第6节): 评分有效性的历史检验
逻辑: 在 T 期末用"当时可知"的数据评分 -> 取前 N% 等权组合 -> 对比 T+1 期同类均值
防前视: 评分函数只接收截至 asof 的净值切片; 持仓类指标须另行对齐披露滞后
"""
import numpy as np
import pandas as pd

import metrics
import scoring


def forward_return(nav: pd.Series, start: pd.Timestamp, months: int = 12) -> float:
    """asof 之后 N 个月的前瞻收益"""
    nav = nav.sort_index().dropna()
    fwd = nav.loc[nav.index > start]
    if fwd.empty:
        return np.nan
    end = start + pd.DateOffset(months=months)
    fwd = fwd.loc[fwd.index <= end]
    if len(fwd) < 2:
        return np.nan
    return float(fwd.iloc[-1] / fwd.iloc[0] - 1)


def backtest_one_period(navs: dict[str, pd.Series], bench_ret: pd.Series,
                        asof: str, top_pct: float = 0.2, fwd_months: int = 12) -> dict:
    """单期回测: asof 评分 -> 前瞻收益对比
    navs: fund_code -> 净值序列(完整历史, 内部会切片防前视)"""
    asof_ts = pd.Timestamp(asof)
    rows = []
    for code, nav in navs.items():
        hist = nav.loc[nav.index <= asof_ts]
        m = metrics.compute_fund_metrics(hist, bench_ret.loc[bench_ret.index <= asof_ts])
        m["fund_code"] = code
        rows.append(m)
    df = pd.DataFrame(rows)
    df = df[df.get("valid_3y", False) == True]  # noqa: E712
    if len(df) < 10:
        return {"asof": asof, "error": "样本不足"}
    scored = scoring.score_all(df)
    thresh = scored["composite_score"].quantile(1 - top_pct)
    top = scored[scored["composite_score"] >= thresh]

    fwd_all = {c: forward_return(navs[c], asof_ts, fwd_months) for c in scored["fund_code"]}
    scored["fwd_return"] = scored["fund_code"].map(fwd_all)
    top_fwd = scored.loc[scored["fund_code"].isin(top["fund_code"]), "fwd_return"].mean()
    uni_fwd = scored["fwd_return"].mean()

    # 信息系数: 综合分与前瞻收益的秩相关 (rank后pearson, 避免scipy依赖)
    valid = scored.dropna(subset=["fwd_return", "composite_score"])
    if len(valid) > 5:
        ic = valid["composite_score"].rank().corr(valid["fwd_return"].rank())
    else:
        ic = np.nan
    return {
        "asof": asof, "n_universe": len(scored), "n_top": len(top),
        "top_fwd_return": top_fwd, "universe_fwd_return": uni_fwd,
        "excess": top_fwd - uni_fwd, "rank_ic": ic,
    }


def backtest_multi_period(navs: dict[str, pd.Series], bench_ret: pd.Series,
                          asof_list: list[str], top_pct: float = 0.2) -> pd.DataFrame:
    """多期滚动回测汇总"""
    results = [backtest_one_period(navs, bench_ret, a, top_pct) for a in asof_list]
    df = pd.DataFrame(results)
    if "excess" in df:
        print(f"平均超额: {df['excess'].mean():.2%} | 胜率: {(df['excess'] > 0).mean():.0%} | "
              f"平均RankIC: {df['rank_ic'].mean():.3f}")
    return df
