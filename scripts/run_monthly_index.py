"""权益被动指数 + ETF 双 Track 月度评价入口。"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import data_akshare as da
import data_index_equity as die
import scoring_index as si

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "data" / "index_equity_te_check.md"


def apply_te_gate(df: pd.DataFrame, track: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-index", type=int, default=None)
    parser.add_argument("--limit-etf", type=int, default=None)
    parser.add_argument("--family", default=None, help="仅运行指定指数族")
    args = parser.parse_args()

    off, etf, enhanced = die.classify_universe()
    mapping = die.build_index_map(off, etf)
    off = die.merge_map(off, mapping)
    etf = die.merge_map(etf, mapping)
    if args.family:
        off = off[off["index_family"] == args.family]
        etf = etf[etf["index_family"] == args.family]
    if args.limit_index:
        off = off.head(args.limit_index)
    if args.limit_etf:
        etf = etf.head(args.limit_etf)
    print(f"INDEX={len(off)} | ETF={len(etf)} | 指增待批2={len(enhanced)}")

    index_returns = die.build_index_returns(mapping)
    spot = die.etf_spot()
    index_metrics = die.build_offexchange_metrics(off, index_returns) if len(off) else off
    etf_metrics = die.build_etf_metrics(etf, spot, index_returns) if len(etf) else etf

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
    _report(index_metrics, etf_metrics, withdrawn, mapping)

    scored_index, deferred_index = si.score_index_equity(index_metrics)
    scored_etf, deferred_etf = si.score_etf(etf_metrics)
    out_path = Path("output") / f"score_index_etf_{date.today().isoformat()}.xlsx"
    out_path.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(out_path) as writer:
        scored_index.sort_values(
            "composite_score", ascending=False).to_excel(
                writer, sheet_name="指数榜", index=False)
        scored_etf.sort_values(
            "composite_score", ascending=False).to_excel(
                writer, sheet_name="ETF榜", index=False)
        deferred_index.to_excel(writer, sheet_name="指数待评", index=False)
        deferred_etf.to_excel(writer, sheet_name="ETF待评", index=False)
        enhanced.to_excel(writer, sheet_name="指增留批2", index=False)
    print(f"输出：{out_path}")
    print(f"指数评分={len(scored_index)} 待评={len(deferred_index)} | "
          f"ETF评分={len(scored_etf)} 待评={len(deferred_etf)} | "
          f"TE撤回={len(withdrawn)}")


if __name__ == "__main__":
    main()
