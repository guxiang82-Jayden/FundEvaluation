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


def build_bond_metrics_table(codes: list, factors: pd.DataFrame, asof=None):
    """返回 (指标宽表 df, navs dict)。navs 供固收+ 的 build_bond_plus_metrics 复用。"""
    rows = []
    navs = {}
    for i, code in enumerate(codes):
        try:
            nav = da.fund_nav(code)
            navs[code] = nav
            m = metrics_bond.compute_bond_metrics(nav, factors, asof=asof)
            m["fund_code"] = code
            rows.append(m)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {code} bond metrics failed: {e}")
        if (i + 1) % 50 == 0:
            print(f"  metrics {i+1}/{len(codes)}")
    return pd.DataFrame(rows), navs


def derive_de_columns(df: pd.DataFrame) -> pd.DataFrame:
    """从 build_meta_table 字段派生 D/E 维评分输入列(对齐 config.BOND_INDICATORS)。"""
    if "manager_career_days" in df:
        df["manager_experience"] = pd.to_numeric(
            df["manager_career_days"], errors="coerce") / 365.25
    if "manager_total_aum" in df:
        df["management_load"] = pd.to_numeric(df["manager_total_aum"], errors="coerce")
    # total_fee 已由 fund_meta 提供; inst_ratio 暂无源(E2 缺 -> 按剩余权重归一)
    return df


# 固收+ 分流: 这些子组走 BOND_PLUS 记分卡(权益中枢分组), 其余走纯债 BOND 记分卡
BOND_PLUS_SUBGROUPS = {"偏债混合/固收+", "混合债券二级"}


def split_tracks(std_df: pd.DataFrame):
    """按 bond_subgroup 分流为 (纯债track, 固收+track)。"""
    is_plus = std_df["bond_subgroup"].isin(BOND_PLUS_SUBGROUPS)
    return std_df[~is_plus].copy(), std_df[is_plus].copy()


def _score_grouped(std_df: pd.DataFrame, group_col: str,
                   dim_weights: dict, indicators: dict) -> pd.DataFrame:
    """组内(>=5只)分位评分, 复用 scoring.score_all。"""
    parts = []
    for _, gdf in std_df.groupby(group_col):
        if len(gdf) < 5:
            continue
        parts.append(scoring.score_all(
            gdf, dim_weights=dim_weights, indicators=indicators,
            veto_dim="B_risk", primary_dim="A_return"))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def score_bond_track(std_bond: pd.DataFrame) -> pd.DataFrame:
    """纯债 track: 子组内 BOND 记分卡(<10只回退纯债综合)。"""
    if std_bond.empty:
        return std_bond
    df = std_bond.copy()
    counts = df["bond_subgroup"].value_counts()
    small = counts[counts < 10].index
    df["effective_group"] = df["bond_subgroup"].where(
        ~df["bond_subgroup"].isin(small), "纯债综合")
    scored = _score_grouped(df, "effective_group",
                            config.BOND_DIM_WEIGHTS, config.BOND_INDICATORS)
    if not scored.empty:
        scored["scorecard"] = "BOND"
    return scored


def score_plus_track(std_plus: pd.DataFrame, navs: dict = None,
                     equity_index_ret: pd.Series = None) -> pd.DataFrame:
    """固收+ track: 用 scoring_bond_plus(权益中枢分组 + 目标回撤达标率/股债贡献分解);
    模块未就绪或缺 equity_position 时, 用纯债 BOND 记分卡兜底。"""
    if std_plus.empty:
        return std_plus
    try:
        import scoring_bond_plus
    except ImportError:
        scoring_bond_plus = None
    has_eq = ("equity_position" in std_plus.columns
              and std_plus["equity_position"].notna().any())
    if scoring_bond_plus is not None and hasattr(scoring_bond_plus, "score_bond_plus") and has_eq:
        df = std_plus.copy()
        # 用净值 + 权益指数补 target_dd_pass / equity_contrib_ratio(缺则该指标自动跳过)
        if navs and hasattr(scoring_bond_plus, "build_bond_plus_metrics"):
            df = scoring_bond_plus.build_bond_plus_metrics(df, navs, equity_index_ret)
        scored = scoring_bond_plus.score_bond_plus(df)
        if scored is not None and not scored.empty:
            scored["scorecard"] = "BOND_PLUS"
        return scored
    reason = "scoring_bond_plus 未就绪" if scoring_bond_plus is None else "缺 equity_position"
    print(f"  [固收+] {reason} -> 暂用纯债记分卡兜底(待条件满足自动切 BOND_PLUS)")
    df = std_plus.copy()
    df["effective_group"] = df["bond_subgroup"]
    scored = _score_grouped(df, "effective_group",
                            config.BOND_DIM_WEIGHTS, config.BOND_INDICATORS)
    if not scored.empty:
        scored["scorecard"] = "BOND(fallback)"
    return scored


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
    mt, navs = build_bond_metrics_table(codes, factors, asof=args.asof)
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

    # 固收+ 股债贡献分解需权益指数收益(默认基准); 失败则 equity_contrib 置空
    try:
        equity_index_ret = da.index_returns(config.DEFAULT_EQUITY_BENCHMARK)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 权益指数取数失败, equity_contrib 跳过: {e}")
        equity_index_ret = None

    print("== L2 评分(分流: 纯债 BOND / 固收+ BOND_PLUS) ==")
    bond_std, plus_std = split_tracks(standard)
    print(f"  纯债 track: {len(bond_std)} 只 | 固收+ track: {len(plus_std)} 只")
    scored_bond = score_bond_track(bond_std)
    scored_plus = score_plus_track(plus_std, navs=navs, equity_index_ret=equity_index_ret)
    scored = pd.concat([x for x in (scored_bond, scored_plus) if not x.empty],
                       ignore_index=True)
    if scored.empty:
        print("无足量子组可评分, 退出。")
        return

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
    if "scorecard" in scored:
        print(f"记分卡分布: {scored['scorecard'].value_counts().to_dict()}")
    print(f"否决: {scored['veto'].sum()} | 短板: {scored['shortboard'].sum()}")
    cols = [c for c in ["fund_code", "fund_name", "composite_score",
                        "score_A_return", "score_B_risk", "campisi_alpha",
                        "scale_yi", "scorecard", "effective_group"] if c in main_board.columns]
    print("\n可投主榜 Top10(仅预览, Excel 存全部):")
    print(main_board.head(10)[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
