"""Tests for the standalone bond-fund L0 classifier."""

import pandas as pd

import classify_bond


def test_classification() -> None:
    samples = pd.DataFrame(
        [
            ("000001", "稳健中短债A", "债券型-中短债"),
            ("000002", "长期纯债A", "债券型-长债"),
            ("000003", "信用增强债券A", "债券型-混合一级"),
            ("000004", "稳健回报债券A", "债券型-混合二级"),
            ("000005", "安心回报混合A", "混合型-偏债"),
            ("000006", "精选可转债A", "债券型-混合二级"),
            ("000007", "三年摊余定开债券", "债券型-长债"),
            ("000008", "政策性金融债持有期A", "债券型-长债"),
            ("000009", "同业存单指数7天持有", "指数型-固收"),
            ("000010", "未知产品", "其他"),
        ],
        columns=["fund_code", "fund_name", "fund_type"],
    )

    out = classify_bond.classify_bond(samples).set_index("fund_code")

    assert out.loc["000001", "bond_subgroup"] == "短期纯债"
    assert out.loc["000002", "bond_subgroup"] == "中长期纯债"
    assert out.loc["000003", "bond_subgroup"] == "混合债券一级"
    assert out.loc["000004", "bond_subgroup"] == "混合债券二级"
    assert out.loc["000005", "bond_subgroup"] == "偏债混合/固收+"
    assert out.loc["000006", "bond_subgroup"] == "可转债基金"

    assert "信用债型" in out.loc["000003", "bond_strategy_tags"]
    assert out.loc["000007", "bond_strategy_tags"] == "摊余成本法+持有期"
    assert set(out.loc["000008", "bond_strategy_tags"].split("+")) == {
        "利率债型",
        "持有期",
    }
    assert set(out.loc["000009", "bond_strategy_tags"].split("+")) == {
        "持有期",
        "同业存单",
    }

    assert out.loc["000006", "classify_confidence"] == "high"
    assert out.loc["000009", "bond_subgroup"] == "未分类"
    assert out.loc["000009", "classify_confidence"] == "low"
    assert out.loc["000010", "classify_confidence"] == "low"


def test_required_columns() -> None:
    try:
        classify_bond.classify_bond(pd.DataFrame({"fund_code": ["1"]}))
    except ValueError as exc:
        assert "fund_name" in str(exc)
        assert "fund_type" in str(exc)
    else:
        raise AssertionError("missing columns should raise ValueError")


if __name__ == "__main__":
    test_classification()
    test_required_columns()
    print("classify_bond tests passed")
