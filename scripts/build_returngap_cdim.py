"""批量计算权益基金半年频 ReturnGap 并增量写入 data/cdim_data.csv。

严格只使用半年报/年报(Q2/Q4)全持仓；Q1/Q3 前十大不参与。

用法:
  python build_returngap_cdim.py --limit 30
  python build_returngap_cdim.py --start-year 2023 --end-year 2025
  python build_returngap_cdim.py --refresh
"""
import argparse
import os
import re
from datetime import date

import numpy as np
import pandas as pd

import data_akshare as da

CDIM_CSV = os.path.join("data", "cdim_data.csv")
MIN_HOLDINGS_COVERAGE = 0.70
MIN_VALID_PERIODS = 2


def _report_date(label: str) -> pd.Timestamp | None:
    match = re.search(r"(\d{4})年([24])季度", str(label))
    if not match:
        return None
    year, quarter = int(match.group(1)), int(match.group(2))
    return pd.Timestamp(year=year, month=6 if quarter == 2 else 12,
                        day=30 if quarter == 2 else 31)


def _is_a_share(code: str) -> bool:
    raw = str(code).strip()
    return len(raw) == 6 and raw.isdigit() and raw[0] in "034689"


def _sina_symbol(stock_code: str) -> str:
    if stock_code.startswith(("4", "8")):
        return f"bj{stock_code}"
    if stock_code.startswith(("5", "6", "9")):
        return f"sh{stock_code}"
    return f"sz{stock_code}"


def fund_full_holdings(fund_code: str, year: int) -> pd.DataFrame:
    """返回指定年份 Q2/Q4 全持仓，列 report_date/stock_code/weight。"""
    def fetch():
        raw = da.ak.fund_portfolio_hold_em(symbol=fund_code, date=str(year))
        required = {"股票代码", "占净值比例", "季度"}
        if raw.empty or not required.issubset(raw.columns):
            return pd.DataFrame(columns=["report_date", "stock_code", "weight"])
        out = pd.DataFrame({
            "report_date": raw["季度"].map(_report_date),
            "stock_code": raw["股票代码"].astype(str).str.strip(),
            "weight": pd.to_numeric(raw["占净值比例"], errors="coerce") / 100,
        })
        out = out.dropna(subset=["report_date", "stock_code", "weight"])
        out = out[out["weight"] > 0]
        return (out.groupby(["report_date", "stock_code"], as_index=False)["weight"]
                .sum())

    return da.cached(f"returngap_hold_{fund_code}_{year}", fetch, max_age_days=30)


def stock_adjusted_close(stock_code: str, start_date: pd.Timestamp,
                         end_date: pd.Timestamp) -> pd.Series:
    """A股前复权收盘价；新浪失败时降级东财，每只股票长期缓存一次。"""
    def fetch():
        try:
            raw = da.ak.stock_zh_a_daily(
                symbol=_sina_symbol(stock_code),
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if raw.empty or not {"date", "close"}.issubset(raw.columns):
                raise ValueError("sina empty")
            out = raw[["date", "close"]].copy()
        except Exception:
            raw = da.ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if raw.empty or not {"日期", "收盘"}.issubset(raw.columns):
                return pd.DataFrame(columns=["date", "close"])
            out = raw.rename(columns={"日期": "date", "收盘": "close"})[
                ["date", "close"]].copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out["close"] = pd.to_numeric(out["close"], errors="coerce")
        return out.dropna().sort_values("date").drop_duplicates("date", keep="last")

    frame = da.cached(f"returngap_stock_{stock_code}", fetch, max_age_days=30)
    if frame.empty:
        return pd.Series(dtype=float)
    frame = frame[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna().set_index("date")["close"].sort_index()


def period_return(values: pd.Series, start: pd.Timestamp,
                  end: pd.Timestamp) -> float:
    """报告日后首个可得值至下个报告日最后可得值的区间收益。"""
    clean = pd.to_numeric(values, errors="coerce").dropna().sort_index()
    if clean.empty:
        return np.nan
    if not isinstance(clean.index, pd.DatetimeIndex):
        clean.index = pd.to_datetime(clean.index, errors="coerce")
        clean = clean[~clean.index.isna()]
    window = clean[(clean.index >= start) & (clean.index <= end)]
    if len(window) < 2 or window.iloc[0] <= 0:
        return np.nan
    return float(window.iloc[-1] / window.iloc[0] - 1)


def compute_return_gap(nav: pd.Series, snapshots: dict[pd.Timestamp, pd.DataFrame],
                       stock_prices: dict[str, pd.Series],
                       min_coverage: float = MIN_HOLDINGS_COVERAGE,
                       max_periods: int = 4) -> tuple[dict, list[dict]]:
    """计算单基金 ReturnGap 聚合值和逐期审计记录。"""
    dates = sorted(snapshots)[-(max_periods + 1):]
    records = []
    for start, end in zip(dates, dates[1:]):
        holdings = snapshots[start]
        total_weight = pd.to_numeric(holdings["weight"], errors="coerce").sum()
        available = []
        for row in holdings.itertuples(index=False):
            stock_ret = period_return(
                stock_prices.get(str(row.stock_code), pd.Series(dtype=float)),
                start, end)
            if np.isfinite(stock_ret):
                available.append((float(row.weight), stock_ret))
        available_weight = sum(weight for weight, _ in available)
        coverage = available_weight / total_weight if total_weight > 0 else 0.0
        actual = period_return(nav, start, end)
        hypothetical = (
            sum(weight * stock_ret for weight, stock_ret in available)
            / available_weight
            if available_weight > 0 else np.nan
        )
        valid = (
            coverage >= min_coverage
            and np.isfinite(actual)
            and np.isfinite(hypothetical)
        )
        records.append({
            "start": start,
            "end": end,
            "actual_return": actual,
            "hypothetical_return": hypothetical,
            "return_gap": actual - hypothetical if valid else np.nan,
            "holdings_coverage": coverage,
            "valid": valid,
        })

    valid_rows = [row for row in records if row["valid"]]
    if not records:
        return {}, records
    result = {
        "return_gap": (float(np.mean([row["return_gap"] for row in valid_rows]))
                       if valid_rows else np.nan),
        "return_gap_n_periods": len(valid_rows),
        "holdings_coverage": (float(np.mean(
            [row["holdings_coverage"] for row in valid_rows]))
            if valid_rows else np.nan),
        "return_gap_actual_mean": (float(np.mean(
            [row["actual_return"] for row in valid_rows]))
            if valid_rows else np.nan),
        "return_gap_hypothetical_mean": (float(np.mean(
            [row["hypothetical_return"] for row in valid_rows]))
            if valid_rows else np.nan),
        "return_gap_invalid_periods": len(records) - len(valid_rows),
    }
    return result, records


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
    base = existing.set_index("fund_code").reindex(
        existing.set_index("fund_code").index.union(fresh.index))
    for column in fresh.columns:
        base.loc[fresh.index, column] = fresh[column]
    out = base.reset_index()
    out.to_csv(CDIM_CSV, index=False, encoding="utf-8-sig")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-year", type=int, default=date.today().year - 3)
    parser.add_argument("--end-year", type=int, default=date.today().year - 1)
    parser.add_argument("--max-periods", type=int, default=4)
    parser.add_argument("--checkpoint", type=int, default=10)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    universe = da.active_equity_universe()
    if args.limit:
        universe = universe.head(args.limit)
    existing = _load_existing()
    completed = set()
    if not args.refresh and "return_gap_n_periods" in existing:
        completed = set(existing.loc[
            existing["return_gap_n_periods"].notna(), "fund_code"])
    todo = universe[~universe["fund_code"].isin(completed)]
    print(f"目标 {len(universe)} | 已完成 {len(universe)-len(todo)} | 待计算 {len(todo)}")

    holdings_by_fund = {}
    stock_codes = set()
    holdings_fail = 0
    for i, code in enumerate(todo["fund_code"], start=1):
        frames = []
        try:
            for year in range(args.start_year, args.end_year + 1):
                frame = fund_full_holdings(code, year)
                if not frame.empty:
                    frames.append(frame)
        except Exception as e:  # noqa: BLE001
            holdings_fail += 1
            print(f"[warn] {code} holdings failed: {e}")
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            snapshots = {
                pd.Timestamp(report_date): group[["stock_code", "weight"]].copy()
                for report_date, group in combined.groupby("report_date")
            }
            keep_dates = sorted(snapshots)[-(args.max_periods + 1):]
            snapshots = {report_date: snapshots[report_date]
                         for report_date in keep_dates}
            holdings_by_fund[code] = snapshots
            for frame in snapshots.values():
                stock_codes.update(
                    code for code in frame["stock_code"] if _is_a_share(code))
        if i % 25 == 0:
            print(f"  holdings {i}/{len(todo)} | funds={len(holdings_by_fund)}")

    start = pd.Timestamp(args.start_year, 1, 1)
    end = pd.Timestamp(args.end_year + 1, 1, 31)
    stock_prices = {}
    stock_fail = 0
    for i, code in enumerate(sorted(stock_codes), start=1):
        try:
            prices = stock_adjusted_close(code, start, end)
            if not prices.empty:
                stock_prices[code] = prices
            else:
                stock_fail += 1
        except Exception:  # noqa: BLE001
            stock_fail += 1
        if i % 100 == 0:
            print(f"  stocks {i}/{len(stock_codes)} | usable={len(stock_prices)}")

    updates = []
    invalid_periods = 0
    audit_samples = []
    for i, code in enumerate(todo["fund_code"], start=1):
        snapshots = holdings_by_fund.get(code, {})
        if len(snapshots) >= 2:
            try:
                result, records = compute_return_gap(
                    da.fund_nav(code), snapshots, stock_prices,
                    max_periods=args.max_periods)
                if result:
                    updates.append({"fund_code": code, **result})
                    invalid_periods += result["return_gap_invalid_periods"]
                    audit_samples.extend(
                        [{"fund_code": code, **row} for row in records if row["valid"]])
            except Exception as e:  # noqa: BLE001
                print(f"[warn] {code} ReturnGap failed: {e}")
        if i % args.checkpoint == 0:
            existing = _save(existing, updates)
            updates = []
            print(f"  ReturnGap {i}/{len(todo)}")
    existing = _save(existing, updates)

    selected = existing[existing["fund_code"].isin(universe["fund_code"])]
    periods = pd.to_numeric(selected.get("return_gap_n_periods"), errors="coerce")
    coverage = pd.to_numeric(selected.get("holdings_coverage"), errors="coerce")
    gap = pd.to_numeric(selected.get("return_gap"), errors="coerce")
    reliable = (periods >= MIN_VALID_PERIODS) & (coverage >= MIN_HOLDINGS_COVERAGE)
    print(f"完成: 全持仓可得 {len(holdings_by_fund)}/{len(todo)} | "
          f"股票行情 {len(stock_prices)}/{len(stock_codes)} | "
          f"C3有效 {reliable.sum()}/{len(universe)} ({reliable.mean():.1%})")
    if reliable.any():
        valid_gap = gap[reliable]
        print(f"ReturnGap min/median/max: {valid_gap.min():.2%}/"
              f"{valid_gap.median():.2%}/{valid_gap.max():.2%} | "
              f"作废期数 {invalid_periods}")
    if audit_samples:
        print("逐期样例:")
        sample = pd.DataFrame(audit_samples).head(5)
        print(sample[["fund_code", "start", "end", "actual_return",
                      "hypothetical_return", "return_gap",
                      "holdings_coverage"]].to_string(index=False))
    if holdings_fail or stock_fail:
        print(f"失败: holdings={holdings_fail}, stock={stock_fail}")


if __name__ == "__main__":
    main()
