"""批量计算权益基金 RBSA 风格稳定性并增量写入 data/cdim_data.csv。

用法:
  python build_style_cdim.py --limit 50
  python build_style_cdim.py                 # 全量，可中断续跑
  python build_style_cdim.py --refresh       # 重算已有 RBSA 行
"""
import argparse
import os

import numpy as np
import pandas as pd

import data_akshare as da
import rbsa

CDIM_CSV = os.path.join("data", "cdim_data.csv")
STYLE_COLUMNS = [
    "style_stability", "style_switches_2y", "rbsa_r2",
    "style_large_value", "style_large_growth",
    "style_small_value", "style_small_growth",
]


def compute_style_metrics(nav: pd.Series, style_rets: pd.DataFrame) -> dict:
    """单基金 RBSA 指标，数据不足时返回空字典。"""
    fund_ret = pd.to_numeric(nav, errors="coerce").sort_index().pct_change().dropna()
    rolling = rbsa.rolling_rbsa(fund_ret, style_rets)
    if rolling.empty:
        return {}
    stability = rbsa.style_stability(rolling)
    full = rbsa.rbsa(fund_ret, style_rets)
    if not np.isfinite(stability["stability"]) or not np.isfinite(full["r2"]):
        return {}
    latest = rolling.iloc[-1]
    result = {
        "style_stability": stability["stability"],
        "style_switches_2y": stability["switches_2y"],
        "rbsa_r2": full["r2"],
    }
    for style in rbsa.DEFAULT_STYLE_BASIS:
        result[f"style_{style}"] = latest.get(style, np.nan)
    return result


def _load_existing() -> pd.DataFrame:
    if not os.path.exists(CDIM_CSV):
        return pd.DataFrame(columns=["fund_code"])
    out = pd.read_csv(CDIM_CSV, dtype={"fund_code": str})
    out["fund_code"] = out["fund_code"].astype(str).str.zfill(6)
    return out.drop_duplicates("fund_code", keep="last")


def _save(existing: pd.DataFrame, updates: list[dict]) -> pd.DataFrame:
    if not updates:
        return existing
    fresh = pd.DataFrame(updates).set_index("fund_code")
    base = existing.set_index("fund_code")
    base = base.reindex(base.index.union(fresh.index))
    for col in fresh.columns:
        base.loc[fresh.index, col] = fresh[col]
    base = base.reset_index()
    base.to_csv(CDIM_CSV, index=False, encoding="utf-8-sig")
    return base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="调试时限制基金数")
    parser.add_argument("--refresh", action="store_true", help="重算已有 RBSA 数据")
    parser.add_argument("--checkpoint", type=int, default=25, help="每 N 只落盘")
    parser.add_argument(
        "--enhanced", action="store_true", help="改为补算指数增强 universe")
    parser.add_argument("--family", default=None, help="仅补指定指增指数族")
    args = parser.parse_args()

    styles = da.style_index_returns()
    print(f"风格指数: {styles.index.min().date()} -> {styles.index.max().date()}, "
          f"{len(styles)} 个共同交易日")
    if args.enhanced:
        import data_index_equity as die

        _, _, universe = die.classify_universe()
        parsed = universe["fund_name"].map(
            lambda name: die.parse_index_name(name, enhanced=True))
        universe["index_family"] = parsed.map(lambda item: item["index_family"])
        if args.family:
            universe = universe[universe["index_family"] == args.family]
    else:
        universe = da.active_equity_universe()
    if args.limit:
        universe = universe.head(args.limit)
    existing = _load_existing()
    completed = set()
    if not args.refresh and "style_stability" in existing:
        completed = set(existing.loc[existing["style_stability"].notna(), "fund_code"])
    todo = universe[~universe["fund_code"].isin(completed)]
    print(f"目标 {len(universe)} | 已完成 {len(universe)-len(todo)} | 待计算 {len(todo)}")

    updates = []
    failed = 0
    too_short = 0
    for i, row in enumerate(todo.itertuples(index=False), start=1):
        code = row.fund_code
        try:
            metrics = compute_style_metrics(da.fund_nav(code), styles)
            if not metrics:
                too_short += 1
                continue
            updates.append({"fund_code": code, **metrics})
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[warn] {code} RBSA failed: {e}")
        if i % args.checkpoint == 0:
            existing = _save(existing, updates)
            updates = []
            print(f"  RBSA {i}/{len(todo)} | failed={failed} | too_short={too_short}")
    existing = _save(existing, updates)

    selected = existing[existing["fund_code"].isin(universe["fund_code"])]
    valid = selected.get("style_stability", pd.Series(dtype=float)).dropna()
    n7 = (pd.to_numeric(selected.get("style_switches_2y"), errors="coerce") > 2).sum()
    print(f"完成: C2覆盖 {len(valid)}/{len(universe)} ({len(valid)/max(len(universe), 1):.1%}) | "
          f"失败 {failed} | 历史不足 {too_short} | N7候选 {n7}")


if __name__ == "__main__":
    main()
