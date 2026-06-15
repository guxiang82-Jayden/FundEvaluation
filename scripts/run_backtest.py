"""回测驱动脚本: 主动权益分维度 RankIC 回测 + 权重校准报告
用法: python run_backtest.py [--limit 300] [--out data/backtest_calibration_report.md]

说明:
- 取规模前 N 只主动权益基金的完整历史净值
- 在 2019-2024 年末 6 个 asof 点滚动评估
- 输出分维度 IC 均值 + 长短窗口对比 + 权重校准建议 (写入 md 报告)
- 【限制】回测仅用净值可算的 A/B 维; C/D/E 含持仓类指标需披露日期对齐, 本版暂不纳入
"""
import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

# 本地模块
import backtest as bt
import config
import data_akshare as da


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _load_navs(codes: list, history_cutoff) -> tuple:
    """批量加载净值 + 失败原因分桶诊断(P0修复: 原写死2014门槛错杀大量基金)。
    history_cutoff: 基金净值起点须 <= 此日期, 才能至少覆盖一个回测期的窗口;
    更早 asof 由 backtest_one_period 内 valid_3y/inception 逐期把关。
    返回 (navs dict, diag dict)。"""
    cutoff = pd.Timestamp(history_cutoff)
    navs = {}
    diag = {"requested": len(codes), "fetch_fail": 0, "too_short": 0, "valid": 0}
    n = len(codes)
    for i, code in enumerate(codes):
        try:
            nav = da.fund_nav(code)
        except Exception:         # noqa: BLE001
            diag["fetch_fail"] += 1
            continue
        if nav is None or len(nav) == 0:
            diag["fetch_fail"] += 1
            continue
        if nav.index.min() > cutoff:
            diag["too_short"] += 1
            continue
        navs[code] = nav
        if (i + 1) % 50 == 0:
            print(f"  净值加载 {i+1}/{n} (有效 {len(navs)})", flush=True)
    diag["valid"] = len(navs)
    return navs, diag


def _load_inception_dates(meta: pd.DataFrame) -> dict:
    """fund_code -> 成立日 Timestamp"""
    if "found_date" in meta.columns:
        return dict(zip(meta["fund_code"], pd.to_datetime(meta["found_date"], errors="coerce")))
    return {}


def _write_report(
    results: pd.DataFrame,
    summary: pd.DataFrame,
    suggestions: dict,
    out_path: str,
    n_universe: int,
    asof_list: list,
    diag: dict = None,
):
    lines = [
        "# 回测校准报告 — 主动权益评分权重",
        f"> 生成时间: {date.today().isoformat()}  ",
        f"> 回测基金数: {n_universe} 只 (规模前 N 只主动权益)  ",
        f"> 评估节点: {', '.join(asof_list)}  ",
        f"> 前瞻窗口: 12 个月  ",
        "",
        "## ⚠️ 限制说明",
        "评分口径: **同类组(backbone)内分位**(匹配生产); IC 对组内前瞻超额。",
        "本次回测**仅使用净值可算的 A/B 维指标**, C/D/E 维含持仓/经理等数据"
        "须对齐披露滞后, 本版暂不纳入。C/D/E 维权重建议仅供参考, 应在获得足够历史"
        "快照后单独校准。",
        "",
        "## 数据诊断(样本构造, P0修复后)",
        "",
        (f"- 请求 {diag['requested']} / 抓取失败 {diag['fetch_fail']} / "
         f"历史太短(成立晚)被筛 {diag['too_short']} / **最终有效 {diag['valid']}**"
         if diag else "- (无诊断数据)"),
        "",
        "## 1. 多期滚动总览",
        "",
    ]

    # 总览表
    overview_cols = ["asof", "n_universe", "n_top", "excess", "rank_ic"]
    ov = results[[c for c in overview_cols if c in results.columns]].copy()
    if "excess" in ov:
        ov["excess"] = ov["excess"].map(lambda x: f"{x:.2%}" if pd.notna(x) else "—")
    if "rank_ic" in ov:
        ov["rank_ic"] = ov["rank_ic"].map(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
    lines.append(ov.to_markdown(index=False))
    lines.append("")

    valid = results.dropna(subset=["rank_ic"])
    if len(valid):
        lines += [
            f"- **平均超额**: {valid['excess'].mean():.2%}",
            f"- **胜率**: {(valid['excess'] > 0).mean():.0%}",
            f"- **平均综合分 RankIC**: {valid['rank_ic'].mean():.3f}",
            "",
        ]

    # 分维度 IC
    lines += [
        "## 2. 分维度 RankIC (vs 组内前瞻超额收益)",
        "",
        "| 指标 | 均值IC | 正IC期占比 | 有效期数 | 当前权重 |",
        "|------|--------|-----------|---------|---------|",
    ]
    for _, row in summary.iterrows():
        w = f"{row['current_weight']:.0%}" if pd.notna(row.get("current_weight")) else "—"
        lines.append(
            f"| {row['metric']} | {row['mean_ic']:.4f} | "
            f"{row['positive_rate']:.0%} | {row['n_periods']} | {w} |"
        )
    lines.append("")

    # 长短窗口对比
    window_rows = summary[summary["metric"].str.contains(r"_3y$|_5y$")]
    if not window_rows.empty:
        lines += [
            "## 3. 长短窗口预测力对比 (5y vs 3y)",
            "",
            "核心问题: 较长历史 vs 近期数据, 谁对未来12个月更有预测力?",
            "",
            "| 指标 | 均值IC | 正IC率 |",
            "|------|--------|-------|",
        ]
        for _, row in window_rows.iterrows():
            lines.append(
                f"| {row['metric']} | {row['mean_ic']:.4f} | {row['positive_rate']:.0%} |"
            )

        # 3y vs 5y 对比汇总
        bases = set()
        for m in window_rows["metric"]:
            for suf in ("_3y", "_5y"):
                if m.endswith(suf):
                    bases.add(m[:-3])
        lines += ["", "**窗口胜负小结:**"]
        for base in sorted(bases):
            r3 = summary[summary["metric"] == f"ic_{base}_3y"]["mean_ic"]
            r5 = summary[summary["metric"] == f"ic_{base}_5y"]["mean_ic"]
            if r3.empty or r5.empty:
                continue
            v3, v5 = r3.values[0], r5.values[0]
            winner = "5y更强" if v5 > v3 else "3y更强" if v3 > v5 else "相当"
            lines.append(f"- `{base}`: 3y={v3:.4f}, 5y={v5:.4f} → **{winner}**")
        lines.append("")

    # 权重校准建议
    lines += [
        "## 4. 维度权重校准建议",
        "",
        "> 方法: 各维度正 IC 均值归一 → 建议权重; 仅 A/B 有 IC 证据, C/D/E 暂延用先验。",
        "",
        "| 维度 | 当前权重 | 建议权重 | 变化 | 均值IC | 说明 |",
        "|------|---------|---------|-----|--------|-----|",
    ]
    for dim, info in suggestions.items():
        cur = f"{info['current']:.0%}"
        sug = f"{info['suggested']:.0%}"
        dlt = f"{info['delta']:+.0%}" if info["delta"] != 0 else "—"
        ic_s = f"{info['mean_ic']:.4f}" if info["mean_ic"] is not None else "无数据"
        lines.append(f"| {dim} | {cur} | {sug} | {dlt} | {ic_s} | {info['note']} |")

    lines += [
        "",
        "## 5. 后续动作",
        "",
        "- [ ] 评审上述建议, 确认 A/B 维权重调整方向合理",
        "- [ ] 待 C/D/E 维历史快照积累(2–3 个存档期)后, 补做 C/D/E 维 IC 校准",
        "- [ ] 5y vs 3y 若证据明确, 修改 `config.WINDOW_WEIGHTS`",
        "- [ ] 最终拍板后, 修改 `config.DIM_WEIGHTS` / `WINDOW_WEIGHTS` 并重跑全量",
    ]

    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n报告已写入: {out_path}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300, help="取规模前 N 只基金")
    ap.add_argument("--asof-start", type=int, default=2019, help="最早评估年(年末)")
    ap.add_argument("--asof-end", type=int, default=2024, help="最晚评估年(年末)")
    ap.add_argument("--min-history-years", type=int, default=3, help="评分窗口所需最短历史(年)")
    ap.add_argument("--out", default="data/backtest_calibration_report.md", help="报告路径")
    args = ap.parse_args()

    asof_list = [f"{y}-12-31" for y in range(args.asof_start, args.asof_end + 1)]
    load_cutoff = pd.Timestamp(f"{args.asof_end}-12-31") - pd.DateOffset(years=args.min_history_years)

    print("== 获取主动权益全量 ==")
    funds = da.active_equity_universe()
    meta = da.build_meta_table(funds["fund_code"].tolist()[:args.limit * 2])  # 取多些备用
    # 按规模降序取前 N 只
    if "scale_yi" in meta.columns:
        meta = meta.sort_values("scale_yi", ascending=False)
    codes = meta["fund_code"].tolist()[:args.limit]
    print(f"目标基金: {len(codes)} 只 | 历史门槛: 净值起点需 ≤ {load_cutoff.date()}")

    print("== 批量加载净值(约需 2–5 分钟) ==")
    navs, diag = _load_navs(codes, load_cutoff)
    print(f"  数据诊断: 请求{diag['requested']} / 抓取失败{diag['fetch_fail']} / "
          f"历史太短{diag['too_short']} / 有效{diag['valid']}")

    print("== 加载基准行情 ==")
    index_rets = da.load_all_index_returns_v2()
    bench_ret = index_rets.get(config.DEFAULT_EQUITY_BENCHMARK, pd.Series(dtype=float))

    inception_dates = _load_inception_dates(meta)

    # 同类组分类(backbone 粗组, 历史样本更稳): 让回测按生产口径"组内分位打分"
    try:
        import classify
        ep = (meta.set_index("fund_code")["equity_position"]
              if "equity_position" in meta.columns else None)
        cls = classify.classify(meta, equity_position=ep)
        subgroups = dict(zip(cls["fund_code"], cls["backbone"]))
        print(f"  同类组(backbone)分布: {pd.Series(subgroups).value_counts().to_dict()}")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 分类失败, 退回全市场打分: {e}")
        subgroups = None

    print("== 滚动回测(同类组内打分) ==")
    results = bt.backtest_multi_period(
        navs=navs,
        bench_ret=bench_ret,
        asof_list=asof_list,
        top_pct=0.2,
        subgroups=subgroups,
        inception_dates=inception_dates,
    )

    # 汇总 & 建议
    summary = bt.dim_ic_summary(results)
    suggestions = bt.calibration_suggest(summary)

    print("\n== IC 汇总 ==")
    print(summary.to_string(index=False))

    print("\n== 权重校准建议 ==")
    for dim, info in suggestions.items():
        print(f"  {dim}: {info['current']:.0%} → {info['suggested']:.0%}  ({info['note']})")

    _write_report(results, summary, suggestions, args.out, len(navs), asof_list, diag=diag)


if __name__ == "__main__":
    main()
