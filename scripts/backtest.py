"""回测验证模块 (框架文档第6节): 评分有效性的历史检验
逻辑: 在 T 期末用"当时可知"的数据评分 -> 取前 N% 等权组合 -> 对比 T+1 期同类中位数超额
防前视: 评分函数只接收截至 asof 的净值切片; 持仓类指标须另行对齐披露滞后

升级说明 (v1.0):
- 新增分维度 + 分窗口 RankIC (IC 对象: 各维度分/各窗口原始指标 vs 前瞻组内超额收益)
- 新增 subgroups 参数: 组内超额前瞻收益 (防跨组失真)
- 新增 inception_dates 参数: 排除 asof 时点尚未成立满 3 年的基金
- dim_ic_summary(): 多期 IC 汇总 (均值 + 正IC率)
- calibration_suggest(): 由 IC 证据给出维度权重调整建议 (只写报告, 不改 config)
"""
import numpy as np
import pandas as pd

import config
import metrics
import scoring


# ---------------------------------------------------------------------------
# 核心工具
# ---------------------------------------------------------------------------

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


def _rank_ic(x: pd.Series, y: pd.Series) -> float:
    """秩相关 IC (避免 scipy 依赖)"""
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(df) < 6:
        return np.nan
    return float(df["x"].rank().corr(df["y"].rank()))


# ---------------------------------------------------------------------------
# 单期回测
# ---------------------------------------------------------------------------

def backtest_one_period(
    navs: dict,
    bench_ret: pd.Series,
    asof: str,
    top_pct: float = 0.2,
    fwd_months: int = 12,
    subgroups: dict | None = None,
    inception_dates: dict | None = None,
) -> dict:
    """单期回测: asof 评分 -> 前瞻组内超额收益对比

    参数
    ----
    navs          : fund_code -> 净值序列 (完整历史, 内部切片防前视)
    bench_ret     : 基准日收益序列
    asof          : 评估截止日 'YYYY-MM-DD'
    top_pct       : Top 组比例 (默认前20%)
    fwd_months    : 前瞻窗口 (月)
    subgroups     : fund_code -> subgroup 字符串 (组内分位/IC 用; None=全局)
    inception_dates: fund_code -> 成立日 Timestamp (排除未满3年基金)

    返回
    ----
    dict, 含 asof/n_universe/rank_ic/ic_A_return/ic_B_risk/... 等
    """
    asof_ts = pd.Timestamp(asof)
    cutoff_3y = asof_ts - pd.DateOffset(years=3)

    rows = []
    for code, nav in navs.items():
        # 防前视: 只用 asof 之前净值
        hist = nav.loc[nav.index <= asof_ts].dropna()
        if len(hist) < 60:          # 数据太少跳过
            continue
        # 排除成立不足3年的基金 (防前视: 用 inception_dates 或首条净值日期)
        inception = (inception_dates.get(code) if inception_dates else None) or hist.index[0]
        if pd.Timestamp(inception) > cutoff_3y:
            continue
        bench_hist = bench_ret.loc[bench_ret.index <= asof_ts]
        m = metrics.compute_fund_metrics(hist, bench_hist, asof=asof_ts)
        m["fund_code"] = code
        m["subgroup"] = (subgroups or {}).get(code, "__all__")
        rows.append(m)

    if not rows:
        return {"asof": asof, "error": "无有效基金"}

    df = pd.DataFrame(rows)
    # valid_3y 过滤 (compute_fund_metrics 已算)
    df = df[df.get("valid_3y", pd.Series(False, index=df.index)).astype(bool)]
    if len(df) < 10:
        return {"asof": asof, "error": f"样本不足({len(df)})"}

    # 评分 (回测只用净值可算的 A/B 维; C/D/E 无历史持仓 → 自动 provisional)
    scored = scoring.score_all(df)

    # 前瞻收益 & 组内超额
    scored["fwd_return"] = scored["fund_code"].map(
        {c: forward_return(navs[c], asof_ts, fwd_months) for c in scored["fund_code"]}
    )
    grp_med = scored.groupby("subgroup")["fwd_return"].transform("median")
    scored["fwd_excess"] = scored["fwd_return"] - grp_med

    # Top 组表现
    thresh = scored["composite_score"].quantile(1 - top_pct)
    top_mask = scored["composite_score"] >= thresh
    top_fwd = scored.loc[top_mask, "fwd_return"].mean()
    uni_fwd = scored["fwd_return"].mean()

    # 综合分 IC (对组内超额)
    ic_composite = _rank_ic(scored["composite_score"], scored["fwd_excess"])

    # 分维度 IC
    dim_ics = {}
    for dim in config.DIM_WEIGHTS:
        col = f"score_{dim}"
        if col in scored.columns:
            dim_ics[f"ic_{dim}"] = _rank_ic(scored[col], scored["fwd_excess"])

    # 分窗口 IC: A/B 维关键原始指标 3y vs 5y
    window_ics = {}
    for base in ["excess_return_ann", "monthly_win_rate",
                 "max_drawdown", "calmar", "sortino"]:
        for win in ["3y", "5y"]:
            col = f"{base}_{win}"
            if col in scored.columns:
                window_ics[f"ic_{base}_{win}"] = _rank_ic(scored[col], scored["fwd_excess"])

    return {
        "asof": asof,
        "n_universe": len(scored),
        "n_top": int(top_mask.sum()),
        "top_fwd_return": top_fwd,
        "universe_fwd_return": uni_fwd,
        "excess": top_fwd - uni_fwd,
        "rank_ic": ic_composite,
        **dim_ics,
        **window_ics,
    }


# ---------------------------------------------------------------------------
# 多期滚动
# ---------------------------------------------------------------------------

def backtest_multi_period(
    navs: dict,
    bench_ret: pd.Series,
    asof_list: list,
    top_pct: float = 0.2,
    subgroups: dict | None = None,
    inception_dates: dict | None = None,
) -> pd.DataFrame:
    """多期滚动回测汇总"""
    results = [
        backtest_one_period(navs, bench_ret, a, top_pct,
                            subgroups=subgroups, inception_dates=inception_dates)
        for a in asof_list
    ]
    df = pd.DataFrame(results)
    valid = df[~df.get("error", pd.Series("", index=df.index)).astype(bool).fillna(False)]
    if "excess" in valid.columns and len(valid):
        print(f"有效期数: {len(valid)}/{len(asof_list)} | "
              f"平均超额: {valid['excess'].mean():.2%} | "
              f"胜率: {(valid['excess'] > 0).mean():.0%} | "
              f"平均RankIC: {valid['rank_ic'].mean():.3f}")
    return df


# ---------------------------------------------------------------------------
# IC 汇总与权重校准建议
# ---------------------------------------------------------------------------

def dim_ic_summary(results_df: pd.DataFrame) -> pd.DataFrame:
    """从多期回测结果汇总各维度/指标的 IC 统计

    返回
    ----
    DataFrame: metric / mean_ic / positive_rate / n_periods / current_weight(if applicable)
    """
    ic_cols = [c for c in results_df.columns if c.startswith("ic_")]
    rows = []
    for col in ic_cols:
        s = results_df[col].dropna()
        if len(s) == 0:
            continue
        rows.append({
            "metric": col,
            "mean_ic": round(s.mean(), 4),
            "positive_rate": round((s > 0).mean(), 2),
            "n_periods": len(s),
            "ic_std": round(s.std(), 4),
        })
    summary = pd.DataFrame(rows).sort_values("mean_ic", ascending=False)
    # 标注当前维度权重
    dim_weight_map = {f"ic_{k}": v for k, v in config.DIM_WEIGHTS.items()}
    summary["current_weight"] = summary["metric"].map(dim_weight_map)
    return summary.reset_index(drop=True)


def calibration_suggest(summary_df: pd.DataFrame) -> dict:
    """由 IC 证据给出维度权重校准建议

    逻辑: 取各维度 IC 均值(仅正值), 按比例归一, 与现有权重对比。
    结果只用于报告, 不直接修改 config.py。

    返回
    ----
    dict: dim -> {"current": float, "suggested": float, "delta": float, "note": str}
    """
    dim_rows = summary_df[summary_df["metric"].str.match(r"ic_[ABCDE]_")]
    if dim_rows.empty:
        # fallback: 匹配 ic_A_return 风格
        dim_rows = summary_df[summary_df["metric"].str.startswith("ic_") &
                              ~summary_df["metric"].str.contains(r"\d")]

    ic_map = dict(zip(dim_rows["metric"], dim_rows["mean_ic"]))
    suggestions = {}
    total_pos_ic = sum(max(v, 0) for v in ic_map.values())

    for dim, cur_w in config.DIM_WEIGHTS.items():
        ic_key = f"ic_{dim}"
        ic_val = ic_map.get(ic_key, np.nan)
        if np.isnan(ic_val):
            suggested = cur_w
            note = "无IC数据, 保持原权重"
        elif total_pos_ic == 0:
            suggested = cur_w
            note = "各维IC≤0, 暂不调权(非缺数据)"
        else:
            suggested = round(max(ic_val, 0) / total_pos_ic, 3) if total_pos_ic > 0 else cur_w
            delta = suggested - cur_w
            if abs(delta) < 0.02:
                note = "与现权重接近, 无需调整"
            elif delta > 0:
                note = f"IC较强, 建议上调 {delta:+.2%}"
            else:
                note = f"IC较弱, 建议下调 {delta:+.2%}"
        suggestions[dim] = {
            "current": cur_w,
            "suggested": suggested,
            "delta": round(suggested - cur_w, 3),
            "mean_ic": round(ic_val, 4) if not np.isnan(ic_val) else None,
            "note": note,
        }
    return suggestions
