"""滚动复盘机制(核心原则落地: 评分→复盘→迭代)
依据: research/基金评估-核心原则_过去与未来.md

输入: archive/ 下两期及以上评分存档(xlsx) + 当前净值(算前瞻收益)
输出: 季度复盘报告 md + 复盘指标

复盘四问:
1. 上期 Top 组本期是否跑赢同类中位数?(命中率)
2. 哪些规则误杀/漏放?
3. 各维度得分 vs 后续表现的 RankIC 是否仍为正?
4. 是否有基金发生历史可比性break而评分未反映?(换将/规模突变)

注: 前瞻收益需真实净值, 本模块用 archive 中已存的下一期评分近似(下一期A维即区间表现),
    或外部传入 forward_returns。脚本独立可跑(不依赖MCP)。
"""
import os
import glob

import numpy as np
import pandas as pd


def load_archives(archive_dir: str = "../archive") -> dict:
    """读所有评分存档, 返回 {date_str: df}. 文件名 score_active_equity_YYYY-MM-DD*.xlsx"""
    out = {}
    for f in sorted(glob.glob(os.path.join(archive_dir, "score_active_equity_*.xlsx"))):
        base = os.path.basename(f)
        # 提取日期
        import re
        m = re.search(r"(\d{4}-\d{2}-\d{2})", base)
        if not m:
            continue
        date = m.group(1)
        try:
            xl = pd.ExcelFile(f)
            sheet = "可投主榜" if "可投主榜" in xl.sheet_names else xl.sheet_names[0]
            df = xl.parse(sheet, dtype={"fund_code": str})
            df["fund_code"] = df["fund_code"].str.zfill(6)
            out[date] = df
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 读取 {base} 失败: {e}")
    return out


def hit_rate(prev: pd.DataFrame, fwd_returns: pd.Series, top_pct: float = 0.2) -> dict:
    """问1: 上期Top组本期跑赢同类中位数的比例
    fwd_returns: fund_code -> 本期前瞻收益; 同类中位数按 effective_group 分组"""
    prev = prev.copy()
    prev["fwd"] = prev["fund_code"].map(fwd_returns)
    valid = prev.dropna(subset=["fwd", "composite_score"])
    if len(valid) < 20:
        return {"error": "样本不足"}
    grp_col = "effective_group" if "effective_group" in valid else None
    if grp_col:
        med = valid.groupby(grp_col)["fwd"].transform("median")
    else:
        med = valid["fwd"].median()
    valid = valid.assign(beat=valid["fwd"] > med)
    thr = valid["composite_score"].quantile(1 - top_pct)
    top = valid[valid["composite_score"] >= thr]
    return {
        "top_hit_rate": float(top["beat"].mean()),       # 目标 >0.55
        "universe_hit_rate": float(valid["beat"].mean()),
        "top_n": len(top),
        "top_avg_fwd": float(top["fwd"].mean()),
        "universe_avg_fwd": float(valid["fwd"].mean()),
    }


def rank_ic(prev: pd.DataFrame, fwd_returns: pd.Series) -> dict:
    """问3: 综合分及各维度分 vs 前瞻收益的秩相关(Spearman, rank后pearson)"""
    prev = prev.copy()
    prev["fwd"] = prev["fund_code"].map(fwd_returns)
    v = prev.dropna(subset=["fwd"])
    if len(v) < 20:
        return {"error": "样本不足"}
    out = {}
    for col in ["composite_score", "score_A_return", "score_B_risk",
                "score_C_attribution", "score_D_manager", "score_E_operation"]:
        if col in v and v[col].notna().sum() >= 20:
            vv = v.dropna(subset=[col])
            out[col] = float(vv[col].rank().corr(vv["fwd"].rank()))
    return out


def rule_effectiveness(prev_excluded: pd.DataFrame, fwd_returns: pd.Series) -> dict:
    """问2: 被各N规则剔除的基金, 本期表现如何(剔得对则其表现应偏弱)"""
    if prev_excluded.empty or "screen_reasons" not in prev_excluded:
        return {}
    ex = prev_excluded.copy()
    ex["fwd"] = ex["fund_code"].map(fwd_returns)
    out = {}
    for rule in ["N1_规模过小", "N3_成立太短", "N4_任期太短", "N5_经理近期变更"]:
        mask = ex["screen_reasons"].str.contains(rule, na=False)
        sub = ex[mask].dropna(subset=["fwd"])
        if len(sub) >= 5:
            out[rule] = {"n": len(sub), "avg_fwd": float(sub["fwd"].mean())}
    return out


def compute_forward_from_next(prev: pd.DataFrame, nxt: pd.DataFrame) -> pd.Series:
    """近似前瞻收益: 用下一期存档的 ann_return_3y 变化不可靠;
    更稳妥用下一期的近1期区间收益. 此处占位: 用下期A维原始超额近似排序信号.
    实盘应替换为真实区间净值收益(见 TODO)"""
    # TODO v1.0: 接真实净值算两存档日期之间的区间收益
    # 占位实现: 用下期 excess_return_ann_3y 作为"延续表现"的代理(仅供骨架跑通)
    if "excess_return_ann_3y" in nxt:
        return nxt.set_index("fund_code")["excess_return_ann_3y"]
    return pd.Series(dtype=float)


def run_review(archive_dir: str = "../archive", out_dir: str = "../") -> str:
    """主入口: 取最近两期存档做复盘, 输出报告 md"""
    arch = load_archives(archive_dir)
    dates = sorted(arch.keys())
    if len(dates) < 2:
        msg = f"复盘需≥2期存档, 当前 {len(dates)} 期({dates}). 积累更多期后再跑。"
        print(msg)
        return msg
    prev_d, cur_d = dates[-2], dates[-1]
    prev, cur = arch[prev_d], arch[cur_d]
    fwd = compute_forward_from_next(prev, cur)

    hr = hit_rate(prev, fwd)
    ic = rank_ic(prev, fwd)

    lines = [
        f"# 季度复盘报告 {prev_d} → {cur_d}",
        "",
        "> ⚠️ 骨架版: 前瞻收益用下期存档代理, 实盘须接真实区间净值(见 review.py TODO)。",
        "> 依据 [[research/基金评估-核心原则_过去与未来]]。",
        "",
        "## 问1: 命中率(上期Top20%本期是否跑赢同类中位数)",
        "",
    ]
    if "error" in hr:
        lines.append(f"- {hr['error']}")
    else:
        lines += [
            f"- Top组命中率: **{hr['top_hit_rate']:.0%}**(目标>55%){'✅' if hr['top_hit_rate']>0.55 else '⚠️ 需检视'}",
            f"- 全体命中率: {hr['universe_hit_rate']:.0%} | Top组前瞻均值 {hr['top_avg_fwd']:.2%} vs 全体 {hr['universe_avg_fwd']:.2%}",
        ]
    lines += ["", "## 问3: 各维度 RankIC(分数 vs 后续表现, 正且稳定为佳)", ""]
    if "error" in ic:
        lines.append(f"- {ic['error']}")
    else:
        for k, v in ic.items():
            flag = "✅" if v > 0.05 else ("⚠️失效?" if v < 0 else "·")
            lines.append(f"- {k}: {v:+.3f} {flag}")
    lines += [
        "", "## 问2/问4: 规则有效性 / 可比性break(待真实前瞻数据接入后细化)",
        "- TODO: 接真实区间净值后, 统计各N规则剔除样本的后续表现 + 换将/规模突变基金的评分滞后",
        "",
        "## 结论与迭代建议", "",
        "- (人工填写: 哪个维度失效→调权重; 哪条规则误杀→调阈值)",
    ]
    report = "\n".join(lines)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"复盘报告_{prev_d}_to_{cur_d}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"复盘报告: {path}")
    print(f"命中率: {hr.get('top_hit_rate', 'N/A')} | RankIC(综合): {ic.get('composite_score', 'N/A')}")
    return path


if __name__ == "__main__":
    run_review()
