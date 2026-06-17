"""BOND_INDEX Phase B: load fund-index mapping and index return series.

index_mainstream is a manual prior in [0, 1] and must be recalibrated later.
Missing index_code rows are intentional: the scorecard will stay provisional.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import data_akshare as da


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP_PATH = REPO_ROOT / "data" / "index_map_bond.csv"


def load_index_map(path: str | Path = DEFAULT_MAP_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["fund_code", "index_code", "index_name", "index_mainstream"])
    df = pd.read_csv(path, dtype={"fund_code": str, "index_code": str})
    for col in ("fund_code", "index_code", "index_name", "index_mainstream"):
        if col not in df.columns:
            df[col] = pd.NA
    df["fund_code"] = df["fund_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    df["index_code"] = df["index_code"].fillna("").astype(str).str.strip()
    df.loc[df["index_code"].isin(["", "nan", "None", "<NA>"]), "index_code"] = pd.NA
    df["index_mainstream"] = pd.to_numeric(df["index_mainstream"], errors="coerce")
    return df[["fund_code", "index_code", "index_name", "index_mainstream"]].drop_duplicates(
        "fund_code", keep="first")


def merge_index_map(df: pd.DataFrame, index_map: pd.DataFrame | None = None) -> pd.DataFrame:
    """Merge mapping columns while preserving values already present in df."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    out = df.copy()
    out["fund_code"] = out["fund_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    mapping = load_index_map() if index_map is None else index_map.copy()
    if mapping.empty:
        return out
    merged = out.merge(mapping, on="fund_code", how="left", suffixes=("", "_map"))
    for col in ("index_code", "index_name", "index_mainstream"):
        map_col = f"{col}_map"
        if map_col not in merged.columns:
            continue
        if col in out.columns:
            merged[col] = merged[col].combine_first(merged[map_col])
        else:
            merged[col] = merged[map_col]
        merged = merged.drop(columns=[map_col])
    return merged


def build_index_ret_map(index_map: pd.DataFrame | None = None) -> dict[str, pd.Series]:
    """Fetch unique mapped index return series; failures are logged and skipped."""
    mapping = load_index_map() if index_map is None else index_map
    if mapping is None or mapping.empty or "index_code" not in mapping.columns:
        return {}
    out: dict[str, pd.Series] = {}
    codes = sorted({str(c).strip() for c in mapping["index_code"].dropna() if str(c).strip()})
    for code in codes:
        try:
            out[code] = da.index_returns(code)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] BOND_INDEX index {code} failed: {e}")
    return out


if __name__ == "__main__":
    m = load_index_map()
    r = build_index_ret_map(m)
    print(f"index_map rows={len(m)} mapped={m['index_code'].notna().sum()} returns={len(r)}")
