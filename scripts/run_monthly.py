"""月度跑批主入口: L0 分类 -> L1 初筛 -> L2 评分 -> Excel 输出
用法: python run_monthly.py [--asof 2026-05-31] [--limit 100]
v0.1: 主动权益组; 依赖 akshare 环境(用户机器), 沙箱内只能跑合成数据测试
"""
import argparse
import os
from datetime import date

import pandas as pd

import benchmark as bm
import config
import data_akshare as da
import metrics
import screening
import scoring


def build_metrics_table(funds: pd.DataFrame, index_rets: dict, asof=None, limit=None) -> pd.DataFrame:
    rows = []
    codes = funds["fund_code"].tolist()
    if limit:
        codes = codes[:limit]
    for i, code in enumerate(codes):
        try:
            nav = da.fund_nav(code)
            # v0.1: 基准统一用默认(中证800); v0.2 接入逐基金基准解析
            bench_ret, bench_note = bm.get_benchmark_returns("", index_rets)
            m = metrics.compute_fund_metrics(nav, bench_ret, asof=asof)
            m["fund_code"] = code
            m["bench_note"] = bench_note
            rows.append(m)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {code} metrics failed: {e}")
        if (i + 1) % 50 == 0:
            print(f"  metrics {i+1}/{len(codes)}")
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default=None, help="评估截止日 YYYY-MM-DD, 默认最新")
    ap.add_argument("--limit", type=int, default=None, help="限制基金数(调试用)")
    args = ap.parse_args()

    print("== L0 同类组 ==")
    funds = da.active_equity_universe()
    print(f"主动权益组(粗): {len(funds)} 只")

    print("== 指数行情 ==")
    index_rets = da.load_all_index_returns()

    print("== 指标计算 ==")
    mt = build_metrics_table(funds, index_rets, asof=args.asof, limit=args.limit)
    df = funds.merge(mt, on="fund_code", how="inner")

    print("== L1 初筛 ==")
    # v0.1: 元数据接口未完成, 初筛仅跑可用规则; 完整规则待 data_akshare.fund_meta
    df = screening.apply_screening(df)
    standard = df[df["channel"] == "standard"]
    print(f"标准通道: {len(standard)} | 观察: {(df['channel']=='theme_observation').sum()} | 剔除: {df['screened_out'].sum()}")

    print("== L2 评分 ==")
    scored = scoring.score_all(standard)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(config.OUTPUT_DIR, f"score_active_equity_{args.asof or date.today().isoformat()}.xlsx")
    with pd.ExcelWriter(out_path) as xw:
        scored.sort_values("composite_score", ascending=False).to_excel(xw, sheet_name="评分", index=False)
        df[df["channel"] == "theme_observation"].to_excel(xw, sheet_name="主题观察池", index=False)
        df[df["screened_out"]].to_excel(xw, sheet_name="剔除清单", index=False)
    print(f"输出: {out_path}")
    print(f"重点池: {scored['focus_pool'].sum()} 只")


if __name__ == "__main__":
    main()
