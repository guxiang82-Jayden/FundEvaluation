"""债基月度跑批主入口(v0.4 固收线): L0分类 -> L1初筛 -> 指标(净值+Campisi) -> 4-Track评分 -> Excel
用法: python run_monthly_bond.py [--asof 2026-05-31] [--limit 100]
4-Track(2026-06-14 真跑质检后重定义):
  BOND(纯债: 短期/中长期纯债, 组内分位) / BOND1(一级债: 混合债券一级)
  PLUS(固收+: 混合二级/偏债, 权益中枢分档, scoring_bond_plus)
  CB(可转债: scoring_bond_cb 专用卡, 组内>=5 评分) / BOND_INDEX(指数型-固收/QDII工具型, 待工具卡 -> 暂不评分单列观察)
依赖 akshare(用户机); 沙箱无网络, 用 test_bond_pipeline.py / test_bond_tracks.py 跑合成数据。
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


# ---------- Track 映射(4-Track + 工具型, 真跑质检 P0) ----------
PURE_SUBGROUPS = {"短期纯债", "中长期纯债"}        # -> BOND 纯债(组内分位)
BOND1_SUBGROUPS = {"混合债券一级"}                  # -> BOND1 一级债
PLUS_SUBGROUPS = {"混合债券二级", "偏债混合/固收+"}  # -> PLUS 固收+(权益中枢分档)
CB_SUBGROUPS = {"可转债基金"}                        # -> CB 可转债(scoring_bond_cb 专用卡, v0先验)
MIN_GROUP = 5   # 同类组内可评分最小样本; 不足则 defer(不跨异质组回退)
# universe 类型正则: QDII 仅纳"含债"子类(P0修复: 原 bare QDII 错纳股票/商品/另类 75.8%)
BOND_TYPE_RE = r"债券型|混合型-偏债|指数型-固收|QDII.*债"
BOND_INDEX_TYPE_RE = r"指数型-固收|QDII.*债"  # 工具型/海外单列 track


def bond_universe() -> pd.DataFrame:
    """主动境内债基 + 指数固收/QDII(单列工具型) universe。
    P0: 份额合并(复用 data_akshare.merge_share_classes); 先排除同业存单等特殊策略。"""
    import akshare as ak
    u = ak.fund_name_em().rename(columns={
        "基金代码": "fund_code", "基金简称": "fund_name", "基金类型": "fund_type"})
    u["fund_code"] = u["fund_code"].astype(str).str.zfill(6)
    mask = u["fund_type"].fillna("").str.contains(BOND_TYPE_RE, regex=True)
    u = u[mask].copy()
    # 先排除同业存单等特殊策略(后续再细分)
    u = u[~u["fund_name"].fillna("").str.contains("同业存单", regex=False)]
    u = u.drop_duplicates("fund_code")
    return da.merge_share_classes(u)   # 份额合并 -> 一产品一行


def assign_track(df: pd.DataFrame) -> pd.DataFrame:
    """按 fund_type + bond_subgroup 打 track 标签。指数固收/QDII 优先单列 BOND_INDEX。"""
    out = df.copy()
    ft = out["fund_type"].fillna("")
    sg = out.get("bond_subgroup", pd.Series("", index=out.index)).fillna("")
    track = pd.Series("BOND", index=out.index, dtype="object")  # 默认纯债
    track[sg.isin(BOND1_SUBGROUPS)] = "BOND1"
    track[sg.isin(PLUS_SUBGROUPS)] = "PLUS"
    track[sg.isin(CB_SUBGROUPS)] = "CB"
    # 工具型/海外优先(覆盖 subgroup 误判: 指数固收常按名落入纯债子组)
    track[ft.str.contains(BOND_INDEX_TYPE_RE, regex=True)] = "BOND_INDEX"
    out["track"] = track
    return out


def build_bond_metrics_table(codes: list, factors: pd.DataFrame, asof=None):
    """返回 (指标宽表 df, navs dict)。navs 供固收+ build_bond_plus_metrics 复用。"""
    rows, navs = [], {}
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
    """从 build_meta_table 字段派生 D/E 维评分输入列。"""
    if "manager_career_days" in df:
        df["manager_experience"] = pd.to_numeric(
            df["manager_career_days"], errors="coerce") / 365.25
    if "manager_total_aum" in df:
        df["management_load"] = pd.to_numeric(df["manager_total_aum"], errors="coerce")
    return df


def screening_coverage(df: pd.DataFrame) -> dict:
    """P1: 初筛字段真实非空覆盖率(字段存在但大量为空比缺列更隐蔽)。"""
    cov = {}
    for col in ("scale_yi", "fund_age_years", "manager_changed_recent",
                "leverage_ratio", "neg_alert", "inst_ratio"):
        if col in df.columns:
            cov[col] = float(df[col].notna().mean())
        else:
            cov[col] = 0.0
    return cov


def score_subgroups(std: pd.DataFrame, dim_weights: dict, indicators: dict,
                    label: str, group_col: str = "bond_subgroup") -> pd.DataFrame:
    """组内(>=MIN_GROUP)分位评分; 不足则 defer(不跨异质组回退)。tag scorecard=label。"""
    if std.empty:
        return pd.DataFrame()
    parts = []
    for _, gdf in std.groupby(group_col):
        if len(gdf) < MIN_GROUP:
            continue  # defer, 不并入其它组
        parts.append(scoring.score_all(
            gdf, dim_weights=dim_weights, indicators=indicators,
            veto_dim="B_risk", primary_dim="A_return"))
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["scorecard"] = label
    return out


def score_plus_track(std_plus: pd.DataFrame, navs: dict = None,
                     equity_index_ret: pd.Series = None) -> pd.DataFrame:
    """固收+ track: scoring_bond_plus(权益中枢分档); 模块缺失/缺 equity_position 兜底纯债卡。"""
    if std_plus.empty:
        return pd.DataFrame()
    try:
        import scoring_bond_plus
    except ImportError:
        scoring_bond_plus = None
    has_eq = ("equity_position" in std_plus.columns
              and std_plus["equity_position"].notna().any())
    if scoring_bond_plus is not None and hasattr(scoring_bond_plus, "score_bond_plus") and has_eq:
        df = std_plus.copy()
        if navs and hasattr(scoring_bond_plus, "build_bond_plus_metrics"):
            df = scoring_bond_plus.build_bond_plus_metrics(df, navs, equity_index_ret)
        scored = scoring_bond_plus.score_bond_plus(df)
        if scored is not None and not scored.empty:
            scored["scorecard"] = "BOND_PLUS"
        return scored
    reason = "scoring_bond_plus 未就绪" if scoring_bond_plus is None else "缺 equity_position"
    print(f"  [固收+] {reason} -> 暂用纯债记分卡兜底")
    scored = score_subgroups(std_plus, config.BOND_DIM_WEIGHTS, config.BOND_INDICATORS,
                             "BOND(fallback)")
    return scored


def score_cb_track(std_cb: pd.DataFrame, navs: dict = None,
                   equity_index_ret: pd.Series = None) -> pd.DataFrame:
    """可转债 track: scoring_bond_cb(权益beta+转债仓位+风控, v0先验)。<MIN_GROUP defer。"""
    if std_cb.empty:
        return pd.DataFrame()
    try:
        import scoring_bond_cb
    except ImportError:
        return pd.DataFrame()
    df = std_cb.copy()
    if navs and hasattr(scoring_bond_cb, "build_cb_metrics"):
        df = scoring_bond_cb.build_cb_metrics(df, navs, equity_index_ret)
    return scoring_bond_cb.score_cb(df)  # 已 tag scorecard="CB"


def score_index_track(std_index: pd.DataFrame) -> pd.DataFrame:
    """工具型 track: scoring_bond_index(Phase A: 成本/规模/运作分位; 跟踪误差/指数代表性待 Phase B)。
    指数固收 / QDII债 分子组评分, <MIN_GROUP defer; 已 tag scorecard='BOND_INDEX'。模块缺失则跳过。"""
    if std_index.empty:
        return pd.DataFrame()
    try:
        import scoring_bond_index
    except ImportError:
        return pd.DataFrame()
    return scoring_bond_index.score_index(std_index)


# scorecard -> Excel sheet 名
_SHEET_MAP = {
    "BOND": "纯债主榜", "BOND1": "一级债榜",
    "BOND_PLUS": "固收+榜", "BOND(fallback)": "固收+榜",
    "CB": "可转债榜", "BOND_INDEX": "工具型榜",
}


def write_score_workbook(out_path: str, main_board: pd.DataFrame,
                         not_scored: pd.DataFrame, micro_board: pd.DataFrame,
                         df_all: pd.DataFrame) -> dict:
    """多 sheet 输出: 各 track 主榜 + 待评(可转债/工具型/小样本) + 小微观察区 + 剔除清单。"""
    counts = {}
    with pd.ExcelWriter(out_path) as xw:
        if "scorecard" in main_board.columns:
            written = {}
            for sc, sheet in _SHEET_MAP.items():
                sub = main_board[main_board["scorecard"] == sc]
                if sub.empty:
                    continue
                written.setdefault(sheet, []).append(sub)
            for sheet, subs in written.items():
                board = pd.concat(subs, ignore_index=True).sort_values(
                    "composite_score", ascending=False)
                board.to_excel(xw, sheet_name=sheet, index=False)
                counts[sheet] = len(board)
        elif not main_board.empty:
            main_board.to_excel(xw, sheet_name="可投主榜", index=False)
            counts["可投主榜"] = len(main_board)
        # 待评 track(可转债/工具型/小样本 defer): 按 track 分表
        if not not_scored.empty and "track" in not_scored.columns:
            defer_sheets = {"CB": "可转债待评", "BOND_INDEX": "工具型待评"}
            for tk, sheet in defer_sheets.items():
                sub = not_scored[not_scored["track"] == tk]
                if not sub.empty:
                    sub.to_excel(xw, sheet_name=sheet, index=False)
                    counts[sheet] = len(sub)
            rest = not_scored[~not_scored["track"].isin(defer_sheets)]
            if not rest.empty:
                rest.to_excel(xw, sheet_name="小样本待评", index=False)
                counts["小样本待评"] = len(rest)
        micro_board.to_excel(xw, sheet_name="小微观察区", index=False)
        df_all[df_all["screened_out"]].to_excel(xw, sheet_name="剔除清单", index=False)
        counts["小微观察区"] = len(micro_board)
        counts["剔除清单"] = int(df_all["screened_out"].sum())
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default=None, help="评估截止日 YYYY-MM-DD, 默认最新")
    ap.add_argument("--limit", type=int, default=None, help="限制基金数(调试用)")
    args = ap.parse_args()

    print("== L0 债基 universe(份额合并) + 同类组分类 ==")
    funds = classify_bond.classify_bond(bond_universe())
    print(f"债基组(份额合并后): {len(funds)} 只")
    print(classify_bond.subgroup_stats(funds).to_string())
    codes = funds["fund_code"].tolist()
    if args.limit:
        codes = codes[: args.limit]

    print("== 元数据(规模/成立/经理/费率) ==")
    meta = da.build_meta_table(codes)

    print("== 中债指数因子(Campisi) ==")
    factors = campisi.build_factors(data_bond.bond_index_weekly_returns())
    print(f"  可用因子: {list(factors.columns)} ({len(factors.columns)})")

    print("== 指标计算(净值风控 + Campisi alpha) ==")
    mt, navs = build_bond_metrics_table(codes, factors, asof=args.asof)
    df = (funds.merge(meta.drop(columns=["fund_name"], errors="ignore"),
                      on="fund_code", how="right")
          .merge(mt, on="fund_code", how="inner"))
    df = derive_de_columns(df)
    df = cdim_bond.load_cdim_bond(df)
    df = assign_track(df)

    print("== L1 债基初筛 ==")
    df = screening_bond.apply_screening_bond(df)
    for w in df.attrs.get("screening_warnings", []):
        print(f"  [screen] {w}")
    cov = screening_coverage(df)
    print("  初筛字段非空覆盖率: " + ", ".join(f"{k}={v:.0%}" for k, v in cov.items()))
    standard = df[df["channel"] == "standard"].copy()
    print(f"标准通道: {len(standard)} | 剔除: {df['screened_out'].sum()}")
    print(f"  track 分布: {standard['track'].value_counts().to_dict()}")

    # 固收+ 股债贡献需权益指数
    try:
        equity_index_ret = da.index_returns(config.DEFAULT_EQUITY_BENCHMARK)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 权益指数取数失败, equity_contrib 跳过: {e}")
        equity_index_ret = None

    print("== L2 评分(4-Track) ==")
    parts = [
        score_subgroups(standard[standard["track"] == "BOND"],
                        config.BOND_DIM_WEIGHTS, config.BOND_INDICATORS, "BOND"),
        score_subgroups(standard[standard["track"] == "BOND1"],
                        config.BOND_DIM_WEIGHTS, config.BOND_INDICATORS, "BOND1"),
        score_plus_track(standard[standard["track"] == "PLUS"], navs, equity_index_ret),
        score_cb_track(standard[standard["track"] == "CB"], navs, equity_index_ret),
        score_index_track(standard[standard["track"] == "BOND_INDEX"]),
    ]
    parts = [p for p in parts if not p.empty]
    scored = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    scored_codes = set(scored["fund_code"]) if not scored.empty else set()
    not_scored = standard[~standard["fund_code"].isin(scored_codes)].copy()
    print(f"  已评分: {len(scored)} | 待评(可转债/工具型/小样本): {len(not_scored)}")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(config.OUTPUT_DIR,
                            f"score_bond_{args.asof or date.today().isoformat()}.xlsx")
    for d in (scored, df, not_scored):
        if not d.empty:
            d["fund_code"] = d["fund_code"].astype(str).str.zfill(6)
    if scored.empty:
        main_board = micro_board = scored
    else:
        scored_sorted = scored.sort_values("composite_score", ascending=False)
        warn = scored_sorted.get("investability_warn",
                                 pd.Series(False, index=scored_sorted.index)).fillna(False)
        main_board, micro_board = scored_sorted[~warn], scored_sorted[warn]
    sheet_counts = write_score_workbook(out_path, main_board, not_scored, micro_board, df)

    if not args.limit:
        import shutil
        archive_dir = os.path.join("..", "archive")
        os.makedirs(archive_dir, exist_ok=True)
        shutil.copy(out_path, os.path.join(archive_dir, os.path.basename(out_path)))
        print(f"已归档 → archive/{os.path.basename(out_path)}")

    print(f"输出: {out_path}  sheets={sheet_counts}")
    print("\n== 质检 ==")
    if "score_label" in scored:
        print(f"评分可信度: {scored['score_label'].value_counts().to_dict()}")
    if "scorecard" in scored:
        print(f"记分卡分布: {scored['scorecard'].value_counts().to_dict()}")
    if "campisi_conf" in scored:
        print(f"Campisi 置信度: {scored['campisi_conf'].value_counts().to_dict()}")
    if not scored.empty:
        print(f"否决: {scored['veto'].sum()} | 短板: {scored['shortboard'].sum()}")
        cols = [c for c in ["fund_code", "fund_name", "composite_score", "scorecard",
                            "score_A_return", "score_B_risk", "campisi_alpha", "scale_yi"]
                if c in main_board.columns]
        print("\n主榜 Top10(仅预览):")
        print(main_board.head(10)[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
