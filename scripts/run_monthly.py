"""月度跑批主入口: L0 分类 -> L1 初筛 -> L2 评分 -> Excel 输出
用法: python run_monthly.py [--asof 2026-05-31] [--limit 100]
v0.1: 主动权益组; 依赖 akshare 环境(用户机器), 沙箱内只能跑合成数据测试
"""
import argparse
import os
from datetime import date

import pandas as pd

import benchmark as bm
import classify
import config
import data_akshare as da
import metrics
import screening
import scoring


def build_metrics_table(codes: list, index_rets: dict, bench_texts: dict, asof=None) -> pd.DataFrame:
    """bench_texts: fund_code -> 业绩基准字符串(来自雪球基本信息), 逐基金解析合成"""
    rows = []
    default_ret = index_rets.get(config.DEFAULT_EQUITY_BENCHMARK)
    for i, code in enumerate(codes):
        try:
            nav = da.fund_nav(code)
            bench_ret, bench_note = bm.get_benchmark_returns(bench_texts.get(code, ""), index_rets)
            # 根因修复: 合成基准与基金近3年窗口重叠不足(债券/港股成分数据短)-> 回退默认基准
            if default_ret is not None and not nav.empty:
                win = nav.loc[nav.index >= nav.index[-1] - pd.Timedelta(days=365 * 3)]
                overlap = bench_ret.index.isin(win.index).sum() if not bench_ret.empty else 0
                if overlap < max(60, int(len(win) * 0.5)):
                    bench_ret = default_ret
                    bench_note = f"fallback_overlap:{config.DEFAULT_EQUITY_BENCHMARK}"
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

    # 任期补充表(且慢MCP会话内生成, 当前覆盖候选池632只; 无文件自动跳过)
    tenure_path = os.path.join("data", "manager_tenure.csv")
    if os.path.exists(tenure_path):
        tn = pd.read_csv(tenure_path, dtype={"fund_code": str})
        tn["fund_code"] = tn["fund_code"].str.zfill(6)
        tmap = tn.set_index("fund_code")
        hit = meta["fund_code"].isin(tmap.index)
        meta.loc[hit, "tenure_years"] = meta.loc[hit, "fund_code"].map(tmap["max_tenure_years"])
        meta.loc[hit, "manager_changed_recent"] = meta.loc[hit, "fund_code"].map(
            tmap["recent_manager_added"])
        print(f"  任期补充(且慢源): 命中 {hit.sum()}/{len(meta)} 只 -> N4/N5 生效")

    print("== 指数行情 ==")
    index_rets = da.load_all_index_returns_v2()

    print("== 指标计算 ==")
    mt = build_metrics_table(codes, index_rets, bench_texts, asof=args.asof)
    df = funds.merge(meta.drop(columns=["fund_name"], errors="ignore"),
                     on="fund_code", how="right").merge(mt, on="fund_code", how="inner")

    print("== L0.5 同类组细分 ==")
    ep = (meta.set_index("fund_code")["equity_position"]
          if "equity_position" in meta.columns else None)
    df = classify.classify(df, equity_position=ep)
    counts = df["subgroup"].value_counts()
    small = counts[counts < 10].index
    df["effective_group"] = df["subgroup"].where(~df["subgroup"].isin(small), df["backbone"])
    print(f"子组数: {df['effective_group'].nunique()} (含<10只回退 {len(small)} 组)")
    print(df["effective_group"].value_counts().head(8).to_string())

    print("== L1 初筛 ==")
    df = screening.apply_screening(df)
    standard = df[df["channel"] == "standard"]
    print(f"标准通道: {len(standard)} | 观察: {(df['channel']=='theme_observation').sum()} | 剔除: {df['screened_out'].sum()}")

    print("== L2 评分(子组内分位) ==")
    parts = []
    for g, gdf in standard.groupby("effective_group"):
        if len(gdf) < 5:
            continue  # 极小组不评分(进观察)
        parts.append(scoring.score_all(gdf))
    scored = pd.concat(parts, ignore_index=True)

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
    print(f"正式重点池: {scored['focus_pool'].sum()} 只 | 候选池(provisional): {scored.get('candidate_pool', pd.Series(dtype=bool)).sum()} 只")

    # ---- 质检汇总 ----
    print("\n== 质检 ==")
    if "score_label" in scored:
        print(f"评分可信度: {scored['score_label'].value_counts().to_dict()}")
        print(f"维度权重覆盖率均值: {scored['weight_coverage'].mean():.0%}")
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
