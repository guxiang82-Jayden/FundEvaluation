"""CB 专用 mini-RankIC 回测。

真实模式依赖 AkShare:
    python backtest_cb.py --limit 80

无网络自测:
    python backtest_cb.py --self-test

脚本只读 scoring_bond_cb.py, 不改权重。CB 单组内分位、防前视、前瞻
12个月 CB 组内超额收益; 输出各维 mean_ic/ic_std/t。
"""
from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

import backtest
import classify_bond
import config
import data_akshare as da
import metrics
import metrics_bond
import scoring_bond_cb as cb


def rank_ic(x: pd.Series, y: pd.Series) -> float:
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(df) < 6:
        return np.nan
    return float(df["x"].rank().corr(df["y"].rank()))


def forward_return(nav: pd.Series, asof: pd.Timestamp, months: int = 12) -> float:
    return backtest.forward_return(nav, asof, months)


def cb_universe(limit: int | None = None) -> pd.DataFrame:
    funds = da.fund_universe()
    bond_like = funds[
        funds["fund_type"].fillna("").str.contains(r"债券型|混合型-偏债", regex=True)
    ].copy()
    classified = classify_bond.classify_bond(bond_like)
    cb_funds = classified[classified["bond_subgroup"].eq("可转债基金")].copy()
    cb_funds = cb_funds.sort_values("fund_code").reset_index(drop=True)
    return cb_funds.head(limit) if limit else cb_funds


def _score_asof(
    navs: dict[str, pd.Series],
    asof: str,
    equity_ret: pd.Series | None,
) -> pd.DataFrame:
    asof_ts = pd.Timestamp(asof)
    rows = []
    hist_navs = {}
    for code, nav in navs.items():
        hist = nav.loc[nav.index <= asof_ts].dropna()
        if hist.empty:
            continue
        m = metrics_bond.compute_bond_metrics(hist, factors=None, asof=asof_ts)
        if not m.get("valid_3y", False):
            continue
        m["fund_code"] = code
        m["bond_subgroup"] = "可转债基金"
        hist_navs[code] = hist
        rows.append(m)
    if len(rows) < cb.MIN_GROUP:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    eq = equity_ret.loc[equity_ret.index <= asof_ts] if equity_ret is not None else None
    df = cb.build_cb_metrics(df, hist_navs, eq)
    return cb.score_cb(df)


def run_cb_backtest(
    navs: dict[str, pd.Series],
    asof_list: list[str],
    equity_ret: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    results = []
    for asof in asof_list:
        asof_ts = pd.Timestamp(asof)
        scored = _score_asof(navs, asof, equity_ret)
        if scored.empty:
            results.append({"asof": asof, "error": "样本不足"})
            continue
        scored["fwd_return"] = scored["fund_code"].map(
            {c: forward_return(navs[c], asof_ts, 12) for c in scored["fund_code"]}
        )
        med = scored["fwd_return"].median()
        scored["fwd_excess"] = scored["fwd_return"] - med
        row = {
            "asof": asof,
            "n_universe": int(scored["fwd_excess"].notna().sum()),
            "rank_ic": rank_ic(scored["composite_score"], scored["fwd_excess"]),
        }
        for dim in cb.CB_DIM_WEIGHTS:
            col = f"score_{dim}"
            if col in scored:
                row[f"ic_{dim}"] = rank_ic(scored[col], scored["fwd_excess"])
        results.append(row)
    res = pd.DataFrame(results)
    summary = cb_ic_summary(res)
    suggestions = cb_calibration_suggest(summary)
    return res, summary, suggestions


def cb_ic_summary(results_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in [c for c in results_df.columns if c.startswith("ic_")]:
        s = results_df[col].dropna()
        if s.empty:
            continue
        std = float(s.std())
        n = int(len(s))
        mean = float(s.mean())
        se = std / np.sqrt(n) if n and std == std and std > 0 else np.nan
        rows.append({
            "metric": col,
            "mean_ic": round(mean, 4),
            "positive_rate": round(float((s > 0).mean()), 2),
            "n_periods": n,
            "ic_std": round(std, 4) if std == std else np.nan,
            "t_stat": round(mean / se, 2) if se == se and se > 1e-12 else 0.0,
            "current_weight": cb.CB_DIM_WEIGHTS.get(col.removeprefix("ic_")),
        })
    return pd.DataFrame(rows).sort_values("mean_ic", ascending=False).reset_index(drop=True)


def cb_calibration_suggest(
    summary: pd.DataFrame,
    max_step: float = 0.10,
    t_thresh: float = 1.0,
) -> dict:
    out = {}
    for dim, cur in cb.CB_DIM_WEIGHTS.items():
        metric = f"ic_{dim}"
        row = summary[summary["metric"].eq(metric)]
        if row.empty:
            out[dim] = {"current": cur, "suggested": cur, "delta": 0.0,
                        "mean_ic": None, "t_stat": None,
                        "note": "无IC数据, 维持v0"}
            continue
        r = row.iloc[0]
        t = float(r["t_stat"])
        mean_ic = float(r["mean_ic"])
        if abs(t) < t_thresh:
            suggested = cur
            note = f"IC不显著(t={t:+.1f}), 维持v0"
        else:
            step = max_step * float(np.tanh(t / 2.0))
            suggested = float(np.clip(cur + step, 0.05, cur + max_step))
            note = f"IC显著{'为正' if t > 0 else '为负'}(t={t:+.1f}), 建议小步调整"
        out[dim] = {"current": cur, "suggested": round(suggested, 3),
                    "delta": round(suggested - cur, 3),
                    "mean_ic": round(mean_ic, 4), "t_stat": round(t, 2),
                    "note": note}
    return out


def synth_navs(n: int = 30, seed: int = 290) -> tuple[dict[str, pd.Series], pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2017-01-01", "2026-05-31")
    eq_ret = pd.Series(rng.normal(0.0002, 0.012, len(idx)), index=idx)
    navs = {}
    for i in range(n):
        beta = 0.25 + 0.5 * rng.random()
        skill = (i / n - 0.5) * 0.00025
        risk_noise = rng.normal(0, 0.004 + 0.003 * rng.random(), len(idx))
        ret = beta * eq_ret.values + skill + risk_noise
        navs[f"CB{i:03d}"] = pd.Series((1 + ret).cumprod(), index=idx)
    return navs, eq_ret


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--asof-start", type=int, default=2020)
    ap.add_argument("--asof-end", type=int, default=2024)
    args = ap.parse_args()

    asof_list = [f"{y}-12-31" for y in range(args.asof_start, args.asof_end + 1)]
    if args.self_test:
        navs, equity_ret = synth_navs()
    else:
        funds = cb_universe(args.limit)
        print(f"CB universe: {len(funds)}")
        navs = {}
        for i, code in enumerate(funds["fund_code"].astype(str)):
            try:
                navs[code] = da.fund_nav(code)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] {code} nav failed: {e}")
            if (i + 1) % 20 == 0:
                print(f"  nav {i+1}/{len(funds)} valid={len(navs)}")
        equity_ret = da.index_returns(config.DEFAULT_EQUITY_BENCHMARK)

    results, summary, suggestions = run_cb_backtest(navs, asof_list, equity_ret)
    print("== CB mini-RankIC results ==")
    print(results.round(4).to_string(index=False))
    print("\n== CB IC summary ==")
    print(summary.round(4).to_string(index=False))
    print("\n== v1 suggestions (guarded) ==")
    for dim, info in suggestions.items():
        print(
            f"{dim}: {info['current']:.0%}->{info['suggested']:.0%} "
            f"IC={info['mean_ic']} t={info['t_stat']} | {info['note']}"
        )
    print(f"\nGenerated: {date.today().isoformat()}")


if __name__ == "__main__":
    main()
