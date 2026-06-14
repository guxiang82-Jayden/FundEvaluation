"""L1 negative screening for bond funds and fixed-income-plus funds.

This module is intentionally independent from the active-equity screening
pipeline. Missing source columns skip the corresponding rule with a warning.
"""

from __future__ import annotations

import warnings

import pandas as pd


SCREENING_BOND = {
    "FN1_min_scale_yi": 0.5,
    "FN2_min_fund_age_years": 1.0,
    "FN3_recent_change_months": 6,
    "FN4_max_leverage_ratio": 1.40,
    "FN6_max_inst_ratio": 0.95,
}

RULE_COLUMNS = {
    "FN1": ("scale_yi",),
    "FN2": ("fund_age_years",),
    "FN3": ("manager_changed_recent",),
    "FN4": ("leverage_ratio",),
    "FN5": ("neg_alert",),
    "FN6": ("inst_ratio",),
}


def apply_screening_bond(df: pd.DataFrame) -> pd.DataFrame:
    """Apply FN1-FN6 and add reasons, exclusion flag, and channel.

    Expected metadata columns:
      fund_code, fund_name, scale_yi, fund_age_years,
      manager_changed_recent, leverage_ratio, neg_alert, inst_ratio

    Missing rule columns are skipped. FN6 currently uses institutional
    ownership above 95% as a conservative proxy; when holder-count data is
    available, the rule should be tightened to require both high institutional
    ownership and very few holders.
    """
    out = df.copy()
    reasons = {idx: [] for idx in out.index}
    skipped = []

    def flag(mask: pd.Series, reason: str) -> None:
        for idx in out.index[mask.fillna(False)]:
            reasons[idx].append(reason)

    def available(rule: str) -> bool:
        missing = [col for col in RULE_COLUMNS[rule] if col not in out.columns]
        if not missing:
            return True
        message = f"{rule} skipped: missing columns {missing}"
        skipped.append(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        return False

    if available("FN1"):
        scale = pd.to_numeric(out["scale_yi"], errors="coerce")
        flag(scale < SCREENING_BOND["FN1_min_scale_yi"], "FN1_规模过小")

    if available("FN2"):
        age = pd.to_numeric(out["fund_age_years"], errors="coerce")
        flag(
            age < SCREENING_BOND["FN2_min_fund_age_years"],
            "FN2_成立太短",
        )

    if available("FN3"):
        flag(
            out["manager_changed_recent"].eq(True),  # noqa: E712
            "FN3_经理近期变更",
        )

    if available("FN4"):
        leverage = pd.to_numeric(out["leverage_ratio"], errors="coerce")
        flag(
            leverage > SCREENING_BOND["FN4_max_leverage_ratio"],
            "FN4_杠杆超限",
        )

    if available("FN5"):
        flag(out["neg_alert"].eq(True), "FN5_踩雷记录")  # noqa: E712

    if available("FN6"):
        inst_ratio = pd.to_numeric(out["inst_ratio"], errors="coerce")
        flag(
            inst_ratio > SCREENING_BOND["FN6_max_inst_ratio"],
            "FN6_机构定制盘",
        )

    out["screen_reasons"] = [";".join(reasons[idx]) for idx in out.index]
    out["screened_out"] = out["screen_reasons"].ne("")
    out["channel"] = "standard"
    out.loc[out["screened_out"], "channel"] = "excluded"
    out.attrs["screening_warnings"] = skipped
    return out


if __name__ == "__main__":
    sample = pd.DataFrame(
        [
            {
                "fund_code": "B001",
                "fund_name": "正常纯债",
                "scale_yi": 10.0,
                "fund_age_years": 5.0,
                "manager_changed_recent": False,
                "leverage_ratio": 1.20,
                "neg_alert": False,
                "inst_ratio": 0.60,
            },
            {
                "fund_code": "B002",
                "fund_name": "高杠杆债基",
                "scale_yi": 10.0,
                "fund_age_years": 5.0,
                "manager_changed_recent": False,
                "leverage_ratio": 1.60,
                "neg_alert": False,
                "inst_ratio": 0.60,
            },
        ]
    )
    print(
        apply_screening_bond(sample)[
            ["fund_code", "screen_reasons", "screened_out", "channel"]
        ].to_string(index=False)
    )
