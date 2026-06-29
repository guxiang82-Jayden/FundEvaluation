"""权益被动指数 + ETF 双 Track 月度评价入口。"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import data_akshare as da
import data_index_equity as die
import scoring_enhanced as sen
import scoring_index as si

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "data" / "index_equity_te_check.md"
ENHANCED_REPORT_PATH = REPO_ROOT / "data" / "enhanced_run_report.md"


def apply_te_gate(df: pd.DataFrame, track: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    if out.empty:
        out["te_gate_withdrawn"] = pd.Series(dtype=bool)
        return out, pd.DataFrame()
    limit = 0.05 if track == "INDEX" else 0.08
    te = pd.to_numeric(out.get("tracking_error"), errors="coerce")
    bad = te > limit
    withdrawn = out.loc[bad, [
        c for c in ("fund_code", "fund_name", "track", "index_code",
                    "index_name", "tracking_error") if c in out.columns
    ]].copy()
    out.loc[bad, ["tracking_error", "info_ratio", "tracking_deviation"]] = np.nan
    out["te_gate_withdrawn"] = bad.fillna(False)
    return out, withdrawn


def _report(index_df, etf_df, withdrawn, mapping):
    mapped_by_track = mapping.groupby("track")["index_code"].agg(
        mapped=lambda x: int(x.notna().sum()), total="size")
    lines = [
        "# 权益指数/ETF TE 质检",
        f"> 生成日期：{date.today().isoformat()}",
        "",
        f"- 映射总数：{mapping['index_code'].notna().sum()}/{len(mapping)}",
        f"- 场外指数指标样本：{len(index_df)}",
        f"- ETF 指标样本：{len(etf_df)}",
    ]
    for track, row in mapped_by_track.iterrows():
        lines.append(f"- {track} 映射覆盖：{row['mapped']}/{row['total']}")
    for label, frame in (("场外指数", index_df), ("ETF", etf_df)):
        values = pd.to_numeric(frame.get("tracking_error"), errors="coerce").dropna()
        if len(values):
            lines.append(
                f"- {label} TE：min {values.min():.2%} / "
                f"median {values.median():.2%} / max {values.max():.2%}")
    premium = pd.to_numeric(
        etf_df.get("premium_discount_abs"), errors="coerce").dropna()
    if len(premium):
        lines.append(
            f"- ETF 折溢价绝对值：min {premium.min():.2%} / "
            f"median {premium.median():.2%} / max {premium.max():.2%}")
    warnings = etf_df.get(
        "investability_warn", pd.Series(False, index=etf_df.index))
    lines.append(f"- ETF 可投性预警（含规模<2亿）：{int(warnings.fillna(False).sum())}只")
    lines += ["", "## TE gate 撤回清单", ""]
    if withdrawn.empty:
        lines.append("无。")
    else:
        lines.append(withdrawn.to_markdown(index=False))
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _enhanced_report(metrics, scored, deferred, mapping):
    mapped = mapping[mapping["track"] == "ENHANCED"]
    lines = [
        "# 指数增强评价质检",
        f"> 生成日期：{date.today().isoformat()}",
        "",
        "口径：基金使用复权净值，标的使用价格指数；相对全收益指数，"
        "当前超额收益可能略高估。",
        "",
        f"- 指增映射覆盖：{mapped['index_code'].notna().sum()}/{len(mapped)}",
        f"- 本次指标样本：{len(metrics)}",
        f"- 已评分：{len(scored)}（其中 provisional "
        f"{int(scored.get('provisional', pd.Series(dtype=bool)).fillna(False).sum())}）"
        f"；待评/映射缺失：{len(deferred)}",
    ]
    for col, label in (
        ("excess_return_ann", "超额年化"),
        ("info_ratio", "信息比率"),
        ("tracking_error", "跟踪误差"),
        ("excess_win_rate", "60日滚动超额胜率"),
    ):
        values = pd.to_numeric(metrics.get(col), errors="coerce").dropna()
        if len(values):
            lines.append(
                f"- {label}：min {values.min():.2%} / "
                f"median {values.median():.2%} / max {values.max():.2%}"
                if col != "info_ratio" else
                f"- {label}：min {values.min():.2f} / "
                f"median {values.median():.2f} / max {values.max():.2f}")
    pseudo = metrics.get(
        "pseudo_enhance_warn", pd.Series(False, index=metrics.index))
    excessive = metrics.get(
        "te_excess_warn", pd.Series(False, index=metrics.index))
    lines += [
        f"- 伪增强预警（TE<1%）：{int(pseudo.fillna(False).sum())}只",
        f"- 偏离过大预警（TE>12%）：{int(excessive.fillna(False).sum())}只",
        "",
        "## 全量映射指数族分布",
        "",
        mapped["index_family"].value_counts(dropna=False).to_markdown(),
    ]
    if not scored.empty:
        sample_cols = [
            "fund_code", "fund_name", "index_family", "excess_return_ann",
            "info_ratio", "excess_win_rate", "tracking_error", "score_label",
        ]
        sample = scored.sort_values(
            "composite_score", ascending=False).head(5)
        lines += [
            "",
            "## 本次评分 Top5 抽样",
            "",
            sample[[c for c in sample_cols if c in sample]].to_markdown(
                index=False),
        ]
    ENHANCED_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ranked(writer, df, sheet_name):
    if "composite_score" in df:
        df = df.sort_values("composite_score", ascending=False)
    df.to_excel(writer, sheet_name=sheet_name, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-index", type=int, default=None)
    parser.add_argument("--limit-etf", type=int, default=None)
    parser.add_argument("--limit-enhanced", type=int, default=None)
    parser.add_argument("--only-enhanced", action="store_true")
    parser.add_argument("--family", default=None, help="仅运行指定指数族")
    args = parser.parse_args()

    off, etf, enhanced = die.classify_universe()
    mapping = die.build_index_map(off, etf, enhanced)
    off = die.merge_map(off, mapping)
    etf = die.merge_map(etf, mapping)
    enhanced = die.merge_map(enhanced, mapping)
    if args.family:
        off = off[off["index_family"] == args.family]
        etf = etf[etf["index_family"] == args.family]
        enhanced = enhanced[enhanced["index_family"] == args.family]
    if args.only_enhanced:
        off = off.iloc[0:0]
        etf = etf.iloc[0:0]
    if args.limit_index:
        off = off.head(args.limit_index)
    if args.limit_etf:
        etf = etf.head(args.limit_etf)
    if args.limit_enhanced:
        enhanced = enhanced.head(args.limit_enhanced)
    print(f"INDEX={len(off)} | ETF={len(etf)} | ENHANCED={len(enhanced)}")

    index_returns = die.build_index_returns(mapping)
    spot = die.etf_spot() if len(etf) else pd.DataFrame()
    index_metrics = die.build_offexchange_metrics(off, index_returns) if len(off) else off
    etf_metrics = die.build_etf_metrics(etf, spot, index_returns) if len(etf) else etf
    enhanced_metrics = (
        die.build_enhanced_metrics(enhanced, index_returns)
        if len(enhanced) else enhanced)

    # 整表费率缓存；失败留空，不中断工具卡。
    if len(etf_metrics):
        try:
            fees = da.fund_fee_table(etf_metrics["fund_code"].tolist())
            etf_metrics = etf_metrics.merge(
                fees[["fund_code", "total_fee"]], on="fund_code", how="left",
                suffixes=("", "_fee"))
            if "total_fee_fee" in etf_metrics:
                etf_metrics["total_fee"] = etf_metrics.get(
                    "total_fee").combine_first(etf_metrics["total_fee_fee"])
                etf_metrics = etf_metrics.drop(columns=["total_fee_fee"])
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] ETF fee table failed: {exc}")

    index_metrics, withdrawn_index = apply_te_gate(index_metrics, "INDEX")
    etf_metrics, withdrawn_etf = apply_te_gate(etf_metrics, "ETF")
    withdrawn = pd.concat([withdrawn_index, withdrawn_etf], ignore_index=True)
    if not args.only_enhanced:
        _report(index_metrics, etf_metrics, withdrawn, mapping)

    scored_index, deferred_index = si.score_index_equity(index_metrics)
    scored_etf, deferred_etf = si.score_etf(etf_metrics)
    scored_enhanced, deferred_enhanced = sen.score_enhanced(enhanced_metrics)
    _enhanced_report(
        enhanced_metrics, scored_enhanced, deferred_enhanced, mapping)
    out_path = Path("output") / f"score_index_etf_{date.today().isoformat()}.xlsx"
    out_path.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(out_path) as writer:
        _write_ranked(writer, scored_index, "指数榜")
        _write_ranked(writer, scored_etf, "ETF榜")
        _write_ranked(writer, scored_enhanced, "指增榜")
        deferred_index.to_excel(writer, sheet_name="指数待评", index=False)
        deferred_etf.to_excel(writer, sheet_name="ETF待评", index=False)
        deferred_enhanced.to_excel(writer, sheet_name="指增待评", index=False)
    print(f"输出：{out_path}")
    print(f"指数评分={len(scored_index)} 待评={len(deferred_index)} | "
          f"ETF评分={len(scored_etf)} 待评={len(deferred_etf)} | "
          f"指增评分={len(scored_enhanced)} 待评={len(deferred_enhanced)} | "
          f"TE撤回={len(withdrawn)}")


if __name__ == "__main__":
    main()
