"""L0 classification for mainland bond funds and fixed-income-plus funds.

AKShare ``fund_name_em()`` fund types verified on 2026-06-14:
    债券型-长债, 债券型-中短债, 债券型-混合一级, 债券型-混合二级,
    混合型-偏债, 指数型-固收

No separate ``债券型-可转债`` type was present in the current snapshot, so
convertible-bond funds are identified by fund name before the type mapping.
"""

from __future__ import annotations

import re

import pandas as pd


BOND_SUBGROUPS = (
    "短期纯债",
    "中长期纯债",
    "混合债券一级",
    "混合债券二级",
    "偏债混合/固收+",
    "可转债基金",
)

STRATEGY_PATTERNS = {
    "利率债型": r"利率债|国债|政金债|政策性金融债|国开债",
    "信用债型": r"信用",
    "摊余成本法": r"摊余",
    "持有期": r"持有|定开",
    "同业存单": r"同业存单",
}


def _strategy_tags(fund_name: str) -> str:
    hits = [
        label
        for label, pattern in STRATEGY_PATTERNS.items()
        if re.search(pattern, fund_name, flags=re.IGNORECASE)
    ]
    return "+".join(hits)


def classify_bond(df: pd.DataFrame) -> pd.DataFrame:
    """Add bond subgroup, strategy tags, and classification confidence.

    Required columns are ``fund_code``, ``fund_name``, and ``fund_type``.
    ``bond_strategy_tags`` is a ``+``-joined orthogonal second axis.
    Credit-sinking is intentionally not inferred from names; future holding
    data can append that tag without changing the asset subgroup.
    """
    required = {"fund_code", "fund_name", "fund_type"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"classify_bond missing columns: {sorted(missing)}")

    out = df.copy()
    name = out["fund_name"].fillna("").astype(str)
    fund_type = out["fund_type"].fillna("").astype(str)

    subgroup = pd.Series("未分类", index=out.index, dtype="object")
    confidence = pd.Series("low", index=out.index, dtype="object")

    type_rules = (
        (r"债券型-(?:中短债|短债)", "短期纯债"),
        (r"债券型-长债", "中长期纯债"),
        (r"债券型-混合一级", "混合债券一级"),
        (r"债券型-混合二级", "混合债券二级"),
        (r"混合型-偏债", "偏债混合/固收+"),
    )
    for pattern, label in type_rules:
        hit = fund_type.str.contains(pattern, regex=True, na=False)
        subgroup.loc[hit] = label
        confidence.loc[hit] = "high"

    # Name takes precedence because Eastmoney currently has no standalone
    # convertible-bond fund type and places such products in mixed bond types.
    convertible = name.str.contains(r"可转债|转债", regex=True, na=False)
    subgroup.loc[convertible] = "可转债基金"
    confidence.loc[convertible] = "high"

    # Future extension point: append "信用下沉" from holding-implied ratings.
    out["bond_subgroup"] = subgroup
    out["bond_strategy_tags"] = name.map(_strategy_tags)
    out["classify_confidence"] = confidence
    return out


def subgroup_stats(out: pd.DataFrame) -> pd.DataFrame:
    """Return descending counts by bond subgroup."""
    return (
        out.groupby("bond_subgroup", dropna=False)
        .size()
        .sort_values(ascending=False)
        .rename("count")
        .to_frame()
    )


def _main() -> None:
    import akshare as ak

    universe = ak.fund_name_em().rename(
        columns={
            "基金代码": "fund_code",
            "基金简称": "fund_name",
            "基金类型": "fund_type",
        }
    )
    fixed_income = universe[
        universe["fund_type"].fillna("").str.contains(
            r"债券型|混合型-偏债", regex=True
        )
    ].copy()
    classified = classify_bond(fixed_income)

    print(f"Fixed-income universe: {len(classified)}")
    print(subgroup_stats(classified).to_string())
    print("\nConfidence:")
    print(classified["classify_confidence"].value_counts().to_string())
    print("\nStrategy tags (non-empty):")
    tags = classified.loc[
        classified["bond_strategy_tags"] != "", "bond_strategy_tags"
    ]
    print(tags.value_counts().head(20).to_string())


if __name__ == "__main__":
    _main()
