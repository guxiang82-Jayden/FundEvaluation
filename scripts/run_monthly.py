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


def build_metrics_table(codes: list, index_rets: dict, bench_texts: dict, asof=None) -> pd.DataFrame:
    """bench_texts: fund_code -> 业绩基准字符串(来自雪球基本信息), 逐基金解析合成"""
    rows = []
    for i, code in enumerate(codes):
        try:
            nav = da.fund_nav(code)
            bench_ret, bench_note = bm.get_benchmark_returns(bench_texts.get(code, ""), index_rets)
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
    codes = funds["fund_code"].tolist()
    if args.limit:
        codes = codes[: args.limit]

    print("== 元数据(规模/成立/基准/仓位, 约0.4s/只) ==")
    meta = da.build_meta_table(codes)
    bench_texts = (dict(zip(meta["fund_code"], meta["benchmark_text"].fillna("")))
                   if "benchmark_text" in meta else {})

    print("== 指数行情 ==")
    index_rets = da.load_all_index_returns_v2()

    print("== 指标计算 ==")
    mt = build_metrics_table(codes, index_rets, bench_texts, asof=args.asof)
    df = funds.merge(meta.drop(columns=["fund_name"], errors="ignore"),
                     on="fund_code", how="right").merge(mt, on="fund_code", how="inner")

    print("== L1 初筛 ==")
    # 当前可用规则: N1/N2(规模) N3(成立) + 主题豁免; N4-N8 数据源待补自动跳过
    df = screening.apply_screening(df)
    standard = df[df["channel"] == "standard"]
    print(f"标准通道: {len(standard)} | 观察: {(df['channel']=='theme_observation').sum()} | 剔除: {df['screened_out'].sum()}")

    print("== L2 评分 ==")
    scored = scoring.score_all(standard)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(config.OUTPUT_DIR, f"score_active_equity_{args.asof or date.today().isoformat()}.xlsx")
    # 代码列强制6位文本, 防Excel数值化丢前导零
    for d in (scored, df):
        d["fund_code"] = d["fund_code"].astype(str).str.zfill(6)
    with pd.ExcelWriter(out_path) as xw:
        scored.sort_values("composite_score", ascending=False).to_excel(xw, sheet_name="评分", index=False)
        df[df["channel"] == "theme_observation"].to_excel(xw, sheet_name="主题观察池", index=False)
        df[df["screened_out"]].to_excel(xw, sheet_name="剔除清单", index=False)
    print(f"输出: {out_path}")
    print(f"重点池: {scored['focus_pool'].sum()} 只")

    # ---- 质检汇总 ----
    print("\n== 质检 ==")
    print(f"代码6位占比: {(scored['fund_code'].str.len() == 6).mean():.0%}")
    if "valid_5y" in scored:
        print(f"5y数据齐占比: {scored['valid_5y'].mean():.1%}")
    if "bench_note" in scored:
        print(f"基准: {scored['bench_note'].str.split(':').str[0].value_counts().to_dict()}")
    print(f"否决: {scored['veto'].sum()} | 短板: {scored['shortboard'].sum()}")
    excluded = df[df["screened_out"]]
    if not excluded.empty:
        print(f"剔除原因: {excluded['screen_reasons'].str.split(';').explode().value_counts().to_dict()}")
    cols = [c for c in ["fund_code", "fund_name", "composite_score", "score_A_return", "score_B_risk", "scale_yi"] if c in scored.columns]
    print("\nTop10:")
    print(scored.nlargest(10, "composite_score")[cols].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
