"""固收+ 分流骨架测试(无网络): split_tracks + 纯债/固收+ 双 track 评分。
scoring_bond_plus 未交付时, 固收+ track 应走纯债记分卡兜底(scorecard=BOND(fallback))。
运行: python test_bond_tracks.py
"""
import numpy as np
import pandas as pd

import run_monthly_bond as rmb


def _synth(subgroups):
    rng = np.random.default_rng(3)
    rows = []
    k = 0
    for sg, cnt in subgroups.items():
        for _ in range(cnt):
            rows.append(dict(
                fund_code=f"{k+1:06d}", fund_name=f"测试{k}", bond_subgroup=sg,
                campisi_alpha=rng.normal(0.01, 0.005), ann_return_3y=rng.normal(0.03, 0.01),
                cpr_persistence=rng.uniform(0.5, 3),
                calmar_3y=rng.uniform(0.5, 5), max_drawdown_3y=-rng.uniform(0.005, 0.05),
                recovery_days_3y=rng.integers(10, 200), sortino_3y=rng.uniform(0.5, 4),
                monthly_positive_ratio_3y=rng.uniform(0.5, 0.95),
                selection_share_bond=rng.uniform(-0.5, 1.5),
                credit_sink=rng.uniform(0.2, 1.2), duration_dev=rng.uniform(0.5, 6),
                leverage_contrib=rng.uniform(1.0, 1.4),
                manager_experience=rng.uniform(2, 12), management_load=rng.uniform(20, 400),
                total_fee=rng.uniform(0.003, 0.008), scale_yi=rng.uniform(5, 50), valid_3y=True,
                equity_position=(0.15 if sg=="混合债券二级" else 0.25)))
            k += 1
    return pd.DataFrame(rows)


def test_split_and_dual_track():
    print("== 固收+ 分流骨架测试 ==")
    df = _synth({"中长期纯债": 8, "短期纯债": 6, "混合债券二级": 8, "偏债混合/固收+": 6})
    bond_std, plus_std = rmb.split_tracks(df)
    assert len(bond_std) == 14 and len(plus_std) == 14, (len(bond_std), len(plus_std))
    assert set(plus_std["bond_subgroup"]) <= rmb.BOND_PLUS_SUBGROUPS
    print(f"  分流: 纯债 {len(bond_std)} | 固收+ {len(plus_std)} ✓")

    sb = rmb.score_bond_track(bond_std)
    assert not sb.empty and (sb["scorecard"] == "BOND").all()
    assert sb["composite_score"].between(0, 100).all()
    print(f"  纯债 track: {len(sb)} 只 scorecard=BOND ✓")

    sp = rmb.score_plus_track(plus_std)  # scoring_bond_plus 已交付 -> 权益中枢分组
    assert not sp.empty and (sp["scorecard"] == "BOND_PLUS").all()
    assert "equity_band" in sp.columns and set(sp["equity_band"]) <= {"稳健", "积极"}
    scored_rows = sp[sp["composite_score"].notna()]
    assert scored_rows["composite_score"].between(0, 100).all()
    print(f"  固收+ track: {len(sp)} 只 scorecard=BOND_PLUS, 档位={sorted(set(sp['equity_band']))} ✓")

    combined = pd.concat([sb, sp], ignore_index=True)
    print(f"  合并 {len(combined)} 只 | 记分卡分布 {combined['scorecard'].value_counts().to_dict()}")




def test_excel_split_by_scorecard():
    print("== Excel 固收+榜 分表测试 ==")
    import openpyxl
    main_board = pd.DataFrame({
        "fund_code": [f"{i:06d}" for i in range(6)],
        "composite_score": [80, 70, 60, 55, 50, 40],
        "scorecard": ["BOND", "BOND", "BOND", "BOND_PLUS", "BOND_PLUS", "BOND(fallback)"],
    })
    micro_board = pd.DataFrame({"fund_code": ["900001"], "composite_score": [30],
                                "scorecard": ["BOND"]})
    df_all = pd.DataFrame({"fund_code": ["800001"], "screened_out": [True]})
    out = "/sessions/keen-sharp-ptolemy/mnt/outputs/_score_bond_test.xlsx"
    counts = rmb.write_score_workbook(out, main_board, micro_board, df_all)
    wb = openpyxl.load_workbook(out)
    assert set(wb.sheetnames) == {"纯债可投主榜", "固收+榜", "小微观察区", "剔除清单"}, wb.sheetnames
    assert counts["纯债可投主榜"] == 3 and counts["固收+榜"] == 3, counts
    print(f"  sheet={wb.sheetnames} | 行数={counts} ✓")


if __name__ == "__main__":
    test_split_and_dual_track()
    test_excel_split_by_scorecard()
    print("\n固收+ 分流骨架测试通过 ✅")
