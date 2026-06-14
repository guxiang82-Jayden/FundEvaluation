"""滚动复盘机制(核心原则落地: 评分→复盘→迭代)
依据: research/基金评估-核心原则_过去与未来.md | 路线图 07 第五节

输入: archive/ 下两期及以上评分存档(xlsx) + 真实净值(算区间前瞻收益)
输出: 季度复盘报告 md + 复盘指标

复盘四问:
  Q1 命中率: 上期 Top20% 本期是否跑赢同类中位数?(目标 >55%)
  Q2 规则有效性: 被各负面规则剔除的基金, 后续表现是否确实偏弱?(剔得对)
  Q3 RankIC: 综合分/各维度分 vs 后续区间收益的秩相关, 是否仍正且稳?
  Q4 可比性break: 规模突变/换将等事件发生而上期评分未反映?

双线: kind="equity"(score_active_equity_*) / "bond"(score_bond_* 多榜合并, 带 scorecard)。
前瞻收益: 优先真实区间净值(forward_returns 或 nav_func 计算); 无则用下期存档代理(标注不可靠)。
脚本独立可跑(真实净值需 akshare; 合成测试见 test_review.py)。
"""
import glob
import os
import re

import numpy as np
import pandas as pd

# 各 kind 的存档文件前缀与榜单 sheet
_ARCHIVE_SPEC = {
    "equity": ("score_active_equity_", ["可投主榜"]),
    "bond": ("score_bond_", ["纯债主榜", "一级债榜", "固收+榜", "可投主榜"]),
}
_GROUP_COLS = ["effective_group", "bond_subgroup", "subgroup", "scorecard"]


def _group_col(df: pd.DataFrame):
    for c in _GROUP_COLS:
        if c in df.columns:
            return c
    return None


def load_archives(archive_dir: str = "../archive", kind: str = "equity") -> dict:
    """读某条线的所有评分存档 -> {date_str: df}。债基线合并多榜单 sheet。"""
    prefix, board_sheets = _ARCHIVE_SPEC[kind]
    out = {}
    for f in sorted(glob.glob(os.path.join(archive_dir, f"{prefix}*.xlsx"))):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
        if not m:
            continue
        try:
            xl = pd.ExcelFile(f)
            use = [s for s in board_sheets if s in xl.sheet_names] or [xl.sheet_names[0]]
            parts = [xl.parse(s, dtype={"fund_code": str}) for s in use]
            df = pd.concat(parts, ignore_index=True)
            df["fund_code"] = df["fund_code"].astype(str).str.zfill(6)
            df = df.drop_duplicates("fund_code", keep="first")
            out[m.group(1)] = df
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 读取 {os.path.basename(f)} 失败: {e}")
    return out


def load_excluded(archive_dir: str, kind: str, date: str) -> pd.DataFrame:
    """读某期存档的'剔除清单'sheet(供 Q2 规则有效性)。"""
    prefix, _ = _ARCHIVE_SPEC[kind]
    files = glob.glob(os.path.join(archive_dir, f"{prefix}{date}*.xlsx"))
    if not files:
        return pd.DataFrame()
    try:
        xl = pd.ExcelFile(files[0])
        if "剔除清单" not in xl.sheet_names:
            return pd.DataFrame()
        df = xl.parse("剔除清单", dtype={"fund_code": str})
        if "fund_code" in df.columns:
            df["fund_code"] = df["fund_code"].astype(str).str.zfill(6)
        return df
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def forward_returns_from_nav(codes, start, end, nav_func) -> pd.Series:
    """真实区间前瞻收益: 各基金 (end净值 / start净值 − 1)。
    nav_func(code) -> 累计净值 Series(DatetimeIndex)。用 <=日期的最后一条对齐。"""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    out = {}
    for c in codes:
        try:
            nav = nav_func(c)
        except Exception:  # noqa: BLE001
            continue
        if nav is None or len(nav) == 0:
            continue
        nav = nav.sort_index().dropna()
        a = nav.loc[nav.index <= start]
        b = nav.loc[nav.index <= end]
        if a.empty or b.empty or a.iloc[-1] == 0:
            continue
        out[c] = float(b.iloc[-1] / a.iloc[-1] - 1)
    return pd.Series(out, dtype=float)


def compute_forward_from_next(prev: pd.DataFrame, nxt: pd.DataFrame) -> pd.Series:
    """代理前瞻(不可靠, 仅无真实净值时兜底): 用下期存档 excess_return_ann_3y 作延续表现代理。"""
    for col in ("excess_return_ann_3y", "ann_return_3y", "composite_score"):
        if col in nxt.columns:
            return nxt.set_index("fund_code")[col]
    return pd.Series(dtype=float)


def hit_rate(prev: pd.DataFrame, fwd: pd.Series, top_pct: float = 0.2) -> dict:
    """Q1: 上期 Top 组本期跑赢同类中位数比例(同类按组列分组)。"""
    p = prev.copy()
    p["fwd"] = p["fund_code"].map(fwd)
    v = p.dropna(subset=["fwd", "composite_score"])
    if len(v) < 10:
        return {"error": f"样本不足({len(v)})"}
    gc = _group_col(v)
    med = v.groupby(gc)["fwd"].transform("median") if gc else v["fwd"].median()
    v = v.assign(beat=v["fwd"] > med)
    thr = v["composite_score"].quantile(1 - top_pct)
    top = v[v["composite_score"] >= thr]
    return {
        "top_hit_rate": float(top["beat"].mean()),
        "universe_hit_rate": float(v["beat"].mean()),
        "top_n": int(len(top)), "n": int(len(v)),
        "top_avg_fwd": float(top["fwd"].mean()),
        "universe_avg_fwd": float(v["fwd"].mean()),
        "group_col": gc,
    }


def rank_ic(prev: pd.DataFrame, fwd: pd.Series, min_n: int = 10) -> dict:
    """Q3: 综合分/各维度分 vs 前瞻收益的秩相关。"""
    p = prev.copy()
    p["fwd"] = p["fund_code"].map(fwd)
    v = p.dropna(subset=["fwd"])
    if len(v) < min_n:
        return {"error": f"样本不足({len(v)})"}
    out = {}
    for col in ["composite_score", "score_A_return", "score_B_risk",
                "score_C_attribution", "score_D_manager", "score_E_operation"]:
        if col in v and v[col].notna().sum() >= min_n:
            vv = v.dropna(subset=[col])
            out[col] = float(vv[col].rank().corr(vv["fwd"].rank()))
    return out


def rule_effectiveness(excluded: pd.DataFrame, fwd: pd.Series, min_n: int = 5) -> dict:
    """Q2: 被各负面规则剔除的基金后续表现(剔得对则偏弱)。兼容权益N* 与债基FN*。"""
    if excluded is None or excluded.empty or "screen_reasons" not in excluded.columns:
        return {}
    ex = excluded.copy()
    ex["fwd"] = ex["fund_code"].map(fwd)
    reasons = (ex["screen_reasons"].dropna().str.split(";").explode().str.strip())
    out = {}
    for rule in sorted(set(reasons) - {""}):
        sub = ex[ex["screen_reasons"].str.contains(re.escape(rule), na=False)].dropna(subset=["fwd"])
        if len(sub) >= min_n:
            out[rule] = {"n": int(len(sub)), "avg_fwd": float(sub["fwd"].mean())}
    return out


def comparability_breaks(prev: pd.DataFrame, cur: pd.DataFrame,
                         scale_jump: float = 2.0, top_pct: float = 0.2) -> pd.DataFrame:
    """Q4: 规模突变/换将等可比性break, 且上期为 Top 高分(评分未反映风险)。"""
    if "fund_code" not in prev or "fund_code" not in cur:
        return pd.DataFrame()
    p = prev.drop_duplicates("fund_code").set_index("fund_code")
    c = cur.drop_duplicates("fund_code").set_index("fund_code")
    thr = p["composite_score"].quantile(1 - top_pct) if "composite_score" in p else np.inf
    rows = []
    for code in p.index.intersection(c.index):
        flags = []
        if "scale_yi" in p.columns and "scale_yi" in c.columns:
            ps, cs = p.at[code, "scale_yi"], c.at[code, "scale_yi"]
            if pd.notna(ps) and pd.notna(cs) and ps > 0:
                r = cs / ps
                if r >= scale_jump or r <= 1 / scale_jump:
                    flags.append(f"规模突变 {ps:.1f}→{cs:.1f}亿")
        for mc in ("manager_changed_recent", "manager_changed"):
            if mc in c.columns and bool(c.at[code, mc]) is True:
                flags.append("近期换将")
                break
        if flags:
            sc = p.at[code, "composite_score"] if "composite_score" in p.columns else np.nan
            rows.append({"fund_code": code, "prev_score": sc,
                         "prev_top": bool(pd.notna(sc) and sc >= thr),
                         "breaks": ";".join(flags)})
    out = pd.DataFrame(rows)
    return out.sort_values("prev_score", ascending=False) if not out.empty else out


def run_review(archive_dir: str = "../archive", out_dir: str = "../", kind: str = "equity",
               forward_returns: pd.Series = None, nav_func=None) -> str:
    """主入口: 取最近两期存档复盘, 输出报告 md。
    前瞻收益优先级: forward_returns > nav_func计算 > 下期存档代理(不可靠)。"""
    arch = load_archives(archive_dir, kind)
    dates = sorted(arch.keys())
    if len(dates) < 2:
        msg = f"[{kind}] 复盘需≥2期存档, 当前 {len(dates)} 期({dates})。积累更多期后再跑。"
        print(msg)
        return msg
    prev_d, cur_d = dates[-2], dates[-1]
    prev, cur = arch[prev_d], arch[cur_d]

    proxy = False
    if forward_returns is not None:
        fwd = forward_returns
    elif nav_func is not None:
        fwd = forward_returns_from_nav(prev["fund_code"].tolist(), prev_d, cur_d, nav_func)
    else:
        fwd = compute_forward_from_next(prev, cur)
        proxy = True

    hr = hit_rate(prev, fwd)
    ic = rank_ic(prev, fwd)
    breaks = comparability_breaks(prev, cur)
    rules = rule_effectiveness(load_excluded(archive_dir, kind, prev_d), fwd)

    L = [f"# 季度复盘报告 [{kind}] {prev_d} → {cur_d}", ""]
    if proxy:
        L += ["> ⚠️ 前瞻收益用下期存档代理(不可靠)。传入 forward_returns 或 nav_func 以用真实区间净值。", ""]
    else:
        L += ["> 前瞻收益: 真实区间净值。依据 [[research/基金评估-核心原则_过去与未来]]。", ""]

    L += ["## Q1 命中率(上期Top20% 本期跑赢同类中位)", ""]
    if "error" in hr:
        L.append(f"- {hr['error']}")
    else:
        ok = "✅" if hr["top_hit_rate"] > 0.55 else "⚠️ 需检视"
        L += [f"- Top组命中率: **{hr['top_hit_rate']:.0%}**(目标>55%){ok} | 同类分组列: {hr['group_col']}",
              f"- 全体命中率 {hr['universe_hit_rate']:.0%} | Top前瞻均值 {hr['top_avg_fwd']:.2%} vs 全体 {hr['universe_avg_fwd']:.2%}(n={hr['n']}, top={hr['top_n']})"]

    L += ["", "## Q3 各维度 RankIC(分数 vs 后续收益, 正且稳为佳)", ""]
    if "error" in ic:
        L.append(f"- {ic['error']}")
    else:
        for k, v in ic.items():
            flag = "✅" if v > 0.05 else ("⚠️ 失效?" if v < 0 else "·")
            L.append(f"- {k}: {v:+.3f} {flag}")

    L += ["", "## Q4 可比性break(规模突变/换将, 上期评分或未反映)", ""]
    if breaks.empty:
        L.append("- 未检出(或缺 scale_yi/manager 列)")
    else:
        n_top = int(breaks["prev_top"].sum())
        L.append(f"- 检出 {len(breaks)} 只, 其中上期Top高分 {n_top} 只(评分滞后风险):")
        for _, r in breaks.head(15).iterrows():
            tag = "【上期Top】" if r["prev_top"] else ""
            L.append(f"  - {r['fund_code']} {tag}{r['breaks']}(上期分 {r['prev_score']:.1f})")

    L += ["", "## Q2 规则有效性(剔除样本后续表现, 偏弱=剔得对)", ""]
    if not rules:
        L.append("- 无剔除清单 sheet 或前瞻样本不足")
    else:
        for r, info in sorted(rules.items(), key=lambda kv: kv[1]["avg_fwd"]):
            L.append(f"- {r}: n={info['n']}, 剔除样本后续均值 {info['avg_fwd']:+.2%}")
    L += ["", "## 结论与迭代建议", "",
          "- (人工/下游: 哪维 RankIC 转负→调权重; 哪条规则误杀→调阈值; break 高分基金→历史分打折)"]

    report = "\n".join(L)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"复盘报告_{kind}_{prev_d}_to_{cur_d}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[{kind}] 复盘报告: {path}")
    print(f"  命中率: {hr.get('top_hit_rate', 'N/A')} | RankIC(综合): {ic.get('composite_score', 'N/A')} | break: {len(breaks)}")
    return path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="equity", choices=["equity", "bond"])
    ap.add_argument("--archive", default="../archive")
    ap.add_argument("--out", default="../")
    ap.add_argument("--real-nav", action="store_true", help="用 akshare 真实净值算前瞻(否则代理)")
    args = ap.parse_args()
    nf = None
    if args.real_nav:
        import data_akshare as da
        nf = da.fund_nav
    run_review(args.archive, args.out, kind=args.kind, nav_func=nf)
