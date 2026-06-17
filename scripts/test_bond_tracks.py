"""4-Track 路由 + 评分 + Excel 分表测试(无网络)。
覆盖: assign_track / score_subgroups(组内defer不跨异质) / score_plus_track / write_score_workbook。
运行: python test_bond_tracks.py
"""
import tempfile

import numpy as np
import pandas as pd

import config
import run_monthly_bond as rmb


def _metric_cols(rng, n):
    return dict(
        campisi_alpha=rng.normal(0.01, 0.005, n), ann_return_3y=rng.normal(0.03, 0.01, n),
        cpr_persistence=rng.uniform(0.5, 3, n), calmar_3y=rng.uniform(0.5, 5, n),
        max_drawdown_3y=-rng.uniform(0.005, 0.05, n), recovery_days_3y=rng.integers(10, 200, n),
        sortino_3y=rng.uniform(0.5, 4, n), monthly_positive_ratio_3y=rng.uniform(0.5, 0.95, n),
        selection_share_bond=rng.uniform(-0.5, 1.5, n), manager_experience=rng.uniform(2, 12, n),
        management_load=rng.uniform(20, 400, n), total_fee=rng.uniform(0.003, 0.008, n),
        scale_yi=rng.uniform(5, 50, n), valid_3y=True)


def test_assign_track():
    print("== assign_track 4-Track 映射 ==")
    df = pd.DataFrame({
        "fund_code": [f"{i:06d}" for i in range(6)],
        "fund_type": ["债券型-长债", "债券型-混合一级", "债券型-混合二级",
                      "混合型-偏债", "债券型-可转债", "指数型-固收"],
        "bond_subgroup": ["中长期纯债", "混合债券一级", "混合债券二级",
                          "偏债混合/固收+", "可转债基金", "中长期纯债"],
    })
    out = rmb.assign_track(df)
    assert list(out["track"]) == ["BOND", "BOND1", "PLUS", "PLUS", "CB", "BOND_INDEX"], list(out["track"])
    print(f"  {list(out['track'])} ✓ (指数固收按fund_type覆盖纯债误判)")


def test_score_subgroups_defer():
    print("== 纯债组内评分: 小组defer不跨异质 ==")
    rng = np.random.default_rng(1)
    rows = []
    for sg, cnt in [("中长期纯债", 6), ("短期纯债", 3)]:  # 短债<5 应 defer
        for _ in range(cnt):
            r = {k: (v[len(rows) % len(v)] if hasattr(v, "__len__") and not isinstance(v, bool) else v)
                 for k, v in _metric_cols(rng, 30).items()}
            r["bond_subgroup"] = sg
            rows.append(r)
    std = pd.DataFrame(rows)
    std["fund_code"] = [f"{i:06d}" for i in range(len(std))]
    scored = rmb.score_subgroups(std, config.BOND_DIM_WEIGHTS, config.BOND_INDICATORS, "BOND")
    assert set(scored["bond_subgroup"]) == {"中长期纯债"}, set(scored["bond_subgroup"])
    assert (scored["scorecard"] == "BOND").all()
    assert "纯债综合" not in set(scored.get("bond_subgroup", []))
    print(f"  中长期纯债{len(scored)}只评分, 短债3只defer未并入 ✓")


def test_plus_track():
    print("== 固收+ track(BOND_PLUS) ==")
    rng = np.random.default_rng(2)
    n = 12
    df = pd.DataFrame(_metric_cols(rng, n))
    df["fund_code"] = [f"{i:06d}" for i in range(n)]
    df["bond_subgroup"] = "混合债券二级"
    df["equity_position"] = 0.15
    scored = rmb.score_plus_track(df)
    assert (scored["scorecard"] == "BOND_PLUS").all()
    assert "equity_band" in scored.columns
    print(f"  {len(scored)}只 BOND_PLUS, 档位={sorted(set(scored['equity_band']))} ✓")


def test_excel_multi_sheet():
    print("== Excel 多 track 分表 ==")
    import openpyxl
    main_board = pd.DataFrame({
        "fund_code": [f"{i:06d}" for i in range(7)], "composite_score": [80, 70, 60, 55, 50, 45, 40],
        "scorecard": ["BOND", "BOND", "BOND1", "BOND1", "BOND_PLUS", "BOND_PLUS", "BOND_INDEX"]})
    not_scored = pd.DataFrame({"fund_code": ["700001", "700002"],
                               "track": ["CB", "BOND_INDEX"]})
    micro = pd.DataFrame({"fund_code": ["900001"], "composite_score": [30], "scorecard": ["BOND"]})
    df_all = pd.DataFrame({"fund_code": ["800001"], "screened_out": [True]})
    with tempfile.TemporaryDirectory() as d:
        out = f"{d}/score_bond_test.xlsx"
        counts = rmb.write_score_workbook(out, main_board, not_scored, micro, df_all)
        names = set(openpyxl.load_workbook(out).sheetnames)
    expect = {"纯债主榜", "一级债榜", "固收+榜", "工具型榜", "可转债待评", "工具型待评", "小微观察区", "剔除清单"}
    assert names == expect, names
    print(f"  sheets={sorted(names)} | counts={counts} ✓")


def test_index_track():
    print("== 工具型 track(BOND_INDEX) ==")
    rng = np.random.default_rng(3)
    rows = []
    for ftype, n in [("指数型-固收", 6), ("QDII债券", 5), ("指数型-固收", 3)]:
        # 第三组用于验证子组内 <5 不影响; 这里两类 fund_type 合并计数: 指数固收共9, QDII 5
        for _ in range(n):
            rows.append({"fund_type": ftype,
                         "scale_yi": float(rng.uniform(1, 80)),
                         "total_fee": float(rng.uniform(0.002, 0.008)),
                         "fund_age_years": float(rng.uniform(1, 8))})
    df = pd.DataFrame(rows)
    df["fund_code"] = [f"{i:06d}" for i in range(len(df))]
    scored = rmb.score_index_track(df)
    assert not scored.empty and (scored["scorecard"] == "BOND_INDEX").all(), scored
    subs = set(scored["index_subgroup"])
    assert subs == {"指数固收", "QDII债"}, subs  # 两子组各>=5 均评分
    assert scored["score_label"].str.startswith("provisional").all(), scored["score_label"].tolist()
    print(f"  {len(scored)}只 BOND_INDEX, 子组={sorted(subs)}, Phase A 全 provisional ✓")


def test_index_track_phase_b():
    print("== 工具型 track Phase B(跟踪误差+主流度) ==")
    rng = np.random.default_rng(31)
    idx = pd.bdate_range(end="2026-05-29", periods=260)
    index_ret = pd.Series(rng.normal(0.0001, 0.002, len(idx)), index=idx)
    rows, navs = [], {}
    for i in range(6):
        code = f"03{i:04d}"
        ret = index_ret + rng.normal(0, 0.0003 + i * 0.0002, len(idx))
        navs[code] = pd.Series((1 + ret).cumprod(), index=idx)
        rows.append({
            "fund_code": code,
            "fund_type": "指数型-固收",
            "scale_yi": 10 + i,
            "total_fee": 0.004,
            "fund_age_years": 5,
            "index_code": "CBA_TEST",
            "index_mainstream": 0.9,
        })
    scored = rmb.score_index_track(pd.DataFrame(rows), navs, {"CBA_TEST": index_ret})
    assert not scored.empty
    assert scored["tracking_error"].notna().all()
    assert scored["score_label"].eq("formal").all(), scored["score_label"].tolist()
    print("  映射+指数收益可用 -> tracking_error 生效且 formal ✓")


def test_investability_warn():
    print("== 可投性前置(mark + score_all OR透传) ==")
    import scoring
    df = pd.DataFrame({
        "fund_code": [f"{i:06d}" for i in range(4)],
        "subscribe_status": ["开放申购", "暂停申购", "", ""],
        "can_subscribe": [True, True, False, True],
        "fund_status_text": ["", "", "", "定期开放"],
        "scale_yi": [50, 50, 50, 50]})
    out = rmb.screening_bond.mark_investability_bond(df)
    assert list(out["investability_warn"]) == [False, True, True, True], list(out["investability_warn"])
    # 列全缺 -> 优雅降级, 不报错且全 False
    bare = pd.DataFrame({"fund_code": ["x"], "scale_yi": [50]})
    assert not rmb.screening_bond.mark_investability_bond(bare)["investability_warn"].any()
    # score_all OR 透传: 规模大(micro=False)但上游 warn=True 应保留
    rng = np.random.default_rng(9)
    g = pd.DataFrame(_metric_cols(rng, 6))
    g["fund_code"] = [f"{i:06d}" for i in range(6)]
    g["bond_subgroup"] = "中长期纯债"
    g["scale_yi"] = 50.0
    g["investability_warn"] = [True, False, False, False, False, False]
    scored = scoring.score_all(g, dim_weights=config.BOND_DIM_WEIGHTS,
                               indicators=config.BOND_INDICATORS,
                               veto_dim="B_risk", primary_dim="A_return")
    sc0 = scored.set_index("fund_code").loc["000000", "investability_warn"]
    assert bool(sc0) is True, "上游 investability_warn 未透传"
    print("  状态识别/优雅降级/score_all OR透传 ✓")


if __name__ == "__main__":
    test_assign_track()
    test_score_subgroups_defer()
    test_plus_track()
    test_index_track()
    test_index_track_phase_b()
    test_investability_warn()
    test_excel_multi_sheet()
    print("\n4-Track 测试全部通过 ✅")
