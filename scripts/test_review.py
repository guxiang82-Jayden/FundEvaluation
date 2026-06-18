"""review.py 复盘机制测试(合成 archive, 无网络)。
覆盖: load_archives(债基多榜合并) / hit_rate / rank_ic / comparability_breaks / run_review 端到端。
运行: python test_review.py
"""
import os
import tempfile

import numpy as np
import pandas as pd

import review


def _synth_board(n=40, seed=0, score_offset=0.0):
    rng = np.random.default_rng(seed)
    sc = np.linspace(20, 90, n) + rng.normal(0, 3, n)
    return pd.DataFrame({
        "fund_code": [f"{i:06d}" for i in range(n)],
        "fund_name": [f"基金{i}" for i in range(n)],
        "composite_score": sc,
        "score_A_return": sc + rng.normal(0, 5, n),
        "score_B_risk": sc + rng.normal(0, 5, n),
        "score_C_attribution": rng.uniform(30, 80, n),
        "score_D_manager": rng.uniform(30, 80, n),
        "score_E_operation": rng.uniform(30, 80, n),
        "effective_group": np.where(np.arange(n) % 2 == 0, "中长期纯债", "短期纯债"),
        "scale_yi": rng.uniform(5, 50, n),
        "manager_changed_recent": False,
    })


def test_hit_rate_and_ic():
    print("== Q1命中率 + Q3 RankIC ==")
    prev = _synth_board(40, seed=1)
    # 前瞻收益与综合分单调正相关 -> 高分应跑赢, RankIC>0
    fwd = prev.set_index("fund_code")["composite_score"] / 1000 + \
        pd.Series(np.random.default_rng(2).normal(0, 0.002, len(prev)),
                  index=prev["fund_code"])
    hr = review.hit_rate(prev, fwd)
    ic = review.rank_ic(prev, fwd)
    assert hr["top_hit_rate"] >= 0.6, hr
    assert ic["composite_score"] > 0.3, ic
    print(f"  Top命中率 {hr['top_hit_rate']:.0%} | 综合RankIC {ic['composite_score']:+.3f} [OK]")


def test_comparability_breaks():
    print("== Q4 可比性break ==")
    prev = _synth_board(20, seed=3)
    cur = prev.copy()
    cur.loc[0, "scale_yi"] = prev.loc[0, "scale_yi"] * 3      # 规模突变
    cur.loc[1, "manager_changed_recent"] = True               # 换将
    prev.loc[0, "composite_score"] = 95                       # 上期高分
    br = review.comparability_breaks(prev, cur)
    codes = set(br["fund_code"])
    assert "000000" in codes and "000001" in codes, codes
    assert bool(br[br["fund_code"] == "000000"]["prev_top"].iloc[0]) is True
    print(f"  检出 {len(br)} 只(规模突变+换将), 上期Top标记正确 [OK]")


def test_load_and_run_bond():
    print("== 债基多榜合并 + run_review 端到端 ==")
    with tempfile.TemporaryDirectory() as d:
        for date, seed in [("2026-03-31", 10), ("2026-06-30", 11)]:
            b = _synth_board(30, seed=seed)
            path = os.path.join(d, f"score_bond_{date}.xlsx")
            with pd.ExcelWriter(path) as xw:
                b.iloc[:18].to_excel(xw, sheet_name="纯债主榜", index=False)
                b.iloc[18:].to_excel(xw, sheet_name="固收+榜", index=False)
                # 剔除清单(供 Q2 规则有效性)
                exc = pd.DataFrame({"fund_code": [f"9{i:05d}" for i in range(6)],
                                    "screen_reasons": ["FN1_规模过小"] * 6})
                exc.to_excel(xw, sheet_name="剔除清单", index=False)
        arch = review.load_archives(d, kind="bond")
        assert len(arch) == 2 and len(arch["2026-03-31"]) == 30, {k: len(v) for k, v in arch.items()}
        # 真实前瞻(合成): 高分跑赢
        prev = arch["2026-03-31"]
        fwd = prev.set_index("fund_code")["composite_score"] / 1000
        # 给剔除基金也加前瞻(偏弱), 让 Q2 生效
        exc_fwd = pd.Series({f"9{i:05d}": -0.02 for i in range(6)})
        fwd = pd.concat([fwd, exc_fwd])
        path = review.run_review(d, d, kind="bond", forward_returns=fwd)
        assert os.path.exists(path) and path.endswith(".md")
        txt = open(path, encoding="utf-8").read()
        assert "命中率" in txt and "RankIC" in txt
        assert "FN1_规模过小" in txt, "Q2 规则有效性未生效"
    print("  债基2榜合并(30只) + 报告含命中率/RankIC/Q2规则有效性 [OK]")


if __name__ == "__main__":
    test_hit_rate_and_ic()
    test_comparability_breaks()
    test_load_and_run_bond()
    print("\nreview.py 复盘测试全部通过 [OK]")
