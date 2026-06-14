"""AKShare data layer for the NAV-based Campisi bond factors.

The ChinaBond series below are fetched with:
    ak.bond_index_general_cbond(
        index_category=<category>, indicator="财富", period=<period>
    )
The returned columns, verified with AKShare 1.18.64, are ``date`` and ``value``.

Available mappings:
    中债国债总财富   -> 国债总指数 / 财富 / 总值
    中债中短期     -> 国债总指数 / 财富 / 1-3年
    中债长期       -> 国债总指数 / 财富 / 7-10年
    中债企业债AAA  -> 企业债AAA指数 / 财富 / 总值
    中债国开债     -> 国开行债券总指数 / 财富 / 总值
    中债高收益企业债 -> 高收益企业债指数 / 财富 / 总值

TODO: ``bond_available_index_cbond()`` has no ChinaBond convertible-bond
index. ``中债转债`` is therefore omitted instead of being substituted with a
non-ChinaBond series.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import akshare as ak
except ImportError:
    ak = None


CACHE_DIR = Path(__file__).resolve().parent / "cache" / "bond_indices"
CACHE_MAX_AGE_DAYS = 7

# Output key -> (ChinaBond index category, indicator, maturity segment)
INDEX_SPECS = {
    "中债国债总财富": ("国债总指数", "财富", "总值"),
    "中债中短期": ("国债总指数", "财富", "1-3年"),
    "中债长期": ("国债总指数", "财富", "7-10年"),
    "中债企业债AAA": ("企业债AAA指数", "财富", "总值"),
    "中债国开债": ("国开行债券总指数", "财富", "总值"),
    "中债高收益企业债": ("高收益企业债指数", "财富", "总值"),
}


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{name}.parquet"


def _cache_is_fresh(path: Path, max_age_days: int) -> bool:
    if not path.exists():
        return False
    age_days = (datetime.now().timestamp() - path.stat().st_mtime) / 86400
    return age_days < max_age_days


def _fetch_index_nav(
    name: str,
    index_category: str,
    indicator: str,
    period: str,
    max_age_days: int = CACHE_MAX_AGE_DAYS,
) -> pd.Series:
    """Fetch one ChinaBond wealth index and return its daily level series."""
    if ak is None:
        raise ImportError("akshare is required to fetch ChinaBond indices")

    path = _cache_path(name)
    if _cache_is_fresh(path, max_age_days):
        df = pd.read_parquet(path)
    else:
        df = ak.bond_index_general_cbond(
            index_category=index_category,
            indicator=indicator,
            period=period,
        )
        required = {"date", "value"}
        if not required.issubset(df.columns):
            raise ValueError(
                f"{name}: expected AKShare columns {sorted(required)}, "
                f"got {list(df.columns)}"
            )
        df = df.loc[:, ["date", "value"]].copy()
        df.to_parquet(path, index=False)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).drop_duplicates("date", keep="last")
    series = df.set_index("date")["value"].sort_index()
    series.name = name
    if series.empty:
        raise ValueError(f"{name}: AKShare returned no usable observations")
    return series


def bond_index_weekly_returns() -> dict[str, pd.Series]:
    """Return available ChinaBond factor proxies as Friday weekly returns.

    Keys exactly match ``campisi.build_factors``. A failed or unavailable index
    is skipped so the caller can construct the subset of supported factors.
    """
    result: dict[str, pd.Series] = {}
    for name, (category, indicator, period) in INDEX_SPECS.items():
        try:
            nav = _fetch_index_nav(name, category, indicator, period)
            weekly = nav.resample("W-FRI").last().pct_change().dropna()
            if not weekly.empty:
                result[name] = weekly.rename(name)
        except Exception as exc:  # Keep partial factor availability.
            print(f"[warn] {name} unavailable: {type(exc).__name__}: {exc}")
    return result


def _fund_nav(fund_code: str) -> pd.Series:
    """Fetch a fund cumulative-NAV series for the standalone verification."""
    if ak is None:
        raise ImportError("akshare is required for end-to-end verification")
    df = ak.fund_open_fund_info_em(
        symbol=fund_code,
        indicator="累计净值走势",
    )
    required = {"净值日期", "累计净值"}
    if not required.issubset(df.columns):
        raise ValueError(
            f"fund {fund_code}: expected columns {sorted(required)}, "
            f"got {list(df.columns)}"
        )
    dates = pd.to_datetime(df["净值日期"], errors="coerce")
    values = pd.to_numeric(df["累计净值"], errors="coerce")
    nav = pd.Series(values.to_numpy(), index=dates, name=fund_code).dropna()
    return nav[~nav.index.duplicated(keep="last")].sort_index()


def _main() -> None:
    import campisi

    weekly = bond_index_weekly_returns()
    print("== ChinaBond weekly returns ==")
    for name, series in weekly.items():
        print(
            f"{name}: {series.index.min().date()} -> "
            f"{series.index.max().date()}, rows={len(series)}"
        )

    factors = campisi.build_factors(weekly)
    print(f"\nCampisi factors: {list(factors.columns)} ({len(factors.columns)})")

    fund_code = os.environ.get("CAMPISI_VERIFY_FUND", "000186")
    fund_weekly = campisi.nav_to_weekly(_fund_nav(fund_code))
    result = campisi.campisi_regress(fund_weekly, factors)
    print(f"\nFund {fund_code} end-to-end verification")
    print(
        f"n={result['n']}, R2={result['r2']:.4f}, "
        f"alpha_ann={result['alpha_ann']:.4%}, "
        f"confidence={result['confidence']}"
    )
    print(f"betas={result['betas']}")


if __name__ == "__main__":
    _main()
