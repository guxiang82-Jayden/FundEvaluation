"""Tests for the standalone bond-fund L1 screening module."""

import warnings

import pandas as pd

import screening_bond


def _base(code: str, name: str) -> dict:
    return {
        "fund_code": code,
        "fund_name": name,
        "scale_yi": 10.0,
        "fund_age_years": 3.0,
        "manager_changed_recent": False,
        "leverage_ratio": 1.20,
        "neg_alert": False,
        "inst_ratio": 0.60,
    }


def test_all_rules() -> None:
    rows = []

    normal = _base("B000", "正常债基")
    rows.append(normal)

    small = _base("B001", "迷你债基")
    small["scale_yi"] = 0.3
    rows.append(small)

    young = _base("B002", "次新债基")
    young["fund_age_years"] = 0.5
    rows.append(young)

    changed = _base("B003", "换将债基")
    changed["manager_changed_recent"] = True
    rows.append(changed)

    leveraged = _base("B004", "高杠杆债基")
    leveraged["leverage_ratio"] = 1.60
    rows.append(leveraged)

    alerted = _base("B005", "踩雷债基")
    alerted["neg_alert"] = True
    rows.append(alerted)

    institutional = _base("B006", "机构定制债基")
    institutional["inst_ratio"] = 0.98
    rows.append(institutional)

    out = screening_bond.apply_screening_bond(
        pd.DataFrame(rows)
    ).set_index("fund_code")

    assert out.loc["B000", "channel"] == "standard"
    assert not out.loc["B000", "screened_out"]
    assert "FN1_规模过小" in out.loc["B001", "screen_reasons"]
    assert "FN2_成立太短" in out.loc["B002", "screen_reasons"]
    assert "FN3_经理近期变更" in out.loc["B003", "screen_reasons"]
    assert "FN4_杠杆超限" in out.loc["B004", "screen_reasons"]
    assert "FN5_踩雷记录" in out.loc["B005", "screen_reasons"]
    assert "FN6_机构定制盘" in out.loc["B006", "screen_reasons"]
    assert (out.loc[out.index != "B000", "channel"] == "excluded").all()


def test_multiple_reasons() -> None:
    row = _base("B100", "多重风险债基")
    row.update(
        {
            "scale_yi": 0.2,
            "fund_age_years": 0.4,
            "leverage_ratio": 1.50,
        }
    )
    out = screening_bond.apply_screening_bond(pd.DataFrame([row])).iloc[0]
    assert out["screen_reasons"].split(";") == [
        "FN1_规模过小",
        "FN2_成立太短",
        "FN4_杠杆超限",
    ]


def test_missing_columns_are_skipped() -> None:
    minimal = pd.DataFrame(
        [{"fund_code": "B200", "fund_name": "字段不足债基", "scale_yi": 2.0}]
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = screening_bond.apply_screening_bond(minimal)

    assert out.loc[0, "channel"] == "standard"
    assert not out.loc[0, "screened_out"]
    assert len(caught) == 5
    assert len(out.attrs["screening_warnings"]) == 5
    assert all("skipped" in str(item.message) for item in caught)


if __name__ == "__main__":
    test_all_rules()
    test_multiple_reasons()
    test_missing_columns_are_skipped()
    print("screening_bond tests passed")
