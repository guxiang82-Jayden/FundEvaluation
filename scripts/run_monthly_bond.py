"""债基月度跑批主入口(v0.4 固收线): L0分类 -> L1初筛 -> 指标(净值+Campisi) -> L2评分 -> Excel
用法: python run_monthly_bond.py [--asof 2026-05-31] [--limit 100]
镜像 run_monthly.py(主动权益线), 复用同一评分引擎(scoring.score_all + config.BOND_*)。
依赖 akshare 环境(用户机); 沙箱无网络, 用 test_bond_pipeline.py 跑合成数据。
"""
import argparse
import os
from datetime import date

import pandas as pd

import campisi
import cdim_bond
import classify_bond
import config
import data_akshare as da
import data_bond
import metrics_bond
import scoring
import screening_bond


def bond_universe() -> pd.DataFrame:
    """全市场债券型 + 偏债混合(东财口径), 列对齐 classify_bond 需求。"""
    import akshare as ak
    u = ak.fund_name_em().rename(columns={
        "基金代码": "fund_code", "基金简称": "fund_name", "基金类型": "fund_type"})
    mask = u["fund_type"].fillna("").str.contains(r"债券型|混合型-偏债", regex=True)
    return u[mask].drop_duplicates("fund_code").copy()


def build_bond_metrics_table(codes: list, factors: pd.DataFrame, asof=None) -> pd.DataFrame:
    rows = []
    for i, code in enumerate(codes):
        try:
            nav = da.fund_nav(code)
            m = metrics_bond.compute_bond_metrics(nav, factors, asof=asof)
            m["fund_code"] = code
            rows.append(m)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {code} bond metrics failed: {e}")
        if (i + 1) % 50 == 0:
            print(f"  metrics {i+1}/{len(codes)}")
    return pd.DataFrame(rows)


def derive_de_columns(df: pd.DataFrame) -> pd.DataFrame:
    """从 build_meta_table 字段派生 D/E 维评分输入列(对齐 config.BOND_INDICATORS)。"""
    if "manager_career_days" in df:
        df["manager_experience"] = pd.to_numeric(
            df["manager_career_days"], errors="coerce") / 365.25
    if "manager_total_aum" in df:
        df["management_load"] = pd.to_numeric(df["manager_total_aum"], errors="coerce")
    # total_fee 已由 fund_meta 提供; inst_ratio 暂无源(E2 缺 -> 按剩余权重归一)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default=None, help="评估截止日 YYYY-MM-DD, 默认最新")
    ap.add_argument("--limit", type=int, default=None, help="限制基金数(调试用)")
    args = ap.parse_args()

    print("== L0 债基 universe + 同类组分类 ==")
    funds = classify_bond.classify_bond(bond_universe())
    print(f"债基组(粗): {len(funds)} 只")
    print(classify_bond.subgroup_stats(funds).to_string())
    codes = funds["fund_code"].tolist()
    if args.limit:
        codes = codes[: args.limit]

    print("== 元数据(规模/成立/经理/费率) ==")
    meta = da.build_meta_table(codes)

    print("== 中债指数因子(Campisi 五因子) ==")
    factors = campisi.build_factors(data_bond.bond_index_weekly_returns())
    print(f"  可用因子: {list(factors.columns)} ({len(factors.columns)})")

    print("== 指标计算(净值风控 + Campisi alpha) ==")
    mt = build_bond_metrics_table(codes, factors, asof=args.asof)
    df = (funds.merge(meta.drop(columns=["fund_name"], errors="ignore"),
                      on="fund_code", how="right")
          .merge(mt, on="fund_code", how="inner"))
    df = derive_de_columns(df)
    df = cdim_bond.load_cdim_bond(df)   # C维(信用/久期/杠杆)+排雷/杠杆筛

    print("== L1 债基初筛 ==")
    df = screening_bond.apply_screening_bond(df)
    for w in df.attrs.get("screening_warnings", []):
        print(f"  [screen] {w}")
    standard = df[df["channel"] == "standard"].copy()
    print(f"标准通道: {len(standard)} | 剔除: {df['screened_out'].sum()}")

    print("== L2 评分(子组内分位, 债基记分卡) ==")
    counts = standard["bond_subgroup"].value_counts()
    small = counts[counts < 10].index
    standard["effective_group"] = standard["bond_subgroup"].where(
        ~standard["bond_subgroup"].isin(small), "债基综合")
    print(f"子组数: {standard['effective_group'].nunique()} (含<10只回退 {len(small)} 组)")

    parts = []
    for g, gdf in standard.groupby("effective_group"):
        if len(gdf) < 5:
            continue  # 极小组不评分
        parts.append(scoring.score_all(
            gdf, dim_weights=config.BOND_DIM_WEIGHTS,
            indicators=config.BOND_INDICATORS,
            veto_dim="B_risk", primary_dim="A_return"))
    if not parts:
        print("无足量子组可评分, 退出。")
        return
    scored = pd.concat(parts, ignore_index=True)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(
        config.OUTPUT_DIR,
        f"score_bond_{args.asof or date.today().isoformat()}.xlsx")
    for d in (scored, df):
        d["fund_code"] = d["fund_code"].astype(str).str.zfill(6)
    scored_sorted = scored.sort_values("composite_score", ascending=False)
    warn = scored_sorted.get("investability_warn",
                             pd.Series(False, index=scored_sorted.index))
    main_board = scored_sorted[~warn.fillna(False)]
    micro_board = scored_sorted[warn.fillna(False)]
    with pd.ExcelWriter(out_path) as xw:
        main_board.to_excel(xw, sheet_name="可投主榜", index=False)
        micro_board.to_excel(xw, sheet_name="小微观察区", index=False)
        df[df["screened_out"]].to_excel(xw, sheet_name="剔除清单", index=False)

    if not args.limit:
        import shutil
        archive_dir = os.path.join("..", "archive")
        os.makedirs(archive_dir, exist_ok=True)
        shutil.copy(out_path, os.path.join(archive_dir, os.path.basename(out_path)))
        print(f"已归档 → archive/{os.path.basename(out_path)}")

    print(f"输出: {out_path}")
    print(f"可投主榜: {len(main_board)} | 小微观察区: {len(micro_board)}")
    print(f"正式重点池: {scored['focus_pool'].sum()} 只 | "
          f"候选池(provisional): {scored.get('candidate_pool', pd.Series(dtype=bool)).sum()} 只")

    print("\n== 质检 ==")
    if "score_label" in scored:
        print(f"评分可信度: {scored['score_label'].value_counts().to_dict()}")
        print(f"维度权重覆盖率均值: {scored['weight_coverage'].mean():.0%}")
    if "campisi_conf" in scored:
        print(f"Campisi 置信度分布: {scored['campisi_conf'].value_counts().to_dict()}")
    print(f"否决: {scored['veto'].sum()} | 短板: {scored['shortboard'].sum()}")
    cols = [c for c in ["fund_code", "fund_name", "composite_score",
                        "score_A_return", "score_B_risk", "campisi_alpha",
                        "scale_yi", "effective_group"] if c in main_board.columns]
    print("\n可投主榜 Top10(仅预览, Excel 存全部):")
    print(main_board.head(10)[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
